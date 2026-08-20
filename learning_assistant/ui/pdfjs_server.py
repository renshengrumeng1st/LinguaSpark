"""Loopback-only streaming server for PDF.js and one local document."""

from __future__ import annotations

from contextlib import AbstractContextManager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
from pathlib import Path
import re
import secrets
import threading
from types import TracebackType
from typing import BinaryIO, Mapping
from urllib.parse import quote, unquote, urlsplit


_RANGE_PATTERN = re.compile(r"bytes=(\d*)-(\d*)\Z")
_CHUNK_SIZE = 64 * 1024


def _byte_range(header: str, size: int) -> tuple[int, int]:
    match = _RANGE_PATTERN.fullmatch(header.strip())
    if match is None or size <= 0:
        raise ValueError("invalid byte range")
    first, last = match.groups()
    if not first:
        suffix = int(last or "0")
        if suffix <= 0:
            raise ValueError("invalid suffix range")
        start = max(0, size - suffix)
        return start, size - 1
    start = int(first)
    end = int(last) if last else size - 1
    if start >= size or end < start:
        raise ValueError("range is outside the file")
    return start, min(end, size - 1)


def _copy_bytes(source: BinaryIO, target: BinaryIO, count: int) -> None:
    remaining = count
    while remaining > 0:
        chunk = source.read(min(_CHUNK_SIZE, remaining))
        if not chunk:
            break
        try:
            target.write(chunk)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            break
        remaining -= len(chunk)


class PdfJsAssetServer(AbstractContextManager["PdfJsAssetServer"]):
    """Serve a fixed PDF.js tree and one tokenized PDF on localhost."""

    def __init__(
        self,
        asset_root: Path,
        document_path: Path,
        extra_files: Mapping[str, Path] | None = None,
    ) -> None:
        self.asset_root = Path(asset_root).resolve()
        self.document_path = Path(document_path).resolve()
        self.extra_files = {
            self._normalized_route(route): Path(path).resolve()
            for route, path in (extra_files or {}).items()
        }
        self._document_route = f"/document/{secrets.token_urlsafe(24)}.pdf"
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.request_log: list[tuple[str, str | None]] = []

    @staticmethod
    def _normalized_route(route: str) -> str:
        value = "/" + str(route).lstrip("/")
        if ".." in Path(value).parts:
            raise ValueError("extra file route must not traverse")
        return value

    @property
    def base_url(self) -> str:
        if self._httpd is None:
            raise RuntimeError("PDF.js asset server is not running")
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def document_url(self) -> str:
        return f"{self.base_url}{self._document_route}"

    @property
    def viewer_url(self) -> str:
        document = quote(self._document_route, safe="/")
        return f"{self.base_url}/web/viewer.html?file={document}"

    def start(self) -> "PdfJsAssetServer":
        if self._httpd is not None:
            return self
        if not (self.asset_root / "web" / "viewer.html").is_file():
            raise FileNotFoundError("PDF.js web/viewer.html is missing")
        if not self.document_path.is_file():
            raise FileNotFoundError(self.document_path)

        asset_root = self.asset_root
        document_path = self.document_path
        document_route = self._document_route
        extra_files = self.extra_files
        request_log = self.request_log

        class RequestHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib protocol name
                self._route(head_only=False)

            def do_HEAD(self) -> None:  # noqa: N802 - stdlib protocol name
                self._route(head_only=True)

            def _route(self, head_only: bool) -> None:
                route = unquote(urlsplit(self.path).path)
                request_log.append((route, self.headers.get("Range")))
                if route == document_route:
                    self._send_path(document_path, "application/pdf", head_only)
                    return
                extra = extra_files.get(route)
                if extra is not None and extra.is_file():
                    media_type = mimetypes.guess_type(extra.name)[0]
                    self._send_path(
                        extra,
                        media_type or "application/octet-stream",
                        head_only,
                    )
                    return
                candidate = (asset_root / route.lstrip("/")).resolve()
                try:
                    candidate.relative_to(asset_root)
                except ValueError:
                    self.send_error(404)
                    return
                if not candidate.is_file():
                    self.send_error(404)
                    return
                media_type = mimetypes.guess_type(candidate.name)[0]
                if candidate.suffix == ".mjs":
                    media_type = "text/javascript"
                elif candidate.suffix == ".wasm":
                    media_type = "application/wasm"
                self._send_path(
                    candidate,
                    media_type or "application/octet-stream",
                    head_only,
                )

            def _send_path(self, path: Path, media_type: str, head_only: bool) -> None:
                size = path.stat().st_size
                range_header = self.headers.get("Range")
                start, end, status = 0, max(0, size - 1), 200
                if range_header:
                    try:
                        start, end = _byte_range(range_header, size)
                    except (TypeError, ValueError):
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    status = 206
                length = 0 if size == 0 else end - start + 1
                self.send_response(status)
                self.send_header("Content-Type", media_type)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(length))
                self.send_header("Cache-Control", "no-store")
                if status == 206:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.end_headers()
                if head_only or not length:
                    return
                with path.open("rb") as source:
                    source.seek(start)
                    _copy_bytes(source, self.wfile, length)

            def log_message(self, _format: str, *args: object) -> None:
                return

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(
            target=lambda: self._httpd.serve_forever(poll_interval=0.05),
            name="linguaspark-pdfjs",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=1)
        self._httpd = None
        self._thread = None

    def __enter__(self) -> "PdfJsAssetServer":
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.stop()
