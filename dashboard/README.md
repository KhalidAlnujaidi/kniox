# dashboard
A live, read-only web one-pager over the daemon's state — one source of truth,
two readers (the daemon serves Claude via MCP; this serves the browser).
Run `kx dash` → http://enigma:8765 (tailnet/LAN). Per-project dashboards live in
`dashboard/<name>/` (drop an `index.html` to override the generic detail page).
