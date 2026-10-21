import os
import tempfile
import unittest

from shelf.apps import SeenApps


class SeenAppsTest(unittest.TestCase):
    def test_recent_order_and_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "apps.json")
            seen = SeenApps(path)
            seen.note("Nuke")
            seen.note("Org.gnome.Nautilus")
            seen._seen["Nuke"] += 10  # most recent
            seen.note("Nuke")
            again = SeenApps(path)
            self.assertEqual(again.recent(), ["Nuke", "Org.gnome.Nautilus"])
            self.assertEqual(again.recent(also=["nuke", "Blender"]),
                             ["Nuke", "Org.gnome.Nautilus", "Blender"])

    def test_corrupt_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "apps.json")
            with open(path, "w") as fh:
                fh.write("[")
            with self.assertLogs("shelf.apps", "WARNING"):
                self.assertEqual(SeenApps(path).recent(), [])


if __name__ == "__main__":
    unittest.main()
