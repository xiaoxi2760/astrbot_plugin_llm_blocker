# astrbot_plugin_llm_blocker — LLM屏蔽助手

按群禁用 AstrBot 的 LLM 聊天响应，**其他插件功能（指令、正则响应等）照常工作**。

## 功能

- 在指定群聊中关闭机器人的 LLM 聊天，机器人对被禁群不再回复任何 LLM 消息；
- 同群内其他插件（指令、正则、定时任务等）**完全不受影响**，照常响应；
- 支持**强力模式**：被禁群内任何 LLM 请求（含其他插件发起的）都会被拦截；
- 支持直接输 QQ 群号操作（不必身处该群，私聊机器人发送最方便）。

## 安装

将本插件目录 `astrbot_plugin_llm_blocker` 放入 AstrBot 的 `data/plugins/` 目录，然后在管理面板「插件管理」中启用即可。

## 使用

管理员指令（需 @ 机器人或带唤醒前缀；直接输群号即可生效）：

| 指令 | 说明 |
| --- | --- |
| `/blockllm` | 禁用**当前群**的 LLM 聊天 |
| `/blockllm <群号>` | 禁用指定群的 LLM 聊天 |
| `/unblockllm` | 恢复**当前群**的 LLM 聊天 |
| `/unblockllm <群号>` | 恢复指定群的 LLM 聊天 |
| `/listblockllm` | 查看已禁用 LLM 的群列表及强力模式状态 |
| `/strongllmblock [on\|off]` | 开关强力模式（无参数则切换） |

**示例（私聊机器人最方便）：**

```
/blockllm 123456789        # 禁用群 123456789 的 LLM 聊天
/strongllmblock on         # 开启强力模式
/listblockllm              # 查看当前状态
/unblockllm 123456789      # 恢复该群 LLM 聊天
```

## 模式说明

- **默认模式**：只拦截 AstrBot 的默认 LLM 聊天链路。插件发起的 LLM 请求不受影响，其他插件照常工作。
- **强力模式**：额外拦截「经 AstrBot 管线发起」的插件 LLM 请求（即插件 handler `yield ProviderRequest` 的场景，通过 `on_llm_request` 钩子 `stop_event()` 实现）。

**两种模式都拦不住的请求**：插件在自身代码中直接调用 provider API（如 `provider.text_chat()`）发起的 LLM 请求不经过 AstrBot 管线，任何事件钩子都无法拦截。例如某些插件的"轻量分析模型"调用。此类请求需要在该插件自身的配置中按群禁用，或通过 AstrBot「会话管理」在该群禁用对应插件。

## 配置

所有配置都可以在管理面板「插件管理 → LLM屏蔽助手 → 配置」中直接修改（配置文件为 `data/config/astrbot_plugin_llm_blocker_config.json`），**保存后插件自动热重载生效**：

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `strong_mode` | bool | `false` | 强力模式开关；群内 `/strongllmblock` 切换后会同步到这里 |
| `blocked_groups` | list | `[]` | 已禁用 LLM 的群号列表；群内 `/blockllm`、`/unblockllm` 管理后会同步到这里 |

面板配置是唯一数据源。聊天指令与面板双向同步：指令改动立即写入面板配置，面板改动保存后热重载生效。

**旧版升级**：如果之前用过独立数据文件（`data/plugin_data/llm_blocker/blocked_groups.json`），首次启动会自动把其中的屏蔽群和强力模式合并迁移到面板配置，原文件备份为 `.bak`。

## 实现原理

- 默认模式：`@filter.event_message_type(GROUP_MESSAGE)` 处理器在命中被禁群时调用 `event.should_call_llm(True)`，只阻止 AstrBot 默认 LLM 请求链路，不 `stop_event()`、不产生结果，因此不影响同消息内的其他插件 handler。
- 唤醒副作用防护：处理器额外挂 `AtOrWakeCommandFilter` 自定义过滤器，仅当消息已 @ 机器人 / 命中唤醒前缀时才触发，避免机器人在每个群消息都被误唤醒。
- 强力模式：`@filter.on_llm_request()` 钩子（普通协程）在被禁群内 `event.stop_event()`，拦截该群所有**经管线发起**的 LLM 请求。

## 依赖

无第三方依赖（仅使用 Python 标准库 `json`、`os`）。`requirements.txt` 中已注明。
