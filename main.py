"""
VoiceCall Plugin - AstrBot 插件入口（对接真实 AstrBot API）

基于 AstrBot Star 插件框架：
- 基类: Star (from astrbot.api.star)
- 注册: @register 装饰器
- 配置: context.get_config()
- Provider: context.get_using_provider/get_using_tts_provider/get_using_stt_provider
- LLM 调用: provider.text_chat(prompt=...)
- 消息事件: @filter.on_llm_response()
"""

import asyncio
import json
from pathlib import Path
from typing import Optional

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
from astrbot.core.message.message_event_result import MessageChain

from .command_parser import CommandParser, CommandType, ParsedCommand
from .call_state_machine import CallStateMachine, CallState, InvalidTransitionError
from .ws_server import WsServer
from .audio_pipeline import AudioPipeline
from .openai_stt import OpenAICompatibleSTTProvider

CALL_TIMEOUT = 15  # 呼叫等待超时（秒）


@register("voice_call_webui", "VoiceCall Team", "网页语音通话插件 - 在 WebUI 中实现真实语音通话，复用 AstrBot LLM/STT/TTS", "1.0.3")
class VoiceCallPlugin(Star):
    """
    AstrBot VoiceCall 插件

    QQ（NapCat）负责文字聊天和会话上下文，WebUI 负责语音通话。
    复用 AstrBot 已配置的 LLM/STT/TTS Provider，不新增独立模型配置。
    """

    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        if config is None and hasattr(context, "get_config"):
            try:
                config = context.get_config()
            except Exception:
                config = None

        # 核心模块
        self.state_machine = CallStateMachine()
        self.ws_server = WsServer(
            host="127.0.0.1",
            port=6888,
            static_root=self._resolve_webui_root(),
        )
        self.audio_pipeline: Optional[AudioPipeline] = None

        # 状态
        self._initialized = False
        self._call_timeout_task: Optional[asyncio.Task] = None
        self._ws_disconnect_task: Optional[asyncio.Task] = None
        self._pipeline_lock = asyncio.Lock()
        self._umo: Optional[str] = None
        self._active_context_umo: Optional[str] = None
        self._platform_name: Optional[str] = None
        self._platform_id: Optional[str] = None

        # 从 AstrBotConfig 读取插件配置（优先使用传入的 config，回退到 context.get_config()）
        self.show_subtitle = True
        self.sync_to_qq = False
        self.text_input_mode = True
        self.ai_call_notify_enabled = True
        self.ai_call_notify_target = ""
        self.conversation_context_target = ""
        self.webui_public_url = ""
        self.webui_password = "voicecall"
        self.openai_stt_enabled = True
        self.openai_stt_api_key = ""
        self.openai_stt_base_url = "https://api.openai.com/v1"
        self.openai_stt_model = "whisper-1"
        self.openai_stt_language = "zh"
        self.openai_stt_prompt = ""
        self.openai_stt_timeout = 60
        self.stt_provider_id = ""
        self.tts_provider_id = ""
        webui_host = "127.0.0.1"
        webui_port = 6888
        if config is not None:
            self.show_subtitle = self._config_get(config, "show_subtitle", True)
            self.sync_to_qq = self._config_get(config, "sync_to_qq", False)
            self.text_input_mode = self._config_get(config, "text_input_mode", True)
            self.ai_call_notify_enabled = self._config_get(config, "ai_call_notify_enabled", True)
            self.ai_call_notify_target = str(self._config_get(config, "ai_call_notify_target", "") or "").strip()
            self.conversation_context_target = str(self._config_get(config, "conversation_context_target", "") or "").strip()
            self.webui_public_url = str(self._config_get(config, "webui_public_url", "") or "").strip()
            self.webui_password = str(self._config_get(config, "webui_password", "voicecall") or "").strip()
            self.openai_stt_enabled = self._config_get(config, "openai_stt_enabled", True)
            self.openai_stt_api_key = str(self._config_get(config, "openai_stt_api_key", "") or "").strip()
            self.openai_stt_base_url = str(self._config_get(config, "openai_stt_base_url", "https://api.openai.com/v1") or "").strip()
            self.openai_stt_model = str(self._config_get(config, "openai_stt_model", "whisper-1") or "").strip()
            self.openai_stt_language = str(self._config_get(config, "openai_stt_language", "zh") or "").strip()
            self.openai_stt_prompt = str(self._config_get(config, "openai_stt_prompt", "") or "").strip()
            self.openai_stt_timeout = int(self._config_get(config, "openai_stt_timeout", 60) or 60)
            self.stt_provider_id = str(self._config_get(config, "stt_provider_id", "") or "").strip()
            self.tts_provider_id = str(self._config_get(config, "tts_provider_id", "") or "").strip()
            webui_host = self._config_get(config, "webui_host", self._config_get(config, "ws_host", "127.0.0.1"))
            webui_port = self._config_get(config, "webui_port", self._config_get(config, "ws_port", 6888))
        self.ws_server.host = str(webui_host)
        self.ws_server.port = int(webui_port)
        self.ws_server.password = self.webui_password

    # ═══════════════════════════════════════════════════
    # AstrBot 生命周期
    # ═══════════════════════════════════════════════════

    async def initialize(self) -> None:
        if self._initialized:
            return

        # 创建音频管线
        self.audio_pipeline = AudioPipeline(state_machine=self.state_machine)

        # 注册模块间回调
        self._register_callbacks()

        # 启动 WebSocket 服务（供 WebUI 连接）
        try:
            await self.ws_server.start()
        except OSError as e:
            logger.error(f"WebSocket 启动失败 (端口 {self.ws_server.port}): {e}")
            raise

        self._initialized = True
        logger.info("VoiceCall 插件初始化完成")

    async def terminate(self) -> None:
        if self._ws_disconnect_task and not self._ws_disconnect_task.done():
            self._ws_disconnect_task.cancel()
            self._ws_disconnect_task = None
        # 如果在非 IDLE 状态，通知 WebUI 通话结束
        if not self.state_machine.is_idle:
            try:
                await self.ws_server.send_call_ended(
                    self.state_machine.call_id or "unknown",
                    reason="plugin_shutdown",
                )
                if self.state_machine.state == CallState.CALLING:
                    await self.state_machine.reject_call()
                elif self.state_machine.state != CallState.IDLE:
                    await self.state_machine.end_call(reason="plugin_shutdown")
            except Exception:
                pass
        await self.ws_server.stop()
        logger.info("VoiceCall 插件已关闭")

    # ═══════════════════════════════════════════════════
    # AstrBot 事件：拦截 LLM 回复中的通话指令
    # ═══════════════════════════════════════════════════

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req):
        """
        记录当前 AstrBot 会话来源，供 WebUI 通话复用同一会话历史和 Provider。
        """
        self._remember_event_session(event)
        if self.audio_pipeline:
            await self._bind_providers(self._umo)
        if self.state_machine.is_in_call and hasattr(req, "prompt"):
            req.prompt = self._with_voice_call_context(getattr(req, "prompt", "") or "")

    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, response=None):
        """
        监听 LLM 回复。
        当检测到通话指令时，拦截消息并执行对应操作。
        """
        self._remember_event_session(event)

        message = ""
        if response is not None:
            message = getattr(response, "completion_text", "") or str(response)
        if not message:
            message = event.message_str or ""

        cmd = CommandParser.parse(message)
        if cmd is None:
            return  # 无指令，透传到 QQ

        logger.info(f"[LLM指令] {cmd.type.value} content={cmd.content}")
        if self.audio_pipeline:
            await self._bind_providers(self._umo)

        try:
            handled = await self._handle_command(cmd, event)
            if handled:
                if response is not None and hasattr(response, "completion_text"):
                    response.completion_text = ""
                event.stop_event()  # 阻止原消息发送到 QQ
        except InvalidTransitionError as e:
            logger.warning(f"状态转换拒绝: {e}")
        except Exception as e:
            logger.error(f"处理指令异常: {e}", exc_info=True)

    async def _handle_command(self, cmd: ParsedCommand, event: AstrMessageEvent) -> bool:
        if cmd.type == CommandType.INITIATE_CALL:
            await self._do_initiate_call(cmd)
            return True
        elif cmd.type == CommandType.ACCEPT_CALL:
            await self._do_accept_call(cmd)
            return True
        elif cmd.type == CommandType.REJECT_CALL:
            await self._do_reject_call(cmd)
            return True
        elif cmd.type == CommandType.END_CALL:
            await self._do_end_call(cmd)
            return True
        return False

    # ═══════════════════════════════════════════════════
    # WebSocket 消息分发（来自 WebUI）
    # ═══════════════════════════════════════════════════

    async def _handle_ws_message(self, data: dict) -> None:
        msg_type = data.get("type", "")
        payload = data.get("payload", {})
        handler = {
            "user_call":    self._ws_user_call,
            "answer_call":  self._ws_answer_call,
            "reject_call":  self._ws_reject_call,
            "hangup":       self._ws_hangup,
            "audio_data":   self._ws_audio_data,
            "mic_status":   self._ws_mic_status,
            "text_input":   self._ws_text_input,
        }.get(msg_type)

        if handler:
            try:
                await handler(payload)
            except Exception as e:
                logger.error(f"WS处理 '{msg_type}' 失败: {e}")
                await self.ws_server.send_error(str(e))
        else:
            logger.warning(f"未知 WS 消息: {msg_type}")

    # ═══════════════════════════════════════════════════
    # 指令执行（LLM 回复路径）
    # ═══════════════════════════════════════════════════

    async def _do_initiate_call(self, cmd: ParsedCommand) -> None:
        self._activate_context_session()
        call_id = await self.state_machine.start_incoming_call(cmd.content)
        await self.ws_server.send_incoming_call(call_id, cmd.content or "")
        await self._notify_ai_initiated_call(call_id, cmd.content or "")

    async def _do_accept_call(self, cmd: ParsedCommand) -> None:
        if self.state_machine.state != CallState.CALLING:
            return
        await self.state_machine.accept_call()
        call_id = self.state_machine.call_id
        await self.ws_server.send_call_connected(call_id)
        await self._speak(call_id, cmd.content or "你好，请问有什么事？")

    async def _do_reject_call(self, cmd: ParsedCommand) -> None:
        if self.state_machine.state != CallState.CALLING:
            return
        call_id = self.state_machine.call_id
        await self.state_machine.reject_call()
        msg = cmd.content or "抱歉，现在不方便接听"
        await self.audio_pipeline.text_to_speech(call_id, msg)
        await self._subtitle(call_id, "ai", msg)
        await self.ws_server.send_call_ended(call_id, reason="rejected")

    async def _do_end_call(self, cmd: ParsedCommand) -> None:
        if not self.state_machine.is_in_call:
            return
        call_id = self.state_machine.call_id
        msg = cmd.content or "好的，再见"
        await self.audio_pipeline.text_to_speech(call_id, msg)
        await self._subtitle(call_id, "ai", msg)
        await self.state_machine.end_call(reason="ai_hangup")
        await self.ws_server.send_call_ended(call_id, reason="ai_hangup")

    # ═══════════════════════════════════════════════════
    # WebSocket 消息处理（用户操作）
    # ═══════════════════════════════════════════════════

    async def _ws_user_call(self, payload: dict) -> None:
        """用户点击拨号 → LLM 判断 → 接通/拒绝"""
        # 如果状态卡在 CALLING（上次呼叫可能异常中断），自动重置
        if self.state_machine.state == CallState.CALLING:
            logger.warning("检测到残留 CALLING 状态，自动重置")
            await self.state_machine.force_reset()
        if not self.state_machine.is_idle:
            await self.ws_server.send_error("当前有通话正在进行，请先挂断")
            return

        self._activate_context_session()
        call_id = await self.state_machine.start_outgoing_call()
        logger.info(f"用户拨号 call_id={call_id}")

        await self.ws_server.send({"type": "call_status", "payload": {
            "call_id": call_id, "status": "calling", "message": "正在等待 AI 回应..."}})

        # 调用 AstrBot LLM。这里单独加强格式约束，避免模型只自然语言回复导致呼叫失败。
        response = await self._llm_chat(
            "【对方正在向你发起通话】\n"
            "这是一次私人网页语音通话，不是客服对话。请完全按照你当前的人设、关系和日程判断是否接听。"
            "如果接听，必须以【接听通话】或【接受通话】开头；如果拒绝，必须以【拒绝通话】开头。"
            "接听后的第一句话要像真人打电话开场，短一些、自然一些，禁止自称 AI、助手、机器人或客服，"
            "禁止说“有什么可以帮您”“请问需要什么帮助”这类服务话术。"
            "格式示例：【接听通话】怎么啦$我在呢。",
            call_id,
        )
        # The LLM request can outlive the browser call.  For example, the
        # caller may hang up, the 15-second ring timeout may fire, or the WebUI
        # may reconnect while the provider is still generating.  In all of
        # those cases the state machine has already returned to IDLE (or moved
        # to a different call), so a late reply must not try to accept/reject
        # this stale call.
        if (
            self.state_machine.state != CallState.CALLING
            or self.state_machine.call_id != call_id
        ):
            logger.info(
                "忽略已结束或已替换的用户拨号结果 call_id=%s state=%s active_call_id=%s",
                call_id,
                self.state_machine.state.value,
                self.state_machine.call_id,
            )
            return
        if response is None:
            await self._fail(call_id, "llm_error", "AI 未响应")
            return

        logger.info(f"用户拨号 LLM 回复: {response}")
        cmd = CommandParser.parse(response)
        if cmd is None:
            logger.warning("用户拨号 LLM 回复未包含通话指令，按接听处理")
            cmd = ParsedCommand(CommandType.ACCEPT_CALL, response.strip() or "我在，怎么啦？")

        if cmd.type == CommandType.ACCEPT_CALL:
            await self.state_machine.accept_call()
            await self.ws_server.send_call_connected(call_id)
            await self._speak(call_id, self._sanitize_call_greeting(cmd.content or "我在，怎么啦？"))
        elif cmd.type == CommandType.REJECT_CALL:
            await self.state_machine.reject_call()
            msg = cmd.content or "抱歉，现在不方便接听"
            await self.audio_pipeline.text_to_speech(call_id, msg)
            await self._subtitle(call_id, "ai", msg)
            await self.ws_server.send_call_ended(call_id, reason="rejected")
        elif cmd.type == CommandType.USER_CALLING:
            await self.state_machine.accept_call()
            await self.ws_server.send_call_connected(call_id)
            await self._speak(call_id, cmd.content or "我在，怎么啦？")
        else:
            await self._fail(call_id, "invalid_command")

    async def _ws_answer_call(self, payload: dict) -> None:
        call_id = payload.get("call_id", "")
        if call_id != self.state_machine.call_id:
            return await self.ws_server.send_error("通话 ID 不匹配")
        try:
            await self.state_machine.accept_call()
            await self.ws_server.send_call_connected(call_id)
            init_message = self.state_machine.call_info.init_message if self.state_machine.call_info else ""
            if init_message:
                await self._speak(call_id, init_message)
        except InvalidTransitionError as e:
            await self.ws_server.send_error(str(e))

    async def _ws_reject_call(self, payload: dict) -> None:
        call_id = payload.get("call_id", "")
        if call_id != self.state_machine.call_id:
            return await self.ws_server.send_error("通话 ID 不匹配")
        try:
            await self.state_machine.reject_call()
            await self.ws_server.send_call_ended(call_id, reason="user_rejected")
        except InvalidTransitionError as e:
            await self.ws_server.send_error(str(e))

    async def _ws_hangup(self, payload: dict) -> None:
        call_id = payload.get("call_id", "")
        reason = "user_cancelled" if self.state_machine.state == CallState.CALLING else "user_hangup"
        if call_id and call_id != self.state_machine.call_id:
            return await self.ws_server.send_error("通话 ID 不匹配")
        try:
            if self.state_machine.state in (CallState.CALLING, CallState.RINGING):
                await self.state_machine.reject_call()
            else:
                await self.state_machine.end_call(reason=reason)
            await self.ws_server.send_call_ended(call_id, reason=reason)
        except InvalidTransitionError as e:
            await self.ws_server.send_error(str(e))

    async def _ws_audio_data(self, payload: dict) -> None:
        if not self.state_machine.is_in_call:
            return
        call_id = payload.get("call_id", "")
        if call_id != self.state_machine.call_id:
            return await self.ws_server.send_error("通话 ID 不匹配")
        if self._pipeline_lock.locked():
            logger.debug("上一段语音仍在处理，丢弃当前音频片段")
            return
        audio_b64 = payload.get("audio", "")
        fmt = payload.get("format", "webm")
        if audio_b64:
            logger.info(
                "收到网页音频包 call_id=%s format=%s base64_len=%s",
                call_id,
                fmt,
                len(audio_b64),
            )
            async with self._pipeline_lock:
                if self.audio_pipeline and self.audio_pipeline._stt is None:
                    await self._bind_providers(self._umo)
                await self.audio_pipeline.run_full_pipeline(call_id, audio_b64, fmt)

    async def _ws_mic_status(self, payload: dict) -> None:
        logger.info(f"麦克风: muted={payload.get('muted', False)}")

    async def _ws_text_input(self, payload: dict) -> None:
        if not self.text_input_mode:
            return await self.ws_server.send_error("文字输入模式未开启")
        if not self.state_machine.is_in_call:
            return
        call_id = payload.get("call_id", "")
        if call_id != self.state_machine.call_id:
            return await self.ws_server.send_error("通话 ID 不匹配")
        text = payload.get("text", "")
        if text:
            async with self._pipeline_lock:
                if self.audio_pipeline and (self.audio_pipeline._llm is None or self.audio_pipeline._tts is None):
                    await self._bind_providers(self._umo)
                await self.audio_pipeline.run_text_pipeline(call_id, text)

    # ═══════════════════════════════════════════════════
    # 内部辅助
    # ═══════════════════════════════════════════════════

    async def _bind_providers(self, umo: Optional[str] = None) -> None:
        """绑定 AstrBot 已配置的 LLM/STT/TTS Provider"""
        umo = umo if umo is not None else self._umo
        if not self.audio_pipeline:
            return

        llm = self._get_using_provider("LLM", self.context.get_using_provider, umo)
        tts = self._get_configured_provider(self.tts_provider_id, "TTS")
        if tts is None:
            tts = self._get_using_provider("TTS", self.context.get_using_tts_provider, umo)
        stt = self._build_openai_stt_provider() if self.openai_stt_enabled else None
        if stt is None and not self.openai_stt_enabled:
            stt = self._get_configured_provider(self.stt_provider_id, "STT")
            if stt is None:
                stt = self._get_using_provider("STT", self.context.get_using_stt_provider, umo)

        self.audio_pipeline._llm = llm
        self.audio_pipeline._tts = tts
        self.audio_pipeline._stt = stt
        self.audio_pipeline._use_mock = llm is None

        if llm:
            logger.info(f"LLM: {self._provider_id(llm)}")
        if tts:
            logger.info(f"TTS: {self._provider_id(tts)}")
        if stt:
            logger.info(f"STT: {self._provider_id(stt)}")

        missing = []
        if not llm:
            missing.append("LLM")
        if not tts:
            missing.append("TTS")
        if not stt:
            missing.append("STT")
        if missing:
            logger.warning(f"{'/'.join(missing)} Provider 未配置或不可用，将按模块使用 Mock 回退")

    def _build_openai_stt_provider(self):
        if not self.openai_stt_api_key:
            logger.warning("OpenAI compatible STT is enabled but openai_stt_api_key is empty")
            return None
        return OpenAICompatibleSTTProvider(
            api_key=self.openai_stt_api_key,
            base_url=self.openai_stt_base_url,
            model=self.openai_stt_model,
            language=self.openai_stt_language,
            prompt=self.openai_stt_prompt,
            timeout=self.openai_stt_timeout,
        )

    def _get_using_provider(self, provider_name: str, getter, umo: Optional[str]):
        try:
            return getter(umo)
        except TypeError:
            try:
                return getter()
            except Exception as e:
                logger.warning(f"当前会话 {provider_name} Provider 获取失败: {e}")
                return None
        except Exception as e:
            logger.warning(f"当前会话 {provider_name} Provider 获取失败: {e}")
            return None

    def _get_configured_provider(self, provider_id: str, provider_name: str):
        if not provider_id:
            return None
        try:
            provider = self.context.get_provider_by_id(provider_id)
        except Exception as e:
            logger.warning(f"{provider_name} Provider {provider_id} 获取失败: {e}")
            return None
        if not provider:
            logger.warning(f"{provider_name} Provider {provider_id} 未找到，将使用当前会话 Provider")
            return None
        if provider_name == "STT" and not hasattr(provider, "get_text"):
            logger.warning(f"{provider_id} 不是可用的 STT Provider，将使用当前会话 Provider")
            return None
        if provider_name == "TTS" and not hasattr(provider, "get_audio"):
            logger.warning(f"{provider_id} 不是可用的 TTS Provider，将使用当前会话 Provider")
            return None
        return provider

    @staticmethod
    def _provider_id(provider) -> str:
        try:
            meta = provider.meta()
            return getattr(meta, "id", str(meta))
        except Exception:
            return provider.__class__.__name__

    async def _llm_chat(self, prompt: str, session_id: str = "default") -> Optional[str]:
        """调用 LLM，并尽量复用 AstrBot 当前会话历史。"""
        if not self.audio_pipeline:
            return None

        context_umo = self._get_context_umo()
        await self._bind_providers(context_umo)
        provider = self.audio_pipeline._get_llm()
        if provider is None:
            logger.error("LLM Provider 未配置")
            return None

        llm_prompt = self._with_voice_call_context(prompt)

        if self.audio_pipeline._use_mock:
            resp = await provider.text_chat(prompt=llm_prompt, session_id=session_id)
            return getattr(resp, "completion_text", str(resp)) if resp else None

        conversation = await self._get_current_conversation(context_umo)
        contexts = self._load_history(conversation)
        contexts = await self._apply_persona_begin_dialogs(contexts, conversation, context_umo)
        system_prompt = await self._get_persona_prompt(conversation, context_umo)
        provider_session_id = context_umo or session_id
        logger.info(
            "通话 LLM 上下文: umo=%s contexts=%s system_prompt_len=%s",
            provider_session_id,
            len(contexts),
            len(system_prompt or ""),
        )

        resp = await self._call_provider_text_chat(
            provider,
            prompt=llm_prompt,
            session_id=provider_session_id,
            contexts=contexts,
            system_prompt=system_prompt,
        )
        text = getattr(resp, "completion_text", str(resp)) if resp else None
        if text:
            await self._save_conversation_turn(conversation, prompt, text, context_umo)
        return text

    @staticmethod
    def _with_voice_call_context(prompt: str) -> str:
        marker = "[当前正在语音通话中...]"
        text = str(prompt or "")
        if text.lstrip().startswith(marker):
            return text
        return f"{marker}\n{text}"

    async def _speak(self, call_id: str, text: str) -> None:
        """TTS + 播放 + 字幕"""
        await self.audio_pipeline.text_to_speech(call_id, text)
        await self._subtitle(call_id, "ai", text)

    @staticmethod
    def _sanitize_call_greeting(text: str) -> str:
        stripped = (text or "").strip()
        banned = ("AI", "ai", "助手", "机器人", "客服", "帮您", "帮助您", "有什么可以帮")
        if not stripped or any(word in stripped for word in banned):
            return "我在，怎么啦？"
        return stripped

    async def _subtitle(self, call_id: str, speaker: str, text: str) -> None:
        """字幕 + 可选 QQ 同步"""
        if self.show_subtitle:
            await self.ws_server.send_subtitle(call_id, speaker, text)
        if self.sync_to_qq and speaker == "ai" and self._umo:
            try:
                chain = MessageChain().message(text)
                await self.context.send_message(self._umo, chain)
                logger.info(f"[QQ同步] 已发送: {text[:30]}...")
            except Exception as e:
                logger.warning(f"[QQ同步] 发送失败: {e}")

    async def _notify_ai_initiated_call(self, call_id: str, message: str = "") -> None:
        if not self.ai_call_notify_enabled:
            return

        target = self._resolve_ai_call_notify_target()
        if not target:
            logger.warning("[AI来电通知] 未找到可用 QQ 通知目标")
            return

        webui_url = self._webui_url()
        lines = [
            "【网页电话】AI 正在向你发起通话",
            f"通话 ID：{call_id}",
        ]
        if message:
            lines.append(f"来电内容：{message}")
        lines.append(f"打开 WebUI 接听：{webui_url}")
        lines.append("如果页面已经打开，会自动弹出来电界面。")

        try:
            chain = MessageChain().message("\n".join(lines))
            await self.context.send_message(target, chain)
            logger.info(f"[AI来电通知] 已发送 target={target} call_id={call_id}")
        except Exception as e:
            logger.warning(f"[AI来电通知] 发送失败 target={target}: {e}")

    def _resolve_ai_call_notify_target(self) -> Optional[str]:
        target = (self.ai_call_notify_target or "").strip()
        return self._resolve_target_umo(target) if target else self._umo

    def _resolve_context_target(self) -> Optional[str]:
        """将配置中的指定 QQ / UMO 解析为 AstrBot 会话来源。"""
        return self._resolve_target_umo(self.conversation_context_target)

    def _resolve_target_umo(self, target: str) -> Optional[str]:
        """支持 QQ 号、group:群号和完整 unified_msg_origin。"""
        target = str(target or "").strip()
        if not target:
            return None
        if target.lower().startswith("group:"):
            group_id = target.split(":", 1)[1].strip()
            if not group_id.isdigit():
                logger.warning("目标群号格式不正确: %s", target)
                return None
            return f"{self._umo_platform_id()}:GroupMessage:{group_id}"
        if target.isdigit():
            # 明确填写 QQ 号时，始终按私聊发送/读取，不能继承当前群聊的消息类型。
            return f"{self._umo_platform_id()}:FriendMessage:{target}"
        return target

    def _umo_platform_id(self) -> str:
        if self._platform_id:
            return str(self._platform_id)
        if self._platform_name:
            return str(self._platform_name)
        if self._umo:
            return self._umo.split(":", 1)[0]
        return "aiocqhttp"

    def _activate_context_session(self) -> Optional[str]:
        """在一次通话开始时固定上下文，避免其他 QQ 消息切换通话记忆。"""
        self._active_context_umo = self._resolve_context_target() or self._umo
        if self._active_context_umo:
            logger.info("通话上下文已锁定到 umo=%s", self._active_context_umo)
        else:
            logger.warning("通话未找到 AstrBot 上下文；请配置“通话上下文 QQ”或先与机器人私聊一次")
        return self._active_context_umo

    def _get_context_umo(self) -> Optional[str]:
        return self._active_context_umo or self._resolve_context_target() or self._umo

    def _webui_url(self) -> str:
        if self.webui_public_url:
            return self.webui_public_url.rstrip("/") + "/"
        host = self.ws_server.host or "127.0.0.1"
        if host in ("0.0.0.0", "::"):
            host = "127.0.0.1"
        return f"http://{host}:{self.ws_server.port}/"

    async def _fail(self, call_id: str, reason: str, msg: str = "") -> None:
        if self.state_machine.state in (CallState.CALLING, CallState.RINGING):
            await self.state_machine.reject_call()
        elif self.state_machine.state == CallState.CONNECTED:
            await self.state_machine.end_call(reason=reason)
        await self.ws_server.send_call_ended(call_id, reason=reason)
        if msg:
            await self.ws_server.send_error(msg)

    @staticmethod
    def _config_get(config: AstrBotConfig, key: str, default):
        return config.get(key, default) if hasattr(config, "get") else default

    def _remember_event_session(self, event: AstrMessageEvent) -> None:
        self._umo = event.unified_msg_origin
        try:
            self._platform_name = event.get_platform_name()
        except Exception:
            self._platform_name = self._umo.split(":")[0] if self._umo else None
        try:
            self._platform_id = event.get_platform_id()
        except Exception:
            self._platform_id = self._umo.split(":")[0] if self._umo else None

    @staticmethod
    def _resolve_webui_root() -> Path:
        """定位 WebUI 静态文件目录。"""
        plugin_dir = Path(__file__).resolve().parent
        candidates = [
            plugin_dir / "webui",
            plugin_dir,
            plugin_dir.parent,
        ]
        for candidate in candidates:
            if (candidate / "index.html").is_file():
                return candidate
        return plugin_dir.parent

    async def _get_current_conversation(self, umo: Optional[str] = None):
        umo = umo or self._get_context_umo()
        if not umo:
            return None
        conv_mgr = getattr(self.context, "conversation_manager", None)
        if not conv_mgr:
            return None
        try:
            cid = await conv_mgr.get_curr_conversation_id(umo)
            if not cid:
                cid = await conv_mgr.new_conversation(umo, self._umo_platform_id())
            return await conv_mgr.get_conversation(umo, cid)
        except Exception as e:
            logger.warning(f"读取 AstrBot 会话失败 umo={umo}: {e}")
            return None

    @staticmethod
    def _load_history(conversation) -> list[dict]:
        if not conversation:
            return []
        history = getattr(conversation, "history", None)
        if not history:
            return []
        if isinstance(history, list):
            return list(history)
        try:
            parsed = json.loads(history)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []

    async def _apply_persona_begin_dialogs(self, contexts: list[dict], conversation, umo: Optional[str] = None) -> list[dict]:
        persona = await self._resolve_persona(conversation, umo)
        begin_dialogs = None
        if persona:
            begin_dialogs = (
                self._persona_get(persona, "_begin_dialogs_processed")
                or self._persona_get(persona, "begin_dialogs")
            )
        normalized = self._normalize_begin_dialogs(begin_dialogs)
        if normalized:
            return normalized + contexts
        return contexts

    async def _get_persona_prompt(self, conversation, umo: Optional[str] = None) -> str:
        persona = await self._resolve_persona(conversation, umo)
        prompt = self._persona_prompt(persona)
        if persona:
            logger.info(
                "通话使用 AstrBot 人设: id=%s prompt_len=%s",
                self._persona_id(persona),
                len(prompt),
            )
        else:
            logger.warning("通话未解析到 AstrBot 人设，将使用空 system_prompt")
        return prompt

    @staticmethod
    def _normalize_begin_dialogs(begin_dialogs) -> list[dict]:
        if not isinstance(begin_dialogs, list):
            return []
        if all(isinstance(item, dict) for item in begin_dialogs):
            return list(begin_dialogs)
        normalized = []
        user_turn = True
        for item in begin_dialogs:
            if not isinstance(item, str):
                continue
            normalized.append({
                "role": "user" if user_turn else "assistant",
                "content": item,
                "_no_save": True,
            })
            user_turn = not user_turn
        return normalized

    def _persona_prompt(self, persona) -> str:
        if not persona:
            return ""
        return str(
            self._persona_get(persona, "prompt", "")
            or self._persona_get(persona, "system_prompt", "")
            or ""
        )

    def _persona_id(self, persona) -> str:
        if not persona:
            return ""
        return str(
            self._persona_get(persona, "name", "")
            or self._persona_get(persona, "persona_id", "")
            or ""
        )

    @staticmethod
    def _persona_get(persona, key: str, default=None):
        if isinstance(persona, dict):
            return persona.get(key, default)
        return getattr(persona, key, default)

    async def _resolve_persona(self, conversation, umo: Optional[str] = None):
        persona_mgr = getattr(self.context, "persona_manager", None)
        if not persona_mgr:
            return None
        umo = umo or self._get_context_umo()
        persona_id = getattr(conversation, "persona_id", None) if conversation else None
        try:
            if hasattr(persona_mgr, "resolve_selected_persona") and umo:
                provider_settings = {}
                try:
                    cfg = self.context.get_config(umo)
                    provider_settings = cfg.get("provider_settings", {}) if hasattr(cfg, "get") else {}
                except Exception:
                    provider_settings = {}

                _, persona, _, _ = await persona_mgr.resolve_selected_persona(
                    umo=umo,
                    conversation_persona_id=persona_id,
                    platform_name=self._platform_name or umo.split(":")[0],
                    provider_settings=provider_settings,
                )
                if persona:
                    return persona
            if persona_id and hasattr(persona_mgr, "get_persona_v3_by_id"):
                persona = persona_mgr.get_persona_v3_by_id(persona_id)
                if persona:
                    return persona
            if persona_id and hasattr(persona_mgr, "get_persona"):
                persona = await persona_mgr.get_persona(persona_id)
                if persona:
                    return persona
            if hasattr(persona_mgr, "get_default_persona_v3"):
                persona = await persona_mgr.get_default_persona_v3(umo)
                if persona:
                    return persona
            persona = getattr(persona_mgr, "selected_default_persona_v3", None)
            if persona:
                return persona
            persona = getattr(persona_mgr, "selected_default_persona", None)
            if persona:
                return persona
        except Exception as e:
            logger.warning(f"读取 AstrBot 人设失败: {e}")
        return None

    async def _call_provider_text_chat(
        self,
        provider,
        prompt: str,
        session_id: str,
        contexts: list[dict],
        system_prompt: str,
    ):
        attempts = [
            {
                "prompt": prompt,
                "session_id": session_id,
                "contexts": contexts,
                "system_prompt": system_prompt,
            },
            {
                "prompt": prompt,
                "contexts": contexts,
                "system_prompt": system_prompt,
            },
            {
                "prompt": prompt,
                "contexts": contexts,
            },
            {
                "prompt": prompt,
            },
        ]
        last_error = None
        for kwargs in attempts:
            try:
                return await provider.text_chat(**kwargs)
            except TypeError as e:
                last_error = e
                continue
        logger.error(f"LLM 参数不兼容: {last_error}")
        return None

    async def _save_conversation_turn(
        self,
        conversation,
        user_text: str,
        assistant_text: str,
        umo: Optional[str] = None,
    ) -> None:
        umo = umo or self._get_context_umo()
        if not conversation or not umo:
            return
        conv_mgr = getattr(self.context, "conversation_manager", None)
        if not conv_mgr:
            return

        history = self._load_history(conversation)
        stored_user = self._display_text_for_history(user_text, fallback="用户通过网页向你发起了通话")
        stored_ai = self._display_text_for_history(assistant_text)
        history.extend([
            {"role": "user", "content": stored_user},
            {"role": "assistant", "content": stored_ai},
        ])
        try:
            await conv_mgr.update_conversation(umo, conversation.cid, history=history)
        except Exception as e:
            logger.warning(f"写入 AstrBot 会话失败 umo={umo}: {e}")

    @staticmethod
    def _display_text_for_history(text: str, fallback: str = "") -> str:
        cmd = CommandParser.parse(text)
        if cmd:
            return cmd.content or fallback or text
        return text

    # ═══════════════════════════════════════════════════
    # 回调
    # ═══════════════════════════════════════════════════

    def _register_callbacks(self) -> None:
        self.ws_server.on_message = self._handle_ws_message
        self.state_machine.on_state_change = self._on_state_change
        # 允许手机在短暂断网、锁屏或接管桌面页面后恢复同一通话。
        self.ws_server.on_disconnect = self._on_ws_disconnect
        self.ws_server.on_connect = self._on_ws_connect
        if self.audio_pipeline:
            self.audio_pipeline.on_tts_ready = self._on_tts
            self.audio_pipeline.on_subtitle = self._subtitle
            self.audio_pipeline.on_command = self._on_cmd
            self.audio_pipeline.llm_handler = self._llm_chat

    async def _on_ws_connect(self) -> None:
        """WebUI 新连接 → 同步未结束的来电/通话，而不是重置状态。"""
        if self._ws_disconnect_task and not self._ws_disconnect_task.done():
            self._ws_disconnect_task.cancel()
        self._ws_disconnect_task = None
        await self._bind_providers(self._get_context_umo())
        await self.ws_server.send_config({
            "show_subtitle": self.show_subtitle,
            "sync_to_qq": self.sync_to_qq,
            "text_input_mode": self.text_input_mode,
            "stt_provider_id": "openai_compatible_stt" if self.openai_stt_enabled else self.stt_provider_id,
            "tts_provider_id": self.tts_provider_id,
        })

        call_id = self.state_machine.call_id
        if not call_id:
            return
        if self.state_machine.state == CallState.RINGING:
            message = self.state_machine.call_info.init_message if self.state_machine.call_info else ""
            await self.ws_server.send_incoming_call(call_id, message or "")
        elif self.state_machine.state == CallState.CONNECTED:
            await self.ws_server.send_call_connected(call_id)
        elif self.state_machine.state == CallState.CALLING:
            await self.ws_server.send({"type": "call_status", "payload": {
                "call_id": call_id,
                "status": "calling",
                "message": "正在等待 AI 回应...",
            }})

    async def _on_ws_disconnect(self) -> None:
        """WebUI 断开 → 留出短暂重连窗口，避免手机锁屏/切后台直接挂断。"""
        if self.state_machine.is_idle:
            return
        if self._ws_disconnect_task and not self._ws_disconnect_task.done():
            self._ws_disconnect_task.cancel()
        self._ws_disconnect_task = asyncio.create_task(self._reset_after_ws_disconnect())

    async def _reset_after_ws_disconnect(self) -> None:
        try:
            await asyncio.sleep(20)
            if not self.ws_server.is_connected and not self.state_machine.is_idle:
                logger.warning(
                    f"WebUI 断开超过 20 秒，结束未恢复通话 "
                    f"(state={self.state_machine.state.value})"
                )
                await self.state_machine.force_reset()
        except asyncio.CancelledError:
            return

    async def _on_tts(
        self,
        call_id: str,
        audio_b64: str,
        text: str,
        audio_format: str = "mp3",
    ) -> None:
        await self.ws_server.send_play_audio(call_id, audio_b64, text, audio_format)

    async def _on_cmd(self, cmd: ParsedCommand) -> None:
        if cmd.type == CommandType.END_CALL and self.state_machine.call_id:
            cid = self.state_machine.call_id
            await self._speak(cid, cmd.content or "好的，再见")
            await self.state_machine.end_call(reason="ai_hangup")
            await self.ws_server.send_call_ended(cid, reason="ai_hangup")

    async def _on_state_change(self, old: CallState, new: CallState) -> None:
        if self._call_timeout_task and not self._call_timeout_task.done():
            self._call_timeout_task.cancel()
            self._call_timeout_task = None
        if new == CallState.CALLING:
            self._call_timeout_task = asyncio.create_task(
                self._timeout(self.state_machine.call_id))
        elif new == CallState.IDLE:
            self._active_context_umo = None

    async def _timeout(self, call_id: str) -> None:
        try:
            await asyncio.sleep(CALL_TIMEOUT)
            if self.state_machine.state == CallState.CALLING and self.state_machine.call_id == call_id:
                logger.warning(f"呼叫超时 call_id={call_id}")
                await self.state_machine.reject_call()
                await self.ws_server.send_call_ended(call_id, reason="timeout")
                await self.ws_server.send_error("呼叫超时")
        except asyncio.CancelledError:
            pass
