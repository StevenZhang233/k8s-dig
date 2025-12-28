"""
产品市场集成模块
自动从产品市场获取部署错误，并触发K8s诊断
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
from pathlib import Path

import yaml
import httpx

logger = logging.getLogger(__name__)


# ============================================================
# 数据模型
# ============================================================

class DeployStatus(Enum):
    """部署状态"""
    PENDING = "PENDING"
    DEPLOYING = "DEPLOYING"
    SUCCESS = "SUCCESS"
    DEPLOY_FAILED = "DEPLOY_FAILED"
    DEPLOY_TIMEOUT = "DEPLOY_TIMEOUT"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"
    HEALTH_CHECK_FAILED = "HEALTH_CHECK_FAILED"


@dataclass
class DeploymentError:
    """部署错误信息"""
    deployment_id: str
    product_id: str
    product_name: str
    environment_id: str
    namespace: str
    status: DeployStatus
    error_message: str
    error_detail: Optional[str]
    timestamp: datetime
    template_name: str
    template_version: str
    
    def to_diagnosis_request(self) -> Dict:
        """转换为诊断请求"""
        return {
            "problem": f"{self.product_name} 部署失败: {self.error_message}",
            "environment": self.environment_id,
            "namespace": self.namespace,
            "context": {
                "deployment_id": self.deployment_id,
                "product_id": self.product_id,
                "template": f"{self.template_name}:{self.template_version}",
                "error_detail": self.error_detail
            }
        }


# ============================================================
# 产品市场客户端（抽象基类）
# ============================================================

class MarketplaceClient(ABC):
    """产品市场客户端抽象基类"""
    
    @abstractmethod
    async def get_failed_deployments(self) -> List[DeploymentError]:
        """获取失败的部署列表"""
        pass
    
    @abstractmethod
    async def get_deployment_detail(self, deployment_id: str) -> Dict:
        """获取部署详情"""
        pass
    
    @abstractmethod
    async def get_deployment_logs(self, deployment_id: str) -> str:
        """获取部署日志"""
        pass
    
    @abstractmethod
    async def update_deployment_status(
        self, 
        deployment_id: str, 
        diagnosis_result: str
    ):
        """更新部署的诊断结果"""
        pass


# ============================================================
# HTTP API 实现
# ============================================================

class HTTPMarketplaceClient(MarketplaceClient):
    """基于HTTP API的产品市场客户端"""
    
    def __init__(self, config: Dict):
        self.base_url = config.get("base_url", "")
        self.token = config.get("token", "")
        self.timeout = config.get("timeout", 30)
        self.watch_statuses = config.get("watch_statuses", ["DEPLOY_FAILED"])
        
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=self.timeout
        )
    
    async def get_failed_deployments(self) -> List[DeploymentError]:
        """获取失败的部署列表"""
        try:
            # 调用产品市场API
            response = await self.client.get(
                "/deployments",
                params={
                    "status": ",".join(self.watch_statuses),
                    "limit": 50,
                    "order": "desc"
                }
            )
            response.raise_for_status()
            
            data = response.json()
            errors = []
            
            for item in data.get("items", []):
                error = DeploymentError(
                    deployment_id=item["id"],
                    product_id=item["product_id"],
                    product_name=item["product_name"],
                    environment_id=item["environment_id"],
                    namespace=item["namespace"],
                    status=DeployStatus(item["status"]),
                    error_message=item.get("error_message", "未知错误"),
                    error_detail=item.get("error_detail"),
                    timestamp=datetime.fromisoformat(item["updated_at"]),
                    template_name=item.get("template_name", ""),
                    template_version=item.get("template_version", "")
                )
                errors.append(error)
            
            return errors
            
        except Exception as e:
            logger.error(f"获取失败部署列表失败: {e}")
            return []
    
    async def get_deployment_detail(self, deployment_id: str) -> Dict:
        """获取部署详情"""
        response = await self.client.get(f"/deployments/{deployment_id}")
        response.raise_for_status()
        return response.json()
    
    async def get_deployment_logs(self, deployment_id: str) -> str:
        """获取部署日志"""
        response = await self.client.get(f"/deployments/{deployment_id}/logs")
        response.raise_for_status()
        return response.text
    
    async def update_deployment_status(
        self, 
        deployment_id: str, 
        diagnosis_result: str
    ):
        """更新部署的诊断结果"""
        await self.client.post(
            f"/deployments/{deployment_id}/diagnosis",
            json={"result": diagnosis_result}
        )


# ============================================================
# 模拟客户端（用于测试）
# ============================================================

class MockMarketplaceClient(MarketplaceClient):
    """模拟客户端，用于本地测试"""
    
    def __init__(self, config: Dict):
        self.mock_errors: List[DeploymentError] = []
    
    def add_mock_error(self, error: DeploymentError):
        """添加模拟错误"""
        self.mock_errors.append(error)
    
    async def get_failed_deployments(self) -> List[DeploymentError]:
        return self.mock_errors
    
    async def get_deployment_detail(self, deployment_id: str) -> Dict:
        return {"id": deployment_id, "status": "DEPLOY_FAILED"}
    
    async def get_deployment_logs(self, deployment_id: str) -> str:
        return "Mock deployment logs..."
    
    async def update_deployment_status(
        self, 
        deployment_id: str, 
        diagnosis_result: str
    ):
        logger.info(f"[Mock] 更新部署 {deployment_id} 诊断结果")


# ============================================================
# 自动诊断调度器
# ============================================================

class AutoDiagnosisScheduler:
    """自动诊断调度器"""
    
    def __init__(
        self, 
        marketplace_client: MarketplaceClient,
        agent,  # K8sDiagnosticAgent
        config: Dict
    ):
        self.marketplace = marketplace_client
        self.agent = agent
        self.config = config
        
        self.polling_interval = config.get("polling", {}).get("interval_seconds", 60)
        self.max_concurrent = config.get("auto_diagnosis", {}).get("max_concurrent", 5)
        
        self._running = False
        self._processed_ids: set = set()
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
    
    async def start(self):
        """启动调度器"""
        self._running = True
        logger.info("自动诊断调度器已启动")
        
        while self._running:
            try:
                await self._check_and_diagnose()
            except Exception as e:
                logger.error(f"调度器错误: {e}")
            
            await asyncio.sleep(self.polling_interval)
    
    def stop(self):
        """停止调度器"""
        self._running = False
        logger.info("自动诊断调度器已停止")
    
    async def _check_and_diagnose(self):
        """检查并触发诊断"""
        errors = await self.marketplace.get_failed_deployments()
        
        for error in errors:
            # 跳过已处理的
            if error.deployment_id in self._processed_ids:
                continue
            
            # 标记为已处理
            self._processed_ids.add(error.deployment_id)
            
            # 异步触发诊断
            asyncio.create_task(self._diagnose(error))
    
    async def _diagnose(self, error: DeploymentError):
        """执行诊断"""
        async with self._semaphore:
            logger.info(f"开始诊断部署: {error.deployment_id}")
            
            try:
                # 获取部署日志作为上下文
                logs = await self.marketplace.get_deployment_logs(error.deployment_id)
                
                # 构建诊断请求
                request = error.to_diagnosis_request()
                request["context"]["deployment_logs"] = logs[:5000]  # 限制长度
                
                # 调用Agent诊断
                problem = f"""
产品: {error.product_name}
部署ID: {error.deployment_id}
错误: {error.error_message}
详情: {error.error_detail or '无'}
部署日志摘要: {logs[:1000]}...

请诊断此部署失败的原因。
"""
                
                report = await self.agent.diagnose(
                    problem=problem,
                    environment=error.environment_id
                )
                
                # 更新诊断结果到产品市场
                await self.marketplace.update_deployment_status(
                    error.deployment_id,
                    report
                )
                
                logger.info(f"诊断完成: {error.deployment_id}")
                
            except Exception as e:
                logger.error(f"诊断失败 {error.deployment_id}: {e}")


# ============================================================
# 工厂函数
# ============================================================

def create_marketplace_client(config_path: str = "config/marketplace.yaml") -> MarketplaceClient:
    """创建产品市场客户端"""
    path = Path(config_path)
    
    if not path.exists():
        logger.warning(f"配置文件不存在: {path}，使用模拟客户端")
        return MockMarketplaceClient({})
    
    with open(path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    api_config = config.get("marketplace", {}).get("api", {})
    
    if not api_config.get("base_url"):
        return MockMarketplaceClient(config)
    
    return HTTPMarketplaceClient(api_config)
