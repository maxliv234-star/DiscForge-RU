"""DiscForge TV LAN media server (Python standard library, no external packages).

Serves only explicit video files under --media-root. This first alpha does NOT
stream physical Blu-ray discs, does NOT remove copy protection, and does NOT
emulate BD-J menus. Designed for a trusted home network, without TLS.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from time import monotonic
from tv_server.discovery import start_discovery
from urllib.parse import urlsplit

EXTENSIONS = {".mp4", ".m4v", ".mkv", ".mov", ".m2ts"}
TOKEN_HEADER = "X-DiscForge-Token"
RANGE_PATTERN = re.compile(r"^bytes=(\d*)-(\d*)$")


def media_catalog(root: Path) -> dict[str, Path]:
    """Scan the selected root, ignore symlinks, hidden files and traversal."""
    root = root.resolve(strict=True)
    items: dict[str, Path] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink() or path.suffix.lower() not in EXTENSIONS:
            continue
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            continue
        identifier = hashlib.sha256(relative.as_posix().encode("utf-8")).hexdigest()[:24]
        items[identifier] = resolved
    return items


def parse_range(value: str | None, size: int) -> tuple[int, int, bool]:
    """Return inclusive byte boundaries (start, end, is_partial)."""
    if size < 0:
        raise ValueError("Negative file size")
    if value is None:
        return 0, max(0, size - 1), False
    match = RANGE_PATTERN.fullmatch(value.strip())
    if not match or size == 0:
        raise ValueError("Invalid range")
    first, last = match.groups()
    if not first and not last:
        raise ValueError("Invalid range")
    if not first:
        length = int(last)
        if length <= 0:
            raise ValueError("Invalid suffix length")
        return max(0, size - length), size - 1, True
    start = int(first)
    end = min(int(last), size - 1) if last else size - 1
    if start >= size or end < start:
        raise ValueError("Range out of bounds")
    return start, end, True


def poster_for(file: Path, root: Path) -> Path | None:
    """Only serve a small local sidecar artwork file inside the media root."""
    for candidate in (file.with_suffix(".jpg"), file.with_suffix(".png"),
                      file.parent / "folder.jpg", file.parent / "folder.png"):
        if candidate.is_symlink() or not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root):
            continue
        try:
            if resolved.stat().st_size <= 8 * 1024 * 1024:
                return resolved
        except OSError:
            pass
    return None


def make_handler(root: Path, token: str):
    if len(token) < 16:
        raise ValueError("Token must contain at least 16 characters")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Media root must be a directory")

    # Multiple parallel HTTP Range requests must not rescan an entire NAS on
    # each request. An index is refreshed at most every five seconds; new
    # files become visible automatically without restarting the server.
    catalog_lock = Lock()
    catalog_entries: dict[str, Path] = {}
    catalog_updated_at = float("-inf")

    def current_catalog() -> dict[str, Path]:
        nonlocal catalog_entries, catalog_updated_at
        with catalog_lock:
            now = monotonic()
            if now - catalog_updated_at >= 5.0:
                catalog_entries = media_catalog(root)
                catalog_updated_at = now
            return catalog_entries

    class Handler(BaseHTTPRequestHandler):
        server_version = "DiscForge-TV/0.1"
        protocol_version = "HTTP/1.1"

        def reply(self, status: int, data: bytes = b"", mime: str = "application/json", extra=None):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def serve(self):
            if self.headers.get(TOKEN_HEADER) is None or not hmac.compare_digest(
                    self.headers.get(TOKEN_HEADER, ""), token):
                self.reply(401, b'{"error":"Unauthorized"}')
                return
            path = urlsplit(self.path).path
            if path == "/api/v1/library":
                entries = []
                for item_id, file in current_catalog().items():
                    try:
                        size = file.stat().st_size
                    except OSError:
                        continue
                    relative = file.relative_to(root)
                    category = relative.parts[0] if len(relative.parts) > 1 else "Фильмы"
                    artwork = poster_for(file, root)
                    entries.append({"id": item_id, "title": file.stem, "size": size,
                                    "category": category,
                                    "poster": "/api/v1/poster/" + item_id if artwork else None,
                                    "url": "/api/v1/media/" + item_id})
                entries.sort(key=lambda row: row["title"].casefold())
                payload = json.dumps({"version": 1, "items": entries},
                                     ensure_ascii=False).encode("utf-8")
                self.reply(200, payload, "application/json; charset=utf-8")
                return
            poster_prefix = "/api/v1/poster/"
            if path.startswith(poster_prefix):
                identifier = path[len(poster_prefix):]
                if not re.fullmatch(r"[a-f0-9]{24}", identifier):
                    self.reply(404, b'{"error":"Not found"}')
                    return
                file = current_catalog().get(identifier)
                artwork = poster_for(file, root) if file is not None else None
                if artwork is None:
                    self.reply(404, b'{"error":"Not found"}')
                    return
                try:
                    self.send_media(artwork)
                except OSError:
                    self.close_connection = True
                return
            prefix = "/api/v1/media/"
            if path.startswith(prefix):
                identifier = path[len(prefix):]
                if not re.fullmatch(r"[a-f0-9]{24}", identifier):
                    self.reply(404, b'{"error":"Not found"}')
                    return
                file = current_catalog().get(identifier)
                if file is None:
                    self.reply(404, b'{"error":"Not found"}')
                    return
                try:
                    self.send_media(file)
                except OSError:
                    # Files may disappear between scanning and opening.
                    # Avoid claiming successful playback when the source changed.
                    self.close_connection = True
                return
            self.reply(404, b'{"error":"Not found"}')

        def send_media(self, file: Path):
            with file.open("rb") as stream:
                size = os.fstat(stream.fileno()).st_size
                try:
                    start, end, partial = parse_range(self.headers.get("Range"), size)
                except ValueError:
                    self.reply(416, b"", extra={"Content-Range": f"bytes */{size}",
                                               "Accept-Ranges": "bytes"})
                    return
                remaining = (end - start + 1) if size else 0
                mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                self.send_response(206 if partial else 200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(remaining))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("X-Content-Type-Options", "nosniff")
                if partial:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.end_headers()
                if self.command == "HEAD":
                    return
                stream.seek(start)
                try:
                    while remaining:
                        chunk = stream.read(min(256 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        def do_GET(self):
            self.serve()

        def do_HEAD(self):
            self.serve()

        def log_message(self, fmt, *args):
            # Never log secret authentication headers.
            super().log_message(fmt, *args)

    return Handler


def saved_token(file: Path) -> str:
    file.parent.mkdir(parents=True, exist_ok=True)
    if file.exists():
        token = file.read_text(encoding="utf-8").strip()
        if len(token) < 16:
            raise ValueError("Invalid token file; expected >= 16 characters")
        return token
    token = secrets.token_urlsafe(24)
    with file.open("x", encoding="utf-8") as handle:
        handle.write(token + "\n")
    try:
        file.chmod(0o600)
    except OSError:
        pass
    return token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DiscForge TV: local-network video library")
    parser.add_argument("--media-root", required=True, help="Folder with local MP4/MKV files")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Use 0.0.0.0 ONLY for a trusted home network")
    parser.add_argument("--port", type=int, default=8098)
    parser.add_argument("--token-file",
                        default=str(Path.home() / ".discforge-tv" / "token"))
    parser.add_argument("--no-print-token", action="store_true",
                        help="Do not expose the pairing secret in unattended logs")
    parser.add_argument("--no-discovery", action="store_true",
                        help="Disable optional UDP LAN service discovery")
    parser.add_argument("--discovery-port", type=int, default=8099)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535 or not 1 <= args.discovery_port <= 65535:
        parser.error("Invalid TCP/UDP port")
    root = Path(args.media_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        parser.error("--media-root must be a directory")
    token = saved_token(Path(args.token_file).expanduser())
    server = ThreadingHTTPServer((args.host, args.port), make_handler(root, token))
    print(f"DiscForge TV: http://{args.host}:{server.server_port}", flush=True)
    if args.no_print_token:
        print("Код подключения хранится в указанном --token-file", flush=True)
    else:
        print(f"Код подключения для ТВ: {token}", flush=True)
    print("Только локальная сеть. Не открывайте порт на роутере!", flush=True)
    discovery = None
    if not args.no_discovery and args.host != "127.0.0.1":
        discovery = start_discovery(args.discovery_port, args.port)
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        if discovery is not None:
            discovery.close()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
