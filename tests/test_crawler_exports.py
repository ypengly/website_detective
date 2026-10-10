import csv, json, os, tempfile, threading, unittest
from website_detective.crawler import Crawler
from website_detective.exporters import export_csv, export_html, export_json, export_pdf, _csv_safe
from website_detective.fetcher import normalize_url, canonical_key, same_site
from website_detective.models import AuditResult
from website_detective.storage import Storage
from tests import site_fixture


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.base = site_fixture.start()
        cls.result = Crawler(cls.base + "/", max_pages=10, delay=0).run()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()


class UrlTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_url("Example.com"), "https://example.com/")
        with self.assertRaises(ValueError): normalize_url("")
        with self.assertRaises(ValueError): normalize_url("ftp://x.com")

    def test_helpers(self):
        self.assertEqual(canonical_key("http://A.com/x#frag"), "http://a.com/x")
        self.assertTrue(same_site("http://www.a.com/x", "a.com"))
        self.assertFalse(same_site("http://b.com/x", "a.com"))


class CrawlTests(Base):
    def titles(self): return {i.title for i in self.result.issues}

    def test_pages_and_robots(self):
        urls = [p.url for p in self.result.pages]
        self.assertFalse(any("/private/" in u for u in urls), "robots.txt Disallow must be respected")
        self.assertTrue(any(u.endswith("/about") for u in urls))
        self.assertFalse(any("invalid" in u for u in urls), "external domains must not be crawled")
        self.assertTrue(self.result.site_info["robots_txt"])
        self.assertGreaterEqual(self.result.site_info["blocked_by_robots"], 1)

    def test_findings(self):
        t = self.titles()
        for e in ("Broken image", "Broken internal link", "Duplicate title", "Missing html lang attribute",
                  "Multiple H1 headings", "Form fields without labels", "Missing Content-Security-Policy", "Page served over HTTP"):
            self.assertIn(e, t)
        self.assertNotIn("No sitemap found", t)

    def test_issue_fields_complete(self):
        for i in self.result.issues:
            for f in (i.title, i.url, i.why, i.evidence, i.suggestion):
                self.assertTrue(f)

    def test_scores(self):
        self.assertTrue(all(0 <= v <= 100 for v in self.result.scores.values()))
        self.assertIn("Overall", self.result.scores)

    def test_page_limit_and_cancel(self):
        r = Crawler(self.base + "/", max_pages=1, delay=0).run()
        self.assertEqual(len(r.pages), 1)
        ev = threading.Event(); ev.set()
        r = Crawler(self.base + "/", max_pages=10, delay=0, cancel=ev).run()
        self.assertTrue(r.cancelled); self.assertEqual(len(r.pages), 0)

    def test_unreachable_host(self):
        r = Crawler("http://127.0.0.1:9/", max_pages=1, delay=0).run()
        self.assertEqual(len(r.pages), 1)
        self.assertIn("Page could not be fetched", {i.title for i in r.issues})


class ExportTests(Base):
    def test_all_exports(self):
        with tempfile.TemporaryDirectory() as d:
            j, c, h, p = (os.path.join(d, "a." + e) for e in ("json", "csv", "html", "pdf"))
            export_json(self.result, j); export_csv(self.result, c); export_html(self.result, h); export_pdf(self.result, p)
            with open(j, encoding="utf-8") as fh: data = json.load(fh)
            self.assertEqual(data["issue_count"], len(self.result.issues))
            with open(c, encoding="utf-8-sig") as fh: rows = list(csv.reader(fh))
            self.assertEqual(len(rows), len(self.result.issues) + 1)
            with open(h, encoding="utf-8") as fh: self.assertIn("WEBSITE AUDIT", fh.read())
            with open(p, "rb") as fh: self.assertEqual(fh.read(5), b"%PDF-")

    def test_csv_injection_guard(self):
        self.assertEqual(_csv_safe("=HYPERLINK(1)"), "'=HYPERLINK(1)")

    def test_storage_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            s = Storage(os.path.join(d, "t.db"))
            i = s.save(self.result)
            self.assertEqual(s.list()[0]["id"], i)
            back = s.load(i)
            self.assertEqual(len(back.issues), len(self.result.issues))
            self.assertIsInstance(back, AuditResult)
            s.delete(i); self.assertIsNone(s.load(i))


if __name__ == "__main__":
    unittest.main()
