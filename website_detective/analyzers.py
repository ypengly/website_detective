"""Per-page and site-level checks. Pure functions: HTML/headers in, Issues out.

Wording policy: "why" text describes documented guidance or general good practice
and avoids claiming a definite ranking or revenue impact.
"""
from __future__ import annotations
import json, re
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from .models import Issue, PageResult


def _i(cat, title, url, why, evidence, fix, sev="Medium") -> Issue:
    return Issue(cat, title, url, why, evidence, fix, sev)


# ---------------------------------------------------------------- SEO
def check_seo(url: str, soup: BeautifulSoup, page: PageResult) -> list[Issue]:
    out: list[Issue] = []
    S = "SEO"
    t = soup.title.get_text(strip=True) if soup.title else ""
    page.title = t
    if not t:
        out.append(_i(S, "Missing <title>", url, "Search engines and browsers use the title to label a page; Google's documentation recommends a unique, descriptive title for each page.", "No <title> element or it is empty.", "Add a concise, descriptive title unique to this page.", "High"))
    elif len(t) > 60:
        out.append(_i(S, "Title may be too long", url, "Long titles are often truncated in search result displays (no fixed limit; roughly 50-60 characters is a common guideline).", f"Title is {len(t)} characters: '{t[:80]}'", "Shorten the title and put key words first.", "Low"))
    elif len(t) < 15:
        out.append(_i(S, "Title may be too short", url, "Very short titles tend to describe a page poorly.", f"Title is {len(t)} characters: '{t}'", "Use a more descriptive title.", "Low"))

    md = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    d = (md.get("content") or "").strip() if md else ""
    page.meta_description = d
    if not d:
        out.append(_i(S, "Missing meta description", url, "Search engines may use the meta description as the result snippet; without one they generate their own from page text.", "No <meta name=\"description\"> content found.", "Write a unique summary of the page (about 70-160 characters).", "Medium"))
    elif len(d) > 170:
        out.append(_i(S, "Meta description may be too long", url, "Snippets are commonly truncated in search results; length limits are not fixed.", f"Description is {len(d)} characters.", "Tighten the description.", "Low"))

    can = soup.find("link", rel=lambda v: v and "canonical" in (v if isinstance(v, list) else [v]))
    page.canonical = (can.get("href") or "").strip() if can else ""
    if not page.canonical:
        out.append(_i(S, "Missing canonical link", url, "A canonical URL helps signal the preferred version when the same content is reachable at several URLs.", "No <link rel=\"canonical\"> found.", "Add a self-referencing canonical on indexable pages.", "Low"))

    h1s = soup.find_all("h1")
    page.h1_count = len(h1s)
    if not h1s:
        out.append(_i(S, "Missing H1 heading", url, "A top-level heading helps users and crawlers understand the main topic of the page.", "No <h1> element found.", "Add one descriptive <h1>.", "Medium"))
    elif len(h1s) > 1:
        out.append(_i(S, "Multiple H1 headings", url, "HTML5 permits multiple H1s, but a single main heading is a common clarity guideline.", f"{len(h1s)} <h1> elements found.", "Consider using one H1 and H2-H6 for sub-sections.", "Info"))

    robots_meta = soup.find("meta", attrs={"name": re.compile("^robots$", re.I)})
    if robots_meta and "noindex" in (robots_meta.get("content") or "").lower():
        out.append(_i(S, "Page set to noindex", url, "A noindex directive asks search engines not to include the page in results.", f"meta robots = '{robots_meta.get('content')}'", "Confirm this is intentional.", "Info"))

    og = {m.get("property") for m in soup.find_all("meta") if (m.get("property") or "").startswith("og:")}
    missing = [p for p in ("og:title", "og:description", "og:image") if p not in og]
    if missing:
        out.append(_i(S, "Incomplete Open Graph metadata", url, "Open Graph tags control how links are previewed when shared on social platforms.", "Missing: " + ", ".join(missing), "Add the missing og: tags.", "Low"))

    has_ld = False
    for s in soup.find_all("script", type="application/ld+json"):
        has_ld = True
        try:
            json.loads(s.string or "")
        except (ValueError, TypeError):
            out.append(_i(S, "Invalid JSON-LD structured data", url, "Structured data that fails to parse cannot be used for rich-result features.", "A JSON-LD block is not valid JSON.", "Validate with a structured-data testing tool.", "Medium"))
    if not has_ld and not soup.find(attrs={"itemscope": True}):
        out.append(_i(S, "No structured data detected", url, "Structured data (schema.org) can make a page eligible for rich results; it is optional.", "No JSON-LD or microdata found.", "Consider schema.org markup that fits the page type.", "Info"))

    text = soup.get_text(" ", strip=True)
    page.word_count = len(text.split())
    if page.word_count < 150 and page.status == 200:
        out.append(_i(S, "Thin text content", url, "Pages with little text give users and crawlers little to evaluate (a heuristic, not a penalty rule).", f"About {page.word_count} words of visible text.", "Check that the page provides enough useful content for its purpose.", "Info"))
    return out


# ---------------------------------------------------------------- Accessibility
def _lum(hexc: str) -> float | None:
    h = hexc.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return None
    try:
        rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    except ValueError:
        return None
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast_ratio(fg: str, bg: str) -> float | None:
    a, b = _lum(fg), _lum(bg)
    if a is None or b is None:
        return None
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def check_accessibility(url: str, soup: BeautifulSoup) -> list[Issue]:
    out: list[Issue] = []
    A = "Accessibility"
    html = soup.find("html")
    if not html or not (html.get("lang") or "").strip():
        out.append(_i(A, "Missing html lang attribute", url, "Screen readers use the language attribute to choose pronunciation (WCAG 3.1.1).", "<html> has no lang attribute.", "Add e.g. <html lang=\"en\">.", "Medium"))

    no_alt = [im for im in soup.find_all("img") if im.get("alt") is None and im.get("role") not in ("presentation", "none")]
    if no_alt:
        out.append(_i(A, "Images missing alt attribute", url, "Alternative text lets assistive technology describe images (WCAG 1.1.1).", f"{len(no_alt)} image(s) without alt, e.g. {no_alt[0].get('src', '')[:100]}", "Add descriptive alt text, or alt=\"\" for decorative images.", "High" if len(no_alt) > 3 else "Medium"))

    levels = [int(h.name[1]) for h in soup.find_all(re.compile(r"^h[1-6]$"))]
    for prev, cur in zip(levels, levels[1:]):
        if cur > prev + 1:
            out.append(_i(A, "Heading hierarchy skips a level", url, "Skipped levels can make the document outline harder to navigate with assistive technology (WCAG 1.3.1 guidance).", f"h{prev} is followed by h{cur}.", "Use sequential heading levels.", "Low"))
            break

    unlabeled = []
    for f in soup.find_all(["input", "select", "textarea"]):
        if f.name == "input" and (f.get("type") or "text").lower() in ("hidden", "submit", "button", "reset", "image"):
            continue
        if f.get("aria-label") or f.get("aria-labelledby") or f.get("title"):
            continue
        fid = f.get("id")
        if fid and soup.find("label", attrs={"for": fid}):
            continue
        if f.find_parent("label"):
            continue
        unlabeled.append(f)
    if unlabeled:
        n = unlabeled[0]
        out.append(_i(A, "Form fields without labels", url, "Unlabeled controls are hard to identify for screen-reader users (WCAG 1.3.1, 3.3.2).", f"{len(unlabeled)} field(s), e.g. <{n.name} name='{n.get('name', '')}'>", "Associate a <label for>, or add aria-label.", "High"))

    bad_links = [a for a in soup.find_all("a", href=True)
                 if not a.get_text(strip=True) and not a.get("aria-label") and not a.get("aria-labelledby")
                 and not a.get("title") and not any(im.get("alt") for im in a.find_all("img"))]
    if bad_links:
        out.append(_i(A, "Links without accessible name", url, "Links with no text are announced without purpose (WCAG 2.4.4).", f"{len(bad_links)} link(s), e.g. href={bad_links[0].get('href')[:100]}", "Add link text or aria-label.", "Medium"))
    vague = [a for a in soup.find_all("a", href=True) if a.get_text(strip=True).lower() in ("click here", "here", "read more", "more")]
    if len(vague) > 2:
        out.append(_i(A, "Vague link text", url, "Generic link text is ambiguous when links are listed out of context (WCAG 2.4.4).", f"{len(vague)} links such as 'click here'/'read more'.", "Use link text that describes the destination.", "Low"))

    empty_btn = [b for b in soup.find_all("button") if not b.get_text(strip=True) and not b.get("aria-label") and not b.get("aria-labelledby") and not b.get("title")]
    if empty_btn:
        out.append(_i(A, "Buttons without accessible name", url, "Buttons need a name so assistive technology can announce their purpose.", f"{len(empty_btn)} button(s) with no text or aria-label.", "Add visible text or aria-label.", "Medium"))

    ids = [e.get("id") for e in soup.find_all(id=True)]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        out.append(_i(A, "Duplicate id attributes", url, "Duplicate ids can break label and ARIA references.", "Duplicated: " + ", ".join(sorted(dup)[:5]), "Make ids unique.", "Low"))
    for el in soup.find_all(attrs={"aria-labelledby": True}):
        if any(not soup.find(id=r) for r in el["aria-labelledby"].split()):
            out.append(_i(A, "aria-labelledby references missing id", url, "A broken ARIA reference gives the element no name.", f"<{el.name}> points to id '{el['aria-labelledby']}'.", "Point it at an existing element id.", "Medium"))
            break
    for el in soup.find_all(attrs={"aria-hidden": "true"}):
        if el.name in ("a", "button", "input") and el.get("tabindex") != "-1":
            out.append(_i(A, "Focusable element hidden with aria-hidden", url, "Hidden-from-AT elements that remain focusable create confusing keyboard behaviour.", f"<{el.name}> has aria-hidden=true but is focusable.", "Remove aria-hidden or add tabindex=\"-1\".", "Medium"))
            break

    low = []
    for el in soup.find_all(style=True):
        st = el["style"].lower()
        fg = re.search(r"(?<![-\w])color\s*:\s*(#[0-9a-f]{3,6})\b", st)
        bg = re.search(r"background(?:-color)?\s*:\s*(#[0-9a-f]{3,6})\b", st)
        if fg and bg:
            r = contrast_ratio(fg.group(1), bg.group(1))
            if r is not None and r < 4.5:
                low.append((round(r, 2), fg.group(1), bg.group(1)))
    if low:
        out.append(_i(A, "Possible low colour contrast (indicator only)", url, "WCAG 1.4.3 asks for a 4.5:1 contrast ratio for normal text. This check only sees inline styles, so it is an indicator, not a full contrast audit.", f"{len(low)} inline style(s), e.g. ratio {low[0][0]}:1 ({low[0][1]} on {low[0][2]}).", "Verify with a contrast checker.", "Low"))
    return out


# ---------------------------------------------------------------- Mobile
def check_mobile(url: str, soup: BeautifulSoup) -> list[Issue]:
    vp = soup.find("meta", attrs={"name": re.compile("^viewport$", re.I)})
    if not vp:
        return [_i("Technical", "Missing viewport meta tag", url, "Without a viewport tag, mobile browsers typically render the page at desktop width.", "No <meta name=\"viewport\">.", "Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">.", "High")]
    c = (vp.get("content") or "").lower().replace(" ", "")
    out = []
    if "width=device-width" not in c:
        out.append(_i("Technical", "Viewport not device-width", url, "A fixed viewport width may not adapt to small screens.", f"viewport content='{vp.get('content')}'", "Use width=device-width.", "Medium"))
    if "user-scalable=no" in c or "maximum-scale=1" in c:
        out.append(_i("Accessibility", "Viewport blocks zoom", url, "Disabling pinch-zoom hinders low-vision users (WCAG 1.4.4).", f"viewport content='{vp.get('content')}'", "Remove user-scalable=no / maximum-scale=1.", "Medium"))
    return out


# ---------------------------------------------------------------- Security headers
def check_security_headers(url: str, headers: dict[str, str], is_https: bool) -> list[Issue]:
    """Passive header presence check only. Not a penetration test or security rating."""
    h = {k.lower(): v for k, v in headers.items()}
    X = "Security Headers"
    out: list[Issue] = []
    if not is_https:
        out.append(_i(X, "Page served over HTTP", url, "HTTP traffic is unencrypted and can be read or altered in transit.", "URL scheme is http.", "Serve the site over HTTPS and redirect HTTP to it.", "High"))
    if is_https and "strict-transport-security" not in h:
        out.append(_i(X, "Missing Strict-Transport-Security (HSTS)", url, "HSTS tells browsers to use HTTPS only for this host.", "Header not present.", "Add Strict-Transport-Security with a suitable max-age once HTTPS is stable.", "Medium"))
    if "content-security-policy" not in h:
        out.append(_i(X, "Missing Content-Security-Policy", url, "CSP can limit which sources a page may load, reducing the impact of some injection bugs.", "Header not present.", "Define a CSP; start in report-only mode if unsure.", "Medium"))
    if h.get("x-content-type-options", "").lower() != "nosniff":
        out.append(_i(X, "Missing X-Content-Type-Options: nosniff", url, "Prevents browsers from MIME-sniffing responses into a different type.", f"Value: '{h.get('x-content-type-options', '(absent)')}'", "Add X-Content-Type-Options: nosniff.", "Low"))
    if "referrer-policy" not in h:
        out.append(_i(X, "Missing Referrer-Policy", url, "Controls how much URL information is sent in the Referer header.", "Header not present.", "Add e.g. Referrer-Policy: strict-origin-when-cross-origin.", "Low"))
    csp = h.get("content-security-policy", "")
    if "x-frame-options" not in h and "frame-ancestors" not in csp.lower():
        out.append(_i(X, "No framing protection", url, "Without X-Frame-Options or CSP frame-ancestors, other sites may embed this page in a frame (clickjacking risk).", "Neither header present.", "Add X-Frame-Options or CSP frame-ancestors.", "Medium"))
    if "server" in h and re.search(r"\d+\.\d+", h["server"]):
        out.append(_i(X, "Server header discloses version", url, "Version details can help someone look up known issues for that software.", f"Server: {h['server']}", "Consider hiding version numbers.", "Info"))
    return out


# ---------------------------------------------------------------- Performance
def check_performance(url: str, page: PageResult, headers: dict[str, str]) -> list[Issue]:
    h = {k.lower(): v for k, v in headers.items()}
    P = "Performance"
    out: list[Issue] = []
    if page.response_time_ms > 1500:
        out.append(_i(P, "Slow server response", url, "A slow response delays everything that follows. Time includes network latency from where this tool runs.", f"{page.response_time_ms:.0f} ms to download the HTML.", "Check server processing, caching and hosting location.", "High" if page.response_time_ms > 3000 else "Medium"))
    if page.html_bytes > 500_000:
        out.append(_i(P, "Large HTML document", url, "Larger documents take longer to download and parse.", f"{page.html_bytes / 1024:.0f} KB of HTML.", "Reduce inline content and markup.", "Medium"))
    total = page.html_bytes + page.resource_bytes
    if total > 3_000_000:
        out.append(_i(P, "Large total page weight", url, "Heavy pages cost more on slow or metered connections.", f"~{total / 1e6:.1f} MB (HTML + resources with a known size).", "Optimise images and scripts.", "Medium"))
    if page.resource_count > 100:
        out.append(_i(P, "High number of requests", url, "Many requests add overhead, especially on HTTP/1.1.", f"{page.resource_count} sub-resources referenced.", "Bundle or lazy-load resources.", "Low"))
    enc = h.get("content-encoding", "").lower()
    ctype = h.get("content-type", "")
    if page.html_bytes > 2048 and not any(e in enc for e in ("gzip", "br", "zstd", "deflate")):
        out.append(_i(P, "HTML not compressed", url, "Text compresses well; compression usually cuts transfer size substantially.", f"No Content-Encoding on {ctype or 'response'}; {page.html_bytes / 1024:.0f} KB.", "Enable gzip or Brotli on the server.", "Medium"))
    if "cache-control" not in h and "expires" not in h:
        out.append(_i(P, "No caching headers on HTML", url, "Without caching headers, browsers and CDNs must guess how long to reuse the response.", "No Cache-Control or Expires.", "Set an appropriate Cache-Control policy.", "Low"))
    return out


def check_resource(page_url: str, res_url: str, kind: str, status: int, headers: dict[str, str], err: str) -> list[Issue]:
    h = {k.lower(): v for k, v in headers.items()}
    out: list[Issue] = []
    if status == 0 or status >= 400:
        cat = "Technical"
        title = "Broken image" if kind == "image" else f"Broken {kind} resource"
        out.append(_i(cat, title, page_url, "Resources that fail to load can leave a page visibly or functionally incomplete.", f"{res_url} -> {'error: ' + err if status == 0 else 'HTTP ' + str(status)}", "Fix or remove the reference.", "High" if kind != "image" else "Medium"))
        return out
    try:
        size = int(h.get("content-length", "0"))
    except ValueError:
        size = 0
    if kind == "image" and size > 300_000:
        out.append(_i("Performance", "Large image file", page_url, "Large images are a common cause of heavy pages.", f"{res_url} is {size / 1024:.0f} KB.", "Resize and compress; consider WebP/AVIF.", "Medium"))
    if kind in ("script", "style") and size > 250_000 and "content-encoding" not in h:
        out.append(_i("Performance", f"Large uncompressed {kind} file", page_url, "Large text assets benefit from compression.", f"{res_url} is {size / 1024:.0f} KB with no Content-Encoding.", "Enable compression and minify.", "Medium"))
    if kind in ("image", "script", "style") and "cache-control" not in h and "expires" not in h and "etag" not in h:
        out.append(_i("Performance", "Static resource without caching headers", page_url, "Static assets are usually safe to cache for longer periods.", f"{res_url} has no Cache-Control/Expires/ETag.", "Add long-lived Cache-Control for versioned assets.", "Low"))
    return out


def img_has_dimensions(soup: BeautifulSoup, url: str) -> list[Issue]:
    n = [i for i in soup.find_all("img") if not (i.get("width") and i.get("height"))]
    if len(n) > 3:
        return [_i("Performance", "Images without width/height attributes", url, "Declaring dimensions lets browsers reserve space and can reduce layout shifts.", f"{len(n)} images lack width/height.", "Add width and height attributes.", "Low")]
    return []


# ---------------------------------------------------------------- Technical (page level)
def check_technical(url: str, page: PageResult) -> list[Issue]:
    out: list[Issue] = []
    T = "Technical"
    if page.error:
        out.append(_i(T, "Page could not be fetched", url, "Pages that fail to load cannot be used or evaluated.", page.error, "Check server availability and the URL.", "High"))
        return out
    if page.status >= 400:
        out.append(_i(T, f"HTTP error {page.status}", url, "Error responses are not useful to visitors.", f"Status {page.status}.", "Fix the page or update links pointing to it.", "High"))
    if len(page.redirects) > 1:
        out.append(_i(T, "Redirect chain", url, "Each extra redirect adds a round trip.", " -> ".join(page.redirects + [page.final_url]), "Link directly to the final URL.", "Low" if len(page.redirects) == 2 else "Medium"))
    elif page.redirects:
        out.append(_i(T, "URL redirects", url, "Internal links to redirecting URLs cost an extra request.", f"{url} -> {page.final_url}", "Update the link to the final URL.", "Info"))
    if page.canonical and page.final_url:
        from urllib.parse import urljoin
        c = urljoin(page.final_url, page.canonical).rstrip("/")
        if c != page.final_url.rstrip("/"):
            out.append(_i(T, "Canonical points elsewhere", url, "The page asks to be treated as a duplicate of another URL; unintended values can exclude the page.", f"canonical = {c}", "Confirm the canonical is intentional.", "Info"))
    return out


def check_site_duplicates(pages: list[PageResult]) -> list[Issue]:
    out: list[Issue] = []
    for attr, label in (("title", "Duplicate title"), ("meta_description", "Duplicate meta description")):
        seen: dict[str, list[str]] = {}
        for p in pages:
            v = getattr(p, attr).strip().lower()
            if v and p.status == 200:
                seen.setdefault(v, []).append(p.final_url or p.url)
        for v, urls in seen.items():
            if len(urls) > 1:
                for u in urls:
                    out.append(_i("SEO" if attr == "title" else "SEO", label, u, "Identical text across pages makes them harder to tell apart in search results.", f"Shared by {len(urls)} pages: '{v[:80]}'", "Write unique text for each page.", "Medium" if attr == "title" else "Low"))
    return out
