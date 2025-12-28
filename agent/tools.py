"""
K8s诊断工具集 - 用于LangGraph Agent
"""
import logging
from typing import List, Optional

from langchain_core.tools import tool
from kubernetes import client
from kubernetes.client.rest import ApiException
from kubernetes.stream import stream

from .environment import EnvironmentManager

logger = logging.getLogger(__name__)


def create_k8s_tools(env_manager: EnvironmentManager, config: dict) -> List:
    """
    创建K8s诊断工具集
    
    Args:
        env_manager: 环境管理器
        config: 应用配置
        
    Returns:
        工具列表
    """
    security = config.get("security", {})
    blocked_ns = set(security.get("blocked_namespaces", []))
    allowed_exec = set(security.get("allowed_exec_commands", []))
    
    def check_namespace(namespace: str) -> bool:
        """检查namespace是否允许访问"""
        if namespace in blocked_ns:
            raise ValueError(f"不允许访问namespace: {namespace}")
        return True
    
    def check_exec_command(command: str) -> bool:
        """检查exec命令是否在白名单"""
        base_cmd = command.split()[0] if command else ""
        if "/" in base_cmd:
            base_cmd = base_cmd.split("/")[-1]
        if base_cmd not in allowed_exec:
            raise ValueError(f"命令 '{base_cmd}' 不在允许列表中")
        return True
    
    # ==================== 定义工具 ====================
    
    @tool
    def list_pods(namespace: str) -> str:
        """列出指定namespace下所有Pod的状态，用于发现问题Pod"""
        check_namespace(namespace)
        
        try:
            core_v1, _, _ = env_manager.get_k8s_clients()
            pods = core_v1.list_namespaced_pod(namespace)
            
            if not pods.items:
                return f"📭 namespace '{namespace}' 中没有Pod"
            
            result = [f"📦 Namespace: {namespace} 的Pod列表:"]
            result.append("-" * 60)
            
            for pod in pods.items:
                name = pod.metadata.name
                phase = pod.status.phase
                
                restarts = 0
                if pod.status.container_statuses:
                    restarts = sum(cs.restart_count for cs in pod.status.container_statuses)
                
                status_icon = "✅" if phase == "Running" and restarts == 0 else (
                    "⚠️" if phase == "Running" else "❌"
                )
                
                result.append(f"{status_icon} {name}: {phase} (重启: {restarts})")
            
            return "\n".join(result)
        except ApiException as e:
            return f"❌ API错误: {e.reason}"
    
    @tool
    def describe_pod(namespace: str, pod_name: str) -> str:
        """获取Pod的详细描述，包括事件、状态、容器信息"""
        check_namespace(namespace)
        
        try:
            core_v1, _, _ = env_manager.get_k8s_clients()
            pod = core_v1.read_namespaced_pod(pod_name, namespace)
            
            result = [f"📋 Pod: {pod_name}"]
            result.append(f"Namespace: {namespace}")
            result.append(f"Node: {pod.spec.node_name or 'Not Scheduled'}")
            result.append(f"Status: {pod.status.phase}")
            result.append(f"IP: {pod.status.pod_ip or 'N/A'}")
            
            # 容器状态
            if pod.status.container_statuses:
                result.append("\n🐳 Containers:")
                for cs in pod.status.container_statuses:
                    result.append(f"  - {cs.name}: Ready={cs.ready}, Restarts={cs.restart_count}")
                    if cs.state.waiting:
                        result.append(f"    状态: Waiting - {cs.state.waiting.reason}")
                    elif cs.state.terminated:
                        result.append(f"    状态: Terminated - {cs.state.terminated.reason}")
            
            # 获取事件
            events = core_v1.list_namespaced_event(
                namespace,
                field_selector=f"involvedObject.name={pod_name}"
            )
            
            if events.items:
                result.append("\n📣 Recent Events:")
                for event in sorted(events.items, key=lambda x: x.last_timestamp or x.event_time, reverse=True)[:5]:
                    type_icon = "⚠️" if event.type == "Warning" else "ℹ️"
                    result.append(f"  {type_icon} {event.reason}: {event.message}")
            
            return "\n".join(result)
        except ApiException as e:
            if e.status == 404:
                return f"❌ Pod '{pod_name}' 不存在"
            return f"❌ API错误: {e.reason}"
    
    @tool
    def get_pod_logs(namespace: str, pod_name: str, tail_lines: int = 100, previous: bool = False) -> str:
        """获取Pod的日志输出，用于排查应用层错误。previous=True获取崩溃前日志"""
        check_namespace(namespace)
        
        try:
            core_v1, _, _ = env_manager.get_k8s_clients()
            logs = core_v1.read_namespaced_pod_log(
                pod_name,
                namespace,
                tail_lines=tail_lines,
                previous=previous
            )
            
            header = f"📜 Pod: {pod_name} 日志 (最近{tail_lines}行)"
            if previous:
                header += " [上次崩溃]"
            
            return f"{header}\n{'=' * 40}\n{logs}" if logs else "📭 没有日志"
        except ApiException as e:
            return f"❌ 获取日志失败: {e.reason}"
    
    @tool
    def get_events(namespace: str) -> str:
        """获取namespace下的K8s事件，用于排查调度、拉镜像等问题"""
        check_namespace(namespace)
        
        try:
            core_v1, _, _ = env_manager.get_k8s_clients()
            events = core_v1.list_namespaced_event(namespace)
            
            if not events.items:
                return f"📭 namespace '{namespace}' 中没有事件"
            
            result = [f"📣 Namespace: {namespace} 的事件:"]
            
            sorted_events = sorted(
                events.items,
                key=lambda x: x.last_timestamp or x.event_time or x.metadata.creation_timestamp,
                reverse=True
            )[:15]
            
            for event in sorted_events:
                type_icon = "⚠️" if event.type == "Warning" else "ℹ️"
                result.append(
                    f"{type_icon} {event.involved_object.kind}/{event.involved_object.name}: "
                    f"{event.reason} - {event.message}"
                )
            
            return "\n".join(result)
        except ApiException as e:
            return f"❌ API错误: {e.reason}"
    
    @tool
    def list_jobs(namespace: str) -> str:
        """列出namespace下所有Job的状态，用于查看DBSql等批处理任务"""
        check_namespace(namespace)
        
        try:
            _, _, batch_v1 = env_manager.get_k8s_clients()
            jobs = batch_v1.list_namespaced_job(namespace)
            
            if not jobs.items:
                return f"📭 namespace '{namespace}' 中没有Job"
            
            result = [f"📋 Namespace: {namespace} 的Job列表:"]
            
            for job in jobs.items:
                name = job.metadata.name
                succeeded = job.status.succeeded or 0
                failed = job.status.failed or 0
                completions = job.spec.completions or 1
                
                if succeeded >= completions:
                    status = "✅ Complete"
                elif failed > 0:
                    status = "❌ Failed"
                else:
                    status = "🔄 Running"
                
                result.append(f"{status} {name}: {succeeded}/{completions}")
            
            return "\n".join(result)
        except ApiException as e:
            return f"❌ API错误: {e.reason}"
    
    @tool
    def get_job_logs(namespace: str, job_name: str) -> str:
        """获取Job的执行日志，用于排查DBSql等任务失败原因"""
        check_namespace(namespace)
        
        try:
            core_v1, _, _ = env_manager.get_k8s_clients()
            
            pods = core_v1.list_namespaced_pod(
                namespace,
                label_selector=f"job-name={job_name}"
            )
            
            if not pods.items:
                return f"❌ 没有找到Job '{job_name}' 关联的Pod"
            
            result = [f"📜 Job: {job_name} 的日志"]
            
            for pod in pods.items:
                result.append(f"\n🔹 Pod: {pod.metadata.name}")
                try:
                    logs = core_v1.read_namespaced_pod_log(
                        pod.metadata.name,
                        namespace,
                        tail_lines=100
                    )
                    result.append(logs if logs else "(无日志)")
                except:
                    result.append("(无法获取日志)")
            
            return "\n".join(result)
        except ApiException as e:
            return f"❌ API错误: {e.reason}"
    
    @tool
    def exec_in_pod(namespace: str, pod_name: str, command: str) -> str:
        """在Pod内执行诊断命令（仅限白名单命令如: env, ps, cat, ls, df, netstat等）"""
        check_namespace(namespace)
        check_exec_command(command)
        
        try:
            core_v1, _, _ = env_manager.get_k8s_clients()
            
            exec_command = ['/bin/sh', '-c', command]
            
            result = stream(
                core_v1.connect_get_namespaced_pod_exec,
                pod_name,
                namespace,
                command=exec_command,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False
            )
            
            return f"🔧 执行: {command}\n{'=' * 40}\n{result}"
        except ApiException as e:
            return f"❌ 执行失败: {e.reason}"
        except Exception as e:
            return f"❌ 错误: {str(e)}"
    
    @tool
    def restart_pod(namespace: str, pod_name: str) -> str:
        """删除Pod触发Deployment重建（Pod会自动重建）。这是一个修复操作，请谨慎使用。"""
        check_namespace(namespace)
        
        try:
            core_v1, _, _ = env_manager.get_k8s_clients()
            core_v1.delete_namespaced_pod(pod_name, namespace)
            return f"✅ Pod '{pod_name}' 已删除，将由控制器重建"
        except ApiException as e:
            return f"❌ 删除失败: {e.reason}"
    
    @tool
    def get_deployment(namespace: str, name: str) -> str:
        """获取Deployment的详细信息，包括副本数、容器配置等"""
        check_namespace(namespace)
        
        try:
            _, apps_v1, _ = env_manager.get_k8s_clients()
            deploy = apps_v1.read_namespaced_deployment(name, namespace)
            
            result = [f"🚀 Deployment: {name}"]
            result.append(f"Replicas: {deploy.status.ready_replicas or 0}/{deploy.spec.replicas}")
            
            for container in deploy.spec.template.spec.containers:
                result.append(f"\n🐳 Container: {container.name}")
                result.append(f"  Image: {container.image}")
                if container.resources.requests:
                    result.append(f"  Requests: {container.resources.requests}")
                if container.resources.limits:
                    result.append(f"  Limits: {container.resources.limits}")
            
            return "\n".join(result)
        except ApiException as e:
            return f"❌ 获取失败: {e.reason}"
    
    # 返回所有工具
    return [
        list_pods,
        describe_pod,
        get_pod_logs,
        get_events,
        list_jobs,
        get_job_logs,
        exec_in_pod,
        restart_pod,
        get_deployment
    ]
