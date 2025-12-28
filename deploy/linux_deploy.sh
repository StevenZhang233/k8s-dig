#!/bin/bash
# ============================================================
# K8s Diagnostic Agent - Linux 部署脚本
# 适用于: x86_64 Linux 服务器
# ============================================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ============================================================
# 配置变量
# ============================================================
APP_NAME="k8s-diagnostic-agent"
APP_DIR="/opt/${APP_NAME}"
SERVICE_USER="k8sdiag"
PYTHON_VERSION="3.11"
WEB_PORT=7860

# ============================================================
# 检查运行环境
# ============================================================
check_requirements() {
    log_info "检查系统环境..."
    
    # 检查是否为root用户
    if [[ $EUID -ne 0 ]]; then
        log_error "请使用 root 用户运行此脚本"
        exit 1
    fi
    
    # 检查架构
    ARCH=$(uname -m)
    if [[ "$ARCH" != "x86_64" ]]; then
        log_error "此脚本仅支持 x86_64 架构，当前架构: $ARCH"
        exit 1
    fi
    
    # 检查系统
    if [[ -f /etc/debian_version ]]; then
        OS="debian"
        PKG_MANAGER="apt-get"
    elif [[ -f /etc/redhat-release ]]; then
        OS="redhat"
        PKG_MANAGER="yum"
    else
        log_warn "未识别的操作系统，将尝试继续..."
        PKG_MANAGER="apt-get"
    fi
    
    log_success "系统检查通过: $OS ($ARCH)"
}

# ============================================================
# 安装系统依赖
# ============================================================
install_dependencies() {
    log_info "安装系统依赖..."
    
    if [[ "$PKG_MANAGER" == "apt-get" ]]; then
        apt-get update
        apt-get install -y \
            python3 \
            python3-pip \
            python3-venv \
            git \
            curl \
            wget
    else
        yum install -y \
            python3 \
            python3-pip \
            git \
            curl \
            wget
    fi
    
    log_success "系统依赖安装完成"
}

# ============================================================
# 创建应用用户
# ============================================================
setup_user() {
    log_info "创建应用用户..."
    
    if id "$SERVICE_USER" &>/dev/null; then
        log_warn "用户 $SERVICE_USER 已存在"
    else
        useradd -r -s /bin/false -d "$APP_DIR" "$SERVICE_USER"
        log_success "用户 $SERVICE_USER 创建成功"
    fi
}

# ============================================================
# 部署应用代码
# ============================================================
deploy_code() {
    log_info "部署应用代码..."
    
    # 创建目录
    mkdir -p "$APP_DIR"
    
    # 如果当前目录有代码，复制过去
    if [[ -f "./requirements.txt" ]]; then
        cp -r ./* "$APP_DIR/"
        log_info "从当前目录复制代码"
    # 否则从GitHub克隆
    elif [[ -n "$GITHUB_REPO" ]]; then
        log_info "从GitHub克隆代码..."
        git clone "$GITHUB_REPO" "$APP_DIR"
    else
        log_error "未找到代码源，请设置 GITHUB_REPO 环境变量或在项目目录运行"
        exit 1
    fi
    
    chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"
    log_success "代码部署完成"
}

# ============================================================
# 创建Python虚拟环境并安装依赖
# ============================================================
setup_python_env() {
    log_info "设置Python虚拟环境..."
    
    cd "$APP_DIR"
    
    # 创建虚拟环境
    python3 -m venv venv
    
    # 激活并安装依赖
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    
    log_success "Python环境设置完成"
}

# ============================================================
# 创建配置文件
# ============================================================
setup_config() {
    log_info "配置应用..."
    
    cd "$APP_DIR"
    
    # 创建.env文件（如果不存在）
    if [[ ! -f ".env" ]]; then
        if [[ -f ".env.example" ]]; then
            cp .env.example .env
            log_warn "已创建 .env 文件，请编辑填写 API Key"
        fi
    fi
    
    # 更新config.yaml中的host为0.0.0.0以允许公网访问
    if [[ -f "config.yaml" ]]; then
        sed -i 's/host: "127.0.0.1"/host: "0.0.0.0"/g' config.yaml
        sed -i 's/host: 127.0.0.1/host: 0.0.0.0/g' config.yaml
    fi
    
    log_success "配置完成"
}

# ============================================================
# 创建Systemd服务
# ============================================================
setup_systemd() {
    log_info "创建Systemd服务..."
    
    cat > /etc/systemd/system/${APP_NAME}.service << EOF
[Unit]
Description=K8s Diagnostic Agent
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/venv/bin"
ExecStart=${APP_DIR}/venv/bin/python -m web.app
Restart=always
RestartSec=10

# 日志
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${APP_NAME}

# 安全设置
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

    # 重载systemd配置
    systemctl daemon-reload
    
    # 启用服务
    systemctl enable ${APP_NAME}
    
    log_success "Systemd服务创建完成"
}

# ============================================================
# 配置防火墙
# ============================================================
setup_firewall() {
    log_info "配置防火墙..."
    
    # 尝试使用firewalld
    if command -v firewall-cmd &> /dev/null; then
        firewall-cmd --permanent --add-port=${WEB_PORT}/tcp
        firewall-cmd --reload
        log_success "Firewalld规则添加完成"
    # 尝试使用ufw
    elif command -v ufw &> /dev/null; then
        ufw allow ${WEB_PORT}/tcp
        log_success "UFW规则添加完成"
    # 尝试使用iptables
    elif command -v iptables &> /dev/null; then
        iptables -A INPUT -p tcp --dport ${WEB_PORT} -j ACCEPT
        log_success "iptables规则添加完成"
    else
        log_warn "未检测到防火墙工具，请手动开放端口 ${WEB_PORT}"
    fi
}

# ============================================================
# 启动服务
# ============================================================
start_service() {
    log_info "启动服务..."
    
    systemctl start ${APP_NAME}
    
    # 等待服务启动
    sleep 3
    
    if systemctl is-active --quiet ${APP_NAME}; then
        log_success "服务启动成功！"
    else
        log_error "服务启动失败，请检查日志: journalctl -u ${APP_NAME}"
        exit 1
    fi
}

# ============================================================
# 显示部署信息
# ============================================================
print_info() {
    echo ""
    echo "============================================================"
    echo -e "${GREEN}  K8s Diagnostic Agent 部署完成!${NC}"
    echo "============================================================"
    echo ""
    echo "  📁 安装目录: ${APP_DIR}"
    echo "  🌐 访问地址: http://<服务器IP>:${WEB_PORT}"
    echo ""
    echo "  常用命令:"
    echo "    启动服务:   systemctl start ${APP_NAME}"
    echo "    停止服务:   systemctl stop ${APP_NAME}"
    echo "    重启服务:   systemctl restart ${APP_NAME}"
    echo "    查看状态:   systemctl status ${APP_NAME}"
    echo "    查看日志:   journalctl -u ${APP_NAME} -f"
    echo ""
    echo "  ⚠️  请编辑 ${APP_DIR}/.env 文件，填写 GOOGLE_API_KEY"
    echo ""
    echo "============================================================"
}

# ============================================================
# 主函数
# ============================================================
main() {
    echo ""
    echo "============================================================"
    echo "  K8s Diagnostic Agent - 自动部署脚本"
    echo "============================================================"
    echo ""
    
    check_requirements
    install_dependencies
    setup_user
    deploy_code
    setup_python_env
    setup_config
    setup_systemd
    setup_firewall
    start_service
    print_info
}

# 运行主函数
main "$@"
