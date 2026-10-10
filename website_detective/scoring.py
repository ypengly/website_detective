"""Heuristic category scores (0-100).

These are a summary aid for this tool only. They are NOT a prediction of search
ranking, user experience, or security posture.
"""
from __future__ import annotations
from .models import AuditResult, CATEGORIES, SEVERITY_WEIGHT


def compute_scores(result: AuditResult) -> dict[str, int]:
    total_pages = max(1, len(result.pages))
    scores = {}
    for cat in CATEGORIES:
        groups: dict[str, tuple[str, set[str]]] = {}
        for i in result.by_category(cat):
            groups.setdefault(i.title, (i.severity, set()))[1].add(i.url)
        penalty = 0.0
        for sev, urls in groups.values():
            share = min(1.0, len(urls) / total_pages)
            penalty += SEVERITY_WEIGHT.get(sev, 0) * (0.5 + 0.5 * share)
        scores[cat] = max(0, round(100 - penalty))
    scores["Overall"] = round(sum(scores[c] for c in CATEGORIES) / len(CATEGORIES))
    return scores
