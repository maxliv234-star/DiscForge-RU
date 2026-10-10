"""Network and range tests for the DiscForge TV server."""
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tv_server.server import make_handler, media_catalog, parse_range, saved_token

KEY = "test-token-which-is-long-enough"


class RangeTests(unittest.TestCase):
    def test_entire_file(self):
        self.assertEqual(parse_range(None, 10), (0, 9, False))

    def test_first_last_and_suffix(self):
        self.assertEqual(parse_range("bytes=0-3", 10), (0, 3, True))
        self.assertEqual(parse_range("bytes=8-", 10), (8, 9, True))
        self.assertEqual(parse_range("bytes=-4", 10), (6, 9, True))
        self.assertEqual(parse_range("bytes=0-300", 10), (0, 9, True))

    def test_invalid_ranges(self):
        for header in ("bytes=100-", "bytes=9-2", "bytes=0-1,3-5", "bytes=-0", "bad"):
            with self.subTest(header=header), self.assertRaises(ValueError):
                parse_range(header, 10)

    def test_zero_length(self):
        self.assertEqual(parse_range(None, 0), (0, 0, False))
        with self.assertRaises(ValueError):
            parse_range("bytes=0-", 0)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "Фильм.mp4").write_bytes(b"0123456789")
        (self.root / ".hidden.mp4").write_bytes(b"not listed")
        (self.root / "private.txt").write_text("private")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.root, KEY))
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.base = "http://127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=3)
        self.tmp.cleanup()

    def request(self, path, headers=None, method="GET"):
        request = Request(self.base + path, method=method, headers=headers or {})
        return urlopen(request, timeout=3)

    def test_requires_token(self):
        with self.assertRaises(HTTPError) as cm:
            self.request("/api/v1/library")
        self.assertEqual(cm.exception.code, 401)

    def test_library_and_stream(self):
        with self.request("/api/v1/library", {"X-DiscForge-Token": KEY}) as resp:
            self.assertEqual(resp.status, 200)
            entries = json.loads(resp.read().decode("utf-8"))["items"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "Фильм")
        url = entries[0]["url"]
        with self.request(url, {"X-DiscForge-Token": KEY, "Range": "bytes=2-5"}) as resp:
            self.assertEqual(resp.status, 206)
            self.assertEqual(resp.headers["Content-Range"], "bytes 2-5/10")
            self.assertEqual(resp.read(), b"2345")
        with self.request(url, {"X-DiscForge-Token": KEY}, "HEAD") as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers["Content-Length"], "10")
        with self.request(url, {"X-DiscForge-Token": KEY}) as resp:
            self.assertEqual(resp.read(), b"0123456789")

    def test_range_rejected(self):
        identifier = next(iter(media_catalog(self.root)))
        with self.assertRaises(HTTPError) as cm:
            self.request("/api/v1/media/" + identifier,
                         {"X-DiscForge-Token": KEY, "Range": "bytes=50-"})
        self.assertEqual(cm.exception.code, 416)

    def test_traversal_not_allowed(self):
        with self.assertRaises(HTTPError) as cm:
            self.request("/api/v1/media/../../private.txt",
                         {"X-DiscForge-Token": KEY})
        self.assertEqual(cm.exception.code, 404)

    def test_catalog_cached_for_repeated_ranges_and_refreshed(self):
        from tv_server import server as module
        real_catalog = module.media_catalog
        with patch.object(module, "media_catalog", wraps=real_catalog) as scan:
            with self.request("/api/v1/library", {"X-DiscForge-Token": KEY}) as resp:
                item = json.loads(resp.read())["items"][0]
            for suffix in ("bytes=0-1", "bytes=3-5", "bytes=8-9"):
                with self.request(item["url"], {"X-DiscForge-Token": KEY,
                                                "Range": suffix}) as resp:
                    self.assertEqual(resp.status, 206)
                    resp.read()
            self.assertEqual(scan.call_count, 1,
                             "Reading several video chunks must not rescan the entire library")
            # A fresh handler must see new media after a cache refresh.
            # Replace monotonic rather than sleep so the test is fast.
            with patch.object(module, "monotonic", return_value=float("inf")):
                (self.root / "Другой.mp4").write_bytes(b"test")
                with self.request("/api/v1/library", {"X-DiscForge-Token": KEY}) as resp:
                    updated = json.loads(resp.read())["items"]
            self.assertEqual(len(updated), 2)
            self.assertEqual(scan.call_count, 2)

    def test_token_storage(self):
        path = self.root / "config" / "token"
        one = saved_token(path)
        self.assertEqual(one, saved_token(path))
        self.assertGreaterEqual(len(one), 16)

    def test_no_symlinks(self):
        outside = self.root.parent / "outside.mp4"
        try:
            (self.root / "fake.mp4").symlink_to(outside)
        except (NotImplementedError, OSError):
            self.skipTest("No symlink permission")
        self.assertEqual(len(media_catalog(self.root)), 1)


if __name__ == "__main__":
    unittest.main()
