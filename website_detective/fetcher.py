from __future__ import annotations
import threading, time
from urllib.parse import urlparse, urlunparse, urldefrag
from urllib.robotparser import RobotFileParser
import requests

USER_AGENT = "WebsiteDetective/1.0 (+technical-audit; respects robots.txt)"
MAX_BODY = 5 * 1024 * 1024  # never download more than 5 MB of a page body


def normalize_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Please enter a URL.")
    if "://" not in raw:
        raw = "https://" + raw
    p = urlparse(raw)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError(f"Not a valid http(s) URL: {raw}")
    return urlunparse((p.scheme, p.netloc.lower(), p.path or "/", "", p.query, ""))


def canonical_key(url: str) -> str:
    """Key used for de-duplicating URLs while crawling."""
    u, _ = urldefrag(url)
    p = urlparse(u)
    return urlunparse((p.scheme, p.netloc.lower(), p.path or "/", "", p.query, ""))


def same_site(url: str, host: str) -> bool:
    h = (urlparse(url).hostname or "").lower()
    base = host.lower()
    return h == base or h == "www." + base or base == "www." + h


class Fetcher:
    """Polite HTTP client: serialised requests with a minimum delay between them."""

    def __init__(self, delay: float = 0.5, timeout: float = 15.0, user_agent: str = USER_AGENT):
        self.delay = max(0.0, delay)
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.user_agent = user_agent
        self._last = 0.0
        self._lock = threading.Lock()
        self.request_count = 0

    def _throttle(self):
        with self._lock:
            wait = self._last + self.delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.request_count += 1

    def get(self, url: str) -> tuple[requests.Response | None, float, str]:
        """Return (response, elapsed_ms, error). Body is capped at MAX_BODY."""
        self._throttle()
        t0 = time.perf_counter()
        try:
            r = self.session.get(url, timeout=self.timeout, allow_redirects=True, stream=True)
            chunks, size = [], 0
            for chunk in r.iter_content(65536):
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_BODY:
                    break
            r._content = b"".join(chunks)  # noqa: SLF001 - make .content/.text usable
            r._content_consumed = True  # noqa: SLF001
            return r, (time.perf_counter() - t0) * 1000, ""
        except requests.RequestException as e:
            return None, (time.perf_counter() - t0) * 1000, f"{type(e).__name__}: {e}"

    def head(self, url: str) -> tuple[int, dict[str, str], str]:
        """HEAD with GET fallback for servers that reject HEAD. Returns (status, headers, error)."""
        self._throttle()
        try:
            r = self.session.head(url, timeout=self.timeout, allow_redirects=True)
            if r.status_code in (403, 405, 501):
                self._throttle()
                r = self.session.get(url, timeout=self.timeout, allow_redirects=True, stream=True)
                r.close()
            return r.status_code, dict(r.headers), ""
        except requests.RequestException as e:
            return 0, {}, f"{type(e).__name__}: {e}"


class Robots:
    def __init__(self, fetcher: Fetcher, base_url: str):
        p = urlparse(base_url)
        self.url = f"{p.scheme}://{p.netloc}/robots.txt"
        self.exists = False
        self.sitemaps: list[str] = []
        self.crawl_delay: float | None = None
        self._rp = RobotFileParser()
        self._allow_all = True
        r, _, _ = fetcher.get(self.url)
        if r is not None and r.status_code == 200 and "html" not in r.headers.get("Content-Type", "").lower():
            self.exists = True
            self._allow_all = False
            lines = r.text.splitlines()
            self._rp.parse(lines)
            self.sitemaps = [ln.split(":", 1)[1].strip() for ln in lines if ln.lower().startswith("sitemap:")]
            cd = self._rp.crawl_delay(fetcher.user_agent) or self._rp.crawl_delay("*")
            self.crawl_delay = float(cd) if cd else None
        elif r is not None and r.status_code >= 500:
            self._allow_all = False  # be conservative if robots.txt errors out
            self._rp.parse(["User-agent: *", "Disallow: /"])

    def allowed(self, url: str, ua: str = USER_AGENT) -> bool:
        return True if self._allow_all else self._rp.can_fetch(ua, url)
