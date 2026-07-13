"""
VoiceCall Plugin - Mock Provider（模拟层，接口与 AstrBot 真实 Provider 一致）

在 AstrBot Provider 不可用时自动回退。
所有方法签名与真实 Provider 匹配。

真实接口：
- STT:  provider.get_text(audio_url: str) → str
- LLM:  provider.text_chat(prompt=...) → LLMResponse (有 .completion_text)
- TTS:  provider.get_audio(text: str) → str (音频文件路径)
"""

import asyncio
import io
import logging
import os
import random
import tempfile
import wave
from dataclasses import dataclass

logger = logging.getLogger("voice_call.mock_provider")


# ── 模拟 LLMResponse ──────────────────────────────────

@dataclass
class MockLLMResponse:
    completion_text: str
    """模拟 AstrBot LLMResponse"""


# ── 模拟对话数据 ──────────────────────────────────────

_ACCEPT = [
    "【接听通话】你好！请问有什么事？",
    "【接听通话】你好呀，我在呢～",
    "【接听通话】嗨！想我了没？",
]
_REJECT = [
    "【拒绝通话】抱歉，我现在不太方便接电话",
    "【拒绝通话】稍等，我这边有点忙",
]
_CHAT = [
    "嗯嗯，我听到了。",
    "好的，明白了！",
    "让我想想...哦对，你说得对。",
    "哈哈，有意思。",
    "嗯，确实是这样呢。",
    "那你觉得呢？",
    "好主意！",
]
_END = [
    "【结束通话】好的，那我先挂啦，再见！",
    "【结束通话】嗯嗯，下次再聊，拜拜～",
    "【结束通话】好，知道了，先这样吧！",
]


class MockSTT:
    """模拟 STT Provider。接口与 astrobot STTProvider 一致。"""

    def __init__(self):
        self._counter = 0
        self._phrases = ["你好", "我想问一下今天的天气怎么样", "帮我设置一个闹钟",
                         "哈哈好的", "嗯，我知道了", "那行，就这样吧"]

    async def get_text(self, audio_url: str) -> str:
        """模拟语音识别。audio_url 是音频文件路径。"""
        await asyncio.sleep(0.2)
        self._counter += 1
        text = self._phrases[(self._counter - 1) % len(self._phrases)]
        logger.info(f"[Mock STT] → {text}")
        return text


class MockLLM:
    """模拟 LLM Provider。接口与 astrobot Provider 一致。"""

    MAX_TURNS = 5

    def __init__(self):
        self._sessions: dict[str, int] = {}

    async def text_chat(self, prompt: str = None, **kwargs) -> MockLLMResponse:
        """模拟 LLM 对话。返回 LLMResponse-like 对象。"""
        await asyncio.sleep(random.uniform(0.5, 1.2))

        session_id = kwargs.get("session_id", "default")
        self._sessions.setdefault(session_id, 0)
        self._sessions[session_id] += 1
        turn = self._sessions[session_id]

        # 检测用户拨号注入
        if "对方正在向你发起通话" in (prompt or ""):
            text = random.choice(_ACCEPT) if random.random() < 0.8 else random.choice(_REJECT)
            logger.info(f"[Mock LLM] 拨号→{text}")
            return MockLLMResponse(completion_text=text)

        # 正常对话
        if turn >= self.MAX_TURNS:
            text = random.choice(_END)
            self._sessions[session_id] = 0
            logger.info(f"[Mock LLM] 第{turn}轮→自动挂断: {text}")
            return MockLLMResponse(completion_text=text)

        text = random.choice(_CHAT)
        logger.info(f"[Mock LLM] 第{turn}轮→{text}")
        return MockLLMResponse(completion_text=text)

    def meta(self):
        """模拟 Provider.meta()"""
        class M: id = "mock_llm"
        return M()

    def reset_session(self, sid: str = "default"):
        self._sessions.pop(sid, None)


class MockTTS:
    """模拟 TTS Provider。接口与 astrobot TTSProvider 一致。"""

    async def get_audio(self, text: str) -> str:
        """
        生成静默 WAV 文件并返回文件路径。
        真实 TTSProvider.get_audio() 同样返回音频文件路径。
        """
        await asyncio.sleep(0.1)

        # 生成极短静默 WAV
        fd, path = tempfile.mkstemp(suffix=".wav", prefix="voicecall_mock_")
        os.close(fd)

        sample_rate = 16000
        num_samples = int(sample_rate * 0.05)
        silent = b'\x00\x00' * num_samples

        with wave.open(path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(silent)

        logger.info(f"[Mock TTS] → {path} ({len(silent)} bytes)")
        return path

    def meta(self):
        class M: id = "mock_tts"
        return M()


class MockProviderBundle:
    """一键创建所有 Mock Provider"""

    def __init__(self):
        self.stt = MockSTT()
        self.llm = MockLLM()
        self.tts = MockTTS()

    def reset(self):
        self.llm.reset_session()
