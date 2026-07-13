"""
VoiceCall Plugin - 配置管理（对接 AstrBotConfig）

插件配置通过 AstrBot 的 _conf_schema.json 定义，
运行时由 context.get_config() 获取 AstrBotConfig 对象。

本模块为向后兼容提供便捷属性访问。
"""

from typing import Any, Optional


class PluginConfig:
    """插件配置管理器（兼容旧代码的便捷包装）"""

    DEFAULTS = {
        "show_subtitle": True,
        "sync_to_qq": False,
        "text_input_mode": True,
        "ai_call_notify_enabled": True,
        "ai_call_notify_target": "",
        "conversation_context_target": "",
        "webui_password": "voicecall",
        "openai_stt_enabled": True,
        "openai_stt_api_key": "",
        "openai_stt_base_url": "https://api.openai.com/v1",
        "openai_stt_model": "whisper-1",
        "openai_stt_language": "zh",
        "openai_stt_prompt": "",
        "openai_stt_timeout": 60,
        "stt_provider_id": "",
        "tts_provider_id": "",
        "webui_host": "127.0.0.1",
        "webui_port": 6888,
        # 兼容旧配置名
        "ws_host": "127.0.0.1",
        "ws_port": 6888,
    }

    def __init__(self, raw: Optional[dict] = None):
        self._raw = raw or {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._raw.get(key, self.DEFAULTS.get(key, default))

    @property
    def show_subtitle(self) -> bool:
        return bool(self.get("show_subtitle", True))

    @property
    def sync_to_qq(self) -> bool:
        return bool(self.get("sync_to_qq", False))

    @property
    def text_input_mode(self) -> bool:
        return bool(self.get("text_input_mode", True))

    @property
    def ai_call_notify_enabled(self) -> bool:
        return bool(self.get("ai_call_notify_enabled", True))

    @property
    def ai_call_notify_target(self) -> str:
        return str(self.get("ai_call_notify_target", "") or "").strip()

    @property
    def conversation_context_target(self) -> str:
        return str(self.get("conversation_context_target", "") or "").strip()

    @property
    def webui_password(self) -> str:
        return str(self.get("webui_password", "voicecall") or "").strip()

    @property
    def openai_stt_enabled(self) -> bool:
        return bool(self.get("openai_stt_enabled", True))

    @property
    def openai_stt_api_key(self) -> str:
        return str(self.get("openai_stt_api_key", "") or "").strip()

    @property
    def openai_stt_base_url(self) -> str:
        return str(self.get("openai_stt_base_url", "https://api.openai.com/v1") or "").strip()

    @property
    def openai_stt_model(self) -> str:
        return str(self.get("openai_stt_model", "whisper-1") or "").strip()

    @property
    def stt_provider_id(self) -> str:
        return str(self.get("stt_provider_id", "") or "").strip()

    @property
    def tts_provider_id(self) -> str:
        return str(self.get("tts_provider_id", "") or "").strip()

    @property
    def ws_host(self) -> str:
        return self.webui_host

    @property
    def ws_port(self) -> int:
        return self.webui_port

    @property
    def webui_host(self) -> str:
        return str(self.get("webui_host", self.get("ws_host", "127.0.0.1")))

    @property
    def webui_port(self) -> int:
        return int(self.get("webui_port", self.get("ws_port", 6888)))
