# K8s Diagnostic Agent

基于 **LangGraph + MCP** 的 K8s 私有云环境智能诊断框架。

## ✨ 特性

- 🤖 **LangGraph Plan-Execute** - 自主规划诊断步骤，动态调整策略
- 🌐 **多环境支持** - 一个Agent管理多个私有云K8s集群
- 🎨 **Gradio Web GUI** - 美观的Web界面，支持环境切换和对话式诊断
- 🔧 **Skills配置化** - 技能以YAML定义，易于扩展
- 🔒 **安全控制** - namespace白名单、exec命令白名单、危险操作确认

## 📦 项目结构

```
k8s-diagnostic-agent/
├── agent/                  # LangGraph Agent
│   ├── agent.py           # 主程序（LangGraph状态机）
│   ├── environment.py     # 多环境管理器
│   └── tools.py           # K8s诊断工具
├── mcp_server/            # MCP Server（可选）
├── web/
│   └── app.py             # Gradio Web界面
├── skills/                # Skills配置
├── config.yaml            # 全局配置
└── requirements.txt
```

## 🚀 快速开始

### 1. 安装依赖

```bash
cd k8s-diagnostic-agent
pip install -r requirements.txt
```

### 2. 配置环境

```bash
cp .env.example .env
# 编辑 .env，填写 OPENAI_API_KEY
```

### 3. 配置K8s环境

编辑 `config.yaml`，添加你的私有云环境：

```yaml
environments:
  clusters:
    - name: env-prod
      display_name: 生产环境
      master_ip: 10.0.1.100
      kubeconfig: ~/.kube/config-prod
```

### 4. 启动Web界面

```bash
python -m web.app
```

访问 http://localhost:7860

## 🎮 使用方式

### Web界面

1. 选择目标环境
2. 输入问题描述，如 "产品A的数据库初始化失败了"
3. Agent自动诊断并生成报告

### 命令行

```python
from agent.agent import K8sDiagnosticAgent

agent = K8sDiagnosticAgent()
agent.initialize("env-prod")

report = await agent.diagnose("db-init job失败了")
print(report)
```

## 🔒 安全说明

- 所有K8s操作受白名单限制
- `kube-system` 等系统namespace被禁止访问
- exec命令仅允许诊断类（env, ps, cat等）
- 危险操作（restart_pod）需确认

## 📋 支持的诊断场景

- ✅ Pod CrashLoopBackOff
- ✅ Pod Pending（调度失败）
- ✅ ImagePullBackOff
- ✅ Job失败（DBSql等）
- ✅ 连接超时问题
- ✅ 资源配额问题
