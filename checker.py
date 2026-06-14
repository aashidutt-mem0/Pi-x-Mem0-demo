"""
checker.py — verify a generated migration against the seeded conventions.

Session 2 asks the agent to add a `refunds` table. This module scores whatever
SQL the agent produced against the same conventions the sandbox encodes, so the
UI can show a concrete pass/fail table instead of asking the viewer to eyeball
the diff. The rules live in sandbox.CONVENTION_RULES.

A rule passes when its `must_have` pattern is present AND its `violation`
pattern (if any) is absent. This is deliberately simple and transparent: it is
a demo aid, not a SQL linter. The point is that the no-memory output visibly
fails rules the with-memory output passes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sandbox import CONVENTION_RULES


@dataclass
class RuleResult:
    rule_id: str
    label: str
    passed: bool
    detail: str


def check_migration(sql: str) -> list[RuleResult]:
    """Score a block of migration SQL against every convention rule."""
    results: list[RuleResult] = []
    text = sql or ""
    for rule in CONVENTION_RULES:
        must = rule.get("must_have") or ""
        viol = rule.get("violation") or ""

        has_required = bool(re.search(must, text, re.IGNORECASE | re.DOTALL)) if must else True
        has_violation = bool(re.search(viol, text, re.IGNORECASE | re.DOTALL)) if viol else False

        passed = has_required and not has_violation
        if not has_required:
            detail = "required pattern missing"
        elif has_violation:
            detail = "found a disallowed pattern"
        else:
            detail = "ok"
        results.append(
            RuleResult(rule_id=rule["id"], label=rule["label"], passed=passed, detail=detail)
        )
    return results


def score(results: list[RuleResult]) -> tuple[int, int]:
    """Return (passed, total)."""
    passed = sum(1 for r in results if r.passed)
    return passed, len(results)


def extract_sql(agent_text: str) -> str:
    """
    Pull the SQL out of the agent's reply. Agents usually fence code blocks;
    grab fenced ```sql blocks if present, otherwise fall back to the raw text
    so the checker still has something to score.
    """
    if not agent_text:
        return ""
    blocks = re.findall(r"```(?:sql)?\s*(.*?)```", agent_text, re.DOTALL | re.IGNORECASE)
    if blocks:
        return "\n\n".join(b.strip() for b in blocks)
    return agent_text
