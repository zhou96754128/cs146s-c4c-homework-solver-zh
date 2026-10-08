"""阶段 ③：域路由。把每道题分派到学科域。

两条通道：
  * **规则优先**（可解释、可测）：读 domain_skills/*.yaml 的关键词表打分；
  * **模型兜底**：规则得分过低/并列时标 needs_llm，交由 solve 阶段用
    qwen3:8b 判定，并记录模型原始输出以备复核。

路由是「可迁移性」的支点：新增学科只需加一个 yaml，不改代码。
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

SKILL_ROOT = Path(__file__).resolve().parent.parent
# 学科关键词表目录：优先 references/（包内约定布局），兼容旧布局 domain_skills/
_REF_DIR = SKILL_ROOT / "references"
DOMAIN_DIR = _REF_DIR if _REF_DIR.is_dir() else SKILL_ROOT / "domain_skills"
DEFAULT_DOMAIN = "linear_algebra"
AMBIGUOUS_MARGIN = 0.15


def load_domains() -> dict:
    table = {}
    for f in sorted(DOMAIN_DIR.glob("*.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        name = d.get("domain") or f.stem
        table[name] = d
    return table


def _score(text: str, spec: dict) -> tuple[float, list[str]]:
    hits: list[str] = []
    score = 0.0
    for kw in spec.get("strong_keywords", []) or []:
        if re.search(kw, text, re.I):
            score += 2.0
            hits.append(f"strong:{kw}")
    for kw in spec.get("keywords", []) or []:
        if re.search(kw, text, re.I):
            score += 1.0
            hits.append(f"kw:{kw}")
    for kw in spec.get("negative_keywords", []) or []:
        if re.search(kw, text, re.I):
            score -= 1.5
            hits.append(f"neg:{kw}")
    return score, hits


def classify(problems: list[dict], domains: dict | None = None) -> list[dict]:
    table = domains or load_domains()
    if not table:
        for p in problems:
            p.setdefault("domain", DEFAULT_DOMAIN)
            p["route"] = {"method": "default", "score": 0.0, "hits": []}
        return problems
    for p in problems:
        text = p.get("raw", "")
        scored = []
        for name, spec in table.items():
            s, hits = _score(text, spec)
            scored.append((s, name, hits))
        scored.sort(reverse=True)
        top_s, top_name, top_hits = scored[0]
        second_s = scored[1][0] if len(scored) > 1 else -99.0
        denom = max(abs(top_s), 1.0)
        ambiguous = (top_s - second_s) / denom < AMBIGUOUS_MARGIN
        p["domain"] = top_name if top_s > 0 else DEFAULT_DOMAIN
        p["route"] = {
            "method": "rule",
            "score": round(top_s, 2),
            "runner_up": scored[1][1] if len(scored) > 1 else None,
            "margin": round((top_s - second_s) / denom, 3),
            "hits": top_hits,
            "needs_llm": bool(ambiguous or top_s <= 0),
        }
    return problems


def domain_labels(domains: dict | None = None) -> dict:
    return {k: v.get("label", k) for k, v in (domains or load_domains()).items()}
