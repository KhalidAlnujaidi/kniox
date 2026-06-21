import json, threading, urllib.request, urllib.error, server

def _serve():
    httpd = server.make_server(port=0)            # ephemeral port
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, httpd.server_address[1]

def _get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return r.status, r.read().decode()

def test_routes(monkeypatch):
    import daemon
    monkeypatch.setattr(daemon, "dashboard_state",
                        lambda: {"ts": "t", "resources": {}, "services": [],
                                 "projects": [], "cluster": [], "notes": []})
    monkeypatch.setattr(daemon, "project_detail",
                        lambda n: None if n == "ghost" else
                        {"name": n, "path": "/x", "status": "idle", "doc": "hi", "runs": []})
    httpd, port = _serve()
    try:
        code, body = _get(port, "/")
        assert code == 200 and "<" in body                 # serves index.html
        code, body = _get(port, "/api/state")
        assert code == 200 and json.loads(body)["ts"] == "t"
        code, body = _get(port, "/project/known")
        assert code == 200 and "known" in body
        try:
            _get(port, "/project/ghost")
            assert False, "expected 404"
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        httpd.shutdown()
