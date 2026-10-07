from __future__ import annotations

import json
import mimetypes
import os
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
TASK_DIR = Path(os.getenv("FB_EXTENSION_TASK_DIR", str(ROOT / "data" / "extension_tasks")))
HOST = "127.0.0.1"
PORT = int(os.getenv("FB_EXTENSION_BRIDGE_PORT", "8766"))
LEASE_SECONDS = 15 * 60


def _task_path(task_id: str) -> Path:
    safe = "".join(ch for ch in task_id if ch.isalnum() or ch in "-_.")
    if not safe or safe != task_id:
        raise ValueError("invalid task id")
    return TASK_DIR / f"{safe}.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _next_task() -> dict | None:
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for path in sorted(TASK_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime):
        try:
            data = _load(path)
        except Exception:
            continue
        status = str(data.get("status", "pending"))
        leased_at = float(data.get("leased_at_epoch") or 0)
        if status == "leased" and leased_at and now - leased_at <= LEASE_SECONDS:
            continue
        if status not in {"pending", "leased"}:
            continue
        data["status"] = "leased"
        data["leased_at_epoch"] = now
        data["leased_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        _save(path, data)
        return {
            "task_id": data["task_id"],
            "group_url": data["group_url"],
            "group_id": data.get("group_id"),
            "body": data["body"],
            "image_count": len(data.get("images") or []),
            "allow_images": bool(data.get("allow_images", True)),
            "action": str(data.get("action") or "post"),
        }
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "FBExtensionBridge/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"bridge {self.address_string()} {fmt % args}", flush=True)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Cache-Control", "no-store")

    def _json(self, status: int, payload: dict | None = None) -> None:
        body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        if payload is not None:
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json(HTTPStatus.OK, {"ok": True, "profile": "Default"})
            return
        if parsed.path == "/next":
            task = _next_task()
            if task is None:
                self._json(HTTPStatus.NO_CONTENT)
            else:
                self._json(HTTPStatus.OK, task)
            return
        if parsed.path == "/event":
            params = parse_qs(parsed.query)
            self._update_event({
                "task_id": (params.get("task_id") or [""])[0],
                "stage": (params.get("stage") or [""])[0],
            })
            return
        if parsed.path == "/result":
            params = parse_qs(parsed.query)
            self._update_result({
                "task_id": (params.get("task_id") or [""])[0],
                "status": (params.get("status") or [""])[0],
                "permalink": (params.get("permalink") or [""])[0],
                "error": (params.get("error") or [""])[0],
            })
            return
        if parsed.path.startswith("/status/"):
            task_id = parsed.path.split("/", 2)[2]
            try:
                task = _load(_task_path(task_id))
            except Exception:
                self._json(HTTPStatus.NOT_FOUND, {"error": "task_not_found"})
                return
            self._json(HTTPStatus.OK, {
                "task_id": task_id,
                "status": task.get("status"),
                "stage": task.get("stage"),
                "result": task.get("result"),
            })
            return
        if parsed.path.startswith("/task/"):
            task_id = parsed.path.split("/", 2)[2]
            try:
                task = _load(_task_path(task_id))
            except Exception:
                self._json(HTTPStatus.NOT_FOUND, {"error": "task_not_found"})
                return
            self._json(HTTPStatus.OK, {
                "task_id": task_id,
                "status": task.get("status"),
                "stage": task.get("stage"),
                "group_url": task.get("group_url"),
                "group_id": task.get("group_id"),
                "body": task.get("body") or "",
                "image_count": len(task.get("images") or []),
                "allow_images": bool(task.get("allow_images", True)),
                "action": str(task.get("action") or "post"),
                "result": task.get("result"),
            })
            return
        if parsed.path.startswith("/image/"):
            self._serve_image(parsed.path)
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def _serve_image(self, request_path: str) -> None:
        parts = request_path.strip("/").split("/")
        if len(parts) != 3:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        _, task_id, raw_index = parts
        try:
            index = int(raw_index)
            task = _load(_task_path(task_id))
            images = task.get("images") or []
            image = Path(images[index])
        except (ValueError, IndexError, OSError, json.JSONDecodeError):
            self._json(HTTPStatus.NOT_FOUND, {"error": "image_not_found"})
            return
        try:
            root = Path(task.get("image_root") or ROOT).resolve()
            resolved = image.resolve()
            if root not in resolved.parents and resolved != root:
                raise ValueError("image outside allowed root")
            data = resolved.read_bytes()
        except (OSError, ValueError):
            self._json(HTTPStatus.NOT_FOUND, {"error": "image_not_found"})
            return
        mime = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self._cors()
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0 or length > 1024 * 1024:
            raise ValueError("invalid body length")
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("body must be object")
        return data

    def do_POST(self) -> None:
        try:
            data = self._read_json_body()
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
            return
        parsed = urlparse(self.path)
        if parsed.path == "/event":
            self._update_event(data)
            return
        if parsed.path == "/result":
            self._update_result(data)
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def _update_event(self, data: dict) -> None:
        task_id = str(data.get("task_id") or "")
        stage = str(data.get("stage") or "")
        if not task_id or stage not in {"tab_opened", "composer_ready", "click_started"}:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_event"})
            return
        try:
            path = _task_path(task_id)
            task = _load(path)
        except Exception:
            self._json(HTTPStatus.NOT_FOUND, {"error": "task_not_found"})
            return
        task["stage"] = stage
        task[f"{stage}_at_epoch"] = time.time()
        _save(path, task)
        self._json(HTTPStatus.OK, {"ok": True})

    def _update_result(self, data: dict) -> None:
        task_id = str(data.get("task_id") or "")
        status = str(data.get("status") or "")
        allowed = {"posted", "uncertain", "failed_before_click", "failed_after_click", "session_expired", "session_ok"}
        if not task_id or status not in allowed:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_result"})
            return
        try:
            path = _task_path(task_id)
            task = _load(path)
        except Exception:
            self._json(HTTPStatus.NOT_FOUND, {"error": "task_not_found"})
            return
        if str(task.get("status") or "") == "finished":
            self._json(HTTPStatus.OK, {"ok": True, "duplicate": True, "result": task.get("result")})
            return
        task["status"] = "finished"
        task["finished_at_epoch"] = time.time()
        task["result"] = {
            "status": status,
            "permalink": data.get("permalink"),
            "error": str(data.get("error") or "")[:500],
        }
        _save(path, task)
        self._json(HTTPStatus.OK, {"ok": True})


def main() -> None:
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"FB extension bridge listening on http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
