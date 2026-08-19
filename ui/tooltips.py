"""Lightweight hover tooltip for tkinter / customtkinter widgets.

A tooltip appears 600 ms after the mouse enters a widget and disappears
when the mouse leaves or the widget is clicked.  Uses tkinter's Toplevel
so it works regardless of customtkinter version.
"""

import tkinter as tk
from typing import Optional


def add_tooltip(widget, text: str) -> None:
    """Attach a hover tooltip to *widget*.

    The tooltip appears 600 ms after the mouse enters the widget and
    disappears when the mouse leaves or the widget is clicked.
    """
    tooltip_window: Optional[tk.Toplevel] = None
    after_id: Optional[str] = None

    def _show(event=None):
        nonlocal tooltip_window, after_id
        if after_id:
            try:
                widget.after_cancel(after_id)
            except Exception:
                after_id = None
        after_id = widget.after(600, _do_show)

    def _do_show():
        nonlocal tooltip_window, after_id
        after_id = None
        if tooltip_window:
            return
        x = widget.winfo_rootx() + widget.winfo_width() // 2
        y = widget.winfo_rooty() + widget.winfo_height() + 4
        tooltip_window = tw = tk.Toplevel(widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)
        label = tk.Label(
            tw, text=text,
            font=("Microsoft YaHei UI", 10),
            bg="#2b2b2b", fg="white",
            padx=8, pady=4,
            borderwidth=1, relief="solid",
        )
        label.pack()

    def _hide(event=None):
        nonlocal tooltip_window, after_id
        if after_id:
            try:
                widget.after_cancel(after_id)
            except Exception:
                pass
            after_id = None
        if tooltip_window:
            try:
                tooltip_window.destroy()
            except Exception:
                pass
            tooltip_window = None

    widget.bind("<Enter>", _show, add="+")
    widget.bind("<Leave>", _hide, add="+")
    widget.bind("<ButtonPress>", _hide, add="+")


def update_tooltip(widget, text: str) -> None:
    """Replace the tooltip text on a widget that was created with add_tooltip."""
    widget.unbind("<Enter>")
    widget.unbind("<Leave>")
    widget.unbind("<ButtonPress>")
    add_tooltip(widget, text)
