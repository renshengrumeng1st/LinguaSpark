"""System tray icon for translation assistant using pystray."""

import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger("tray")


class TrayIconManager:
    """Manages the system tray icon and menu."""

    def __init__(
        self,
        on_show: Callable[[], None],
        on_settings: Callable[[], None],
        on_quit: Callable[[], None],
        icon_path: Optional[str] = None,
    ):
        self.on_show = on_show
        self.on_settings = on_settings
        self.on_quit = on_quit
        self.icon_path = icon_path
        self._icon = None
        self._thread: Optional[threading.Thread] = None

    def _create_icon_image(self):
        """Load icon from assets/icon.ico (same file used for taskbar icon)."""
        import os
        from PIL import Image

        ico_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "assets", "icon.ico"
        )
        if os.path.exists(ico_path):
            try:
                img = Image.open(ico_path)
                # Ensure RGBA for proper tray rendering
                if img.mode != "RGBA":
                    img = img.convert("RGBA")
                return img
            except Exception as e:
                logger.warning("Failed to load ICO: %s", e)

        # Fallback: programmatic icon
        return self._create_fallback_icon()

    def _create_fallback_icon(self):
        """Create a simple blue programmatic icon as fallback."""
        from PIL import Image, ImageDraw

        img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Draw rounded rectangle background
        draw.rounded_rectangle(
            [4, 4, 60, 60],
            radius=12,
            fill=(59, 130, 246, 255)  # Blue
        )

        # Draw a simple "文" (text) representation
        draw.rectangle([18, 18, 46, 22], fill=(255, 255, 255, 255))
        draw.rectangle([18, 28, 46, 32], fill=(255, 255, 255, 255))
        draw.rectangle([18, 38, 46, 42], fill=(255, 255, 255, 255))
        draw.rectangle([26, 18, 30, 42], fill=(255, 255, 255, 255))

        return img

    def _setup_menu(self):
        """Create the tray icon menu."""
        import pystray

        return pystray.Menu(
            pystray.MenuItem("显示/隐藏窗口", self._on_toggle, default=True),
            pystray.MenuItem("打开设置", self._on_open_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出应用", self._on_quit_app),
        )

    def _on_toggle(self, icon, item):
        try:
            self.on_show()
        except Exception as e:
            logger.error("Error toggling window: %s", e)

    def _on_open_settings(self, icon, item):
        try:
            self.on_settings()
        except Exception as e:
            logger.error("Error opening settings: %s", e)

    def _on_quit_app(self, icon, item):
        try:
            self.on_quit()
        except Exception as e:
            logger.error("Error quitting app: %s", e)

    def _run_icon(self):
        """Run the tray icon (blocking, run in separate thread)."""
        try:
            import pystray

            image = self._create_icon_image()
            self._icon = pystray.Icon(
                "便捷翻译",
                image,
                "便捷翻译助手\nAlt+Q 显示/隐藏",
                self._setup_menu()
            )
            self._icon.run()
        except Exception as e:
            logger.error("Tray icon error: %s", e)

    def start(self):
        """Start the tray icon in a background thread."""
        self._thread = threading.Thread(target=self._run_icon, daemon=True)
        self._thread.start()
        logger.info("System tray icon started")

    def stop(self):
        """Stop the tray icon."""
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
