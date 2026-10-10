from __future__ import annotations
import threading, time
from collections import deque
from datetime import datetime
from typing import Callable
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

from . import analyzers as an
from .fetcher import Fetcher, Robots, USER_AGENT, canonical_key, normalize_url, same_site
from .models import AuditResult, Issue, PageResult
from .scoring import compute_scores

ProgressCb = Callable[[int, int, str], None]
MAX_DELAY = 10.0
MAX_LINK_CHECKS = 150     # uncrawled internal links verified with HEAD
MAX_RESOURCE_CHECKS = 250  # unique sub-resources verified with HEAD per audit


class Crawler:
    def __init__(self, start_url: str, max_pages: int = 25, delay: float = 0.5,
                 respect_robots: bool = True, use_browser: bool = False,
                 check_resources: bool = True, progress: ProgressCb | None = None,
                 cancel: threading.Event | None = None, fetcher: Fetcher | None = None):
        self.start_url = normalize_url(start_url)
        self.max_pages = max(1, int(max_pages))
        self.respect_robots = respect_robots
        self.use_browser = use_browser
        self.check_resources = check_resources
        self.progress = progress or (lambda *_: None)
        self.cancel = cancel or threading.Event()
        self.fetcher = fetcher or Fetcher(delay=delay)
        self.host = urlparse(self.start_url).hostname or ""
        self._res_cache: dict[str, tuple[int, dict, str]] = {}
        self._renderer = None

    # -- helpers
    def _log(self, done: int, total: int, msg: str):
        self.progress(done, total, msg)

    def _head_cached(self, url: str):
        if url not in self._res_cache:
            self._res_cache[url] = self.fetcher.head(url)
        return self._res_cache[url]

    def _check_sitemap(self, robots: Robots, result: AuditResult) -> list[str]:
        cands = robots.sitemaps[:3] or [urljoin(self.start_url, "/sitemap.xml")]
        urls: list[str] = []
        found = ""
        for sm in cands:
            r, _, _ = self.fetcher.get(sm)
            if r is not None and r.status_code == 200 and b"<" in r.content[:200]:
                found = sm
                try:
                    root = ET.fromstring(r.content)
                    urls += [e.text.strip() for e in root.iter() if e.tag.endswith("}loc") or e.tag == "loc"][:500]
                except ET.ParseError:
                    result.issues.append(Issue("SEO", "Sitemap is not valid XML", sm, "Search engines cannot reliably read a malformed sitemap.", "XML parse error.", "Regenerate the sitemap.", "Medium"))
                break
        result.site_info["sitemap_url"] = found
        result.site_info["sitemap_urls"] = len(urls)
        if not found:
            result.issues.append(Issue("SEO", "No sitemap found", self.start_url, "Sitemaps help crawlers discover URLs; they are recommended for larger sites but not required.", f"Checked: {', '.join(cands)}", "Publish an XML sitemap and reference it in robots.txt.", "Low"))
        return urls

    # -- main
    def run(self) -> AuditResult:
        t0 = time.perf_counter()
        result = AuditResult(self.start_url, self.host, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        try:
            self._run(result)
        finally:
            if self._renderer:
                self._renderer.close()
            result.duration_s = time.perf_counter() - t0
            result.issues.extend(an.check_site_duplicates(result.pages))
            result.scores = compute_scores(result)
            result.site_info["http_requests_made"] = self.fetcher.request_count
        return result

    def _run(self, result: AuditResult):
        self._log(0, self.max_pages, "Reading robots.txt…")
        robots = Robots(self.fetcher, self.start_url)
        if robots.crawl_delay and self.respect_robots:
            self.fetcher.delay = min(MAX_DELAY, max(self.fetcher.delay, robots.crawl_delay))
        result.site_info.update(robots_txt=robots.exists, robots_url=robots.url,
                                crawl_delay_used=self.fetcher.delay, respect_robots=self.respect_robots)
        if not robots.exists:
            result.issues.append(Issue("SEO", "No robots.txt found", robots.url, "robots.txt is optional, but it is the standard place to give crawlers guidance and list sitemaps.", "robots.txt did not return a plain-text 200 response.", "Add a robots.txt, even a minimal one.", "Info"))
        sitemap_urls = self._check_sitemap(robots, result)

        if self.use_browser:
            from .render import BrowserRenderer
            try:
                self._renderer = BrowserRenderer(USER_AGENT)
            except Exception as e:  # browser not installed etc.
                result.site_info["browser_error"] = str(e)[:200]
                self._renderer = None

        queue = deque([self.start_url])
        seen = {canonical_key(self.start_url)}
        for u in sitemap_urls:
            if same_site(u, self.host) and canonical_key(u) not in seen and len(seen) < self.max_pages * 3:
                seen.add(canonical_key(u)); queue.append(u)
        crawled: dict[str, PageResult] = {}
        links_from: dict[str, set[str]] = {}  # target -> source pages
        blocked = 0
        link_targets: dict[str, str] = {}

        while queue and len(result.pages) < self.max_pages and not self.cancel.is_set():
            url = queue.popleft()
            if self.respect_robots and not robots.allowed(url):
                blocked += 1
                continue
            self._log(len(result.pages), self.max_pages, f"Analyzing {url}")
            page, soup = self._fetch_page(url, result)
            result.pages.append(page)
            crawled[canonical_key(url)] = page
            crawled[canonical_key(page.final_url or url)] = page
            if soup is None:
                continue
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if href.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
                    continue
                target = urljoin(page.final_url or url, href)
                if urlparse(target).scheme not in ("http", "https"):
                    continue
                if not same_site(target, self.host):
                    continue  # external links are never crawled
                k = canonical_key(target)
                links_from.setdefault(k, set()).add(page.final_url or url)
                link_targets[k] = target
                if k not in seen and not _looks_binary(target):
                    seen.add(k); queue.append(target)

        result.cancelled = self.cancel.is_set()
        result.site_info["blocked_by_robots"] = blocked

        # verify internal links that were discovered but not crawled (page limit)
        if not self.cancel.is_set():
            pending = [k for k in link_targets if k not in crawled][:MAX_LINK_CHECKS]
            for n, k in enumerate(pending):
                if self.cancel.is_set():
                    break
                t = link_targets[k]
                if self.respect_robots and not robots.allowed(t):
                    continue
                self._log(n, len(pending), f"Checking link {t}")
                st, _, err = self._head_cached(t)
                if st == 0 or st >= 400:
                    for src in sorted(links_from[k])[:3]:
                        result.issues.append(Issue("Technical", "Broken internal link", src, "Broken links frustrate visitors and waste crawl effort.", f"{t} -> {'error: ' + err if st == 0 else 'HTTP ' + str(st)}", "Fix or remove the link.", "High"))
        # internal links that point to crawled pages with errors
        done_pages: set[int] = set()
        for k, p in crawled.items():
            if id(p) in done_pages:
                continue
            done_pages.add(id(p))
            if p.status >= 400 or p.error:
                for src in sorted(links_from.get(k, ()))[:3]:
                    if src != (p.final_url or p.url):
                        result.issues.append(Issue("Technical", "Broken internal link", src, "Broken links frustrate visitors and waste crawl effort.", f"{p.url} -> {'HTTP ' + str(p.status) if p.status else p.error}", "Fix or remove the link.", "High"))

    def _fetch_page(self, url: str, result: AuditResult) -> tuple[PageResult, BeautifulSoup | None]:
        page = PageResult(url=url)
        resp, ms, err = self.fetcher.get(url)
        page.response_time_ms = ms
        if resp is None:
            page.error = err
            result.issues.extend(an.check_technical(url, page))
            return page, None
        page.status = resp.status_code
        page.final_url = resp.url
        page.redirects = [h.url for h in resp.history]
        page.headers = dict(resp.headers)
        page.html_bytes = len(resp.content)
        try:
            page.transferred_bytes = int(resp.headers["Content-Length"])
        except (KeyError, ValueError):
            page.transferred_bytes = None
        result.issues.extend(an.check_technical(url, page))
        result.issues.extend(an.check_security_headers(page.final_url, page.headers, page.final_url.startswith("https://")))
        ctype = resp.headers.get("Content-Type", "").lower()
        if "html" not in ctype:
            return page, None
        html = resp.text
        if self._renderer is not None:
            try:
                html, nreq, nbytes = self._renderer.render(page.final_url)
                page.rendered, page.resource_count = True, nreq
                page.resource_bytes = nbytes
            except Exception as e:
                result.site_info.setdefault("render_errors", []).append(f"{url}: {str(e)[:120]}")
        soup = BeautifulSoup(html, "lxml")
        result.issues.extend(an.check_performance(page.final_url, page, page.headers))
        if page.status < 400:
            result.issues.extend(an.check_seo(page.final_url, soup, page))
            result.issues.extend(an.check_accessibility(page.final_url, soup))
            result.issues.extend(an.check_mobile(page.final_url, soup))
            result.issues.extend(an.img_has_dimensions(soup, page.final_url))
            if self.check_resources:
                self._check_page_resources(page, soup, result)
        return page, soup

    def _check_page_resources(self, page: PageResult, soup: BeautifulSoup, result: AuditResult):
        res: list[tuple[str, str]] = []
        for im in soup.find_all("img", src=True):
            res.append((im["src"], "image"))
        for s in soup.find_all("script", src=True):
            res.append((s["src"], "script"))
        for l in soup.find_all("link", href=True):
            rel = l.get("rel") or []
            if "stylesheet" in rel:
                res.append((l["href"], "style"))
        uniq = {}
        for src, kind in res:
            if src.startswith("data:"):
                continue
            uniq[urljoin(page.final_url, src)] = kind
        if not page.rendered:
            page.resource_count = len(uniq)
        total = 0
        for u, kind in uniq.items():
            if self.cancel.is_set():
                break
            if not same_site(u, self.host) and kind != "image":
                continue  # don't probe third-party scripts/styles
            if not same_site(u, self.host):
                continue
            if u not in self._res_cache and len(self._res_cache) >= MAX_RESOURCE_CHECKS:
                continue
            st, hdr, err = self._head_cached(u)
            result.issues.extend(an.check_resource(page.final_url, u, kind, st, hdr, err))
            try:
                total += int({k.lower(): v for k, v in hdr.items()}.get("content-length", "0"))
            except ValueError:
                pass
        if not page.rendered:
            page.resource_bytes = total


_BIN = (".pdf", ".zip", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".mp4", ".mp3", ".css", ".js", ".ico", ".xml", ".exe", ".dmg")


def _looks_binary(url: str) -> bool:
    return urlparse(url).path.lower().endswith(_BIN)
