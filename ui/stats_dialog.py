"""Usage statistics dialog — displays translation usage summary.

Extracted from MainWindow to reduce main_window.py size and improve
separation of concerns.
"""

import customtkinter as ctk

from utils.usage_stats import UsageStats
from utils.translation_cache import TranslationCache


def show_stats_dialog(parent, stats: UsageStats, cache: TranslationCache) -> None:
    """Open a modal statistics dialog centered on the parent window.

    Args:
        parent: The parent CTk window (used for centering and transience).
        stats: UsageStats instance providing the summary data.
        cache: TranslationCache instance (for displaying cache size).
    """
    summary = stats.get_summary()

    dialog = ctk.CTkToplevel(parent)
    dialog.title("使用统计")
    dialog.geometry("380x400")
    dialog.resizable(False, False)
    dialog.transient(parent)

    frame = ctk.CTkFrame(dialog)
    frame.pack(fill="both", expand=True, padx=15, pady=15)

    ctk.CTkLabel(
        frame, text="📊 使用统计",
        font=ctk.CTkFont(size=16, weight="bold"),
    ).pack(pady=(0, 10))

    stats_text = (
        f"总翻译次数：{summary['total_translations']}\n"
        f"总字符数：{summary['total_characters']:,}\n"
        f"文本翻译：{summary['text_translations']}\n"
        f"图片翻译：{summary['image_translations']}\n"
        f"缓存命中（节省）：{summary['cache_hits']}\n"
        f"\n"
        f"今日翻译：{summary['today']['count']}\n"
        f"今日字符：{summary['today']['chars']:,}\n"
        f"今日预估花费：¥{summary['today']['cost']:.4f}\n"
        f"\n"
        f"本月翻译：{summary['month']['count']}\n"
        f"本月字符：{summary['month']['chars']:,}\n"
        f"本月预估花费：¥{summary['month']['cost']:.4f}"
    )

    ctk.CTkLabel(
        frame, text=stats_text,
        font=ctk.CTkFont(size=12),
        justify="left",
    ).pack(pady=5)

    cache_info = f"翻译记忆：{cache.size} 条缓存"
    ctk.CTkLabel(
        frame, text=cache_info,
        font=ctk.CTkFont(size=11), text_color="gray",
    ).pack(pady=(5, 0))

    ctk.CTkButton(
        frame, text="关闭", width=100,
        command=dialog.destroy,
    ).pack(pady=(15, 0))

    _center_dialog(dialog, parent, 380, 400)


def _center_dialog(dialog, parent, width: int, height: int) -> None:
    """Center *dialog* on the parent window."""
    dialog.update_idletasks()
    x = parent.winfo_x() + (parent.winfo_width() // 2) - (width // 2)
    y = parent.winfo_y() + (parent.winfo_height() // 2) - (height // 2)
    dialog.geometry(f"{width}x{height}+{x}+{y}")
