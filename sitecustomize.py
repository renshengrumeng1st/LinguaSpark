"""Prepare the Windows Qt runtime before pytest-qt imports PySide6.

Python's :mod:`site` module imports this file automatically when commands are
run from the project directory.  The package import performs only the small
stdlib-based ICU bootstrap; it does not start the application.
"""

try:
    import learning_assistant  # noqa: F401
except Exception:
    pass

