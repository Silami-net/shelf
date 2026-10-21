import base64
import http.server
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from shelf import fetch

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


class HtmlTest(unittest.TestCase):
    def test_plain_image(self):
        self.assertEqual(fetch.image_in_html('<img src="https://x.org/a/cat.jpg" alt="Cat">'),
                         "https://x.org/a/cat.jpg")

    def test_linked_image(self):
        html = '<a href="https://x.org/page"><img src="https://x.org/full.png"></a>'
        self.assertEqual(fetch.image_in_html(html), "https://x.org/full.png")

    def test_firefox_wrapper_and_data_url(self):
        html = '<html><body>\n<!--StartFragment--><img src="data:image/png;base64,AAAA"><!--EndFragment-->\n</body></html>'
        self.assertEqual(fetch.image_in_html(html), "data:image/png;base64,AAAA")

    def test_text_with_images_is_not_a_picture(self):
        self.assertIsNone(fetch.image_in_html('<p>Some text <img src="https://x.org/i.png"></p>'))

    def test_link_without_image(self):
        self.assertIsNone(fetch.image_in_html('<a href="https://x.org">Example</a>'))

    def test_relative_or_blob_source(self):
        self.assertIsNone(fetch.image_in_html('<img src="/static/a.png">'))
        self.assertIsNone(fetch.image_in_html('<img src="blob:https://x.org/123">'))

    def test_decode(self):
        html = '<img src="https://x.org/é.png">'
        for raw in (html.encode(), html.encode("utf-16"), html.encode("utf-16-le")):
            self.assertEqual(fetch.decode_html(raw), html)


class NameTest(unittest.TestCase):
    def test_names(self):
        cases = [
            ("https://x.org/img/sunset%20v2.jpg?w=800", "image/jpeg", "sunset v2.jpg"),
            ("https://x.org/photo.jpeg", "image/jpeg", "photo.jpeg"),
            ("https://x.org/render", "image/png", "render.png"),
            ("https://x.org/image.php?id=3", "image/gif", "image.php.gif"),
            ("https://x.org/fake.png", "image/webp", "fake.webp"),
            ("https://x.org/", "image/png", "image.png"),
            ("data:image/svg+xml;base64,AAAA", "image/svg+xml", "image.svg"),
            ("", "image/png", "image.png"),
        ]
        for url, mime, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(fetch.file_name(url, mime), expected)

    def test_data_url(self):
        data, mime = fetch.decode_data_url("data:image/png;base64," + base64.b64encode(PNG).decode())
        self.assertEqual((data, mime), (PNG, "image/png"))
        self.assertEqual(fetch.decode_data_url("data:text/plain,hi%20there"),
                         (b"hi there", "text/plain"))


class DropChoiceTest(unittest.TestCase):
    def test_first_request(self):
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        from shelf.dnd import first_request
        browser = {"text/uri-list", "text/html", "text/plain", "text/x-moz-url"}
        self.assertEqual(first_request(browser), "text/html")
        self.assertEqual(first_request(browser | {"image/png"}), "text/html")
        self.assertEqual(first_request({"image/png", "TARGETS"}), "image/png")
        # Files from a file manager, selected text, plain text: unchanged behaviour.
        self.assertIsNone(first_request({"text/uri-list", "text/plain", "UTF8_STRING"}))
        self.assertIsNone(first_request({"text/html", "text/plain"}))
        self.assertIsNone(first_request({"UTF8_STRING"}))


class _Server(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body, mime = (PNG, "image/png") if self.path.startswith("/pic") else (b"<html>", "text/html")
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(fetch, "DOWNLOAD_DIR", self.dir.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.dir.cleanup)
        self.server = http.server.HTTPServer(("127.0.0.1", 0), _Server)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def test_downloads_picture_with_its_name(self):
        path = fetch._download(self.base + "/pic/sh010_v003.png")
        self.assertEqual(os.path.basename(path), "sh010_v003.png")
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), PNG)

    def test_refuses_web_pages(self):
        with self.assertRaises(ValueError):
            fetch._download(self.base + "/page.html")

    def test_data_url(self):
        path = fetch._download("data:image/png;base64," + base64.b64encode(PNG).decode())
        self.assertEqual(os.path.basename(path), "image.png")

    def test_clean_keeps_shelf_items_and_recent_files(self):
        kept = fetch.save(PNG, "kept.png", self.dir.name)
        old = fetch.save(PNG, "old.png", self.dir.name)
        recent = fetch.save(PNG, "recent.png", self.dir.name)
        long_ago = time.time() - 2 * fetch.KEEP_SECONDS
        for p in (kept, old):
            os.utime(os.path.dirname(p), (long_ago, long_ago))
        fetch.clean([kept], self.dir.name)
        self.assertTrue(os.path.exists(kept))
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(recent))


if __name__ == "__main__":
    unittest.main()
