from __future__ import annotations
import sys, threading
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QLabel,
                               QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QProgressBar, QTabWidget, QTableWidget,
                               QTableWidgetItem, QTextBrowser, QFileDialog, QMessageBox, QPlainTextEdit, QSplitter,
                               QHeaderView, QAbstractItemView, QFrame, QGridLayout)
import html as _html

from . import __version__
from .crawler import Crawler
from .exporters import EXPORTERS, score_chart_png, severity_chart_png, SEV_COLOR, DISCLAIMER, sorted_issues
from .models import AuditResult, CATEGORIES, SEVERITIES
from .render import playwright_available
from .storage import Storage


class AuditWorker(QThread):
    progress = Signal(int, int, str)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, **kw):
        super().__init__()
        self.kw = kw
        self.cancel_event = threading.Event()

    def run(self):  # runs off the UI thread
        try:
            res = Crawler(progress=lambda d, t, m: self.progress.emit(d, t, m), cancel=self.cancel_event, **self.kw).run()
            self.finished_ok.emit(res)
        except Exception as e:  # never let a worker crash the app
            self.failed.emit(f"{type(e).__name__}: {e}")

    def stop(self):
        self.cancel_event.set()


class ExportWorker(QThread):
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, fmt, result, path):
        super().__init__(); self.fmt, self.result, self.path = fmt, result, path

    def run(self):
        try:
            EXPORTERS[self.fmt](self.result, self.path); self.done.emit(self.path)
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")


class Card(QFrame):
    def __init__(self, label):
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        l = QVBoxLayout(self)
        self.k = QLabel(label); self.k.setStyleSheet("color:#667;font-size:11px")
        self.v = QLabel("—"); self.v.setStyleSheet("font-size:18px;font-weight:600")
        l.addWidget(self.k); l.addWidget(self.v)

    def set(self, text): self.v.setText(str(text))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Website Detective 🕵️  v{__version__}")
        self.resize(1200, 800)
        self.storage = Storage()
        self.result: AuditResult | None = None
        self.worker: AuditWorker | None = None
        self._export_worker = None
        self._shown: list = []

        root = QWidget(); self.setCentralWidget(root)
        v = QVBoxLayout(root)

        row = QHBoxLayout()
        self.url = QLineEdit(); self.url.setPlaceholderText("https://example.com"); self.url.returnPressed.connect(self.start)
        self.btn = QPushButton("🔎 Analyze Website"); self.btn.clicked.connect(self.start)
        self.stop_btn = QPushButton("Stop"); self.stop_btn.setEnabled(False); self.stop_btn.clicked.connect(self.stop)
        row.addWidget(self.url, 1); row.addWidget(self.btn); row.addWidget(self.stop_btn)
        v.addLayout(row)

        opt = QHBoxLayout()
        opt.addWidget(QLabel("Maximum pages:"))
        self.pages = QComboBox(); self.pages.addItems(["10", "25", "50", "100", "Custom"]); self.pages.setCurrentText("25")
        self.pages.currentTextChanged.connect(lambda t: self.custom.setEnabled(t == "Custom"))
        self.custom = QSpinBox(); self.custom.setRange(1, 1000); self.custom.setValue(30); self.custom.setEnabled(False)
        self.delay = QDoubleSpinBox(); self.delay.setRange(0.0, 10.0); self.delay.setSingleStep(0.25); self.delay.setValue(0.5); self.delay.setSuffix(" s delay")
        self.robots = QCheckBox("Respect robots.txt"); self.robots.setChecked(True)
        self.res = QCheckBox("Check images/assets"); self.res.setChecked(True)
        self.browser = QCheckBox("Render with browser (Playwright)")
        if not playwright_available():
            self.browser.setEnabled(False); self.browser.setToolTip("Playwright is not installed")
        for w in (self.pages, self.custom, self.delay, self.robots, self.res, self.browser):
            opt.addWidget(w)
        opt.addStretch(1)
        v.addLayout(opt)
        note = QLabel("Only audit sites you own or have permission to scan. This is a passive technical review, not a penetration test.")
        note.setStyleSheet("color:#667;font-size:11px"); v.addWidget(note)

        grid = QGridLayout()
        self.cards = {k: Card(k) for k in ("Domain", "Scan time", "Pages scanned", "Scan duration", "Issues found", "Overall score")}
        for n, c in enumerate(self.cards.values()):
            grid.addWidget(c, 0, n)
        v.addLayout(grid)
        self.bar = QProgressBar(); self.bar.setVisible(False); v.addWidget(self.bar)
        self.status = QLabel("Ready."); v.addWidget(self.status)

        self.tabs = QTabWidget(); v.addWidget(self.tabs, 1)
        # overview
        ov = QWidget(); ol = QVBoxLayout(ov)
        ch = QHBoxLayout(); self.chart1 = QLabel(); self.chart2 = QLabel(); ch.addWidget(self.chart1); ch.addWidget(self.chart2)
        ol.addLayout(ch); self.summary = QTextBrowser(); ol.addWidget(self.summary, 1)
        self.tabs.addTab(ov, "Overview")
        # issues
        iw = QWidget(); il = QVBoxLayout(iw)
        f = QHBoxLayout()
        self.cat = QComboBox(); self.cat.addItems(["All categories"] + CATEGORIES)
        self.sev = QComboBox(); self.sev.addItems(["All severities"] + SEVERITIES)
        self.search = QLineEdit(); self.search.setPlaceholderText("Filter text…")
        for w in (self.cat, self.sev):
            w.currentIndexChanged.connect(self.refill)
        self.search.textChanged.connect(self.refill)
        f.addWidget(self.cat); f.addWidget(self.sev); f.addWidget(self.search, 1); il.addLayout(f)
        sp = QSplitter(Qt.Vertical)
        self.table = QTableWidget(0, 4); self.table.setHorizontalHeaderLabels(["Severity", "Category", "Issue", "URL"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self.show_detail)
        self.detail = QTextBrowser(); sp.addWidget(self.table); sp.addWidget(self.detail); sp.setSizes([400, 200])
        il.addWidget(sp, 1); self.tabs.addTab(iw, "Issues")
        # pages
        self.ptable = QTableWidget(0, 6); self.ptable.setHorizontalHeaderLabels(["URL", "Status", "ms", "HTML KB", "Resources", "Title"])
        self.ptable.setEditTriggers(QAbstractItemView.NoEditTriggers); self.ptable.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tabs.addTab(self.ptable, "Pages")
        # history
        hw = QWidget(); hl = QVBoxLayout(hw)
        self.htable = QTableWidget(0, 6); self.htable.setHorizontalHeaderLabels(["ID", "Domain", "Date", "Pages", "Issues", "Score"])
        self.htable.setEditTriggers(QAbstractItemView.NoEditTriggers); self.htable.setSelectionBehavior(QAbstractItemView.SelectRows)
        hb = QHBoxLayout(); lb = QPushButton("Open selected"); lb.clicked.connect(self.open_history)
        db = QPushButton("Delete selected"); db.clicked.connect(self.delete_history); hb.addWidget(lb); hb.addWidget(db); hb.addStretch(1)
        hl.addWidget(self.htable, 1); hl.addLayout(hb); self.tabs.addTab(hw, "History")
        # log
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.tabs.addTab(self.log, "Log")

        ex = QHBoxLayout(); ex.addWidget(QLabel("Export:"))
        self.exp_btns = []
        for fmt in ("PDF", "HTML", "JSON", "CSV"):
            b = QPushButton(fmt); b.setEnabled(False); b.clicked.connect(lambda _=False, f=fmt.lower(): self.export(f))
            ex.addWidget(b); self.exp_btns.append(b)
        ex.addStretch(1); v.addLayout(ex)
        self.load_history()

    # ---- run
    def max_pages(self) -> int:
        t = self.pages.currentText()
        return self.custom.value() if t == "Custom" else int(t)

    def start(self):
        if self.worker and self.worker.isRunning():
            return
        if not self.url.text().strip():
            QMessageBox.information(self, "Website Detective", "Enter a website URL first."); return
        try:
            from .fetcher import normalize_url
            url = normalize_url(self.url.text())
        except ValueError as e:
            QMessageBox.warning(self, "Invalid URL", str(e)); return
        self.log.clear(); self.bar.setVisible(True); self.bar.setRange(0, 0)
        self.btn.setEnabled(False); self.stop_btn.setEnabled(True)
        for b in self.exp_btns: b.setEnabled(False)
        self.cards["Domain"].set(url.split("//", 1)[-1].split("/")[0]); self.status.setText("Starting…")
        self.worker = AuditWorker(start_url=url, max_pages=self.max_pages(), delay=self.delay.value(),
                                  respect_robots=self.robots.isChecked(), use_browser=self.browser.isChecked(),
                                  check_resources=self.res.isChecked())
        self.worker.progress.connect(self.on_progress); self.worker.finished_ok.connect(self.on_done); self.worker.failed.connect(self.on_fail)
        self.worker.start()

    def stop(self):
        if self.worker:
            self.worker.stop(); self.status.setText("Stopping after current request…")

    def on_progress(self, done, total, msg):
        self.bar.setRange(0, max(1, total)); self.bar.setValue(min(done, total)); self.status.setText(msg); self.log.appendPlainText(msg)

    def _idle(self):
        self.btn.setEnabled(True); self.stop_btn.setEnabled(False); self.bar.setVisible(False)

    def on_fail(self, msg):
        self._idle(); self.status.setText("Failed."); QMessageBox.critical(self, "Analysis failed", msg)

    def on_done(self, res: AuditResult):
        self._idle()
        try:
            self.storage.save(res); self.load_history()
        except Exception as e:
            self.log.appendPlainText(f"Could not save to history: {e}")
        self.show_result(res)
        self.status.setText("Scan cancelled — partial results shown." if res.cancelled else "Done.")

    # ---- display
    def show_result(self, res: AuditResult):
        self.result = res
        c = self.cards
        c["Domain"].set(res.domain); c["Scan time"].set(res.started_at); c["Pages scanned"].set(len(res.pages))
        c["Scan duration"].set(f"{res.duration_s:.1f} s"); c["Issues found"].set(len(res.issues)); c["Overall score"].set(res.scores.get("Overall", "—"))
        for lab, fn in ((self.chart1, score_chart_png), (self.chart2, severity_chart_png)):
            pm = QPixmap(); pm.loadFromData(fn(res)); lab.setPixmap(pm.scaledToWidth(540, Qt.SmoothTransformation))
        e = _html.escape
        si = res.site_info
        rows = "".join(f"<li><b>{e(k)}</b>: {res.scores.get(k, 0)} ({len(res.by_category(k))} findings)</li>" for k in CATEGORIES)
        self.summary.setHtml(f"<h3>Overall findings</h3><ul>{rows}</ul><p>robots.txt: {si.get('robots_txt')} · sitemap: {e(str(si.get('sitemap_url') or 'none'))} · "
                             f"blocked by robots: {si.get('blocked_by_robots', 0)} · requests made: {si.get('http_requests_made')}</p><p><i>{e(DISCLAIMER)}</i></p>")
        self.refill()
        self.ptable.setRowCount(len(res.pages))
        for r, p in enumerate(res.pages):
            for col, val in enumerate((p.url, p.status or p.error[:30], f"{p.response_time_ms:.0f}", f"{p.html_bytes / 1024:.1f}", p.resource_count, p.title)):
                self.ptable.setItem(r, col, QTableWidgetItem(str(val)))
        for b in self.exp_btns: b.setEnabled(True)

    def refill(self):
        self.table.setRowCount(0); self.detail.clear(); self._shown = []
        if not self.result: return
        cat, sev, q = self.cat.currentText(), self.sev.currentText(), self.search.text().lower()
        for i in sorted_issues(self.result.issues):
            if cat != "All categories" and i.category != cat: continue
            if sev != "All severities" and i.severity != sev: continue
            if q and q not in (i.title + i.url + i.evidence).lower(): continue
            self._shown.append(i)
        self.table.setRowCount(len(self._shown))
        for r, i in enumerate(self._shown):
            for col, val in enumerate((i.severity, i.category, i.title, i.url)):
                it = QTableWidgetItem(val)
                if col == 0: it.setForeground(QColor(SEV_COLOR[i.severity]))
                self.table.setItem(r, col, it)

    def show_detail(self):
        r = self.table.currentRow()
        if 0 <= r < len(self._shown):
            i, e = self._shown[r], _html.escape
            self.detail.setHtml(f"<h3>{e(i.title)} [{e(i.severity)}]</h3><p><b>URL</b><br>{e(i.url)}</p><p><b>Why it matters</b><br>{e(i.why)}</p>"
                                f"<p><b>Evidence</b><br>{e(i.evidence)}</p><p><b>Suggested improvement</b><br>{e(i.suggestion)}</p>")

    # ---- export / history
    def export(self, fmt):
        if not self.result: return
        default = f"website-audit-{self.result.domain}.{fmt}"
        path, _ = QFileDialog.getSaveFileName(self, f"Export {fmt.upper()}", default, f"*.{fmt}")
        if not path: return
        self._export_worker = ExportWorker(fmt, self.result, path)
        self._export_worker.done.connect(lambda p: self.status.setText(f"Exported {p}"))
        self._export_worker.failed.connect(lambda m: QMessageBox.critical(self, "Export failed", m))
        self._export_worker.start(); self.status.setText("Exporting…")

    def load_history(self):
        rows = self.storage.list()
        self.htable.setRowCount(len(rows))
        for r, d in enumerate(rows):
            for c, k in enumerate(("id", "domain", "started_at", "pages", "issues", "overall")):
                self.htable.setItem(r, c, QTableWidgetItem(str(d[k])))

    def _sel_id(self):
        r = self.htable.currentRow()
        return int(self.htable.item(r, 0).text()) if r >= 0 else None

    def open_history(self):
        i = self._sel_id()
        res = self.storage.load(i) if i else None
        if res: self.show_result(res); self.tabs.setCurrentIndex(0)

    def delete_history(self):
        i = self._sel_id()
        if i and QMessageBox.question(self, "Delete", "Delete this saved audit?") == QMessageBox.Yes:
            self.storage.delete(i); self.load_history()

    def closeEvent(self, ev):
        if self.worker and self.worker.isRunning():
            self.worker.stop(); self.worker.wait(5000)
        super().closeEvent(ev)


def main() -> int:
    app = QApplication(sys.argv)
    w = MainWindow(); w.show()
    return app.exec()
