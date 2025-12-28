"""
LangGraph版本的K8s诊断Agent
使用Plan-Execute模式实现自主诊断
"""
import logging
import operator
from typing import Annotated, Any, Dict, List, Optional, TypedDict, Union

import yaml
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field

from .environment import EnvironmentManager
from .tools import create_k8s_tools

logger = logging.getLogger(__name__)


# ==================== 状态定义 ====================

class DiagnosticStep(BaseModel):
    """诊断步骤"""
    step_id: int
    tool: str
    args: Dict[str, Any]
    reason: str
    status: str = "pending"  # pending, running, completed, failed
    result: Optional[str] = None


class AgentState(TypedDict):
    """Agent状态"""
    # 用户输入
    problem: str
    environment: str
    
    # 诊断计划
    plan: List[DiagnosticStep]
    current_step: int
    
    # 执行历史
    messages: Annotated[List[BaseMessage], operator.add]
    findings: List[str]
    
    # 结论
    root_cause: Optional[str]
    recommendations: List[str]
    final_report: Optional[str]
    
    # 控制
    should_replan: bool
    iteration: int
    max_iterations: int


# ==================== Prompt 模板 ====================

PLANNER_PROMPT = """你是一个K8s诊断专家。根据用户描述的问题，制定诊断计划。

## 可用工具
{tools_description}

## 问题描述
{problem}

## 当前环境
{environment}

## 已有发现（如果有）
{findings}

请输出JSON格式的诊断计划：
```json
{{
  "hypothesis": "初步假设",
  "steps": [
    {{"step_id": 1, "tool": "工具名", "args": {{"namespace": "xxx"}}, "reason": "原因"}}
  ]
}}
```
"""

ANALYZER_PROMPT = """分析诊断命令的执行结果。

## 执行的操作
工具: {tool}
参数: {args}

## 执行结果
{result}

## 之前的发现
{findings}

请判断：
1. 从结果中发现了什么？
2. 是否找到了根因？
3. 下一步应该：continue（继续）/ replan（重新规划）/ conclude（得出结论）

输出JSON：
```json
{{
  "finding": "发现内容",
  "root_cause": "根因（如果找到）或null",
  "next_action": "continue/replan/conclude",
  "confidence": 0.8
}}
```
"""


# ==================== LangGraph Agent ====================

class K8sDiagnosticAgent:
    """基于LangGraph的K8s诊断Agent"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        self.env_manager = EnvironmentManager(config_path)
        self.llm = self._init_llm()
        self.tools = []
        self.graph = None
    
    def _load_config(self, config_path: str) -> dict:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _init_llm(self) -> ChatOpenAI:
        """初始化LLM"""
        import os
        from dotenv import load_dotenv
        load_dotenv()
        
        llm_config = self.config.get("llm", {})
        provider = llm_config.get("provider", "openai")
        
        if provider == "google_genai":
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(
                model=llm_config.get("model", "gemini-1.5-pro"),
                temperature=llm_config.get("temperature", 0.1),
                google_api_key=os.getenv("GOOGLE_API_KEY"),
                convert_system_message_to_human=True
            )
        elif provider == "azure":
            # 现有的Azure逻辑(如果需要)或者保留原来的OpenAI逻辑作为默认
            from langchain_openai import AzureChatOpenAI
            return AzureChatOpenAI(
                azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                openai_api_version="2024-02-15-preview",
                temperature=llm_config.get("temperature", 0.1)
            )
        else:
            # 默认为OpenAI
            return ChatOpenAI(
                model=llm_config.get("model", "gpt-4o"),
                temperature=llm_config.get("temperature", 0.1),
                api_key=os.getenv("OPENAI_API_KEY")
            )
    
    def initialize(self, environment: Optional[str] = None):
        """
        初始化Agent
        
        Args:
            environment: 目标环境名称
        """
        # 切换环境
        if environment:
            self.env_manager.switch_environment(environment)
        
        # 创建工具
        self.tools = create_k8s_tools(self.env_manager, self.config)
        
        # 构建图
        self.graph = self._build_graph()
        
        logger.info(f"Agent初始化完成，当前环境: {self.env_manager.current_env}")
    
    def _build_graph(self) -> StateGraph:
        """构建LangGraph状态机"""
        
        # 创建状态图
        workflow = StateGraph(AgentState)
        
        # 添加节点
        workflow.add_node("planner", self._plan_node)
        workflow.add_node("executor", self._execute_node)
        workflow.add_node("analyzer", self._analyze_node)
        workflow.add_node("reporter", self._report_node)
        
        # 设置入口
        workflow.set_entry_point("planner")
        
        # 添加边
        workflow.add_edge("planner", "executor")
        
        # 条件边：分析后决定下一步
        workflow.add_conditional_edges(
            "analyzer",
            self._should_continue,
            {
                "continue": "executor",
                "replan": "planner",
                "conclude": "reporter",
                "max_reached": "reporter"
            }
        )
        
        workflow.add_edge("executor", "analyzer")
        workflow.add_edge("reporter", END)
        
        return workflow.compile()
    
    async def _plan_node(self, state: AgentState) -> Dict:
        """规划节点：生成诊断计划"""
        # 构建工具描述
        tools_desc = "\n".join([
            f"- {t.name}: {t.description}" for t in self.tools
        ])
        
        findings = "\n".join(state.get("findings", [])) or "无"
        
        prompt = PLANNER_PROMPT.format(
            tools_description=tools_desc,
            problem=state["problem"],
            environment=state["environment"],
            findings=findings
        )
        
        response = await self.llm.ainvoke([HumanMessage(content=prompt)])
        
        # 解析计划
        plan = self._parse_plan(response.content)
        
        return {
            "plan": plan,
            "current_step": 0,
            "should_replan": False,
            "messages": [response]
        }
    
    async def _execute_node(self, state: AgentState) -> Dict:
        """执行节点：执行当前诊断步骤"""
        plan = state["plan"]
        current_step = state["current_step"]
        
        if current_step >= len(plan):
            return {"current_step": current_step}
        
        step = plan[current_step]
        
        # 查找工具
        tool = next((t for t in self.tools if t.name == step.tool), None)
        
        if not tool:
            result = f"错误：未找到工具 {step.tool}"
        else:
            try:
                result = await tool.ainvoke(step.args)
            except Exception as e:
                result = f"执行失败：{str(e)}"
        
        # 更新步骤结果
        step.status = "completed"
        step.result = result
        plan[current_step] = step
        
        return {
            "plan": plan,
            "messages": [AIMessage(content=f"执行 {step.tool}: {result[:500]}...")]
        }
    
    async def _analyze_node(self, state: AgentState) -> Dict:
        """分析节点：分析执行结果"""
        plan = state["plan"]
        current_step = state["current_step"]
        step = plan[current_step]
        
        findings = "\n".join(state.get("findings", [])) or "无"
        
        prompt = ANALYZER_PROMPT.format(
            tool=step.tool,
            args=step.args,
            result=step.result or "无结果",
            findings=findings
        )
        
        response = await self.llm.ainvoke([HumanMessage(content=prompt)])
        
        # 解析分析结果
        analysis = self._parse_analysis(response.content)
        
        new_findings = state.get("findings", []).copy()
        if analysis.get("finding"):
            new_findings.append(analysis["finding"])
        
        return {
            "current_step": current_step + 1,
            "findings": new_findings,
            "root_cause": analysis.get("root_cause"),
            "should_replan": analysis.get("next_action") == "replan",
            "iteration": state.get("iteration", 0) + 1,
            "messages": [response]
        }
    
    async def _report_node(self, state: AgentState) -> Dict:
        """报告节点：生成最终诊断报告"""
        findings = "\n".join([f"- {f}" for f in state.get("findings", [])])
        root_cause = state.get("root_cause", "未能确定根因")
        
        report = f"""# K8s诊断报告

## 问题描述
{state["problem"]}

## 诊断环境
{state["environment"]}

## 诊断发现
{findings}

## 根因分析
{root_cause}

## 建议措施
{self._generate_recommendations(state)}
"""
        
        return {"final_report": report}
    
    def _should_continue(self, state: AgentState) -> str:
        """决定下一步"""
        iteration = state.get("iteration", 0)
        max_iter = state.get("max_iterations", 10)
        
        if iteration >= max_iter:
            return "max_reached"
        
        if state.get("root_cause"):
            return "conclude"
        
        if state.get("should_replan"):
            return "replan"
        
        current_step = state.get("current_step", 0)
        plan = state.get("plan", [])
        
        if current_step >= len(plan):
            return "conclude"
        
        return "continue"
    
    def _parse_plan(self, content: str) -> List[DiagnosticStep]:
        """解析计划JSON"""
        import json
        import re
        
        # 提取JSON
        json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
        if json_match:
            content = json_match.group(1)
        
        try:
            data = json.loads(content)
            steps = []
            for s in data.get("steps", []):
                steps.append(DiagnosticStep(
                    step_id=s["step_id"],
                    tool=s["tool"],
                    args=s.get("args", {}),
                    reason=s.get("reason", "")
                ))
            return steps
        except Exception as e:
            logger.error(f"解析计划失败: {e}")
            return []
    
    def _parse_analysis(self, content: str) -> Dict:
        """解析分析结果"""
        import json
        import re
        
        json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
        if json_match:
            content = json_match.group(1)
        
        try:
            return json.loads(content)
        except:
            return {"finding": content, "next_action": "continue"}
    
    def _generate_recommendations(self, state: AgentState) -> str:
        """生成建议"""
        root_cause = state.get("root_cause", "")
        
        # 基于根因生成建议
        recommendations = []
        
        if "CrashLoopBackOff" in root_cause or "OOM" in root_cause:
            recommendations.append("- 检查应用内存配置，考虑增加资源限制")
            recommendations.append("- 检查应用日志，修复应用层错误")
        
        if "Pending" in root_cause or "资源不足" in root_cause:
            recommendations.append("- 扩容集群节点")
            recommendations.append("- 减少Pod的资源请求")
        
        if "连接" in root_cause or "timeout" in root_cause.lower():
            recommendations.append("- 检查网络策略")
            recommendations.append("- 验证目标服务是否正常运行")
        
        if not recommendations:
            recommendations.append("- 请根据以上诊断发现进行进一步排查")
        
        return "\n".join(recommendations)
    
    async def diagnose(
        self, 
        problem: str, 
        environment: Optional[str] = None
    ) -> str:
        """
        执行诊断
        
        Args:
            problem: 问题描述
            environment: 目标环境（可选）
            
        Returns:
            诊断报告
        """
        if environment:
            self.initialize(environment)
        elif not self.graph:
            self.initialize()
        
        initial_state: AgentState = {
            "problem": problem,
            "environment": self.env_manager.current_env or "default",
            "plan": [],
            "current_step": 0,
            "messages": [],
            "findings": [],
            "root_cause": None,
            "recommendations": [],
            "final_report": None,
            "should_replan": False,
            "iteration": 0,
            "max_iterations": self.config.get("agent", {}).get("max_iterations", 10)
        }
        
        # 运行图
        final_state = await self.graph.ainvoke(initial_state)
        
        return final_state.get("final_report", "诊断失败")
    
    def get_available_environments(self) -> List[Dict]:
        """获取可用环境列表"""
        return self.env_manager.get_env_info_for_display()
