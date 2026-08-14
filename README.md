# astrbot_plugin_llm_blocker — LLM屏蔽助手

按群 / 按用户禁用 AstrBot 的 LLM 聊天响应，**其他插件功能（指令、正则响应等）照常工作**。支持**黑名单 / 白名单**两种拦截模式。

## 功能

- 在指定群聊中关闭机器人的 LLM 聊天，机器人对被禁群不再回复任何 LLM 消息；
- 在指定用户的**私聊（单独聊天）**中关闭 LLM 聊天，或全局关闭所有私聊 LLM；
- **白名单模式**：一键反转为「只允许指定群/用户使用 LLM，其余全部禁用」；
- 同群内其他插件（指令、正则、定时任务等）**完全不受影响**，照常响应；
- 支持**强力模式**：拦截范围内任何 LLM 请求（含其他插件发起的）都会被拦截；
- 支持**管理员豁免**（默认开启）：拦截范围内 AstrBot 配置的管理员（bot 主）仍可正常对话；
- 支持直接输 QQ 群号 / 用户 ID 操作（不必身处该群，私聊机器人发送最方便）。

## 安装

将本插件目录 `astrbot_plugin_llm_blocker` 放入 AstrBot 的 `data/plugins/` 目录，然后在管理面板「插件管理」中启用即可。

## 使用

管理员指令（需 @ 机器人或带唤醒前缀；直接输群号/用户ID即可生效）：

| 指令 | 说明 |
| --- | --- |
| `/blockllm` | 禁用**当前群**的 LLM 聊天 |
| `/blockllm <群号>` | 禁用指定群的 LLM 聊天 |
| `/unblockllm` | 恢复**当前群**的 LLM 聊天 |
| `/unblockllm <群号>` | 恢复指定群的 LLM 聊天 |
| `/blockllmuser` | 禁用**当前私聊用户**的 LLM（需在私聊中发送） |
| `/blockllmuser <用户ID>` | 禁用指定用户的私聊 LLM |
| `/unblockllmuser` | 恢复**当前私聊用户**的 LLM（需在私聊中发送） |
| `/unblockllmuser <用户ID>` | 恢复指定用户的私聊 LLM |
| `/llmblockmode [blacklist\|whitelist]` | 切换黑名单/白名单模式（无参数则切换；也支持中文「黑名单/白名单」） |
| `/listblockllm` | 查看模式、名单及各项开关状态 |
| `/strongllmblock [on\|off]` | 开关强力模式（无参数则切换） |
| `/exemptadmin [on\|off]` | 开关管理员豁免（无参数则切换） |

**示例（私聊机器人最方便）：**

```
/blockllm 123456789        # 禁用群 123456789 的 LLM 聊天
/blockllmuser 987654321    # 禁用用户 987654321 的私聊 LLM
/llmblockmode whitelist    # 切换为白名单模式（仅名单内可对话）
/listblockllm              # 查看当前状态
/unblockllm 123456789      # 恢复该群 LLM 聊天
```

用户 ID 获取：私聊机器人发送 `/sid` 即可看到自己的 ID。

## 模式说明

### 黑名单模式（默认）

仅拦截名单内的群/用户，其余全部正常：

- `blocked_groups` 中的群：LLM 聊天被禁用；
- `blocked_users` 中的用户：私聊 LLM 被禁用；
- `block_private_all` 开启：所有私聊 LLM 被禁用（与用户名单叠加）。

### 白名单模式

仅放行名单内的群/用户，其余全部禁用（包括所有私聊）：

- `blocked_groups` 中的群：LLM 聊天被放行；
- `blocked_users` 中的用户：私聊 LLM 被放行；
- 名单外的群 / 用户 / 全部私聊：LLM 均被禁用。

> 切换为空名单的白名单模式会禁用所有 LLM 聊天，切换时会有提示。管理员豁免开启时 bot 主不受影响。

### 其他开关

- **强力模式**：额外拦截「经 AstrBot 管线发起」的插件 LLM 请求（即插件 handler `yield ProviderRequest` 的场景，通过 `on_llm_request` 钩子 `stop_event()` 实现）。
- **管理员豁免**（默认开启）：拦截范围内 AstrBot 配置的管理员（bot 主）发消息仍可正常与 LLM 对话，两个拦截钩子都会放行；关闭后管理员与普通成员一致被拦截。

**两种模式都拦不住的请求**：插件在自身代码中直接调用 provider API（如 `provider.text_chat()`）发起的 LLM 请求不经过 AstrBot 管线，任何事件钩子都无法拦截。例如某些插件的"轻量分析模型"调用。此类请求需要在该插件自身的配置中按群禁用，或通过 AstrBot「会话管理」在该群禁用对应插件。

## 配置

所有配置都可以在管理面板「插件管理 → LLM屏蔽助手 → 配置」中直接修改（配置文件为 `data/config/astrbot_plugin_llm_blocker_config.json`），**保存后插件自动热重载生效**：

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `mode` | string | `blacklist` | 拦截模式：`blacklist` 黑名单 / `whitelist` 白名单（面板中为下拉选择）；群内 `/llmblockmode` 切换后会同步到这里 |
| `blocked_groups` | list | `[]` | 黑名单模式：被禁用 LLM 的群列表；白名单模式：被放行 LLM 的群列表 |
| `blocked_users` | list | `[]` | 黑名单模式：被禁用私聊 LLM 的用户列表；白名单模式：被放行私聊 LLM 的用户列表 |
| `block_private_all` | bool | `false` | 全局禁用所有私聊 LLM（黑名单模式有效） |
| `strong_mode` | bool | `false` | 强力模式开关；群内 `/strongllmblock` 切换后会同步到这里 |
| `exempt_admin` | bool | `true` | 管理员豁免开关；群内 `/exemptadmin` 切换后会同步到这里 |

面板配置是唯一数据源。聊天指令与面板双向同步：指令改动立即写入面板配置，面板改动保存后热重载生效。

**旧版升级**：如果之前用过独立数据文件（`data/plugin_data/llm_blocker/blocked_groups.json`），首次启动会自动把其中的屏蔽群和强力模式合并迁移到面板配置，原文件备份为 `.bak`。旧配置没有的新字段（`mode`、`blocked_users`、`block_private_all`）自动取默认值，行为与旧版完全一致。

## 实现原理

- 默认拦截：`@filter.event_message_type(GROUP_MESSAGE | PRIVATE_MESSAGE)` 处理器在命中拦截范围时调用 `event.should_call_llm(True)`，只阻止 AstrBot 默认 LLM 请求链路，不 `stop_event()`、不产生结果，因此不影响同消息内的其他插件 handler。
- 唤醒副作用防护：处理器额外挂 `AtOrWakeCommandFilter` 自定义过滤器，仅当消息已 @ 机器人 / 命中唤醒前缀时才触发，避免机器人在每个群消息都被误唤醒。
- 强力模式：`@filter.on_llm_request()` 钩子（普通协程）在拦截范围内 `event.stop_event()`，拦截所有**经管线发起**的 LLM 请求。
- 管理员豁免：两个钩子在放行前都会判断 `event.is_admin()`（AstrBot 配置的管理员），开启豁免时直接放行，不调用任何阻止接口。
- 私聊判定：`event.is_private_chat()` 区分群聊/私聊；私聊按 `event.get_sender_id()` 匹配用户名单。

## 依赖

无第三方依赖（仅使用 Python 标准库 `json`、`os`）。`requirements.txt` 中已注明。
