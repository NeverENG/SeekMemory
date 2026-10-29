"""Pure access decisions over caller-supplied session identities.

根据调用方提供的会话身份作纯权限判断，无读写或资源所有权。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AccessPolicy:
    """Decide access from reduced session and sender IDs without host calls / 根据简化的会话及发送者编号判断权限，不调用宿主。"""

    mode: str = "owner_only"
    owner_umo: str = ""
    trusted_ids: frozenset[str] = frozenset()
    observe_groups: bool = True

    @staticmethod
    def is_group(session_id: str) -> bool:
        """Recognize the existing group-session marker / 识别现有的群聊会话标记。"""
        return ":GroupMessage:" in str(session_id or "")

    def may_remember(self, session_id: str, sender_id: str) -> bool:
        """Decide whether this sender and session may be remembered / 判断是否允许记住此发送者和会话。"""
        session = str(session_id or "")
        sender = str(sender_id or "")
        if self.mode == "everyone":
            return True
        if session and session == self.owner_umo:
            return True
        if self.mode == "owner_and_trusted":
            return sender in self.trusted_ids or session == self.owner_umo
        return False

    def may_observe(self, session_id: str, sender_id: str) -> bool:
        """Allow rememberable input or permitted group observation / 允许可记忆的输入或已获准的群聊观察。"""
        if self.may_remember(session_id, sender_id):
            return True
        return bool(self.observe_groups) and self.is_group(session_id)

    def may_recall(self, session_id: str, sender_id: str) -> bool:
        """Apply the observation permission to recall / 将观察权限应用于召回。"""
        return self.may_observe(session_id, sender_id)


class AccessService:
    """Expose the configured pure access policy / 提供已配置的纯权限规则。"""

    def __init__(self, policy: AccessPolicy) -> None:
        self.policy = policy

    def may_remember(self, session_id: str, sender_id: str) -> bool:
        """Decide whether this sender and session may be remembered / 判断是否允许记住此发送者和会话。"""
        return self.policy.may_remember(session_id, sender_id)

    def may_observe(self, session_id: str, sender_id: str) -> bool:
        """Allow rememberable input or permitted group observation / 允许可记忆的输入或已获准的群聊观察。"""
        return self.policy.may_observe(session_id, sender_id)

    def may_recall(self, session_id: str, sender_id: str) -> bool:
        """Apply the observation permission to recall / 将观察权限应用于召回。"""
        return self.policy.may_recall(session_id, sender_id)

    def is_group(self, session_id: str) -> bool:
        """Recognize the existing group-session marker / 识别现有的群聊会话标记。"""
        return AccessPolicy.is_group(session_id)
