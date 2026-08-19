"""History panel — displays translation history in a scrollable panel."""

import customtkinter as ctk
from typing import Callable, Optional
from utils.history import HistoryManager, HistoryEntry
from ui.tooltips import add_tooltip


class HistoryPanel(ctk.CTkFrame):
    """Scrollable list of past translations."""

    def __init__(
        self,
        parent,
        history_manager: HistoryManager,
        on_select: Optional[Callable[[HistoryEntry], None]] = None,
        **kwargs,
    ):
        super().__init__(parent, **kwargs)
        self.history_manager = history_manager
        self.on_select = on_select

        # Search bar
        self.search_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.search_frame.pack(fill="x", padx=8, pady=(8, 4))

        self.search_entry = ctk.CTkEntry(
            self.search_frame,
            placeholder_text="搜索历史记录...",
            height=28,
        )
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search_entry.bind("<KeyRelease>", self._on_search_key)

        self.clear_btn = ctk.CTkButton(
            self.search_frame,
            text="清空",
            width=50,
            height=28,
            fg_color="gray",
            command=self._clear_history,
        )
        self.clear_btn.pack(side="right", padx=(5, 0))

        # Scrollable area
        self.scroll_frame = ctk.CTkScrollableFrame(self, label_text="翻译历史")
        self.scroll_frame.pack(fill="both", expand=True, padx=4, pady=4)

        self._entry_widgets: list = []
        self._search_timer: str | None = None  # debounce timer id
        self.refresh()

    def refresh(self) -> None:
        """Reload and display all history entries."""
        # Clear existing widgets
        for widget in self._entry_widgets:
            widget.destroy()
        self._entry_widgets.clear()

        entries = self.history_manager.get_all()
        # Favorites pinned to the top (stable order within each group)
        entries = sorted(entries, key=lambda e: 0 if e.favorite else 1)

        if not entries:
            empty_label = ctk.CTkLabel(
                self.scroll_frame,
                text="暂无翻译历史",
                font=ctk.CTkFont(size=12),
                text_color="gray",
            )
            empty_label.pack(pady=20)
            self._entry_widgets.append(empty_label)
            return

        for entry in entries:
            self._create_entry_widget(entry)

    def _create_entry_widget(self, entry: HistoryEntry) -> None:
        """Create a clickable widget for a history entry."""
        frame = ctk.CTkFrame(self.scroll_frame, fg_color=("gray90", "gray20"))
        frame.pack(fill="x", padx=4, pady=2)
        self._entry_widgets.append(frame)

        # Time + model label
        header_frame = ctk.CTkFrame(frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=8, pady=(4, 0))

        time_label = ctk.CTkLabel(
            header_frame,
            text=entry.timestamp,
            font=ctk.CTkFont(size=10),
            text_color="gray",
        )
        time_label.pack(side="left")

        if entry.has_image:
            img_indicator = ctk.CTkLabel(
                header_frame,
                text="[图片]",
                font=ctk.CTkFont(size=10),
                text_color="blue",
            )
            img_indicator.pack(side="right")

        if entry.favorite:
            fav_mark = ctk.CTkLabel(
                header_frame, text="★",
                font=ctk.CTkFont(size=11),
                text_color=("#f59e0b", "#fbbf24"),
            )
            fav_mark.pack(side="right", padx=(0, 4))

        # Source text preview
        source_preview = entry.source_text[:80].replace("\n", " ")
        if len(entry.source_text) > 80:
            source_preview += "..."

        source_label = ctk.CTkLabel(
            frame,
            text=source_preview,
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
            wraplength=300,
        )
        source_label.pack(fill="x", padx=8, pady=(2, 0))
        source_label.bind("<Enter>", lambda e: source_label.configure(cursor="hand2"))
        source_label.bind("<Leave>", lambda e: source_label.configure(cursor=""))

        # Result text preview
        result_preview = entry.result_text[:80].replace("\n", " ")
        if len(entry.result_text) > 80:
            result_preview += "..."

        result_label = ctk.CTkLabel(
            frame,
            text=result_preview,
            font=ctk.CTkFont(size=11),
            anchor="w",
            wraplength=300,
            text_color="gray",
        )
        result_label.pack(fill="x", padx=8, pady=(0, 4))
        result_label.bind("<Enter>", lambda e: result_label.configure(cursor="hand2"))
        result_label.bind("<Leave>", lambda e: result_label.configure(cursor=""))

        # Action buttons (favorite + delete) on the right
        actions = ctk.CTkFrame(frame, fg_color="transparent")
        actions.pack(fill="x", padx=8, pady=(0, 4))

        fav_btn = ctk.CTkButton(
            actions, text="★" if entry.favorite else "☆",
            width=34, height=24, fg_color="transparent",
            text_color=("#f59e0b", "#fbbf24") if entry.favorite else ("gray", "gray"),
            hover_color=("gray85", "gray30"),
            font=ctk.CTkFont(size=12),
            command=lambda e=entry: self._toggle_fav(e),
        )
        fav_btn.pack(side="right", padx=(4, 0))
        add_tooltip(fav_btn, "收藏 / 取消收藏")

        del_btn = ctk.CTkButton(
            actions, text="🗑", width=34, height=24,
            fg_color="transparent", text_color=("gray", "gray"),
            hover_color=("gray85", "gray30"),
            font=ctk.CTkFont(size=12),
            command=lambda e=entry: self._delete_entry(e),
        )
        del_btn.pack(side="right")
        add_tooltip(del_btn, "删除这条记录")

        # Make the text area clickable to load into the main window
        if self.on_select:
            for widget in (header_frame, source_label, result_label):
                widget.bind("<Button-1>", lambda e, ent=entry: self.on_select(ent))

    def _on_search_key(self, event=None) -> None:
        """KeyRelease handler — debounce to avoid rebuilding on every keystroke."""
        if self._search_timer is not None:
            self.after_cancel(self._search_timer)
        self._search_timer = self.after(250, self._on_search)

    def _toggle_fav(self, entry: HistoryEntry) -> None:
        """Toggle the favorite flag and re-render (favorites sort to top)."""
        self.history_manager.toggle_favorite(entry)
        self.refresh()

    def _delete_entry(self, entry: HistoryEntry) -> None:
        """Remove a single history entry and re-render."""
        self.history_manager.delete_entry(entry)
        self.refresh()

    def _on_search(self) -> None:
        """Filter entries based on search keyword (called after debounce)."""
        self._search_timer = None
        keyword = self.search_entry.get().strip()
        if not keyword:
            self.refresh()
            return

        # Clear current display
        for widget in self._entry_widgets:
            widget.destroy()
        self._entry_widgets.clear()

        results = self.history_manager.search(keyword)
        for entry in results:
            self._create_entry_widget(entry)

    def _clear_history(self) -> None:
        """Clear all history after confirmation."""
        # Simple confirmation dialog
        dialog = ctk.CTkToplevel(self)
        dialog.title("确认清空")
        dialog.geometry("300x130")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, text="确定要清空所有翻译历史吗？",
            font=ctk.CTkFont(size=13),
        ).pack(pady=(20, 15))

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack()

        def _do_clear():
            self.history_manager.clear()
            self.refresh()
            dialog.destroy()

        ctk.CTkButton(
            btn_frame, text="确定", width=80, fg_color="red", hover_color="darkred",
            command=_do_clear,
        ).pack(side="left", padx=10)

        ctk.CTkButton(
            btn_frame, text="取消", width=80, fg_color="gray",
            command=dialog.destroy,
        ).pack(side="left", padx=10)

        # Center dialog
        dialog.update_idletasks()
        p = self.winfo_toplevel()
        x = p.winfo_x() + (p.winfo_width() // 2) - 150
        y = p.winfo_y() + (p.winfo_height() // 2) - 65
        dialog.geometry(f"300x130+{x}+{y}")
