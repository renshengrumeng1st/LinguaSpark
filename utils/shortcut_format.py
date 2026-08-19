"""Shortcut binding display formatting — shared by UI modules.

Converts tkinter binding strings (e.g. ``"<Control-Return>"``) into
human-readable display labels (e.g. ``"Ctrl+Enter"``).
"""

# Maps tkinter keysym names to user-friendly display names
_DISPLAY_MAP = {
    "Control": "Ctrl",
    "Ctrl": "Ctrl",
    "Alt": "Alt",
    "Shift": "Shift",
    "Meta": "Meta",
    "Return": "Enter",
    "space": "Space",
    "Tab": "Tab",
}


def format_binding(binding: str) -> str:
    """Convert a tkinter binding string to a display-friendly label.

    Examples::

        "<Control-Return>"    → "Ctrl+Enter"
        "<Control-Shift-A>"   → "Ctrl+Shift+A"
        "<Alt-F4>"            → "Alt+F4"
        "<F1>"                → "F1"
    """
    s = binding.strip("<>")
    parts = s.split("-")
    return "+".join(_DISPLAY_MAP.get(p, p) for p in parts)
