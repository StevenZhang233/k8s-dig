"""
环境管理器 - 支持多K8s环境切换
"""
import logging
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass

import yaml
from kubernetes import client, config

logger = logging.getLogger(__name__)


@dataclass
class K8sEnvironment:
    """K8s环境配置"""
    name: str
    display_name: str
    master_ip: str
    kubeconfig: str
    description: str = ""
    
    def __str__(self):
        return f"{self.display_name} ({self.name}) - {self.master_ip}"


class EnvironmentManager:
    """多环境管理器"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        self.environments: Dict[str, K8sEnvironment] = {}
        self.current_env: Optional[str] = None
        
        self._load_environments()
        
        # 记录默认环境名称（延迟切换）
        self.default_env = self.config.get("environments", {}).get("default")
    
    def _load_config(self, config_path: str) -> dict:
        """加载配置"""
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _load_environments(self):
        """加载所有环境配置"""
        clusters = self.config.get("environments", {}).get("clusters", [])
        
        for cluster in clusters:
            env = K8sEnvironment(
                name=cluster["name"],
                display_name=cluster.get("display_name", cluster["name"]),
                master_ip=cluster["master_ip"],
                kubeconfig=cluster.get("kubeconfig", "~/.kube/config"),
                description=cluster.get("description", "")
            )
            self.environments[env.name] = env
            logger.info(f"加载环境: {env}")
    
    def list_environments(self) -> List[K8sEnvironment]:
        """列出所有环境"""
        return list(self.environments.values())
    
    def get_environment(self, name: str) -> Optional[K8sEnvironment]:
        """获取指定环境"""
        return self.environments.get(name)
    
    def get_current_environment(self) -> Optional[K8sEnvironment]:
        """获取当前环境"""
        if self.current_env:
            return self.environments.get(self.current_env)
        return None
    
    def switch_environment(self, env_name: str) -> bool:
        """
        切换到指定环境
        
        Args:
            env_name: 环境名称
            
        Returns:
            是否切换成功
        """
        if env_name not in self.environments:
            logger.error(f"环境 '{env_name}' 不存在")
            return False
        
        env = self.environments[env_name]
        kubeconfig_path = Path(env.kubeconfig).expanduser()
        
        try:
            # 检查kubeconfig是否存在
            if not kubeconfig_path.exists():
                logger.warning(f"kubeconfig文件不存在: {kubeconfig_path}，使用模拟模式")
                self.current_env = env_name
                return True
            
            # 加载kubeconfig
            config.load_kube_config(config_file=str(kubeconfig_path))
            self.current_env = env_name
            logger.info(f"已切换到环境: {env}")
            return True
        except Exception as e:
            logger.warning(f"切换环境失败: {e}，使用模拟模式")
            self.current_env = env_name
            return True
    
    def get_k8s_clients(self) -> tuple:
        """
        获取当前环境的K8s客户端
        
        Returns:
            (CoreV1Api, AppsV1Api, BatchV1Api)
        """
        if not self.current_env:
            raise RuntimeError("未选择环境，请先调用 switch_environment()")
        
        return (
            client.CoreV1Api(),
            client.AppsV1Api(),
            client.BatchV1Api()
        )
    
    def test_connection(self, env_name: Optional[str] = None) -> Dict:
        """
        测试环境连接
        
        Args:
            env_name: 环境名称，留空则测试当前环境
            
        Returns:
            {success: bool, message: str, nodes: int}
        """
        target_env = env_name or self.current_env
        
        if not target_env:
            return {"success": False, "message": "未指定环境", "nodes": 0}
        
        # 临时切换
        original_env = self.current_env
        if env_name and env_name != self.current_env:
            if not self.switch_environment(env_name):
                return {"success": False, "message": "切换环境失败", "nodes": 0}
        
        try:
            core_v1, _, _ = self.get_k8s_clients()
            nodes = core_v1.list_node()
            node_count = len(nodes.items)
            
            return {
                "success": True,
                "message": f"连接成功，集群有 {node_count} 个节点",
                "nodes": node_count
            }
        except Exception as e:
            return {"success": False, "message": str(e), "nodes": 0}
        finally:
            # 恢复原环境
            if original_env and original_env != target_env:
                self.switch_environment(original_env)
    
    def get_env_info_for_display(self) -> List[Dict]:
        """获取环境信息（用于GUI显示）"""
        result = []
        for env in self.environments.values():
            is_current = env.name == self.current_env
            result.append({
                "name": env.name,
                "display_name": env.display_name,
                "master_ip": env.master_ip,
                "description": env.description,
                "is_current": is_current,
                "status_icon": "🟢" if is_current else "⚪"
            })
        return result
