from __future__ import annotations

from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from learning_assistant.ui.pdfjs_server import PdfJsAssetServer, _copy_bytes


def _open(request: str | Request):
    return urlopen(request, timeout=2)


def test_stream_copy_treats_a_cancelled_browser_request_as_normal() -> None:
    """Closing a PDF tab mid-response must not dump a server-thread traceback."""
    class DisconnectedClient:
        def write(self, _chunk: bytes) -> None:
            raise ConnectionResetError("browser closed the request")

    _copy_bytes(BytesIO(b"still streaming"), DisconnectedClient(), 15)


def test_server_streams_the_selected_document_with_head_and_byte_ranges(
    tmp_path: Path,
) -> None:
    """Ignoring Range would force large PDFs into memory and slow first render."""
    assets = tmp_path / "pdfjs"
    (assets / "web").mkdir(parents=True)
    (assets / "web" / "viewer.html").write_text("viewer", encoding="utf-8")
    document = tmp_path / "paper.pdf"
    payload = b"%PDF-1.7\n0123456789abcdef"
    document.write_bytes(payload)

    with PdfJsAssetServer(assets, document) as server:
        with _open(Request(server.document_url, method="HEAD")) as response:
            assert response.status == 200
            assert response.headers["Content-Length"] == str(len(payload))
            assert response.headers["Accept-Ranges"] == "bytes"
            assert response.read() == b""

        with _open(Request(server.document_url, headers={"Range": "bytes=9-12"})) as response:
            assert response.status == 206
            assert response.headers["Content-Range"] == f"bytes 9-12/{len(payload)}"
            assert response.read() == payload[9:13]

        with _open(Request(server.document_url, headers={"Range": "bytes=-4"})) as response:
            assert response.status == 206
            assert response.read() == payload[-4:]


def test_server_rejects_invalid_ranges_and_paths_outside_the_asset_root(
    tmp_path: Path,
) -> None:
    """A guessed loopback URL must not expose arbitrary local files."""
    assets = tmp_path / "pdfjs"
    (assets / "web").mkdir(parents=True)
    (assets / "web" / "viewer.html").write_text("viewer", encoding="utf-8")
    document = tmp_path / "paper.pdf"
    document.write_bytes(b"%PDF-1.4\nshort")
    (tmp_path / "secret.txt").write_text("private", encoding="utf-8")

    with PdfJsAssetServer(assets, document) as server:
        try:
            _open(Request(server.document_url, headers={"Range": "bytes=999-1000"}))
        except HTTPError as error:
            assert error.code == 416
            assert error.headers["Content-Range"] == "bytes */14"
        else:
            raise AssertionError("invalid byte range was accepted")

        try:
            _open(f"{server.base_url}/%2e%2e/secret.txt")
        except HTTPError as error:
            assert error.code == 404
        else:
            raise AssertionError("asset traversal exposed a local file")


def test_server_serves_only_declared_extra_files(tmp_path: Path) -> None:
    """Custom viewer CSS is explicit; sibling project files stay private."""
    assets = tmp_path / "pdfjs"
    (assets / "web").mkdir(parents=True)
    (assets / "web" / "viewer.html").write_text("viewer", encoding="utf-8")
    document = tmp_path / "paper.pdf"
    document.write_bytes(b"%PDF-1.4\n")
    css = tmp_path / "reader.css"
    css.write_text("body { color: black; }", encoding="utf-8")

    with PdfJsAssetServer(
        assets,
        document,
        {"/linguaspark-reader.css": css},
    ) as server:
        with _open(f"{server.base_url}/linguaspark-reader.css") as response:
            assert response.headers["Content-Type"].startswith("text/css")
            assert response.read() == b"body { color: black; }"
