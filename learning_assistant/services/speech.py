"""Speech provider interface and a persistent Windows SAPI implementation."""

from __future__ import annotations

import hashlib
from pathlib import Path
import queue
import re
import threading
from xml.sax.saxutils import escape

from PySide6.QtCore import QObject, Signal

from learning_assistant.core.paths import app_data_dir
from learning_assistant.core.settings import SettingsStore


class SpeechProvider:
    def speak(self, text: str, locale: str = "en-US") -> bool:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError


class SapiSpeechService(QObject, SpeechProvider):
    """Keeps one COM synthesizer alive instead of spawning PowerShell per click."""

    started = Signal(str)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, rate: int = -1, parent: QObject | None = None):
        super().__init__(parent)
        self.rate = max(-10, min(10, int(rate)))
        self._commands: queue.Queue[tuple[str, str, str]] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="sapi-speech", daemon=True)
        self._thread.start()

    def speak(self, text: str, locale: str = "en-US") -> bool:
        text = text.strip()
        if not text:
            return False
        self._commands.put(("speak", text, locale))
        return True

    def stop(self) -> None:
        self._commands.put(("stop", "", ""))

    def close(self) -> None:
        self._commands.put(("quit", "", ""))

    @staticmethod
    def _select_voice(voice, locale: str) -> None:
        language_codes = {
            "en-US": ("409", "en-us", "english (united states)"),
            "en-GB": ("809", "en-gb", "english (united kingdom)"),
        }
        wanted = language_codes.get(locale, language_codes["en-US"])
        voices = voice.GetVoices()
        fallback = None
        for index in range(voices.Count):
            token = voices.Item(index)
            description = str(token.GetDescription()).casefold()
            try:
                language = str(token.GetAttribute("Language")).casefold()
            except Exception:
                language = ""
            if fallback is None and "english" in description:
                fallback = token
            if any(item in description or item in language for item in wanted):
                voice.Voice = token
                return
        if fallback is not None:
            voice.Voice = fallback

    def _run(self) -> None:
        try:
            import pythoncom
            import win32com.client
        except Exception:
            self.failed.emit("Windows 语音组件不可用")
            return
        pythoncom.CoInitialize()
        try:
            voice = win32com.client.Dispatch("SAPI.SpVoice")
            voice.Rate = self.rate
            while True:
                action, text, locale = self._commands.get()
                if action == "quit":
                    voice.Speak("", 3)
                    return
                if action == "stop":
                    voice.Speak("", 3)  # async + purge queued speech
                    continue
                try:
                    self._select_voice(voice, locale)
                    voice.Rate = self.rate
                    voice.Speak(text, 3)
                    self.started.emit(text)
                    while not voice.WaitUntilDone(80):
                        try:
                            queued = self._commands.get_nowait()
                        except queue.Empty:
                            continue
                        queued_action, queued_text, queued_locale = queued
                        if queued_action == "quit":
                            voice.Speak("", 3)
                            return
                        if queued_action == "stop":
                            voice.Speak("", 3)
                            break
                        voice.Speak("", 3)
                        self._commands.put((queued_action, queued_text, queued_locale))
                        break
                    self.finished.emit()
                except Exception as exc:
                    self.failed.emit(f"朗读失败：{exc}")
        finally:
            try:
                del voice
            except UnboundLocalError:
                pass
            pythoncom.CoUninitialize()


class AzureSpeechService(QObject, SpeechProvider):
    """Azure neural TTS with a small on-disk WAV cache.

    Synthesis happens off the UI thread. Azure returns PCM WAV so Windows can
    play it without shipping another media runtime.
    """

    started = Signal(str)
    finished = Signal()
    failed = Signal(str)

    _REGION = re.compile(r"^[a-z0-9-]+$")

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._commands: queue.Queue[tuple[str, str, str, str, str]] = queue.Queue()
        self._cache_dir = app_data_dir() / "speech-cache"
        self._thread = threading.Thread(target=self._run, name="azure-speech", daemon=True)
        self._thread.start()

    def speak_with_config(
        self, text: str, locale: str, *, key: str, region: str, voice: str
    ) -> bool:
        text = text.strip()
        region = region.strip().casefold()
        if not text or not key or not region or not self._REGION.fullmatch(region):
            return False
        self._commands.put(("speak", text, locale, key, region + "|" + voice))
        return True

    def speak(self, text: str, locale: str = "en-US") -> bool:
        return False

    def stop(self) -> None:
        self._commands.put(("stop", "", "", "", ""))
        try:
            import winsound

            winsound.PlaySound(None, 0)
        except Exception:
            pass

    def close(self) -> None:
        self._commands.put(("quit", "", "", "", ""))
        self.stop()

    def _run(self) -> None:
        try:
            import requests
            import winsound
        except Exception:
            self.failed.emit("神经语音组件不可用，请重新安装依赖")
            return
        while True:
            action, text, locale, key, location = self._commands.get()
            if action == "quit":
                return
            if action == "stop":
                continue
            region, voice = location.split("|", 1)
            voice = voice or ("en-US-JennyNeural" if locale == "en-US" else "en-GB-SoniaNeural")
            digest = hashlib.sha256(f"{voice}\0{text}".encode("utf-8")).hexdigest()
            target = self._cache_dir / f"{digest}.wav"
            try:
                if not target.exists():
                    self._cache_dir.mkdir(parents=True, exist_ok=True)
                    response = requests.post(
                        f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
                        headers={
                            "Ocp-Apim-Subscription-Key": key,
                            "Content-Type": "application/ssml+xml",
                            "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
                            "User-Agent": "LinguaSpark",
                        },
                        data=(
                            f'<speak version="1.0" xml:lang="{locale}">'
                            f'<voice name="{voice}">{escape(text)}</voice></speak>'
                        ).encode("utf-8"),
                        timeout=(5, 20),
                    )
                    response.raise_for_status()
                    temporary = target.with_suffix(".tmp")
                    temporary.write_bytes(response.content)
                    temporary.replace(target)
                self.started.emit(text)
                winsound.PlaySound(
                    str(target),
                    winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
                )
                self.finished.emit()
            except Exception as exc:
                message = str(exc)
                if "401" in message or "403" in message:
                    message = "Azure Speech 密钥或区域无效"
                elif "timed out" in message.casefold():
                    message = "神经语音连接超时"
                self.failed.emit(f"朗读失败：{message}")


class SpeechService(QObject, SpeechProvider):
    """Selects the configured provider while keeping UI code provider-free."""

    started = Signal(str)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, settings: SettingsStore, parent: QObject | None = None):
        super().__init__(parent)
        self.settings = settings
        self.sapi = SapiSpeechService(parent=self)
        self.azure = AzureSpeechService(parent=self)
        for provider in (self.sapi, self.azure):
            provider.started.connect(self.started)
            provider.finished.connect(self.finished)
            provider.failed.connect(self.failed)

    def speak(self, text: str, locale: str = "en-US") -> bool:
        config = dict(self.settings.get("tts", {}))
        if config.get("provider") == "azure":
            return self.azure.speak_with_config(
                text,
                locale,
                key=self.settings.azure_speech_key(),
                region=str(config.get("azure_region", "")),
                voice=str(config.get("azure_voice", "")),
            )
        self.sapi.rate = max(-10, min(10, int(config.get("rate", -1))))
        return self.sapi.speak(text, locale)

    def stop(self) -> None:
        self.sapi.stop()
        self.azure.stop()

    def close(self) -> None:
        self.sapi.close()
        self.azure.close()
