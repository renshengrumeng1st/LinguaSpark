"""
Settings dialog for translation assistant.
Allows configuration of API provider, base_url, api_key, model, hotkey, and system prompts.
"""

import logging
import threading
import customtkinter as ctk
from typing import Callable, Optional
from config import ConfigManager, HOTKEY_MODIFIERS, HOTKEY_KEYS, CONFIGURABLE_SHORTCUTS
from utils.hotkey import validate_hotkey_string
from ui.tooltips import add_tooltip

logger = logging.getLogger("settings")

# Common OpenAI-compatible providers — selecting one auto-fills the base URL
# and a suggested model so first-time users only need to paste their API key.
PROVIDER_PRESETS = {
    "自定义 / 手动填写": None,
    "DeepSeek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "OpenAI": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    "通义千问 (Qwen)": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-turbo"},
    "智谱 GLM": {"base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-flash"},
    "腾讯混元": {"base_url": "https://api.hunyuan.cloud.tencent.com/v1", "model": "hunyuan-turbo"},
    "Kimi (Moonshot)": {"base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
    "硅基流动 (SiliconFlow)": {"base_url": "https://api.siliconflow.cn/v1", "model": "Qwen/Qwen2.5-7B-Instruct"},
}


class SettingsDialog(ctk.CTkToplevel):
    """Settings dialog window with tabbed layout."""

    def __init__(
        self,
        parent: ctk.CTk,
        config_manager: ConfigManager,
        on_save: Optional[Callable[[], None]] = None,
        on_close: Optional[Callable[[], None]] = None,
        hotkey_manager=None,
        on_models_changed: Optional[Callable[[], None]] = None,
    ):
        super().__init__(parent)

        self.config_manager = config_manager
        self.on_save_callback = on_save
        self.on_close_callback = on_close
        self.on_models_changed = on_models_changed
        self.hotkey_manager = hotkey_manager

        # Save original theme so we can restore on cancel
        self._original_theme: str = config_manager.get("theme", "System")

        # Window configuration
        self.title("设置 - 翻译助手")
        self.geometry("520x720")
        self.resizable(False, False)

        # Make dialog modal
        self.transient(parent)
        self.grab_set()

        # Ensure closing via the title-bar X also runs the cancel/cleanup path
        # (so on_close fires and the main-window dropdown resyncs).
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # Center the dialog
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (520 // 2)
        y = (self.winfo_screenheight() // 2) - (720 // 2)
        self.geometry(f"520x720+{x}+{y}")

        # Build UI
        self._create_widgets()
        self._load_config()

        # Focus on first input
        self.after(100, self._focus_first)

    def _create_widgets(self) -> None:
        """Create tabbed dialog widgets."""
        # Main container
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.pack(fill="both", expand=True, padx=15, pady=15)

        # Tab view
        self.tabview = ctk.CTkTabview(self.main_frame, width=480)
        self.tabview.pack(fill="both", expand=True, pady=(0, 10))

        self.tab_api = self.tabview.add("API 设置")
        self.tab_hotkey = self.tabview.add("快捷键")
        self.tab_prompts = self.tabview.add("提示词")

        # Build each tab
        self._create_api_tab()
        self._create_hotkey_tab()
        self._create_prompts_tab()

        # Bottom buttons
        self.button_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.button_frame.pack(fill="x", pady=(5, 0))

        self.save_btn = ctk.CTkButton(
            self.button_frame,
            text="保存",
            command=self._on_save,
            width=100,
        )
        self.save_btn.pack(side="right", padx=(10, 0))

        self.cancel_btn = ctk.CTkButton(
            self.button_frame,
            text="取消",
            command=self._on_cancel,
            width=100,
            fg_color="gray",
        )
        self.cancel_btn.pack(side="right")

        # Status label
        self.status_label = ctk.CTkLabel(
            self.main_frame,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="red",
        )
        self.status_label.pack(pady=(5, 0))

    def _create_api_tab(self) -> None:
        """Build the API configuration tab."""
        parent = self.tab_api

        # ── Provider preset selector ────────────────────
        self.provider_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.provider_frame.pack(fill="x", pady=(5, 0), padx=10)

        self.provider_label = ctk.CTkLabel(
            self.provider_frame, text="服务商:", font=ctk.CTkFont(size=12), width=100,
        )
        self.provider_label.pack(side="left")

        self.provider_var = ctk.StringVar(value="自定义 / 手动填写")
        self.provider_combo = ctk.CTkComboBox(
            self.provider_frame,
            values=list(PROVIDER_PRESETS.keys()),
            variable=self.provider_var,
            width=300,
            command=self._on_provider_selected,
        )
        self.provider_combo.pack(side="left", padx=(10, 0))
        add_tooltip(self.provider_combo, "选择服务商可自动填好接口地址和推荐模型")

        # Base URL input
        self.url_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.url_frame.pack(fill="x", pady=5, padx=10)

        self.url_label = ctk.CTkLabel(
            self.url_frame, text="Base URL:",
            font=ctk.CTkFont(size=12), width=100,
        )
        self.url_label.pack(side="left")

        self.url_entry = ctk.CTkEntry(
            self.url_frame,
            placeholder_text="https://api.example.com/v1",
            width=300,
        )
        self.url_entry.pack(side="left", padx=(10, 0))

        # API Key input
        self.key_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.key_frame.pack(fill="x", pady=5, padx=10)

        self.key_label = ctk.CTkLabel(
            self.key_frame, text="API Key:",
            font=ctk.CTkFont(size=12), width=100,
        )
        self.key_label.pack(side="left")

        self.key_entry = ctk.CTkEntry(
            self.key_frame, placeholder_text="sk-...", show="*", width=300,
        )
        self.key_entry.pack(side="left", padx=(10, 0))

        self.show_key_btn = ctk.CTkButton(
            self.key_frame, text="显示", width=50,
            command=self._toggle_key_visibility,
        )
        self.show_key_btn.pack(side="left", padx=(5, 0))

        # Test connection button
        self.test_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.test_frame.pack(fill="x", pady=8, padx=10)

        self.test_btn = ctk.CTkButton(
            self.test_frame,
            text="🔌 测试连接",
            fg_color="green",
            hover_color="darkgreen",
            command=self._test_connection,
        )
        self.test_btn.pack(side="left", padx=(10, 0))

        self.test_result_label = ctk.CTkLabel(
            self.test_frame, text="", font=ctk.CTkFont(size=11),
        )
        self.test_result_label.pack(side="left", padx=(10, 0))

        # Model name input + add button
        self.model_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.model_frame.pack(fill="x", pady=5, padx=10)

        self.model_label = ctk.CTkLabel(
            self.model_frame, text="模型名:",
            font=ctk.CTkFont(size=12), width=100,
        )
        self.model_label.pack(side="left")

        self.model_var = ctk.StringVar()
        self.model_entry = ctk.CTkEntry(
            self.model_frame, placeholder_text="例如 gpt-4o-mini",
            textvariable=self.model_var, width=210,
        )
        self.model_entry.pack(side="left", padx=(10, 0))
        self.model_entry.bind("<Return>", lambda _=None: self._add_model())

        self.add_model_btn = ctk.CTkButton(
            self.model_frame, text="➕ 添加", width=80,
            command=self._add_model,
        )
        self.add_model_btn.pack(side="left", padx=(5, 0))

        # Scrollable list of added models
        self.model_list_frame = ctk.CTkScrollableFrame(
            parent, label_text="已添加模型（翻译页下拉框可选）", width=440, height=150,
        )
        self.model_list_frame.pack(fill="x", padx=10, pady=(5, 2))

        # Status label for add/remove feedback
        self.model_status_label = ctk.CTkLabel(
            parent, text="", font=ctk.CTkFont(size=11), text_color="gray",
        )
        self.model_status_label.pack(anchor="w", padx=12, pady=(0, 4))

        # Temperature slider
        self.temp_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.temp_frame.pack(fill="x", pady=8, padx=10)

        self.temp_label = ctk.CTkLabel(
            self.temp_frame, text="Temperature:",
            font=ctk.CTkFont(size=12), width=100,
        )
        self.temp_label.pack(side="left")

        self.temp_var = ctk.DoubleVar(value=0.3)
        self.temp_slider = ctk.CTkSlider(
            self.temp_frame, from_=0, to=1, number_of_steps=10,
            variable=self.temp_var, width=200,
            command=self._on_temp_change,
        )
        self.temp_slider.pack(side="left", padx=(10, 0))

        self.temp_value_label = ctk.CTkLabel(
            self.temp_frame, text="0.3",
            font=ctk.CTkFont(size=12), width=40,
        )
        self.temp_value_label.pack(side="left", padx=(10, 0))

        # Theme selection
        self.theme_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.theme_frame.pack(fill="x", pady=5, padx=10)

        self.theme_label = ctk.CTkLabel(
            self.theme_frame, text="主题:",
            font=ctk.CTkFont(size=12), width=100,
        )
        self.theme_label.pack(side="left")

        self.theme_var = ctk.StringVar(value="System")
        self.theme_combo = ctk.CTkComboBox(
            self.theme_frame,
            values=["System", "Light", "Dark"],
            variable=self.theme_var, width=150,
            command=self._on_theme_change,
        )
        self.theme_combo.pack(side="left", padx=(10, 0))

    def _on_provider_selected(self, choice: str) -> None:
        """Auto-fill base_url (and a suggested model) from the chosen preset."""
        preset = PROVIDER_PRESETS.get(choice)
        if not preset:
            return
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, preset["base_url"])
        # Pre-fill the suggested model so the user only needs to paste the key
        self.model_var.set(preset["model"])
        self.key_entry.focus_set()

    def _create_hotkey_tab(self) -> None:
        """Build the hotkey configuration tab."""
        parent = self.tab_hotkey

        info_label = ctk.CTkLabel(
            parent,
            text="全局显示/隐藏热键（点击录制）",
            font=ctk.CTkFont(size=12),
            text_color="gray",
        )
        info_label.pack(pady=(10, 8), padx=10, anchor="w")

        # 录制按钮（和其他快捷键一致）
        self.hotkey_recorder_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.hotkey_recorder_frame.pack(fill="x", pady=5, padx=10)

        current_hotkey = self.config_manager.get_hotkey()
        # 显示与录制组件一致的文本格式
        self.hotkey_recorder_btn = ctk.CTkButton(
            self.hotkey_recorder_frame,
            text=self._format_hotkey_display(current_hotkey),
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#0050a0",
            width=200,
            cursor="hand2",
            command=self._toggle_hotkey_recording,
        )
        self.hotkey_recorder_btn.pack(side="left")

        self._recording_hotkey = False
        self._current_hotkey = current_hotkey

        # 冲突提示
        self.hotkey_warning_label = ctk.CTkLabel(
            parent,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="orange",
        )
        self.hotkey_warning_label.pack(pady=(4, 0), padx=10, anchor="w")

        # Hint
        hint_label = ctk.CTkLabel(
            parent,
            text="提示: 保存后热键将立即生效。避免使用已被系统占用的热键。",
            font=ctk.CTkFont(size=10),
            text_color="gray",
        )
        hint_label.pack(pady=(8, 0), padx=10, anchor="w")

        # ── Separator ──────────────────────────────────────
        separator = ctk.CTkFrame(parent, height=2, fg_color="gray")
        separator.pack(fill="x", padx=10, pady=(15, 10))

        # ── Local shortcuts section ────────────────────────
        local_title = ctk.CTkLabel(
            parent,
            text="窗口快捷键（点击录制新快捷键）",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        local_title.pack(anchor="w", padx=10, pady=(0, 8))

        shortcuts = self.config_manager.get_all_shortcuts()
        self._shortcut_recorders: dict[str, "HotkeyRecorder"] = {}

        from ui.hotkey_recorder import HotkeyRecorder

        # Card-style layout: label on top, recorder + clear button below
        for shortcut_key, label_text in CONFIGURABLE_SHORTCUTS.items():
            card = ctk.CTkFrame(parent, fg_color="transparent")
            card.pack(fill="x", pady=4, padx=10)

            lbl = ctk.CTkLabel(
                card, text=label_text,
                font=ctk.CTkFont(size=12),
            )
            lbl.pack(anchor="w")

            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", pady=(2, 0))

            recorder = HotkeyRecorder(
                row, current=shortcuts.get(shortcut_key, ""),
                width=200,
            )
            recorder.pack(side="left", padx=(0, 8))
            self._shortcut_recorders[shortcut_key] = recorder

            # Clear button
            _make_clear = lambda rec=recorder: rec.clear()
            clear_btn = ctk.CTkButton(
                row, text="清除", width=50, height=26,
                fg_color="gray", font=ctk.CTkFont(size=10),
                command=_make_clear,
            )
            clear_btn.pack(side="left")

    def _create_prompts_tab(self) -> None:
        """Build the system prompts configuration tab."""
        parent = self.tab_prompts

        info_label = ctk.CTkLabel(
            parent,
            text="自定义系统提示词（留空则使用默认值）",
            font=ctk.CTkFont(size=12),
            text_color="gray",
        )
        info_label.pack(pady=(10, 5), padx=10, anchor="w")

        # Text prompt
        self.prompt_text_label = ctk.CTkLabel(
            parent, text="文本翻译提示词:",
            font=ctk.CTkFont(size=11),
        )
        self.prompt_text_label.pack(anchor="w", padx=10)

        self.prompt_text_box = ctk.CTkTextbox(parent, height=100, wrap="word")
        self.prompt_text_box.pack(fill="x", padx=10, pady=(2, 10))

        # Image prompt
        self.prompt_image_label = ctk.CTkLabel(
            parent, text="图片翻译提示词:",
            font=ctk.CTkFont(size=11),
        )
        self.prompt_image_label.pack(anchor="w", padx=10)

        self.prompt_image_box = ctk.CTkTextbox(parent, height=80, wrap="word")
        self.prompt_image_box.pack(fill="x", padx=10, pady=(2, 10))

        # Text+Image prompt
        self.prompt_both_label = ctk.CTkLabel(
            parent, text="文本+图片提示词:",
            font=ctk.CTkFont(size=11),
        )
        self.prompt_both_label.pack(anchor="w", padx=10)

        self.prompt_both_box = ctk.CTkTextbox(parent, height=60, wrap="word")
        self.prompt_both_box.pack(fill="x", padx=10, pady=(2, 10))

        # Reset button
        self.reset_prompts_btn = ctk.CTkButton(
            parent,
            text="恢复默认提示词",
            width=140,
            fg_color="gray",
            command=self._reset_prompts,
        )
        self.reset_prompts_btn.pack(anchor="w", padx=10, pady=(5, 0))

    def _refresh_model_list(self) -> None:
        """Rebuild the added-models list UI from config."""
        for child in list(self.model_list_frame.winfo_children()):
            child.destroy()
        entries = self.config_manager.get_custom_models()
        active = self.config_manager.get("model", "")
        if not entries:
            empty = ctk.CTkLabel(
                self.model_list_frame,
                text="（暂无模型，请在上方填写后点击添加）",
                text_color="gray", font=ctk.CTkFont(size=11),
            )
            empty.pack(pady=12)
            return
        for e in entries:
            name = e.get("model", "")
            base = e.get("base_url", "")
            is_active = (name == active)
            row = ctk.CTkFrame(self.model_list_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            mark = "✓ " if is_active else "   "
            base_short = base if len(base) <= 34 else base[:31] + "..."
            lbl = ctk.CTkLabel(
                row, text=f"{mark}{name}  ({base_short})",
                anchor="w", font=ctk.CTkFont(size=12),
                text_color=("#1f6feb" if is_active else None),
            )
            lbl.pack(side="left", fill="x", expand=True, padx=(4, 4))
            del_btn = ctk.CTkButton(
                row, text="删除", width=50, height=24,
                fg_color="gray", font=ctk.CTkFont(size=10),
                command=lambda m=name: self._remove_model(m),
            )
            del_btn.pack(side="right", padx=(4, 0))

    def _add_model(self) -> None:
        """Validate the form and add a new model entry."""
        base_url = self.url_entry.get().strip()
        api_key = self.key_entry.get().strip()
        model = self.model_var.get().strip()
        if not all([base_url, api_key, model]):
            self.model_status_label.configure(
                text="请填写完整的 Base URL、API Key 和模型名", text_color="red",
            )
            return
        if self.config_manager.add_custom_model(base_url, api_key, model):
            self.config_manager.save()
            self.model_var.set("")  # clear model name only (keep base_url/key for siblings)
            self._refresh_model_list()
            self._notify_models_changed()
            self.model_status_label.configure(
                text=f"已添加：{model}（可在翻译页下拉框选择）", text_color="green",
            )
        else:
            self.model_status_label.configure(
                text="该模型已存在", text_color="orange",
            )

    def _remove_model(self, model: str) -> None:
        """Remove a model entry and refresh UI."""
        if self.config_manager.remove_custom_model(model):
            self.config_manager.save()
            self._refresh_model_list()
            self._notify_models_changed()
            self.model_status_label.configure(
                text=f"已删除：{model}", text_color="green",
            )

    def _notify_models_changed(self) -> None:
        """Live-sync the main-window model dropdown (added/removed immediately visible)."""
        if self.on_models_changed:
            try:
                self.on_models_changed()
            except Exception as e:
                logger.debug("on_models_changed callback failed: %s", e)

    # Common system hotkeys that should be avoided
    _CONFLICT_HOTKEYS = {
        ("ctrl", "c"), ("ctrl", "v"), ("ctrl", "x"), ("ctrl", "a"),
        ("ctrl", "z"), ("ctrl", "y"), ("ctrl", "s"), ("ctrl", "n"),
        ("ctrl", "o"), ("ctrl", "p"), ("ctrl", "f"), ("ctrl", "w"),
        ("ctrl", "t"), ("ctrl", "tab"), ("alt", "f4"), ("alt", "tab"),
        ("alt", "esc"), ("alt", "space"), ("ctrl", "esc"), ("ctrl", "alt", "delete"),
        ("win", "l"), ("win", "d"), ("win", "e"), ("win", "r"),
    }

    def _format_hotkey_display(self, hotkey: str) -> str:
        """Format a hotkey string for display (e.g. 'alt+q' → 'Alt+Q')."""
        if not hotkey:
            return "点击录制"
        parts = hotkey.lower().split("+")
        return "+".join(p.capitalize() for p in parts)

    def _toggle_hotkey_recording(self) -> None:
        """Toggle hotkey recording mode."""
        if self._hotkey_recording:
            # Cancel recording
            self._hotkey_recording = False
            self.hotkey_recorder_btn.configure(
                fg_color="#0050a0",
                text=self._format_hotkey_display(self._current_hotkey),
            )
            self.hotkey_recorder_btn.unbind("<KeyPress>")
            self.hotkey_recorder_btn.unbind("<KeyRelease>")
            return

        # Start recording
        self._hotkey_recording = True
        self.hotkey_recorder_btn.configure(
            fg_color="#a05000",
            text="请按下快捷键…",
        )
        self.hotkey_recorder_btn.focus_set()
        self.hotkey_recorder_btn.bind("<KeyPress>", self._on_hotkey_press)
        self.hotkey_recorder_btn.bind("<KeyRelease>", self._on_hotkey_release)

    def _on_hotkey_press(self, event):
        """Capture key press during recording."""
        if not self._hotkey_recording:
            return

        keysym = event.keysym

        # Allow Escape to cancel recording
        if keysym == "Escape":
            self._hotkey_recording = False
            self.hotkey_recorder_btn.configure(
                fg_color="#0050a0",
                text=self._format_hotkey_display(self._current_hotkey),
            )
            self.hotkey_recorder_btn.unbind("<KeyPress>")
            self.hotkey_recorder_btn.unbind("<KeyRelease>")
            return "break"

        # Build modifier list
        mods = []
        if event.state & 0x4:  # Control
            mods.append("Ctrl")
        if event.state & 0x8:  # Alt
            mods.append("Alt")
        if event.state & 0x1:  # Shift
            mods.append("Shift")

        # The actual key
        key = keysym
        if len(key) == 1:
            key = key.upper()
        elif key.startswith("F") and key[1:].isdigit():
            pass  # F1-F12 stay as-is
        else:
            key = key.capitalize()

        if not mods:
            # No modifier, don't capture (require at least Ctrl/Alt/Shift)
            return "break"

        # Build and store
        self._current_hotkey = "+".join(mods).lower() + "+" + key.lower()

        # Update display
        self.hotkey_recorder_btn.configure(
            text=self._format_hotkey_display(self._current_hotkey),
        )

        # Check for conflicts
        conflict_key = tuple([m.lower() for m in mods] + [key.lower()])
        if conflict_key in self._CONFLICT_HOTKEYS:
            self.hotkey_warning_label.configure(
                text="⚠ 该组合可能与系统热键冲突",
            )
        else:
            self.hotkey_warning_label.configure(text="")

        # End recording
        self._hotkey_recording = False
        self.hotkey_recorder_btn.configure(fg_color="#0050a0")
        self.hotkey_recorder_btn.unbind("<KeyPress>")
        self.hotkey_recorder_btn.unbind("<KeyRelease>")
        return "break"

    def _on_hotkey_release(self, event):
        pass

    def _load_config(self) -> None:
        """Load current configuration into UI."""
        base_url = self.config_manager.get("base_url", "")
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, base_url)

        api_key = self.config_manager.get("api_key", "")
        self.key_entry.delete(0, "end")
        self.key_entry.insert(0, api_key)

        temperature = self.config_manager.get("temperature", 0.3)
        self.temp_var.set(temperature)
        self.temp_value_label.configure(text=f"{temperature:.1f}")

        theme = self.config_manager.get("theme", "System")
        self.theme_var.set(theme)

        # Load hotkey
        hotkey = self.config_manager.get("hotkey", "alt+q")
        self._current_hotkey = hotkey
        if hasattr(self, 'hotkey_recorder_btn'):
            self.hotkey_recorder_btn.configure(text=self._format_hotkey_display(hotkey))

        # Preselect the provider preset if the current base_url matches one
        saved_url = self.config_manager.get("base_url", "").strip().rstrip("/")
        matched = "自定义 / 手动填写"
        for name, preset in PROVIDER_PRESETS.items():
            if preset and preset["base_url"].rstrip("/") == saved_url:
                matched = name
                break
        self.provider_var.set(matched)

        # Load prompts
        from config import DEFAULT_SYSTEM_PROMPT_TEXT, DEFAULT_SYSTEM_PROMPT_IMAGE, DEFAULT_SYSTEM_PROMPT_TEXT_IMAGE
        self.prompt_text_box.delete("1.0", "end")
        self.prompt_text_box.insert("1.0", self.config_manager.get("system_prompt_text", DEFAULT_SYSTEM_PROMPT_TEXT))
        self.prompt_image_box.delete("1.0", "end")
        self.prompt_image_box.insert("1.0", self.config_manager.get("system_prompt_image", DEFAULT_SYSTEM_PROMPT_IMAGE))
        self.prompt_both_box.delete("1.0", "end")
        self.prompt_both_box.insert("1.0", self.config_manager.get("system_prompt_text_image", DEFAULT_SYSTEM_PROMPT_TEXT_IMAGE))

        # Populate the added-models list (active config's base_url/api_key
        # are pre-filled above as a convenience for adding sibling models
        # or testing the active connection).
        self._refresh_model_list()

    def _reset_prompts(self) -> None:
        """Reset prompts to defaults."""
        from config import DEFAULT_SYSTEM_PROMPT_TEXT, DEFAULT_SYSTEM_PROMPT_IMAGE, DEFAULT_SYSTEM_PROMPT_TEXT_IMAGE
        self.prompt_text_box.delete("1.0", "end")
        self.prompt_text_box.insert("1.0", DEFAULT_SYSTEM_PROMPT_TEXT)
        self.prompt_image_box.delete("1.0", "end")
        self.prompt_image_box.insert("1.0", DEFAULT_SYSTEM_PROMPT_IMAGE)
        self.prompt_both_box.delete("1.0", "end")
        self.prompt_both_box.insert("1.0", DEFAULT_SYSTEM_PROMPT_TEXT_IMAGE)

    def _on_temp_change(self, value: float) -> None:
        """Handle temperature slider change."""
        self.temp_value_label.configure(text=f"{value:.1f}")

    def _on_theme_change(self, choice=None) -> None:
        """Handle theme change — apply immediately without saving.

        Uses after() to defer the actual theme switch so it runs outside
        the combobox event handler, preventing event-loop conflicts with
        the parent window's <Configure> binding.
        """
        theme = choice if isinstance(choice, str) else self.theme_var.get()
        # Defer to break out of the combobox callback event loop
        self.after(30, lambda t=theme: self._apply_theme_change(t))

    @staticmethod
    def _apply_theme_change(theme: str) -> None:
        """Actually switch the appearance mode."""
        if theme == "Light":
            ctk.set_appearance_mode("light")
        elif theme == "Dark":
            ctk.set_appearance_mode("dark")
        else:
            ctk.set_appearance_mode("system")

    def _restore_theme(self) -> None:
        """Restore the theme that was active before the dialog opened."""
        current = self.theme_var.get()
        if current != self._original_theme:
            self._apply_theme_change(self._original_theme)

    def _toggle_key_visibility(self) -> None:
        """Toggle API key visibility."""
        current_show = self.key_entry.cget("show")
        if current_show == "*":
            self.key_entry.configure(show="")
            self.show_key_btn.configure(text="隐藏")
        else:
            self.key_entry.configure(show="*")
            self.show_key_btn.configure(text="显示")

    def _test_connection(self) -> None:
        """Test the currently active model's API connection in a background thread."""
        base_url = self.config_manager.get("base_url", "").strip()
        api_key = self.config_manager.get("api_key", "").strip()
        model = self.config_manager.get("model", "").strip()

        if not all([base_url, api_key, model]):
            self.test_result_label.configure(text="请先添加并选择一个模型", text_color="red")
            return

        self.test_btn.configure(state="disabled", text="测试中...")
        self.test_result_label.configure(text="正在连接...", text_color="gray")

        def _do_test():
            try:
                from translator import Translator
                t = Translator(
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    timeout=15,
                )
                result = t.test_connection()
                self.after(0, lambda: self.test_result_label.configure(
                    text=f"连接成功! 回复: {result[:50]}...",
                    text_color="green",
                ))
            except Exception as e:
                self.after(0, lambda: self.test_result_label.configure(
                    text=f"连接失败: {e}",
                    text_color="red",
                ))
            finally:
                self.after(0, lambda: self.test_btn.configure(state="normal", text="🔌 测试连接"))

        thread = threading.Thread(target=_do_test, daemon=True)
        thread.start()

    def _build_hotkey_string(self) -> str:
        """Return the recorded hotkey string."""
        return getattr(self, '_current_hotkey', 'alt+q')

    def _validate(self) -> bool:
        """Validate input fields. Base URL/Key/Model are managed via the
        add-model flow, so only the hotkey is validated here."""
        # Validate hotkey
        hotkey = self._build_hotkey_string()
        if not validate_hotkey_string(hotkey):
            self.status_label.configure(text=f"无效的热键组合: {hotkey}")
            return False

        return True

    def _on_save(self) -> None:
        """Handle save button click.

        Models (base_url/api_key/model) are persisted immediately on
        add/remove/select, so here we only save the remaining settings.
        """
        if not self._validate():
            return

        # Save configuration (model endpoint is managed via add/remove)
        self.config_manager.set("temperature", self.temp_var.get())
        self.config_manager.set("theme", self.theme_var.get())
        self.config_manager.set("hotkey", self._build_hotkey_string())

        # Save prompts
        self.config_manager.set("system_prompt_text", self.prompt_text_box.get("1.0", "end-1c").strip())
        self.config_manager.set("system_prompt_image", self.prompt_image_box.get("1.0", "end-1c").strip())
        self.config_manager.set("system_prompt_text_image", self.prompt_both_box.get("1.0", "end-1c").strip())

        # Save configurable shortcuts
        for key, recorder in self._shortcut_recorders.items():
            self.config_manager.set_shortcut(key, recorder.get_binding())

        if self.config_manager.save():
            self.status_label.configure(text="保存成功！", text_color="green")
            self.after(500, self._close_dialog)
            if self.on_save_callback:
                self.on_save_callback()
        else:
            self.status_label.configure(text="保存失败，请重试", text_color="red")

    def _on_cancel(self) -> None:
        """Handle cancel button click — restore original theme."""
        self._restore_theme()
        self._close_dialog()

    def _close_dialog(self) -> None:
        """Close the dialog."""
        self.grab_release()
        self.destroy()
        if self.on_close_callback:
            try:
                self.on_close_callback()
            except Exception as e:
                logger.debug("on_close callback failed: %s", e)

    def _focus_first(self) -> None:
        """Focus on first input field."""
        self.url_entry.focus_set()


def show_settings_dialog(
    parent: ctk.CTk,
    config_manager: ConfigManager,
    on_save: Optional[Callable[[], None]] = None,
    on_close: Optional[Callable[[], None]] = None,
    hotkey_manager=None,
    on_models_changed: Optional[Callable[[], None]] = None,
) -> SettingsDialog:
    """
    Show settings dialog.

    Args:
        parent: Parent window
        config_manager: Configuration manager instance
        on_save: Optional callback after successful save
        on_close: Optional callback after dialog is closed/destroyed
        hotkey_manager: Optional hotkey manager for re-registration
        on_models_changed: Optional callback after a model is added/removed

    Returns:
        SettingsDialog instance
    """
    dialog = SettingsDialog(
        parent, config_manager,
        on_save=on_save, on_close=on_close, hotkey_manager=hotkey_manager,
        on_models_changed=on_models_changed,
    )
    dialog.focus_set()
    return dialog
