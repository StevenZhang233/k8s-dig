"""
审计日志记录
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class AuditLogger:
    """审计日志记录器"""
    
    def __init__(self, config: dict):
        self.config = config
        audit_config = config.get("audit", {})
        
        self.enabled = audit_config.get("enabled", True)
        self.log_path = Path(audit_config.get("log_path", "./logs/audit.log"))
        
        # 确保日志目录存在
        if self.enabled:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
    
    def log(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: Optional[str] = None,
        user: str = "agent",
        success: bool = True
    ):
        """
        记录审计日志
        
        Args:
            tool_name: 工具名称
            arguments: 工具参数
            result: 执行结果（可选）
            user: 操作用户
            success: 是否成功
        """
        if not self.enabled:
            return
        
        # 构建审计记录
        record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "user": user,
            "tool": tool_name,
            "arguments": self._sanitize_arguments(arguments),
            "success": success,
        }
        
        if result:
            # 截断过长的结果
            max_length = 1000
            if len(result) > max_length:
                record["result"] = result[:max_length] + "... (truncated)"
            else:
                record["result"] = result
        
        # 写入日志文件
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"写入审计日志失败: {e}")
        
        # 同时记录到标准日志
        log_msg = f"AUDIT: {user} called {tool_name} with {arguments}"
        if success:
            logger.info(log_msg)
        else:
            logger.warning(log_msg + " (FAILED)")
    
    def _sanitize_arguments(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        清理敏感参数
        
        对于敏感字段（如密码），用 *** 替换
        """
        sanitized = {}
        sensitive_keys = ["password", "token", "secret", "key", "credential"]
        
        for key, value in arguments.items():
            key_lower = key.lower()
            
            # 检查是否是敏感字段
            is_sensitive = any(s in key_lower for s in sensitive_keys)
            
            if is_sensitive and value:
                sanitized[key] = "***"
            else:
                sanitized[key] = value
        
        return sanitized
    
    def log_security_event(
        self,
        event_type: str,
        details: Dict[str, Any],
        severity: str = "warning"
    ):
        """
        记录安全事件
        
        Args:
            event_type: 事件类型（如 "namespace_blocked", "command_rejected"）
            details: 事件详情
            severity: 严重级别 (info, warning, error)
        """
        if not self.enabled:
            return
        
        record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "type": "security_event",
            "event_type": event_type,
            "severity": severity,
            "details": details
        }
        
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"写入安全事件日志失败: {e}")
        
        # 根据严重级别记录
        if severity == "error":
            logger.error(f"SECURITY: {event_type} - {details}")
        elif severity == "warning":
            logger.warning(f"SECURITY: {event_type} - {details}")
        else:
            logger.info(f"SECURITY: {event_type} - {details}")
    
    def get_recent_logs(self, count: int = 50) -> list:
        """
        获取最近的审计日志
        
        Args:
            count: 要获取的记录数
            
        Returns:
            审计记录列表
        """
        if not self.log_path.exists():
            return []
        
        records = []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in lines[-count:]:
                    try:
                        records.append(json.loads(line.strip()))
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"读取审计日志失败: {e}")
        
        return records
