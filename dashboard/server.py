#!/usr/bin/env python3
"""kniox dashboard — read-only web one-pager over the daemon's state. A second
reader beside the MCP server. stdlib only; binds 0.0.0.0 for tailnet/LAN reach."""
from __future__ import annotations
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "daemon"))
import daemon  # noqa: E402

PORT = 8765


def render_project_page(name: str):
    detail = daemon.project_detail(name)
    if detail is None:
        return None
    custom = HERE / name / "index.html"          # per-project dashboard override
    if custom.exists():
        return custom.read_text()
    runs = "".join(f"<li>{r['task']} — {r['state']}</li>" for r in detail.get("runs", []))
    doc = detail.get("doc") or "_no next.md / PROGRESS.md_"
    return (f"<!doctype html><meta charset=utf-8><title>{name}</title>"
            "<body style='font-family:system-ui;max-width:760px;margin:2rem auto'>"
            f"<a href='/'>&larr; all projects</a><h1>{name}</h1>"
            f"<p><b>path</b> {detail.get('path')} · <b>status</b> {detail.get('status')}</p>"
            f"<h3>recent runs</h3><ul>{runs or '<li>none</li>'}</ul>"
            f"<h3>notes</h3><pre style='white-space:pre-wrap'>{doc}</pre>"
            f"<p style='color:#888'>per-project dashboard slot — "
            f"customise at dashboard/{name}/index.html</p></body>")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, (HERE / "index.html").read_text()); return
        if self.path == "/api/state":
            try:
                body = json.dumps(daemon.dashboard_state())
            except Exception as e:
                body = json.dumps({"error": str(e), "hint": "is the daemon importable?"})
            self._send(200, body, "application/json"); return
        if self.path.startswith("/project/"):
            name = self.path[len("/project/"):].strip("/")
            html = render_project_page(name)
            if html is None:
                self._send(404, f"unknown project: {name}"); return
            self._send(200, html); return
        self._send(404, "not found")

    def log_message(self, *a):
        pass


def make_server(port=PORT):
    return ThreadingHTTPServer(("0.0.0.0", port), Handler)


if __name__ == "__main__":
    httpd = make_server()
    print(f"kniox dashboard → http://0.0.0.0:{PORT}  (tailnet/LAN: http://enigma:{PORT})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
