"""
Main window for translation assistant.
Provides text input, image paste/drag-drop, compact mode, and translation result display.
"""

import tkinter as tk
import threading
import queue
from typing import Dict, Optional
from PIL import Image, ImageTk
import customtkinter as ctk

from config import ConfigManager
from translator import Translator, TranslationError
from ui.settings_dialog import show_settings_dialog
from ui.stats_dialog import show_stats_dialog
from ui.tooltips import add_tooltip, update_tooltip
from utils.history import HistoryManager
from utils.image_utils import build_image_content
from utils.translation_cache import TranslationCache
from utils.usage_stats import UsageStats
from utils.clipboard_text import get_clipboard_text, get_selected_text_via_copy
from utils.shortcut_format import format_binding
from utils import tts


# ── Color palette ─────────────────────────────────────────────
# Tuples are (light_mode, dark_mode) for theme-aware rendering.
ACCENT = ("#3b82f6", "#2563eb")          # primary blue — translate button
ACCENT_HOVER = ("#2563eb", "#1d4ed8")    # hover state for accent
SUCCESS = ("#22c55e", "#16a34a")         # green — cache hit, success
SUBTLE = ("#e5e7eb", "#404040")          # neutral — secondary buttons
SUBTLE_HOVER = ("#d1d5db", "#525252")    # hover for secondary
SURFACE = ("#f9fafb", "#2d2d2d")         # input/result surface bg
BORDER = ("#e5e7eb", "#3a3a3a")          # subtle border
STREAMING_BG = ("#eff6ff", "#1e293b")    # streaming state tint
ICON_TEXT = ("#374151", "#d1d5db")       # icon/text on subtle buttons (dark in light, light in dark)

# Moving ">>>-----" marquee frames shown while a translation is in flight.
# The ">>>" arrow slides left→right across a dashed track, looping.
def _build_progress_frames(width: int = 12, arrow: str = ">>>") -> list:
    n = len(arrow)
    frames = []
    for i in range(width - n + 1):
        row = ["-"] * width
        for j in range(n):
            row[i + j] = arrow[j]
        frames.append("".join(row))
    return frames

_PROGRESS_FRAMES = _build_progress_frames()


class MainWindow:
    """Main translation window with normal and compact modes."""

    # Mode constants
    MODE_NORMAL = "normal"
    MODE_COMPACT = "compact"

    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.current_image: Optional[Image.Image] = None
        self.image_tk: Optional[ImageTk.PhotoImage] = None

        # Streaming & thread management
        self._streaming = False
        self._stream_queue: queue.Queue = queue.Queue()
        self._active_thread: Optional[threading.Thread] = None
        self._cancel_event = threading.Event()  # Signal to cancel ongoing translation

        # History manager
        self.history_manager = HistoryManager()
        self._current_source_text = ""
        self._current_has_image = False

        # Translation cache — avoid redundant API calls
        self.cache = TranslationCache()

        # Usage statistics
        self.stats = UsageStats()

        # Window state
        self._compact_mode = config_manager.get("compact_mode", False)
        self._mode = self.MODE_COMPACT if self._compact_mode else self.MODE_NORMAL
        self._position_save_timer = None
        self._dialog_open = False  # True while settings dialog is open

        # Create main window
        self.window = ctk.CTk()
        self.window.title("便捷翻译")
        self.window.resizable(True, True)

        # Set taskbar/window icon (same as tray icon)
        import os
        ico_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "assets", "icon.ico"
        )
        if os.path.exists(ico_path):
            try:
                self.window.iconbitmap(default=ico_path)
            except Exception:
                try:
                    from PIL import Image, ImageTk
                    img = Image.open(ico_path)
                    photo = ImageTk.PhotoImage(img)
                    self.window.iconphoto(True, photo)
                    self._icon_photo = photo  # prevent GC
                except Exception:
                    pass

        # Set theme
        self._apply_theme()

        # Hide window initially (wait for hotkey)
        self.window.withdraw()

        # Build UI
        self._create_widgets()
        self._setup_bindings()
        self._apply_initial_geometry()

    # ──────────────────────────────────────────────
    # Theme
    # ──────────────────────────────────────────────

    def _apply_theme(self) -> None:
        """Apply theme based on configuration."""
        theme = self.config_manager.get("theme", "System")
        if theme == "Light":
            ctk.set_appearance_mode("light")
        elif theme == "Dark":
            ctk.set_appearance_mode("dark")
        else:
            ctk.set_appearance_mode("system")

    # ──────────────────────────────────────────────
    # Widget creation
    # ──────────────────────────────────────────────

    def _create_widgets(self) -> None:
        """Create UI widgets (mode-dependent)."""
        # Main container
        self.main_frame = ctk.CTkFrame(self.window, fg_color="transparent")
        self.main_frame.pack(fill="both", expand=True, padx=15, pady=15)

        # ── Toolbar ──────────────────────────────────────
        self._create_toolbar()

        # ── Input area ───────────────────────────────────
        self.input_frame = ctk.CTkFrame(
            self.main_frame,
            fg_color=SURFACE,
            border_width=1,
            border_color=BORDER,
            corner_radius=10,
        )
        self.input_frame.pack(fill="x", pady=(5, 8))

        self.input_label = ctk.CTkLabel(
            self.input_frame,
            text="输入文本  ·  Ctrl+V 粘贴图片",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        )
        self.input_label.pack(anchor="w", padx=12, pady=(10, 4))

        self.input_content_frame = ctk.CTkFrame(self.input_frame, fg_color="transparent")
        self.input_content_frame.pack(fill="x", padx=12, pady=(0, 10))

        self.text_input = ctk.CTkTextbox(
            self.input_content_frame,
            height=80 if not self._compact_mode else 40,
            font=ctk.CTkFont(size=13),
            wrap="word",
            fg_color="transparent",
            border_width=0,
        )
        self.text_input.pack(side="left", fill="both", expand=True)

        # Image preview
        self.image_frame = ctk.CTkFrame(self.input_content_frame, width=120)
        self.image_frame.pack(side="right", padx=(10, 0))
        self.image_frame.pack_forget()

        self.image_header = ctk.CTkFrame(self.image_frame, fg_color="transparent")
        self.image_header.pack(fill="x", padx=5, pady=(5, 2))

        self.image_label = ctk.CTkLabel(
            self.image_header, text="图片", font=ctk.CTkFont(size=10),
        )
        self.image_label.pack(side="left")

        self.remove_image_btn = ctk.CTkButton(
            self.image_header, text="✕", width=20, height=16,
            fg_color=("darkred", "#8b0000"), hover_color=("red", "#cd0000"),
            font=ctk.CTkFont(size=8),
            command=self._remove_image,
        )
        self.remove_image_btn.pack(side="right")
        add_tooltip(self.remove_image_btn, "移除图片")

        self.image_preview = ctk.CTkLabel(
            self.image_frame, text="", width=100, height=60,
        )
        self.image_preview.pack(padx=5, pady=(0, 5))

        # ── Translate button ─────────────────────────────
        self.translate_btn = ctk.CTkButton(
            self.main_frame,
            text="翻  译",
            height=38,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            corner_radius=8,
            command=self._do_translate,
        )
        self.translate_btn.pack(fill="x", pady=(8, 8))

        # ── Translation progress (shown ONLY while translating) ──
        # A moving ">>>-----" marquee + "翻译中…" caption gives unambiguous
        # feedback during the (sometimes multi-second) wait for the model.
        self.progress_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.progress_frame.pack_forget()  # hidden until a translation starts

        self.progress_anim = ctk.CTkLabel(
            self.progress_frame, text=_PROGRESS_FRAMES[0],
            font=ctk.CTkFont(family="Consolas", size=14, weight="bold"),
            text_color=ACCENT, anchor="w",
        )
        self.progress_anim.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.progress_label = ctk.CTkLabel(
            self.progress_frame, text="翻译中…",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=ACCENT, width=58, anchor="e",
        )
        self.progress_label.pack(side="right")

        self._progress_animating = False
        self._progress_frame_index = 0

        # ── Result area ──────────────────────────────────
        self.result_frame = ctk.CTkFrame(
            self.main_frame,
            fg_color=SURFACE,
            border_width=1,
            border_color=BORDER,
            corner_radius=10,
        )
        self.result_frame.pack(fill="both", expand=True, pady=(0, 8))

        self.result_header = ctk.CTkFrame(self.result_frame, fg_color="transparent")
        self.result_header.pack(fill="x", padx=12, pady=(10, 4))

        self.result_label = ctk.CTkLabel(
            self.result_header, text="翻译结果", font=ctk.CTkFont(size=11),
            text_color="gray",
        )
        self.result_label.pack(side="left")

        self.copy_btn = self._make_icon_button(self.result_header, "📋", self._copy_result)
        self.copy_btn.pack(side="right", padx=(0, 4))
        add_tooltip(self.copy_btn, "复制翻译结果")

        self.retrans_btn = self._make_icon_button(self.result_header, "🔄", self._do_translate)
        self.retrans_btn.pack(side="right", padx=(0, 4))
        add_tooltip(self.retrans_btn, "重新翻译")

        self.stats_btn = self._make_icon_button(self.result_header, "📊", self._show_stats)
        self.stats_btn.pack(side="right")
        add_tooltip(self.stats_btn, "使用统计")

        # Two independent play buttons: user chooses to read English words
        # OR example sentences — whichever they prefer.
        self.tts_examples_btn = ctk.CTkButton(
            self.result_header, text="🔊例句", width=64, height=28,
            fg_color=SUBTLE, hover_color=SUBTLE_HOVER,
            text_color=ICON_TEXT, corner_radius=6,
            font=ctk.CTkFont(size=12),
            command=lambda: self._play_tts("examples"),
        )
        self.tts_examples_btn.pack(side="right", padx=(0, 4))
        add_tooltip(self.tts_examples_btn, "朗读示例句子")

        self.tts_words_btn = ctk.CTkButton(
            self.result_header, text="🔊单词", width=64, height=28,
            fg_color=SUBTLE, hover_color=SUBTLE_HOVER,
            text_color=ICON_TEXT, corner_radius=6,
            font=ctk.CTkFont(size=12),
            command=lambda: self._play_tts("words"),
        )
        self.tts_words_btn.pack(side="right", padx=(0, 4))
        add_tooltip(self.tts_words_btn, "朗读英文单词")

        self.tts_speaking = False
        self._tts_mode = None  # which category is currently playing

        from ui.markdown_viewer import MarkdownViewer
        self.result_text: MarkdownViewer = MarkdownViewer(
            self.result_frame,
            font=("Microsoft YaHei UI", 14),
        )
        self.result_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # ── Status bar ───────────────────────────────────
        status_text = self._build_status_text()
        self.status_bar = ctk.CTkLabel(
            self.main_frame,
            text=status_text,
            font=ctk.CTkFont(size=11),
            text_color="gray",
        )
        self.status_bar.pack(fill="x", pady=(4, 0))

        # Refresh tooltips to show configured shortcuts
        self._refresh_button_tooltips()

    def _create_toolbar(self) -> None:
        """Create the top toolbar with action buttons."""
        self.toolbar = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.toolbar.pack(fill="x", pady=(0, 8))

        # Left side: mode toggle
        self.mode_btn = self._make_icon_button(
            self.toolbar, "🔳" if self._compact_mode else "🔲",
            self._toggle_mode,
        )
        self.mode_btn.pack(side="left")
        add_tooltip(self.mode_btn, "精简模式 / 普通模式")

        # Title (hidden in compact mode)
        self.title_label = ctk.CTkLabel(
            self.toolbar,
            text="便捷翻译",
            font=ctk.CTkFont(size=15, weight="bold"),
        )
        if not self._compact_mode:
            self.title_label.pack(side="left", padx=(10, 0))

        # Quick model switcher — switch models without opening settings
        self._create_model_switcher(self.toolbar)

        # Right side: action buttons (packed right-to-left)
        self.settings_btn = self._make_icon_button(self.toolbar, "⚙️", self._show_settings)
        self.settings_btn.pack(side="right")
        add_tooltip(self.settings_btn, "设置")

        self.clear_btn = self._make_icon_button(self.toolbar, "🗑️", self._clear_all)
        self.clear_btn.pack(side="right", padx=(0, 4))
        add_tooltip(self.clear_btn, "清空 (Ctrl+L)")

        self.history_btn = self._make_icon_button(self.toolbar, "📜", self._show_history)
        self.history_btn.pack(side="right", padx=(0, 4))
        add_tooltip(self.history_btn, "翻译历史")

        # 划线翻译按钮（Alt+W）
        self.select_btn = self._make_icon_button(self.toolbar, "🖱️", self._select_translate)
        self.select_btn.pack(side="right", padx=(0, 4))
        add_tooltip(self.select_btn, "划线翻译 (Alt+W)")

    def _create_model_switcher(self, parent) -> None:
        """Create a model-selection combobox on the toolbar for quick switching.

        Lists the current provider's models (or all known models in custom
        mode) with a cost indicator. Selecting a model persists it to the
        config immediately and applies on the next translation.
        """
        self.model_var = ctk.StringVar()
        self._model_ids: list = []
        self._model_labels: list = []
        self.model_combo = ctk.CTkComboBox(
            parent,
            values=[],
            variable=self.model_var,
            width=170,
            height=28,
            font=ctk.CTkFont(size=12),
            command=self._on_model_selected,
        )
        self.model_combo.pack(side="left", padx=(8, 0))
        add_tooltip(self.model_combo, "切换模型（立即生效）")
        self._populate_model_combo()

    def _model_label(self, model_id: str) -> str:
        """Short combobox label: model id + cost indicator."""
        from config import MODEL_INFO
        info = MODEL_INFO.get(model_id)
        if info:
            return f"{model_id}  {info['cost']}"
        return model_id

    def _model_tooltip(self, model_id: str) -> str:
        """Full description tooltip for a model id."""
        from config import MODEL_INFO
        info = MODEL_INFO.get(model_id)
        if info:
            return f"{info['cost']} {info['desc']}"
        return model_id

    def _populate_model_combo(self) -> None:
        """Fill the model combobox from the current provider's models.

        Falls back to all known models when the provider is "自定义" or unset,
        so a custom base_url can still reach any model. The currently
        configured model is always included even if it is not in the list.
        """
        ids = self.config_manager.get_models_for_provider()

        self._model_ids = ids
        self._model_labels = [self._model_label(mid) for mid in ids]
        self.model_combo.configure(values=self._model_labels)
        current = self.config_manager.get("model", "")
        if current:
            self.model_var.set(self._model_label(current))
        elif self._model_labels:
            self.model_var.set(self._model_labels[0])

    def _combo_label_to_id(self, label: str) -> str:
        """Map a combobox display label back to its model id."""
        if label in self._model_labels:
            return self._model_ids[self._model_labels.index(label)]
        # Fallback: longest-prefix match (handles custom models not in MODEL_INFO)
        for mid in sorted(self._model_ids, key=len, reverse=True):
            if label.startswith(mid):
                return mid
        return label

    def _on_model_selected(self, choice: str) -> None:
        """Persist the selected model immediately and confirm via status bar.

        ``select_model`` syncs the active base_url/api_key from the
        chosen model's stored entry, so translation uses the right endpoint.
        """
        model_id = self._combo_label_to_id(choice)
        if not model_id:
            return
        if self.config_manager.select_model(model_id):
            self.config_manager.save()
            self._set_status(f"已切换模型 → {model_id}")
            update_tooltip(self.model_combo, self._model_tooltip(model_id))

    def _sync_model_combo(self) -> None:
        """Re-sync the combobox to the config model (e.g. after settings save)."""
        self._populate_model_combo()

    def _make_icon_button(self, parent, text: str, command, width: int = 34, height: int = 28):
        """Create a consistently-styled subtle icon button for the toolbar."""
        return ctk.CTkButton(
            parent,
            text=text,
            width=width,
            height=height,
            fg_color=SUBTLE,
            hover_color=SUBTLE_HOVER,
            text_color=ICON_TEXT,
            corner_radius=6,
            font=ctk.CTkFont(size=13),
            command=command,
        )

    def _build_status_text(self) -> str:
        """Build status bar text based on current shortcuts from config."""
        hotkey = self.config_manager.get_hotkey().upper()
        sc = self.config_manager.get_all_shortcuts()

        parts = [f"{hotkey} 呼出"]
        for key, label in [
            ("shortcut_translate", "翻译"),
            ("shortcut_clear", "清空"),
            ("shortcut_select", "划线"),
        ]:
            b = sc.get(key, "")
            if b:
                parts.append(f"{format_binding(b)} {label}")
        parts.append("ESC 隐藏")
        return " | ".join(parts)

    # ──────────────────────────────────────────────
    # Bindings & geometry
    # ──────────────────────────────────────────────

    def _setup_bindings(self) -> None:
        """Setup keyboard and event bindings (reads shortcuts from config)."""
        shortcuts = self.config_manager.get_all_shortcuts()

        # Remember old shortcuts so rebind_shortcuts() can unbind them
        self._saved_shortcuts: Dict[str, str] = dict(shortcuts)

        # Helper to safely bind a shortcut (skip if empty)
        # Use default-argument capture to avoid closure-in-loop bug
        def _bind(shortcut_key: str, callback):
            binding = shortcuts.get(shortcut_key, "")
            if binding:
                try:
                    self.window.bind(binding, lambda e, cb=callback: cb())
                except Exception:
                    pass  # Invalid binding format → skip

        _bind("shortcut_translate", self._do_translate)
        _bind("shortcut_clear", self._clear_all)
        _bind("shortcut_select", self._select_translate)
        _bind("shortcut_history", self._show_history)
        _bind("shortcut_stats", self._show_stats)
        _bind("shortcut_mode", self._toggle_mode)

        # Escape is fixed (hide window) — not configurable
        self.window.bind('<Escape>', self._on_escape)

        # Ctrl+V for paste is fixed (system convention)
        self.window.bind('<Control-v>', lambda e: self._handle_paste())
        self.text_input.bind('<Control-v>', lambda e: self._handle_paste())

        # Track window move for position memory
        self.window.bind('<Configure>', self._on_window_configure)

        # Drag and drop
        try:
            from tkinterdnd2 import DND_FILES
            self.window.drop_target_register(DND_FILES)
            self.window.dnd_bind('<<Drop>>', self._handle_drop)
        except ImportError:
            pass

        self.window.protocol("WM_DELETE_WINDOW", self.hide)

    # Default window geometries
    _DEFAULT_NORMAL_W = 600
    _DEFAULT_NORMAL_H = 500
    _DEFAULT_COMPACT_W = 480
    _DEFAULT_COMPACT_H = 220

    def _on_escape(self, event=None) -> None:
        """Escape key: cancel ongoing translation, then hide window."""
        if self._streaming:
            self._cancel_event.set()
        self.hide()

    def _cancel_translation(self) -> None:
        """Cancel an in-progress translation and reset UI state."""
        self._cancel_event.set()
        self._set_streaming_ui(False)
        self._set_status("翻译已取消")

    def _apply_initial_geometry(self) -> None:
        """Center the window at the fixed 600x500 size."""
        w, h = self._DEFAULT_NORMAL_W, self._DEFAULT_NORMAL_H
        x = (self.window.winfo_screenwidth() // 2) - (w // 2)
        y = (self.window.winfo_screenheight() // 2) - (h // 2)

        self.window.geometry(f"{w}x{h}+{x}+{y}")
        self.window.minsize(w, h)

        if self._compact_mode:
            self._apply_compact_layout()
        else:
            self.window.minsize(420, 360)

    def _on_window_configure(self, event) -> None:
        """Debounced save of window position/size."""
        if event.widget is not self.window:
            return
        # Only track when visible and not minimized
        if event.width < 100 or event.height < 100:
            return
        # Skip if settings dialog is open (prevents event conflicts)
        if getattr(self, '_dialog_open', False):
            return

        # Debounce: cancel pending save, schedule new one
        if self._position_save_timer:
            self.window.after_cancel(self._position_save_timer)
        self._position_save_timer = self.window.after(500, self._save_position)

    def _save_position(self) -> None:
        """Persist current window position and size."""
        try:
            x = self.window.winfo_x()
            y = self.window.winfo_y()
            w = self.window.winfo_width()
            h = self.window.winfo_height()
            self.config_manager.save_window_geometry(x, y, w, h)
        except Exception:
            pass  # Ignore if window is being destroyed

    def rebind_shortcuts(self) -> None:
        """Re-read shortcuts from config and properly rebind window events.

        Correctly unbinds the OLD shortcuts before binding the new ones,
        and avoids the classic closure-in-loop bug by using default-arg capture.
        """
        old_shortcuts = getattr(self, '_saved_shortcuts', {})
        new_shortcuts = self.config_manager.get_all_shortcuts()

        shortcut_callbacks = [
            ("shortcut_translate", self._do_translate),
            ("shortcut_clear", self._clear_all),
            ("shortcut_select", self._select_translate),
            ("shortcut_history", self._show_history),
            ("shortcut_stats", self._show_stats),
            ("shortcut_mode", self._toggle_mode),
        ]

        for key, callback in shortcut_callbacks:
            old_binding = old_shortcuts.get(key, "")
            new_binding = new_shortcuts.get(key, "")

            # 1. Unbind the OLD shortcut (if it changed and is non-empty)
            if old_binding and old_binding != new_binding:
                try:
                    self.window.unbind(old_binding)
                except Exception:
                    pass

            # 2. Bind the NEW shortcut (use default-arg to capture callback)
            if new_binding:
                try:
                    self.window.bind(new_binding, lambda e, cb=callback: cb())
                except Exception:
                    pass

        # 3. Update saved shortcuts for next rebind
        self._saved_shortcuts = dict(new_shortcuts)

        self._update_status_text()
        self._refresh_button_tooltips()

    # ──────────────────────────────────────────────
    # Mode toggle (compact mode)
    # ──────────────────────────────────────────────

    def _toggle_mode(self) -> None:
        """Switch between normal and compact mode."""
        self._compact_mode = not self._compact_mode
        self.config_manager.set("compact_mode", self._compact_mode)
        self.config_manager.save()

        # Update button icon
        self.mode_btn.configure(text="🔳" if self._compact_mode else "🔲")

        if self._compact_mode:
            self._apply_compact_layout()
        else:
            self._apply_normal_layout()
        self._update_status_text()

    def _expand_to_normal_for_result(self) -> None:
        """Auto-expand from compact to normal mode when translation completes.

        Updates the internal state so the UI toggle button stays in sync,
        but does NOT persist compact_mode to config — the user's saved
        preference is preserved so next startup stays in compact mode.
        """
        self.mode_btn.configure(text="🔲")
        self._apply_normal_layout()
        # Mark that we are now showing normal layout (so the toggle button works),
        # but don't save — next time the app starts it will still use compact mode.
        self._compact_mode = False

    def _apply_compact_layout(self) -> None:
        """Switch to compact layout at the fixed 600x500 size."""
        w, h = self._DEFAULT_COMPACT_W, self._DEFAULT_COMPACT_H
        x = (self.window.winfo_screenwidth() // 2) - (w // 2)
        y = (self.window.winfo_screenheight() // 2) - (h // 2)

        self.window.geometry(f"{w}x{h}+{x}+{y}")
        self.window.minsize(w, h)

        # Hide title
        self.title_label.pack_forget()

        # Shrink input
        self.text_input.configure(height=50)

        # Hide input label
        self.input_label.pack_forget()

    def _apply_normal_layout(self) -> None:
        """Restore normal layout at the fixed 600x500 size."""
        w, h = self._DEFAULT_NORMAL_W, self._DEFAULT_NORMAL_H
        x = (self.window.winfo_screenwidth() // 2) - (w // 2)
        y = (self.window.winfo_screenheight() // 2) - (h // 2)

        self.window.geometry(f"{w}x{h}+{x}+{y}")
        self.window.minsize(w, h)
        self.title_label.pack(side="left", padx=(10, 0))
        self.text_input.configure(height=70)
        self.input_label.pack(anchor="w", padx=12, pady=(10, 4))

    # ──────────────────────────────────────────────
    # Window show/hide
    # ──────────────────────────────────────────────

    def show(self) -> None:
        """Show the window and bring to front."""
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()
        self.window.attributes('-topmost', True)
        self.window.after(100, lambda: self.window.attributes('-topmost', False))
        self.text_input.focus_set()

    def hide(self) -> None:
        """Hide the window."""
        # Save position before hiding
        if self._position_save_timer:
            self.window.after_cancel(self._position_save_timer)
        self._save_position()
        self.window.withdraw()

    def toggle(self) -> None:
        """Toggle window visibility."""
        if self.window.winfo_viewable():
            self.hide()
        else:
            self.show()

    # ──────────────────────────────────────────────
    # Settings & Hotkey
    # ──────────────────────────────────────────────

    def _show_settings(self) -> None:
        """Show settings dialog."""
        self._dialog_open = True
        show_settings_dialog(
            self.window,
            self.config_manager,
            hotkey_manager=getattr(self, '_hotkey_manager', None),
            on_save=self._on_settings_saved,
            on_close=self._on_settings_closed,
            on_models_changed=self._sync_model_combo,
        )

    def set_hotkey_manager(self, hotkey_manager) -> None:
        """Allow main.py to inject the hotkey manager for re-registration."""
        self._hotkey_manager = hotkey_manager

    def _on_settings_closed(self) -> None:
        """Called when settings dialog is closed/destroyed."""
        self._dialog_open = False
        # Models may have been added/removed (persisted immediately),
        # so resync the dropdown to reflect the current entries.
        self._sync_model_combo()

    def _on_settings_saved(self) -> None:
        """Handle settings saved — may trigger theme/language/hotkey updates."""
        self.rebind_shortcuts()
        self._apply_geometry_from_config()
        self._sync_model_combo()

    def _apply_geometry_from_config(self) -> None:
        """After settings save, if compact_mode changed, update layout."""
        new_compact = self.config_manager.get("compact_mode", False)
        if new_compact != self._compact_mode:
            self._compact_mode = new_compact
            self.mode_btn.configure(text="🔳" if self._compact_mode else "🔲")
            if self._compact_mode:
                self._apply_compact_layout()
            else:
                self._apply_normal_layout()

    # ──────────────────────────────────────────────
    # History
    # ──────────────────────────────────────────────

    def _show_history(self) -> None:
        """Open history panel in a new window."""
        dialog = ctk.CTkToplevel(self.window)
        dialog.title("翻译历史")
        dialog.geometry("400x500")
        dialog.minsize(350, 400)
        dialog.transient(self.window)

        from ui.history_panel import HistoryPanel
        panel = HistoryPanel(
            dialog,
            history_manager=self.history_manager,
            on_select=lambda entry: self._load_history_entry(entry, dialog),
        )
        panel.pack(fill="both", expand=True, padx=5, pady=5)

        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (400 // 2)
        y = (dialog.winfo_screenheight() // 2) - (500 // 2)
        dialog.geometry(f"400x500+{x}+{y}")

    def _load_history_entry(self, entry, dialog) -> None:
        """Load a history entry into the main window."""
        self.text_input.delete("1.0", "end")
        self.text_input.insert("1.0", entry.source_text)
        self._set_result(entry.result_text)
        dialog.destroy()

    # ──────────────────────────────────────────────
    # Paste & Drop
    # ──────────────────────────────────────────────

    def _handle_paste(self) -> None:
        """Handle paste event — paste image if found in clipboard, otherwise let text pass through."""
        from PIL import ImageGrab

        def _try_pil() -> bool:
            """Try PIL's grabclipboard — works on Windows for most images."""
            image = ImageGrab.grabclipboard()
            if isinstance(image, Image.Image):
                self._set_image(image)
                return True
            if isinstance(image, list) and image:
                # On some platforms grabclipboard returns a list of filenames
                ext = image[0].lower()
                if ext.endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp')):
                    self._set_image(Image.open(image[0]))
                    return True
            return False

        def _try_win32() -> bool:
            """Try win32clipboard to detect bitmap/DIB images that PIL might miss."""
            try:
                import win32clipboard
                win32clipboard.OpenClipboard()
                try:
                    for fmt in (win32clipboard.CF_BITMAP, win32clipboard.CF_DIB, win32clipboard.CF_DIBV5):
                        if win32clipboard.IsClipboardFormatAvailable(fmt):
                            image = ImageGrab.grabclipboard()
                            if isinstance(image, Image.Image):
                                self._set_image(image)
                                return True
                finally:
                    win32clipboard.CloseClipboard()
            except Exception:
                pass
            return False

        try:
            if _try_pil() or _try_win32():
                return "break"
        except Exception:
            pass
        return None

    def _handle_drop(self, event) -> None:
        """Handle file drop event."""
        try:
            file_path = event.data
            if file_path.startswith('{') and file_path.endswith('}'):
                file_path = file_path[1:-1]
            image_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp')
            if file_path.lower().endswith(image_extensions):
                image = Image.open(file_path)
                self._set_image(image)
        except Exception as e:
            self._set_status(f"无法加载图片: {e}", error=True)

    # ──────────────────────────────────────────────
    # Image handling
    # ──────────────────────────────────────────────

    def _set_image(self, image: Image.Image) -> None:
        """Set current image and update preview."""
        self.current_image = image
        thumbnail = image.copy()
        thumbnail.thumbnail((100, 60), Image.Resampling.LANCZOS)
        self.image_tk = ctk.CTkImage(light_image=thumbnail, dark_image=thumbnail, size=thumbnail.size)
        self.image_preview.configure(image=self.image_tk, text="")
        self.image_frame.pack(side="right", padx=(10, 0))
        self._set_status(f"图片已加载 ({image.size[0]}x{image.size[1]})")

    def _remove_image(self) -> None:
        """Remove current image."""
        self.current_image = None
        self.image_tk = None
        self.image_preview.configure(image=None, text="")
        self.image_frame.pack_forget()
        self._set_status("图片已移除")

    def _clear_all(self) -> None:
        """Clear all inputs and results."""
        self.text_input.delete("1.0", "end")
        self._remove_image()
        self._set_result("")
        self._set_status("已清空")

    # ──────────────────────────────────────────────
    # Translation (streaming)
    # ──────────────────────────────────────────────

    def _do_translate(self) -> None:
        """Perform translation with streaming support, cache lookup, and progress.

        If a translation is already in progress, clicking the button (or
        pressing the shortcut again) cancels it instead of starting a new one.
        """
        if self._streaming:
            self._cancel_translation()
            return

        text = self.text_input.get("1.0", "end-1c").strip()

        if not text and not self.current_image:
            self._set_status("请输入文本或粘贴图片", error=True)
            return

        if not self.config_manager.is_configured():
            self._set_status("请先配置 API 设置", error=True)
            self._show_settings()
            return

        # Track for history
        self._current_source_text = text
        self._current_has_image = self.current_image is not None
        model = self.config_manager.get("model", "")

        # Check translation cache first — only for text-only translations
        if text and not self.current_image:
            cached = self.cache.get(text, model)
            if cached is not None:
                self._set_result(cached)
                self._set_status("⚡ 缓存命中（未调用 API）", success=True)
                self.stats.record(model, len(text), cache_hit=True)
                # Still save to history
                self.history_manager.add(
                    source_text=text, result_text=cached,
                    has_image=False, model=model,
                )
                return

        # Set UI to streaming state
        self._streaming = True
        self._cancel_event.clear()
        self._char_count = 0  # Track for progress display
        self._first_chunk_time: Optional[float] = None
        self._set_streaming_ui(True)
        self._set_progress_visible(True)
        self.result_text.clear()
        self._stream_queue = queue.Queue()

        # Start waiting indicator
        self._update_progress_indicator()

        # Run translation in separate thread
        self._active_thread = threading.Thread(
            target=self._translate_worker, args=(text,), daemon=True,
        )
        self._active_thread.start()

        # Start polling the stream queue
        self._poll_stream_queue()

    def _create_translator(self) -> Translator:
        """Build a Translator instance from the current API config."""
        api_config = self.config_manager.get_api_config()
        system_prompts = {
            "system_prompt_text": api_config.get("system_prompt_text", ""),
            "system_prompt_image": api_config.get("system_prompt_image", ""),
            "system_prompt_text_image": api_config.get("system_prompt_text_image", ""),
        }
        return Translator(
            base_url=api_config["base_url"],
            api_key=api_config["api_key"],
            model=api_config["model"],
            temperature=api_config.get("temperature", 0.3),
            timeout=api_config.get("timeout", 60),
            system_prompts=system_prompts or None,
        )

    def _build_translation_messages(self, translator: Translator, text: str) -> list:
        """Build the message list for the current input (text and/or image).

        Selects the appropriate system prompt key based on whether an image
        is present and whether accompanying text was provided.
        """
        if self.current_image and text:
            prompt_key = "system_prompt_text_image"
            user_content = self._build_image_content(text)
        elif self.current_image:
            prompt_key = "system_prompt_image"
            user_content = self._build_image_content(None)
        else:
            prompt_key = "system_prompt_text"
            user_content = text

        return [
            {"role": "system", "content": translator.get_system_prompt(prompt_key)},
            {"role": "user", "content": user_content},
        ]

    def _translate_worker(self, text: str) -> None:
        """Worker thread for streaming translation."""
        try:
            translator = self._create_translator()
            messages = self._build_translation_messages(translator, text)

            for chunk in translator._make_stream_request(messages):
                if self._cancel_event.is_set():
                    self._stream_queue.put(("cancelled", None))
                    return
                self._stream_queue.put(("chunk", chunk))

            if not self._cancel_event.is_set():
                self._stream_queue.put(("done", None))
            else:
                self._stream_queue.put(("cancelled", None))

        except TranslationError as e:
            self._stream_queue.put(("error", str(e)))
        except Exception as e:
            self._stream_queue.put(("error", f"翻译失败: {e}"))

    def _build_image_content(self, text: Optional[str]) -> list:
        """Build multimodal content with base64 image."""
        return build_image_content(self.current_image, text)

    def _update_progress_indicator(self) -> None:
        """Show streaming progress in the status bar."""
        if not self._streaming:
            return
        import time
        if self._first_chunk_time is not None:
            elapsed = time.time() - self._first_chunk_time
            self._set_status(
                f"翻译中… 已接收 {self._char_count} 字符 ({elapsed:.1f}s)"
            )
        else:
            # Animated ellipsis so the wait feels alive during first-token latency
            dots = "." * ((int(time.time() * 2) % 4))
            self._set_status(f"等待模型响应{dots}")
        self.window.after(500, self._update_progress_indicator)

    @staticmethod
    def _raw_has_markdown(text: str) -> bool:
        """Check if *text* contains any markdown formatting markers.

        Used to decide whether a full markdown re-render is needed after
        streaming completes — plain text results skip the re-render to
        avoid a visual flash.
        """
        if not text:
            return False
        markers = ("**", "*", "`", "# ", "- ", "* ", "+ ", "> ", "```")
        return any(m in text for m in markers)

    def _poll_stream_queue(self) -> None:
        """Poll stream queue and update UI with chunks."""
        import time
        try:
            while True:
                msg_type, data = self._stream_queue.get_nowait()

                if msg_type == "chunk":
                    if self._first_chunk_time is None:
                        self._first_chunk_time = time.time()
                    self._char_count += len(data)
                    self._append_result(data)
                elif msg_type == "done":
                    # Re-render accumulated raw text as proper markdown —
                    # but skip the rerender if there are no markdown markers,
                    # avoiding an unnecessary visual flash for plain-text results.
                    if self._raw_has_markdown(self.result_text.get_raw()):
                        self.result_text.rerender()
                    self._on_translation_complete()
                    return
                elif msg_type == "cancelled":
                    self._set_streaming_ui(False)
                    self.result_text.clear()
                    self._set_status("翻译已取消")
                    return
                elif msg_type == "error":
                    self._on_translation_error(data)
                    return
        except queue.Empty:
            self.window.after(15, self._poll_stream_queue)

    def _set_streaming_ui(self, is_streaming: bool) -> None:
        """Update UI elements during streaming state.

        During streaming the translate button becomes a cancel button
        with an amber accent, and the result frame border tints blue
        to provide clear visual feedback that a translation is in progress.
        """
        if is_streaming:
            self.translate_btn.configure(
                text="取消翻译",
                fg_color=("#f59e0b", "#b45309"),
                hover_color=("#d97706", "#92400e"),
            )
            self.retrans_btn.configure(state="disabled")
            self.result_frame.configure(border_color=ACCENT)
        else:
            self.translate_btn.configure(
                text="翻  译",
                fg_color=ACCENT,
                hover_color=ACCENT_HOVER,
                state="normal",
            )
            self.retrans_btn.configure(state="normal")
            self.result_frame.configure(border_color=BORDER)
            self._set_progress_visible(False)
            self._streaming = False
            self._active_thread = None

    def _set_progress_visible(self, visible: bool) -> None:
        """Show/hide the moving ">>>-----" marquee during translation."""
        if visible:
            if not self.progress_frame.winfo_ismapped():
                self.progress_frame.pack(fill="x", pady=(0, 8))
            if not self._progress_animating:
                self._progress_animating = True
                self._progress_frame_index = 0
                self._animate_progress()
        else:
            self._progress_animating = False
            if self.progress_frame.winfo_ismapped():
                self.progress_frame.pack_forget()

    def _animate_progress(self) -> None:
        """Advance the ">>>-----" marquee one step (looped via after())."""
        if not self._progress_animating:
            return
        self._progress_frame_index = (
            self._progress_frame_index + 1
        ) % len(_PROGRESS_FRAMES)
        self.progress_anim.configure(text=_PROGRESS_FRAMES[self._progress_frame_index])
        self.window.after(120, self._animate_progress)

    def _on_translation_complete(self) -> None:
        """Handle successful translation."""
        self._set_streaming_ui(False)

        # Auto-expand from compact to normal mode so result is visible
        if self._compact_mode:
            self._expand_to_normal_for_result()

        result = self.result_text.get_raw()
        model = self.config_manager.get("model", "")

        if result and not result.startswith("错误:"):
            char_count = len(self._current_source_text)

            # Save to translation cache
            if self._current_source_text and not self._current_has_image:
                self.cache.put(self._current_source_text, model, result)

            # Record usage stats
            self.stats.record(
                model=model,
                char_count=char_count,
                has_image=self._current_has_image,
            )

            # Save to history
            self.history_manager.add(
                source_text=self._current_source_text,
                result_text=result,
                has_image=self._current_has_image,
                model=model,
            )

            status = "✓ 翻译完成"
            if self.cache.size > 0:
                status += f"  ·  缓存 {self.cache.size} 条"
            self._set_status(status, success=True)
        else:
            self._set_status("翻译完成")

    def _on_translation_error(self, error: str) -> None:
        """Handle translation error."""
        self._set_streaming_ui(False)
        self._set_result(f"错误: {error}")
        self._set_status(error, error=True)

    # ──────────────────────────────────────────────
    # Select / translate (Alt+W)
    # ──────────────────────────────────────────────

    def _select_translate(self) -> None:
        """Translate the currently selected text (Alt+W).

        Runs the copy operation in a background thread to avoid blocking
        the tkinter event loop (the copy waits up to 1s for Alt release).
        """
        if self._streaming:
            return

        import threading

        def _do_copy():
            # Copy selected text BEFORE showing window
            text = get_selected_text_via_copy()
            # Schedule UI update on main thread
            self.window.after(0, lambda: self._apply_select_result(text))

        threading.Thread(target=_do_copy, daemon=True).start()

    def _apply_select_result(self, text: Optional[str]) -> None:
        """Apply the copied text to the UI (called on main thread)."""
        # Ensure window is visible
        if not self.window.winfo_viewable():
            self.show()
        if text:
            self.text_input.delete("1.0", "end")
            self.text_input.insert("1.0", text)
            self._set_status(f"已获取选中文字 ({len(text)} 字符)")
            self.text_input.focus_set()
            # Auto-translate
            self.window.after(100, self._do_translate)
        else:
            self._set_status("未能获取选中文字，请先选中文本", error=True)

    # ──────────────────────────────────────────────
    # Usage statistics
    # ──────────────────────────────────────────────

    def _show_stats(self) -> None:
        """Open statistics dialog."""
        show_stats_dialog(self.window, self.stats, self.cache)

    # ──────────────────────────────────────────────
    # Result & status helpers
    # ──────────────────────────────────────────────

    def _set_result(self, text: str, error: bool = False) -> None:
        """Set result text (replaces all content)."""
        self.result_text.set_content(text)

    def _append_result(self, text: str) -> None:
        """Append text to result box (for streaming, raw mode)."""
        self.result_text.append_raw(text)

    def _set_status(self, text: str, error: bool = False, success: bool = False) -> None:
        """Set status bar text with optional color cues."""
        if error:
            color = ("#dc2626", "#ef4444")
        elif success:
            color = SUCCESS
        else:
            color = "gray"
        self.status_bar.configure(text=text, text_color=color)

    def _update_status_text(self) -> None:
        """Restore status bar to default info text."""
        self.status_bar.configure(text=self._build_status_text(), text_color="gray")

    def _refresh_button_tooltips(self) -> None:
        """Update button tooltips to reflect current shortcuts."""
        sc = self.config_manager.get_all_shortcuts()

        _btn_tooltip_mappings = [
            (self.clear_btn, "清空", "shortcut_clear"),
            (self.select_btn, "划线翻译", "shortcut_select"),
            (self.history_btn, "翻译历史", "shortcut_history"),
            (self.stats_btn, "使用统计", "shortcut_stats"),
            (self.mode_btn, "精简模式 / 普通模式", "shortcut_mode"),
        ]
        for btn, base, key in _btn_tooltip_mappings:
            b = sc.get(key, "")
            extra = f" ({format_binding(b)})" if b else ""
            update_tooltip(btn, base + extra)

    def _copy_result(self) -> None:
        """Copy result (raw markdown) to clipboard."""
        result = self.result_text.get_raw()
        if result and not result.startswith("错误:"):
            self.window.clipboard_clear()
            self.window.clipboard_append(result)
            self._set_status("已复制到剪贴板")
            self.window.after(2000, self._update_status_text)

    # ──────────────────────────────────────────────
    # Text-to-speech (read aloud)
    # ──────────────────────────────────────────────

    def _play_tts(self, category: str) -> None:
        """Play either 'words' (English words) or 'examples' (example sentences).

        The user clicks whichever they want to hear. Clicking the button that is
        currently playing stops it; the other button is disabled while speaking.
        """
        result = self.result_text.get_raw()
        if not result or result.startswith("错误:"):
            self._set_status("无可朗读内容", error=True)
            return

        # Clicking the active button again → stop.
        if self.tts_speaking and self._tts_mode == category:
            tts.stop()
            self._set_tts_buttons(None)
            return

        if category == "words":
            text = tts.extract_english_words(result)
            label, empty = "英文单词", "译文中没有可朗读的英文单词"
        else:
            text = tts.extract_english_sentences(result)
            label, empty = "示例句子", "译文中没有可朗读的示例句子"

        if not text:
            self._set_status(empty, error=True)
            return

        tts.speak(text)
        self._tts_mode = category
        self.tts_speaking = True
        self._set_tts_buttons(category)
        self._set_status(f"🔊 正在朗读{label}…")
        self._check_tts_done()

    def _set_tts_buttons(self, active: str | None) -> None:
        """Reflect TTS state on the two play buttons.

        *active* is "words", "examples", or None (idle). The active button shows
        a stop (⏹) look; the inactive one is disabled while something plays.
        """
        self.tts_speaking = active is not None
        self._tts_mode = active

        for cat, btn in (("words", self.tts_words_btn), ("examples", self.tts_examples_btn)):
            if cat == active:
                btn.configure(text="⏹", fg_color=("#f59e0b", "#b45309"),
                              hover_color=("#d97706", "#92400e"),
                              text_color=("white", "white"))
                add_tooltip(btn, "停止朗读")
            else:
                btn.configure(text="🔊" + ("单词" if cat == "words" else "例句"),
                              fg_color=SUBTLE, hover_color=SUBTLE_HOVER,
                              text_color=ICON_TEXT)
                add_tooltip(btn, "朗读" + ("英文单词" if cat == "words" else "示例句子"))
                if active is not None:
                    btn.configure(state="disabled")
                else:
                    btn.configure(state="normal")

    def _check_tts_done(self) -> None:
        """Poll until speech finishes, then revert the buttons."""
        if not tts.is_speaking():
            self._set_tts_buttons(None)
            self._update_status_text()
            return
        self.window.after(500, self._check_tts_done)

    # ──────────────────────────────────────────────
    # Run / Quit
    # ──────────────────────────────────────────────

    def run(self) -> None:
        """Start the main event loop."""
        self.window.mainloop()

    def quit(self) -> None:
        """Quit the application."""
        self._cancel_event.set()  # Signal any ongoing translation to stop
        tts.stop()
        self.window.quit()
        self.window.destroy()
