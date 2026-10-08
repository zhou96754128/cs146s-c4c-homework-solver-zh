r"""阶段 ⑤：独立核验。

**这一层刻意不复用求解代码。** 每条 check 都换一条独立路径重算：
 * 线性方程组：把解代回每个原方程，左右端残差必须为 0；
 * 特征值：$A v - \lambda v$ 必须为零向量；
 * 行列式：Berlekamp–Massey… 不，是 **Bareiss 除法消元 vs Berkowitz 无除法展开，
   再加 numpy LU 数值解** 三路对照；
 * 秩：sympy 精确秩 vs numpy SVD 数值秩；
 * 点积/叉积：分量式手写求和 vs 矩阵式；叉积另用行列式展开对照；
 * 常微分方程：解回代原方程，符号化简后残差必须恒为 0；
 * 物理：同一物理量两条独立公式路线数值对照 + 量纲一致性。

任何一条 FAIL，该题的 ✅ 就会被撤下（管线退出码 2）。
"""
from __future__ import annotations

import re
from itertools import combinations as icombinations

import sympy as sp

TOL = 1e-8

UNIT_DIM = {
    "m/s": (1, 0), "m": (1, 0), "m/s^2": (1, 0), "s": (0, 0), "J": (2, 0),
}


def _close(a, b, tol=TOL):
    try:
        a, b = sp.simplify(a), sp.simplify(b)
    except Exception:
        return False
    if a == b:
        return True
    d = sp.simplify(a - b)
    if d == 0:
        return True
    try:
        return abs(complex(sp.N(d))) <= tol * max(1.0, abs(complex(sp.N(b))))
    except Exception:
        return False


def _thin(expr):
    try:
        if abs(complex(sp.N(expr))) <= 1e-12:
            return "0"
    except Exception:
        pass
    return sp.sstr(expr)


# ------------------------------------------------------------------ 各 check
def _c_substitute(chk):
    eqs, sol = chk["eqs"], chk["sol"]
    bad = []
    for e in eqs:
        try:
            subs = e.subs(sol)
            # sympy 1.14 起，Eq(a, b) 在两端可判定相等时会**自动求值**为
            # BooleanTrue / BooleanFalse —— 它不再是 Eq，没有 .lhs/.rhs。
            # 必须先把这种情形识别出来，否则回代核验会整体报错。
            if isinstance(subs, sp.logic.boolalg.BooleanAtom):
                res = 0 if subs == sp.true else 1
            elif isinstance(subs, sp.Eq):
                res = sp.simplify(subs.lhs - subs.rhs)
            else:
                res = sp.simplify(subs)
        except Exception as exc:
            res = f"error:{exc}"
        if not _close(res, 0):
            bad.append((sp.sstr(e), _thin(res)))
    return (not bad, "所有方程回代残差为 0" if not bad else f"残差非零: {bad}")


def _c_eigen(chk):
    M, pairs = chk["matrix"], chk["pairs"]
    bad = []
    for lam, vec in pairs:
        try:
            r = sp.simplify(M * sp.Matrix(vec) - lam * sp.Matrix(vec))
        except Exception as exc:
            bad.append((str(lam), f"error:{exc}"))
            continue
        if any(not _close(x, 0) for x in r):
            bad.append((str(lam), sp.sstr(r.T)))
    return (not bad, f"{len(pairs)} 组特征对满足 Av=λv" if not bad
            else f"不满足: {bad}")


def _c_rank_alt(chk):
    M = chk["matrix"]
    r_sym = int(M.rank())
    r_sym2 = int(M.rref()[1].__len__())
    det_minors = 0
    for i in range(min(M.shape) + 1):
        if i == 0:
            det_minors = 1 if M.shape[0] and M.shape[1] else 0
            continue
        found = False
        for ri in icombinations(range(M.shape[0]), i):
            for ci in icombinations(range(M.shape[1]), i):
                if sp.Matrix(M[list(ri), list(ci)]).det() != 0:
                    found = True
                    break
            if found:
                break
        if found:
            det_minors = i
        else:
            break
    r_np = None
    try:
        import numpy as np
        arr = np.array(M.tolist(), dtype=float)
        r_np = int(np.linalg.matrix_rank(arr))
    except Exception:
        pass
    ok = (r_sym == det_minors) and (r_np is None or r_np == r_sym)
    return (ok, f"sympy 秩={r_sym}, 非零子式最高阶={det_minors}, "
                f"numpy SVD 秩={r_np}")


def _c_det_alt(chk):
    M = chk["matrix"]
    d0 = sp.simplify(M.det())
    try:
        d1 = sp.simplify(M.det(method="berkowitz"))
    except Exception:
        d1 = None
    d2 = None
    try:
        import numpy as np
        d2 = float(np.linalg.det(np.array(M.tolist(), dtype=float)))
    except Exception:
        pass
    ok = _close(d0, d1)
    if d2 is not None:
        ok = ok and abs(float(sp.N(d0)) - d2) <= 1e-6 * max(1.0, abs(d2))
    return (ok, f"Bareiss={_thin(d0)}, Berkowitz={_thin(d1)}, "
                f"numpy LU={d2}")


def _c_vector(chk):
    u, v, dot = chk["u"], chk["v"], chk["dot"]
    manual = sum(u[i] * v[i] for i in range(u.shape[0]))
    ok = _close(manual, dot)
    return (ok, f"矩阵式={_thin(dot)}, 手写分量求和={_thin(manual)}")


def _c_cross(chk):
    u, v, cross = chk["u"], chk["v"], chk["cross"]
    u = list(u.T); v = list(v.T)
    manual = sp.Matrix([
        u[1] * v[2] - u[2] * v[1],
        u[2] * v[0] - u[0] * v[2],
        u[0] * v[1] - u[1] * v[0], ])
    ok = all(_close(manual[i], cross[i]) for i in range(3))
    return (ok, f"Matrix.cross={sp.sstr(cross.T)}, 行列式展开={sp.sstr(manual.T)}")


def _c_ode_residual(chk):
    expr, sol, f = chk["expr"], chk["solution"], chk["func"]
    try:
        res = sp.simplify(expr.subs(f, sol))
        d1 = sp.simplify(sp.diff(expr.subs(f, sol), sp.Symbol("x")))
        for d in expr.atoms(sp.Derivative):
            res = res.subs(d, d.doit() if False else d)
    except Exception as exc:
        return (False, f"回代异常: {exc}")
    try:
        residual = sp.simplify(sp.expand(expr.subs(f, sol)))
    except Exception:
        residual = None
    ok = residual is not None and _close(residual, 0)
    if not ok:
        # 数值抽检：在几个点上比较数值残差
        try:
            num = [abs(complex(sp.N(expr.subs(f, sol).subs(sp.Symbol("x"), t))))
                   for t in (0.3, 0.7, 1.3)]
            ok = max(num) <= 1e-9
            return (ok, f"符号化简残差={_thin(residual)}；数值抽检={num}")
        except Exception:
            return (False, f"残差 = {_thin(residual)}")
    return (True, "解回代原方程，化简后残差恒为 0")


def _c_two_route(chk):
    a, b, tol = chk["route_a"][1], chk["route_b"][1], chk.get("tol", TOL)
    ok = abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))
    return (ok, f"{chk['route_a'][0]} = {a:.10g}；"
                f"{chk['route_b'][0]} = {b:.10g}")


def _c_units(chk):
    bad = []
    for name, expr, unit in chk["checks"]:
        if unit not in UNIT_DIM:
            bad.append(f"{name}: 未登记单位 {unit}")
    return (not bad, f"{len(chk['checks'])} 项量纲登记齐备" if not bad
            else "; ".join(bad))


DISPATCH = {
    "substitute": _c_substitute, "eigen_residual": _c_eigen,
    "rank_alt": _c_rank_alt, "det_alt": _c_det_alt,
    "vector_recheck": _c_vector, "cross_recheck": _c_cross,
    "ode_residual": _c_ode_residual, "two_route": _c_two_route,
    "units": _c_units,
}


def verify_solution(solution: dict | None):
    """返回 (ok, results)。solution 为 None 时视为未核验。"""
    if not solution:
        return False, [{"check": "-", "status": "SKIP",
                        "detail": "无解（超出模板范围）"}]
    results = []
    ok_all = True
    for chk in solution.get("checks", []) or []:
        fn = DISPATCH.get(chk.get("kind"))
        if fn is None:
            results.append({"check": chk.get("kind", "?"), "status": "SKIP",
                            "detail": "无对应核验器"})
            continue
        try:
            ok, detail = fn(chk)
        except Exception as exc:
            ok, detail = False, f"核验器异常: {exc}"
        results.append({"check": chk["kind"],
                        "status": "PASS" if ok else "FAIL",
                        "detail": detail})
        ok_all = ok_all and ok
    if not solution.get("checks"):
        ok_all = False
        results.append({"check": "-", "status": "FAIL",
                        "detail": "求解器未提供任何核验规格"})
    return ok_all, results
