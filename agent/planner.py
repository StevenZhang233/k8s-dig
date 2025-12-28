"""
Planner组件 - 负责生成诊断计划
"""
import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class DiagnosticStep(BaseModel):
    """诊断步骤"""
    step_id: int
    action: str = Field(description="要执行的动作/工具名称")
    params: Dict[str, Any] = Field(default_factory=dict, description="工具参数")
    reason: str = Field(description="执行此步骤的原因")
    expected_outcome: str = Field(description="预期结果")
    depends_on: Optional[int] = Field(default=None, description="依赖的步骤ID")


class DiagnosticPlan(BaseModel):
    """诊断计划"""
    problem_description: str = Field(description="问题描述")
    initial_hypothesis: str = Field(description="初步假设")
    steps: List[DiagnosticStep] = Field(description="诊断步骤列表")
    

PLANNER_SYSTEM_PROMPT = """你是一个专业的K8s集群诊断专家。你的任务是根据用户描述的问题，制定一个详细的诊断计划。

## 你可以使用的诊断工具

### 查询类（只读，安全）
- `list_pods`: 列出namespace下所有Pod - 用于发现问题Pod
- `describe_pod`: 获取Pod详情 - 查看Pod状态、容器状态、事件
- `get_events`: 获取K8s事件 - 查看调度失败、拉镜像失败等事件
- `list_jobs`: 列出所有Job - 用于查看DBSql等批处理任务
- `describe_job`: 获取Job详情
- `get_configmap`: 获取ConfigMap配置
- `get_deployment`: 获取Deployment详情

### 日志类（只读，安全）
- `get_pod_logs`: 获取Pod日志 - 查看应用错误
- `get_previous_logs`: 获取崩溃前日志 - 排查CrashLoopBackOff
- `get_job_logs`: 获取Job执行日志

### 调试类（受限）
- `exec_in_pod`: 在Pod内执行诊断命令 - 仅限env, ps, cat, ls, df, netstat等

### 操作类（需确认）
- `restart_pod`: 重启Pod - 删除Pod触发重建

## 诊断策略

针对常见问题的诊断路径：

1. **CrashLoopBackOff**
   - 获取Pod日志 (get_pod_logs)
   - 获取崩溃前日志 (get_previous_logs)
   - 查看Pod详情 (describe_pod)

2. **Pending状态**
   - 查看Pod详情 (describe_pod)
   - 获取事件 (get_events) - 检查调度失败原因
   
3. **ImagePullBackOff**
   - 查看Pod详情 (describe_pod) - 查看镜像名称
   - 获取事件 (get_events) - 查看拉取失败原因

4. **Job失败（如DBSql任务）**
   - 获取Job详情 (describe_job)
   - 获取Job日志 (get_job_logs)
   - 获取事件 (get_events)

5. **连接失败（如数据库连接超时）**
   - 在Pod内检查网络 (exec_in_pod: ping, nslookup)
   - 检查环境变量 (exec_in_pod: env)
   - 检查目标服务Pod状态 (list_pods)

## 输出格式

请以JSON格式输出诊断计划：
```json
{
  "problem_description": "问题的简要描述",
  "initial_hypothesis": "根据问题描述的初步假设",
  "steps": [
    {
      "step_id": 1,
      "action": "工具名称",
      "params": {"namespace": "xxx", ...},
      "reason": "执行此步骤的原因",
      "expected_outcome": "预期能获得什么信息",
      "depends_on": null
    }
  ]
}
```

## 注意事项

1. 先从宏观的查询开始（如list_pods），再深入具体资源
2. 根据上一步的结果动态调整后续步骤（这会在re-plan时处理）
3. 保持步骤简洁，每步只做一件事
4. 明确说明每步的预期结果
"""


class Planner:
    """诊断计划生成器"""
    
    def __init__(self, llm_client, config: dict):
        """
        初始化Planner
        
        Args:
            llm_client: LLM客户端（OpenAI兼容）
            config: 应用配置
        """
        self.llm = llm_client
        self.config = config
        self.model = config.get("llm", {}).get("model", "gpt-4o")
    
    async def create_plan(
        self, 
        problem: str,
        context: Optional[Dict[str, Any]] = None
    ) -> DiagnosticPlan:
        """
        根据问题描述生成诊断计划
        
        Args:
            problem: 用户描述的问题
            context: 可选的上下文信息（如产品信息、namespace等）
            
        Returns:
            DiagnosticPlan对象
        """
        user_message = f"问题描述：{problem}"
        
        if context:
            user_message += f"\n\n上下文信息：{context}"
        
        response = await self._call_llm(
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_message=user_message
        )
        
        # 解析LLM响应
        plan = self._parse_plan_response(response)
        
        logger.info(f"生成诊断计划: {len(plan.steps)}个步骤")
        
        return plan
    
    async def replan(
        self,
        original_plan: DiagnosticPlan,
        executed_steps: List[Dict[str, Any]],
        new_findings: str
    ) -> DiagnosticPlan:
        """
        根据新发现重新规划
        
        Args:
            original_plan: 原始计划
            executed_steps: 已执行的步骤及结果
            new_findings: 新发现的信息
            
        Returns:
            更新后的DiagnosticPlan
        """
        replan_prompt = f"""
原始问题：{original_plan.problem_description}
原始假设：{original_plan.initial_hypothesis}

已执行的步骤：
{self._format_executed_steps(executed_steps)}

新发现：
{new_findings}

请根据新发现，更新诊断计划。如果已经找到根因，可以给出结论步骤。
"""
        
        response = await self._call_llm(
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_message=replan_prompt
        )
        
        return self._parse_plan_response(response)
    
    async def _call_llm(self, system_prompt: str, user_message: str) -> str:
        """调用LLM"""
        response = self.llm.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        
        return response.choices[0].message.content
    
    def _parse_plan_response(self, response: str) -> DiagnosticPlan:
        """解析LLM响应为DiagnosticPlan"""
        import json
        
        try:
            data = json.loads(response)
            return DiagnosticPlan(**data)
        except Exception as e:
            logger.error(f"解析计划失败: {e}")
            # 返回一个默认计划
            return DiagnosticPlan(
                problem_description="解析失败",
                initial_hypothesis="无法解析LLM响应",
                steps=[]
            )
    
    def _format_executed_steps(self, steps: List[Dict[str, Any]]) -> str:
        """格式化已执行的步骤"""
        formatted = []
        for step in steps:
            formatted.append(f"步骤{step['step_id']}: {step['action']}")
            formatted.append(f"  参数: {step['params']}")
            formatted.append(f"  结果: {step.get('result', 'N/A')[:500]}")
            formatted.append("")
        return "\n".join(formatted)
