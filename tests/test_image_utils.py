"""Tests for utils/image_utils.py"""

import io
import unittest
from PIL import Image

from utils.image_utils import image_to_base64_png, build_image_content


class TestImageToBase64Png(unittest.TestCase):
    """Test image_to_base64_png conversion."""

    def test_rgba_image(self):
        """RGBA image should produce valid base64 PNG."""
        img = Image.new("RGBA", (10, 10), (255, 0, 0, 128))
        b64 = image_to_base64_png(img)
        self.assertIsInstance(b64, str)
        self.assertTrue(len(b64) > 0)

    def test_rgb_image(self):
        """RGB image should be converted to RGBA/PNG correctly."""
        img = Image.new("RGB", (10, 10), (0, 255, 0))
        b64 = image_to_base64_png(img)
        self.assertIsInstance(b64, str)
        self.assertTrue(len(b64) > 0)

    def test_output_is_png(self):
        """Output should be a valid PNG (check magic bytes after decode)."""
        import base64
        img = Image.new("RGBA", (5, 5))
        b64 = image_to_base64_png(img)
        raw = base64.b64decode(b64)
        self.assertEqual(raw[:4], b"\x89PNG")

    def test_deterministic(self):
        """Same image should produce same output."""
        img = Image.new("RGBA", (10, 10), (100, 200, 50, 200))
        self.assertEqual(image_to_base64_png(img), image_to_base64_png(img))

    def test_large_image_resized(self):
        """Large images should be down-scaled to reduce payload size."""
        import base64
        from utils.image_utils import _MAX_IMAGE_DIMENSION
        big = Image.new("RGBA", (3000, 2000))
        b64 = image_to_base64_png(big)
        raw = base64.b64decode(b64)
        decoded = Image.open(io.BytesIO(raw))
        self.assertLessEqual(max(decoded.size), _MAX_IMAGE_DIMENSION)

    def test_small_image_not_resized(self):
        """Small images should pass through unchanged in dimensions."""
        import base64
        img = Image.new("RGBA", (100, 80))
        b64 = image_to_base64_png(img)
        raw = base64.b64decode(b64)
        decoded = Image.open(io.BytesIO(raw))
        self.assertEqual(decoded.size, (100, 80))


class TestBuildImageContent(unittest.TestCase):
    """Test build_image_content multimodal content builder."""

    def setUp(self):
        self.img = Image.new("RGBA", (10, 10))

    def test_image_only(self):
        content = build_image_content(self.img)
        self.assertEqual(len(content), 1)
        self.assertEqual(content[0]["type"], "image_url")
        self.assertIn("url", content[0]["image_url"])
        self.assertTrue(content[0]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_image_with_text(self):
        content = build_image_content(self.img, "hello")
        self.assertEqual(len(content), 2)
        # Text should come first
        self.assertEqual(content[0]["type"], "text")
        self.assertEqual(content[0]["text"], "hello")
        self.assertEqual(content[1]["type"], "image_url")
        self.assertIn("url", content[1]["image_url"])

    def test_image_with_empty_text(self):
        """Empty string text should behave like no text."""
        content = build_image_content(self.img, "")
        # Empty string is falsy, so only image
        self.assertEqual(len(content), 1)
        self.assertEqual(content[0]["type"], "image_url")


if __name__ == "__main__":
    unittest.main()
