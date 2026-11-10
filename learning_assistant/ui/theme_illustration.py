"""Small decorative illustrations; never painted over study content."""
from __future__ import annotations

import math
from PySide6.QtCore import QPointF, QRectF, Qt, QEvent
from PySide6.QtGui import QColor, QPainter, QPixmap, QPolygonF, QPen
from PySide6.QtWidgets import QApplication, QWidget
from learning_assistant.core.paths import project_root
from learning_assistant.ui.theme import THEMES


_PIXMAPS: dict[str, QPixmap] = {}


def draw_illustration(painter: QPainter, rect: QRectF, theme_id: str) -> None:
    t = THEMES.get(theme_id, THEMES["sakura"])
    asset = project_root() / "assets" / "themes" / f"{theme_id}.png"
    if theme_id in ("nahida", "furina", "raiden") and asset.is_file():
        if theme_id not in _PIXMAPS:
            _PIXMAPS[theme_id] = QPixmap(str(asset))
        pixmap = _PIXMAPS[theme_id]
        if not pixmap.isNull():
            size = pixmap.size().scaled(rect.size().toSize(), Qt.KeepAspectRatio)
            target = QRectF(rect.center().x() - size.width()/2, rect.center().y() - size.height()/2, size.width(), size.height())
            painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
            return
    painter.save()
    painter.translate(rect.x(), rect.y())
    painter.scale(rect.width()/180, rect.height()/130)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    def ellipse(x, y, w, h, color):
        painter.setBrush(QColor(color))
        painter.drawEllipse(QRectF(x, y, w, h))
    def star(x, y, radius, color):
        points = [QPointF(x + math.cos(-math.pi/2+i*math.pi/5)*(radius if i%2 == 0 else radius*.48),
                         y + math.sin(-math.pi/2+i*math.pi/5)*(radius if i%2 == 0 else radius*.48)) for i in range(10)]
        painter.setBrush(QColor(color))
        painter.drawPolygon(QPolygonF(points))
    ellipse(26, 28, 126, 90, t.tint)
    for x, y, r in ((26, 27, 4), (151, 24, 6), (150, 95, 4), (41, 105, 3)):
        star(x, y, r, t.accent)
    if theme_id == "dark":
        ellipse(57, 26, 67, 67, "#f2dba7")
        ellipse(78, 16, 57, 61, t.tint)
        star(93, 84, 24, t.accent)
    elif theme_id == "forest":
        painter.setBrush(QColor(t.accent))
        painter.drawRoundedRect(QRectF(61, 53, 56, 49), 23, 23)
        ellipse(57, 29, 38, 22, "#9ac08d")
        ellipse(90, 25, 37, 23, "#729e75")
        ellipse(74, 70, 5, 7, t.surface)
        ellipse(99, 70, 5, 7, t.surface)
    elif theme_id == "light":
        ellipse(106, 20, 34, 34, "#f5ce77")
        for x,y,w,h in ((48,60,38,33),(66,43,48,47),(91,57,38,35)):
            ellipse(x,y,w,h,t.surface)
        ellipse(72, 67, 5, 6, t.text)
        ellipse(99, 67, 5, 6, t.text)
    else:
        star(88, 62, 39, "#f3ca7f")
        ellipse(76, 58, 5, 8, t.text)
        ellipse(96, 58, 5, 8, t.text)
        ellipse(67, 72, 12, 5, "#eaa7bf")
        ellipse(99, 72, 12, 5, "#eaa7bf")
        for x,y in ((38,48),(130,53),(125,104)):
            ellipse(x,y,11,6,"#edbad5")
    painter.setPen(QPen(QColor(t.accent), 2))
    painter.setBrush(QColor(t.surface))
    painter.drawRoundedRect(QRectF(54, 104, 68, 13), 5, 5)
    painter.drawLine(88, 104, 88, 117)
    painter.restore()


class ThemeIllustration(QWidget):
    def __init__(self, theme_id: str | None = None, parent=None):
        super().__init__(parent)
        self.theme_id = theme_id
        self.setFixedSize(166, 120)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        app = QApplication.instance()
        theme_id = self.theme_id or (app.property("linguasparkTheme") if app else None) or "sakura"
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        draw_illustration(painter, QRectF(self.rect()), theme_id)
        painter.end()

    def changeEvent(self, event):
        if event.type() in (QEvent.PaletteChange, QEvent.StyleChange):
            self.update()
        super().changeEvent(event)
