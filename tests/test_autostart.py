import os
import tempfile
import unittest

from shelf import autostart


class AutostartTest(unittest.TestCase):
    def test_enable_disable(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "autostart", "shelf.desktop")
            self.assertFalse(autostart.is_enabled(path))
            self.assertIsNone(autostart.set_enabled(True, path))
            self.assertTrue(autostart.is_enabled(path))
            with open(path) as fh:
                self.assertIn("Exec=" + autostart.LAUNCHER, fh.read())
            self.assertIsNone(autostart.set_enabled(False, path))
            self.assertFalse(os.path.exists(path))
            self.assertIsNone(autostart.set_enabled(False, path))

    def test_appimage_launcher(self):
        os.environ["APPIMAGE"] = "/home/me/Apps/Shelf-x86_64.AppImage"
        try:
            entry = autostart.desktop_entry()
        finally:
            del os.environ["APPIMAGE"]
        self.assertIn("Exec=/home/me/Apps/Shelf-x86_64.AppImage\n", entry)
        self.assertNotIn("/tmp/", entry)

    def test_disabled_by_desktop(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "shelf.desktop")
            with open(path, "w") as fh:
                fh.write(autostart.desktop_entry() + "Hidden=true\n")
            self.assertFalse(autostart.is_enabled(path))

    def test_quoting(self):
        self.assertEqual(autostart._quote("/opt/shelf/bin/shelf"), "/opt/shelf/bin/shelf")
        self.assertEqual(autostart._quote('/my tools/bin/shelf'), '"/my tools/bin/shelf"')
        self.assertEqual(autostart._quote('/a"b/$x'), '"/a\\"b/\\$x"')


if __name__ == "__main__":
    unittest.main()
