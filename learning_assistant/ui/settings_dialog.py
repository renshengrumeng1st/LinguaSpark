"""Focused settings dialog for model and learning preferences."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QFrame, QListWidget, QMessageBox, QPushButton, QScrollArea, QSpinBox, QStackedWidget,
    QVBoxLayout, QWidget,
)

from learning_assistant.core.settings import SettingsStore
from learning_assistant.services.autostart import AutostartError, AutostartService
from learning_assistant.services.selection import GlobalHotkeyService
from learning_assistant.ui.appearance_settings import AppearanceSettingsPage
from learning_assistant.ui.model_settings import ModelSettingsPage


class HotkeyEdit(QLineEdit):
    """Record exactly one shortcut chord in a predictable format."""

    def __init__(self, value: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setReadOnly(True)
        try:
            value = GlobalHotkeyService.format_binding(value)
        except ValueError:
            pass
        self.setText(value)
        self.setPlaceholderText("点击后按下组合键")
        self.setToolTip("支持 Ctrl、Alt、Shift、Win 与字母、数字或 F1–F24")

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key_Escape:
            self.clearFocus()
            return
        if key in (Qt.Key_Backspace, Qt.Key_Delete):
            self.clear()
            return
        if key in (
            Qt.Key_Control, Qt.Key_Alt, Qt.Key_Shift, Qt.Key_Meta,
        ):
            return
        key_name = ""
        if Qt.Key_A <= key <= Qt.Key_Z:
            key_name = chr(ord("A") + key - Qt.Key_A)
        elif Qt.Key_0 <= key <= Qt.Key_9:
            key_name = chr(ord("0") + key - Qt.Key_0)
        elif Qt.Key_F1 <= key <= Qt.Key_F24:
            key_name = f"F{key - Qt.Key_F1 + 1}"
        if not key_name:
            return
        modifiers = event.modifiers()
        parts: list[str] = []
        if modifiers & Qt.ControlModifier:
            parts.append("Ctrl")
        if modifiers & Qt.AltModifier:
            parts.append("Alt")
        if modifiers & Qt.ShiftModifier:
            parts.append("Shift")
        if modifiers & Qt.MetaModifier:
            parts.append("Win")
        parts.append(key_name)
        self.setText("+".join(parts))
        event.accept()


class SettingsDialog(QDialog):
    settings_changed = Signal()

    def __init__(
        self,
        settings: SettingsStore,
        parent=None,
        autostart: AutostartService | None = None,
    ):
        super().__init__(parent)
        self.settings = settings
        self.autostart = autostart or AutostartService()
        self.setWindowTitle("LinguaSpark · 设置")
        self.resize(1040, 760)
        self.setMinimumSize(940, 680)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("settingsSidebar")
        sidebar.setFixedWidth(190)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 26, 18, 22)
        side.setSpacing(16)
        mark = QLabel("✦")
        mark.setObjectName("brandMark")
        mark.setFixedSize(36, 36)
        mark.setAlignment(Qt.AlignCenter)
        side.addWidget(mark)
        brand = QLabel("LinguaSpark")
        brand.setObjectName("navBrand")
        side.addWidget(brand)
        tagline = QLabel("你的 AI 学习空间")
        tagline.setObjectName("muted")
        side.addWidget(tagline)
        side.addSpacing(16)
        self.navigation = QListWidget()
        self.navigation.setObjectName("settingsNavigation")
        self.navigation.addItems(["常规设置", "AI 模型", "外观与风格", "学习与发音", "快捷键"])
        side.addWidget(self.navigation, 1)
        side_note = QLabel("本机保存偏好\n让每次学习更顺手")
        side_note.setObjectName("muted")
        side.addWidget(side_note)
        layout.addWidget(sidebar)

        content = QWidget()
        content.setObjectName("settingsContent")
        root = QVBoxLayout(content)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(16)
        self.page_title = QLabel()
        self.page_title.setObjectName("pageTitle")
        self.page_subtitle = QLabel()
        self.page_subtitle.setObjectName("muted")
        self.page_subtitle.setWordWrap(True)
        root.addWidget(self.page_title)
        root.addWidget(self.page_subtitle)
        self.pages = QStackedWidget()
        self.model_page = ModelSettingsPage(settings)
        self.appearance_page = AppearanceSettingsPage(settings)
        self.model_page.settings_changed.connect(self.settings_changed)
        self.appearance_page.settings_changed.connect(self.settings_changed)
        self._page_titles = [
            ("常规设置", "安排启动与后台运行，让学习工具随时待命。"),
            ("AI 模型", "添加、编辑和验证模型连接，选择你的学习伙伴。"),
            ("外观与风格", "喜欢星光、夜色还是自然？这里都可以找到。"),
            ("学习与发音", "选择学习语言、发音方式和适合自己的学习节奏。"),
            ("快捷键", "设置窗口、划词翻译与 PDF 标记的常用按键。"),
        ]
        for page, card in ((self._general_tab(), True), (self.model_page, False),
                           (self.appearance_page, False), (self._learning_tab(), True),
                           (self._hotkeys_tab(), True)):
            self.pages.addWidget(self._scroll_page(page, card))
        root.addWidget(self.pages, 1)
        footer = QHBoxLayout()
        note = QLabel("配置与学习记录保存在当前 Windows 账户中。")
        note.setObjectName("muted")
        footer.addWidget(note, 1)
        close_button = QPushButton("完成")
        close_button.setObjectName("primary")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        root.addLayout(footer)
        layout.addWidget(content, 1)
        self.navigation.currentRowChanged.connect(self._navigate)
        self.navigation.setCurrentRow(1)
        self.finished.connect(lambda _result: self.model_page.cancel_connection())
        self.finished.connect(lambda _result: self.model_page.cancel_catalog())

    @staticmethod
    def _scroll_page(page: QWidget, card: bool) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        if card:
            frame = QFrame()
            frame.setObjectName("settingsCard")
            wrapper = QVBoxLayout(frame)
            wrapper.setContentsMargins(22, 22, 22, 22)
            page.layout().setContentsMargins(0, 0, 0, 0)
            page.layout().setSpacing(16)
            wrapper.addWidget(page)
            scroll.setWidget(frame)
        else:
            scroll.setWidget(page)
        return scroll

    def _navigate(self, index: int) -> None:
        if 0 <= index < len(self._page_titles):
            self.pages.setCurrentIndex(index)
            self.page_title.setText(self._page_titles[index][0])
            self.page_subtitle.setText(self._page_titles[index][1])


    def _general_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        self.autostart_checkbox = QCheckBox("开机时自动启动 LinguaSpark")
        try:
            self.autostart_checkbox.setChecked(self.autostart.is_enabled())
        except AutostartError as error:
            self.autostart_checkbox.setEnabled(False)
            initial_status = str(error)
        else:
            initial_status = "开机启动时将在后台驻留系统托盘，不弹出模式选择窗口。"
        root.addWidget(self.autostart_checkbox)
        hint = QLabel("使用当前 Windows 账户的启动设置，无需管理员权限。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.autostart_status = QLabel(initial_status)
        self.autostart_status.setObjectName("muted")
        self.autostart_status.setWordWrap(True)
        root.addWidget(self.autostart_status)
        actions = QHBoxLayout()
        save = QPushButton("保存常规设置")
        save.setObjectName("primary")
        save.clicked.connect(self._save_general)
        actions.addStretch(1)
        actions.addWidget(save)
        root.addLayout(actions)
        root.addStretch(1)
        return page

    def _save_general(self) -> None:
        requested = self.autostart_checkbox.isChecked()
        try:
            self.autostart.set_enabled(requested)
            actual = self.autostart.is_enabled()
        except AutostartError as error:
            try:
                self.autostart_checkbox.setChecked(self.autostart.is_enabled())
            except AutostartError:
                self.autostart_checkbox.setChecked(not requested)
            self.autostart_status.setText("未能更新开机自启设置。")
            QMessageBox.warning(self, "开机自启设置失败", str(error))
            return
        self.autostart_checkbox.setChecked(actual)
        self.autostart_status.setText("开机自启已开启。" if actual else "开机自启已关闭。")


    def _hotkeys_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        form = QFormLayout()
        self.window_hotkey = HotkeyEdit(
            str(self.settings.get("window_hotkey", "Alt+Q"))
        )
        self.selection_hotkey = HotkeyEdit(
            str(self.settings.get("selection_hotkey", "Alt+W"))
        )
        self.pdf_highlight_hotkey = HotkeyEdit(
            str(self.settings.get("pdf_highlight_hotkey", "Ctrl+H"))
        )
        self.pdf_remove_highlight_hotkey = HotkeyEdit(
            str(self.settings.get("pdf_remove_highlight_hotkey", "Ctrl+R"))
        )
        form.addRow("显示/隐藏窗口", self.window_hotkey)
        form.addRow("翻译选中文字", self.selection_hotkey)
        form.addRow("PDF 标记", self.pdf_highlight_hotkey)
        form.addRow("PDF 移除标记", self.pdf_remove_highlight_hotkey)
        root.addLayout(form)
        hint = QLabel(
            "点击输入框后，直接按下想使用的组合键。建议至少包含 Ctrl、Alt、Shift 或 Win，"
            "避免覆盖普通按键。打开设置期间，全局快捷键会暂时停用。"
            "PDF 标记快捷键仅在当前 PDF 标签中生效。"
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.hotkey_status = QLabel("")
        self.hotkey_status.setObjectName("muted")
        root.addWidget(self.hotkey_status)
        actions = QHBoxLayout()
        reset = QPushButton("恢复默认")
        reset.setObjectName("ghost")
        reset.clicked.connect(self._reset_hotkeys)
        save = QPushButton("保存快捷键")
        save.setObjectName("primary")
        save.clicked.connect(self._save_hotkeys)
        actions.addStretch(1)
        actions.addWidget(reset)
        actions.addWidget(save)
        root.addLayout(actions)
        root.addStretch(1)
        return page

    def _reset_hotkeys(self) -> None:
        self.window_hotkey.setText("Alt+Q")
        self.selection_hotkey.setText("Alt+W")
        self.pdf_highlight_hotkey.setText("Ctrl+H")
        self.pdf_remove_highlight_hotkey.setText("Ctrl+R")

    @staticmethod
    def _validated_hotkeys(
        window: str, selection: str,
        highlight: str = "Ctrl+H", remove_highlight: str = "Ctrl+R",
    ) -> dict[str, str]:
        values = {
            "window_hotkey": window.strip(),
            "selection_hotkey": selection.strip(),
            "pdf_highlight_hotkey": highlight.strip(),
            "pdf_remove_highlight_hotkey": remove_highlight.strip(),
        }
        if not all(values.values()):
            raise ValueError("快捷键都不能为空。")
        try:
            parsed = {
                name: GlobalHotkeyService._parse(value)
                for name, value in values.items()
            }
        except ValueError as exc:
            raise ValueError("快捷键只支持字母、数字或 F1–F24。") from exc
        for name, (modifiers, _) in parsed.items():
            key_part = values[name].replace("-", "+").split("+")[-1].strip().casefold()
            if modifiers == 0 and not (key_part.startswith("f") and key_part[1:].isdigit()):
                raise ValueError("字母或数字快捷键必须搭配 Ctrl、Alt、Shift 或 Win。")
        if len(set(parsed.values())) != len(parsed):
            raise ValueError("不同功能不能使用相同的快捷键。")
        return {
            name: GlobalHotkeyService.format_binding(value)
            for name, value in values.items()
        }

    def _save_hotkeys(self) -> None:
        try:
            values = self._validated_hotkeys(
                self.window_hotkey.text(), self.selection_hotkey.text(),
                self.pdf_highlight_hotkey.text(), self.pdf_remove_highlight_hotkey.text(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "快捷键不可用", str(exc))
            return
        for name, value in values.items():
            self.settings.set(name, value)
        self.settings.save()
        self.settings_changed.emit()
        self.hotkey_status.setText("已保存，关闭设置后立即生效。")

    def _learning_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.source_language = QComboBox()
        self.source_language.addItem("英语", "en")
        self.target_language = QComboBox()
        self.target_language.addItem("简体中文", "zh-CN")
        self.target_language.addItem("English", "en")
        self.explanation_language = QComboBox()
        self.explanation_language.addItem("简体中文", "zh-CN")
        self.explanation_language.addItem("English", "en")
        self.voice_locale = QComboBox()
        self.voice_locale.addItem("美式英语", "en-US")
        self.voice_locale.addItem("英式英语", "en-GB")
        self.tts_provider = QComboBox()
        self.tts_provider.addItem("Windows 本地语音（离线）", "sapi")
        self.tts_provider.addItem("Azure 神经语音（自然）", "azure")
        self.tts_rate = QSpinBox()
        self.tts_rate.setRange(-5, 5)
        self.tts_rate.setSuffix(" 语速")
        self.review_reminders = QCheckBox("有到期单词时，每天提醒一次")
        self.review_reminders.setChecked(bool(self.settings.get("review_reminders", True)))
        self.azure_region = QLineEdit()
        self.azure_region.setPlaceholderText("例如 eastasia")
        self.azure_key_edit = QLineEdit()
        self.azure_key_edit.setEchoMode(QLineEdit.Password)
        self.azure_key_edit.setPlaceholderText("Azure Speech Key")
        self.azure_voice = QComboBox()
        self.azure_voice.setEditable(True)
        self.azure_voice.addItem("Jenny · 美式女声", "en-US-JennyNeural")
        self.azure_voice.addItem("Guy · 美式男声", "en-US-GuyNeural")
        self.azure_voice.addItem("Sonia · 英式女声", "en-GB-SoniaNeural")
        self.azure_voice.addItem("Ryan · 英式男声", "en-GB-RyanNeural")
        languages = self.settings.languages()
        tts = dict(self.settings.get("tts", {}))
        self._set_combo(self.source_language, languages.source)
        self._set_combo(self.target_language, languages.target)
        self._set_combo(self.explanation_language, languages.explanation)
        self._set_combo(
            self.voice_locale,
            str(tts.get("voice_locale", "en-US")),
        )
        self._set_combo(self.tts_provider, str(tts.get("provider", "sapi")))
        self._set_combo(self.azure_voice, str(tts.get("azure_voice", "en-US-JennyNeural")))
        self.tts_rate.setValue(int(tts.get("rate", -1)))
        self.azure_region.setText(str(tts.get("azure_region", "")))
        self.azure_key_edit.setText(self.settings.azure_speech_key())
        form.addRow("学习语言", self.source_language)
        form.addRow("翻译语言", self.target_language)
        form.addRow("解释语言", self.explanation_language)
        form.addRow("发音口音", self.voice_locale)
        form.addRow("语音引擎", self.tts_provider)
        form.addRow("本地语速", self.tts_rate)
        form.addRow("复习提醒", self.review_reminders)
        form.addRow("Azure 区域", self.azure_region)
        form.addRow("Azure 密钥", self.azure_key_edit)
        form.addRow("神经声音", self.azure_voice)
        tts_hint = QLabel("神经语音音质更自然；密钥会通过当前 Windows 账户加密保存。未配置时可使用离线本地语音。")
        tts_hint.setObjectName("muted")
        tts_hint.setWordWrap(True)
        form.addRow("", tts_hint)
        save_button = QPushButton("保存学习设置")
        save_button.setObjectName("primary")
        save_button.clicked.connect(self._save_learning)
        form.addRow("", save_button)
        return page

    @staticmethod
    def _set_combo(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)


    def _save_learning(self) -> None:
        self.settings.set("languages", {
            "source": self.source_language.currentData(),
            "target": self.target_language.currentData(),
            "explanation": self.explanation_language.currentData(),
        })
        tts = dict(self.settings.get("tts", {}))
        tts["voice_locale"] = self.voice_locale.currentData()
        tts["provider"] = self.tts_provider.currentData()
        tts["rate"] = self.tts_rate.value()
        tts["azure_region"] = self.azure_region.text().strip()
        tts["azure_voice"] = self.azure_voice.currentData() or self.azure_voice.currentText().strip()
        self.settings.set("tts", tts)
        self.settings.set("review_reminders", self.review_reminders.isChecked())
        self.settings.set_azure_speech_key(self.azure_key_edit.text())
        self.settings.save()
        self.settings_changed.emit()
