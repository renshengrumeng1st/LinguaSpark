"""Tests for config.py"""

import json
import os
import tempfile
import unittest

from config import ConfigManager, DEFAULT_CONFIG


class TestConfigManager(unittest.TestCase):
    """Test ConfigManager with temporary files."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w",
        )
        self._tmp.close()
        self.config = ConfigManager(config_file=self._tmp.name)

    def tearDown(self):
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_default_values(self):
        """New config should have all default keys."""
        for key in DEFAULT_CONFIG:
            self.assertIn(key, self.config.all_config)

    def test_get_set(self):
        """get/set should work for arbitrary keys."""
        self.config.set("api_key", "test-key-123")
        self.assertEqual(self.config.get("api_key"), "test-key-123")

    def test_save_and_reload(self):
        """Saved config should persist across instances."""
        self.config.set("api_key", "persist-me")
        self.config.set("model", "gpt-4")
        self.assertTrue(self.config.save())

        # Reload from same file
        reloaded = ConfigManager(config_file=self._tmp.name)
        self.assertEqual(reloaded.get("api_key"), "persist-me")
        self.assertEqual(reloaded.get("model"), "gpt-4")

    def test_is_configured(self):
        """is_configured requires base_url, api_key, and model."""
        self.assertFalse(self.config.is_configured())
        self.config.set("base_url", "https://api.example.com/v1")
        self.assertFalse(self.config.is_configured())
        self.config.set("api_key", "sk-xxx")
        self.assertFalse(self.config.is_configured())
        self.config.set("model", "gpt-4")
        self.assertTrue(self.config.is_configured())

    def test_corrupted_file(self):
        """Corrupted JSON should fall back to defaults."""
        with open(self._tmp.name, "w") as f:
            f.write("not valid json{{{")
        cfg = ConfigManager(config_file=self._tmp.name)
        # Should have default values, not crash
        self.assertEqual(cfg.get("temperature"), DEFAULT_CONFIG["temperature"])

    def test_window_geometry_roundtrip(self):
        """save_window_geometry / get_window_geometry should round-trip."""
        self.config.save_window_geometry(100, 200, 600, 500)
        geo = self.config.get_window_geometry()
        self.assertEqual(geo["x"], 100)
        self.assertEqual(geo["y"], 200)
        self.assertEqual(geo["width"], 600)
        self.assertEqual(geo["height"], 500)

    def test_window_geometry_negative_returns_none(self):
        """Negative coordinates should return None (not saved)."""
        geo = self.config.get_window_geometry()
        self.assertIsNone(geo)

    def test_shortcuts_default_values(self):
        """Configurable shortcuts should have defaults."""
        shortcuts = self.config.get_all_shortcuts()
        self.assertIn("shortcut_translate", shortcuts)
        self.assertEqual(shortcuts["shortcut_translate"], "<Control-Return>")
        self.assertEqual(shortcuts["shortcut_clear"], "<Control-l>")

    def test_shortcut_set_and_get(self):
        """Setting a shortcut should round-trip."""
        self.config.set_shortcut("shortcut_translate", "<Control-Shift-A>")
        shortcuts = self.config.get_all_shortcuts()
        self.assertEqual(shortcuts["shortcut_translate"], "<Control-Shift-A>")

    def test_models_default_empty(self):
        """Fresh config has no selectable models."""
        self.assertEqual(self.config.get_models_for_provider(), [])

    def test_add_custom_model_stores_entry(self):
        """add_custom_model stores base_url/api_key/model and returns True."""
        self.assertTrue(self.config.add_custom_model("https://api.x.com/v1", "sk-1", "model-a"))
        entries = self.config.get_custom_models()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["model"], "model-a")
        self.assertEqual(entries[0]["base_url"], "https://api.x.com/v1")
        self.assertEqual(entries[0]["api_key"], "sk-1")

    def test_add_custom_model_appears_in_list(self):
        """Added models appear in get_models_for_provider."""
        self.config.add_custom_model("https://api.x.com/v1", "sk-1", "model-a")
        self.assertEqual(self.config.get_models_for_provider(), ["model-a"])

    def test_add_custom_model_rejects_empty_and_duplicate(self):
        """Empty model names and duplicates are rejected."""
        self.assertFalse(self.config.add_custom_model("url", "key", ""))
        self.assertFalse(self.config.add_custom_model("url", "key", "   "))
        self.assertTrue(self.config.add_custom_model("url", "key", "model-a"))
        self.assertFalse(self.config.add_custom_model("url2", "key2", "model-a"))
        self.assertEqual(len(self.config.get_custom_models()), 1)

    def test_add_custom_model_activates_when_none_active(self):
        """Adding a model when none is active activates it (syncs flat fields)."""
        self.config.add_custom_model("https://api.x.com/v1", "sk-1", "model-a")
        self.assertEqual(self.config.get("model"), "model-a")
        self.assertEqual(self.config.get("base_url"), "https://api.x.com/v1")
        self.assertEqual(self.config.get("api_key"), "sk-1")

    def test_add_custom_model_does_not_override_active(self):
        """Adding a model when one is already active does not switch active."""
        self.config.add_custom_model("https://api.x.com/v1", "sk-1", "model-a")
        self.config.add_custom_model("https://api.y.com/v1", "sk-2", "model-b")
        self.assertEqual(self.config.get("model"), "model-a")

    def test_select_model_syncs_flat_fields(self):
        """select_model updates base_url/api_key/model from the entry."""
        self.config.add_custom_model("https://api.x.com/v1", "sk-1", "model-a")
        self.config.add_custom_model("https://api.y.com/v1", "sk-2", "model-b")
        self.assertTrue(self.config.select_model("model-b"))
        self.assertEqual(self.config.get("model"), "model-b")
        self.assertEqual(self.config.get("base_url"), "https://api.y.com/v1")
        self.assertEqual(self.config.get("api_key"), "sk-2")
        self.assertFalse(self.config.select_model("nonexistent"))

    def test_remove_custom_model_reselects_active(self):
        """Removing the active model reselects another entry."""
        self.config.add_custom_model("https://api.x.com/v1", "sk-1", "model-a")
        self.config.add_custom_model("https://api.y.com/v1", "sk-2", "model-b")
        self.assertTrue(self.config.remove_custom_model("model-a"))
        self.assertEqual(self.config.get("model"), "model-b")
        self.assertEqual(self.config.get("base_url"), "https://api.y.com/v1")

    def test_remove_custom_model_clears_when_none_left(self):
        """Removing the last model clears the active config."""
        self.config.add_custom_model("https://api.x.com/v1", "sk-1", "model-a")
        self.assertTrue(self.config.remove_custom_model("model-a"))
        self.assertEqual(self.config.get("model"), "")
        self.assertEqual(self.config.get_custom_models(), [])

    def test_custom_models_persist_across_reload(self):
        """Custom models survive a save/reload cycle."""
        self.config.add_custom_model("https://api.x.com/v1", "sk-1", "persisted-model")
        self.assertTrue(self.config.save())
        reloaded = ConfigManager(config_file=self._tmp.name)
        self.assertIn("persisted-model", reloaded.get_models_for_provider())
        entries = reloaded.get_custom_models()
        self.assertEqual(entries[0]["base_url"], "https://api.x.com/v1")

    def test_normalize_seeds_from_flat_config(self):
        """On load, a complete flat config is seeded as a model entry."""
        import json
        with open(self._tmp.name, "w", encoding="utf-8") as f:
            json.dump({
                "base_url": "https://api.flat.com/v1",
                "api_key": "sk-flat",
                "model": "flat-model",
                "custom_models": [],
            }, f)
        cfg = ConfigManager(config_file=self._tmp.name)
        entries = cfg.get_custom_models()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["model"], "flat-model")
        self.assertIn("flat-model", cfg.get_models_for_provider())

    def test_normalize_migrates_string_entries(self):
        """Legacy string entries are migrated to dicts using the flat endpoint."""
        import json
        with open(self._tmp.name, "w", encoding="utf-8") as f:
            json.dump({
                "base_url": "https://api.legacy.com/v1",
                "api_key": "sk-legacy",
                "model": "legacy-active",
                "custom_models": ["legacy-model"],
            }, f)
        cfg = ConfigManager(config_file=self._tmp.name)
        entries = cfg.get_custom_models()
        names = [e["model"] for e in entries]
        self.assertIn("legacy-model", names)
        for e in entries:
            if e["model"] == "legacy-model":
                self.assertEqual(e["base_url"], "https://api.legacy.com/v1")




    def test_shortcut_invalid_key_ignored(self):
        """set_shortcut should ignore unknown keys."""
        self.config.set_shortcut("nonexistent_key", "<Control-A>")
        shortcuts = self.config.get_all_shortcuts()
        self.assertNotIn("nonexistent_key", shortcuts)


if __name__ == "__main__":
    unittest.main()
