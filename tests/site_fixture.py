"""Tiny local test site used by the integration tests (no external network needed)."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME = b"""<!doctype html><html><head><title>Home</title></head><body>
<h1>Welcome</h1><h1>Again</h1><h3>Skipped</h3>
<img src="/img/ok.png" alt="ok"><img src="/img/missing.png">
<a href="/about">About</a><a href="/old">Old</a><a href="/nowhere">Gone</a>
<a href="/private/secret">Secret</a><a href="https://external.invalid/x">Ext</a><a href="/empty"></a>
<form><input type="text" name="q"></form>
<p style="color:#777;background:#888">low contrast</p></body></html>"""
ABOUT = b"""<!doctype html><html lang="en"><head><title>Home</title>
<meta name="description" content="About page for the test site, long enough to be useful."><meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="canonical" href="/about"></head><body><h1>About</h1><p>text</p></body></html>"""
ROBOTS = b"User-agent: *\nDisallow: /private/\nSitemap: http://{host}/sitemap.xml\n"
SITEMAP = b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>http://{host}/about</loc></url></urlset>'


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body=b"", ctype="text/html", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    do_HEAD = lambda self: self.do_GET()

    def do_GET(self):
        host = self.headers.get("Host", "")
        p = self.path
        if p == "/": self._send(200, HOME)
        elif p == "/about": self._send(200, ABOUT, extra={"X-Content-Type-Options": "nosniff"})
        elif p == "/old": self._send(301, b"", extra={"Location": "/about"})
        elif p == "/empty": self._send(200, b"<html><body>hi</body></html>")
        elif p == "/robots.txt": self._send(200, ROBOTS.replace(b"{host}", host.encode()), "text/plain")
        elif p == "/sitemap.xml": self._send(200, SITEMAP.replace(b"{host}", host.encode()), "application/xml")
        elif p == "/img/ok.png": self._send(200, b"\x89PNG" + b"0" * 100, "image/png")
        elif p.startswith("/private/"): self._send(200, b"<html><title>secret</title></html>")
        else: self._send(404, b"nf")


def start():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"
