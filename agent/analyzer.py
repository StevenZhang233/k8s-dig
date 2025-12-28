"""
Analyzer组件 - 负责分析执行结果
"""
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AnalysisResult(BaseModel):
    """分析结果"""
    summary: str = Field(description="结果摘要")
    findings: List[str] = Field(description="关键发现列表")
    root_cause: Optional[str] = Field(default=None, description="根因（如果找到）")
    confidence: float = Field(default=0.0, description="置信度 0-1")
    next_action: str = Field(description="建议的下一步动作: continue/replan/conclude")
    recommendations: List[str] = Field(default_factory=list, description="修复建议")


ANALYZER_SYSTEM_PROMPT = """你是一个K8s集群诊断分析专家。你的任务是分析诊断命令的执行结果，提取关键信息，判断根因。

## 你需要分析的常见问题模式

### Pod状态问题
- **CrashLoopBackOff**: 查看日志中的错误信息，常见原因：
  - 应用启动失败（配置错误、依赖缺失）
  - OOM killed（内存不足）
  - Liveness probe失败
  
- **Pending**: 查看事件，常见原因：
  - Insufficient cpu/memory（资源不足）
  - No nodes available（没有可用节点）
  - PVC pending（存储卷问题）
  
- **ImagePullBackOff**: 查看事件，常见原因：
  - 镜像不存在
  - 认证失败
  - 网络问题

### Job失败
- 查看Job日志中的错误
- 常见原因：
  - 数据库连接失败
  - 脚本执行错误
  - 超时

### 连接问题
- 分析网络诊断结果
- 检查DNS解析
- 检查服务端Pod状态

## 输出格式

请以JSON格式输出分析结果：
```json
{
  "summary": "一句话总结当前发现",
  "findings": ["发现1", "发现2"],
  "root_cause": "根因（如果已确定，否则为null）",
  "confidence": 0.8,
  "next_action": "continue|replan|conclude",
  "recommendations": ["建议1", "建议2"]
}
```

## next_action说明
- **continue**: 继续执行计划中的下一步
- **replan**: 需要根据新发现调整计划
- **conclude**: 已找到根因或无法继续，准备输出结论
"""


class Analyzer:
    """诊断结果分析器"""
    
    def __init__(self, llm_client, config: dict):
        """
        初始化Analyzer
        
        Args:
            llm_client: LLM客户端
            config: 应用配置
        """
        self.llm = llm_client
        self.config = config
        self.model = config.get("llm", {}).get("model", "gpt-4o")
    
    async def analyze(
        self,
        step_action: str,
        step_params: Dict[str, Any],
        step_result: str,
        context: Optional[Dict[str, Any]] = None
    ) -> AnalysisResult:
        """
        分析单个步骤的执行结果
        
        Args:
            step_action: 执行的动作
            step_params: 动作参数
            step_result: 执行结果
            context: 上下文信息（包括之前的分析结果）
            
        Returns:
            AnalysisResult对象
        """
        user_message = f"""
执行的操作: {step_action}
参数: {step_params}

执行结果:
{step_result[:3000]}  # 截断过长的结果
"""
        
        if context:
            user_message += f"\n\n之前的分析上下文:\n{context}"
        
        response = await self._call_llm(
            system_prompt=ANALYZER_SYSTEM_PROMPT,
            user_message=user_message
        )
        
        return self._parse_analysis_response(response)
    
    async def synthesize(
        self,
        all_findings: List[AnalysisResult],
        original_problem: str
    ) -> str:
        """
        综合所有发现，生成最终报告
        
        Args:
            all_findings: 所有分析结果
            original_problem: 原始问题描述
            
        Returns:
            最终诊断报告
        """
        synthesis_prompt = f"""
请根据以下诊断过程，生成一份面向用户的诊断报告。

原始问题: {original_problem}

诊断过程中的发现:
{self._format_findings(all_findings)}

请生成一份清晰的诊断报告，包括：
1. 问题概述
2. 排查过程
3. 根因分析
4. 修复建议

使用中文回复，格式清晰易读。
"""
        
        response = await self._call_llm(
            system_prompt="你是一个K8s运维专家，请生成清晰专业的诊断报告。",
            user_message=synthesis_prompt,
            json_mode=False
        )
        
        return response
    
    async def _call_llm(
        self, 
        system_prompt: str, 
        user_message: str,
        json_mode: bool = True
    ) -> str:
        """调用LLM"""
        kwargs = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "temperature": 0.1
        }
        
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        
        response = self.llm.chat.completions.create(**kwargs)
        
        return response.choices[0].message.content
    
    def _parse_analysis_response(self, response: str) -> AnalysisResult:
        """解析分析响应"""
        import json
        
        try:
            data = json.loads(response)
            return AnalysisResult(**data)
        except Exception as e:
            logger.error(f"解析分析结果失败: {e}")
            return AnalysisResult(
                summary="解析失败",
                findings=["无法解析LLM响应"],
                next_action="conclude"
            )
    
    def _format_findings(self, findings: List[AnalysisResult]) -> str:
        """格式化所有发现"""
        formatted = []
        for i, f in enumerate(findings, 1):
            formatted.append(f"【步骤{i}】{f.summary}")
            for finding in f.findings:
                formatted.append(f"  - {finding}")
            if f.root_cause:
                formatted.append(f"  根因: {f.root_cause}")
            formatted.append("")
        return "\n".join(formatted)
