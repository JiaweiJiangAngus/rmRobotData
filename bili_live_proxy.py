#!/usr/bin/env python3
"""Tiny local proxy for testing Bilibili live HLS in the static dashboard."""

from __future__ import annotations

import json
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


DEFAULT_ROOM_ID = "82357"
HOST = "127.0.0.1"
PORT = 8765
ROOT = Path(__file__).resolve().parent
URL_CACHE: dict[str, str] = {}
URL_CACHE_LOCK = threading.Lock()


def cache_url(url: str) -> str:
    with URL_CACHE_LOCK:
        key = format(abs(hash(url)), "x")
        URL_CACHE[key] = url
    return f"/bili/cached/{key}"


def fetch_url(url: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    request_headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
        "Referer": "https://live.bilibili.com/",
        "Origin": "https://live.bilibili.com",
    }
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers.items()), error.read()


def proxy_url(url: str) -> str:
    return cache_url(url)


def rewrite_m3u8(payload: bytes, base_url: str) -> bytes:
    text = payload.decode("utf-8", errors="replace")

    def map_replacer(match: re.Match[str]) -> str:
        quoted = match.group(1)
        resolved = urllib.parse.urljoin(base_url, quoted)
        return f'URI="{proxy_url(resolved)}"'

    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append(line)
        elif stripped.startswith("#"):
            lines.append(re.sub(r'URI="([^"]+)"', map_replacer, line))
        else:
            lines.append(proxy_url(urllib.parse.urljoin(base_url, stripped)))
    return ("\n".join(lines) + "\n").encode("utf-8")


class BiliProxyHandler(BaseHTTPRequestHandler):
    server_version = "BiliLiveProxy/0.1"

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Range, Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Expose-Headers", "Content-Length, Content-Range, Accept-Ranges")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_HEAD(self) -> None:
        self.do_GET(send_body=False)

    def do_GET(self, send_body: bool = True) -> None:
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path in ("/", "/dashboard", "/index.html"):
            self.send_dashboard(send_body)
        elif parsed.path == "/bili/live":
            self.handle_live(query, send_body)
        elif parsed.path == "/bili/proxy":
            self.handle_proxy(query, send_body)
        elif parsed.path.startswith("/bili/cached/"):
            self.handle_cached(parsed.path.rsplit("/", 1)[-1], send_body)
        else:
            self.send_json(404, {"error": "not found"}, send_body)

    def send_dashboard(self, send_body: bool) -> None:
        dashboard = ROOT / "docs" / "index.html"
        if not dashboard.exists():
            self.send_json(404, {"error": "docs/index.html not found; run ./publish_pages.bash first"}, send_body)
            return
        body = dashboard.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def handle_live(self, query: dict[str, list[str]], send_body: bool) -> None:
        room_id = query.get("room_id", [DEFAULT_ROOM_ID])[0]
        play_url = (
            "https://api.live.bilibili.com/xlive/web-room/v2/index/getRoomPlayInfo"
            f"?room_id={urllib.parse.quote(room_id)}"
            "&protocol=0,1&format=0,1,2&codec=0,1&qn=10000&platform=web&ptype=8"
        )
        room_url = f"https://api.live.bilibili.com/room/v1/Room/get_info?room_id={urllib.parse.quote(room_id)}"
        play_status, _, play_body = fetch_url(play_url)
        room_status, _, room_body = fetch_url(room_url)
        try:
            payload = {
                "playData": json.loads(play_body.decode("utf-8", errors="replace")),
                "roomData": json.loads(room_body.decode("utf-8", errors="replace")) if room_status < 400 else None,
            }
        except json.JSONDecodeError as error:
            self.send_json(502, {"error": f"Bilibili response is not JSON: {error}"}, send_body)
            return
        self.rewrite_play_payload(payload)
        self.send_json(play_status if play_status >= 400 else 200, payload, send_body)

    def rewrite_play_payload(self, payload: dict) -> None:
        origin = f"http://{self.headers.get('Host', f'{HOST}:{PORT}')}"
        playurl = payload.get("playData", {}).get("data", {}).get("playurl_info", {}).get("playurl", {})
        for stream in playurl.get("stream", []) or []:
            for fmt in stream.get("format", []) or []:
                for codec in fmt.get("codec", []) or []:
                    url_infos = codec.get("url_info") or []
                    if not codec.get("base_url") or not url_infos:
                        continue
                    first = url_infos[0]
                    full_url = f"{first.get('host', '')}{codec.get('base_url', '')}{first.get('extra', '')}"
                    if not full_url.startswith("https://"):
                        continue
                    codec["base_url"] = cache_url(full_url)
                    codec["url_info"] = [{"host": origin, "extra": "", "stream_ttl": first.get("stream_ttl", 0)}]
        payload["proxiedStreams"] = True

    def handle_proxy(self, query: dict[str, list[str]], send_body: bool) -> None:
        raw_url = query.get("url", [""])[0]
        self.proxy_remote_url(raw_url, send_body)

    def handle_cached(self, key: str, send_body: bool) -> None:
        with URL_CACHE_LOCK:
            raw_url = URL_CACHE.get(key, "")
        self.proxy_remote_url(raw_url, send_body)

    def proxy_remote_url(self, raw_url: str, send_body: bool) -> None:
        parsed = urllib.parse.urlparse(raw_url)
        if parsed.scheme != "https" or not parsed.netloc.endswith(("bilivideo.com", "bilibili.com")):
            self.send_json(400, {"error": "only Bilibili HTTPS URLs can be proxied"}, send_body)
            return
        request_headers: dict[str, str] = {}
        if "Range" in self.headers:
            request_headers["Range"] = self.headers["Range"]
        status, headers, body = fetch_url(raw_url, request_headers)
        content_type = headers.get("Content-Type", "application/octet-stream")
        if "mpegurl" in content_type or raw_url.split("?", 1)[0].endswith(".m3u8"):
            body = rewrite_m3u8(body, raw_url)
            content_type = "application/vnd.apple.mpegurl; charset=utf-8"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", headers.get("Accept-Ranges", "bytes"))
        if "Content-Range" in headers:
            self.send_header("Content-Range", headers["Content-Range"])
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def send_json(self, status: int, payload: dict, send_body: bool) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("[bili-proxy] " + format % args + "\n")


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), BiliProxyHandler)
    print(f"Dashboard: http://{HOST}:{PORT}/")
    print(f"Bilibili live proxy: http://{HOST}:{PORT}/bili/live?room_id={DEFAULT_ROOM_ID}")
    print("Keep this terminal open while testing the dashboard.")
    server.serve_forever()


if __name__ == "__main__":
    main()
