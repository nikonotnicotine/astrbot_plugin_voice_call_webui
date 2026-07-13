"""
VoiceCall Plugin - 统一指令解析模块

负责解析 LLM 回复中的特殊控制指令：
- 【发起通话】  AI 主动发起通话
- 【接听通话】/【接受通话】  AI 接受用户通话请求
- 【拒绝通话】  AI 拒绝用户通话请求
- 【结束通话】  AI 主动挂断
- 【对方正在向你发起通话】  通知 AI 用户正在拨号
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class CommandType(Enum):
    """指令类型枚举"""
    INITIATE_CALL = "initiate_call"        # 【发起通话】AI 主动呼叫用户
    ACCEPT_CALL = "accept_call"             # 【接听通话】/【接受通话】AI 同意接听
    REJECT_CALL = "reject_call"             # 【拒绝通话】AI 拒绝接听
    END_CALL = "end_call"                   # 【结束通话】AI 挂断
    USER_CALLING = "user_calling"           # 【对方正在向你发起通话】通知 AI


@dataclass
class ParsedCommand:
    """解析后的指令"""
    type: CommandType
    content: Optional[str] = None   # 附加内容（如【发起通话】后面的消息文本）

    @property
    def has_content(self) -> bool:
        return self.content is not None and len(self.content) > 0


class CommandParser:
    """
    统一指令解析器

    用法:
        cmd = CommandParser.parse("【发起通话】你在家吗？")
        if cmd and cmd.type == CommandType.INITIATE_CALL:
            message = cmd.content  # "你在家吗？"
    """

    # 匹配 【xxx】yyyy 格式
    COMMAND_PATTERN = re.compile(r'【(.+?)】\s*(.*)', re.DOTALL)

    # 指令文本 → CommandType 映射
    COMMAND_MAP: dict[str, CommandType] = {
        "发起通话": CommandType.INITIATE_CALL,
        "接受通话": CommandType.ACCEPT_CALL,
        "接听通话": CommandType.ACCEPT_CALL,       # 客户使用的别名
        "拒绝通话": CommandType.REJECT_CALL,
        "结束通话": CommandType.END_CALL,
        "对方正在向你发起通话": CommandType.USER_CALLING,
    }

    @classmethod
    def parse(cls, text: str) -> Optional[ParsedCommand]:
        """
        解析文本中的指令。

        Args:
            text: LLM 回复文本

        Returns:
            ParsedCommand 或 None（无指令）
        """
        if not text:
            return None

        text = text.strip()
        match = cls.COMMAND_PATTERN.match(text)
        if not match:
            return None

        command_text = match.group(1).strip()
        content = match.group(2).strip() if match.group(2) else None

        cmd_type = cls.COMMAND_MAP.get(command_text)
        if cmd_type is None:
            return None

        # 处理 $ 分隔符：客户用 $ 分隔多句话，替换为换行
        if content:
            content = content.replace('$', '\n').strip()

        return ParsedCommand(type=cmd_type, content=content if content else None)

    @classmethod
    def has_command(cls, text: str) -> bool:
        """检查文本中是否包含任何指令"""
        return cls.parse(text) is not None

    @classmethod
    def extract_all(cls, text: str) -> list[ParsedCommand]:
        """
        提取文本中所有的指令（支持一行多个指令）。

        Args:
            text: 待解析文本

        Returns:
            指令列表（按出现顺序）
        """
        results = []
        for match in cls.COMMAND_PATTERN.finditer(text):
            command_text = match.group(1).strip()
            content = match.group(2).strip() if match.group(2) else None
            cmd_type = cls.COMMAND_MAP.get(command_text)
            if cmd_type:
                results.append(ParsedCommand(type=cmd_type, content=content if content else None))
        return results

    @classmethod
    def register_command(cls, command_text: str, cmd_type: CommandType) -> None:
        """
        动态注册新指令（方便扩展）。

        Args:
            command_text: 指令文本，如 "静音"
            cmd_type: 对应的 CommandType
        """
        cls.COMMAND_MAP[command_text] = cmd_type
