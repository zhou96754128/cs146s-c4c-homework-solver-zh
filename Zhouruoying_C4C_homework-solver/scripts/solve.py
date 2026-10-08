"""阶段 ④：求解调度。

职责：按路由结果把题目交给对应求解器组；规则没覆盖到的题目走
「模型规范化 → 再求解」的兜底通道；最后批量生成 AI 讲解。

留痕：每道题都会带上 `llm` 字段，记录模型**被用在哪一步、采纳还是驳回**，
这是 AI 日志的证据来源（不是事后回忆）。

编号容错：题目编号既可能是 `1` 这样的纯数字，也可能是 `P01` 这样的字符串。
模型回填编号时经常自行改写（`P01` ↔ `P01` ↔ `1` ↔ `01`），因此这里统一走
`_resolve_id` 做「原样 → 小写 → 末尾数字归一」三级匹配，绝不直接 `int(id)`。
"""
from __future__ import annotations

import importlib
import re

DOMAIN_MODULES = {
    "linear_algebra": ["solvers_algebra"],
    "ode": ["solvers_ode"],
    "physics": ["solvers_physics"],
}
ALL_MODULES = ["solvers_algebra", "solvers_ode", "solvers_physics"]


def _load(names):
    return [importlib.import_module(n) for n in names]


def _try(modules, problem):
    for mod in modules:
        fn = getattr(mod, "try_solve", None)
        if fn is not None:
            got = fn(problem)
            if got:
                return got, mod.__name__
            continue
        for f in getattr(mod, "ORDER", []):
            got = f(problem)
            if got:
                return got, mod.__name__
    return None, None


# ---------------------------------------------------------------- 编号解析
def _digits(value):
    """取字符串末尾的数字并去掉前导零：'P01'->'1'、'01'->'1'、'13'->'13'。"""
    m = re.search(r"(\d+)\s*$", str(value).strip())
    if not m:
        return None
    return str(int(m.group(1)))


def _id_index(problems):
    """建立「可接受的编号写法 -> 规范编号」映射。"""
    idx = {}
    for p in problems:
        pid = str(p["id"])
        idx.setdefault(pid, pid)
        idx.setdefault(pid.lower(), pid)
        d = _digits(pid)
        if d is not None:
            idx.setdefault(d, pid)
    return idx


def _resolve_id(raw, idx):
    """把模型返回的编号还原为规范编号；无法匹配时返回 None（不猜）。"""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s in idx:
        return idx[s]
    if s.lower() in idx:
        return idx[s.lower()]
    d = _digits(s)
    if d is not None and d in idx:
        return idx[d]
    return None


EXPLAIN_PROMPT = """你是一位大学助教。请为下列每道题写**一句话**中文解题要点（不超过 40 字），
只讲思路与依据，不要重复数值答案，不要输出公式推导。严格只输出 JSON 数组。

题目清单（每行开头是该题编号）：
{items}

输出格式（务必严格遵守）：
[{{"id": "<题目编号，原样照抄清单里的编号>", "point": "……"}}]
"""

ROUTE_PROMPT = """下面每道题需要判断学科域，可选值为：linear_algebra（线性代数）、
ode（常微分方程）、physics（大学物理）。严格只输出 JSON 数组。

题目（每行开头是该题编号）：
{items}

输出格式（务必严格遵守）：
[{{"id": "<题目编号，原样照抄清单里的编号>", "domain": "linear_algebra"}}]
"""


def solve_all(problems, use_llm=True, llm=None, logger=None):
    """就地填充 problem["solution"] / problem["verified"] / problem["llm"]。"""
    stats = {"solved": 0, "unsolved": 0, "llm_calls": 0,
             "llm_route_review": 0, "llm_fallback": 0, "llm_explain": 0,
             "llm_adopted": 0, "llm_rejected": 0,
             "llm_unmatched_id": 0, "llm_explained": 0}

    def log(msg):
        if logger:
            logger(msg)

    # ---- 4a 路由复核：只有规则不确定的题才问模型
    need = [p for p in problems if p.get("needs_llm")]
    if need and use_llm and llm is not None:
        items = "\n".join(f'{p["id"]}. {p["raw"][:200]}' for p in need)
        res = llm.generate(ROUTE_PROMPT.format(items=items))
        stats["llm_calls"] += 1
        got = llm.extract_json(res["text"]) or []
        idx = _id_index(need)
        back = {}
        for d in got:
            if isinstance(d, dict) and "id" in d:
                key = _resolve_id(d["id"], idx)
                if key is None:
                    stats["llm_unmatched_id"] += 1
                    continue
                back[key] = d.get("domain")
        for p in need:
            new = back.get(str(p["id"]))
            if new in DOMAIN_MODULES:
                stats["llm_route_review"] += 1
                p["llm"] = {"stage": "route_review", "asked": p["domain"],
                            "model_said": new, "decision":
                            "adopt" if new != p["domain"] else "confirm"}
                if new != p["domain"]:
                    # 规则分与规则**不一致**时采纳模型（模型看全文，规则只看词表）
                    log(f'  路由复核：题 {p["id"]} 规则={p["domain"]} '
                        f'模型={new} → 采纳模型')
                    p["domain"] = new
                    p["route_source"] = "llm_review"
            else:
                p["llm"] = {"stage": "route_review", "asked": p["domain"],
                            "model_said": new, "decision": "reject",
                            "why": "模型返回非法域或无法解析，保留规则结果"}
        stats["llm_rejected"] += sum(
            1 for p in need if p.get("llm", {}).get("decision") == "reject")
        stats["llm_adopted"] += sum(
            1 for p in need if p.get("llm", {}).get("decision") == "adopt")
    elif need:
        for p in need:
            p["llm"] = {"stage": "route_review", "decision": "skipped",
                        "why": "本地模型不可用或 --no-llm"}

    # ---- 4b 求解
    for p in problems:
        mods = _load(DOMAIN_MODULES.get(p.get("domain"), [])) + \
            _load([m for m in ALL_MODULES
                   if m not in DOMAIN_MODULES.get(p.get("domain"), [])])
        sol, where = _try(mods, p)
        if sol is not None:
            stats["solved"] += 1
            p["solution"] = sol
            p["solver_module"] = where
        else:
            p["solution"] = None
            p["solver_module"] = None
            stats["unsolved"] += 1

    # ---- 4c 未解题的模型兜底（规范化后重试）
    retry = [p for p in problems if p["solution"] is None]
    if retry and use_llm and llm is not None:
        for p in retry:
            prompt = ("请把下面这道题**原样精炼**为一段 LaTeX 文本（不要解答，"
                      "不要输出解释，只输出题目本身）：\n\n" + p["raw"][:600])
            res = llm.generate(prompt)
            stats["llm_calls"] += 1
            cand = (res["text"] or "").strip()
            ok = False
            if cand and len(cand) > 5:
                probe = dict(p)
                probe["raw"] = cand
                sol, where = _try(_load(ALL_MODULES), probe)
                if sol is not None:
                    p["solution"] = sol
                    p["solver_module"] = where + "（经模型规范化）"
                    ok = True
            stats["llm_fallback"] += 1
            stats["llm_adopted" if ok else "llm_rejected"] += 1
            p["llm"] = {"stage": "normalize_fallback",
                        "decision": "adopt" if ok else "reject",
                        "why": "模型规范化后符号引擎解得" if ok
                        else "模型规范化后仍无法确定性求解，标记为超出模板范围",
                        "raw_excerpt": cand[:300],
                        "meta": res["meta"]}
            if ok:
                stats["solved"] += 1
                stats["unsolved"] -= 1
            log(f'  兜底：题 {p["id"]} '
                f'{"成功" if ok else "仍失败（保留未解，不编造答案）"}')

    # ---- 4d 批量生成 AI 讲解
    done = [p for p in problems if p["solution"]]
    if done and use_llm and llm is not None:
        items = "\n".join(
            f'{p["id"]}. {p["raw"][:160]} 【我们的答案：'
            f'{p["solution"]["answer_latex"][:80]}】' for p in done)
        res = llm.generate(EXPLAIN_PROMPT.format(items=items))
        stats["llm_calls"] += 1
        stats["llm_explain"] = 1
        arr = llm.extract_json(res["text"]) or []
        idx = _id_index(done)
        back = {}
        for d in arr:
            if isinstance(d, dict) and "id" in d:
                key = _resolve_id(d["id"], idx)
                if key is None:
                    stats["llm_unmatched_id"] += 1
                    continue
                back[key] = str(d.get("point", ""))[:120]
        hit = 0
        for p in done:
            pt = back.get(str(p["id"]), "").strip()
            p["ai_explain"] = pt
            if pt:
                hit += 1
            prev = p.get("llm") or {}
            if prev:
                prev["explain_ok"] = bool(pt)
                prev["meta"] = res["meta"]
                p["llm"] = prev
            else:
                # 本题的讲解来自「一次批量调用」，meta 是批次级的真实遥测
                # （model / prompt_sha256 / prompt_chars / latency_s / ok），
                # 下沉到每题，保证台账逐题可追溯。
                p["llm"] = {"stage": "explain_only",
                            "decision": "adopt" if pt else "reject",
                            "explain_ok": bool(pt),
                            "meta": res["meta"],
                            "batch": True}
        p["_explain_batch_meta"] = res["meta"]
        stats["llm_explained"] = hit
        log(f"  讲解生成：{hit}/{len(done)} 题拿到模型讲解"
            f"（编号未匹配 {stats['llm_unmatched_id']} 条）")
    else:
        for p in problems:
            p.setdefault("ai_explain", "")

    stats["llm_explained"] = sum(1 for p in problems if p.get("ai_explain"))
    return stats
