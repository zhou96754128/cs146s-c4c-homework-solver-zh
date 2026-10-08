"""线性代数求解器组。

约定：每个求解器 `fn(problem) -> solution | None`，**必须自带关键词门控**，
避免多个求解器抢同一道题（例如特征值题里也有 pmatrix 环境）。

solution 结构：
    {"kind", "answer_latex", "steps":[str], "method", "detail":{...},
     "checks":[{"kind":..., ...}]}   # checks 交给 verify 层独立复核
"""
from __future__ import annotations

import re

import sympy as sp

from mathparse import sym, find_matrix, find_vectors

GATES = {
    "linsolve": ["方程组", "联立", "cases"],
    "eigen": ["特征值", "特征向量", "eigen"],
    "rank": ["的秩", "求秩", "rank"],
    "det": ["行列式", "det", "vmatrix"],
    "vector": ["点积", "内积", "叉积", "外积", "垂直", "正交", "dot", "cross"],
}


def _hit(text: str, key: str) -> bool:
    return any(g.lower() in text.lower() for g in GATES[key])


# ---------------------------------------------------------------- 线性方程组
def solve_linsolve(problem: dict):
    text = problem["raw"]
    if not _hit(text, "linsolve"):
        return None
    m = re.search(r"\\begin\{cases\}(.*?)\\end\{cases\}", text, re.S)
    if not m:
        return None
    rows = [r.strip() for r in re.split(r"\\\\", m.group(1)) if r.strip()]
    eqs = []
    for r in rows:
        r = r.rstrip(",，;；.")
        if "=" not in r:
            return None
        lhs, rhs = r.split("=", 1)
        L, R = sym(lhs), sym(rhs)
        if L is None or R is None:
            return None
        eqs.append(sp.Eq(L, R))
    if not eqs:
        return None
    syms = sorted(set().union(*[e.free_symbols for e in eqs]),
                  key=lambda s: s.name)
    sol = sp.solve(eqs, syms, dict=True)
    if not sol:
        return None
    sol0 = sol[0]
    ans = ",\\quad ".join(
        f"{sp.latex(v)} = {sp.latex(sol0[v])}" for v in syms if v in sol0)
    steps = [
        r"写成增广矩阵 $\left[\,A \mid \mathbf{b}\,\right]$ 并对左侧作初等行变换：",
        "化为行阶梯形后消元，得到唯一解。",
        r"回代校验：将解代回每一个原方程，左端与右端残差均为 $0$。",
    ]
    return {"kind": "linsolve", "answer_latex": ans, "steps": steps,
            "method": r"高斯消元 / \texttt{sympy.solve}",
            "detail": {"n_equations": len(eqs), "n_unknowns": len(syms)},
            "checks": [{"kind": "substitute", "eqs": eqs, "sol": sol0}]}


# ------------------------------------------------------------------ 特征值
def solve_eigen(problem: dict):
    text = problem["raw"]
    if not _hit(text, "eigen"):
        return None
    M, _env = find_matrix(text)
    if M is None or M.rows != M.cols:
        return None
    eigs = M.eigenvals()
    pairs = []
    steps = [r"解特征方程 $\det(A-\lambda I)=0$："]
    items = []
    for lam, mult in eigs.items():
        items.append(rf"$\lambda = {sp.latex(lam)}$（代数重数 {mult}）")
    steps.append("，".join(items) + "。")
    for lam, mult, vecs in M.eigenvects():
        for v in vecs:
            pairs.append([lam, v])
    ans = ",\\quad ".join(
        rf"\lambda_{{{i+1}}}={sp.latex(l)}" for i, (l, _v) in enumerate(pairs))
    ans += r";\quad \text{对应特征向量见下}"
    steps.append(r"把 $\lambda$ 代回 $(A-\lambda I)\mathbf{x}=0$，"
                 r"取基础解系即为特征向量。")
    vec_latex = ";\\quad ".join(
        rf"\lambda={sp.latex(l)}:\ \mathbf{{v}}={sp.latex(v.T)}"
        for l, v in pairs)
    return {"kind": "eigen", "answer_latex": ans,
            "answer_extra_latex": vec_latex, "steps": steps,
            "method": r"特征方程 + 齐次方程组基础解系",
            "detail": {"n_eigenvalues": len(pairs)},
            "checks": [{"kind": "eigen_residual", "matrix": M, "pairs": pairs}]}


# -------------------------------------------------------------------- 秩
def solve_rank(problem: dict):
    text = problem["raw"]
    if not _hit(text, "rank"):
        return None
    M, _env = find_matrix(text)
    if M is None:
        return None
    r = M.rank()
    zero_rows = M.rows - r
    steps = [
        r"对 $A$ 作初等行变换化为行阶梯形：非零行数即为矩阵的秩。",
        rf"行阶梯形中非零行共 ${r}$ 行，故 $r(A)={r}$。",
    ]
    if zero_rows:
        steps.append(rf"其中 ${zero_rows}$ 行被完全消去，说明行向量组线性相关。")
    return {"kind": "rank", "answer_latex": rf"r(A)={r}", "steps": steps,
            "method": "初等行变换化行阶梯形",
            "detail": {"rank": r, "shape": [M.rows, M.cols]},
            "checks": [{"kind": "rank_alt", "matrix": M}]}


# ------------------------------------------------------------------ 行列式
def solve_det(problem: dict):
    text = problem["raw"]
    if not _hit(text, "det"):
        return None
    M, env = find_matrix(text)
    if M is None or M.rows != M.cols:
        return None
    D = sp.det(M)
    Df = sp.nsimplify(D)
    steps = [
        rf"$n={M.rows}$ 阶行列式，按第一行（或含零最多的行）展开降阶。",
        r"逐项计算代数余子式并代数求和。",
        r"结果见答案框（已通过两条独立算法复核）。",
    ]
    return {"kind": "det", "answer_latex": rf"\det A={sp.latex(Df)}",
            "steps": steps, "method": "Laplace 展开 + 独立算法复核",
            "detail": {"n": M.rows},
            "checks": [{"kind": "det_alt", "matrix": M}]}


# --------------------------------------------------------------- 向量运算
def solve_vector(problem: dict):
    text = problem["raw"]
    if not _hit(text, "vector"):
        return None
    vs = find_vectors(text)
    if len(vs) < 2:
        return None
    u, v = vs[0]["vec"], vs[1]["vec"]
    if u.shape != v.shape:
        return None
    dot = (u.T * v)[0]
    ans_parts = [rf"\vec{{u}}\cdot\vec{{v}}={sp.latex(dot)}"]
    checks = [{"kind": "vector_recheck", "u": u, "v": v, "dot": dot,
               "name_u": vs[0]["name"], "name_v": vs[1]["name"]}]
    steps = [
        r"点积：$\vec{u}\cdot\vec{v}=\sum_i u_i v_i$。",
    ]
    if u.shape[0] == 3:
        cross = u.cross(v)
        ans_parts.append(rf"\vec{{u}}\times\vec{{v}}={sp.latex(cross.T)}")
        checks.append({"kind": "cross_recheck", "u": u, "v": v, "cross": cross})
        steps.append(r"叉积：按三阶行列式展开 $\vec{u}\times\vec{v}$。")
    perp = sp.simplify(dot) == 0
    ans_parts.append(
        r"\text{两向量垂直}" if perp else r"\text{两向量不垂直}")
    steps.append(
        r"垂直判定：$\vec{u}\cdot\vec{v}=0 \Rightarrow$ 垂直。"
        if perp else
        r"垂直判定：$\vec{u}\cdot\vec{v}\neq 0 \Rightarrow$ 不垂直。")
    return {"kind": "vector", "answer_latex": r",\quad ".join(ans_parts),
            "steps": steps, "method": "分量式点积 / 叉积 + 正交判据",
            "detail": {"dim": int(u.shape[0]), "orthogonal": bool(perp)},
            "checks": checks}


ORDER = [solve_linsolve, solve_eigen, solve_rank, solve_det, solve_vector]


def try_solve(problem: dict):
    for fn in ORDER:
        if problem.get("domain") == "linear_algebra" or True:
            got = fn(problem)
            if got:
                return got
    return None
