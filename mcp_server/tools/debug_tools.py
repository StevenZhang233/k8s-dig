"""
调试相关的K8s操作工具
"""
import logging
from typing import Optional

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.stream import stream

logger = logging.getLogger(__name__)


class DebugTools:
    """调试相关操作工具"""
    
    def __init__(self, app_config: dict):
        self.config = app_config
        self._init_k8s_client()
    
    def _init_k8s_client(self):
        """初始化K8s客户端"""
        k8s_config = self.config.get("kubernetes", {})
        
        if k8s_config.get("in_cluster"):
            config.load_incluster_config()
        else:
            kubeconfig = k8s_config.get("kubeconfig") or None
            config.load_kube_config(config_file=kubeconfig)
        
        self.core_v1 = client.CoreV1Api()
    
    async def exec_in_pod(
        self,
        namespace: str,
        pod_name: str,
        command: str,
        container: Optional[str] = None
    ) -> str:
        """在Pod内执行命令"""
        try:
            # 解析命令
            cmd_parts = command.split()
            
            exec_command = ['/bin/sh', '-c', command]
            
            # 构建exec请求
            kwargs = {
                "name": pod_name,
                "namespace": namespace,
                "command": exec_command,
                "stderr": True,
                "stdin": False,
                "stdout": True,
                "tty": False
            }
            
            if container:
                kwargs["container"] = container
            
            # 执行命令
            result = stream(
                self.core_v1.connect_get_namespaced_pod_exec,
                **kwargs
            )
            
            return f"🔧 执行命令: {command}\n{'=' * 60}\n{result}"
            
        except ApiException as e:
            if e.status == 404:
                return f"❌ Pod '{pod_name}' 不存在"
            return f"❌ API错误: {e.reason}"
        except Exception as e:
            return f"❌ 执行失败: {str(e)}"
    
    async def check_network_connectivity(
        self,
        namespace: str,
        pod_name: str,
        target_host: str,
        target_port: int = 80
    ) -> str:
        """检查网络连通性"""
        # 使用nc或curl检查连接
        command = f"timeout 5 bash -c 'cat < /dev/null > /dev/tcp/{target_host}/{target_port}' && echo 'Connection successful' || echo 'Connection failed'"
        
        return await self.exec_in_pod(namespace, pod_name, command)
    
    async def check_dns_resolution(
        self,
        namespace: str,
        pod_name: str,
        hostname: str
    ) -> str:
        """检查DNS解析"""
        command = f"nslookup {hostname}"
        return await self.exec_in_pod(namespace, pod_name, command)
    
    async def check_environment(
        self,
        namespace: str,
        pod_name: str,
        container: Optional[str] = None
    ) -> str:
        """检查环境变量"""
        return await self.exec_in_pod(namespace, pod_name, "env | sort", container)
    
    async def check_filesystem(
        self,
        namespace: str,
        pod_name: str,
        path: str = "/"
    ) -> str:
        """检查文件系统"""
        command = f"df -h {path} && ls -la {path}"
        return await self.exec_in_pod(namespace, pod_name, command)
    
    async def check_processes(
        self,
        namespace: str,
        pod_name: str
    ) -> str:
        """检查进程列表"""
        return await self.exec_in_pod(namespace, pod_name, "ps aux")
    
    async def check_memory(
        self,
        namespace: str,
        pod_name: str
    ) -> str:
        """检查内存使用"""
        return await self.exec_in_pod(namespace, pod_name, "free -m")
