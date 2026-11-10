"""Search and reopen local history and favorites without another model request."""
from __future__ import annotations

from datetime import datetime
import sqlite3
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QSplitter, QTabBar, QTextBrowser, QVBoxLayout, QWidget,
)
from learning_assistant.storage.learning_repository import LearningRepository


class LibraryDialog(QDialog):
    open_requested = Signal(object)
    changed = Signal()

    def __init__(self, repository: LearningRepository, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.setWindowTitle("历史与收藏 · LinguaSpark")
        self.resize(900, 620)
        self.setMinimumSize(700, 480)
        self._offset = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        title = QLabel("找回每一次发现")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        hint = QLabel("搜索原文或译文，离线查看已保存的结果。重新打开不会调用 AI。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.tabs = QTabBar()
        self.tabs.addTab("查询历史")
        self.tabs.addTab("我的收藏")
        root.addWidget(self.tabs)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索单词、原句或译文…")
        self.kind_filter = QComboBox()
        for name, value in (("全部类型", ""), ("单词", "word"), ("句子", "sentence"), ("图片", "image")):
            self.kind_filter.addItem(name, value)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.kind_filter)
        root.addLayout(filters)
        splitter = QSplitter()
        self.item_list = QListWidget()
        self.item_list.setMinimumWidth(220)
        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(False)
        self.detail.setPlaceholderText("选择一条记录，查看保存的释义或译文。")
        splitter.addWidget(self.item_list)
        splitter.addWidget(self.detail)
        splitter.setSizes([280, 520])
        root.addWidget(splitter, 1)
        self.count_label = QLabel()
        self.count_label.setObjectName("muted")
        self.count_label.setWordWrap(True)
        root.addWidget(self.count_label)
        actions = QHBoxLayout()
        self.delete_button = QPushButton("删除记录")
        self.delete_button.setObjectName("danger")
        self.batch_button = QPushButton("批量删除历史")
        self.batch_button.setCheckable(True)
        self.select_all_button = QPushButton("全选已加载")
        self.bulk_delete_button = QPushButton("删除勾选（0）")
        self.bulk_delete_button.setObjectName("danger")
        self.more_button = QPushButton("加载更多")
        self.open_button = QPushButton("重新打开")
        self.open_button.setObjectName("primary")
        actions.addWidget(self.delete_button)
        actions.addWidget(self.batch_button)
        actions.addWidget(self.select_all_button)
        actions.addWidget(self.bulk_delete_button)
        actions.addWidget(self.more_button)
        actions.addStretch(1)
        actions.addWidget(self.open_button)
        root.addLayout(actions)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self.reload)
        self.search.textChanged.connect(self._queue_search)
        self.tabs.currentChanged.connect(self.reload)
        self.kind_filter.currentIndexChanged.connect(self.reload)
        self.item_list.currentItemChanged.connect(self._preview)
        self.item_list.itemChanged.connect(self._update_batch_actions)
        self.item_list.itemDoubleClicked.connect(self._open)
        self.open_button.clicked.connect(self._open)
        self.delete_button.clicked.connect(self._delete)
        self.batch_button.toggled.connect(self._set_batch_mode)
        self.select_all_button.clicked.connect(self._select_all)
        self.bulk_delete_button.clicked.connect(self._delete_bulk)
        self.more_button.clicked.connect(self._append)
        self.reload()

    @property
    def collection(self):
        return "favorites" if self.tabs.currentIndex() == 1 else "history"

    def reload(self, *_):
        self._search_timer.stop()
        self.item_list.clear()
        if self.collection != "history":
            self.batch_button.setChecked(False)
        self._offset = 0
        self._append()
        if self.item_list.count():
            self.item_list.setCurrentRow(0)
        else:
            self._preview()

    def _append(self):
        rows = self.repository.saved_items(self.collection, self.search.text(), self.kind_filter.currentData(), 101, self._offset)
        for value in rows[:100]:
            date = datetime.fromtimestamp(value["created_at"]).strftime("%m-%d %H:%M")
            excerpt = value["source_text"].replace("\n", " ") or "图片翻译"
            item = QListWidgetItem(f"{excerpt[:55]}\n{date} · { {'word':'单词', 'sentence':'句子', 'image':'图片'}.get(value['query_kind'], '查询') }")
            item.setData(Qt.UserRole, value)
            item.setToolTip(excerpt[:1000])
            if self.batch_button.isChecked() and self.collection == "history":
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
            self.item_list.addItem(item)
        self._offset += min(100, len(rows))
        self.more_button.setVisible(len(rows) > 100)
        self._update_batch_actions()

    def _queue_search(self):
        self._search_timer.start()
        self.delete_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self._update_batch_actions()

    def _set_batch_mode(self, enabled: bool):
        self.item_list.blockSignals(True)
        try:
            for index in range(self.item_list.count()):
                item = self.item_list.item(index)
                item.setData(Qt.CheckStateRole, Qt.Unchecked if enabled else None)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable if enabled else item.flags() & ~Qt.ItemIsUserCheckable)
        finally:
            self.item_list.blockSignals(False)
        self._update_batch_actions()

    def _checked_history(self):
        return [self.item_list.item(index).data(Qt.UserRole)["identifier"]
                for index in range(self.item_list.count())
                if self.item_list.item(index).checkState() == Qt.Checked]

    def _update_batch_actions(self, *_):
        history = self.collection == "history"
        active = history and self.batch_button.isChecked()
        count = len(self._checked_history()) if active else 0
        pending = self._search_timer.isActive()
        self.batch_button.setVisible(history)
        self.batch_button.setEnabled(not pending and (self.item_list.count() > 0 or active))
        self.batch_button.setText("退出批量" if active else "批量删除历史")
        self.select_all_button.setVisible(active)
        self.select_all_button.setEnabled(not pending and self.item_list.count() > 0)
        self.select_all_button.setText("取消全选" if count and count == self.item_list.count() else "全选已加载")
        self.bulk_delete_button.setVisible(active)
        self.bulk_delete_button.setText(f"删除勾选（{count}）")
        self.bulk_delete_button.setEnabled(not pending and count > 0)
        self.delete_button.setVisible(not active)
        self.more_button.setEnabled(not pending)
        text = f"已显示 {self.item_list.count()} 条" if self.item_list.count() else "还没有匹配的记录。换个关键词，或开始一次新的查询。"
        if active:
            text += f" · 已勾选 {count} 条；全选仅包含已加载的记录。"
        self.count_label.setText(text)

    def _select_all(self):
        target = Qt.Unchecked if len(self._checked_history()) == self.item_list.count() else Qt.Checked
        self.item_list.blockSignals(True)
        try:
            for index in range(self.item_list.count()):
                self.item_list.item(index).setCheckState(target)
        finally:
            self.item_list.blockSignals(False)
        self._update_batch_actions()

    def _delete_bulk(self):
        if self.collection != "history" or self._search_timer.isActive():
            return
        identifiers = self._checked_history()
        if not identifiers:
            return
        prompt = f"确定删除勾选的 {len(identifiers)} 条历史记录？\n收藏和学习计划会保留。"
        if QMessageBox.question(self, "批量删除历史", prompt,
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            self.repository.delete_history(identifiers)
        except sqlite3.Error:
            QMessageBox.warning(self, "删除失败", "本次批量删除未完成，请稍后重试。")
            return
        self.reload()
        self.changed.emit()

    def _selected(self):
        item = self.item_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _preview(self, *_):
        value = self._selected()
        self.open_button.setEnabled(value is not None and not self._search_timer.isActive())
        self.delete_button.setEnabled(value is not None and not self._search_timer.isActive())
        self.delete_button.setText("取消收藏" if self.collection == "favorites" else "删除记录")
        if not value:
            self.detail.clear()
            return
        payload = value["payload"]
        lines = [value["source_text"]]
        dictionary = payload.get("dictionary", {})
        if isinstance(dictionary, dict):
            lines.extend(str(line) for line in (dictionary.get("translations") or dictionary.get("definitions") or []))
        note = payload.get("ai_note", {})
        if isinstance(note, dict):
            for key, label in (("plain_explanation", "通俗解释"), ("sense_in_context", "当前语境"), ("memory_tip", "记忆提示")):
                if note.get(key):
                    lines.extend(["", label, str(note[key])])
            for key, label in (("synonyms", "近义词"), ("collocations", "常用搭配")):
                if isinstance(note.get(key), list) and note[key]:
                    lines.extend(["", label, " · ".join(str(v) for v in note[key])])
            for example in note.get("examples", []) if isinstance(note.get("examples"), list) else []:
                if isinstance(example, dict):
                    lines.extend(["", str(example.get("sentence", "")), str(example.get("translation", ""))])
        sentence = payload.get("sentence", {})
        if isinstance(sentence, dict):
            if sentence.get("translation"):
                lines.extend(["", "译文", str(sentence["translation"])])
            if sentence.get("learning_tip"):
                lines.extend(["", str(sentence["learning_tip"])])
        self.detail.setPlainText("\n".join(lines))

    def _open(self, *_):
        value = self._selected()
        if value:
            self.open_requested.emit(value)
            self.accept()

    def _delete(self):
        value = self._selected()
        if not value:
            return
        prompt = "取消这条收藏？学习计划会保留。" if self.collection == "favorites" else "删除这条历史？收藏和学习计划会保留。"
        if QMessageBox.question(self, "确认操作", prompt) != QMessageBox.Yes:
            return
        self.repository.delete_saved(self.collection, value["identifier"])
        self.reload()
        self.changed.emit()
