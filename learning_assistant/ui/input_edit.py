"""Text input with local image-file and screenshot clipboard support."""

from PySide6.QtCore import QByteArray, QBuffer, QFileInfo, QIODevice, Qt, Signal
from PySide6.QtGui import QImage, QImageReader, QKeyEvent, QPainter, QPixmap
from PySide6.QtWidgets import QPlainTextEdit


class InputEdit(QPlainTextEdit):
    submit_requested = Signal()
    image_pasted = Signal(bytes)
    image_rejected = Signal(str)

    def __init__(self, parent=None, *, max_image_pixels=None):
        super().__init__(parent)
        self._max_image_pixels = max_image_pixels

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier:
            self.submit_requested.emit()
            return
        super().keyPressEvent(event)

    @staticmethod
    def _image_file(source) -> str:
        urls = source.urls()
        if len(urls) != 1 or not urls[0].isLocalFile():
            return ""
        path = urls[0].toLocalFile()
        formats = {bytes(value).decode("ascii") for value in QImageReader.supportedImageFormats()}
        if QFileInfo(path).suffix().casefold() in formats or QImageReader(path).canRead():
            return path
        return ""

    def canInsertFromMimeData(self, source) -> bool:
        if self.isReadOnly():
            return False
        return bool(source.hasImage() or self._image_file(source) or super().canInsertFromMimeData(source))

    def insertFromMimeData(self, source) -> None:
        if self.isReadOnly():
            return
        path = self._image_file(source) if not source.hasImage() else ""
        if not source.hasImage() and not path:
            super().insertFromMimeData(source)
            return
        if path:
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            size = reader.size()
            if self._max_image_pixels and size.width() * size.height() > self._max_image_pixels:
                self.image_rejected.emit("截图尺寸过大，请裁剪后重试。")
                return
            image = reader.read()
        else:
            image = source.imageData()
            if isinstance(image, QPixmap):
                image = image.toImage()
        if not isinstance(image, QImage) or image.isNull():
            self.image_rejected.emit("无法读取图片，请重新复制图片或检查文件是否损坏")
            return
        if self._max_image_pixels and image.width() * image.height() > self._max_image_pixels:
            self.image_rejected.emit("截图尺寸过大，请裁剪后重试。")
            return
        if image.hasAlphaChannel():
            flattened = QImage(image.size(), QImage.Format_RGB32)
            flattened.fill(Qt.white)
            painter = QPainter(flattened)
            painter.drawImage(0, 0, image)
            painter.end()
            image = flattened
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        saved = image.save(buffer, "JPEG", 88)
        buffer.close()
        if not saved or not data:
            self.image_rejected.emit("图片转换失败，请尝试 PNG 或 JPEG 图片")
            return
        self.image_pasted.emit(bytes(data))
