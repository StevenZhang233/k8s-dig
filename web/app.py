"""
Gradio Web界面 - K8s诊断Agent (Gemini Style)
"""
import asyncio
import logging
import os
from typing import List, Tuple, Optional

import gradio as gr
import yaml

from agent.agent import K8sDiagnosticAgent
from agent.environment import EnvironmentManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 腾讯工业风格CSS
TENCENT_CSS = """
/* 深色科技感背景 */
body, .gradio-container { 
    background: linear-gradient(135deg, #0d1117 0%, #161b22 50%, #0d1117 100%) !important;
    min-height: 100vh;
}

.container { max-width: 900px; margin: auto; padding-top: 2rem; }

/* 标题：腾讯蓝 + 科技感 */
.header { text-align: center; margin-bottom: 2rem; }
.header h1 { 
    color: #00a4ff !important;
    font-size: 2.2rem;
    font-weight: 600;
    letter-spacing: 2px;
    text-shadow: 0 0 20px rgba(0, 164, 255, 0.5);
    -webkit-background-clip: unset !important;
    -webkit-text-fill-color: unset !important;
    background: none !important;
}

/* 聊天窗口 */
.chat-window { 
    height: 65vh !important; 
    border: 1px solid rgba(0, 164, 255, 0.2) !important;
    background: rgba(22, 27, 34, 0.8) !important;
    border-radius: 8px !important;
    box-shadow: 0 0 30px rgba(0, 164, 255, 0.1) !important;
}

/* 消息气泡 */
.message { 
    border-radius: 4px !important;
}
.user-message {
    background: linear-gradient(135deg, #00a4ff 0%, #0078d4 100%) !important;
    color: white !important;
}
.bot-message {
    background: rgba(48, 54, 61, 0.9) !important;
    border: 1px solid rgba(0, 164, 255, 0.3) !important;
    color: #e6edf3 !important;
}

/* 底部输入区 - 工业风格 */
.input-area {
    position: fixed;
    bottom: 20px;
    left: 50%;
    transform: translateX(-50%);
    width: 90%;
    max-width: 800px;
    background: linear-gradient(135deg, #21262d 0%, #161b22 100%);
    border-radius: 8px;
    box-shadow: 0 0 20px rgba(0, 164, 255, 0.15), inset 0 1px 0 rgba(255,255,255,0.05);
    padding: 12px 16px;
    z-index: 1000;
    display: flex;
    align-items: center;
    border: 1px solid rgba(0, 164, 255, 0.3);
}

.input-box {
    border: none !important;
    box-shadow: none !important;
    background: transparent !important;
    flex-grow: 1;
}
.input-box textarea {
    font-size: 15px !important;
    color: #e6edf3 !important;
    background: transparent !important;
}
.input-box textarea::placeholder {
    color: #8b949e !important;
}

/* 按钮 - 科技感 */
.action-btn {
    border-radius: 6px !important;
    width: 36px !important;
    height: 36px !important;
    min-width: 36px !important;
    padding: 0 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    background: rgba(0, 164, 255, 0.1) !important;
    color: #00a4ff !important;
    border: 1px solid rgba(0, 164, 255, 0.3) !important;
    transition: all 0.2s ease !important;
}
.action-btn:hover { 
    background: rgba(0, 164, 255, 0.2) !important; 
    box-shadow: 0 0 10px rgba(0, 164, 255, 0.3) !important;
}
.send-btn { 
    background: linear-gradient(135deg, #00a4ff 0%, #0078d4 100%) !important; 
    color: white !important;
    border: none !important;
}
.send-btn:hover {
    box-shadow: 0 0 15px rgba(0, 164, 255, 0.5) !important;
}

/* 环境面板 - 工业风格 */
.env-panel {
    position: fixed;
    bottom: 100px;
    left: 50%;
    transform: translateX(-50%);
    width: 90%;
    max-width: 800px;
    background: linear-gradient(135deg, #21262d 0%, #161b22 100%);
    border-radius: 8px;
    box-shadow: 0 0 30px rgba(0, 164, 255, 0.2);
    padding: 20px;
    z-index: 999;
    border: 1px solid rgba(0, 164, 255, 0.3);
}

/* 面板内文字 */
.env-panel label, .env-panel span, .env-panel p {
    color: #e6edf3 !important;
}

/* 下拉框 */
.env-panel select, .env-panel input {
    background: #21262d !important;
    border: 1px solid rgba(0, 164, 255, 0.3) !important;
    color: #e6edf3 !important;
    border-radius: 4px !important;
}

/* 连接按钮 */
.env-panel button[variant="primary"] {
    background: linear-gradient(135deg, #00a4ff 0%, #0078d4 100%) !important;
    border: none !important;
}

.hidden { display: none !important; }
"""

class DiagnosticWebApp:
    """K8s诊断Web应用 (Gemini Style)"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        self.env_manager = EnvironmentManager(config_path)
        self.agent: Optional[K8sDiagnosticAgent] = None
        self.current_env_name = self.env_manager.default_env or "未选择"
    
    def _load_config(self, config_path: str) -> dict:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def get_environment_choices(self) -> List[str]:
        return [f"{env.name}" for env in self.env_manager.list_environments()]
    
    def switch_environment(self, env_name: str) -> str:
        if not env_name: return "⚠️ 请选择环境"
        
        # 清理名称（如果是从dropdown直接选的纯名称）
        clean_name = env_name.split(" ")[0]
        
        if self.env_manager.switch_environment(clean_name):
            self.agent = K8sDiagnosticAgent()
            self.agent.initialize(clean_name)
            self.current_env_name = clean_name
            
            # 测试连接
            result = self.env_manager.test_connection()
            status = "✅" if result["success"] else "⚠️"
            return f"{status} 当前环境: {clean_name}"
        return f"❌ 切换失败"

    async def chat_response(self, message: str, history: List):
        """处理聊天"""
        if not message.strip(): 
            yield history, ""
            return
        
        if not self.agent:
            # 尝试初始化默认环境
            if self.env_manager.current_env:
                self.agent = K8sDiagnosticAgent()
                self.agent.initialize(self.env_manager.current_env)
            else:
                history.append((message, "⚠️ 请先点击左下角 '+' 号选择并连接一个环境。"))
                yield history, ""
                return
        
        history.append((message, None))
        yield history, ""
        
        try:
            report = await self.agent.diagnose(message)
            history[-1] = (message, report)
            yield history, ""
        except Exception as e:
            logger.exception("诊断失败")
            history[-1] = (message, f"❌ 诊断出错: {str(e)}")
            yield history, ""

    def create_ui(self) -> gr.Blocks:
        with gr.Blocks(title="K8s Intelligence") as app:
            
            # 状态存储
            env_panel_visible = gr.State(False)
            
            # 这里的布局稍微有点hacky，为了模拟Gemini布局
            with gr.Column(elem_classes=["container"]):
                with gr.Column(elem_classes=["header"]):
                    gr.Markdown("# ✨ K8s Intelligence")
                    current_env_display = gr.Markdown(f"⚪ 当前环境: {self.current_env_name}")
                
                # 聊天窗口
                chatbot = gr.Chatbot(
                    label=None,
                    show_label=False,
                    elem_classes=["chat-window"],
                    avatar_images=(None, "https://www.gstatic.com/lamda/images/gemini_sparkle_v002_d4735304ff6292a690345.svg"),
                    height=600
                )
            
            # 环境选择面板（默认隐藏，位置绝对定位）
            with gr.Group(visible=False, elem_classes=["env-panel"]) as env_panel:
                gr.Markdown("### 🌐 环境切换")
                with gr.Row():
                    env_dropdown = gr.Dropdown(
                        choices=self.get_environment_choices(),
                        label="选择环境",
                        value=self.env_manager.default_env,
                        scale=3
                    )
                    connect_btn = gr.Button("连接", variant="primary", scale=1)
                
                connect_res = gr.Markdown("")
                
                # 连接逻辑
                connect_btn.click(
                    self.switch_environment,
                    inputs=[env_dropdown],
                    outputs=[current_env_display]
                ).then(
                    lambda: gr.update(visible=False), None, [env_panel] # 连接后隐藏面板
                )

            # 底部输入区
            with gr.Row(elem_classes=["input-area"]):
                # ➕ 按钮
                plus_btn = gr.Button("➕", elem_classes=["action-btn"])
                
                # 输入框
                msg_input = gr.Textbox(
                    show_label=False,
                    placeholder="输入问题，例如：pod为什么启动失败？",
                    elem_classes=["input-box"],
                    container=False,
                    lines=1,
                    scale=10
                )
                
                # 发送按钮
                send_btn = gr.Button("➤", elem_classes=["action-btn", "send-btn"])
            
            # 事件绑定
            
            # 1. 切换面板显示
            def toggle_panel(vis):
                return not vis, gr.update(visible=not vis)

            plus_btn.click(
                toggle_panel,
                inputs=[env_panel_visible],
                outputs=[env_panel_visible, env_panel]
            )

            # 2. 发送消息
            msg_input.submit(
                self.chat_response,
                inputs=[msg_input, chatbot],
                outputs=[chatbot, msg_input]
            )
            
            send_btn.click(
                self.chat_response,
                inputs=[msg_input, chatbot],
                outputs=[chatbot, msg_input]
            )

        return app

def main():
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    app = DiagnosticWebApp()
    ui = app.create_ui()
    
    web_config = app.config.get("web", {})
    
    # Gradio 6.0: theme和css移动到launch
    ui.launch(
        server_name=web_config.get("host", "127.0.0.1"),
        server_port=web_config.get("port", 7860),
        share=False,
        show_error=True,
        theme=gr.themes.Soft(),
        css=TENCENT_CSS
    )

if __name__ == "__main__":
    main()
