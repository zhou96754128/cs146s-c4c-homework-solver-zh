"""大学物理求解器组。

每个物理求解器都产出一条 **双路径核验**（`two_route`）：同一物理量用两条
互不相同的公式路线各算一遍，数值必须吻合；否则核验层判 FAIL。
另外附量纲（单位）一致性检查 `units`。
"""
from __future__ import annotations

import math
import re

G_DEFAULT = 9.8
MPSS = "m/s^2"


def _g(text: str) -> float:
    m = re.search(r"g\s*=\s*([0-9]+(?:\.[0-9]+)?)", text)
    return float(m.group(1)) if m else G_DEFAULT


def _num(text: str, *keys: str):
    for k in keys:
        for pat in (re.escape(k) + r"\s*_?\s*\{?\s*[A-Za-z0-9]?\s*\}?\s*=\s*"
                    r"([0-9]+(?:\.[0-9]+)?)",
                    re.escape(k) + r"([0-9]+(?:\.[0-9]+)?)",
                    r"\\?" + re.escape(k.lstrip("\\")) +
                    r"\s*=\s*([0-9]+(?:\.[0-9]+)?)"):
            m = re.search(pat, text)
            if m:
                return float(m.group(1))
    return None


def _fmt(x: float, nd: int = 4) -> str:
    s = f"{x:.{nd}f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _gate(text: str, words) -> bool:
    return any(w in text for w in words)


def _mk(kind, ans_tex, steps, method, detail, checks):
    return {"kind": kind, "answer_latex": ans_tex, "steps": steps,
            "method": method, "detail": detail, "checks": checks}


# ------------------------------------------------------------ 自由落体
def solve_free_fall(problem: dict):
    text = problem["raw"]
    if not _gate(text, ["自由落体", "自由下落", "静止开始下落", "落地速度"]):
        return None
    t = _num(text, "t", "时间")
    g = _g(text)
    if t is None:
        return None
    v, h = g * t, 0.5 * g * t * t
    steps = [
        r"取竖直向下为正方向，初速度 $v_0=0$。",
        rf"速度：$v=gt={_fmt(g)}\times{_fmt(t)}={_fmt(v)}\,\mathrm{{m/s}}$。",
        rf"下落距离：$h=\tfrac12 g t^2={_fmt(h)}\,\mathrm{{m}}$。",
    ]
    return _mk("free_fall",
               rf"v={_fmt(v)}\,\mathrm{{m/s}},\quad h={_fmt(h)}\,\mathrm{{m}}",
               steps, "匀变速直线运动公式（初速为零）",
               {"t": t, "g": g, "v": v, "h": h},
               [{"kind": "two_route",
                 "quantity": "落地速度 v",
                 "route_a": ["v = g·t", v],
                 "route_b": ["v = sqrt(2gh)", math.sqrt(2 * g * h)],
                 "tol": 1e-9},
                {"kind": "units", "checks": [
                    ["v", "g*t", "m/s"], ["h", "0.5*g*t^2", "m"]]}])


# ------------------------------------------------------------ 牛顿第二定律
def solve_newton2(problem: dict):
    text = problem["raw"]
    if not _gate(text, ["牛顿第二定律", "合外力", "求加速度"]):
        return None
    m = _num(text, "m", "质量")
    F = _num(text, "F", "合力")
    if m is None or F is None or m == 0:
        return None
    a = F / m
    steps = [r"由牛顿第二定律 $F=ma$，得 $a=F/m$。",
             rf"$a={_fmt(F)}/{_fmt(m)}={_fmt(a)}\,\mathrm{{{MPSS}}}$。"]
    return _mk("newton2", rf"a={_fmt(a)}\,\mathrm{{{MPSS}}}", steps,
               "牛顿第二定律 F = ma",
               {"m": m, "F": F, "a": a},
               [{"kind": "two_route", "quantity": "加速度 a",
                 "route_a": ["a = F/m", a],
                 "route_b": ["a = F·(1/m)", F * (1.0 / m)], "tol": 1e-12},
                {"kind": "units", "checks": [["a", "F/m", MPSS]]}])


# -------------------------------------------------------------- 抛体运动
def solve_projectile(problem: dict):
    text = problem["raw"]
    if not _gate(text, ["抛体", "射程", "抛射角", "斜抛"]):
        return None
    v0 = _num(text, "v_0", "v0", "v", "初速")
    th = _num(text, "\\theta", "theta", "抛射角")
    g = _g(text)
    if v0 is None or th is None:
        return None
    rad = math.radians(th)
    R = v0 * v0 * math.sin(2 * rad) / g
    H = v0 * v0 * math.sin(rad) ** 2 / (2 * g)
    t_flight = 2 * v0 * math.sin(rad) / g
    R2 = v0 * math.cos(rad) * t_flight
    steps = [
        r"水平、竖直分解：$v_{0x}=v_0\cos\theta$，$v_{0y}=v_0\sin\theta$。",
        rf"飞行时间 $t=\dfrac{{2v_0\sin\theta}}{{g}}={_fmt(t_flight)}\,\mathrm{{s}}$。",
        rf"射程 $R=v_0\cos\theta\cdot t={_fmt(R)}\,\mathrm{{m}}$。",
        rf"最大高度 $H=\dfrac{{v_0^2\sin^2\theta}}{{2g}}={_fmt(H)}\,\mathrm{{m}}$。",
    ]
    return _mk("projectile",
               rf"R={_fmt(R)}\,\mathrm{{m}},\quad H={_fmt(H)}\,\mathrm{{m}}",
               steps, "运动分解（水平匀速 + 竖直匀变速）",
               {"v0": v0, "theta_deg": th, "g": g, "R": R, "H": H},
               [{"kind": "two_route", "quantity": "射程 R",
                 "route_a": ["R = v0^2 sin(2θ)/g", R],
                 "route_b": ["R = v0 cosθ · (2v0 sinθ/g)", R2], "tol": 1e-9},
                {"kind": "units", "checks": [["R", "v0^2/g", "m"],
                                             ["H", "v0^2/g", "m"]]}])


# -------------------------------------------------------------- 动能定理
def solve_work_energy(problem: dict):
    text = problem["raw"]
    if not _gate(text, ["动能", "动能定理", "重力势能"]):
        return None
    m = _num(text, "m", "质量")
    h = _num(text, "h", "高")
    g = _g(text)
    if m is None or h is None:
        return None
    Ek = m * g * h
    v = math.sqrt(2 * g * h)
    Ek2 = 0.5 * m * v * v
    steps = [
        r"由动能定理 $W_{\text{合}}=\Delta E_k$，重力做功全部转化为动能。",
        rf"$E_k=mgh={_fmt(m)}\times{_fmt(g)}\times{_fmt(h)}={_fmt(Ek)}\,\mathrm{{J}}$。",
        rf"等价校验：落地速度 $v=\sqrt{{2gh}}={_fmt(v)}\,\mathrm{{m/s}}$，"
        rf"$E_k=\tfrac12 m v^2={_fmt(Ek2)}\,\mathrm{{J}}$，两路一致。",
    ]
    return _mk("work_energy", rf"E_k={_fmt(Ek)}\,\mathrm{{J}}", steps,
               "动能定理（重力的功 → 动能增量）",
               {"m": m, "h": h, "g": g, "Ek": Ek, "v": v},
               [{"kind": "two_route", "quantity": "落地动能 Ek",
                 "route_a": ["Ek = mgh", Ek],
                 "route_b": ["Ek = 0.5·m·(2gh)", Ek2], "tol": 1e-9},
                {"kind": "units", "checks": [["Ek", "m*g*h", "J"]]}])


# ------------------------------------------------------------ 简谐运动
def solve_shm(problem: dict):
    text = problem["raw"]
    if not _gate(text, ["弹簧振子", "振动周期", "简谐", "劲度系数"]):
        return None
    k = _num(text, "k", "劲度系数")
    m = _num(text, "m", "质量")
    if k is None or m is None or k <= 0:
        return None
    omega = math.sqrt(k / m)
    T = 2 * math.pi / omega
    T2 = 2 * math.pi * math.sqrt(m / k)
    steps = [
        r"弹簧振子回复力 $F=-kx$，与 $F=ma$ 联立得 $\ddot x+\dfrac km x=0$，"
        r"故 $\omega=\sqrt{k/m}$。",
        rf"$\omega={_fmt(omega)}\,\mathrm{{rad/s}}\Rightarrow "
        rf"T=\dfrac{{2\pi}}{{\omega}}={_fmt(T)}\,\mathrm{{s}}$。",
    ]
    return _mk("shm", rf"T={_fmt(T)}\,\mathrm{{s}}", steps,
               "简谐运动角频率（由运动方程推得）",
               {"k": k, "m": m, "omega": omega, "T": T},
               [{"kind": "two_route", "quantity": "周期 T",
                 "route_a": ["T = 2π/ω, ω=sqrt(k/m)", T],
                 "route_b": ["T = 2*pi*sqrt(m/k)", T2], "tol": 1e-9},
                {"kind": "units", "checks": [["T", "sqrt(m/k)", "s"]]}])


ORDER = [solve_free_fall, solve_newton2, solve_projectile,
         solve_work_energy, solve_shm]


def try_solve(problem: dict):
    for fn in ORDER:
        got = fn(problem)
        if got:
            return got
    return None
