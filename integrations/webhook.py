"""
Webhook处理器 - 接收产品市场的实时部署事件
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Header
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ============================================================
# Webhook 事件模型
# ============================================================

class DeploymentEvent(BaseModel):
    """部署事件"""
    event_type: str  # DEPLOY_STARTED, DEPLOY_SUCCESS, DEPLOY_FAILED, etc.
    deployment_id: str
    product_id: str
    product_name: str
    environment_id: str
    namespace: str
    status: str
    error_message: Optional[str] = None
    error_detail: Optional[str] = None
    template_name: str
    template_version: str
    timestamp: str


# ============================================================
# Webhook 应用
# ============================================================

def create_webhook_app(
    agent,  # K8sDiagnosticAgent 
    webhook_secret: str
) -> FastAPI:
    """
    创建Webhook FastAPI应用
    
    Args:
        agent: 诊断Agent实例
        webhook_secret: Webhook验证密钥
        
    Returns:
        FastAPI应用
    """
    app = FastAPI(title="K8s Diagnostic Webhook")
    
    @app.post("/webhook/deployment")
    async def handle_deployment_event(
        event: DeploymentEvent,
        x_webhook_secret: str = Header(None)
    ):
        """处理部署事件"""
        
        # 验证密钥
        if x_webhook_secret != webhook_secret:
            raise HTTPException(status_code=403, detail="Invalid webhook secret")
        
        logger.info(f"收到部署事件: {event.event_type} - {event.deployment_id}")
        
        # 只处理失败事件
        if event.event_type not in ["DEPLOY_FAILED", "HEALTH_CHECK_FAILED", "ROLLBACK_FAILED"]:
            return {"status": "ignored", "reason": "Not a failure event"}
        
        # 异步触发诊断
        import asyncio
        asyncio.create_task(_diagnose_event(agent, event))
        
        return {
            "status": "accepted",
            "message": f"Diagnosis triggered for {event.deployment_id}"
        }
    
    @app.get("/health")
    async def health_check():
        """健康检查"""
        return {"status": "healthy"}
    
    return app


async def _diagnose_event(agent, event: DeploymentEvent):
    """诊断部署事件"""
    try:
        problem = f"""
[产品市场自动诊断]
产品: {event.product_name}
部署ID: {event.deployment_id}
Namespace: {event.namespace}
错误: {event.error_message or '未知'}
详情: {event.error_detail or '无'}

请诊断此部署失败的原因，并给出修复建议。
"""
        
        report = await agent.diagnose(
            problem=problem,
            environment=event.environment_id
        )
        
        logger.info(f"诊断完成: {event.deployment_id}")
        logger.info(f"诊断报告:\n{report}")
        
        # TODO: 回调产品市场更新诊断结果
        
    except Exception as e:
        logger.error(f"诊断失败: {e}")
