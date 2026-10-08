"""LaTeX → sympy 的确定性解析公共层。

只做「文本规整 + 符号化」，不做语义猜测。所有歧义一律返回 None，
由上层决定是让本地大模型兜底还是标记为「超出模板范围」。
"""
from __future__ import annotations

import re

import sympy as sp

MAX_DEPTH = 3

_GREEK = {"\\alpha": "alpha", "\\beta": "beta", "\\gamma": "gamma",
          "\\theta": "theta", "\\lambda": "lambda", "\\mu": "mu",
          "\\omega": "omega", "\\varphi": "phi", "\\phi": "phi"}
_MATHLOCALS = {"pi": sp.pi, "E": sp.E, "exp": sp.exp, "sqrt": sp.sqrt,
               "sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "cot": sp.cot,
               "sec": sp.sec, "csc": sp.csc, "ln": sp.log, "log": sp.log,
               "abs": sp.Abs, "oo": sp.oo, "sinh": sp.sinh, "cosh": sp.cosh}


def strip_delims(t: str) -> str:
    t = t.strip()
    t = re.sub(r"^\$+|\$+$", "", t).strip()
    t = re.sub(r"^\\\(|\\\)$", "", t).strip()
    return t


def sym(txt: str, extra: dict | None = None):
    """把一段数学文本符号化；失败返回 None（不抛异常）。"""
    t = strip_delims(txt)
    # 只剥离定界/间距类控制序列；`\b` 是零宽断言，不可加 `?` 量词（会触发
    # re.error: nothing to repeat），因此这里用无边界版本的词法表。
    t = re.sub(r"\\(?:left|right|displaystyle|quad|qquad)(?![A-Za-z])", "", t)
    t = re.sub(r"\\[;,!\ ]|~", "", t)
    t = t.replace("\\cdot", "*").replace("\\times", "*").replace("\\div", "/")
    t = re.sub(r"\\dfrac|\\tfrac", r"\\frac", t)
    for _ in range(MAX_DEPTH):                      # 处理嵌套分数/根式
        new = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"((\1)/(\2))", t)
        new = re.sub(r"\\sqrt\[3\]\{([^{}]*)\}", r"((\1)**(1/3))", new)
        new = re.sub(r"\\sqrt\{([^{}]*)\}", r"sqrt(\1)", new)
        if new == t:
            break
        t = new
    t = re.sub(r"\\(?:mathrm|text|operatorname|mbox)\{([^{}]*)\}", r"\1", t)
    for k, v in _GREEK.items():
        t = t.replace(k, v)
    t = re.sub(r"\\(?:Delta|delta)\b", "Delta", t)
    t = t.replace("^", "**")
    t = t.replace("{", "(").replace("}", ")")
    t = t.replace("\\", "")
    t = re.sub(r"(?<![A-Za-z0-9_])e(?![A-Za-z0-9_])", "E", t)   # 自然常数
    t = re.sub(r"(?<=[0-9\)])(?=[A-Za-z(])", "*", t)             # 2x / 2(x)
    t = t.replace("Delta", "Symbol('Delta')")
    locals_map = dict(_MATHLOCALS)
    if extra:
        locals_map.update(extra)
    try:
        return sp.sympify(t, locals=locals_map)
    except Exception:
        return None


def find_matrix(text: str, envs=("vmatrix", "bmatrix", "pmatrix", "matrix")):
    for env in envs:
        m = re.search(r"\\begin\{" + env + r"\}(.*?)\\end\{" + env + r"\}",
                      text, re.S)
        if not m:
            continue
        data = parse_matrix_body(m.group(1))
        if data is not None:
            return sp.Matrix(data), env
    return None, None


def parse_matrix_body(body: str):
    rows = [r for r in re.split(r"\\\\(?:\[[^\]]*\])?", body) if r.strip()]
    data = []
    for r in rows:
        r = r.strip().strip("&").strip()
        cells = [c for c in re.split(r"(?<!\\)&|&", r)]
        vals = []
        for c in cells:
            v = sym(c)
            if v is None:
                return None
            vals.append(v)
        if vals:
            data.append(vals)
    if not data or len({len(r) for r in data}) != 1:
        return None
    return data


def find_vectors(text: str) -> list:
    """抽取 \\vec{u}=(1,2,3) 形式的向量。"""
    out = []
    for m in re.finditer(
            r"\\vec\s*\{?([A-Za-z])\}?\s*_?\s*\{?\s*([0-9]?)\s*\}?\s*=\s*"
            r"[(\（]\s*([^)\）]*)[)\）]", text):
        comps = [sym(c) for c in m.group(3).split(",")]
        if all(c is not None for c in comps) and comps:
            out.append({"name": m.group(1) + (m.group(2) or ""),
                        "vec": sp.Matrix(comps)})
    return out


def numbers_with_context(text: str, keys: list[str]) -> dict:
    """抽取 `键=数值`（允许 LaTeX 单位后缀），用于物理题参数识别。"""
    found = {}
    for key in keys:
        pat = (re.escape(key) + r"\s*_?\s*\{?\s*[A-Za-z0-9]?\s*\}?\s*=\s*"
               r"([0-9]+(?:\.[0-9]+)?(?:\s*[*/]\s*[0-9]+)?)")
        m = re.search(pat, text)
        if m:
            try:
                found[key] = float(sp.sympify(
                    m.group(1).replace("^", "**")))
            except Exception:
                continue
    return found


def tex_num(x) -> str:
    return sp.latex(x)
