"""
Pod相关的K8s操作工具
"""
import asyncio
import logging
from typing import Optional

from kubernetes import client, config
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)


class PodTools:
    """Pod相关操作工具"""
    
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
        self.apps_v1 = client.AppsV1Api()
    
    async def list_pods(self, namespace: str) -> str:
        """列出namespace下所有Pod"""
        try:
            pods = self.core_v1.list_namespaced_pod(namespace)
            
            if not pods.items:
                return f"📭 namespace '{namespace}' 中没有Pod"
            
            result = [f"📦 Namespace: {namespace} 的Pod列表:\n"]
            result.append("-" * 80)
            result.append(f"{'NAME':<50} {'STATUS':<15} {'RESTARTS':<10} {'AGE'}")
            result.append("-" * 80)
            
            for pod in pods.items:
                name = pod.metadata.name
                phase = pod.status.phase
                
                # 计算重启次数
                restarts = 0
                if pod.status.container_statuses:
                    restarts = sum(
                        cs.restart_count for cs in pod.status.container_statuses
                    )
                
                # 计算年龄
                age = self._calculate_age(pod.metadata.creation_timestamp)
                
                # 状态图标
                status_icon = self._get_status_icon(phase, restarts)
                
                result.append(
                    f"{name:<50} {status_icon} {phase:<12} {restarts:<10} {age}"
                )
            
            return "\n".join(result)
            
        except ApiException as e:
            return f"❌ API错误: {e.reason}"
        except Exception as e:
            return f"❌ 错误: {str(e)}"
    
    async def describe_pod(self, namespace: str, pod_name: str) -> str:
        """描述Pod详情"""
        try:
            pod = self.core_v1.read_namespaced_pod(pod_name, namespace)
            
            result = [f"📋 Pod: {pod_name}"]
            result.append("=" * 60)
            
            # 基本信息
            result.append(f"\n📍 Namespace: {namespace}")
            result.append(f"📍 Node: {pod.spec.node_name or 'Not Scheduled'}")
            result.append(f"📍 Status: {pod.status.phase}")
            result.append(f"📍 IP: {pod.status.pod_ip or 'N/A'}")
            
            # 容器状态
            result.append(f"\n🐳 Containers:")
            if pod.status.container_statuses:
                for cs in pod.status.container_statuses:
                    result.append(f"  - {cs.name}:")
                    result.append(f"      Ready: {cs.ready}")
                    result.append(f"      Restarts: {cs.restart_count}")
                    
                    if cs.state.running:
                        result.append(f"      State: Running since {cs.state.running.started_at}")
                    elif cs.state.waiting:
                        result.append(f"      State: Waiting - {cs.state.waiting.reason}")
                        if cs.state.waiting.message:
                            result.append(f"      Message: {cs.state.waiting.message}")
                    elif cs.state.terminated:
                        result.append(f"      State: Terminated - {cs.state.terminated.reason}")
                        result.append(f"      Exit Code: {cs.state.terminated.exit_code}")
            
            # 获取事件
            events = self.core_v1.list_namespaced_event(
                namespace,
                field_selector=f"involvedObject.name={pod_name}"
            )
            
            if events.items:
                result.append(f"\n📣 Recent Events:")
                for event in sorted(events.items, key=lambda x: x.last_timestamp or x.event_time, reverse=True)[:5]:
                    type_icon = "⚠️" if event.type == "Warning" else "ℹ️"
                    result.append(f"  {type_icon} [{event.type}] {event.reason}: {event.message}")
            
            return "\n".join(result)
            
        except ApiException as e:
            if e.status == 404:
                return f"❌ Pod '{pod_name}' 在 namespace '{namespace}' 中不存在"
            return f"❌ API错误: {e.reason}"
        except Exception as e:
            return f"❌ 错误: {str(e)}"
    
    async def get_logs(
        self, 
        namespace: str, 
        pod_name: str,
        tail_lines: int = 100,
        container: Optional[str] = None,
        previous: bool = False
    ) -> str:
        """获取Pod日志"""
        try:
            logs = self.core_v1.read_namespaced_pod_log(
                pod_name,
                namespace,
                container=container,
                tail_lines=tail_lines,
                previous=previous
            )
            
            if not logs:
                return f"📭 Pod '{pod_name}' 没有日志输出"
            
            header = f"📜 Pod: {pod_name} 的日志 (最近{tail_lines}行)"
            if previous:
                header += " [上次崩溃]"
            if container:
                header += f" [容器: {container}]"
            
            return f"{header}\n{'=' * 60}\n{logs}"
            
        except ApiException as e:
            if e.status == 404:
                return f"❌ Pod '{pod_name}' 不存在或容器未启动"
            return f"❌ API错误: {e.reason}"
        except Exception as e:
            return f"❌ 错误: {str(e)}"
    
    async def get_events(
        self, 
        namespace: str,
        field_selector: Optional[str] = None
    ) -> str:
        """获取K8s事件"""
        try:
            if field_selector:
                events = self.core_v1.list_namespaced_event(
                    namespace, field_selector=field_selector
                )
            else:
                events = self.core_v1.list_namespaced_event(namespace)
            
            if not events.items:
                return f"📭 namespace '{namespace}' 中没有事件"
            
            result = [f"📣 Namespace: {namespace} 的事件:\n"]
            
            # 按时间排序
            sorted_events = sorted(
                events.items,
                key=lambda x: x.last_timestamp or x.event_time or x.metadata.creation_timestamp,
                reverse=True
            )[:20]  # 只显示最近20条
            
            for event in sorted_events:
                type_icon = "⚠️" if event.type == "Warning" else "ℹ️"
                time_str = str(event.last_timestamp or event.event_time or "")[:19]
                result.append(
                    f"{type_icon} [{time_str}] {event.involved_object.kind}/{event.involved_object.name}"
                )
                result.append(f"   {event.reason}: {event.message}")
                result.append("")
            
            return "\n".join(result)
            
        except ApiException as e:
            return f"❌ API错误: {e.reason}"
        except Exception as e:
            return f"❌ 错误: {str(e)}"
    
    async def get_configmap(self, namespace: str, name: str) -> str:
        """获取ConfigMap"""
        try:
            cm = self.core_v1.read_namespaced_config_map(name, namespace)
            
            result = [f"📝 ConfigMap: {name}"]
            result.append("=" * 60)
            
            if cm.data:
                for key, value in cm.data.items():
                    # 截断过长的值
                    if len(value) > 500:
                        value = value[:500] + "... (truncated)"
                    result.append(f"\n🔑 {key}:")
                    result.append(value)
            else:
                result.append("(empty)")
            
            return "\n".join(result)
            
        except ApiException as e:
            if e.status == 404:
                return f"❌ ConfigMap '{name}' 不存在"
            return f"❌ API错误: {e.reason}"
    
    async def get_deployment(self, namespace: str, name: str) -> str:
        """获取Deployment详情"""
        try:
            deploy = self.apps_v1.read_namespaced_deployment(name, namespace)
            
            result = [f"🚀 Deployment: {name}"]
            result.append("=" * 60)
            result.append(f"Replicas: {deploy.status.ready_replicas or 0}/{deploy.spec.replicas}")
            result.append(f"Strategy: {deploy.spec.strategy.type}")
            
            # 容器信息
            result.append("\n🐳 Containers:")
            for container in deploy.spec.template.spec.containers:
                result.append(f"  - {container.name}: {container.image}")
                if container.resources.requests:
                    result.append(f"    Requests: {container.resources.requests}")
                if container.resources.limits:
                    result.append(f"    Limits: {container.resources.limits}")
            
            # 条件
            if deploy.status.conditions:
                result.append("\n📊 Conditions:")
                for cond in deploy.status.conditions:
                    status_icon = "✅" if cond.status == "True" else "❌"
                    result.append(f"  {status_icon} {cond.type}: {cond.message or ''}")
            
            return "\n".join(result)
            
        except ApiException as e:
            if e.status == 404:
                return f"❌ Deployment '{name}' 不存在"
            return f"❌ API错误: {e.reason}"
    
    async def restart_pod(self, namespace: str, pod_name: str) -> str:
        """重启Pod（通过删除）"""
        try:
            self.core_v1.delete_namespaced_pod(pod_name, namespace)
            return f"✅ Pod '{pod_name}' 已删除，将由控制器重建"
        except ApiException as e:
            if e.status == 404:
                return f"❌ Pod '{pod_name}' 不存在"
            return f"❌ API错误: {e.reason}"
    
    def _get_status_icon(self, phase: str, restarts: int) -> str:
        """获取状态图标"""
        if phase == "Running" and restarts == 0:
            return "✅"
        elif phase == "Running" and restarts > 0:
            return "⚠️"
        elif phase == "Pending":
            return "⏳"
        elif phase in ["Failed", "Unknown"]:
            return "❌"
        elif phase == "Succeeded":
            return "✔️"
        return "❓"
    
    def _calculate_age(self, timestamp) -> str:
        """计算资源年龄"""
        if not timestamp:
            return "N/A"
        
        from datetime import datetime, timezone
        
        now = datetime.now(timezone.utc)
        diff = now - timestamp
        
        days = diff.days
        hours = diff.seconds // 3600
        minutes = (diff.seconds % 3600) // 60
        
        if days > 0:
            return f"{days}d"
        elif hours > 0:
            return f"{hours}h"
        else:
            return f"{minutes}m"
