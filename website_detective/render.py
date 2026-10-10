"""Optional Playwright rendering for JavaScript-heavy pages."""
from __future__ import annotations


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


class BrowserRenderer:
    """Renders pages in headless Chromium and counts the network requests/bytes made."""

    def __init__(self, user_agent: str, timeout_ms: int = 20000):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(headless=True)
        except Exception:
            self._pw.stop()
            raise
        self._ctx = self._browser.new_context(user_agent=user_agent)
        self._timeout = timeout_ms

    def render(self, url: str) -> tuple[str, int, int]:
        """Return (rendered_html, request_count, transferred_bytes)."""
        page = self._ctx.new_page()
        count, total = [0], [0]

        def on_req(_r):
            count[0] += 1

        def on_resp(resp):
            try:
                total[0] += int(resp.headers.get("content-length", "0"))
            except ValueError:
                pass

        page.on("request", on_req)
        page.on("response", on_resp)
        try:
            page.goto(url, wait_until="networkidle", timeout=self._timeout)
            return page.content(), count[0], total[0]
        finally:
            page.close()

    def close(self):
        for fn in (self._ctx.close, self._browser.close, self._pw.stop):
            try:
                fn()
            except Exception:
                pass
