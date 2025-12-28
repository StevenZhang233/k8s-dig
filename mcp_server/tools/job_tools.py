"""
Job相关的K8s操作工具
"""
import logging
from typing import Optional

from kubernetes import client, config
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)


class JobTools:
    """Job相关操作工具（用于DBSql任务等）"""
    
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
        
        self.batch_v1 = client.BatchV1Api()
        self.core_v1 = client.CoreV1Api()
    
    async def list_jobs(self, namespace: str) -> str:
        """列出namespace下所有Job"""
        try:
            jobs = self.batch_v1.list_namespaced_job(namespace)
            
            if not jobs.items:
                return f"📭 namespace '{namespace}' 中没有Job"
            
            result = [f"📋 Namespace: {namespace} 的Job列表:\n"]
            result.append("-" * 90)
            result.append(f"{'NAME':<40} {'STATUS':<15} {'COMPLETIONS':<15} {'AGE'}")
            result.append("-" * 90)
            
            for job in jobs.items:
                name = job.metadata.name
                
                # 确定状态
                status = self._get_job_status(job)
                status_icon = self._get_job_status_icon(status)
                
                # 完成情况
                succeeded = job.status.succeeded or 0
                completions = job.spec.completions or 1
                completion_str = f"{succeeded}/{completions}"
                
                # 年龄
                age = self._calculate_age(job.metadata.creation_timestamp)
                
                result.append(
                    f"{name:<40} {status_icon} {status:<12} {completion_str:<15} {age}"
                )
            
            return "\n".join(result)
            
        except ApiException as e:
            return f"❌ API错误: {e.reason}"
        except Exception as e:
            return f"❌ 错误: {str(e)}"
    
    async def describe_job(self, namespace: str, job_name: str) -> str:
        """描述Job详情"""
        try:
            job = self.batch_v1.read_namespaced_job(job_name, namespace)
            
            result = [f"📋 Job: {job_name}"]
            result.append("=" * 60)
            
            # 基本信息
            status = self._get_job_status(job)
            result.append(f"\n📍 Namespace: {namespace}")
            result.append(f"📍 Status: {self._get_job_status_icon(status)} {status}")
            
            # 完成情况
            succeeded = job.status.succeeded or 0
            failed = job.status.failed or 0
            active = job.status.active or 0
            completions = job.spec.completions or 1
            
            result.append(f"\n📊 Progress:")
            result.append(f"   Completions: {succeeded}/{completions}")
            result.append(f"   Active: {active}")
            result.append(f"   Failed: {failed}")
            
            # 时间信息
            if job.status.start_time:
                result.append(f"\n⏰ Start Time: {job.status.start_time}")
            if job.status.completion_time:
                result.append(f"   Completion Time: {job.status.completion_time}")
            
            # 容器信息
            result.append(f"\n🐳 Container:")
            for container in job.spec.template.spec.containers:
                result.append(f"   Image: {container.image}")
                if container.command:
                    result.append(f"   Command: {' '.join(container.command)}")
            
            # Job条件
            if job.status.conditions:
                result.append(f"\n📣 Conditions:")
                for cond in job.status.conditions:
                    icon = "✅" if cond.status == "True" else "❌"
                    result.append(f"   {icon} {cond.type}: {cond.message or ''}")
            
            # 获取关联的Pod
            pods = self.core_v1.list_namespaced_pod(
                namespace,
                label_selector=f"job-name={job_name}"
            )
            
            if pods.items:
                result.append(f"\n🔗 Related Pods:")
                for pod in pods.items:
                    phase = pod.status.phase
                    icon = "✅" if phase == "Succeeded" else ("❌" if phase == "Failed" else "⏳")
                    result.append(f"   {icon} {pod.metadata.name} - {phase}")
            
            return "\n".join(result)
            
        except ApiException as e:
            if e.status == 404:
                return f"❌ Job '{job_name}' 在 namespace '{namespace}' 中不存在"
            return f"❌ API错误: {e.reason}"
        except Exception as e:
            return f"❌ 错误: {str(e)}"
    
    async def get_logs(self, namespace: str, job_name: str) -> str:
        """获取Job的日志"""
        try:
            # 找到Job关联的Pod
            pods = self.core_v1.list_namespaced_pod(
                namespace,
                label_selector=f"job-name={job_name}"
            )
            
            if not pods.items:
                return f"❌ 没有找到Job '{job_name}' 关联的Pod"
            
            result = [f"📜 Job: {job_name} 的日志"]
            result.append("=" * 60)
            
            for pod in pods.items:
                result.append(f"\n🔹 Pod: {pod.metadata.name} (Status: {pod.status.phase})")
                result.append("-" * 40)
                
                try:
                    # 尝试获取日志
                    logs = self.core_v1.read_namespaced_pod_log(
                        pod.metadata.name,
                        namespace,
                        tail_lines=100
                    )
                    result.append(logs if logs else "(no logs)")
                except ApiException as e:
                    result.append(f"(无法获取日志: {e.reason})")
            
            return "\n".join(result)
            
        except ApiException as e:
            return f"❌ API错误: {e.reason}"
        except Exception as e:
            return f"❌ 错误: {str(e)}"
    
    async def delete_job(self, namespace: str, job_name: str) -> str:
        """删除Job"""
        try:
            # 使用propagation_policy删除关联的Pod
            self.batch_v1.delete_namespaced_job(
                job_name,
                namespace,
                propagation_policy="Background"
            )
            return f"✅ Job '{job_name}' 已删除"
        except ApiException as e:
            if e.status == 404:
                return f"❌ Job '{job_name}' 不存在"
            return f"❌ API错误: {e.reason}"
    
    def _get_job_status(self, job) -> str:
        """判断Job状态"""
        if job.status.succeeded and job.status.succeeded >= (job.spec.completions or 1):
            return "Complete"
        elif job.status.failed:
            # 检查是否达到backoff limit
            if job.status.failed >= (job.spec.backoff_limit or 6):
                return "Failed"
            return "Running"
        elif job.status.active:
            return "Running"
        else:
            return "Pending"
    
    def _get_job_status_icon(self, status: str) -> str:
        """获取状态图标"""
        icons = {
            "Complete": "✅",
            "Failed": "❌",
            "Running": "🔄",
            "Pending": "⏳"
        }
        return icons.get(status, "❓")
    
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
