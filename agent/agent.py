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
    
    # 反思 (Reflection)
    reflection: Optional[Dict]  # 反思结果
    reflection_count: int  # 反思次数


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

REFLECTOR_PROMPT = """你是一个诊断质量评审专家。请反思当前的诊断过程，评估诊断质量并提出改进建议。

## 原始问题
{problem}

## 诊断计划
{plan_summary}

## 执行步骤和结果
{execution_summary}

## 当前发现
{findings}

## 当前根因判断
{root_cause}

请从以下维度反思：
1. **完整性**：诊断是否覆盖了所有可能的故障点？是否遗漏了关键检查？
2. **准确性**：根因判断是否正确？是否有足够证据支撑？
3. **深度**：是否需要进一步深入调查？
4. **效率**：诊断步骤是否合理？有无冗余?

输出JSON：
```json
{{
  "quality_score": 8,
  "completeness": "完整性评估",
  "accuracy": "准确性评估", 
  "suggestions": ["建议1", "建议2"],
  "should_improve": true,
  "improvement_focus": "需要改进的方向描述"
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
        workflow.add_node("reflector", self._reflect_node)  # 新增反思节点
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
                "conclude": "reflector",  # 改为先反思
                "max_reached": "reflector"
            }
        )
        
        workflow.add_edge("executor", "analyzer")
        
        # 反思后决定是否需要改进
        workflow.add_conditional_edges(
            "reflector",
            self._should_improve,
            {
                "improve": "planner",   # 需要改进则重新规划
                "accept": "reporter"    # 接受则生成报告
            }
        )
        
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
    
    async def _reflect_node(self, state: AgentState) -> Dict:
        """反思节点：评估诊断质量并决定是否需要改进"""
        # 构建计划摘要
        plan_summary = "\n".join([
            f"{i+1}. {s.tool}: {s.reason}" 
            for i, s in enumerate(state.get("plan", []))
        ]) or "无计划"
        
        # 构建执行摘要
        execution_summary = "\n".join([
            f"- {s.tool}: {s.result[:200] if s.result else '无结果'}..."
            for s in state.get("plan", []) if s.status == "completed"
        ]) or "无执行记录"
        
        findings = "\n".join(state.get("findings", [])) or "无发现"
        root_cause = state.get("root_cause", "未确定")
        
        prompt = REFLECTOR_PROMPT.format(
            problem=state["problem"],
            plan_summary=plan_summary,
            execution_summary=execution_summary,
            findings=findings,
            root_cause=root_cause
        )
        
        response = await self.llm.ainvoke([HumanMessage(content=prompt)])
        
        # 解析反思结果
        reflection = self._parse_reflection(response.content)
        
        logger.info(f"反思评分: {reflection.get('quality_score', 'N/A')}, "
                   f"需要改进: {reflection.get('should_improve', False)}")
        
        return {
            "reflection": reflection,
            "reflection_count": state.get("reflection_count", 0) + 1,
            "messages": [response]
        }
    
    def _should_improve(self, state: AgentState) -> str:
        """决定是否需要根据反思结果改进"""
        reflection = state.get("reflection", {})
        reflection_count = state.get("reflection_count", 0)
        
        # 最多反思2次，避免无限循环
        if reflection_count >= 2:
            logger.info("达到最大反思次数，接受当前结果")
            return "accept"
        
        # 质量评分低于6分且建议改进
        quality_score = reflection.get("quality_score", 10)
        should_improve = reflection.get("should_improve", False)
        
        if quality_score < 6 and should_improve:
            logger.info(f"质量评分 {quality_score} 较低，尝试改进")
            return "improve"
        
        return "accept"
    
    def _parse_reflection(self, content: str) -> Dict:
        """解析反思结果"""
        import json
        import re
        
        json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
        if json_match:
            content = json_match.group(1)
        
        try:
            return json.loads(content)
        except:
            return {
                "quality_score": 7,
                "should_improve": False,
                "suggestions": []
            }
    
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
            "max_iterations": self.config.get("agent", {}).get("max_iterations", 10),
            "reflection": None,
            "reflection_count": 0
        }
        
        # 运行图
        final_state = await self.graph.ainvoke(initial_state)
        
        return final_state.get("final_report", "诊断失败")
    
    def get_available_environments(self) -> List[Dict]:
        """获取可用环境列表"""
        return self.env_manager.get_env_info_for_display()
