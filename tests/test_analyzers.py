import unittest
from bs4 import BeautifulSoup
from website_detective import analyzers as an
from website_detective.models import PageResult


def titles(issues): return {i.title for i in issues}


class SeoTests(unittest.TestCase):
    def test_missing_everything(self):
        soup = BeautifulSoup("<html><body><p>x</p></body></html>", "lxml")
        t = titles(an.check_seo("http://x/", soup, PageResult("http://x/", status=200)))
        for expected in ("Missing <title>", "Missing meta description", "Missing canonical link", "Missing H1 heading",
                         "Incomplete Open Graph metadata", "No structured data detected"):
            self.assertIn(expected, t)

    def test_good_page(self):
        html = """<html><head><title>A good descriptive title</title><meta name="description" content="d">
        <link rel="canonical" href="/"><meta property="og:title" content="t"><meta property="og:description" content="d">
        <meta property="og:image" content="i"><script type="application/ld+json">{"@type":"Thing"}</script></head>
        <body><h1>Hi</h1></body></html>"""
        t = titles(an.check_seo("http://x/", BeautifulSoup(html, "lxml"), PageResult("http://x/")))
        self.assertNotIn("Missing <title>", t); self.assertNotIn("Missing canonical link", t)
        self.assertNotIn("No structured data detected", t); self.assertNotIn("Missing H1 heading", t)

    def test_invalid_jsonld(self):
        soup = BeautifulSoup('<script type="application/ld+json">{bad</script>', "lxml")
        self.assertIn("Invalid JSON-LD structured data", titles(an.check_seo("u", soup, PageResult("u"))))


class AccessibilityTests(unittest.TestCase):
    def test_detects_problems(self):
        html = """<html><body><h1>a</h1><h4>b</h4><img src="a.png"><a href="/x"></a>
        <input type="text" name="n"><button></button><div id="d"></div><div id="d"></div>
        <p style="color:#777777;background:#888888">t</p><span aria-labelledby="nope"></span></body></html>"""
        t = titles(an.check_accessibility("u", BeautifulSoup(html, "lxml")))
        for e in ("Missing html lang attribute", "Images missing alt attribute", "Heading hierarchy skips a level",
                  "Form fields without labels", "Links without accessible name", "Buttons without accessible name",
                  "Duplicate id attributes", "aria-labelledby references missing id",
                  "Possible low colour contrast (indicator only)"):
            self.assertIn(e, t)

    def test_labelled_ok(self):
        html = '<html lang="en"><body><label for="a">A</label><input id="a"><img src="x" alt=""><a href="/">Home</a></body></html>'
        t = titles(an.check_accessibility("u", BeautifulSoup(html, "lxml")))
        self.assertEqual(t, set())

    def test_contrast_math(self):
        self.assertAlmostEqual(an.contrast_ratio("#000", "#fff"), 21.0, places=1)
        self.assertIsNone(an.contrast_ratio("zzz", "#fff"))


class SecurityTests(unittest.TestCase):
    def test_missing_headers(self):
        t = titles(an.check_security_headers("https://x/", {}, True))
        self.assertTrue({"Missing Strict-Transport-Security (HSTS)", "Missing Content-Security-Policy",
                         "Missing Referrer-Policy", "No framing protection"} <= t)

    def test_http(self):
        self.assertIn("Page served over HTTP", titles(an.check_security_headers("http://x/", {}, False)))

    def test_all_present(self):
        h = {"Strict-Transport-Security": "max-age=1", "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
             "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}
        self.assertEqual(an.check_security_headers("https://x/", h, True), [])


class MiscTests(unittest.TestCase):
    def test_performance(self):
        p = PageResult("u", response_time_ms=4000, html_bytes=600_000)
        t = titles(an.check_performance("u", p, {}))
        self.assertTrue({"Slow server response", "Large HTML document", "HTML not compressed", "No caching headers on HTML"} <= t)

    def test_viewport(self):
        self.assertIn("Missing viewport meta tag", titles(an.check_mobile("u", BeautifulSoup("<html></html>", "lxml"))))

    def test_duplicates(self):
        a = PageResult("a", final_url="a", status=200, title="Same", meta_description="d")
        b = PageResult("b", final_url="b", status=200, title="same", meta_description="d")
        t = titles(an.check_site_duplicates([a, b]))
        self.assertEqual(t, {"Duplicate title", "Duplicate meta description"})

    def test_resource(self):
        t = titles(an.check_resource("p", "r", "image", 404, {}, ""))
        self.assertEqual(t, {"Broken image"})
        self.assertIn("Large image file", titles(an.check_resource("p", "r", "image", 200, {"Content-Length": "999999"}, "")))


if __name__ == "__main__":
    unittest.main()
