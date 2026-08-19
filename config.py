"""Configuration management — reads/writes config.json with API provider presets."""

import json
import logging
import os
import copy
from typing import Dict, Any

logger = logging.getLogger("config")

# Model metadata: description, recommended use-case, and approximate cost level
# cost_level: 🟢 cheap | 🟡 moderate | 🔴 expensive
MODEL_INFO: Dict[str, Dict[str, str]] = {
    "gpt-4o-mini": {
        "desc": "日常对话 · 速度快",
        "cost": "🟢",
        "recommended": "true",
    },
    "gpt-4o": {
        "desc": "高质量翻译 · 图片理解强",
        "cost": "🔴",
        "recommended": "false",
    },
    "deepseek-chat": {
        "desc": "长文本 · 性价比高",
        "cost": "🟢",
        "recommended": "true",
    },
    "deepseek-reasoner": {
        "desc": "复杂推理 · 深度翻译",
        "cost": "🟡",
        "recommended": "false",
    },
    "Qwen/Qwen2.5-VL-72B-Instruct": {
        "desc": "图片翻译 · 中文优化",
        "cost": "🟡",
        "recommended": "false",
    },
    "Qwen/Qwen2.5-VL-32B-Instruct": {
        "desc": "图片翻译 · 速度较快",
        "cost": "🟢",
        "recommended": "false",
    },
    "deepseek-ai/deepseek-vl2": {
        "desc": "图片翻译 · 多模态",
        "cost": "🟡",
        "recommended": "false",
    },
    "Pro/Qwen/Qwen2-VL-7B-Instruct": {
        "desc": "轻量图片翻译",
        "cost": "🟢",
        "recommended": "false",
    },
    "deepseek-v4-flash": {
        "desc": "极速响应 · 日常翻译",
        "cost": "🟢",
        "recommended": "true",
    },
}

# Available modifier choices for hotkey configuration
HOTKEY_MODIFIERS = ["Alt", "Ctrl", "Ctrl+Alt", "Ctrl+Shift", "Shift+Alt"]
HOTKEY_KEYS = [
    "Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P",
    "A", "S", "D", "F", "G", "H", "J", "K", "L",
    "Z", "X", "C", "V", "B", "N", "M",
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "0",
    "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
    "Space", "Tab", "Enter",
]

DEFAULT_SYSTEM_PROMPT_TEXT = (
    "你是专业中英文互译助手。如果输入是句子，请根据可能的语境进行翻译，"
    "要求务必符合原意同时尽可能地表述自然流畅；如果输入是单个英文单词，"
    "则给出其中文含义、词性、音标、1~2个常用搭配和例句。当输入既有中文又有英文时，"
    "请翻译英文部分并保持中文不变。直接对用户输入进行翻译，无需额外说明。"
)

DEFAULT_SYSTEM_PROMPT_IMAGE = (
    "你是专业中英文互译助手，具备图像识别能力。请识别图片中的文字并翻译为中文，"
    "如果图片中没有文字请描述图片内容。要求务必符合原意同时尽可能地表述自然流畅。"
    "当图片中既有中文又有英文时，请翻译英文部分并保持中文不变。"
)

DEFAULT_SYSTEM_PROMPT_TEXT_IMAGE = (
    "你是专业翻译助手，具备图像识别能力。请结合用户提供的文本和图片内容进行翻译，"
    "要求务必符合原意同时尽可能地表述自然流畅。"
)

DEFAULT_CONFIG: Dict[str, Any] = {
    "base_url": "",
    "api_key": "",
    "model": "",
    "custom_models": [],
    "temperature": 0.3,
    "theme": "System",
    "hotkey": "alt+q",
    "window_x": -1,
    "window_y": -1,
    "window_width": 600,
    "window_height": 500,
    "compact_mode": False,
    "system_prompt_text": DEFAULT_SYSTEM_PROMPT_TEXT,
    "system_prompt_image": DEFAULT_SYSTEM_PROMPT_IMAGE,
    "system_prompt_text_image": DEFAULT_SYSTEM_PROMPT_TEXT_IMAGE,
    # Local window shortcuts (changeable in settings)
    "shortcut_translate": "<Control-Return>",
    "shortcut_clear": "<Control-l>",
    "shortcut_select": "<Alt-W>",
    "shortcut_history": "<Control-Shift-H>",
    "shortcut_stats": "<Control-Shift-S>",
    "shortcut_mode": "<Control-Shift-M>",
}

# 可配置的快捷键列表及其显示名称（用于设置界面）
CONFIGURABLE_SHORTCUTS: Dict[str, str] = {
    "shortcut_translate": "翻译",
    "shortcut_clear": "清空",
    "shortcut_select": "划线翻译",
    "shortcut_history": "翻译历史",
    "shortcut_stats": "使用统计",
    "shortcut_mode": "切换精简模式",
}

CONFIG_FILE = "config.json"


class ConfigManager:
    """Manages application configuration."""

    def __init__(self, config_file: str = CONFIG_FILE):
        self.config_file = config_file
        self._config: Dict[str, Any] = {}
        self.load()

    def load(self) -> Dict[str, Any]:
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                self._config = {**copy.deepcopy(DEFAULT_CONFIG), **loaded}
            except Exception as e:
                logger.error("Error loading config: %s", e)
                self._config = copy.deepcopy(DEFAULT_CONFIG)
        else:
            self._config = copy.deepcopy(DEFAULT_CONFIG)
        self._normalize_custom_models()
        return self._config

    def _normalize_custom_models(self) -> None:
        """Ensure custom_models entries are dicts and seed from flat config.

        Migrates legacy string entries (which shared the flat base_url /
        api_key) to ``{base_url, api_key, model}`` dicts, and — when the
        list is empty but a complete flat API config exists — seeds one
        entry from it so the active model is manageable from the UI.
        """
        raw = self._config.get("custom_models", [])
        if not isinstance(raw, list):
            self._config["custom_models"] = []
            raw = []
        flat_base = self._config.get("base_url", "")
        flat_key = self._config.get("api_key", "")
        flat_model = self._config.get("model", "")
        normalized: list[Dict[str, str]] = []
        for entry in raw:
            if isinstance(entry, str) and entry:
                normalized.append({"model": entry, "base_url": flat_base, "api_key": flat_key})
            elif isinstance(entry, dict) and entry.get("model"):
                normalized.append({
                    "model": entry["model"],
                    "base_url": entry.get("base_url", flat_base),
                    "api_key": entry.get("api_key", flat_key),
                })
        if not normalized and flat_model and flat_base and flat_key:
            normalized.append({"model": flat_model, "base_url": flat_base, "api_key": flat_key})
        # Also ensure the active flat model is itself an entry (e.g. legacy
        # configs whose active model was never added to the list), so it is
        # manageable from the UI. No-op once it has been persisted.
        elif flat_model and flat_base and flat_key and not any(
            e["model"] == flat_model for e in normalized
        ):
            normalized.append({"model": flat_model, "base_url": flat_base, "api_key": flat_key})
        self._config["custom_models"] = normalized

    def save(self) -> bool:
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error("Error saving config: %s", e)
            return False

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._config[key] = value

    def update(self, updates: Dict[str, Any]) -> None:
        self._config.update(updates)

    def is_configured(self) -> bool:
        return bool(
            self._config.get("base_url") and
            self._config.get("api_key") and
            self._config.get("model")
        )

    def get_all_shortcuts(self) -> Dict[str, str]:
        """Return all configurable shortcut bindings."""
        return {k: self._config.get(k, DEFAULT_CONFIG[k]) for k in CONFIGURABLE_SHORTCUTS}

    def set_shortcut(self, key: str, binding: str) -> None:
        """Set and persist one shortcut binding."""
        if key in CONFIGURABLE_SHORTCUTS:
            self._config[key] = binding

    def get_api_config(self) -> Dict[str, Any]:
        return {
            "base_url": self._config.get("base_url", ""),
            "api_key": self._config.get("api_key", ""),
            "model": self._config.get("model", ""),
            "temperature": self._config.get("temperature", 0.3),
            "system_prompt_text": self._config.get("system_prompt_text", DEFAULT_SYSTEM_PROMPT_TEXT),
            "system_prompt_image": self._config.get("system_prompt_image", DEFAULT_SYSTEM_PROMPT_IMAGE),
            "system_prompt_text_image": self._config.get("system_prompt_text_image", DEFAULT_SYSTEM_PROMPT_TEXT_IMAGE),
        }

    def get_hotkey(self) -> str:
        """Return the configured hotkey string."""
        return self._config.get("hotkey", "alt+q")

    def get_window_geometry(self) -> dict:
        """Return saved window position/size, or None if not saved."""
        x = self._config.get("window_x", -1)
        y = self._config.get("window_y", -1)
        w = self._config.get("window_width", 600)
        h = self._config.get("window_height", 500)
        if x < 0 or y < 0:
            return None
        return {"x": x, "y": y, "width": w, "height": h}

    def save_window_geometry(self, x: int, y: int, width: int, height: int) -> None:
        """Save window position/size to config."""
        self._config["window_x"] = x
        self._config["window_y"] = y
        self._config["window_width"] = width
        self._config["window_height"] = height
        self.save()

    def get_models_for_provider(self) -> list[str]:
        """Return the selectable model names (from user-added model entries)."""
        names: list[str] = []
        for entry in self._config.get("custom_models", []):
            if isinstance(entry, dict):
                m = entry.get("model", "")
                if m and m not in names:
                    names.append(m)
        return names

    def get_custom_models(self) -> list[Dict[str, str]]:
        """Return copies of the user-added model entries."""
        return [
            {"model": e.get("model", ""), "base_url": e.get("base_url", ""), "api_key": e.get("api_key", "")}
            for e in self._config.get("custom_models", [])
            if isinstance(e, dict)
        ]

    def add_custom_model(self, base_url: str, api_key: str, model: str) -> bool:
        """Add a model entry ``{base_url, api_key, model}``.

        Returns True if added; False on empty/duplicate model name.
        When no model is currently active, the new model is activated
        (flat base_url/api_key/model synced) so translation works.
        """
        model = (model or "").strip()
        base_url = (base_url or "").strip()
        api_key = (api_key or "").strip()
        if not model:
            return False
        entries = self._config.setdefault("custom_models", [])
        if any(isinstance(e, dict) and e.get("model") == model for e in entries):
            return False
        entries.append({"base_url": base_url, "api_key": api_key, "model": model})
        if not self._config.get("model"):
            self._config["model"] = model
            self._config["base_url"] = base_url
            self._config["api_key"] = api_key
        return True

    def select_model(self, model: str) -> bool:
        """Activate a model by name: sync flat base_url/api_key/model.

        Returns True if the model was found among the entries.
        """
        model = (model or "").strip()
        for e in self._config.get("custom_models", []):
            if isinstance(e, dict) and e.get("model") == model:
                self._config["model"] = e["model"]
                self._config["base_url"] = e.get("base_url", "")
                self._config["api_key"] = e.get("api_key", "")
                return True
        return False

    def remove_custom_model(self, model: str) -> bool:
        """Remove a model entry by name. If it was active, reselect another
        entry or clear the active config."""
        model = (model or "").strip()
        entries = self._config.setdefault("custom_models", [])
        for i, e in enumerate(entries):
            if isinstance(e, dict) and e.get("model") == model:
                entries.pop(i)
                if self._config.get("model") == model:
                    if entries:
                        first = entries[0]
                        self._config["model"] = first.get("model", "")
                        self._config["base_url"] = first.get("base_url", "")
                        self._config["api_key"] = first.get("api_key", "")
                    else:
                        self._config["model"] = ""
                        self._config["base_url"] = ""
                        self._config["api_key"] = ""
                return True
        return False

    @property
    def all_config(self) -> Dict[str, Any]:
        return self._config.copy()
