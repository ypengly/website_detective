# Website Detective 🕵️

Desktop tool that crawls a website (politely) and produces a technical audit: SEO, performance, accessibility,
mobile readiness, broken links/images, technical structure and security-related response headers.

> **Scope:** passive review of publicly served pages and headers. It is **not** a penetration test and does no
> exploitation. Only audit sites you own or have permission to scan. Scores are a heuristic summary for this tool
> and are not a prediction of search ranking.

## Run from source (Python 3.11+)
```
pip install -r requirements.txt
python main.py
```
Optional browser rendering: `pip install playwright && playwright install chromium`, then tick
"Render with browser". Rendered pages give a measured request count and executed-JS DOM.

## Tests
```
python -m unittest discover -s tests -t .
```
Tests use a local HTTP fixture site, so no internet is needed. They cover analyzers, robots.txt handling,
external-domain exclusion, page limit, cancellation, unreachable hosts, all four exports and SQLite storage.
The GUI layer is not covered by automated tests.

## Windows EXE
Run `build_exe.bat` → `dist\WebsiteDetective\WebsiteDetective.exe` (PyInstaller, one-folder build).
Browser rendering is excluded from the EXE to keep it small; run from source for that feature.

## What is checked
| Area | Checks |
|---|---|
| SEO | title, meta description, canonical, H1/headings, robots.txt, sitemap, Open Graph, JSON-LD validity, noindex, duplicate titles/descriptions |
| Performance | response time, HTML size, total weight (known sizes), request count, compression, caching headers, large images/assets, image dimensions |
| Accessibility | html lang, alt text, heading order, form labels, link/button names, duplicate ids, ARIA references, zoom blocking, inline-style contrast (indicator only) |
| Technical | HTTP status, redirects/chains, broken internal links, broken images/assets, canonical mismatch, viewport |
| Security headers | HTTPS, HSTS, CSP, X-Content-Type-Options, Referrer-Policy, framing protection, server version disclosure |

## Crawl behaviour
- Presets 10/25/50/100 or a custom limit; same-site pages only (external links are never crawled or probed).
- Honors robots.txt `Disallow` and `Crawl-delay` (capped at 10 s); minimum delay between requests is configurable (default 0.5 s); requests are serial.
- Page bodies are capped at 5 MB; at most 150 uncrawled internal links and 250 assets are verified via HEAD.

## Known limits
- Without browser rendering, JavaScript-generated content is not seen.
- Page weight/request count come from HTML references plus `Content-Length` headers, so they are estimates.
- Contrast checking sees inline styles only; use a dedicated tool for a full WCAG audit.
- Findings use hedged wording; none claim a guaranteed ranking effect.

## Layout
`website_detective/` – `crawler`, `analyzers`, `fetcher`, `scoring`, `exporters`, `storage`, `render`, `gui`; `tests/`; `main.py`.
History is stored in `~/.website_detective/audits.db`.
