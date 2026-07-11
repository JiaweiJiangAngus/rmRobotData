#!/usr/bin/env python3
"""Tiny local proxy for testing Bilibili live HLS in the static dashboard."""

from __future__ import annotations

import json
import re
import shutil
import sys
import threading
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


DEFAULT_ROOM_ID = "82357"
HOST = "127.0.0.1"
PORT = 8765
ROOT = Path(__file__).resolve().parent
RECORDINGS_DIR = ROOT / "recordings"
FFMPEG_HEADERS = (
    "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36\r\n"
    "Referer: https://live.bilibili.com/\r\n"
    "Origin: https://live.bilibili.com\r\n"
)
URL_CACHE: dict[str, str] = {}
URL_CACHE_LOCK = threading.Lock()
RECORDINGS: dict[str, dict] = {}
RECORDINGS_LOCK = threading.Lock()


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


def safe_filename(value: str, fallback: str = "RoboMaster直播") -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", str(value or fallback))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._")
    return (cleaned or fallback)[:120]


def unique_recording_path(name: str, extension: str = "mp4") -> Path:
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    stem = safe_filename(name)
    extension = re.sub(r"[^a-z0-9]+", "", extension.lower()) or "mp4"
    for index in range(1000):
        suffix = f"_{index + 1}" if index else ""
        candidate = RECORDINGS_DIR / f"{stem}{suffix}.{extension}"
        if not candidate.exists():
            return candidate
    return RECORDINGS_DIR / f"{stem}_{int(time.time())}.{extension}"


def resolve_recording_url(raw_url: str, host: str) -> str:
    url = str(raw_url or "").strip()
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/"):
        url = f"http://{host}{url}"
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("录制源不是有效的 HTTP/HLS 地址")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("HTTP 录制源只能来自本地代理")
    return url


def public_recording_session(session: dict) -> dict:
    output_path = Path(session["outputPath"])
    payload = {
        "id": session["id"],
        "state": session["state"],
        "filename": session["filename"],
        "relativePath": str(output_path.relative_to(ROOT)) if output_path.is_relative_to(ROOT) else session["filename"],
        "outputPath": session["outputPath"],
        "viewName": session.get("viewName", ""),
        "matchName": session.get("matchName", ""),
        "startedAt": session.get("startedAt", 0),
        "endedAt": session.get("endedAt"),
        "returncode": session.get("returncode"),
    }
    started_at = float(session.get("startedAt") or time.time())
    ended_at = float(session.get("endedAt") or time.time())
    payload["elapsed"] = max(0, ended_at - started_at)
    try:
        payload["size"] = output_path.stat().st_size
    except OSError:
        payload["size"] = 0
    return payload


def active_recording_count() -> int:
    with RECORDINGS_LOCK:
        return sum(1 for session in RECORDINGS.values() if session.get("state") in {"recording", "stopping"})


def build_ffmpeg_args(source_url: str, output_path: Path) -> list[str]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("找不到 ffmpeg，无法启用本地 MP4 录制")
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-headers",
        FFMPEG_HEADERS,
        "-reconnect",
        "1",
        "-reconnect_streamed",
        "1",
        "-reconnect_delay_max",
        "5",
        "-rw_timeout",
        "15000000",
        "-i",
        source_url,
        "-map",
        "0",
        "-c",
        "copy",
        "-max_muxing_queue_size",
        "4096",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def watch_recording_session(session_id: str) -> None:
    with RECORDINGS_LOCK:
        session = RECORDINGS.get(session_id)
        process = session.get("process") if session else None
    if not session or not process:
        return
    returncode = process.wait()
    with RECORDINGS_LOCK:
        session = RECORDINGS.get(session_id)
        if not session:
            return
        session["returncode"] = returncode
        session["endedAt"] = time.time()
        if session.get("stopRequested"):
            session["state"] = "stopped"
        elif returncode == 0:
            session["state"] = "ended"
        else:
            session["state"] = "failed"


def start_recording_session(item: dict, host: str) -> dict:
    source_url = resolve_recording_url(item.get("url") or item.get("source") or "", host)
    match_name = safe_filename(item.get("matchName") or item.get("name") or "RoboMaster直播")
    view_name = safe_filename(item.get("viewName") or "")
    name = safe_filename(item.get("name") or (f"{match_name}_{view_name}" if view_name else match_name))
    output_path = unique_recording_path(name, "mp4")
    log_path = output_path.with_suffix(output_path.suffix + ".log")
    args = build_ffmpeg_args(source_url, output_path)
    session_id = uuid.uuid4().hex[:12]
    with log_path.open("ab") as log_file:
        log_file.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] start {source_url}\n".encode("utf-8"))
        process = subprocess.Popen(
            args,
            cwd=str(ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=log_file,
        )
    session = {
        "id": session_id,
        "state": "recording",
        "process": process,
        "url": source_url,
        "filename": output_path.name,
        "outputPath": str(output_path),
        "logPath": str(log_path),
        "viewName": view_name,
        "matchName": match_name,
        "startedAt": time.time(),
        "endedAt": None,
        "returncode": None,
        "stopRequested": False,
    }
    with RECORDINGS_LOCK:
        RECORDINGS[session_id] = session
    watcher = threading.Thread(target=watch_recording_session, args=(session_id,), daemon=True)
    watcher.start()
    return public_recording_session(session)


def stop_recording_session(session_id: str) -> dict:
    with RECORDINGS_LOCK:
        session = RECORDINGS.get(session_id)
        process = session.get("process") if session else None
        if session:
            session["stopRequested"] = True
            if session.get("state") == "recording":
                session["state"] = "stopping"
    if not session or not process:
        return {"id": session_id, "state": "missing"}
    if process.poll() is None:
        try:
            if process.stdin:
                process.stdin.write(b"q\n")
                process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
    with RECORDINGS_LOCK:
        session = RECORDINGS.get(session_id, session)
        if session.get("state") == "stopping":
            session["state"] = "stopped"
            session["endedAt"] = session.get("endedAt") or time.time()
            session["returncode"] = process.returncode
        return public_recording_session(session)


class BiliProxyHandler(BaseHTTPRequestHandler):
    server_version = "BiliLiveProxy/0.1"

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS")
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
        elif parsed.path == "/record/health":
            self.handle_record_health(send_body)
        elif parsed.path == "/record/status":
            self.handle_record_status(send_body)
        else:
            self.send_json(404, {"error": "not found"}, send_body)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/record/start":
            self.handle_record_start()
        elif parsed.path == "/record/stop":
            self.handle_record_stop()
        else:
            self.send_json(404, {"error": "not found"}, True)

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

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        body = self.rfile.read(min(length, 1024 * 1024))
        if not body:
            return {}
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def handle_record_health(self, send_body: bool) -> None:
        ffmpeg = shutil.which("ffmpeg")
        self.send_json(200, {
            "ok": bool(ffmpeg),
            "ffmpeg": bool(ffmpeg),
            "ffmpegPath": ffmpeg or "",
            "outputDir": str(RECORDINGS_DIR),
            "active": active_recording_count(),
        }, send_body)

    def handle_record_status(self, send_body: bool) -> None:
        with RECORDINGS_LOCK:
            sessions = [public_recording_session(session) for session in RECORDINGS.values()]
        self.send_json(200, {
            "ok": True,
            "outputDir": str(RECORDINGS_DIR),
            "active": sum(1 for session in sessions if session.get("state") in {"recording", "stopping"}),
            "sessions": sessions[-80:],
        }, send_body)

    def handle_record_start(self) -> None:
        try:
            payload = self.read_json_body()
            items = payload.get("items") or []
            if not isinstance(items, list) or not items:
                self.send_json(400, {"ok": False, "error": "没有可录制的直播源"}, True)
                return
            if len(items) > 12:
                self.send_json(400, {"ok": False, "error": "一次最多录制 12 路视角"}, True)
                return
            sessions = []
            errors = []
            host = self.headers.get("Host", f"{HOST}:{PORT}")
            for item in items:
                try:
                    if not isinstance(item, dict):
                        raise ValueError("录制项格式错误")
                    sessions.append(start_recording_session(item, host))
                except Exception as error:  # Keep other selected views starting when one source is bad.
                    errors.append({"name": item.get("name", "") if isinstance(item, dict) else "", "error": str(error)})
            if not sessions:
                self.send_json(500, {"ok": False, "error": errors[0]["error"] if errors else "录制启动失败", "errors": errors}, True)
                return
            self.send_json(200, {"ok": True, "sessions": sessions, "errors": errors, "outputDir": str(RECORDINGS_DIR)}, True)
        except json.JSONDecodeError as error:
            self.send_json(400, {"ok": False, "error": f"JSON 解析失败：{error}"}, True)
        except Exception as error:
            self.send_json(500, {"ok": False, "error": str(error)}, True)

    def handle_record_stop(self) -> None:
        try:
            payload = self.read_json_body()
        except Exception:
            payload = {}
        ids = payload.get("ids") if isinstance(payload, dict) else None
        if not isinstance(ids, list) or not ids:
            with RECORDINGS_LOCK:
                ids = [session_id for session_id, session in RECORDINGS.items() if session.get("state") in {"recording", "stopping"}]
        sessions = [stop_recording_session(str(session_id)) for session_id in ids]
        self.send_json(200, {"ok": True, "sessions": sessions, "outputDir": str(RECORDINGS_DIR)}, True)

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
