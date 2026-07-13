"""
VoiceCall Plugin - 音频管线（对接真实 AstrBot Provider）

编排 STT → LLM → TTS 的完整处理流程。

关键适配：
- STT: AstrBot STTProvider.get_text(audio_url) 需要文件路径 → 先写临时文件
- TTS: AstrBot TTSProvider.get_audio(text) 返回文件路径 → 读取后转 Base64
- LLM: AstrBot Provider.text_chat(prompt=...) 返回 LLMResponse → 取 .completion_text
"""

import asyncio
import base64
import logging
import os
import re
import shutil
import struct
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from typing import Optional, Callable, Awaitable

from .command_parser import CommandParser, CommandType, ParsedCommand
from .call_state_machine import CallStateMachine
from .mock_provider import MockProviderBundle

logger = logging.getLogger("voice_call.audio_pipeline")


def _iter_installed_ffmpeg_binaries():
    """Yield only binaries already installed with imageio-ffmpeg."""
    try:
        import imageio_ffmpeg

        binary_dir = Path(imageio_ffmpeg.__file__).resolve().parent / "binaries"
        if not binary_dir.is_dir():
            return
        for candidate in sorted(binary_dir.glob("ffmpeg*")):
            if candidate.is_file():
                yield str(candidate)
    except Exception as exc:
        logger.debug("Unable to inspect installed imageio-ffmpeg binary: %s", exc)


def _find_ffmpeg_executable() -> Optional[str]:
    """Locate a pre-existing ffmpeg binary for optional WebM/Opus fallback."""
    explicit = os.environ.get("VOICE_CALL_FFMPEG", "").strip()
    if explicit and Path(explicit).is_file():
        return explicit
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    for bundled in _iter_installed_ffmpeg_binaries():
        return bundled
    return None


def _configure_bundled_ffmpeg() -> None:
    """Let audioread use an already-installed fallback binary, if available."""
    ffmpeg = _find_ffmpeg_executable()
    if not ffmpeg:
        logger.info("No local ffmpeg found; WebAudio PCM/WAV capture remains available")
        return
    try:
        import audioread.ffdec

        audioread.ffdec.COMMANDS = tuple(
            dict.fromkeys((ffmpeg, *audioread.ffdec.COMMANDS))
        )
        logger.info("Configured pre-installed ffmpeg for optional browser audio decoding")
    except Exception as exc:
        logger.warning("Bundled ffmpeg setup failed: %s", exc)


def _decode_browser_audio_to_wav(source_path: str) -> str:
    """Convert a legacy browser container to mono 16 kHz PCM WAV."""
    ffmpeg = _find_ffmpeg_executable()
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg，无法解码浏览器 WebM/Opus 语音")
    output_fd, output_path = tempfile.mkstemp(suffix=".wav", prefix="voicecall_stt_pcm_")
    os.close(output_fd)
    try:
        completed = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", source_path,
             "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", output_path],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "未知 ffmpeg 错误").strip()
            raise RuntimeError(f"浏览器音频解码失败：{detail[:300]}")
        with wave.open(output_path, "rb") as wav:
            valid = (
                wav.getnchannels() == 1
                and wav.getframerate() == 16000
                and wav.getsampwidth() == 2
                and wav.getcomptype() == "NONE"
            )
            if not valid:
                raise RuntimeError("浏览器音频解码后的 WAV 参数异常")
        return output_path
    except Exception:
        try:
            os.unlink(output_path)
        except OSError:
            pass
        raise


_configure_bundled_ffmpeg()


class AudioPipeline:
    """
    音频处理管线。

    当 AstrBot Provider 不可用时自动使用 Mock。
    上层通过设置 _use_mock = False 来指明使用真实 Provider。
    """

    def __init__(
        self,
        state_machine: CallStateMachine,
        stt_provider=None,
        tts_provider=None,
        llm_provider=None,
    ):
        self._sm = state_machine

        # Provider 实例
        self._stt = stt_provider
        self._tts = tts_provider
        self._llm = llm_provider

        # 是否使用 Mock（由 main.py 在 _bind_providers 后设置）
        self._use_mock = True
        self._mock_bundle: Optional[MockProviderBundle] = None

        # 回调
        self._on_tts_ready: Optional[Callable[[str, str, str, str], Awaitable[None]]] = None
        self._on_subtitle: Optional[Callable[[str, str, str], Awaitable[None]]] = None
        self._on_command: Optional[Callable[[ParsedCommand], Awaitable[None]]] = None
        self._llm_handler: Optional[Callable[[str, str], Awaitable[Optional[str]]]] = None
        self._debug_audio_dir = Path(__file__).resolve().parent / "data" / "debug_audio"
        self._debug_audio_keep = 8

    # ── 回调属性 ──────────────────────────────────────

    @property
    def on_tts_ready(self): return self._on_tts_ready

    @on_tts_ready.setter
    def on_tts_ready(self, h): self._on_tts_ready = h

    @property
    def on_subtitle(self): return self._on_subtitle

    @on_subtitle.setter
    def on_subtitle(self, h): self._on_subtitle = h

    @property
    def on_command(self): return self._on_command

    @on_command.setter
    def on_command(self, h): self._on_command = h

    @property
    def llm_handler(self): return self._llm_handler

    @llm_handler.setter
    def llm_handler(self, h): self._llm_handler = h

    # ── Provider 调用（统一接口）──────────────────────

    async def _call_stt(self, audio_bytes: bytes, audio_format: str = "webm") -> Optional[str]:
        """
        STT 语音识别。

        真实 Provider 需要文件路径 → 先写临时文件；
        Mock 也需要文件路径（接口一致）。
        """
        prov = self._get_stt()
        if prov is None:
            logger.error("STT Provider 未配置")
            return None

        # 写临时音频文件
        stats = self._audio_stats(audio_bytes, audio_format)
        logger.info(
            "STT 输入音频 format=%s size=%s duration=%.2fs rms=%.5f peak=%.5f",
            audio_format,
            len(audio_bytes),
            stats.get("duration", 0.0),
            stats.get("rms", 0.0),
            stats.get("peak", 0.0),
        )

        format_name = self._normalise_audio_format(audio_format)
        suffix = f".{format_name}"
        fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="voicecall_stt_")
        converted_path: Optional[str] = None
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(audio_bytes)
            self._save_debug_audio(audio_bytes, suffix)

            stt_path = tmp_path
            if format_name == "wav":
                self._validate_browser_wav(tmp_path)
            if format_name in {"webm", "ogg", "oga", "opus", "m4a", "mp4", "aac"}:
                converted_path = await asyncio.to_thread(_decode_browser_audio_to_wav, tmp_path)
                stt_path = converted_path
                logger.info("浏览器音频已解码为 SenseVoice WAV：%s", stt_path)

            # 调用 Provider（真实和 Mock 都接受文件路径）
            text = await prov.get_text(stt_path)
            logger.info("STT 原始返回: %r", text)
            return text
        except Exception as e:
            logger.error(f"STT 失败: {e}")
            return None
        finally:
            # 清理临时文件
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            if converted_path:
                try:
                    os.unlink(converted_path)
                except OSError:
                    pass

    async def _call_llm(self, user_text: str, session_id: str = "default") -> Optional[str]:
        """
        LLM 文本生成。

        真实 Provider.text_chat(prompt=...) → LLMResponse.completion_text
        MockLLM.text_chat(prompt=..., session_id=...) → MockLLMResponse.completion_text
        """
        if self._llm_handler:
            return await self._llm_handler(user_text, session_id)

        prov = self._get_llm()
        if prov is None:
            logger.error("LLM Provider 未配置")
            return None

        try:
            # 真实 Provider 的 text_chat 不支持 session_id（已废弃）
            # Mock Provider 需要 session_id 来做对话轮次追踪
            if self._use_mock:
                resp = await prov.text_chat(prompt=user_text, session_id=session_id)
            else:
                resp = await prov.text_chat(prompt=user_text)
            if resp is None:
                return None
            return getattr(resp, 'completion_text', str(resp))
        except Exception as e:
            logger.error(f"LLM 失败: {e}")
            return None

    async def _call_tts(self, text: str) -> Optional[bytes]:
        """
        TTS 语音合成。

        真实 Provider.get_audio() → 音频文件路径 → 读取文件 → bytes
        MockTTS.get_audio() → 音频文件路径 → 读取文件 → bytes
        """
        prov = self._get_tts()
        if prov is None:
            logger.error("TTS Provider 未配置")
            return None

        try:
            audio_path = await prov.get_audio(text)
            if not audio_path or not os.path.exists(audio_path):
                logger.error(f"TTS 输出文件不存在: {audio_path}")
                return None

            with open(audio_path, 'rb') as f:
                audio_bytes = f.read()

            # 清理临时文件
            try:
                os.unlink(audio_path)
            except OSError:
                pass

            return audio_bytes
        except Exception as e:
            logger.error(f"TTS 失败: {e}")
            return None

    # ── 处理流程 ──────────────────────────────────────

    async def process_user_audio(self, call_id: str, audio_b64: str, audio_format: str = "webm") -> Optional[str]:
        """用户语音 → STT → 文本"""
        try:
            audio_bytes = base64.b64decode(audio_b64)
        except Exception:
            logger.error("Base64 解码失败")
            return None

        if not self._looks_like_audio_container(audio_bytes, audio_format):
            logger.warning(
                "跳过无效音频包 format=%s size=%s",
                audio_format,
                len(audio_bytes),
            )
            return None

        stats = self._audio_stats(audio_bytes, audio_format)
        if self._should_skip_audio_for_stt(stats, audio_format):
            logger.info(
                "跳过静音/噪声音频 format=%s duration=%.2fs rms=%.5f peak=%.5f voiced=%.2f",
                audio_format,
                stats.get("duration", 0.0),
                stats.get("rms", 0.0),
                stats.get("peak", 0.0),
                stats.get("voiced_ratio", 0.0),
            )
            return None

        text = await self._call_stt(audio_bytes, audio_format)
        text = self._sanitize_stt_text(text)
        if text:
            logger.info(f"STT: {text}")
            await self._emit_subtitle(call_id, "user", text)
        return text

    async def process_llm_response(self, call_id: str, user_text: str) -> Optional[str]:
        """用户文本 → LLM → 回复"""
        response = await self._call_llm(user_text, session_id=call_id)
        if not response:
            return None

        logger.info(f"LLM: {response}")

        # 检测指令
        cmd = CommandParser.parse(response)
        if cmd:
            logger.info(f"指令: {cmd.type.value}")
            await self._emit_command(cmd)
            if cmd.type == CommandType.END_CALL:
                return response

        # 字幕
        display = cmd.content if (cmd and cmd.has_content) else response
        await self._emit_subtitle(call_id, "ai", display)
        return response

    async def text_to_speech(self, call_id: str, text: str) -> Optional[str]:
        """文本 → TTS → Base64 音频"""
        audio_bytes = await self._call_tts(text)
        if audio_bytes:
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
            await self._emit_tts(call_id, audio_b64, text, self._detect_audio_format(audio_bytes))
            return audio_b64
        return None

    async def run_full_pipeline(self, call_id: str, audio_b64: str, audio_format: str = "webm") -> None:
        """完整管线：用户语音 → STT → LLM → TTS → 播放"""
        text = await self.process_user_audio(call_id, audio_b64, audio_format)
        if not text:
            return
        response = await self.process_llm_response(call_id, text)
        if not response:
            return
        cmd = CommandParser.parse(response)
        if cmd and cmd.type == CommandType.END_CALL:
            return
        display = cmd.content if (cmd and cmd.has_content) else response
        await self.text_to_speech(call_id, display)

    async def run_text_pipeline(self, call_id: str, user_text: str) -> None:
        """文字输入管线：文字 → LLM → TTS → 播放"""
        await self._emit_subtitle(call_id, "user", user_text)
        response = await self.process_llm_response(call_id, user_text)
        if not response:
            return
        cmd = CommandParser.parse(response)
        if cmd and cmd.type == CommandType.END_CALL:
            return
        display = cmd.content if (cmd and cmd.has_content) else response
        await self.text_to_speech(call_id, display)

    # ── 自动 Mock 初始化 ──────────────────────────────

    def _ensure_mock(self) -> None:
        """确保 Mock Provider 已初始化"""
        if self._mock_bundle is None:
            self._mock_bundle = MockProviderBundle()

    def _get_stt(self):
        if self._stt is None:
            self._ensure_mock()
            return self._mock_bundle.stt
        return self._stt

    def _get_llm(self):
        if self._use_mock or self._llm is None:
            self._ensure_mock()
            return self._mock_bundle.llm
        return self._llm

    def _get_tts(self):
        if self._tts is None:
            self._ensure_mock()
            return self._mock_bundle.tts
        return self._tts

    @staticmethod
    def _detect_audio_format(audio_bytes: bytes) -> str:
        if audio_bytes.startswith(b"RIFF") and audio_bytes[8:12] == b"WAVE":
            return "wav"
        if audio_bytes.startswith(b"OggS"):
            return "ogg"
        if audio_bytes.startswith(b"\x1a\x45\xdf\xa3"):
            return "webm"
        # iPhone 与部分 TTS 服务可能返回 AAC/M4A。之前一律标为 mp3，
        # 会导致移动端按错误 MIME 播放失败。
        if len(audio_bytes) >= 8 and audio_bytes[4:8] == b"ftyp":
            return "m4a"
        if len(audio_bytes) >= 2 and audio_bytes[0] == 0xFF and (audio_bytes[1] & 0xF6) == 0xF0:
            return "aac"
        return "mp3"

    @staticmethod
    def _normalise_audio_format(audio_format: str) -> str:
        raw = str(audio_format or "webm").lower().strip().split(";", 1)[0]
        if "webm" in raw:
            return "webm"
        if "ogg" in raw or "opus" in raw:
            return "ogg"
        if "wav" in raw or "wave" in raw:
            return "wav"
        if "m4a" in raw or "mp4" in raw or "aac" in raw:
            return "m4a"
        return re.sub(r"[^a-z0-9]", "", raw) or "webm"

    @staticmethod
    def _validate_browser_wav(path: str) -> None:
        with wave.open(path, "rb") as wav:
            valid = (
                wav.getcomptype() == "NONE"
                and wav.getnchannels() == 1
                and wav.getsampwidth() == 2
                and wav.getframerate() == 16000
            )
            if not valid:
                raise RuntimeError(
                    "网页 WAV 必须是 16 kHz、单声道、16-bit PCM，"
                    f"实际为 rate={wav.getframerate()} channels={wav.getnchannels()} "
                    f"width={wav.getsampwidth()} compression={wav.getcomptype()}"
                )

    @staticmethod
    def _looks_like_audio_container(audio_bytes: bytes, audio_format: str) -> bool:
        if len(audio_bytes) < 16:
            return False
        fmt = AudioPipeline._normalise_audio_format(audio_format)
        if fmt == "webm":
            return audio_bytes.startswith(b"\x1a\x45\xdf\xa3")
        if fmt == "ogg":
            return audio_bytes.startswith(b"OggS")
        if fmt == "wav":
            return audio_bytes.startswith(b"RIFF") and audio_bytes[8:12] == b"WAVE"
        return True

    @staticmethod
    def _should_skip_audio_for_stt(stats: dict, audio_format: str) -> bool:
        if AudioPipeline._normalise_audio_format(audio_format) != "wav":
            return False
        duration = float(stats.get("duration", 0.0) or 0.0)
        rms = float(stats.get("rms", 0.0) or 0.0)
        peak = float(stats.get("peak", 0.0) or 0.0)
        voiced_ratio = float(stats.get("voiced_ratio", 0.0) or 0.0)
        return (
            duration < 0.7 or
            rms < 0.010 or
            peak < 0.045 or
            voiced_ratio < 0.06
        )

    @staticmethod
    def _sanitize_stt_text(text: Optional[str]) -> Optional[str]:
        if not text:
            return None
        cleaned = str(text).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        compact = re.sub(r"[\s，。！？、,.!?~…·\-—_]+", "", cleaned)
        if not compact:
            return None

        hangul_only = bool(re.fullmatch(r"[\uac00-\ud7af]+", compact))
        if hangul_only and len(compact) <= 4:
            logger.info("跳过疑似 SenseVoice 静音韩文幻觉: %r", cleaned)
            return None

        short_noise = {
            "嗯", "呃", "额", "啊", "呜", "唔",
            "嗯嗯", "啊啊", "呃呃", "额额",
            "그", "음", "어", "아",
        }
        if compact in short_noise:
            logger.info("跳过疑似静音/喘气短文本: %r", cleaned)
            return None
        if len(compact) <= 1:
            logger.info("跳过过短 STT 文本: %r", cleaned)
            return None
        return cleaned

    def _save_debug_audio(self, audio_bytes: bytes, suffix: str) -> None:
        try:
            self._debug_audio_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            path = self._debug_audio_dir / f"voicecall_{ts}_{int(time.time() * 1000) % 1000:03d}{suffix}"
            path.write_bytes(audio_bytes)

            files = sorted(
                self._debug_audio_dir.glob("voicecall_*"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for old in files[self._debug_audio_keep:]:
                try:
                    old.unlink()
                except OSError:
                    pass
        except Exception as e:
            logger.warning("保存调试音频失败: %s", e)

    @staticmethod
    def _audio_stats(audio_bytes: bytes, audio_format: str) -> dict:
        if AudioPipeline._normalise_audio_format(audio_format) != "wav":
            return {"duration": 0.0, "rms": 0.0, "peak": 0.0, "voiced_ratio": 0.0}

        tmp_dir = tempfile.mkdtemp(prefix="voicecall_stats_")
        tmp_path = Path(tmp_dir) / "audio.wav"
        try:
            tmp_path.write_bytes(audio_bytes)
            with wave.open(str(tmp_path), "rb") as wav:
                channels = wav.getnchannels()
                sample_width = wav.getsampwidth()
                rate = wav.getframerate()
                frames = wav.getnframes()
                raw = wav.readframes(frames)
            duration = frames / rate if rate else 0.0
            if sample_width != 2 or not raw:
                return {"duration": duration, "rms": 0.0, "peak": 0.0, "voiced_ratio": 0.0}

            count = len(raw) // 2
            samples = struct.unpack("<" + "h" * count, raw)
            if channels > 1:
                samples = samples[::channels]
                count = len(samples)
            if count <= 0:
                return {"duration": duration, "rms": 0.0, "peak": 0.0, "voiced_ratio": 0.0}

            peak = max(abs(s) for s in samples) / 32768.0
            rms = (sum(s * s for s in samples) / count) ** 0.5 / 32768.0
            frame_size = max(1, int(rate * 0.02)) if rate else 320
            frame_count = 0
            voiced_frames = 0
            for start in range(0, count, frame_size):
                frame = samples[start:start + frame_size]
                if not frame:
                    continue
                frame_rms = (sum(s * s for s in frame) / len(frame)) ** 0.5 / 32768.0
                if frame_rms >= 0.016:
                    voiced_frames += 1
                frame_count += 1
            voiced_ratio = voiced_frames / frame_count if frame_count else 0.0
            return {"duration": duration, "rms": rms, "peak": peak, "voiced_ratio": voiced_ratio}
        except Exception:
            return {"duration": 0.0, "rms": 0.0, "peak": 0.0, "voiced_ratio": 0.0}
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── 事件发送 ──────────────────────────────────────

    async def _emit_tts(self, call_id: str, audio_b64: str, text: str, audio_format: str) -> None:
        if self._on_tts_ready:
            try:
                await self._on_tts_ready(call_id, audio_b64, text, audio_format)
            except Exception as e:
                logger.error(f"on_tts_ready 异常: {e}")

    async def _emit_subtitle(self, call_id: str, speaker: str, text: str) -> None:
        if self._on_subtitle:
            try:
                await self._on_subtitle(call_id, speaker, text)
            except Exception as e:
                logger.error(f"on_subtitle 异常: {e}")

    async def _emit_command(self, cmd: ParsedCommand) -> None:
        if self._on_command:
            try:
                await self._on_command(cmd)
            except Exception as e:
                logger.error(f"on_command 异常: {e}")
