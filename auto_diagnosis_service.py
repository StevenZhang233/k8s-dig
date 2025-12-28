#!/usr/bin/env python
"""
自动诊断服务 - 可以作为后台服务运行
支持两种模式：
1. 轮询模式：定期从产品市场API拉取失败部署
2. Webhook模式：实时接收产品市场推送的部署事件
"""
import asyncio
import logging
import os
import argparse
from pathlib import Path

import yaml
import uvicorn
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_config(config_path: str = "config/marketplace.yaml") -> dict:
    """加载配置"""
    path = Path(config_path)
    if not path.exists():
        logger.warning(f"配置文件不存在: {path}")
        return {}
    
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


async def run_polling_mode(config: dict):
    """运行轮询模式"""
    from agent.agent import K8sDiagnosticAgent
    from integrations.marketplace import (
        create_marketplace_client,
        AutoDiagnosisScheduler
    )
    
    logger.info("启动轮询模式...")
    
    # 初始化组件
    agent = K8sDiagnosticAgent()
    marketplace_client = create_marketplace_client()
    
    marketplace_config = config.get("marketplace", {})
    
    scheduler = AutoDiagnosisScheduler(
        marketplace_client=marketplace_client,
        agent=agent,
        config=marketplace_config
    )
    
    # 启动调度器
    await scheduler.start()


def run_webhook_mode(config: dict):
    """运行Webhook模式"""
    from agent.agent import K8sDiagnosticAgent
    from integrations.webhook import create_webhook_app
    
    logger.info("启动Webhook模式...")
    
    # 初始化Agent
    agent = K8sDiagnosticAgent()
    
    # 获取Webhook配置
    webhook_config = config.get("marketplace", {}).get("webhook", {})
    webhook_secret = os.getenv(
        "MARKETPLACE_WEBHOOK_SECRET",
        webhook_config.get("secret", "default-secret")
    )
    listen_port = webhook_config.get("listen_port", 8080)
    
    # 创建Webhook应用
    app = create_webhook_app(agent, webhook_secret)
    
    # 启动服务
    uvicorn.run(app, host="0.0.0.0", port=listen_port)


def main():
    parser = argparse.ArgumentParser(description="K8s自动诊断服务")
    parser.add_argument(
        "--mode",
        choices=["polling", "webhook", "both"],
        default="polling",
        help="运行模式: polling(轮询), webhook(实时), both(两者)"
    )
    parser.add_argument(
        "--config",
        default="config/marketplace.yaml",
        help="配置文件路径"
    )
    
    args = parser.parse_args()
    config = load_config(args.config)
    
    if args.mode == "polling":
        asyncio.run(run_polling_mode(config))
    elif args.mode == "webhook":
        run_webhook_mode(config)
    elif args.mode == "both":
        # TODO: 同时运行两种模式
        logger.info("同时运行轮询和Webhook模式...")
        # 可以使用多进程或在webhook服务中嵌入轮询任务
        run_webhook_mode(config)


if __name__ == "__main__":
    main()
