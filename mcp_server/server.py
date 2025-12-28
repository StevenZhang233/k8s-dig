"""
MCP Server for K8s Diagnostic Agent
提供K8s诊断相关的工具，供Agent调用
"""
import asyncio
import logging
import yaml
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .tools.pod_tools import PodTools
from .tools.job_tools import JobTools
from .tools.debug_tools import DebugTools
from .security.whitelist import WhitelistChecker
from .security.audit import AuditLogger

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class K8sDiagnosticMCPServer:
    """K8s诊断MCP Server"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        self.server = Server("k8s-diagnostic")
        
        # 初始化工具类
        self.pod_tools = PodTools(self.config)
        self.job_tools = JobTools(self.config)
        self.debug_tools = DebugTools(self.config)
        
        # 安全组件
        self.whitelist = WhitelistChecker(self.config)
        self.audit = AuditLogger(self.config)
        
        # 注册工具
        self._register_tools()
    
    def _load_config(self, config_path: str) -> dict:
        """加载配置文件"""
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _register_tools(self):
        """注册所有MCP工具"""
        
        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            """列出所有可用工具"""
            return [
                # ===== 查询类工具 =====
                Tool(
                    name="list_pods",
                    description="列出指定namespace下所有Pod的状态",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "namespace": {
                                "type": "string",
                                "description": "K8s namespace名称"
                            }
                        },
                        "required": ["namespace"]
                    }
                ),
                Tool(
                    name="describe_pod",
                    description="获取Pod的详细描述，包括事件、状态、容器信息",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "namespace": {"type": "string"},
                            "pod_name": {"type": "string"}
                        },
                        "required": ["namespace", "pod_name"]
                    }
                ),
                Tool(
                    name="get_pod_logs",
                    description="获取Pod的日志输出",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "namespace": {"type": "string"},
                            "pod_name": {"type": "string"},
                            "tail_lines": {
                                "type": "integer",
                                "default": 100,
                                "description": "获取最近N行日志"
                            },
                            "container": {
                                "type": "string",
                                "description": "容器名称（多容器Pod时需要）"
                            },
                            "previous": {
                                "type": "boolean",
                                "default": False,
                                "description": "是否获取上次崩溃的日志"
                            }
                        },
                        "required": ["namespace", "pod_name"]
                    }
                ),
                Tool(
                    name="get_events",
                    description="获取namespace下的K8s事件",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "namespace": {"type": "string"},
                            "field_selector": {
                                "type": "string",
                                "description": "事件过滤条件"
                            }
                        },
                        "required": ["namespace"]
                    }
                ),
                # ===== Job相关工具 =====
                Tool(
                    name="list_jobs",
                    description="列出namespace下所有Job的状态",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "namespace": {"type": "string"}
                        },
                        "required": ["namespace"]
                    }
                ),
                Tool(
                    name="describe_job",
                    description="获取Job的详细信息",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "namespace": {"type": "string"},
                            "job_name": {"type": "string"}
                        },
                        "required": ["namespace", "job_name"]
                    }
                ),
                Tool(
                    name="get_job_logs",
                    description="获取Job的执行日志",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "namespace": {"type": "string"},
                            "job_name": {"type": "string"}
                        },
                        "required": ["namespace", "job_name"]
                    }
                ),
                # ===== 调试工具 =====
                Tool(
                    name="exec_in_pod",
                    description="在Pod内执行诊断命令（仅限白名单命令如: env, ps, cat, ls, df, netstat等）",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "namespace": {"type": "string"},
                            "pod_name": {"type": "string"},
                            "command": {
                                "type": "string",
                                "description": "要执行的诊断命令"
                            },
                            "container": {"type": "string"}
                        },
                        "required": ["namespace", "pod_name", "command"]
                    }
                ),
                # ===== 资源查看 =====
                Tool(
                    name="get_configmap",
                    description="获取ConfigMap的内容",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "namespace": {"type": "string"},
                            "name": {"type": "string"}
                        },
                        "required": ["namespace", "name"]
                    }
                ),
                Tool(
                    name="get_deployment",
                    description="获取Deployment的详细信息",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "namespace": {"type": "string"},
                            "name": {"type": "string"}
                        },
                        "required": ["namespace", "name"]
                    }
                ),
                # ===== 操作类工具 =====
                Tool(
                    name="restart_pod",
                    description="删除Pod触发重建（需要确认）",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "namespace": {"type": "string"},
                            "pod_name": {"type": "string"},
                            "confirm": {
                                "type": "boolean",
                                "description": "确认执行此操作"
                            }
                        },
                        "required": ["namespace", "pod_name", "confirm"]
                    }
                ),
            ]
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            """处理工具调用"""
            try:
                # 1. 安全检查
                namespace = arguments.get("namespace", "")
                if not self.whitelist.check_namespace(namespace):
                    return [TextContent(
                        type="text",
                        text=f"❌ 安全错误: namespace '{namespace}' 不在允许列表中"
                    )]
                
                # 2. 记录审计日志
                self.audit.log(name, arguments)
                
                # 3. 执行工具
                result = await self._execute_tool(name, arguments)
                
                return [TextContent(type="text", text=result)]
                
            except Exception as e:
                logger.error(f"工具执行失败: {name}, 错误: {e}")
                return [TextContent(
                    type="text", 
                    text=f"❌ 执行失败: {str(e)}"
                )]
    
    async def _execute_tool(self, name: str, args: dict) -> str:
        """执行具体的工具"""
        # Pod相关
        if name == "list_pods":
            return await self.pod_tools.list_pods(args["namespace"])
        elif name == "describe_pod":
            return await self.pod_tools.describe_pod(
                args["namespace"], args["pod_name"]
            )
        elif name == "get_pod_logs":
            return await self.pod_tools.get_logs(
                args["namespace"],
                args["pod_name"],
                args.get("tail_lines", 100),
                args.get("container"),
                args.get("previous", False)
            )
        elif name == "get_events":
            return await self.pod_tools.get_events(
                args["namespace"],
                args.get("field_selector")
            )
        
        # Job相关
        elif name == "list_jobs":
            return await self.job_tools.list_jobs(args["namespace"])
        elif name == "describe_job":
            return await self.job_tools.describe_job(
                args["namespace"], args["job_name"]
            )
        elif name == "get_job_logs":
            return await self.job_tools.get_logs(
                args["namespace"], args["job_name"]
            )
        
        # 调试相关
        elif name == "exec_in_pod":
            # 检查命令白名单
            if not self.whitelist.check_exec_command(args["command"]):
                return f"❌ 安全错误: 命令 '{args['command']}' 不在允许的诊断命令列表中"
            return await self.debug_tools.exec_in_pod(
                args["namespace"],
                args["pod_name"],
                args["command"],
                args.get("container")
            )
        
        # 资源查看
        elif name == "get_configmap":
            return await self.pod_tools.get_configmap(
                args["namespace"], args["name"]
            )
        elif name == "get_deployment":
            return await self.pod_tools.get_deployment(
                args["namespace"], args["name"]
            )
        
        # 操作类
        elif name == "restart_pod":
            if not args.get("confirm"):
                return "⚠️ 此操作需要确认。请将confirm参数设置为true来确认重启Pod"
            return await self.pod_tools.restart_pod(
                args["namespace"], args["pod_name"]
            )
        
        else:
            return f"❌ 未知工具: {name}"
    
    async def run(self):
        """运行MCP Server"""
        logger.info("启动K8s诊断MCP Server...")
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream, 
                write_stream,
                self.server.create_initialization_options()
            )


def main():
    """入口函数"""
    server = K8sDiagnosticMCPServer()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
