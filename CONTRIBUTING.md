# 贡献指南 - 如何添加新产品支持

本文档说明如何为K8s诊断Agent添加新产品的诊断能力。

## 📁 目录结构

```
k8s-diagnostic-agent/
├── products/
│   └── domains.yaml          # 领域和产品注册
├── skills/
│   ├── _template.yaml        # Skills模板
│   ├── platform/             # 平台领域
│   ├── network/              # 网络领域
│   ├── database/             # 数据库领域
│   │   └── mysql.yaml        # MySQL技能
│   ├── middleware/           # 中间件领域
│   └── compute/              # 计算领域
└── agent/
    └── tools/
        ├── _template.py      # Tools模板
        └── mysql_tools.py    # MySQL工具
```

## 🚀 添加新产品的步骤

### 步骤1：注册产品

在 `products/domains.yaml` 中添加你的产品：

```yaml
domains:
  database:  # 所属领域
    products:
      - id: mysql                    # 产品ID（唯一）
        name: 云数据库MySQL           # 显示名称
        namespaces: ["mysql-*"]      # 匹配的namespace模式
        skills: skills/database/mysql.yaml  # Skills文件路径
```

### 步骤2：创建Skills文件

复制 `skills/_template.yaml` 并修改：

```bash
cp skills/_template.yaml skills/database/mysql.yaml
```

编辑文件，添加产品特有的诊断技能：

```yaml
product_id: mysql
product_name: 云数据库MySQL

skills:
  - id: check_mysql_status
    name: 检查MySQL状态
    description: 检查MySQL实例的运行状态和主从同步情况
    tool: list_pods
    params:
      namespace:
        type: string
        required: true
    safe: true
    requires_confirmation: false
```

### 步骤3：创建Tools（可选）

如果需要产品特有的诊断工具，复制模板：

```bash
cp agent/tools/_template.py agent/tools/mysql_tools.py
```

实现你的工具并在 `register_tools()` 中注册：

```python
@tool
def check_mysql_replication(namespace: str, instance: str) -> str:
    """检查MySQL主从同步状态"""
    # 实现逻辑...
    pass

def register_tools():
    return {
        "create_func": create_mysql_tools,
        "domain": "database",
        "product": "mysql",
        "version": "1.0.0"
    }
```

## 📝 Skills字段说明

| 字段 | 必需 | 说明 |
|------|------|------|
| `id` | ✅ | 技能唯一标识 |
| `name` | ✅ | 技能名称 |
| `description` | ✅ | 技能描述（LLM会读取） |
| `tool` | ✅ | 使用的工具名 |
| `params` | ❌ | 参数定义 |
| `safe` | ✅ | 是否无副作用 |
| `requires_confirmation` | ✅ | 是否需要用户确认 |
| `examples` | ❌ | 使用示例 |

## ✅ 检查清单

- [ ] 产品已在 `domains.yaml` 注册
- [ ] Skills文件路径正确
- [ ] 所有技能都有清晰的描述
- [ ] 危险操作设置了 `requires_confirmation: true`
- [ ] 测试过技能是否正常工作

## 🔗 相关文件

- [Skills模板](skills/_template.yaml)
- [Tools模板](agent/tools/_template.py)
- [领域配置](products/domains.yaml)
