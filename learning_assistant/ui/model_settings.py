"""Model library, explicit drafts, and asynchronous connection feedback."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from learning_assistant.core.settings import SettingsStore
from learning_assistant.domain.models import ModelProfile
from learning_assistant.services.model_connection import ModelCatalogFetcher, ModelConnectionTester
from learning_assistant.services.model_providers import PROVIDER_PRESETS, normalize_base_url


def label(text: str, name: str = "muted") -> QLabel:
    widget = QLabel(text)
    widget.setObjectName(name)
    widget.setWordWrap(True)
    return widget


class ModelSettingsPage(QWidget):
    settings_changed = Signal()

    def __init__(self, settings: SettingsStore, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._editing_id: str | None = None
        self._loading = False
        self._connection_id: int | None = None
        self.connection_tester = ModelConnectionTester(self)
        self.connection_tester.finished.connect(self._connection_finished)
        self.catalog_fetcher = ModelCatalogFetcher(self)
        self.catalog_fetcher.finished.connect(self._catalog_finished)
        self._catalog_id: int | None = None
        self._catalog_timer = QTimer(self)
        self._catalog_timer.setSingleShot(True)
        self._catalog_timer.setInterval(800)
        self._catalog_timer.timeout.connect(self._auto_fetch_models)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        hero = QFrame()
        hero.setObjectName("settingsHero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(18, 14, 18, 14)
        hero_text = QVBoxLayout()
        hero_text.setSpacing(4)
        hero_text.addWidget(label("连接你的 AI 学习伙伴", "cardTitle"))
        hero_text.addWidget(label("管理模型、验证连接，再选择适合自己的学习搭档。"))
        hero_layout.addLayout(hero_text, 1)
        hero_layout.addWidget(label("✦", "heroSpark"))
        root.addWidget(hero)

        body = QHBoxLayout()
        body.setSpacing(16)
        library = QFrame()
        library.setObjectName("settingsCard")
        library.setMinimumWidth(210)
        library.setMaximumWidth(260)
        left = QVBoxLayout(library)
        left.setContentsMargins(14, 16, 14, 14)
        heading = QHBoxLayout()
        self.model_count = label("模型库", "cardTitle")
        heading.addWidget(self.model_count, 1)
        self.add_model_button = QPushButton("＋ 添加")
        self.add_model_button.setObjectName("primary")
        self.add_model_button.clicked.connect(self.new_model)
        heading.addWidget(self.add_model_button)
        left.addLayout(heading)
        self.model_list = QListWidget()
        self.model_list.setObjectName("modelLibrary")
        self.model_list.currentItemChanged.connect(self._load_selected)
        left.addWidget(self.model_list, 1)
        self.empty_hint = label("还没有模型\n\n点击“添加”，创建你的第一个连接。")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        left.addWidget(self.empty_hint, 1)
        self.select_model_button = QPushButton("设为当前模型")
        self.select_model_button.clicked.connect(self._select_model)
        self.remove_model_button = QPushButton("删除")
        self.remove_model_button.setObjectName("danger")
        self.remove_model_button.clicked.connect(self._remove_model)
        left.addWidget(self.select_model_button)
        left.addWidget(self.remove_model_button)
        body.addWidget(library)

        editor = QFrame()
        editor.setObjectName("modelEditorCard")
        right = QVBoxLayout(editor)
        right.setContentsMargins(22, 20, 22, 20)
        right.setSpacing(14)
        editor_header = QHBoxLayout()
        self.editor_title = label("添加模型", "cardTitle")
        editor_header.addWidget(self.editor_title, 1)
        self.active_badge = label("未保存", "badge")
        editor_header.addWidget(self.active_badge)
        right.addLayout(editor_header)
        right.addWidget(label("填写服务商提供的连接信息。测试可以直接使用未保存的配置。"))
        form = QFormLayout()
        form.setSpacing(14)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.provider_combo = QComboBox()
        self.provider_combo.addItem("自定义 / OpenAI 兼容服务", "")
        for preset in PROVIDER_PRESETS:
            self.provider_combo.addItem(preset.name, preset.base_url)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如：日常翻译、深度阅读")
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://api.example.com/v1")
        self.url_edit.setToolTip("填写服务商的 Base URL，不需要附加 /chat/completions。")
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("输入 API Key")
        key_row = QHBoxLayout()
        key_row.setSpacing(7)
        key_row.addWidget(self.key_edit, 1)
        self.show_key_button = QToolButton()
        self.show_key_button.setText("显示")
        self.show_key_button.setCheckable(True)
        self.show_key_button.toggled.connect(self._show_key)
        key_row.addWidget(self.show_key_button)
        self.model_combo = QComboBox()
        self.model_combo.setObjectName("modelIdCombo")
        self.model_combo.setEditable(True)
        self.model_combo.setInsertPolicy(QComboBox.NoInsert)
        self.model_combo.completer().setFilterMode(Qt.MatchContains)
        self.model_combo.completer().setCaseSensitivity(Qt.CaseInsensitive)
        self.model_edit = self.model_combo.lineEdit()
        self.model_edit.setPlaceholderText("服务商提供的模型 ID")
        model_row = QHBoxLayout()
        model_row.addWidget(self.model_combo, 1)
        self.model_dropdown_button = QToolButton()
        self.model_dropdown_button.setObjectName("modelDropdownButton")
        self.model_dropdown_button.setArrowType(Qt.DownArrow)
        self.model_dropdown_button.setFixedWidth(42)
        self.model_dropdown_button.setToolTip("展开可用模型列表；请先填写地址和密钥获取模型。")
        self.model_dropdown_button.setAccessibleName("选择可用模型")
        self.model_dropdown_button.setEnabled(False)
        self.model_dropdown_button.clicked.connect(self.model_combo.showPopup)
        model_row.addWidget(self.model_dropdown_button)
        self.fetch_models_button = QPushButton("获取模型")
        self.fetch_models_button.clicked.connect(self._fetch_models)
        model_row.addWidget(self.fetch_models_button)
        self.output_tokens_spin = QSpinBox()
        self.output_tokens_spin.setRange(256, 131072)
        self.output_tokens_spin.setSingleStep(1024)
        self.output_tokens_spin.setValue(4096)
        self.output_tokens_spin.setToolTip("单次请求的最大输出 token 数，部分模型的思考也占用此预算。上限越大不代表实际用量越大。")
        form.addRow("模型厂商", self.provider_combo)
        form.addRow("显示名称", self.name_edit)
        form.addRow("服务地址", self.url_edit)
        form.addRow("API Key", key_row)
        form.addRow("模型 ID", model_row)
        form.addRow("输出预算（tokens）", self.output_tokens_spin)
        right.addLayout(form)
        self.catalog_status = label("填写地址和密钥后自动获取模型，也可手动输入模型 ID。", "connectionStatus")
        self.catalog_status.setTextFormat(Qt.PlainText)
        right.addWidget(self.catalog_status)
        right.addWidget(label("密钥仅保存在本机，并使用当前 Windows 账户加密保护。"))
        self.form_status = label("", "formStatus")
        right.addWidget(self.form_status)
        right.addStretch(1)
        actions = QHBoxLayout()
        self.test_connection_button = QPushButton("测试连通性")
        self.test_connection_button.setToolTip("向当前表单中的模型发送一条简短测试请求，可能产生少量用量。")
        self.test_connection_button.clicked.connect(self._test_connection)
        self.save_model_button = QPushButton("保存模型")
        self.save_model_button.setObjectName("primary")
        self.save_model_button.clicked.connect(self._save_model)
        actions.addWidget(self.test_connection_button)
        actions.addStretch(1)
        actions.addWidget(self.save_model_button)
        right.addLayout(actions)
        self.connection_status = label("填写配置后，可测试模型是否可用。", "connectionStatus")
        self.connection_status.setTextFormat(Qt.PlainText)
        right.addWidget(self.connection_status)
        body.addWidget(editor, 1)
        root.addLayout(body, 1)
        for edit in (self.name_edit, self.url_edit, self.key_edit, self.model_edit):
            edit.textChanged.connect(self._form_changed)
        for edit in (self.url_edit, self.key_edit):
            edit.textChanged.connect(self._catalog_input_changed)
        self.output_tokens_spin.valueChanged.connect(self._form_changed)
        self.provider_combo.currentIndexChanged.connect(self._provider_changed)
        self._refresh_models()

    @staticmethod
    def _status(widget: QLabel, text: str, state: str = "idle") -> None:
        widget.setText(text)
        widget.setProperty("state", state)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def cancel_connection(self, message: str = "填写配置后，可测试模型是否可用。") -> None:
        self._connection_id = None
        self.connection_tester.cancel()
        self.test_connection_button.setText("测试连通性")
        self._status(self.connection_status, message)

    def _form_changed(self) -> None:
        if not self._loading:
            self.cancel_connection("配置已更改，点击“测试连通性”重新验证。")
            self._status(self.form_status, "")

    def _show_key(self, checked: bool) -> None:
        self.key_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        self.show_key_button.setText("隐藏" if checked else "显示")

    def _provider_changed(self) -> None:
        if self._loading:
            return
        # A provider change must never send the previous provider's key.
        self._loading = True
        self.key_edit.clear()
        self.model_edit.clear()
        self.url_edit.setText(self.provider_combo.currentData() or "")
        self._loading = False
        self._form_changed()
        self._catalog_input_changed()

    def cancel_catalog(self) -> None:
        self._catalog_timer.stop()
        self._catalog_id = None
        self.catalog_fetcher.cancel()
        self.fetch_models_button.setText("获取模型")
        self._status(self.catalog_status, "填写地址和密钥后自动获取模型，也可手动输入模型 ID。")

    def _clear_catalog(self) -> None:
        text = self.model_edit.text()
        self.model_combo.blockSignals(True)
        self.model_edit.blockSignals(True)
        self.model_combo.clear()
        self.model_dropdown_button.setEnabled(False)
        self.model_edit.setText(text)
        self.model_edit.blockSignals(False)
        self.model_combo.blockSignals(False)

    def _catalog_input_changed(self) -> None:
        if self._loading:
            return
        self.cancel_catalog()
        self._clear_catalog()
        self._sync_provider()
        try:
            self._catalog_profile()
        except ValueError:
            return
        self._catalog_timer.start()

    def _sync_provider(self) -> None:
        try:
            url = normalize_base_url(self.url_edit.text())
        except ValueError:
            url = ""
        index = next((i + 1 for i, preset in enumerate(PROVIDER_PRESETS)
                      if normalize_base_url(preset.base_url) == url), 0)
        self.provider_combo.blockSignals(True)
        self.provider_combo.setCurrentIndex(index)
        self.provider_combo.blockSignals(False)

    def _catalog_profile(self) -> ModelProfile:
        profile = ModelProfile("", "", self.url_edit.text().strip(), "", self.key_edit.text().strip())
        ModelConnectionTester.validate(profile, require_model=False)
        return profile

    def _auto_fetch_models(self) -> None:
        try:
            self._catalog_profile()
        except ValueError:
            return
        self._fetch_models()

    def _fetch_models(self) -> None:
        self._catalog_timer.stop()
        if self._catalog_id is not None:
            self.cancel_catalog()
            return
        try:
            profile = self._catalog_profile()
        except ValueError as error:
            self._status(self.catalog_status, str(error), "error")
            return
        self._catalog_id = self.catalog_fetcher.start(profile)
        self.fetch_models_button.setText("取消获取")
        self._status(self.catalog_status, "正在获取可用模型…", "pending")

    def _catalog_finished(self, request_id: int, success: bool, models: list[str], message: str) -> None:
        if request_id != self._catalog_id:
            return
        self._catalog_id = None
        self.fetch_models_button.setText("刷新模型")
        if success:
            text = self.model_edit.text()
            self._loading = True
            self.model_combo.clear()
            self.model_combo.addItems(models)
            self.model_edit.setText(text)
            self.model_dropdown_button.setEnabled(bool(models))
            self._loading = False
        self._status(self.catalog_status, message, "success" if success else "error")

    def _selected_profile(self) -> ModelProfile | None:
        item = self.model_list.currentItem()
        identifier = item.data(Qt.UserRole) if item else None
        return next((profile for profile in self.settings.models() if profile.id == identifier), None)

    def _refresh_models(self, selected_id: str | None = None) -> None:
        profiles = self.settings.models()
        active = self.settings.get("active_model_id", "")
        selected_id = selected_id or active
        self.model_list.blockSignals(True)
        self.model_list.clear()
        selected = None
        for profile in profiles:
            suffix = " · 使用中" if profile.id == active else ""
            item = QListWidgetItem(f"{profile.name or profile.model}{suffix}\n{profile.model}")
            item.setData(Qt.UserRole, profile.id)
            item.setSizeHint(QSize(180, 65))
            item.setToolTip(f"{profile.name}\n{profile.base_url}\n{profile.model}")
            self.model_list.addItem(item)
            if profile.id == selected_id:
                selected = item
        self.model_list.blockSignals(False)
        self.model_count.setText(f"模型库 · {len(profiles)}")
        self.empty_hint.setVisible(not profiles)
        self.model_list.setVisible(bool(profiles))
        if profiles:
            self.model_list.setCurrentItem(selected or self.model_list.item(0))
        else:
            self.new_model()

    def new_model(self) -> None:
        self.cancel_catalog()
        self._clear_catalog()
        self.model_list.setCurrentItem(None)
        self._editing_id = None
        self._loading = True
        for edit in (self.name_edit, self.url_edit, self.key_edit, self.model_edit):
            edit.clear()
        self.output_tokens_spin.setValue(4096)
        self.provider_combo.setCurrentIndex(0)
        self._loading = False
        self.show_key_button.setChecked(False)
        self.editor_title.setText("添加模型")
        self.active_badge.setText("未保存")
        self.select_model_button.setEnabled(False)
        self.remove_model_button.setEnabled(False)
        self.cancel_connection()
        self._status(self.form_status, "")
        self.name_edit.setFocus()

    def _load_selected(self, current, previous=None) -> None:
        self.cancel_connection()
        self.cancel_catalog()
        self._clear_catalog()
        profile = self._selected_profile()
        if profile is None:
            return
        self._editing_id = profile.id
        self._loading = True
        for edit, text in ((self.name_edit, profile.name), (self.url_edit, profile.base_url),
                           (self.key_edit, profile.api_key), (self.model_edit, profile.model)):
            edit.setText(text)
        self.output_tokens_spin.setValue(profile.max_output_tokens)
        self._sync_provider()
        self._loading = False
        self.show_key_button.setChecked(False)
        self.editor_title.setText("编辑模型")
        self.active_badge.setText("正在使用" if profile.id == self.settings.get("active_model_id") else "已保存")
        self.select_model_button.setEnabled(profile.id != self.settings.get("active_model_id"))
        self.remove_model_button.setEnabled(True)
        self._status(self.form_status, "")

    def _form_profile(self) -> ModelProfile:
        url, model = self.url_edit.text().strip().rstrip("/"), self.model_edit.text().strip()
        profile = ModelProfile(self._editing_id or self.settings.model_id(url, model),
                               self.name_edit.text().strip() or model, url, model, self.key_edit.text().strip(),
                               max_output_tokens=self.output_tokens_spin.value())
        ModelConnectionTester.validate(profile)
        profile.base_url = normalize_base_url(url)
        if not self._editing_id:
            profile.id = self.settings.model_id(profile.base_url, model)
        return profile

    def _save_model(self) -> None:
        try:
            profile = self._form_profile()
        except ValueError as error:
            self._status(self.form_status, str(error), "error")
            return
        if any(
            item.id != self._editing_id
            and (item.id == profile.id or
                 (normalize_base_url(item.base_url) == profile.base_url and item.model == profile.model))
            for item in self.settings.models()
        ):
            self._status(self.form_status, "这个服务和模型已存在，请在左侧选择后编辑。", "error")
            return
        try:
            self.settings.upsert_model(profile, make_active=self.settings.active_model() is None)
        except OSError:
            self._status(self.form_status, "保存失败，请检查配置目录的写入权限。", "error")
            return
        self._refresh_models(profile.id)
        self._status(self.form_status, "模型已保存。")
        self.settings_changed.emit()

    def _select_model(self) -> None:
        profile = self._selected_profile()
        if profile and self.settings.select_model(profile.id):
            self._refresh_models(profile.id)
            self._status(self.form_status, "已设为当前模型。")
            self.settings_changed.emit()

    def _remove_model(self) -> None:
        profile = self._selected_profile()
        if profile and QMessageBox.question(self, "删除模型", f"确定删除“{profile.name}”？") == QMessageBox.Yes:
            self.settings.remove_model(profile.id)
            self._refresh_models()
            self.settings_changed.emit()

    def _test_connection(self) -> None:
        if self._connection_id is not None:
            self.cancel_connection("已取消本次测试。")
            return
        try:
            profile = self._form_profile()
        except ValueError as error:
            self._status(self.connection_status, str(error), "error")
            return
        self._connection_id = self.connection_tester.start(profile)
        self.test_connection_button.setText("取消测试")
        self._status(self.connection_status, "正在验证模型连接…", "pending")

    def _connection_finished(self, request_id: int, success: bool, message: str, elapsed_ms: int) -> None:
        if request_id != self._connection_id:
            return
        self._connection_id = None
        self.test_connection_button.setText("测试连通性")
        self._status(self.connection_status, f"{message}  {elapsed_ms} ms", "success" if success else "error")
