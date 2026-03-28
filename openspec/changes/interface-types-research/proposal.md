# ChatMock 接口类型研究报告

## 研究概述

**研究目标**: 分析 ChatMock 项目支持的所有 API 接口类型及其特征
**研究范围**: routes_openai.py, routes_ollama.py
**约束类型**: 技术约束 + 接口规范

---

## 接口类型总览

ChatMock 实现了两套 API 接口规范，通过 Flask Blueprint 架构实现：

| 接口规范 | Blueprint | 基础路径 | 文件位置 |
|---------|-----------|---------|---------|
| OpenAI API | `openai_bp` | `/v1/*` | routes_openai.py |
| Ollama API | `ollama_bp` | `/api/*` | routes_ollama.py |

---

## 一、OpenAI 兼容接口 (`/v1/*`)

### 1.1 POST `/v1/chat/completions`

**功能**: 对话补全接口（核心接口）

**请求格式**:
```json
{
  "model": "gpt-5",
  "messages": [{"role": "user", "content": "..."}],
  "stream": true,
  "tools": [...],
  "tool_choice": "auto",
  "reasoning": {"effort": "high"},
  "responses_tools": [{"type": "web_search"}],
  "stream_options": {"include_usage": true}
}
```

**支持特性**:
- 流式响应 (SSE)
- 工具调用 (function calling)
- 推理努力级别 (reasoning effort)
- Web Search 工具透传
- 提示缓存 (session-based)
- 用量统计 (usage)

**约束**:
- `responses_tools` 仅支持 `web_search` / `web_search_preview`
- `responses_tools` 最大 32768 字节
- 系统消息会被转换为用户消息

### 1.2 POST `/v1/completions`

**功能**: 文本补全接口

**请求格式**:
```json
{
  "model": "gpt-5",
  "prompt": "Once upon a time",
  "stream": false
}
```

**支持特性**:
- 流式响应
- 推理努力级别
- 支持多 prompt 格式（字符串或数组）

### 1.3 GET `/v1/models`

**功能**: 列出可用模型

**响应格式**:
```json
{
  "object": "list",
  "data": [
    {"id": "gpt-5", "object": "model", "owned_by": "owner"},
    {"id": "gpt-5.1", "object": "model", "owned_by": "owner"}
  ]
}
```

**配置**: `EXPOSE_REASONING_MODELS` 控制是否暴露推理变体

---

## 二、Ollama 兼容接口 (`/api/*`)

### 2.1 GET `/api/version`

**功能**: 返回 Ollama 版本信息

**响应格式**:
```json
{"version": "0.12.10"}
```

**配置**: `OLLAMA_VERSION` 可自定义版本号

### 2.2 GET `/api/tags`

**功能**: 列出可用模型（Ollama 格式）

**响应格式**:
```json
{
  "models": [
    {
      "name": "gpt-5",
      "model": "gpt-5",
      "modified_at": "2023-10-01T00:00:00Z",
      "size": 815319791,
      "digest": "...",
      "details": {
        "family": "llama",
        "parameter_size": "8.0B",
        "quantization_level": "Q4_0"
      }
    }
  ]
}
```

### 2.3 POST `/api/show`

**功能**: 显示模型详情

**请求格式**:
```json
{"model": "gpt-5"}
```

**响应格式**: 返回模拟的 Modelfile、参数、模板等信息

**能力声明**: `["completion", "vision", "tools", "thinking"]`

### 2.4 POST `/api/chat`

**功能**: 对话补全接口（Ollama 格式）

**请求格式**:
```json
{
  "model": "gpt-5",
  "messages": [{"role": "user", "content": "..."}],
  "stream": true,
  "tools": [...],
  "images": ["base64..."]
}
```

**支持特性**:
- 流式响应（默认开启）
- 工具调用
- 图像输入（base64）
- Web Search 透传
- 推理标签兼容 (`REASONING_COMPAT`)

---

## 三、上游 API 映射

所有接口最终转换为 ChatGPT Responses API 格式：

```
ChatGPT Responses API: https://chatgpt.com/backend-api/codex/responses
```

**请求转换流程**:
1. 解析 OpenAI/Ollama 请求格式
2. 提取模型名和推理参数
3. 转换消息格式为 Responses API 输入
4. 添加指令文件 (prompt.md / prompt_gpt5_codex.md)
5. 发送上游请求并处理 SSE 响应

---

## 四、约束集合

### 4.1 硬约束（不可违反）

| 约束 ID | 描述 | 来源 |
|--------|------|-----|
| HC-001 | 上游 API 仅支持 Responses API 格式 | upstream.py |
| HC-002 | 认证依赖 ChatGPT Plus/Pro 账户 | oauth.py |
| HC-003 | 流式响应使用 SSE 格式 | transform.py |
| HC-004 | `responses_tools` 仅支持 web_search 类型 | routes_*.py |
| HC-005 | 系统消息会被转为用户消息（上游限制） | routes_*.py |

### 4.2 软约束（可配置）

| 约束 ID | 描述 | 配置项 |
|--------|------|-------|
| SC-001 | 默认推理努力级别 | REASONING_EFFORT |
| SC-002 | 推理标签格式 | REASONING_COMPAT |
| SC-003 | 是否暴露推理变体模型 | EXPOSE_REASONING_MODELS |
| SC-004 | 默认启用 Web Search | DEFAULT_WEB_SEARCH |
| SC-005 | Ollama 版本号 | OLLAMA_VERSION |

### 4.3 依赖关系

```
routes_openai.py → upstream.py → ChatGPT Responses API
routes_ollama.py → upstream.py → ChatGPT Responses API
              ↓
         transform.py (SSE 转换)
              ↓
         reasoning.py (推理参数处理)
              ↓
         session.py (提示缓存)
```

---

## 五、成功判据

### 验证接口正确性

1. **OpenAI 接口验证**:
   - `POST /v1/chat/completions` 返回有效响应
   - `POST /v1/completions` 返回有效响应
   - `GET /v1/models` 返回模型列表

2. **Ollama 接口验证**:
   - `GET /api/version` 返回版本信息
   - `GET /api/tags` 返回模型列表
   - `POST /api/show` 返回模型详情
   - `POST /api/chat` 返回有效响应

3. **流式响应验证**:
   - SSE 事件格式正确
   - `[DONE]` 事件正确终止

4. **工具调用验证**:
   - function calling 正确映射
   - tool_calls 正确返回

---

## 六、风险识别

| 风险 ID | 描述 | 影响 | 缓解措施 |
|--------|------|-----|---------|
| R-001 | 上游 API 变更可能导致接口失效 | 高 | 版本锁定 + 错误监控 |
| R-002 | ChatGPT 账户被封禁 | 高 | 多账户支持 |
| R-003 | 速率限制 (x-codex-* headers) | 中 | limits.py 追踪 |
| R-004 | `responses_tools` 被上游拒绝 | 中 | 自动重试机制已实现 |

---

## 七、待确认问题

无模糊性问题需要用户澄清。接口类型已明确定义。