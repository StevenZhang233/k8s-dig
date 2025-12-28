"""
Executor组件 - 负责执行诊断步骤（调用MCP工具）
"""
import logging
from typing import Dict, Any, Optional
from mcp import ClientSession

logger = logging.getLogger(__name__)


class Executor:
    """诊断步骤执行器"""
    
    def __init__(self, mcp_session: ClientSession, config: dict):
        """
        初始化Executor
        
        Args:
            mcp_session: MCP客户端会话
            config: 应用配置
        """
        self.mcp = mcp_session
        self.config = config
        
        # 最大工具调用次数（每轮）
        self.max_tools = config.get("agent", {}).get("max_tools_per_iteration", 5)
    
    async def execute_step(
        self,
        action: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        执行单个诊断步骤
        
        Args:
            action: 工具名称
            params: 工具参数
            
        Returns:
            执行结果字典，包含 success, result, error 字段
        """
        logger.info(f"执行: {action} with {params}")
        
        try:
            # 调用MCP工具
            result = await self.mcp.call_tool(action, params)
            
            # 提取文本内容
            text_content = ""
            for content in result.content:
                if hasattr(content, "text"):
                    text_content += content.text
            
            return {
                "success": True,
                "result": text_content,
                "error": None
            }
            
        except Exception as e:
            logger.error(f"执行失败: {action}, 错误: {e}")
            return {
                "success": False,
                "result": None,
                "error": str(e)
            }
    
    async def execute_with_confirmation(
        self,
        action: str,
        params: Dict[str, Any],
        confirm_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        执行需要确认的操作
        
        Args:
            action: 工具名称
            params: 工具参数
            confirm_callback: 确认回调函数
            
        Returns:
            执行结果
        """
        # 检查是否需要确认
        require_confirmation = self.config.get("security", {}).get(
            "require_confirmation", []
        )
        
        if action in require_confirmation:
            if confirm_callback:
                confirmed = await confirm_callback(action, params)
                if not confirmed:
                    return {
                        "success": False,
                        "result": None,
                        "error": "用户拒绝操作"
                    }
                # 添加confirm参数
                params["confirm"] = True
            else:
                return {
                    "success": False,
                    "result": None,
                    "error": f"操作 {action} 需要确认但没有提供确认回调"
                }
        
        return await self.execute_step(action, params)
    
    async def get_available_tools(self) -> list:
        """获取可用的工具列表"""
        result = await self.mcp.list_tools()
        return result.tools
