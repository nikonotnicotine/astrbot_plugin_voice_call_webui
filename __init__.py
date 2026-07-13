"""
VoiceCall WebUI plugin for AstrBot.

QQ / NapCat keeps the normal AstrBot conversation context, while the browser
WebUI handles microphone capture, call UI, subtitles, and TTS playback.
"""

from .main import VoiceCallPlugin

__all__ = ["VoiceCallPlugin"]

