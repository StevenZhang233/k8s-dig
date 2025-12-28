"""
白名单安全检查
"""
import re
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class WhitelistChecker:
    """白名单检查器"""
    
    def __init__(self, config: dict):
        self.config = config
        security = config.get("security", {})
        
        # 加载允许/禁止的namespace
        self.allowed_namespaces = set(security.get("allowed_namespaces", []))
        self.blocked_namespaces = set(security.get("blocked_namespaces", [
            "kube-system",
            "kube-public", 
            "kube-node-lease"
        ]))
        
        # 加载允许的exec命令前缀
        self.allowed_exec_commands = security.get("allowed_exec_commands", [
            "env", "ps", "cat", "ls", "df", "free",
            "netstat", "ping", "nslookup", "curl", "wget", "top"
        ])
    
    def check_namespace(self, namespace: str) -> bool:
        """
        检查namespace是否允许访问
        
        规则：
        1. 黑名单优先：如果在blocked_namespaces中，直接拒绝
        2. 如果allowed_namespaces为空，则允许所有（除了黑名单）
        3. 如果allowed_namespaces不为空，必须在白名单中
        """
        if not namespace:
            logger.warning("namespace为空")
            return False
        
        # 黑名单检查
        if namespace in self.blocked_namespaces:
            logger.warning(f"拒绝访问被禁止的namespace: {namespace}")
            return False
        
        # 白名单检查
        if self.allowed_namespaces:
            if namespace in self.allowed_namespaces:
                return True
            else:
                logger.warning(f"namespace '{namespace}' 不在允许列表中")
                return False
        
        # 没有配置白名单，允许所有（除了黑名单）
        return True
    
    def check_exec_command(self, command: str) -> bool:
        """
        检查exec命令是否在白名单中
        
        规则：
        1. 命令的第一个单词必须在白名单中
        2. 禁止包含危险字符（如管道到rm等）
        """
        if not command:
            return False
        
        # 获取命令的第一个单词
        cmd_parts = command.strip().split()
        if not cmd_parts:
            return False
        
        base_cmd = cmd_parts[0]
        
        # 处理路径形式的命令（如 /bin/cat）
        if "/" in base_cmd:
            base_cmd = base_cmd.split("/")[-1]
        
        # 检查是否在白名单中
        if base_cmd not in self.allowed_exec_commands:
            logger.warning(f"命令 '{base_cmd}' 不在允许列表中")
            return False
        
        # 检查危险模式
        dangerous_patterns = [
            r'\|\s*rm',      # 管道到rm
            r'\|\s*dd',      # 管道到dd
            r'>\s*/etc/',    # 重定向到/etc
            r'>\s*/var/',    # 重定向到/var
            r'>\s*/usr/',    # 重定向到/usr
            r'&&\s*rm',      # 链式rm
            r';\s*rm',       # 分号后rm
            r'\$\(',         # 命令替换
            r'`',            # 反引号命令替换
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                logger.warning(f"命令包含危险模式: {pattern}")
                return False
        
        return True
    
    def check_resource_access(
        self, 
        resource_type: str, 
        resource_name: str,
        namespace: str
    ) -> bool:
        """
        检查资源访问权限
        
        可扩展：添加更细粒度的资源访问控制
        """
        # 检查namespace
        if not self.check_namespace(namespace):
            return False
        
        # 可以添加更多资源级别的检查
        # 例如：禁止访问某些敏感ConfigMap
        sensitive_resources = [
            ("secret", "*"),         # 禁止所有secret
            ("configmap", "kubeconfig"),
        ]
        
        for res_type, res_name in sensitive_resources:
            if resource_type == res_type:
                if res_name == "*" or res_name == resource_name:
                    logger.warning(f"拒绝访问敏感资源: {resource_type}/{resource_name}")
                    return False
        
        return True
    
    def get_allowed_namespaces_display(self) -> str:
        """获取允许的namespace列表（用于显示）"""
        if self.allowed_namespaces:
            return ", ".join(sorted(self.allowed_namespaces))
        return "all (except blocked)"
    
    def get_blocked_namespaces_display(self) -> str:
        """获取禁止的namespace列表（用于显示）"""
        return ", ".join(sorted(self.blocked_namespaces))
