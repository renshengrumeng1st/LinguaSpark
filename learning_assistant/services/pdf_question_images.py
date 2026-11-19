"""Validated, in-memory screenshots for PDF multimodal conversation turns."""

import base64
import binascii
import json

from PySide6.QtCore import QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QImageReader


MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_CONTEXT_IMAGE_BYTES = 24 * 1024 * 1024
DEFAULT_IMAGE_QUESTION = "请结合 PDF 解释这张截图，说明其中的关键信息。"


def image_part(data):
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValueError("无法读取截图，请使用 PNG 或 JPEG 图片。")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("单张截图不能超过 8 MB，请裁剪后重试。")
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    format = bytes(reader.format()).decode("ascii").lower()
    size = reader.size()
    if format not in {"png", "jpeg", "jpg"} or not size.isValid():
        raise ValueError("无法读取截图，请使用 PNG 或 JPEG 图片。")
    if size.width() * size.height() > 40_000_000:
        raise ValueError("截图尺寸过大，请裁剪后重试。")
    if reader.read().isNull():
        raise ValueError("截图文件已损坏，请重新选择。")
    mime = "image/png" if format == "png" else "image/jpeg"
    encoded = base64.b64encode(data).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}


def user_message(question, selection, image_bytes=None):
    text = json.dumps({"question": question, "selected_sentence": selection}, ensure_ascii=False)
    content = text if image_bytes is None else [{"type": "text", "text": text}, image_part(image_bytes)]
    return {"role": "user", "content": content}


def content_sizes(content):
    """Count text and image bytes separately; base64 is not prose context."""
    if isinstance(content, str):
        return len(content), 0
    if not isinstance(content, list):
        raise ValueError("对话上下文无效，请清空对话后重试。")
    text_size = image_size = 0
    for part in content:
        if not isinstance(part, dict):
            raise ValueError("对话上下文无效，请清空对话后重试。")
        if part.get("type") == "text" and isinstance(part.get("text"), str):
            text_size += len(part["text"])
        elif part.get("type") == "image_url":
            image_url = part.get("image_url")
            url = image_url.get("url") if isinstance(image_url, dict) else None
            if not isinstance(url, str):
                raise ValueError("截图上下文无效，请清空对话后重试。")
            prefix, separator, encoded = url.partition(",")
            if (not separator or prefix not in {"data:image/png;base64", "data:image/jpeg;base64"}
                    or len(encoded) > (MAX_IMAGE_BYTES + 2) // 3 * 4):
                raise ValueError("截图上下文无效或超过 8 MB，请清空对话后重试。")
            try:
                decoded_size = len(base64.b64decode(encoded, validate=True))
            except (ValueError, binascii.Error) as error:
                raise ValueError("截图上下文无效，请清空对话后重试。") from error
            if not 0 < decoded_size <= MAX_IMAGE_BYTES:
                raise ValueError("截图上下文无效或超过 8 MB，请清空对话后重试。")
            image_size += decoded_size
        else:
            raise ValueError("对话上下文无效，请清空对话后重试。")
    return text_size, image_size
