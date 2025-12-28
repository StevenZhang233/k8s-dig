# Linux 服务器部署指南

## 快速部署

### 方式1：一键部署（推荐）

```bash
# 1. 上传代码到服务器
scp -r k8s-diagnostic-agent/ user@your-server:/tmp/

# 2. SSH登录服务器
ssh root@your-server

# 3. 进入代码目录并运行部署脚本
cd /tmp/k8s-diagnostic-agent
chmod +x deploy/linux_deploy.sh
./deploy/linux_deploy.sh
```

### 方式2：从GitHub直接部署

```bash
# SSH登录服务器后执行
curl -sSL https://raw.githubusercontent.com/StevenZhang233/k8s-dig/main/deploy/linux_deploy.sh | \
  GITHUB_REPO="https://github.com/StevenZhang233/k8s-dig.git" bash
```

## 部署后配置

### 1. 配置API Key

```bash
# 编辑环境变量文件
vi /opt/k8s-diagnostic-agent/.env

# 填写你的 Google API Key
GOOGLE_API_KEY=AIzaSy...
```

### 2. 配置K8s集群

```bash
# 编辑配置文件
vi /opt/k8s-diagnostic-agent/config.yaml

# 修改environments部分，添加你的K8s集群信息
```

### 3. 重启服务

```bash
systemctl restart k8s-diagnostic-agent
```

## 服务管理

```bash
# 启动
systemctl start k8s-diagnostic-agent

# 停止
systemctl stop k8s-diagnostic-agent

# 重启
systemctl restart k8s-diagnostic-agent

# 查看状态
systemctl status k8s-diagnostic-agent

# 查看日志（实时）
journalctl -u k8s-diagnostic-agent -f

# 查看最近100行日志
journalctl -u k8s-diagnostic-agent -n 100
```

## 访问Web界面

部署完成后，访问：
```
http://<服务器公网IP>:7860
```

## 常见问题

### 端口无法访问
```bash
# 检查防火墙
firewall-cmd --list-ports
# 或
ufw status

# 手动开放端口
firewall-cmd --permanent --add-port=7860/tcp && firewall-cmd --reload
# 或
ufw allow 7860/tcp
```

### 服务启动失败
```bash
# 查看详细日志
journalctl -u k8s-diagnostic-agent --no-pager

# 手动测试运行
cd /opt/k8s-diagnostic-agent
source venv/bin/activate
python -m web.app
```

### Python依赖问题
```bash
# 重新安装依赖
cd /opt/k8s-diagnostic-agent
source venv/bin/activate
pip install -r requirements.txt
```
