"""Tests for translator.py — focus on error-handling regression coverage.

The key regression: ``_make_request`` / ``_make_stream_request`` previously
referenced an unbound ``resp`` when ``.post()`` raised before assignment,
masking the real error with ``NameError``. These tests ensure connection /
timeout failures surface as friendly ``TranslationError`` instead.
"""

import unittest
from unittest import mock

import requests

from translator import Translator, TranslationError


def _make_translator() -> Translator:
    return Translator(base_url="https://api.example.com/v1", api_key="sk-x", model="m")


class TestTranslatorErrors(unittest.TestCase):
    """Error paths must raise TranslationError, never NameError."""

    def test_connection_error_raises_translation_error(self):
        """A ConnectionError during .post() yields a friendly TranslationError."""
        t = _make_translator()
        with mock.patch("translator._get_session") as gs:
            gs.return_value.post.side_effect = requests.exceptions.ConnectionError("down")
            with self.assertRaises(TranslationError) as cm:
                t._make_request([{"role": "user", "content": "hi"}])
            self.assertIn("连接", str(cm.exception))

    def test_timeout_raises_translation_error(self):
        """A Timeout during .post() yields a friendly TranslationError."""
        t = _make_translator()
        with mock.patch("translator._get_session") as gs:
            gs.return_value.post.side_effect = requests.exceptions.Timeout("slow")
            with self.assertRaises(TranslationError) as cm:
                t._make_request([{"role": "user", "content": "hi"}])
            self.assertIn("超时", str(cm.exception))

    def test_stream_connection_error_raises_translation_error(self):
        """Streaming path also surfaces connection errors as TranslationError."""
        t = _make_translator()
        with mock.patch("translator._get_session") as gs:
            gs.return_value.post.side_effect = requests.exceptions.ConnectionError("down")
            with self.assertRaises(TranslationError):
                # Consume the generator so the exception is raised.
                list(t._make_stream_request([{"role": "user", "content": "hi"}]))

    def test_no_nameerror_on_request_failure(self):
        """Regression: must not raise NameError for 'resp' (the original bug)."""
        t = _make_translator()
        with mock.patch("translator._get_session") as gs:
            gs.return_value.post.side_effect = requests.exceptions.ConnectionError("down")
            try:
                t._make_request([{"role": "user", "content": "hi"}])
            except NameError as e:
                self.fail(f"NameError leaked instead of TranslationError: {e}")
            except TranslationError:
                pass  # expected


class TestTranslatorSuccess(unittest.TestCase):
    """Happy-path parsing of a standard OpenAI-style response."""

    def test_make_request_returns_message_content(self):
        t = _make_translator()
        resp = mock.Mock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "choices": [{"message": {"content": "你好"}}]
        }
        with mock.patch("translator._get_session") as gs:
            gs.return_value.post.return_value = resp
            result = t._make_request([{"role": "user", "content": "hello"}])
        self.assertEqual(result, "你好")

    def test_translate_text_empty_input(self):
        t = _make_translator()
        with self.assertRaises(TranslationError):
            t.translate_text("   ")

    def test_get_system_prompt_fallback(self):
        """Missing custom prompt falls back to the built-in default."""
        t = _make_translator()
        prompt = t.get_system_prompt("system_prompt_text")
        self.assertTrue(prompt)  # default is non-empty


if __name__ == "__main__":
    unittest.main()
