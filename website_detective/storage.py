from __future__ import annotations
import json, sqlite3
from pathlib import Path
from .models import AuditResult


def default_db_path() -> Path:
    base = Path.home() / ".website_detective"
    base.mkdir(parents=True, exist_ok=True)
    return base / "audits.db"


class Storage:
    def __init__(self, path: str | Path | None = None):
        self.path = str(path or default_db_path())
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS audits(
                id INTEGER PRIMARY KEY AUTOINCREMENT, domain TEXT, started_at TEXT,
                duration_s REAL, pages INTEGER, issues INTEGER, overall INTEGER, data TEXT)""")

    def _conn(self):
        return sqlite3.connect(self.path)

    def save(self, r: AuditResult) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO audits(domain,started_at,duration_s,pages,issues,overall,data) VALUES(?,?,?,?,?,?,?)",
                (r.domain, r.started_at, r.duration_s, len(r.pages), len(r.issues),
                 r.scores.get("Overall", 0), json.dumps(r.to_dict())))
            return int(cur.lastrowid)

    def list(self, limit: int = 100) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT id,domain,started_at,duration_s,pages,issues,overall FROM audits ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        keys = ("id", "domain", "started_at", "duration_s", "pages", "issues", "overall")
        return [dict(zip(keys, r)) for r in rows]

    def load(self, audit_id: int) -> AuditResult | None:
        with self._conn() as c:
            row = c.execute("SELECT data FROM audits WHERE id=?", (audit_id,)).fetchone()
        return AuditResult.from_dict(json.loads(row[0])) if row else None

    def delete(self, audit_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM audits WHERE id=?", (audit_id,))
