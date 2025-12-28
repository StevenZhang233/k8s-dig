"""
============================================================
Tools 模板文件
============================================================

使用说明：
1. 复制此文件到 agent/tools/ 目录
2. 重命名为你的产品工具，如: mysql_tools.py
3. 实现你的产品特有诊断工具
4. 在 agent/tools/__init__.py 中注册

============================================================
"""
from typing import Optional
from langchain_core.tools import tool


def create_template_tools(env_manager, config: dict) -> list:
    """
    创建产品特有工具集
    
    Args:
        env_manager: 环境管理器，用于获取K8s客户端
        config: 应用配置
        
    Returns:
        工具列表
    """
    
    # 从配置中获取安全设置
    security = config.get("security", {})
    blocked_ns = set(security.get("blocked_namespaces", []))
    
    def check_namespace(namespace: str) -> bool:
        """检查namespace是否允许访问"""
        if namespace in blocked_ns:
            raise ValueError(f"不允许访问namespace: {namespace}")
        return True
    
    # ============================================================
    # 示例工具1：只读查询
    # ============================================================
    @tool
    def template_check_status(namespace: str, component: str = "") -> str:
        """
        检查产品组件状态
        
        Args:
            namespace: 目标namespace
            component: 组件名称（可选）
            
        Returns:
            状态信息
        """
        check_namespace(namespace)
        
        try:
            core_v1, _, _ = env_manager.get_k8s_clients()
            
            label_selector = f"app={component}" if component else ""
            pods = core_v1.list_namespaced_pod(
                namespace, 
                label_selector=label_selector
            )
            
            if not pods.items:
                return f"📭 未找到组件"
            
            result = [f"📦 {namespace} 组件状态:"]
            for pod in pods.items:
                status = pod.status.phase
                icon = "✅" if status == "Running" else "❌"
                result.append(f"  {icon} {pod.metadata.name}: {status}")
            
            return "\n".join(result)
            
        except Exception as e:
            return f"❌ 查询失败: {str(e)}"
    
    # ============================================================
    # 示例工具2：执行产品特有命令
    # ============================================================
    @tool
    def template_run_diagnostic(
        namespace: str, 
        pod_name: str, 
        diagnostic_type: str = "basic"
    ) -> str:
        """
        执行产品特有诊断命令
        
        Args:
            namespace: 目标namespace
            pod_name: Pod名称
            diagnostic_type: 诊断类型 (basic/detailed)
            
        Returns:
            诊断结果
        """
        check_namespace(namespace)
        
        # 定义允许的诊断命令
        diagnostic_commands = {
            "basic": "echo 'Basic diagnostic'",
            "detailed": "echo 'Detailed diagnostic'"
        }
        
        if diagnostic_type not in diagnostic_commands:
            return f"❌ 未知诊断类型: {diagnostic_type}"
        
        # TODO: 实现实际的诊断逻辑
        # 使用 kubernetes.stream 执行命令
        
        return f"🔧 诊断完成: {diagnostic_type}"
    
    # ============================================================
    # 示例工具3：获取产品特有指标
    # ============================================================
    @tool
    def template_get_metrics(namespace: str, metric_name: str = "all") -> str:
        """
        获取产品特有指标
        
        Args:
            namespace: 目标namespace
            metric_name: 指标名称 (all/cpu/memory/connections)
            
        Returns:
            指标信息
        """
        check_namespace(namespace)
        
        # TODO: 实现实际的指标获取逻辑
        # 可以从Prometheus、产品API等获取
        
        return f"📊 指标 {metric_name}: 正常"
    
    # 返回所有工具
    return [
        template_check_status,
        template_run_diagnostic,
        template_get_metrics
    ]


# ============================================================
# 注册函数 - 在 agent/tools/__init__.py 中调用
# ============================================================
def register_tools():
    """
    返回工具创建函数和元信息
    """
    return {
        "create_func": create_template_tools,
        "domain": "template",           # 所属领域
        "product": "template_product",  # 所属产品
        "version": "1.0.0"
    }
