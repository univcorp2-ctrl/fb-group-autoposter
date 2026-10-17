"""Deterministic quality gate for Facebook property posts.

A post is published only when it is readable on a phone: real line breaks,
a headline, the core facts, no wall-of-text lines, no decorative rule spam and
no self-defeating numbers (e.g. a negative cash-flow projection).

score() returns 0-10; ``passes`` requires every CRITICAL check and score >= 8.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

PASS_SCORE = 8
_RULE_RUN = re.compile(r"[━─—―=＿_]{6,}")
_NEGATIVE_MONEY = re.compile(r"[-−▲△]\s*[\d,]+\s*万円|年間約\s*[-−]")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐✅]")
_HASHTAG = re.compile(r"#\S+")
REQUIRED_FACTS = ("価格", "利回り", "所在地", "交通")


@dataclass
class QualityReport:
    score: int
    issues: list[str] = field(default_factory=list)
    critical: list[str] = field(default_factory=list)

    @property
    def passes(self) -> bool:
        return not self.critical and self.score >= PASS_SCORE

    def summary(self) -> str:
        return f"score={self.score}/10 critical={self.critical} issues={self.issues}"


def evaluate(body: str) -> QualityReport:
    text = (body or "").replace("\r\n", "\n")
    lines = text.split("\n")
    content = [ln.strip() for ln in lines if ln.strip()]
    issues: list[str] = []
    critical: list[str] = []
    points = 0

    # 1. Real layout: enough separate lines (CRITICAL: one-block posts are unreadable).
    if len(content) >= 10:
        points += 1
    else:
        critical.append(f"too_few_lines:{len(content)}")

    # 2. No wall-of-text line.
    long_lines = [ln for ln in content if len(ln) > 95]
    if not long_lines:
        points += 1
    else:
        issues.append(f"long_lines:{len(long_lines)}")

    # 3. Core facts present and not placeholders (CRITICAL).
    missing = [k for k in REQUIRED_FACTS if k not in text]
    if "記載なし" in text:
        missing.append("記載なし")
    if not missing:
        points += 1
    else:
        critical.append("missing_facts:" + ",".join(missing))

    # 4. Headline first line.
    if content and content[0].startswith("【"):
        points += 1
    else:
        issues.append("no_headline")

    # 5. No decorative rule spam.
    if not _RULE_RUN.search(text):
        points += 1
    else:
        issues.append("rule_lines")

    # 6. No negative money projection (CRITICAL: actively hurts the listing).
    if not _NEGATIVE_MONEY.search(text):
        points += 1
    else:
        critical.append("negative_money_figure")

    # Implausible yield is almost always a data error (or 底地/借地) and kills
    # credibility in investor groups (CRITICAL).
    for m in re.finditer(r"利回り[^0-9\n]{0,6}([0-9]+(?:\.[0-9]+)?)%", text):
        if float(m.group(1)) > 40:
            critical.append(f"implausible_yield:{m.group(1)}")
            break

    # 7. Sensible length.
    if 250 <= len(text) <= 1100:
        points += 1
    else:
        issues.append(f"length:{len(text)}")

    # 8. Hashtags: at most 6, grouped on one line.
    tag_lines = [ln for ln in content if _HASHTAG.search(ln)]
    if len(_HASHTAG.findall(text)) <= 6 and len(tag_lines) <= 1:
        points += 1
    else:
        issues.append("hashtags")

    # 9. No duplicated lines.
    dupes = {ln for ln in content if content.count(ln) > 1 and len(ln) > 4}
    if not dupes:
        points += 1
    else:
        issues.append("duplicate_lines")

    # 10. Emoji restraint.
    if len(_EMOJI.findall(text)) <= 12:
        points += 1
    else:
        issues.append("too_many_emoji")

    return QualityReport(score=points, issues=issues, critical=critical)
