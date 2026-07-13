"""
VoiceCall Plugin - 通话状态机

管理通话生命周期状态转换：
    IDLE ──(用户拨号)──▶ CALLING ──【接听通话】/【接受通话】──▶ CONNECTED
    │                      │                          │
    │                      └──【拒绝通话】──▶ IDLE ◀───┘
    │                                                    
    └──【发起通话】──▶ RINGING ──(用户接听)──▶ CONNECTED
                          │                          
                          └──(用户拒绝)──▶ IDLE

规则：
- 同时只能存在一通通话
- IDLE 状态下才能发起/接收新通话
- CONNECTED 状态下【结束通话】或任一方挂断 → IDLE
"""

import time
import uuid
from enum import Enum, auto
from typing import Optional, Callable, Awaitable
from dataclasses import dataclass, field
import logging

logger = logging.getLogger("voice_call.state_machine")


class CallState(Enum):
    """通话状态"""
    IDLE = "idle"            # 空闲，无通话
    CALLING = "calling"      # 用户发起呼叫，等待 LLM 回应
    RINGING = "ringing"      # AI 发起呼叫，等待用户接听/拒绝
    CONNECTED = "connected"  # 通话已建立


# 状态转换表：当前状态 → 允许的目标状态
VALID_TRANSITIONS: dict[CallState, set[CallState]] = {
    CallState.IDLE:      {CallState.CALLING, CallState.RINGING},
    CallState.CALLING:   {CallState.CONNECTED, CallState.IDLE},       # 接受→接通, 拒绝/超时→空闲
    CallState.RINGING:   {CallState.CONNECTED, CallState.IDLE},       # 用户接听→接通, 拒绝→空闲
    CallState.CONNECTED: {CallState.IDLE},                             # 挂断→空闲
}


@dataclass
class CallInfo:
    """通话信息"""
    call_id: str
    direction: str          # "incoming" (AI→用户) 或 "outgoing" (用户→AI)
    init_message: Optional[str] = None  # 发起通话时的附带消息
    created_at: float = field(default_factory=time.time)


class InvalidTransitionError(Exception):
    """非法的状态转换"""
    pass


class CallStateMachine:
    """
    通话状态机

    用法:
        sm = CallStateMachine()
        sm.on_state_change = lambda old, new: print(f"{old} → {new}")

        sm.start_outgoing_call("你好")   # IDLE → CALLING
        sm.accept_call()                  # CALLING → CONNECTED
        sm.end_call()                     # CONNECTED → IDLE
    """

    def __init__(self):
        self._state: CallState = CallState.IDLE
        self._call_info: Optional[CallInfo] = None
        self._on_state_change: Optional[Callable[[CallState, CallState], Awaitable[None]]] = None

    # ── 属性 ──────────────────────────────────────────

    @property
    def state(self) -> CallState:
        return self._state

    @property
    def call_info(self) -> Optional[CallInfo]:
        return self._call_info

    @property
    def call_id(self) -> Optional[str]:
        return self._call_info.call_id if self._call_info else None

    @property
    def is_idle(self) -> bool:
        return self._state == CallState.IDLE

    @property
    def is_in_call(self) -> bool:
        return self._state == CallState.CONNECTED

    @property
    def on_state_change(self) -> Optional[Callable]:
        return self._on_state_change

    @on_state_change.setter
    def on_state_change(self, callback: Optional[Callable[[CallState, CallState], Awaitable[None]]]):
        self._on_state_change = callback

    # ── 内部方法 ──────────────────────────────────────

    def _generate_call_id(self) -> str:
        return str(uuid.uuid4())[:8]

    async def _transition(self, new_state: CallState) -> None:
        """执行状态转换"""
        allowed = VALID_TRANSITIONS.get(self._state, set())
        if new_state not in allowed:
            raise InvalidTransitionError(
                f"不允许从 {self._state.value} 转换到 {new_state.value}，"
                f"允许的目标状态: {[s.value for s in allowed]}"
            )

        old_state = self._state
        self._state = new_state
        logger.info(f"通话状态: {old_state.value} → {new_state.value}")

        if self._on_state_change:
            try:
                await self._on_state_change(old_state, new_state)
            except Exception as e:
                logger.error(f"状态回调异常: {e}")

        # 回到 IDLE 时清除通话信息
        if new_state == CallState.IDLE:
            self._call_info = None

    # ── 公开方法：状态转换 ────────────────────────────

    async def start_outgoing_call(self, message: Optional[str] = None) -> str:
        """
        用户发起通话。IDLE → CALLING

        Args:
            message: 可选的附加消息

        Returns:
            call_id

        Raises:
            InvalidTransitionError: 当前不在 IDLE 状态
        """
        if not self.is_idle:
            raise InvalidTransitionError("当前有通话正在进行，无法发起新通话")

        call_id = self._generate_call_id()
        self._call_info = CallInfo(
            call_id=call_id,
            direction="outgoing",
            init_message=message,
        )
        await self._transition(CallState.CALLING)
        return call_id

    async def start_incoming_call(self, message: Optional[str] = None) -> str:
        """
        AI 发起通话。IDLE → RINGING

        Args:
            message: AI 发起通话时的附带消息

        Returns:
            call_id

        Raises:
            InvalidTransitionError: 当前不在 IDLE 状态
        """
        if not self.is_idle:
            raise InvalidTransitionError("当前有通话正在进行，无法发起新通话")

        call_id = self._generate_call_id()
        self._call_info = CallInfo(
            call_id=call_id,
            direction="incoming",
            init_message=message,
        )
        await self._transition(CallState.RINGING)
        return call_id

    @property
    def call_duration(self) -> float:
        """当前通话已持续时间（秒），仅在 CONNECTED 时有意义"""
        if self._call_info and self._state == CallState.CONNECTED:
            return time.time() - self._call_info.created_at
        return 0.0

    async def accept_call(self) -> None:
        """
        通话被接受。CALLING/RINGING → CONNECTED

        Raises:
            InvalidTransitionError: 当前状态不允许接受通话
        """
        if self._state not in (CallState.CALLING, CallState.RINGING):
            raise InvalidTransitionError(f"当前状态 {self._state.value} 不允许接受通话")
        await self._transition(CallState.CONNECTED)

    async def reject_call(self) -> None:
        """
        通话被拒绝。CALLING/RINGING → IDLE

        Raises:
            InvalidTransitionError: 当前状态不允许拒绝通话
        """
        if self._state not in (CallState.CALLING, CallState.RINGING):
            raise InvalidTransitionError(f"当前状态 {self._state.value} 不允许拒绝通话")
        await self._transition(CallState.IDLE)

    async def end_call(self, reason: str = "hangup") -> None:
        """
        结束通话。CONNECTED → IDLE

        Args:
            reason: 挂断原因 (ai_hangup, user_hangup, rejected, timeout)

        Raises:
            InvalidTransitionError: 当前不在通话中
        """
        if self._state != CallState.CONNECTED:
            raise InvalidTransitionError(f"当前状态 {self._state.value} 不允许挂断")
        logger.info(f"通话结束，原因: {reason}")
        await self._transition(CallState.IDLE)

    async def force_reset(self) -> None:
        """强制重置到 IDLE（异常恢复用）"""
        old_state = self._state
        self._state = CallState.IDLE
        self._call_info = None
        logger.warning("状态机已强制重置为 IDLE")
        # A forced reset is still a real lifecycle change.  Notify the plugin
        # so it can cancel the ring timeout and clear per-call context; without
        # this callback a late timeout/LLM result can act on an already-reset
        # call.
        if old_state != CallState.IDLE and self._on_state_change:
            try:
                await self._on_state_change(old_state, CallState.IDLE)
            except Exception as e:
                logger.error(f"状态回调异常: {e}")
