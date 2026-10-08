"""阶段 ②：解析。把归一化文本切成「题目」结构，保留行号锚点。

切题策略（顺序尝试，先严格后宽松）：
  1. Markdown 标题行  `## 3. 求行列式...`  /  `### 题 3`
  2. 编号行          `3. ...` / `3、...` / `(3) ...` / `Problem 3` / `习题 3`
  3. 空行分块        兜底：连续非空行成一块

小问切分：`(a)` `(b)` `(1)` `(2)` `①②③` `（i）（ii）`。
不使用大模型做这一步 —— 切题必须是确定性的，否则行号锚点不可复核。
"""
from __future__ import annotations

import hashlib
import re
from typing import Iterable

HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s*(.+?)\s*$")
NUMBERED_RES = [
    re.compile(r"^\s*\**\s*(?:题目|习题|问题)?\s*(\d{1,2})\s*[.、．)）]\s*(.+)$"),
    re.compile(r"^\s*[(（]\s*(\d{1,2})\s*[)）]\s*(.+)$"),
    re.compile(r"^\s*(?:Problem|Exercise|Question)\s+(\d{1,2})\s*[:.]?\s*(.+)$",
               re.I),
    re.compile(r"^\s*\*\*(?:题目|习题)?\s*(\d{1,2})\s*[.、．]\s*(.+?)\*\*\s*$"),
]
SUBITEM_RE = re.compile(
    r"[(（]\s*([a-hA-H]|[ivxIVX]{1,4}|\d{1,2})\s*[)）]|([①②③④⑤⑥⑦⑧⑨⑩])")
DEFAULT_DOMAIN = "linear_algebra"
MAX_TITLE_CHARS = 180


def _clean(text: str) -> str:
    text = re.sub(r"\*\*|\*|`", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _split_subitems(body: str) -> list[dict]:
    marks = list(SUBITEM_RE.finditer(body))
    if len(marks) < 2:
        return []
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        label = m.group(1) or m.group(2) or str(i + 1)
        out.append({"label": label,
                    "text": body[m.end():end].strip()})
    return [s for s in out if s["text"]]


def _mk(title: str, body: str, line: int, index: int) -> dict:
    title = _clean(title)[:MAX_TITLE_CHARS]
    body = body.strip()
    full = (title + ("\n" + body if body else "")).strip()
    pid = "P%02d" % index
    return {
        "id": pid,
        "source_line": line,
        "title": title,
        "body": body,
        "raw": full,
        "subitems": _split_subitems(full),
        "sha256": hashlib.sha256(full.encode("utf-8")).hexdigest()[:16],
    }


def _blocks_from_headings(lines: list[dict]) -> list[dict]:
    heads = []
    for item in lines:
        m = HEADING_RE.match(item["text"])
        if m and not m.group(1).startswith("#####"):
            heads.append((item["line"], m.group(2).strip()))
    if not heads:
        return []
    out = []
    for i, (line, title) in enumerate(heads):
        nxt = heads[i + 1][0] if i + 1 < len(heads) else len(lines) + 1
        body = "\n".join(x["text"] for x in lines
                         if line < x["line"] < nxt)
        out.append(_mk(title, body, line, len(out) + 1))
    return out


def _blocks_from_numbering(lines: list[dict]) -> list[dict]:
    hits = []
    for item in lines:
        for rx in NUMBERED_RES:
            m = rx.match(item["text"])
            if m:
                hits.append((item["line"], m.group(1), m.group(2)))
                break
    if len(hits) < 2:
        return []
    out = []
    for i, (line, _num, title) in enumerate(hits):
        nxt = hits[i + 1][0] if i + 1 < len(hits) else len(lines) + 1
        body = "\n".join(x["text"] for x in lines if line < x["line"] < nxt)
        # 若正文里藏着后续小问，一并保留
        out.append(_mk(title, body, line, len(out) + 1))
    return out


def _blocks_from_paragraphs(lines: list[dict]) -> list[dict]:
    out, buf, start = [], [], 0
    for item in lines:
        if item["text"].strip():
            if not buf:
                start = item["line"]
            buf.append(item["text"])
        else:
            if len(" ".join(buf)) > 25:
                out.append(_mk(buf[0], "\n".join(buf[1:]), start, len(out) + 1))
            buf = []
    if len(" ".join(buf)) > 25:
        out.append(_mk(buf[0], "\n".join(buf[1:]), start, len(out) + 1))
    return out


def parse(doc: dict) -> list[dict]:
    lines = doc.get("lines") or []
    for fn in (_blocks_from_headings, _blocks_from_numbering,
               _blocks_from_paragraphs):
        blocks = fn(lines)
        if len(blocks) >= 2:
            return [dict(b, domain=DEFAULT_DOMAIN) for b in blocks]
    return []


def iter_answers_tex(tex_text: str) -> Iterable[str]:
    """从已解好的 .tex（如 starter 的 challenge_answers_cn.tex）抽取解答段，
    用于「教师参考解」交叉比对。仅做粗切，不做语义解释。"""
    parts = re.split(r"\\(?:sub)?section\*?\{", tex_text)
    for p in parts[1:]:
        yield p[:2000]


if __name__ == "__main__":
    import json
    import sys
    import ingest as _ing
    d = _ing.ingest(sys.argv[1])
    print(json.dumps([{k: v for k, v in p.items()
                       if k in ("id", "title", "source_line", "sha256")}
                      for p in parse(d)], ensure_ascii=False, indent=2))
