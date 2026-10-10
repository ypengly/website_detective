from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any

CATEGORIES = ["SEO", "Performance", "Accessibility", "Technical", "Security Headers"]
SEVERITIES = ["High", "Medium", "Low", "Info"]
SEVERITY_WEIGHT = {"High": 10.0, "Medium": 4.0, "Low": 1.5, "Info": 0.0}


@dataclass
class Issue:
    category: str
    title: str
    url: str
    why: str
    evidence: str
    suggestion: str
    severity: str = "Medium"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PageResult:
    url: str
    final_url: str = ""
    status: int = 0
    response_time_ms: float = 0.0
    html_bytes: int = 0
    transferred_bytes: int | None = None
    resource_count: int = 0
    resource_bytes: int = 0
    redirects: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    title: str = ""
    meta_description: str = ""
    canonical: str = ""
    word_count: int = 0
    h1_count: int = 0
    error: str = ""
    rendered: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("headers", None)
        return d


@dataclass
class AuditResult:
    start_url: str
    domain: str
    started_at: str
    duration_s: float = 0.0
    pages: list[PageResult] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    site_info: dict[str, Any] = field(default_factory=dict)
    scores: dict[str, int] = field(default_factory=dict)
    cancelled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_url": self.start_url, "domain": self.domain,
            "started_at": self.started_at, "duration_s": round(self.duration_s, 2),
            "pages_scanned": len(self.pages), "issue_count": len(self.issues),
            "cancelled": self.cancelled, "scores": self.scores,
            "site_info": self.site_info,
            "pages": [p.to_dict() for p in self.pages],
            "issues": [i.to_dict() for i in self.issues],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AuditResult":
        r = cls(d["start_url"], d["domain"], d["started_at"], d.get("duration_s", 0.0))
        r.pages = [PageResult(**p) for p in d.get("pages", [])]
        r.issues = [Issue(**i) for i in d.get("issues", [])]
        r.site_info = d.get("site_info", {})
        r.scores = d.get("scores", {})
        r.cancelled = d.get("cancelled", False)
        return r

    def by_category(self, cat: str) -> list[Issue]:
        return [i for i in self.issues if i.category == cat]
