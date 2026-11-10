"""OpenAI-compatible provider presets and endpoint-specific capabilities.

Only send vendor extensions to the vendor's own host. A model name alone does
not establish what a proxy supports. Model IDs are fetched, never hardcoded.
"""

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True)
class ProviderPreset:
    name: str
    base_url: str


PROVIDER_PRESETS = (
    ProviderPreset("LongCat", "https://api.longcat.chat/openai/v1"),
    ProviderPreset("DeepSeek", "https://api.deepseek.com/v1"),
    ProviderPreset("通义千问 / 阿里云百炼", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    ProviderPreset("智谱 GLM", "https://open.bigmodel.cn/api/paas/v4"),
    ProviderPreset("月之暗面 / Kimi", "https://api.moonshot.cn/v1"),
    ProviderPreset("硅基流动", "https://api.siliconflow.cn/v1"),
    ProviderPreset("豆包 / 火山方舟", "https://ark.cn-beijing.volces.com/api/v3"),
    ProviderPreset("OpenAI", "https://api.openai.com/v1"),
    ProviderPreset("Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai"),
    ProviderPreset("OpenRouter", "https://openrouter.ai/api/v1"),
    ProviderPreset("Groq", "https://api.groq.com/openai/v1"),
    ProviderPreset("Mistral", "https://api.mistral.ai/v1"),
    ProviderPreset("xAI / Grok", "https://api.x.ai/v1"),
)


def normalize_base_url(base_url: str) -> str:
    parts = urlsplit(base_url.strip().rstrip("/"))
    path = parts.path.rstrip("/")
    # Accept an accidentally pasted completion URL without duplicating it.
    if path.endswith("/chat/completions"):
        path = path[:-len("/chat/completions")]
    # Older LongCat configurations omit the protocol's v1 segment.
    if parts.hostname == "api.longcat.chat" and path in ("", "/openai"):
        path = "/openai/v1"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def api_endpoint(base_url: str, resource: str) -> str:
    return normalize_base_url(base_url) + "/" + resource


def provider_options(base_url: str, model: str, *, json_output: bool = False) -> dict:
    host = urlsplit(base_url).hostname
    options: dict = {}
    if host in {"api.longcat.chat", "api.deepseek.com", "open.bigmodel.cn", "api.z.ai"}:
        options["thinking"] = {"type": "disabled"}
    elif host in {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com", "api.siliconflow.cn", "api.siliconflow.com"}:
        options["enable_thinking"] = False
    elif host in {"api.moonshot.cn", "api.moonshot.ai"} and model.casefold().startswith("kimi-k2.5"):
        options["thinking"] = {"type": "disabled"}
    elif host == "ark.cn-beijing.volces.com" and model.casefold().startswith("doubao"):
        options["thinking"] = {"type": "disabled"}
    if host in {"open.bigmodel.cn", "api.z.ai"}:
        options["do_sample"] = False
    if json_output and host in {"api.longcat.chat", "api.deepseek.com", "open.bigmodel.cn", "api.z.ai"}:
        options["response_format"] = {"type": "json_object"}
    return options
