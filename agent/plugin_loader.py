"""
插件加载器 - 动态加载产品Skills和Tools
"""
import os
import importlib
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

import yaml

logger = logging.getLogger(__name__)


class PluginLoader:
    """插件加载器"""
    
    def __init__(self, base_path: str = "."):
        self.base_path = Path(base_path)
        self.domains: Dict[str, Any] = {}
        self.products: Dict[str, Any] = {}
        self.skills: Dict[str, List] = {}
        self.tools: Dict[str, List] = {}
    
    def load_domains(self, domains_file: str = "products/domains.yaml"):
        """加载领域配置"""
        domains_path = self.base_path / domains_file
        
        if not domains_path.exists():
            logger.warning(f"领域配置文件不存在: {domains_path}")
            return
        
        with open(domains_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        self.domains = config.get("domains", {})
        
        # 解析产品
        for domain_id, domain_info in self.domains.items():
            for product in domain_info.get("products", []):
                product_id = product["id"]
                self.products[product_id] = {
                    "domain": domain_id,
                    "domain_name": domain_info["name"],
                    **product
                }
        
        logger.info(f"加载了 {len(self.domains)} 个领域, {len(self.products)} 个产品")
    
    def load_skills(self, product_id: Optional[str] = None):
        """
        加载产品Skills
        
        Args:
            product_id: 指定产品ID，为None则加载所有
        """
        products_to_load = (
            [self.products[product_id]] 
            if product_id and product_id in self.products 
            else self.products.values()
        )
        
        for product in products_to_load:
            pid = product["id"]
            skills_file = product.get("skills")
            
            if not skills_file:
                continue
            
            skills_path = self.base_path / skills_file
            
            if not skills_path.exists():
                logger.debug(f"Skills文件不存在: {skills_path}")
                continue
            
            try:
                with open(skills_path, 'r', encoding='utf-8') as f:
                    skills_config = yaml.safe_load(f)
                
                self.skills[pid] = skills_config.get("skills", [])
                logger.info(f"加载产品 {pid} 的 {len(self.skills[pid])} 个技能")
                
            except Exception as e:
                logger.error(f"加载Skills失败 {skills_path}: {e}")
    
    def load_tools(self, product_id: Optional[str] = None):
        """
        加载产品Tools
        
        Args:
            product_id: 指定产品ID，为None则加载所有
        """
        tools_dir = self.base_path / "agent" / "tools"
        
        if not tools_dir.exists():
            return
        
        # 查找所有工具模块
        for tool_file in tools_dir.glob("*.py"):
            if tool_file.name.startswith("_"):
                continue
            
            module_name = tool_file.stem
            
            try:
                # 动态导入模块
                module = importlib.import_module(f"agent.tools.{module_name}")
                
                # 检查是否有注册函数
                if hasattr(module, "register_tools"):
                    tool_info = module.register_tools()
                    tool_product = tool_info.get("product", module_name)
                    
                    if product_id and tool_product != product_id:
                        continue
                    
                    self.tools[tool_product] = tool_info
                    logger.info(f"注册工具模块: {module_name} -> {tool_product}")
                    
            except Exception as e:
                logger.debug(f"加载工具模块失败 {module_name}: {e}")
    
    def get_product_skills(self, product_id: str) -> List[Dict]:
        """获取产品的所有技能"""
        return self.skills.get(product_id, [])
    
    def get_product_tools(self, product_id: str, env_manager, config: dict) -> List:
        """获取产品的所有工具实例"""
        tool_info = self.tools.get(product_id)
        
        if not tool_info:
            return []
        
        create_func = tool_info.get("create_func")
        if create_func:
            return create_func(env_manager, config)
        
        return []
    
    def get_all_skills_for_llm(self) -> str:
        """获取所有技能的描述（用于LLM提示词）"""
        lines = []
        
        for pid, skills in self.skills.items():
            product = self.products.get(pid, {})
            lines.append(f"\n## {product.get('name', pid)}")
            
            for skill in skills:
                lines.append(f"- **{skill['name']}** ({skill['id']}): {skill['description']}")
        
        return "\n".join(lines)
    
    def list_products_by_domain(self, domain_id: str) -> List[Dict]:
        """列出某领域下的所有产品"""
        return [
            p for p in self.products.values() 
            if p.get("domain") == domain_id
        ]
    
    def match_product_by_namespace(self, namespace: str) -> Optional[Dict]:
        """根据namespace匹配产品"""
        import fnmatch
        
        for product in self.products.values():
            patterns = product.get("namespaces", [])
            for pattern in patterns:
                if fnmatch.fnmatch(namespace, pattern):
                    return product
        
        return None


# 单例
_loader: Optional[PluginLoader] = None


def get_plugin_loader(base_path: str = ".") -> PluginLoader:
    """获取插件加载器单例"""
    global _loader
    if _loader is None:
        _loader = PluginLoader(base_path)
        _loader.load_domains()
        _loader.load_skills()
        _loader.load_tools()
    return _loader
