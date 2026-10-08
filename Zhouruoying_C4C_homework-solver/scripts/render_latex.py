r"""阶段 ⑥：渲染。把题目 + 解 + 核验结果排成中文作业 PDF 的源码。

输出两份：
 * `<name>.tex` —— 可直接用 xelatex / tectonic 编译（中文用 fontspec 直连系统字体，
   不依赖 ctex/xeCJK，避免缺包）；
 * `<name>.md`  —— 便于阅读与 diff 的 Markdown 版。

排版要点（都是踩过的坑）：
 * 中文必须 XeLaTeX 系引擎（tectonic 就是）+ fontspec，pdflatex 会缺字；
 * `\XeTeXlinebreaklocale "zh"` 才能正确断行中文；
 * 长公式用 `\[ \]` 独立行，避免行内溢出；
 * 核验通过打 ✅、失败打 ⚠️ 并在汇总表里红字标出。
"""
from __future__ import annotations

import re
from pathlib import Path

FONT_STACK = ["PingFang SC", "Heiti SC", "Songti SC", "STSong",
              "Noto Sans CJK SC"]

PREAMBLE = r"""\documentclass[11pt]{article}
\usepackage[a4paper,margin=2.2cm]{geometry}
\usepackage{amsmath,amssymb,amsfonts}
\usepackage{fontspec}
\usepackage{xcolor}
\usepackage{tcolorbox}
\usepackage{booktabs}
\usepackage{enumitem}
\usepackage{array}
\tcbuselibrary{skins,breakable}
\setmainfont{%(font)s}
\XeTeXlinebreaklocale "zh"
\XeTeXlinebreakskip = 0pt plus 1pt
\definecolor{okgreen}{HTML}{1B7F3B}
\definecolor{warnred}{HTML}{B3261E}
\definecolor{aiblue}{HTML}{1F4E79}
\definecolor{rulegray}{HTML}{7A7A7A}
\newcommand{\okmark}{\textcolor{okgreen}{\textbf{[已核验]}}}
\newcommand{\warnmark}{\textcolor{warnred}{\textbf{[未通过]}}}
\newtcolorbox{aibox}[1]{colback=aiblue!4,colframe=aiblue!55,
  boxrule=0.5pt,arc=2pt,breakable,title=#1,fonttitle=\bfseries\small}
\newtcolorbox{veribox}[1]{colback=okgreen!4,colframe=okgreen!45,
  boxrule=0.5pt,arc=2pt,breakable,title=#1,fonttitle=\bfseries\small}
"""


def _tex_escape_plain(s: str) -> str:
    """只转义**非公式**文本中的裸特殊字符；题干/步骤本身已是 LaTeX。"""
    return s


def _frontmatter(meta: dict) -> str:
    lines = [r"\begin{center}", r"{\LARGE\bfseries %s}\\[6pt]" % meta["title"],
             r"{\small %s}" % r" \quad\textbar\quad ".join(
                 f"{k}：{v}" for k, v in meta.get("fields", {}).items()),
             r"\end{center}", r"\vspace{6pt}", r"\hrule", r"\vspace{10pt}"]
    return "\n".join(lines)


def _summary_table(problems) -> str:
    rows = [r"\begin{center}\small", r"\begin{tabular}{p{0.5cm}p{6.2cm}p{3.4cm}p{3.0cm}}",
            r"\toprule", r"\# & 题目 & 结果 & 核验 \\", r"\midrule"]
    for p in problems:
        stem = _short(_wrap_inline_math(
            _flatten_math_envs(p.get("stem") or p.get("raw", ""))))
        ans = p["solution"]["answer_latex"] if p.get("solution") else "—"
        if p.get("solution") and p.get("verified"):
            badge = r"\textcolor{okgreen}{\textbf{通过}}"
        elif p.get("solution"):
            badge = r"\textcolor{warnred}{\textbf{未通过}}"
        else:
            badge = "超出范围"
        rows.append(rf'{p["id"]} & {stem} & ${ans}$ & {badge} \\')
    rows += [r"\bottomrule", r"\end{tabular}", r"\end{center}"]
    return "\n".join(rows)


# 题目原文里可能夹带**裸的数学环境**（cases / 矩阵 / aligned…）。这类环境只能
# 出现在数学模式里，直接贴进正文会触发 `! Missing $ inserted.`；而贴进表格
# 单元格时 `\[ \]` 又不合法。下面按用途分别处理。
MATH_ENVS = ("cases", "aligned", "alignedat", "gathered", "split", "array",
             "matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix",
             "Vmatrix", "smallmatrix")

_ENV_RE = re.compile(r"(?<!\$)(?<!\[)\\begin\{(" + "|".join(MATH_ENVS) +
                     r")\}(.*?)\\end\{\1\}", re.S)


def _math_mode_at(s: str, idx: int) -> bool:
    r"""判断 s 的 idx 处是否**已处于数学模式**。

    判据（够用即可，不做完整 TeX 词法分析）：
     * idx 之前有未转义的奇数个行内美元符 —— 行内数学模式未闭合；
     * idx 之前 `\[` 多于 `\]`，或 `\(` 多于 `\)` —— 显式数学模式未闭合。

    踩过的坑：题目原文本身就写成「行内美元符包着 A = \begin{pmatrix}...\end{pmatrix}」
    这种形式的，再补一层 `\[ \]` 就成了嵌套两层数学模式，tectonic 直接报
    `! LaTeX Error: Bad math environment delimiter.`
    """
    before = s[:idx]
    if len(re.findall(r"(?<!\\)\$", before)) % 2 == 1:
        return True
    if before.count(r"\[") > before.count(r"\]"):
        return True
    return before.count(r"\(") > before.count(r"\)")


def _wrap_math_envs(s: str) -> str:
    r"""正文用：只给**裸**数学环境补 `\[ \]` 行间公式壳；已在数学模式内的原样保留。"""
    out, pos = [], 0
    for m in _ENV_RE.finditer(s):
        out.append(s[pos:m.start()])
        out.append(m.group(0) if _math_mode_at(s, m.start())
                   else "\\[" + m.group(0) + "\\]")
        pos = m.end()
    out.append(s[pos:])
    return "".join(out)


_ASCII_RUN_RE = re.compile(r"[\x20-\x7e]+")
_MATH_SIGNAL_RE = re.compile(r"[\^_\\]")


def _wrap_inline_math(s: str) -> str:
    r"""正文用：给**裸的行内数学**补 `$...$` 壳。

    题干来自真实作业，物理量常写成 `g = 9.8 m/s^2`、`v_0 = 20 m/s`、
    `\theta = 30^\circ` 这种**没有美元符**的形式；直接进 XeTeX 会触发
    `! Missing $ inserted.`（run11 实测，卡在 `.tex` 第 142 行）。

    规则：把 ASCII 连续段里**含 `^` / `_` / `\` 且不在数学模式内**的片段
    用 `$...$` 包起来；已被 `$...$` 包住的部分、显式 `\[ \]` / `\( \)`
    片段一律不动，避免嵌套数学模式。
    """
    out, pos = [], 0
    for m in _ASCII_RUN_RE.finditer(s):
        seg = m.group(0)
        if not _MATH_SIGNAL_RE.search(seg):
            continue
        if _math_mode_at(s, m.start()):
            continue
        if any(tok in seg for tok in (r"\[", r"\]", r"\(", r"\)")):
            continue
        rebuilt = []
        for i, part in enumerate(seg.split("$")):
            if i % 2 == 1 or not (_MATH_SIGNAL_RE.search(part) and part.strip()):
                rebuilt.append(part)          # 原就在 $...$ 里 / 不含信号 → 不动
            else:
                lead = len(part) - len(part.lstrip())
                trail = len(part) - len(part.rstrip())
                rebuilt.append(" " * lead + "$" + part.strip() + "$" + " " * trail)
        out.append(s[pos:m.start()])
        out.append("$".join(rebuilt))
        pos = m.end()
    out.append(s[pos:])
    return "".join(out)


def _prep_stem(s: str) -> str:
    r"""题干总入口：先给裸数学环境补 `\[ \]`，再给裸行内数学补 `$...$`。"""
    return _wrap_inline_math(_wrap_math_envs(s))


def _flatten_math_envs(s: str) -> str:
    r"""表格单元格用：压成行内公式（`\\` 变分号、`&` 变逗号）；已在数学模式内的不再补美元符。"""
    out, pos = [], 0
    for m in _ENV_RE.finditer(s):
        out.append(s[pos:m.start()])
        inner = " ".join(m.group(2).replace(r"\\", "; ").replace("&", ", ").split())
        out.append(inner if _math_mode_at(s, m.start()) else "$" + inner + "$")
        pos = m.end()
    out.append(s[pos:])
    return "".join(out)


def _short(s: str, n: int = 70) -> str:
    s = " ".join(s.split())
    if len(s) <= n:
        return s
    cut = s[:n - 1]
    if cut.count("$") % 2:      # 截断点落在行内公式里 → 退到公式起点之前
        cut = cut[:cut.rfind("$")]
    return cut + "…"


def render(problems, meta: dict, out_stem: Path,
           font: str = FONT_STACK[0]) -> dict:
    tex = [PREAMBLE % {"font": font}, r"\begin{document}",
           _frontmatter(meta), r"\section*{一、题目与解答}", ""]
    for p in problems:
        tex.append(r"\subsection*{题 %s}" % p["id"])
        tex.append(r"\noindent\textbf{题目.}\quad " + _tex_escape_plain(
            _prep_stem(p.get("stem") or p.get("raw", ""))) + r"\par")
        sol = p.get("solution")
        if not sol:
            tex.append(r"\begin{aibox}{未纳入解答}本机确定性求解模板未覆盖该题"
                       r"（已尝试本地模型规范化兜底）；按「不编造答案」原则"
                       r"留空并如实登记。\end{aibox}")
            tex.append("")
            continue
        tex.append(r"\vspace{4pt}\noindent\textbf{解答.}\quad")
        tex.append(r"\begin{enumerate}[leftmargin=1.6em,itemsep=2pt]")
        for s in sol["steps"]:
            tex.append(r"  \item " + _wrap_inline_math(s))
        tex.append(r"\end{enumerate}")
        tex.append(r"\[ \boxed{%s} \]" % sol["answer_latex"])
        tex.append(r"\noindent{\small 方法：%s}\par" % _esc_plain(sol["method"]))
        if p.get("verified"):
            mark, env = r"\okmark", "veribox"
        else:
            mark, env = r"\warnmark", "aibox"
        detail = r"\\".join(
            "%s：%s" % (_esc_plain(r["check"]), _esc_plain(str(r["detail"])))
            for r in p.get("verify_results", []))
        tex.append(r"\begin{%s}{独立核验 %s}%s\end{%s}"
                   % (env, mark, detail or "—", env))
        if p.get("ai_explain"):
            tex.append(r"\begin{aibox}{AI 讲解（本地 qwen3:8b，仅讲解不产数值）}"
                       r"%s\end{aibox}" % _esc_plain(p["ai_explain"]))
        tex.append(r"\vspace{10pt}")
    tex += [r"\section*{二、核验汇总}", _summary_table(problems)]
    tex += [r"\vspace{6pt}", r"\noindent{\small %s}\par" % _esc_plain(
        meta.get("footer", "")), r"\end{document}"]
    src = "\n".join(tex)
    out_stem.parent.mkdir(parents=True, exist_ok=True)
    (out_stem.with_suffix(".tex")).write_text(src, encoding="utf-8")
    (out_stem.with_suffix(".md")).write_text(markdown(problems, meta),
                                             encoding="utf-8")
    return {"tex": str(out_stem.with_suffix(".tex")),
            "md": str(out_stem.with_suffix(".md")),
            "chars": len(src)}


def _esc_plain(s: str) -> str:
    """对「方法说明/核验详情」这类**纯文本**中的 LaTeX 敏感符做保护。"""
    out = []
    for ch in s:
        if ch in "#$%&_":
            out.append("\\" + ch)
        elif ch == "~":
            out.append(r"\textasciitilde{}")
        elif ch == "^":
            out.append(r"\textasciicircum{}")
        else:
            out.append(ch)
    return "".join(out).replace(r"\textbackslash", r"\textbackslash{}")


def markdown(problems, meta: dict) -> str:
    md = [f"# {meta['title']}", ""]
    for k, v in meta.get("fields", {}).items():
        md.append(f"- **{k}**：{v}")
    md += ["", "---", "", "## 一、题目与解答", ""]
    for p in problems:
        md.append(f"### 题 {p['id']}")
        md.append("")
        md.append(("**题目.** " + (p.get("stem") or p.get("raw", ""))).strip())
        md.append("")
        sol = p.get("solution")
        if not sol:
            md += ["> 未纳入解答：本机确定性求解模板未覆盖该题（已尝试本地模型"
                   "规范化兜底）；按「不编造答案」原则留空并如实登记。", ""]
            continue
        md.append("**解答.**")
        md.append("")
        for i, s in enumerate(sol["steps"], 1):
            md.append(f"{i}. {s}")
        md += ["", f"**答案：**`{sol['answer_latex']}`", "",
               f"- 方法：{sol['method']}",
               f"- 独立核验：{'✅ 通过' if p.get('verified') else '⚠️ 未通过'}"]
        for r in p.get("verify_results", []):
            md.append(f"  - `{r['check']}` {r['status']} — {r['detail']}")
        if p.get("ai_explain"):
            md += ["", f"> **AI 讲解**（本地 qwen3:8b，仅讲解不产数值）："
                       f"{p['ai_explain']}"]
        md += ["", "---", ""]
    md += ["## 二、核验汇总", "",
           "| # | 题目 | 答案 | 核验 |", "|---|---|---|---|"]
    for p in problems:
        ans = p["solution"]["answer_latex"] if p.get("solution") else "—"
        badge = "✅" if p.get("verified") else ("⚠️" if p.get("solution")
                                                else "超出范围")
        md.append(f"| {p['id']} | {_short(p.get('stem') or p.get('raw', ''))} "
                  f"| `{ans}` | {badge} |")
    md += ["", meta.get("footer", "")]
    return "\n".join(md)
