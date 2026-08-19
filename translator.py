"""Translation module — supports text and image translation via OpenAI-compatible APIs."""

import json
import logging
from typing import Optional, Dict, Any, List, Generator
import requests
from PIL import Image

from config import (
    DEFAULT_SYSTEM_PROMPT_TEXT,
    DEFAULT_SYSTEM_PROMPT_IMAGE,
    DEFAULT_SYSTEM_PROMPT_TEXT_IMAGE,
)

logger = logging.getLogger("translator")


class TranslationError(Exception):
    pass


# Module-level session for HTTP connection pooling.
# Reusing the same Session across translations avoids repeated TLS
# handshakes, cutting ~200-400 ms off each subsequent request.
_session: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    """Return the shared requests.Session (created lazily on first use)."""
    global _session
    if _session is None:
        _session = requests.Session()
        # Pre-configure adapter limits for better connection reuse
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=4,
            pool_maxsize=4,
        )
        _session.mount("https://", adapter)
        _session.mount("http://", adapter)
    return _session


class Translator:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.1,
        timeout: int = 60,
        api_options: Optional[Dict[str, Any]] = None,
        system_prompts: Optional[Dict[str, str]] = None,
    ):
        self.base_url: str = base_url.rstrip('/')
        self.api_key: str = api_key
        self.model: str = model
        self.temperature: float = temperature
        self.timeout: int = timeout
        self.api_options: Dict[str, Any] = api_options or {}
        self.system_prompts: Dict[str, str] = system_prompts or {}

    # Fallback prompts used when no custom prompt is configured.
    # Imported from config.py to avoid duplicating the default strings.
    _DEFAULT_PROMPTS: Dict[str, str] = {
        "system_prompt_text": DEFAULT_SYSTEM_PROMPT_TEXT,
        "system_prompt_image": DEFAULT_SYSTEM_PROMPT_IMAGE,
        "system_prompt_text_image": DEFAULT_SYSTEM_PROMPT_TEXT_IMAGE,
    }

    def get_system_prompt(self, prompt_key: str) -> str:
        """Get system prompt by key, fallback to built-in defaults."""
        return self.system_prompts.get(prompt_key) or self._DEFAULT_PROMPTS.get(prompt_key, "")

    def _convert_to_longcat_format(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert standard OpenAI multimodal format to LongCat-specific format.

        LongCat expects 'input_image' type instead of 'image_url', and
        the data as a direct string rather than a URL wrapper.
        """
        converted = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if isinstance(content, list):
                new_content = []
                for item in content:
                    if item.get("type") == "image_url":
                        # Convert OpenAI image_url format to LongCat input_image format
                        url = item.get("image_url", {}).get("url", "")
                        # Strip data URI prefix if present, keep only base64 data
                        if url.startswith("data:image/"):
                            url = url.split(",", 1)[1] if "," in url else url
                        new_content.append({
                            "type": "input_image",
                            "input_image": {
                                "type": "base64",
                                "data": url,
                            },
                        })
                    else:
                        new_content.append(item)
                converted.append({"role": role, "content": new_content})
            else:
                converted.append({
                    "role": role,
                    "content": [{"type": "text", "text": content}]
                })
        return converted

    def _build_payload(self, messages: List[Dict[str, Any]], stream: bool) -> Dict[str, Any]:
        if "longcat" in self.base_url.lower():
            messages = self._convert_to_longcat_format(messages)

        # 智谱 GLM API 对 system 消息兼容性较差，将 system 合并到 user 消息中
        if "bigmodel" in self.base_url.lower() or "glm" in self.base_url.lower():
            messages = self._merge_system_to_user(messages)

        temperature = self.temperature
        # 智谱 GLM API 限制 temperature 最多 2 位小数
        if "bigmodel" in self.base_url.lower() or "glm" in self.base_url.lower():
            temperature = round(temperature, 2)

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }

        for key in (
            "sessionId", "session_id", "topP", "top_p", "topK", "top_k",
            "textRepetitionPenalty", "audioRepetitionPenalty",
            "inferenceCount", "output_modalities"
        ):
            if key in self.api_options:
                payload[key] = self.api_options[key]

        for k, v in self.api_options.items():
            if k not in payload:
                payload[k] = v

        return payload

    def _merge_system_to_user(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """将 system 消息合并到 user 消息中，提高与智谱 GLM API 的兼容性。"""
        system_content = []
        other_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                if content:
                    system_content.append(content)
            else:
                other_messages.append(msg)

        if system_content and other_messages:
            # 将 system 内容前置到第一个 user 消息中
            combined_system = "\n\n".join(system_content)
            for i, msg in enumerate(other_messages):
                if msg.get("role") == "user":
                    user_content = msg.get("content", "")
                    other_messages[i] = {
                        "role": "user",
                        "content": f"{combined_system}\n\n---\n\n{user_content}"
                    }
                    break
        elif system_content and not other_messages:
            # 只有 system 消息时，转为 user 消息
            combined_system = "\n\n".join(system_content)
            other_messages = [{"role": "user", "content": combined_system}]

        return other_messages

    def _request_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

    def _translate_request_error(self, resp, exc: Exception) -> TranslationError:
        """Convert a requests exception into a user-friendly TranslationError.

        Shared by ``_make_request`` and ``_make_stream_request`` so that
        both code paths produce identical error messages.
        """
        if isinstance(exc, requests.exceptions.Timeout):
            return TranslationError("请求超时。请检查网络或增加超时时间。")
        if isinstance(exc, requests.exceptions.ConnectionError):
            return TranslationError("连接错误。请检查网络和 API 地址。")
        if isinstance(exc, requests.exceptions.HTTPError):
            status = getattr(resp, "status_code", None)
            # 尝试获取 API 返回的错误详情
            detail = ""
            try:
                if resp is not None:
                    error_json = resp.json()
                    detail = error_json.get("error", {}).get("message", "") or error_json.get("message", "") or str(error_json)
            except Exception:
                try:
                    if resp is not None:
                        detail = resp.text[:500]
                except Exception:
                    pass
            if status == 401:
                return TranslationError("认证失败，请检查 API Key。")
            if status == 429:
                return TranslationError("Rate limit，稍后重试。")
            if detail:
                return TranslationError(f"HTTP 错误 {status}: {detail}")
            return TranslationError(f"HTTP 错误 {status}: {exc}")
        return TranslationError(f"翻译失败: {exc}")

    def _make_request(self, messages: List[Dict[str, Any]]) -> str:
        headers = self._request_headers()
        payload = self._build_payload(messages, stream=False)

        # 记录请求信息用于调试
        logger.debug("API Request: model=%s, messages=%s", payload.get("model"), json.dumps(messages, ensure_ascii=False)[:500])

        resp = None
        try:
            resp = _get_session().post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout
            )
            resp.raise_for_status()
            result = resp.json()

            if isinstance(result, dict):
                choices = result.get("choices") or []
                if choices:
                    choice = choices[0]
                    if isinstance(choice, dict):
                        msg = choice.get("message")
                        if isinstance(msg, dict) and msg.get("content"):
                            return msg["content"]
                        if choice.get("content"):
                            return choice["content"]
                        delta = choice.get("delta")
                        if isinstance(delta, dict) and delta.get("content"):
                            return delta["content"]

                if result.get("content"):
                    return result["content"]
                if result.get("error"):
                    raise TranslationError(f"API Error: {result['error']}")

            raise TranslationError("Unexpected API response format")

        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.HTTPError) as e:
            raise self._translate_request_error(resp, e)
        except json.JSONDecodeError:
            raise TranslationError("无法解析 API 返回（非 JSON）。")
        except TranslationError:
            raise
        except Exception as e:
            raise TranslationError(f"翻译失败: {e}")

    def _make_stream_request(self, messages: List[Dict[str, Any]]) -> Generator[str, None, None]:
        """Stream translation result — yields content chunks as they arrive."""
        headers = self._request_headers()
        payload = self._build_payload(messages, stream=True)

        resp = None
        try:
            resp = _get_session().post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout,
                stream=True,
            )
            resp.raise_for_status()

            for line in resp.iter_lines():
                if not line:
                    continue
                line_str = line.decode("utf-8")
                if line_str.startswith("data: "):
                    data_str = line_str[6:]
                    if data_str.strip() == "[DONE]":
                        return
                    try:
                        data = json.loads(data_str)
                        choices = data.get("choices") or []
                        if choices:
                            choice = choices[0]
                            if isinstance(choice, dict):
                                delta = choice.get("delta")
                                if isinstance(delta, dict):
                                    content = delta.get("content")
                                    if content:
                                        yield content
                                # Some APIs put content at choice level
                                elif choice.get("content"):
                                    yield choice["content"]
                    except json.JSONDecodeError:
                        continue

        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.HTTPError) as e:
            raise self._translate_request_error(resp, e)
        except TranslationError:
            raise
        except Exception as e:
            raise TranslationError(f"翻译失败: {e}")

    def translate_text(self, text: str) -> str:
        if not text or not text.strip():
            raise TranslationError("请输入要翻译的文本。")
        messages = [
            {"role": "system", "content": self.get_system_prompt("system_prompt_text")},
            {"role": "user", "content": text}
        ]
        return self._make_request(messages)

    def translate_image(self, image: Image.Image, additional_text: Optional[str] = None) -> str:
        from utils.image_utils import build_image_content
        user_content = build_image_content(image, additional_text)
        messages = [
            {"role": "system", "content": self.get_system_prompt("system_prompt_image")},
            {"role": "user", "content": user_content}
        ]
        return self._make_request(messages)

    def translate_text_with_image(self, text: str, image: Image.Image) -> str:
        from utils.image_utils import build_image_content
        user_content = build_image_content(image, text)
        messages = [
            {"role": "system", "content": self.get_system_prompt("system_prompt_text_image")},
            {"role": "user", "content": user_content}
        ]
        return self._make_request(messages)

    def test_connection(self) -> str:
        """Test API connectivity by sending a minimal request. Returns model info or raises TranslationError."""
        messages = [
            {"role": "user", "content": "Hello"},
        ]
        return self._make_request(messages)
