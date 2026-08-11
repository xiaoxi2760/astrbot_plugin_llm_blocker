import json
import os

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register


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
    "按群禁用默认LLM聊天，其他插件不受影响",
    "v1.1.0",
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
        self.blocked_groups: set[str] = set()
        self.strong_mode: bool = False
        # 管理员豁免：开启后 AstrBot 配置的管理员（bot 主）在被禁群内仍可正常与 LLM 对话
        self.exempt_admin: bool = True
        if self.config is not None:
            # 面板配置是唯一数据源
            self.blocked_groups = {
                str(i).strip()
                for i in (self.config.get("blocked_groups") or [])
                if str(i).strip()
            }
            self.strong_mode = bool(self.config.get("strong_mode", False))
            self.exempt_admin = bool(self.config.get("exempt_admin", True))
            self._migrate_legacy_file()
        else:
            self._load_legacy_file()

    # ------------------------------------------------------------------
    # 持久化：面板配置优先；无面板配置时退回独立数据文件（兼容旧格式：纯列表）
    # ------------------------------------------------------------------
    def _load_legacy_file(self) -> None:
        data = {}
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
        except Exception as e:
            print(f"[llm_blocker] 加载配置失败: {e}")
            return

        if isinstance(data, list):
            # 旧格式：纯列表 -> 视为屏蔽群列表，强力模式关闭
            self.blocked_groups = {
                str(i).strip() for i in data if str(i).strip()
            }
            self.strong_mode = False
        elif isinstance(data, dict):
            groups = data.get("blocked_groups", [])
            self.blocked_groups = {
                str(i).strip() for i in groups if str(i).strip()
            }
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
            print(f"[llm_blocker] 迁移旧配置失败: {e}")
            return

        if isinstance(data, list):
            legacy_groups = {str(i).strip() for i in data if str(i).strip()}
            legacy_strong = False
        elif isinstance(data, dict):
            legacy_groups = {
                str(i).strip()
                for i in data.get("blocked_groups", [])
                if str(i).strip()
            }
            legacy_strong = bool(data.get("strong_mode", False))
        else:
            legacy_groups, legacy_strong = set(), False

        if legacy_groups or legacy_strong:
            self.blocked_groups |= legacy_groups
            self.strong_mode = self.strong_mode or legacy_strong
            self._persist()
            print(
                f"[llm_blocker] 已把旧数据文件中的 {len(legacy_groups)} 个屏蔽群"
                f"迁移到面板配置（原文件备份为 .bak）"
            )
        try:
            os.replace(self.config_path, self.config_path + ".bak")
        except Exception as e:
            print(f"[llm_blocker] 备份旧配置文件失败: {e}")

    def _persist(self) -> None:
        """保存当前状态：有面板配置就回写面板配置（WebUI 可见），否则写独立数据文件。"""
        if self.config is not None:
            try:
                self.config["blocked_groups"] = sorted(self.blocked_groups)
                self.config["strong_mode"] = self.strong_mode
                self.config["exempt_admin"] = self.exempt_admin
                save = getattr(self.config, "save_config", None)
                if callable(save):
                    save()
            except Exception as e:
                print(f"[llm_blocker] 保存面板配置失败: {e}")
            return
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            data = {
                "blocked_groups": sorted(self.blocked_groups),
                "strong_mode": self.strong_mode,
                "exempt_admin": self.exempt_admin,
            }
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[llm_blocker] 保存配置失败: {e}")

    # ------------------------------------------------------------------
    # 管理指令（仅管理员；指令需 @ 机器人或唤醒前缀）
    # 直接输群号即可生效：私聊机器人发送 /blockllm 123456 最方便。
    # ------------------------------------------------------------------
    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("blockllm")
    async def block_llm(self, event: AstrMessageEvent, group_id: str = ""):
        gid = group_id.strip() or str(event.get_group_id() or "").strip()
        if not gid:
            yield event.plain_result(
                "请指定群号：/blockllm <群号>（私聊机器人直接输最方便），或在群内直接 /blockllm"
            )
            return
        if gid in self.blocked_groups:
            yield event.plain_result(f"群 {gid} 已在禁用列表中")
            return
        self.blocked_groups.add(gid)
        self._persist()
        yield event.plain_result(
            f"已禁用群 {gid} 的 LLM 聊天（其他插件不受影响）"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("unblockllm")
    async def unblock_llm(self, event: AstrMessageEvent, group_id: str = ""):
        gid = group_id.strip() or str(event.get_group_id() or "").strip()
        if not gid:
            yield event.plain_result(
                "请指定群号：/unblockllm <群号>，或在群内直接 /unblockllm"
            )
            return
        if gid not in self.blocked_groups:
            yield event.plain_result(f"群 {gid} 不在禁用列表中")
            return
        self.blocked_groups.discard(gid)
        self._persist()
        yield event.plain_result(f"已恢复群 {gid} 的 LLM 聊天")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("listblockllm")
    async def list_blocked(self, event: AstrMessageEvent):
        strong = "开" if self.strong_mode else "关"
        if not self.blocked_groups:
            yield event.plain_result(f"当前没有禁用 LLM 的群（强力模式：{strong}）")
            return
        lines = [f"已禁用 LLM 的群（强力模式：{strong}）："]
        lines.extend(sorted(self.blocked_groups))
        yield event.plain_result("\n".join(lines))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("strongllmblock")
    async def toggle_strong(self, event: AstrMessageEvent, arg: str = ""):
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
            "：被禁群内经管线的插件 LLM 请求也会被拦截"
            "（插件私下直接调 provider 的除外）"
            if self.strong_mode
            else "：仅拦截默认 LLM 聊天，插件发起的 LLM 请求不受影响"
        )
        yield event.plain_result(f"强力模式{state}{extra}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("exemptadmin")
    async def toggle_exempt_admin(self, event: AstrMessageEvent, arg: str = ""):
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
            "：被禁群内 AstrBot 配置的管理员（bot 主）发消息仍可正常与 LLM 对话"
            if self.exempt_admin
            else "：被禁群内管理员也会被拦截，与普通成员一致"
        )
        yield event.plain_result(f"管理员豁免{state}{extra}")

    # ------------------------------------------------------------------
    # 核心1：只拦默认 LLM，不终止事件、不影响其他插件
    # ------------------------------------------------------------------
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.custom_filter(AtOrWakeCommandFilter)
    async def suppress_default_llm(self, event: AstrMessageEvent):
        gid = str(event.get_group_id() or "").strip()
        if gid and gid in self.blocked_groups:
            # 管理员豁免：bot 主在被禁群内仍可正常对话
            if self.exempt_admin and event.is_admin():
                return
            # 只会阻止 AstrBot 默认的 LLM 请求链路，不会阻止插件中的 LLM 请求。
            event.should_call_llm(True)
        yield

    # ------------------------------------------------------------------
    # 核心2：强力模式，拦该群所有 LLM 请求（含插件发起）
    # ------------------------------------------------------------------
    @filter.on_llm_request()
    async def strong_block_llm(self, event: AstrMessageEvent, req):
        if not self.strong_mode:
            return
        gid = str(event.get_group_id() or "").strip()
        if gid and gid in self.blocked_groups:
            # 管理员豁免：bot 主在被禁群内仍可正常对话
            if self.exempt_admin and event.is_admin():
                return
            event.stop_event()
