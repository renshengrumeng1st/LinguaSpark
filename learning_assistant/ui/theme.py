"""Shared visual styles and live application palette switching."""
from __future__ import annotations

from dataclasses import dataclass
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Theme:
    name: str
    subtitle: str
    background: str
    surface: str
    soft: str
    sidebar: str
    text: str
    muted: str
    line: str
    accent: str
    hover: str
    tint: str
    banner_start: str
    banner_end: str
    success: str
    error: str


THEMES = {
    "sakura": Theme("星樱", "樱粉与星光 · 轻二次元", "#f8f5fc", "#ffffff", "#f3eef9", "#f1ebf7",
                    "#302944", "#80758f", "#e8e0f0", "#9461c7", "#7c4eae", "#eee3fb",
                    "#fff0f6", "#eeeaff", "#348568", "#bf4d69"),
    "dark": Theme("夜航", "紫蓝夜色 · 专注工作室", "#151922", "#202632", "#292f3e", "#191e29",
                  "#e8eaf2", "#9ba7bc", "#353e50", "#8c9bff", "#7486ee", "#303858",
                  "#262c48", "#252438", "#79d9b2", "#ffa1b1"),
    "light": Theme("晴空", "干净留白 · 轻快日常", "#f4f7fc", "#ffffff", "#eef2f8", "#edf2fa",
                   "#23334e", "#79869b", "#dfe7f2", "#426de2", "#3159ca", "#e5edff",
                   "#edf4ff", "#e9efff", "#2f866b", "#c45465"),
    "forest": Theme("松林", "柔绿暖纸 · 自然护眼", "#f0f3eb", "#fcfdf8", "#e9efe4", "#e7ede1",
                    "#2b4035", "#788571", "#dce4d4", "#4d7b5e", "#3c644c", "#e0eddc",
                    "#e9f1e1", "#f6efdf", "#367951", "#b75a59"),
    "nahida": Theme("净善花园 · 纳西妲", "嫩绿与金叶 · 知识的花园", "#f3f6eb", "#ffffff", "#edf2e1", "#e8efdc",
                    "#30452d", "#758369", "#dce6cb", "#668e45", "#507436", "#e7f0d6",
                    "#edf6de", "#fbf4d9", "#39794e", "#b95e66"),
    "furina": Theme("沫蓝舞台 · 芙宁娜", "海蓝与银白 · 水上的圆舞曲", "#f1f5fc", "#ffffff", "#eaf0fb", "#e4ecfa",
                    "#263954", "#7385a0", "#d7e2f5", "#527bc5", "#3f62a7", "#e1eaff",
                    "#e5efff", "#f0edff", "#34866c", "#bd5a79"),
    "raiden": Theme("紫电永恒 · 雷电将军", "堇紫与微光 · 静谧的夜读", "#201a2d", "#2d253f", "#372d4b", "#251e34",
                    "#eee6f8", "#b2a1c9", "#4b3c62", "#b69ade", "#9d7cc9", "#48385f",
                    "#39284d", "#28243d", "#8cd8b6", "#f2a5be"),
}


def stylesheet_for_theme(theme_id: str = "sakura") -> str:
    t = THEMES.get(theme_id, THEMES["sakura"])
    return f"""
    QWidget {{ font-family: "Segoe UI", "Microsoft YaHei UI"; font-size: 14px; color: {t.text}; }}
    QMainWindow, QDialog, QWidget#settingsContent, QWidget#pdfWorkspace {{ background: {t.background}; }}
    QFrame#card, QFrame#settingsCard, QFrame#modelEditorCard {{
        background: {t.surface}; border: 1px solid {t.line}; border-radius: 16px;
    }}
    QLabel#title, QLabel#pdfTitle {{ font-size: 21px; font-weight: 700; }}
    QLabel#word {{ font-size: 30px; font-weight: 700; }}
    QLabel#muted, QLabel#chooserSubtitle, QLabel#pdfStatus {{ color: {t.muted}; font-size: 12px; }}
    QLabel#section, QLabel#phonetic {{ color: {t.muted}; font-size: 13px; }}
    QLabel#section {{ font-weight: 600; }}
    QLabel#eyebrow {{ color: {t.accent}; font-size: 11px; font-weight: 700; }}
    QLabel#pageTitle {{ font-size: 26px; font-weight: 700; }}
    QLabel#cardTitle {{ font-size: 17px; font-weight: 650; }}
    QLabel#modelName {{ font-size: 14px; font-weight: 650; }}
    QLabel#badge {{ background: {t.tint}; color: {t.accent}; border-radius: 6px; padding: 4px 8px; font-size: 11px; }}
    QLabel#brandMark {{ background: {t.accent}; color: white; border-radius: 13px; font-size: 25px; font-weight: 700; }}
    QLabel#navBrand {{ font-size: 19px; font-weight: 700; }}
    QFrame#settingsSidebar {{ background: {t.sidebar}; border-right: 1px solid {t.line}; }}
    QListWidget#settingsNavigation {{ background: transparent; border: none; padding: 0; outline: 0; }}
    QListWidget#settingsNavigation::item {{ padding: 12px 14px; margin: 3px 0; border-radius: 10px; color: {t.muted}; }}
    QListWidget#settingsNavigation::item:selected {{ background: {t.tint}; color: {t.accent}; font-weight: 650; }}
    QListWidget#settingsNavigation::item:hover {{ background: {t.soft}; }}
    QFrame#settingsHero {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {t.banner_start},stop:1 {t.banner_end});
        border: 1px solid {t.line}; border-radius: 15px;
    }}
    QLabel#heroSpark {{ color: {t.accent}; font-size: 36px; }}
    QFrame#themeCard {{ background: {t.surface}; border: 1px solid {t.line}; border-radius: 14px; }}
    QFrame#themeCard[chosen="true"] {{ border: 2px solid {t.accent}; }}
    QPushButton, QToolButton {{ background: {t.soft}; border: 1px solid {t.line}; border-radius: 9px; padding: 8px 12px; }}
    QPushButton:hover, QToolButton:hover {{ background: {t.tint}; border-color: {t.accent}; }}
    QPushButton#primary {{ background: {t.accent}; color: {'#201a2d' if theme_id in ('dark', 'raiden') else 'white'};
        border: 1px solid {t.accent}; font-weight: 650; padding: 9px 17px; }}
    QPushButton#primary:hover {{ background: {t.hover}; }}
    QPushButton#ghost {{ background: transparent; border: 1px solid transparent; color: {t.muted}; padding: 7px 9px; }}
    QPushButton#ghost:hover {{ background: {t.tint}; color: {t.accent}; }}
    QPushButton#danger {{ background: transparent; border-color: {t.line}; color: {t.error}; }}
    QPushButton:disabled, QToolButton:disabled {{ color: {t.muted}; background: {t.soft}; border-color: {t.line}; }}
    QLineEdit, QComboBox, QSpinBox {{ background: {t.surface}; border: 1px solid {t.line};
        border-radius: 9px; padding: 9px 11px; min-height: 20px; selection-background-color: {t.tint}; selection-color: {t.text}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {t.accent}; }}
    QComboBox QAbstractItemView {{ background: {t.surface}; color: {t.text}; selection-background-color: {t.tint}; selection-color: {t.text}; }}
    QComboBox::drop-down {{ border: none; width: 22px; margin-right: 7px; }}
    QComboBox#modelIdCombo {{ padding-right: 11px; }}
    QComboBox#modelIdCombo::drop-down {{ width: 0px; margin: 0px; border: none; }}
    QToolButton#modelDropdownButton {{ background: {t.tint}; border-color: {t.accent}; color: {t.accent}; }}
    QToolButton#modelDropdownButton:hover {{ background: {t.soft}; }}
    QToolButton#modelDropdownButton:disabled {{ background: {t.soft}; border-color: {t.line}; color: {t.muted}; }}
    QTextBrowser {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.line}; border-radius: 12px; padding: 16px; selection-background-color: {t.tint}; selection-color: {t.text}; }}
    QListWidget {{ background: {t.surface}; border: 1px solid {t.line}; border-radius: 12px; padding: 5px; outline: 0; }}
    QListWidget::item {{ padding: 10px; margin: 2px 0; border-radius: 8px; }}
    QListWidget::item:selected {{ background: {t.tint}; color: {t.accent}; }}
    QListWidget::item:hover {{ background: {t.soft}; }}
    QPlainTextEdit {{ border: none; background: transparent; font-size: 17px; selection-background-color: {t.tint}; selection-color: {t.text}; }}
    QScrollArea, QStackedWidget {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ width: 7px; background: transparent; }}
    QScrollBar::handle:vertical {{ background: {t.line}; border-radius: 3px; min-height: 30px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QCheckBox, QRadioButton {{ spacing: 8px; }}
    QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 8px; border: 1px solid {t.muted}; background: {t.surface}; }}
    QRadioButton::indicator:checked {{ background: {t.accent}; border: 3px solid {t.tint}; }}
    QLabel#connectionStatus {{ border-radius: 9px; padding: 10px 12px; color: {t.muted}; background: {t.soft}; }}
    QLabel#connectionStatus[state="success"] {{ color: {t.success}; background: {t.soft}; }}
    QLabel#connectionStatus[state="error"] {{ color: {t.error}; background: {t.soft}; }}
    QLabel#formStatus {{ color: {t.muted}; }}
    QLabel#formStatus[state="error"] {{ color: {t.error}; }}
    QPushButton#modeCard {{ background: {t.surface}; border: 1px solid {t.line}; border-radius: 16px;
        padding: 20px 16px; font-size: 16px; font-weight: 600; text-align: center; }}
    QPushButton#modeCard:hover {{ background: {t.tint}; border-color: {t.accent}; }}
    QLabel#chooserTitle, QLabel#emptyTitle {{ font-size: 24px; font-weight: 700; }}
    QTabWidget::pane {{ border: 1px solid {t.line}; border-radius: 8px; }}
    QTabBar::tab {{ background: {t.soft}; color: {t.muted}; padding: 10px 16px; border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ background: {t.surface}; color: {t.accent}; border-bottom-color: {t.accent}; }}
    QMenu {{ background: {t.surface}; border: 1px solid {t.line}; padding: 5px; }}
    QMenu::item {{ padding: 8px 18px; border-radius: 5px; }}
    QMenu::item:selected {{ background: {t.tint}; }}
    QToolTip {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.line}; padding: 6px; }}
    """


def apply_app_theme(theme_id: str = "sakura") -> None:
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        raise RuntimeError("Application theme requires QApplication")
    theme_id = theme_id if theme_id in THEMES else "sakura"
    t = THEMES[theme_id]
    if not app.property("linguasparkTheme"):
        app.setStyle("Fusion")
    palette = QPalette()
    for role, color in {
        QPalette.Window: t.background, QPalette.WindowText: t.text,
        QPalette.Base: t.surface, QPalette.AlternateBase: t.soft,
        QPalette.Text: t.text, QPalette.Button: t.soft, QPalette.ButtonText: t.text,
        QPalette.ToolTipBase: t.surface, QPalette.ToolTipText: t.text,
        QPalette.Highlight: t.accent, QPalette.HighlightedText: "#ffffff",
        QPalette.Link: t.accent, QPalette.BrightText: t.error,
    }.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor(t.muted))
    app.setPalette(palette)
    app.setStyleSheet(stylesheet_for_theme(theme_id))
    app.setProperty("linguasparkTheme", theme_id)


APP_QSS = stylesheet_for_theme()
