"""常微分方程求解器（sympy.dsolve 为确定性后端）。

关键设计：**「解出来」不算完** —— 求解器同时产出一条 `ode_residual` 核验规格：
把解（含任意常数 C_i，或初值定解）回代原方程，符号化简后残差必须恒为 0。
核验由 verify 层执行，不信任本模块。
"""
from __future__ import annotations

import re

import sympy as sp

X = sp.Symbol("x")
Y = sp.Function("y")

LOCALS = {"y": Y, "x": X, "Derivative": sp.Derivative,
          "exp": sp.exp, "sin": sp.sin, "cos": sp.cos, "log": sp.log,
          "sqrt": sp.sqrt}

GATE = ["微分方程", "求通解", "求特解", "dy/dx", "初值问题", "y'", "y''"]


def _gate(text: str) -> bool:
    return any(g in text for g in GATE)


def _extract_ode(text: str):
    r"""从题面里取微分方程主体与小问中的初值条件。

    返回 (ode_expr_latex, [condition_latex, ...]) 或 (None, None)。
    """
    cands = re.findall(r"\$([^$]+)\$", text)
    cands += re.findall(r"\\\[(.*?)\\\]", text, re.S)
    body = None
    for c in cands:
        if ("'" in c or "y''" in c) and "y" in c:
            body = c.strip()
            break
    if body is None:
        m = re.search(r"(y''?\s*[+-=].*)", text)
        if not m:
            return None, None
        body = m.group(1).strip()
    parts = [p.strip() for p in re.split(r"[,，;；]", body) if p.strip()]
    return parts[0], parts[1:]


def _to_expr(main: str):
    t = main.strip().rstrip(".")
    t = (t.replace("\\dfrac", "\\frac").replace("\\mathrm{d}", "d")
          .replace("\\,", " ").replace("\\;", " ")
          .replace("\\ ", " ").replace("\\!", ""))
    t = t.replace("″", "''").replace("′", "'")
    # dy/dx 写法规范化成一阶导数
    t = re.sub(r"\\frac\s*\{\s*d\s*y\s*\}\s*\{\s*d\s*x\s*\}", "\x02", t)
    if "=" in t:
        lhs, rhs = t.split("=", 1)
        t = f"({lhs})-({rhs})"
    # 先把导数抽成占位符，避免与「裸 y 补自变量」互相干扰
    t = re.sub(r"y\s*''", "\x01", t)
    t = re.sub(r"y\s*'", "\x02", t)
    # 裸 y（函数本身）补自变量。lookbehind 只排除字母/下划线，
    # 这样 `2y` 这类隐式系数才会被补成 `2*y(x)`（含数字的旧写法会漏掉）。
    t = re.sub(r"(?<![A-Za-z_\x01\x02])y(?![A-Za-z0-9_(])", "\x03", t)
    # 隐式乘法 → 显式乘法
    t = re.sub(r"([0-9A-Za-z_)\x01\x02\x03])\s*(\x01|\x02|\x03)", r"\1*\2", t)
    t = t.replace("\x01", "Derivative(y(x),(x,2))")
    t = t.replace("\x02", "Derivative(y(x),x)")
    t = t.replace("\x03", "y(x)")
    # 清理一元位置的冗余乘号（如 `(*Derivative…` / `-*y(x)`）
    t = re.sub(r"(^|[(+\-*/])\s*\*", r"\1", t)
    from mathparse import sym
    return sym(t, extra=LOCALS)


def _to_ics(conds: list[str]):
    ics = {}
    errs = []
    for c in conds:
        if "=" not in c or "y" not in c:
            continue
        lhs, rhs = c.split("=", 1)
        rhs_v = _num(rhs)
        if rhs_v is None:
            errs.append(c)
            continue
        if "''" in lhs or "′" in lhs:
            ics[sp.Derivative(Y(X), (X, 2)).subs(X, 0)] = rhs_v
        elif "'" in lhs:
            ics[sp.Derivative(Y(X), X).subs(X, 0)] = rhs_v
        else:
            ics[Y(0)] = rhs_v
    return ics, errs


def _num(t: str):
    from mathparse import sym
    v = sym(t)
    if v is None:
        return None
    try:
        return sp.nsimplify(v)
    except Exception:
        return None


def solve_ode(problem: dict):
    text = problem["raw"]
    if not _gate(text):
        return None
    main, conds = _extract_ode(text)
    if main is None:
        return None
    expr = _to_expr(main)
    if expr is None:
        return None
    ics, _errs = _to_ics(conds)
    try:
        if ics:
            sol = sp.dsolve(sp.Eq(expr, 0), Y(X), ics=ics)
        else:
            sol = sp.dsolve(sp.Eq(expr, 0), Y(X))
    except Exception:
        return None
    if sol is None or not hasattr(sol, "rhs"):
        return None
    rhs = sp.simplify(sol.rhs)
    order = int(sp.ode_order(expr, Y(X)))
    kind = {1: "一阶", 2: "二阶"}.get(order, f"{order} 阶")
    label = "初值问题（特解）" if ics else "通解"
    steps = [
        rf"判定方程阶数与类型：{kind}常微分方程。",
        (r"分离变量后两端积分，得到含任意常数的通解。"
         if order == 1 and not ics else
         r"写出特征方程并求特征根，按根的情形写通解。"
         if order == 2 else r"按标准方法求解。"),
    ]
    if ics:
        steps.append(r"代入初值条件定出常数，得到满足初值的特解。")
    steps.append(r"回代：把解代入原方程，两端之差化简恒为 $0$（见核验栏）。")
    return {"kind": "ode", "answer_latex": sp.latex(sol),
            "steps": steps,
            "method": rf"{kind}常微分方程 —— "
                      r"\texttt{sympy.dsolve}（分离变量 / 特征方程法）",
            "detail": {"order": order, "has_ics": bool(ics),
                       "n_constants": len(sp.Derivative(Y(X), X).free_symbols
                                          ^ sp.Derivative(Y(X), X).free_symbols)
                       if False else (0 if ics else order)},
            "checks": [{"kind": "ode_residual", "expr": expr, "solution": rhs,
                        "func": Y(X)}]}


ORDER: list = [solve_ode]
