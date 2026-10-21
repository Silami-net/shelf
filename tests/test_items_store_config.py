import os
import tempfile
import unittest

from shelf import config, items, store
from shelf.items import Item


class ItemsTest(unittest.TestCase):
    def test_uris(self):
        got = items.from_uris(["file:///mnt/proj/shot%20010/comp_v003.nk",
                               "https://example.com/a", "", "# comment", "smb://srv/share/x.exr"])
        self.assertEqual([i.kind for i in got], ["file", "url", "file"])
        self.assertEqual(got[0].path, "/mnt/proj/shot 010/comp_v003.nk")
        self.assertEqual(got[0].label, "comp_v003.nk")
        self.assertEqual(got[0].detail, "/mnt/proj/shot 010")
        self.assertEqual(got[2].path, None)
        self.assertEqual(got[2].label, "x.exr")

    def test_folder_label(self):
        self.assertEqual(Item("file", "file:///mnt/proj/renders/").label, "renders")

    def test_unicode_path(self):
        it = items.from_uris(["file:///tmp/caf%C3%A9.png"])[0]
        self.assertEqual(it.path, "/tmp/café.png")

    def test_text(self):
        self.assertEqual(items.from_text("  \n "), [])
        self.assertEqual(items.from_text("https://example.com/x")[0].kind, "url")
        snippet = items.from_text("\n  hello world\nsecond line\n")[0]
        self.assertEqual(snippet.kind, "text")
        self.assertEqual(snippet.label, "hello world")
        self.assertIn("3 lines", snippet.detail)
        self.assertEqual(items.from_text("not a link: https://x.y")[0].kind, "text")

    def test_merge_skips_duplicates(self):
        shelf = items.from_uris(["file:///a"])
        added = items.merge(shelf, items.from_uris(["file:///a", "file:///b", "file:///b"]))
        self.assertEqual([i.value for i in added], ["file:///b"])
        self.assertEqual(len(shelf), 2)

    def test_as_text(self):
        self.assertEqual(Item("file", "file:///a%20b").as_text(), "/a b")
        self.assertEqual(Item("text", "hi").as_text(), "hi")


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "sub", "state.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_round_trip(self):
        original = items.from_uris(["file:///a"]) + items.from_text("snippet")
        store.save(original, self.path)
        self.assertEqual(store.load(self.path), original)

    def test_missing_file(self):
        self.assertEqual(store.load(self.path), [])

    def test_corrupt_file_is_set_aside(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as fh:
            fh.write("{not json")
        self.assertEqual(store.load(self.path), [])
        self.assertTrue(os.path.exists(self.path + ".bad"))


class ConfigTest(unittest.TestCase):
    def test_default_file_matches_defaults(self):
        self.assertEqual(config.parse(config.DEFAULT_INI), config.Config())

    def test_values_and_bad_values(self):
        with self.assertLogs("shelf.config", "WARNING"):
            cfg = config.parse("[shelf]\nedge = left\nwidth = 9000\nopen_on_hover = no\n"
                               "hotkey = Super+F6  # comment\nmonitor = DP-0\n")
        self.assertEqual(cfg.edge, "left")
        self.assertEqual(cfg.width, config.Config.width)
        self.assertFalse(cfg.open_on_hover)
        self.assertEqual(cfg.hotkey, "Super+F6")
        self.assertEqual(cfg.monitor, "DP-0")

    def test_app_rules(self):
        cfg = config.parse("[shelf]\nfloating_new_apps = on\n[apps]\nNuke = off\n"
                           "Brave-browser = on\n")
        self.assertEqual(cfg.floating_apps, {"Nuke": False, "Brave-browser": True})
        self.assertFalse(cfg.floating_for("Nuke"))
        self.assertFalse(cfg.floating_for("nuke"))
        self.assertTrue(cfg.floating_for("Brave-browser"))
        self.assertTrue(cfg.floating_for("Sublime_text"))
        self.assertTrue(cfg.floating_for(None))
        cfg.floating_new_apps = False
        self.assertFalse(cfg.floating_for("Sublime_text"))
        self.assertTrue(cfg.floating_for("Brave-browser"))
        cfg.floating_enabled = False
        self.assertFalse(cfg.floating_for("Brave-browser"))

    def test_bad_app_rule(self):
        with self.assertLogs("shelf.config", "WARNING"):
            cfg = config.parse("[apps]\nNuke = maybe\n")
        self.assertEqual(cfg.floating_apps, {})

    def test_empty_float_hotkey(self):
        self.assertEqual(config.parse("[shelf]\nfloat_hotkey =\n").float_hotkey, "")

    def test_bad_edge(self):
        with self.assertLogs("shelf.config", "WARNING"):
            self.assertEqual(config.parse("[shelf]\nedge = top\n").edge, "right")

    def test_save_round_trip(self):
        cfg = config.Config(monitor="DP-0", edge="left", width=150, min_items=5,
                            open_on_hover=False,
                            hotkey="Super+F6", empty_timeout_seconds=12,
                            floating_enabled=False, floating_offset=80, float_hotkey="Ctrl+F6",
                            floating_new_apps=False,
                            floating_apps={"Nuke": False, "Org.gnome.Nautilus": True})
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "shelf.ini")
            self.assertIsNone(config.save(cfg, path))
            self.assertEqual(config.load(path), cfg)

    def test_load_writes_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "shelf", "shelf.ini")
            self.assertEqual(config.load(path), config.Config())
            self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
