#!/usr/bin/env python3
"""Local Xianyu image handoff page.

The page is deliberately idempotent: a save request is recorded once per
asset_id, and a later timeout can only move the asset to pending/manual review.
It never creates a second copy because a browser did not expose a gallery
count change.
"""

from __future__ import annotations

import argparse
import cgi
import hashlib
import html
import json
import mimetypes
import os
import re
import secrets
import socket
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


IMAGE_TYPES = {
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".heic": "image/heic",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def local_ip(preferred: str | None) -> str:
    if preferred:
        return preferred
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.168.0.253", 80))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def clean_name(name: str) -> str:
    name = Path(name).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or "image.png"


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class Gallery:
    def __init__(self, root: Path, state_path: Path) -> None:
        self.root = root.resolve()
        self.state_path = state_path.resolve()
        self.lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        self.state = self._load()
        self._sync_files()

    def _load(self) -> dict:
        if not self.state_path.exists():
            return {"version": 1, "assets": {}, "events": []}
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and isinstance(value.get("assets"), dict):
                value.setdefault("events", [])
                return value
        except (OSError, ValueError):
            pass
        return {"version": 1, "assets": {}, "events": []}

    def _persist(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.state_path)

    def _sync_files(self) -> None:
        changed = False
        with self.lock:
            known_names = {asset["filename"] for asset in self.state["assets"].values()}
            for path in sorted(self.root.iterdir()):
                if not path.is_file() or path.suffix.lower() not in IMAGE_TYPES or path.name in known_names:
                    continue
                asset = self._make_asset(path, "imported")
                self.state["assets"][asset["asset_id"]] = asset
                changed = True
            if changed:
                self._persist()

    def _make_asset(self, path: Path, original_name: str) -> dict:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        stat = path.stat()
        short_hash = digest.hexdigest()[:16]
        return {
            "asset_id": f"xianyu_{short_hash}",
            "filename": path.name,
            "original_name": original_name,
            "size": stat.st_size,
            "sha256": digest.hexdigest(),
            "modified_ns": stat.st_mtime_ns,
            "created_at": time.time(),
            "save_status": "not_requested",
            "save_requested_at": None,
            "download_requests": 0,
        }

    def assets(self) -> list[dict]:
        with self.lock:
            self._sync_files()
            return sorted(self.state["assets"].values(), key=lambda item: item["created_at"], reverse=True)

    def latest_asset(self) -> dict | None:
        """Return only the newest asset for the phone handoff page."""
        assets = self.assets()
        return assets[0] if assets else None

    def add_upload(self, filename: str, content: bytes) -> dict:
        if len(content) > MAX_UPLOAD_BYTES:
            raise ValueError("upload_too_large")
        digest = hashlib.sha256(content).hexdigest()
        with self.lock:
            for asset in self.state["assets"].values():
                if asset.get("sha256") == digest:
                    return asset
            safe = clean_name(filename)
            suffix = Path(safe).suffix.lower()
            if suffix not in IMAGE_TYPES:
                raise ValueError("unsupported_image_type")
            asset_id = f"xianyu_{digest[:16]}"
            final_name = f"{asset_id}_{safe}"
            final_path = self.root / final_name
            temp_path = self.root / f".{asset_id}.part"
            temp_path.write_bytes(content)
            os.replace(temp_path, final_path)
            asset = self._make_asset(final_path, safe)
            self.state["assets"][asset["asset_id"]] = asset
            self._event("asset_uploaded", asset["asset_id"], {"filename": final_name})
            self._persist()
            return asset

    def request_save(self, asset_id: str) -> tuple[dict, bool]:
        with self.lock:
            asset = self.state["assets"].get(asset_id)
            if not asset:
                raise KeyError(asset_id)
            already = asset["save_status"] in {"requested", "pending", "confirmed", "manual_required"}
            if not already:
                asset["save_status"] = "requested"
                asset["save_requested_at"] = time.time()
                asset["download_requests"] = int(asset.get("download_requests", 0)) + 1
                self._event("save_requested", asset_id, {"filename": asset["filename"]})
                self._persist()
            return asset, already

    def mark_download_started(self, asset_id: str) -> dict:
        with self.lock:
            asset = self.state["assets"].get(asset_id)
            if not asset:
                raise KeyError(asset_id)
            self._event("download_served", asset_id, {"filename": asset["filename"]})
            self._persist()
            return asset

    def latest_event(self) -> dict | None:
        with self.lock:
            return self.state["events"][-1] if self.state["events"] else None

    def _event(self, kind: str, asset_id: str, data: dict) -> None:
        self.state["events"].append({"event_id": secrets.token_hex(8), "at": time.time(), "kind": kind, "asset_id": asset_id, **data})
        self.state["events"] = self.state["events"][-200:]

    def file_for(self, asset_id: str) -> tuple[dict, Path]:
        with self.lock:
            asset = self.state["assets"].get(asset_id)
            if not asset:
                raise KeyError(asset_id)
            path = (self.root / asset["filename"]).resolve()
            if path.parent != self.root or not path.is_file():
                raise FileNotFoundError(asset["filename"])
            return asset, path


class Handler(BaseHTTPRequestHandler):
    server_version = "XianyuAssetGallery/1.0"

    def _cfg(self) -> dict:
        return self.server.gallery_config  # type: ignore[attr-defined]

    def _parts(self) -> list[str]:
        return [unquote(part) for part in urlsplit(self.path).path.split("/") if part]

    def _authorized(self, parts: list[str]) -> bool:
        return bool(parts) and secrets.compare_digest(parts[0], self._cfg()["token"])

    def _send_json(self, value: object, status: int = 200) -> None:
        payload = json_bytes(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_html(self, body: str, status: int = 200) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        parts = self._parts()
        if not self._authorized(parts):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        gallery: Gallery = self._cfg()["gallery"]
        if len(parts) == 1:
            self._send_html(self._page(gallery.latest_asset()))
            return
        if len(parts) == 2 and parts[1] == "api":
            self._send_json({"assets": gallery.assets(), "latest_event": gallery.latest_event()})
            return
        if len(parts) == 3 and parts[1] in {"preview", "download"}:
            try:
                asset, path = gallery.file_for(parts[2])
            except (KeyError, FileNotFoundError):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = IMAGE_TYPES.get(path.suffix.lower(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            size = path.stat().st_size
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            disposition = "inline" if parts[1] == "preview" else "attachment"
            self.send_header("Content-Disposition", f"{disposition}; filename*=UTF-8''{asset['filename']}")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            gallery.mark_download_started(asset["asset_id"])
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    self.wfile.write(chunk)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parts = self._parts()
        if not self._authorized(parts):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        gallery: Gallery = self._cfg()["gallery"]
        if len(parts) == 2 and parts[1] == "upload":
            try:
                form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers.get("Content-Type", "")})
                field = form["image"]
                content = field.file.read(MAX_UPLOAD_BYTES + 1)
                asset = gallery.add_upload(field.filename or "image.png", content)
            except (KeyError, ValueError, OSError):
                self._send_json({"ok": False, "error": "invalid_image_upload"}, HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"ok": True, "asset": asset})
            return
        if len(parts) == 3 and parts[1] == "save":
            try:
                asset, already = gallery.request_save(parts[2])
            except KeyError:
                self._send_json({"ok": False, "error": "unknown_asset"}, HTTPStatus.NOT_FOUND)
                return
            self._send_json({"ok": True, "already_requested": already, "asset": asset})
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _page(self, asset: dict | None) -> str:
        token = html.escape(self._cfg()["token"])
        if asset:
            aid = html.escape(asset["asset_id"])
            name = html.escape(asset["filename"])
            status = html.escape(asset.get("save_status", "not_requested"))
            button = "已记录保存" if status in {"requested", "pending", "confirmed", "manual_required"} else "保存到手机"
            photo = f'''<article class="card" data-asset="{aid}">
              <img src="/{token}/preview/{aid}" alt="{name}" loading="eager">
              <div class="meta"><strong>最新图片</strong><span>{name}</span><small>状态：{status}</small></div>
              <button data-save="{aid}" {'disabled' if status in {"requested", "pending", "confirmed", "manual_required"} else ''}>{button}</button>
            </article>'''
        else:
            photo = '<p class="empty">还没有图片，请先上传。</p>'
        return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>闲鱼图片中转</title>
        <style>body{{font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#111827;color:#f9fafb;margin:0;padding:16px}}main{{max-width:720px;margin:auto}}h1{{margin:0 0 6px;font-size:24px}}p{{color:#cbd5e1}}.panel,.card{{background:#1f2937;border:1px solid #374151;border-radius:16px;padding:14px;margin:14px 0}}input,button{{font:inherit}}button{{background:#8b5cf6;color:white;border:0;border-radius:10px;padding:11px 14px;cursor:pointer}}button:disabled{{background:#4b5563;cursor:not-allowed}}.card{{display:flex;flex-direction:column;gap:10px}}img{{width:100%;max-height:65vh;aspect-ratio:1;object-fit:contain;background:#0b1020;border-radius:10px}}.meta{{display:grid;gap:4px}}.meta span,.meta small{{color:#cbd5e1;overflow-wrap:anywhere}}.empty{{text-align:center;margin:30px 0}}#status{{color:#c4b5fd;font-weight:600;margin-top:10px}}</style></head>
        <body><main><h1>闲鱼图片中转</h1><p>只显示最新图片。保存请求记录后不会重复下载。</p>
        <section class="panel"><form id="upload"><input type="file" name="image" accept="image/*" required><button>上传新图片</button></form><div id="status">{("最新图片已就绪" if asset and status == "not_requested" else "最新图片已记录保存，不会重复下载" if asset else "等待上传图片")}</div></section>
        <section>{photo}</section>
        <script>const token={json.dumps(self._cfg()["token"])};const statusEl=document.querySelector('#status');document.querySelector('#upload').addEventListener('submit',async e=>{{e.preventDefault();const r=await fetch('/'+token+'/upload',{{method:'POST',body:new FormData(e.target)}});const j=await r.json();statusEl.textContent=j.ok?'图片已登记，可在列表中保存。':'上传失败：'+j.error;if(j.ok)location.reload();}});document.querySelectorAll('[data-save]').forEach(b=>b.addEventListener('click',async()=>{{b.disabled=true;b.textContent='正在记录…';const r=await fetch('/'+token+'/save/'+b.dataset.save,{{method:'POST'}});const j=await r.json();if(j.ok){{if(!j.already_requested){{const a=document.createElement('a');a.href='/'+token+'/download/'+j.asset.asset_id;a.download=j.asset.filename;a.click();}}b.textContent=j.already_requested?'已记录过，不重复下载':'保存请求已记录';statusEl.textContent='已通知：'+j.asset.filename+'，浏览器已发起一次保存请求；后续不再重复请求';}}else{{b.disabled=false;b.textContent='保存到手机';statusEl.textContent='保存记录失败：'+j.error;}}}}));</script></main></body></html>'''

    def log_message(self, fmt: str, *args: object) -> None:
        print("[gallery] " + (fmt % args), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("xianyu-assets"))
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--advertise", default=None)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--state", type=Path, default=Path("xianyu_asset_gallery_state.json"))
    args = parser.parse_args()
    gallery = Gallery(args.root, args.state)
    token = secrets.token_urlsafe(18)
    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    server.gallery_config = {"gallery": gallery, "token": token}  # type: ignore[attr-defined]
    advertised = local_ip(args.advertise)
    print(json.dumps({"url": f"http://{advertised}:{args.port}/{token}/", "root": str(gallery.root), "state": str(gallery.state_path)}, ensure_ascii=False), flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
