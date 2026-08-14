import json
import os

from astrbot import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

MODE_BLACKLIST = "blacklist"
MODE_WHITELIST = "whitelist"


class AtOrWakeCommandFilter(filter.CustomFilter):
    """仅当消息已经 @ 机器人 / 命中唤醒前缀时通过。

    避免用一个对所有群消息生效的 handler 导致机器人在每个群消息都「醒来」
    （waking_check 阶段 is_wake 被置 True），只拦截真正会触发默认 LLM 的消息。
    """

    def filter(self, event: AstrMessageEvent, cfg) -> bool:
        return bool(event.is_at_or_wake_command)


@register(
    "astrbot_plugin_llm_blocker",
    "xiaoxi2760",
    "按群/按用户禁用LLM聊天（支持黑白名单模式），其他插件不受影响",
    "v1.2.1",
)
class LLMBlocker(Star):
    def __init__(
        self,
        context: Context,
        config: dict | None = None,
        config_path: str | None = None,
    ):
        super().__init__(context)
        # AstrBot 插件配置（data/config/astrbot_plugin_llm_blocker_config.json）。
        # 面板保存配置后 AstrBot 会热重载本插件，__init__ 重新读取即为最新值。
        self.config = config
        # 旧版独立数据文件：仅在面板配置不可用时兜底，也是旧数据的一次性迁移来源。
        self.config_path = config_path or os.path.join(
            "data", "plugin_data", "llm_blocker", "blocked_groups.json"
        )
        # 拦截模式：blacklist=黑名单（仅拦截名单内）；whitelist=白名单（仅放行名单内）
        self.mode: str = MODE_BLACKLIST
        # 被禁用 LLM 的群列表（白名单模式下为「放行」列表）
        self.blocked_groups: set[str] = set()
        # 私聊（单独聊天）中被禁用 LLM 的用户列表（白名单模式下为「放行」列表）
        self.blocked_users: set[str] = set()
        # 全局禁用所有私聊 LLM（仅黑名单模式有效）
        self.block_private_all: bool = False
        self.strong_mode: bool = False
        # 管理员豁免：开启后 AstrBot 配置的管理员（bot 主）在拦截范围内仍可正常与 LLM 对话
        self.exempt_admin: bool = True
        if self.config is not None:
            # 面板配置是唯一数据源
            self._load_from_config()
            self._migrate_legacy_file()
        else:
            self._load_legacy_file()

    # ------------------------------------------------------------------
    # 配置读取与持久化：面板配置优先；无面板配置时退回独立数据文件（兼容旧格式）
    # ------------------------------------------------------------------
    @staticmethod
    def _to_str_set(items) -> set[str]:
        return {str(i).strip() for i in (items or []) if str(i).strip()}

    @staticmethod
    def _normalize_mode(mode) -> str:
        return MODE_WHITELIST if str(mode or "").strip() == MODE_WHITELIST else MODE_BLACKLIST

    def _load_from_config(self) -> None:
        self.mode = self._normalize_mode(self.config.get("mode"))
        self.blocked_groups = self._to_str_set(self.config.get("blocked_groups"))
        self.blocked_users = self._to_str_set(self.config.get("blocked_users"))
        self.block_private_all = bool(self.config.get("block_private_all", False))
        self.strong_mode = bool(self.config.get("strong_mode", False))
        self.exempt_admin = bool(self.config.get("exempt_admin", True))

    def _load_legacy_file(self) -> None:
        data = {}
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
        except Exception as e:
            logger.error(f"[llm_blocker] 加载配置失败: {e}")
            return

        if isinstance(data, list):
            # 旧格式：纯列表 -> 视为屏蔽群列表
            self.blocked_groups = self._to_str_set(data)
        elif isinstance(data, dict):
            self.mode = self._normalize_mode(data.get("mode"))
            self.blocked_groups = self._to_str_set(data.get("blocked_groups"))
            self.blocked_users = self._to_str_set(data.get("blocked_users"))
            self.block_private_all = bool(data.get("block_private_all", False))
            self.strong_mode = bool(data.get("strong_mode", False))
            self.exempt_admin = bool(data.get("exempt_admin", True))

    def _migrate_legacy_file(self) -> None:
        """旧版独立数据文件 -> 面板配置，一次性合并（群取并集、强力模式取或），
        迁移后把旧文件改名为 .bak，避免每次启动重复合并。"""
        if not os.path.exists(self.config_path):
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"[llm_blocker] 迁移旧配置失败: {e}")
            return

        if isinstance(data, list):
            legacy_groups = self._to_str_set(data)
            legacy_strong = False
        elif isinstance(data, dict):
            legacy_groups = self._to_str_set(data.get("blocked_groups"))
            legacy_strong = bool(data.get("strong_mode", False))
        else:
            legacy_groups, legacy_strong = set(), False

        if legacy_groups or legacy_strong:
            self.blocked_groups |= legacy_groups
            self.strong_mode = self.strong_mode or legacy_strong
            self._persist()
            logger.info(
                f"[llm_blocker] 已把旧数据文件中的 {len(legacy_groups)} 个屏蔽群"
                f"迁移到面板配置（原文件备份为 .bak）"
            )
        try:
            os.replace(self.config_path, self.config_path + ".bak")
        except Exception as e:
            logger.error(f"[llm_blocker] 备份旧配置文件失败: {e}")

    def _persist(self) -> None:
        """保存当前状态：有面板配置就回写面板配置（WebUI 可见），否则写独立数据文件。"""
        if self.config is not None:
            try:
                self.config["mode"] = self.mode
                self.config["blocked_groups"] = sorted(self.blocked_groups)
                self.config["blocked_users"] = sorted(self.blocked_users)
                self.config["block_private_all"] = self.block_private_all
                self.config["strong_mode"] = self.strong_mode
                self.config["exempt_admin"] = self.exempt_admin
                save = getattr(self.config, "save_config", None)
                if callable(save):
                    save()
            except Exception as e:
                logger.error(f"[llm_blocker] 保存面板配置失败: {e}")
            return
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            data = {
                "mode": self.mode,
                "blocked_groups": sorted(self.blocked_groups),
                "blocked_users": sorted(self.blocked_users),
                "block_private_all": self.block_private_all,
                "strong_mode": self.strong_mode,
                "exempt_admin": self.exempt_admin,
            }
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[llm_blocker] 保存配置失败: {e}")

    # ------------------------------------------------------------------
    # 拦截判定
    # ------------------------------------------------------------------
    def _is_whitelist(self) -> bool:
        return self.mode == MODE_WHITELIST

    def _list_label(self) -> str:
        return "白名单" if self._is_whitelist() else "禁用列表"

    def _is_llm_blocked(self, event: AstrMessageEvent) -> bool:
        """判断该消息上下文是否应拦截 LLM（与当前模式相关）。

        Args:
            event: 消息事件。

        Returns:
            是否应拦截 LLM。
        """
        if event.is_private_chat():
            uid = str(event.get_sender_id() or "").strip()
            in_list = bool(uid) and uid in self.blocked_users
            # 白名单：私聊默认全部禁用，仅名单内用户放行；
            # 黑名单：仅名单内用户被禁用，或全局私聊开关开启时全部禁用。
            return (not in_list) if self._is_whitelist() else (
                self.block_private_all or in_list
            )
        gid = str(event.get_group_id() or "").strip()
        in_list = bool(gid) and gid in self.blocked_groups
        # 白名单：群默认全部禁用，仅名单内群放行；黑名单：仅名单内群被禁用。
        return (not in_list) if self._is_whitelist() else in_list

    # ------------------------------------------------------------------
    # 管理指令（仅管理员；指令需 @ 机器人或唤醒前缀）
    # 直接输群号/用户ID即可生效：私聊机器人发送 /blockllm 123456 最方便。
    # 群号与用户 ID 均可通过 /sid 等途径获取。
    # ------------------------------------------------------------------
    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("blockllm")
    async def block_llm(self, event: AstrMessageEvent, group_id: str = ""):
        """禁用指定群的 LLM 聊天（黑名单模式）/ 将群加入白名单（白名单模式）。"""
        gid = group_id.strip() or str(event.get_group_id() or "").strip()
        if not gid:
            yield event.plain_result(
                "请指定群号：/blockllm <群号>（私聊机器人直接输最方便），或在群内直接 /blockllm"
            )
            return
        if gid in self.blocked_groups:
            yield event.plain_result(f"群 {gid} 已在{self._list_label()}中")
            return
        self.blocked_groups.add(gid)
        self._persist()
        if self._is_whitelist():
            yield event.plain_result(
                f"已将群 {gid} 加入白名单（白名单模式下仅白名单内的群可正常使用 LLM）"
            )
        else:
            yield event.plain_result(
                f"已禁用群 {gid} 的 LLM 聊天（其他插件不受影响）"
            )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("unblockllm")
    async def unblock_llm(self, event: AstrMessageEvent, group_id: str = ""):
        """恢复指定群的 LLM 聊天（黑名单模式）/ 将群移出白名单（白名单模式）。"""
        gid = group_id.strip() or str(event.get_group_id() or "").strip()
        if not gid:
            yield event.plain_result(
                "请指定群号：/unblockllm <群号>，或在群内直接 /unblockllm"
            )
            return
        if gid not in self.blocked_groups:
            yield event.plain_result(f"群 {gid} 不在{self._list_label()}中")
            return
        self.blocked_groups.discard(gid)
        self._persist()
        if self._is_whitelist():
            yield event.plain_result(f"已将群 {gid} 移出白名单（该群 LLM 将被禁用）")
        else:
            yield event.plain_result(f"已恢复群 {gid} 的 LLM 聊天")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("blockllmuser")
    async def block_llm_user(self, event: AstrMessageEvent, user_id: str = ""):
        """禁用指定用户的私聊 LLM（黑名单模式）/ 将用户加入白名单（白名单模式）。"""
        uid = user_id.strip()
        if not uid and event.is_private_chat():
            # 私聊中无参数 = 禁用当前用户
            uid = str(event.get_sender_id() or "").strip()
        if not uid:
            yield event.plain_result(
                "请指定用户 ID：/blockllmuser <用户ID>（私聊机器人发送 /sid 可查看自己的 ID），"
                "或在私聊中直接 /blockllmuser 禁用当前用户"
            )
            return
        if uid in self.blocked_users:
            yield event.plain_result(f"用户 {uid} 已在{self._list_label()}中")
            return
        self.blocked_users.add(uid)
        self._persist()
        if self._is_whitelist():
            yield event.plain_result(f"已将用户 {uid} 加入白名单（其私聊 LLM 放行）")
        else:
            yield event.plain_result(f"已禁用用户 {uid} 的私聊 LLM")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("unblockllmuser")
    async def unblock_llm_user(self, event: AstrMessageEvent, user_id: str = ""):
        """恢复指定用户的私聊 LLM（黑名单模式）/ 将用户移出白名单（白名单模式）。"""
        uid = user_id.strip()
        if not uid and event.is_private_chat():
            uid = str(event.get_sender_id() or "").strip()
        if not uid:
            yield event.plain_result(
                "请指定用户 ID：/unblockllmuser <用户ID>，或在私聊中直接 /unblockllmuser"
            )
            return
        if uid not in self.blocked_users:
            yield event.plain_result(f"用户 {uid} 不在{self._list_label()}中")
            return
        self.blocked_users.discard(uid)
        self._persist()
        if self._is_whitelist():
            yield event.plain_result(f"已将用户 {uid} 移出白名单（其私聊 LLM 将被禁用）")
        else:
            yield event.plain_result(f"已恢复用户 {uid} 的私聊 LLM")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("listblockllm")
    async def list_blocked(self, event: AstrMessageEvent):
        """查看当前拦截模式、名单与各项开关状态。"""
        mode = "白名单（仅放行名单内）" if self._is_whitelist() else "黑名单（仅禁用名单内）"
        strong = "开" if self.strong_mode else "关"
        exempt = "开" if self.exempt_admin else "关"
        private_all = "开" if self.block_private_all else "关"
        lines = [
            f"拦截模式：{mode}",
            f"强力模式：{strong}",
            f"管理员豁免：{exempt}",
            f"全局禁用私聊：{private_all}",
        ]
        label = self._list_label()
        if self.blocked_groups:
            lines.append(f"{label}（群）：" + "、".join(sorted(self.blocked_groups)))
        else:
            lines.append(f"{label}（群）：（空）")
        if self.blocked_users:
            lines.append(f"{label}（用户）：" + "、".join(sorted(self.blocked_users)))
        else:
            lines.append(f"{label}（用户）：（空）")
        yield event.plain_result("\n".join(lines))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("llmblockmode")
    async def toggle_mode(self, event: AstrMessageEvent, arg: str = ""):
        """切换黑名单/白名单拦截模式（无参数则切换）。"""
        arg = arg.strip().lower()
        if arg in ("blacklist", "黑名单"):
            self.mode = MODE_BLACKLIST
        elif arg in ("whitelist", "白名单"):
            self.mode = MODE_WHITELIST
        else:
            self.mode = MODE_BLACKLIST if self._is_whitelist() else MODE_WHITELIST
        self._persist()
        if self._is_whitelist():
            warn = ""
            if not self.blocked_groups and not self.blocked_users:
                warn = "（注意：当前白名单为空，所有 LLM 聊天将被禁用）"
            yield event.plain_result(
                f"已切换为白名单模式：仅名单内的群/用户可正常使用 LLM，其余全部禁用{warn}"
            )
        else:
            yield event.plain_result(
                "已切换为黑名单模式：仅名单内的群/用户被禁用 LLM，其余正常"
            )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("strongllmblock")
    async def toggle_strong(self, event: AstrMessageEvent, arg: str = ""):
        """开关强力模式（无参数则切换）：开启后拦截范围内经管线的插件 LLM 请求也会被拦截。"""
        arg = arg.strip().lower()
        if arg in ("on", "1", "true", "开", "启用"):
            self.strong_mode = True
        elif arg in ("off", "0", "false", "关", "关闭"):
            self.strong_mode = False
        else:
            self.strong_mode = not self.strong_mode  # 无参数则切换
        self._persist()
        state = "已开启" if self.strong_mode else "已关闭"
        extra = (
            "：拦截范围内经管线的插件 LLM 请求也会被拦截"
            "（插件私下直接调 provider 的除外）"
            if self.strong_mode
            else "：仅拦截默认 LLM 聊天，插件发起的 LLM 请求不受影响"
        )
        yield event.plain_result(f"强力模式{state}{extra}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("exemptadmin")
    async def toggle_exempt_admin(self, event: AstrMessageEvent, arg: str = ""):
        """开关管理员豁免（无参数则切换）：开启后拦截范围内 bot 主仍可正常对话。"""
        arg = arg.strip().lower()
        if arg in ("on", "1", "true", "开", "启用"):
            self.exempt_admin = True
        elif arg in ("off", "0", "false", "关", "关闭"):
            self.exempt_admin = False
        else:
            self.exempt_admin = not self.exempt_admin  # 无参数则切换
        self._persist()
        state = "已开启" if self.exempt_admin else "已关闭"
        extra = (
            "：拦截范围内 AstrBot 配置的管理员（bot 主）发消息仍可正常与 LLM 对话"
            if self.exempt_admin
            else "：拦截范围内管理员也会被拦截，与普通成员一致"
        )
        yield event.plain_result(f"管理员豁免{state}{extra}")

    # ------------------------------------------------------------------
    # 核心1：只拦默认 LLM，不终止事件、不影响其他插件
    # ------------------------------------------------------------------
    @filter.event_message_type(
        filter.EventMessageType.GROUP_MESSAGE
        | filter.EventMessageType.PRIVATE_MESSAGE
    )
    @filter.custom_filter(AtOrWakeCommandFilter)
    async def suppress_default_llm(self, event: AstrMessageEvent):
        """消息事件监听（群聊+私聊）：拦截范围内阻止默认 LLM 请求链路，不终止事件、不影响其他插件。"""
        if self._is_llm_blocked(event):
            # 管理员豁免：bot 主在拦截范围内仍可正常对话
            if self.exempt_admin and event.is_admin():
                return
            # 只会阻止 AstrBot 默认的 LLM 请求链路，不会阻止插件中的 LLM 请求。
            event.should_call_llm(True)
        yield

    # ------------------------------------------------------------------
    # 核心2：强力模式，拦该上下文所有 LLM 请求（含插件发起）
    # ------------------------------------------------------------------
    @filter.on_llm_request()
    async def strong_block_llm(self, event: AstrMessageEvent, req):
        """on_llm_request 钩子：强力模式下拦截范围内所有经管线的 LLM 请求（含插件发起）。"""
        if not self.strong_mode:
            return
        if self._is_llm_blocked(event):
            # 管理员豁免：bot 主在拦截范围内仍可正常对话
            if self.exempt_admin and event.is_admin():
                return
            event.stop_event()
