<div align="center">

# ChatMock

**让 Codex 在你喜爱的聊天应用和编程工具中运行**

[中文文档](README_CN.md) | [English](README.md)

[![PyPI](https://img.shields.io/pypi/v/chatmock?color=blue&label=pypi)](https://pypi.org/project/chatmock/)
[![Python](https://img.shields.io/pypi/pyversions/chatmock)](https://pypi.org/project/chatmock/)
[![License](https://img.shields.io/github/license/RayBytes/ChatMock)](LICENSE)
[![Stars](https://img.shields.io/github/stars/RayBytes/ChatMock?style=flat)](https://github.com/RayBytes/ChatMock/stargazers)
[![Last Commit](https://img.shields.io/github/last-commit/RayBytes/ChatMock)](https://github.com/RayBytes/ChatMock/commits/main)
[![Issues](https://img.shields.io/github/issues/RayBytes/ChatMock)](https://github.com/RayBytes/ChatMock/issues)

<br>


</div>

<br>

## 安装

#### Homebrew
```bash
brew tap RayBytes/chatmock
brew install chatmock
```

#### pipx / pip
```bash
pipx install chatmock
```

#### GUI
从 [releases](https://github.com/RayBytes/ChatMock/releases) 下载 (macOS 和 Windows)

#### Docker
参见 [DOCKER.md](DOCKER.md)

<br>

## 快速开始

```bash
# 1. 使用 ChatGPT 账号登录
chatmock login

# 2. 启动服务器
chatmock serve
```

服务器默认运行在 `http://127.0.0.1:8000`。将 `http://127.0.0.1:8000/v1` 作为 OpenAI 兼容应用的基础 URL。

<br>

## 多账户池

ChatMock 支持多个 ChatGPT 账户，并在触发速率限制时自动切换。

### 添加账户

```bash
# 添加第一个账户
chatmock login

# 添加更多账户（再次运行 login）
chatmock login
```

每次登录都会提示你确认将账户添加到池中。

### 管理账户

```bash
# 列出所有账户
chatmock account list

# 显示账户详情
chatmock account show <account-id>

# 设置账户优先级 (1=最高, 10=最低)
chatmock account priority <account-id> 1

# 重命名账户
chatmock account rename <account-id> "work-account"

# 移除账户
chatmock account remove <account-id>
```

### 池状态

```bash
# 查看池状态
chatmock pool status

# 以 JSON 格式查看
chatmock pool status --json
```

### API 端点

池管理 API (默认仅限本地访问):

| 端点 | 方法 | 描述 |
|----------|--------|-------------|
| `/v1/pool/status` | GET | 获取池状态 |
| `/v1/pool/accounts` | GET | 列出所有账户 |
| `/v1/pool/accounts/<id>` | GET | 获取账户详情 |
| `/v1/pool/accounts/<id>` | DELETE | 移除账户 |
| `/v1/pool/accounts/<id>` | PATCH | 更新别名/优先级 |
| `/v1/pool/reload` | POST | 从磁盘重新加载池 |
| `/v1/pool/config` | GET/PATCH | 查看/更新配置 |

### 反向代理安全配置

如果在 nginx/traefik 后运行，请设置 API token:

```bash
export CHATMOCK_POOL_API_TOKEN="your-secret-token"
```

然后在请求中包含 token:
```bash
curl -H "Authorization: Bearer your-secret-token" http://your-server/v1/pool/status
```

### 工作原理

- **自动切换**: 当账户触发速率限制时，进入冷却期，使用下一个可用账户
- **加权选择**: 优先级更高且剩余配额更多的账户会被优先选择
- **冷却恢复**: 速率限制重置后，账户自动变为可用
- **线程安全**: 支持并发请求

<br>

## 使用示例

<details open>
<summary><b>Python</b></summary>

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="anything"  # 不检查
)

response = client.chat.completions.create(
    model="gpt-5.4",
    messages=[{"role": "user", "content": "hello"}]
)
print(response.choices[0].message.content)
```

</details>

<details>
<summary><b>cURL</b></summary>

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-5.4",
    "messages": [{"role": "user", "content": "hello"}]
  }'
```

</details>

<br>

## 支持的模型

- `gpt-5.4`
- `gpt-5.4-mini`
- `gpt-5.2`
- `gpt-5.1`
- `gpt-5`
- `gpt-5.3-codex`
- `gpt-5.3-codex-spark`
- `gpt-5.2-codex`
- `gpt-5-codex`
- `gpt-5.1-codex`
- `gpt-5.1-codex-max`
- `gpt-5.1-codex-mini`
- `codex-mini`

<br>

## 功能特性

- 工具/函数调用
- 视觉/图像输入
- 思考摘要（通过 think 标签）
- 可配置的思考强度
- 支持模型的快速模式
- 网页搜索工具
- OpenAI 兼容的 `/v1/responses` (HTTP + WebSocket)
- Ollama 兼容端点
- 推理强度作为独立模型暴露（可选）
- 可选的 API Token 认证

<br>

## API 认证

默认情况下，ChatMock 接受无认证的请求（适用于本地开发）。

要启用认证，请设置 API Token：

```bash
# 通过环境变量
export CHATMOCK_API_TOKEN="your-secret-token"
chatmock serve

# 或通过 CLI 参数
chatmock serve --api-token "your-secret-token"
```

启用后，客户端必须携带 Token：

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="your-secret-token"  # 必须与配置的 Token 匹配
)
```

```bash
curl -H "Authorization: Bearer your-secret-token" \
  http://127.0.0.1:8000/v1/chat/completions \
  -d '{"model": "gpt-5.4", "messages": [{"role": "user", "content": "hello"}]}'
```

<br>

## 配置

所有标志放在 `chatmock serve` 之后。也可以设置为环境变量。

| 标志 | 环境变量 | 选项 | 默认值 | 描述 |
|------|---------|---------|---------|-------------|
| `--reasoning-effort` | `CHATGPT_LOCAL_REASONING_EFFORT` | none, minimal, low, medium, high, xhigh | medium | 模型思考强度 |
| `--reasoning-summary` | `CHATGPT_LOCAL_REASONING_SUMMARY` | auto, concise, detailed, none | auto | 思考摘要详细程度 |
| `--reasoning-compat` | `CHATGPT_LOCAL_REASONING_COMPAT` | legacy, o3, think-tags | think-tags | 推理内容返回格式 |
| `--fast-mode` | `CHATGPT_LOCAL_FAST_MODE` | true/false | false | 支持模型的优先处理 |
| `--enable-web-search` | `CHATGPT_LOCAL_ENABLE_WEB_SEARCH` | true/false | false | 允许模型搜索网页 |
| `--expose-reasoning-models` | `CHATGPT_LOCAL_EXPOSE_REASONING_MODELS` | true/false | false | 将每个推理级别列为独立模型 |
| `--api-token` | `CHATMOCK_API_TOKEN` | 字符串 | 无 | API 认证 Token |

<details>
<summary><b>请求中的网页搜索</b></summary>

```json
{
  "model": "gpt-5.4",
  "messages": [{"role": "user", "content": "latest news on ..."}],
  "responses_tools": [{"type": "web_search"}],
  "responses_tool_choice": "auto"
}
```

</details>

<details>
<summary><b>请求中的快速模式</b></summary>

```json
{
  "model": "gpt-5.4",
  "input": "summarize this",
  "fast_mode": true
}
```

</details>

<br>

## 注意事项

请负责任地使用，风险自负。本项目与 OpenAI 无关。

<br>

## Star 历史

[![Star History Chart](https://api.star-history.com/svg?repos=RayBytes/ChatMock&type=Timeline)](https://www.star-history.com/#RayBytes/ChatMock&Timeline)