#!/usr/bin/env python3
"""C4C 作业自动求解与排版 —— 主管线（七阶段）。

    ingest -> parse -> classify -> solve -> verify -> render -> compile
      ①        ②         ③          ④        ⑤        ⑥        ⑦

设计分工（本技能的核心主张）：
  * **本地大模型**（ollama + qwen3:8b）负责「路由复核 / 题目规范化兜底 / 讲解生成」；
  * **确定性符号引擎**（sympy）负责「求解」，保证结果可复现；
  * **独立核验层**（verify）不信任前两者 —— 换一条算法路径回代/复算，
    只有核验通过的答案才标「已核验」，核验不通过的会撤下标记并让管线退出码为 2。

用法：
    python3 pipeline.py <input> <output_dir> [--compile] [--course NAME]
                        [--student NAME] [--title TITLE] [--verbose]
                        [--no-llm] [--log-dir DIR] [--json]

退出码：0 全部成功；2 存在未通过核验的题目；3 环境依赖缺失；4 编译失败。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "scripts"))
sys.path.insert(0, str(HERE))

from bootstrap import ensure_dependencies  # noqa: E402

import ingest  # noqa: E402
import parse_problems  # noqa: E402
import classify  # noqa: E402
import solve as solve_mod  # noqa: E402
import verify as verify_mod  # noqa: E402
import render_latex  # noqa: E402
import compile_pdf  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="C4C 作业自动求解与排版管线")
    p.add_argument("input", help="作业输入文件（.md/.txt/.tex/.pdf/.docx）")
    p.add_argument("output_dir", help="输出目录")
    p.add_argument("--compile", action="store_true", help="调用 LaTeX 编译 PDF")
    p.add_argument("--course", default="高等数学（跨学科扩展）", help="课程名")
    p.add_argument("--student", default="", help="学生姓名（用于文件名与页眉）")
    p.add_argument("--title", default="", help="作业标题覆盖")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--no-llm", action="store_true",
                   help="完全旁路本地大模型（讲解留空并标注未启用）")
    p.add_argument("--log-dir", default="", help="日志目录（默认 <output_dir>/logs）")
    p.add_argument("--json", action="store_true", help="把结构化结果打印到 stdout")
    p.add_argument("--font", default="", help="覆盖正文字体（默认 PingFang SC）")
    return p


def _jsonable(obj):
    """把 sympy 等非 JSON 原生对象递归降级为可序列化形式。

    `json.dumps(..., default=str)` 只作用于**值**；非字符串的**键**
    （例如 sympy.Symbol）仍会抛 `TypeError: keys must be str...`，
    所以键也必须显式转成 str。
    """
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(v) for v in obj]
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    return str(obj)


def _dump(path: Path, obj) -> None:
    path.write_text(json.dumps(_jsonable(obj), ensure_ascii=False, indent=2,
                               default=str),
                    encoding="utf-8")


def _load_llm(use_llm: bool, verbose: bool):
    """返回 (llm_module_or_None, status)。模型不可用时降级而不是崩。"""
    if not use_llm:
        return None, {"enabled": False, "reason": "--no-llm"}
    import llm_adapter
    try:
        if not llm_adapter.available():
            raise llm_adapter.LLMUnavailable("ollama 无响应或模型未拉取")
        t = llm_adapter.tags()
        models = [m.get("name", "") for m in t.get("models", [])] if isinstance(t, dict) else []
        if verbose:
            print(f"[pipeline] 本地模型可用：{models}")
        return llm_adapter, {"enabled": True, "host": llm_adapter.DEFAULT_HOST,
                             "model": llm_adapter.DEFAULT_MODEL,
                             "models": models}
    except Exception as exc:  # noqa: BLE001
        print(f"[pipeline] 本地模型不可用，降级为「无讲解」模式：{exc}",
              file=sys.stderr)
        return None, {"enabled": False, "reason": str(exc)}


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    t0 = time.time()
    out = Path(args.output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    log_dir = (Path(args.log_dir).expanduser().resolve()
               if args.log_dir else out / "logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    stage = "bootstrap"
    try:
        deps = ensure_dependencies(verbose=args.verbose)

        # ① ingest -------------------------------------------------------
        stage = "ingest"
        doc = ingest.ingest(args.input)
        _dump(log_dir / "01_ingest.json",
              {k: v for k, v in doc.items() if k != "lines"} | {"n_lines": doc["n_lines"]})

        # ② parse --------------------------------------------------------
        stage = "parse"
        problems = parse_problems.parse(doc)
        _dump(log_dir / "02_parsed.json", problems)
        if not problems:
            print("[pipeline] 未从输入中解析出任何题目", file=sys.stderr)
            return 2

        # ③ classify -----------------------------------------------------
        stage = "classify"
        problems = classify.classify(problems)
        _dump(log_dir / "03_classified.json",
              [{k: v for k, v in p.items() if k not in ("subitems",)}
               for p in problems])

        # ④ solve --------------------------------------------------------
        stage = "solve"
        llm, llm_status = _load_llm(not args.no_llm, args.verbose)
        # 注意：solve_all 是**就地**填充 problem[...] 的，返回的是统计字典；
        # 不能把返回值赋回 problems，否则后续迭代退化为遍历 dict 的键（str）。
        solve_stats = solve_mod.solve_all(
            problems, use_llm=llm is not None, llm=llm,
            logger=(print if args.verbose else None))
        _dump(log_dir / "04_solved.json",
              [{k: v for k, v in p.items() if k != "verify_results"}
               for p in problems])

        # ⑤ verify -------------------------------------------------------
        stage = "verify"
        for p in problems:
            ok, results = verify_mod.verify_solution(p.get("solution"))
            p["verified"] = bool(ok)
            p["verify_results"] = results
        vsummary = _verify_summary(problems)
        _dump(log_dir / "05_verified.json",
              [{k: v for k, v in p.items()} for p in problems])

        # ⑥ render -------------------------------------------------------
        stage = "render"
        meta = {
            "title": args.title or f"{args.course} 作业自动求解报告",
            "fields": {"课程": args.course,
                       "学生": args.student or "（未填写）",
                       "题数": str(len(problems)),
                       "核验通过": f"{vsummary['passed']}/{len(problems)}",
                       "生成时间": time.strftime("%Y-%m-%d %H:%M:%S")},
            "footer": ("本报告由 C4C 作业求解管线自动生成：解答来自确定性符号引擎，"
                       "核验由独立算法路径二次验算，二者分离；本地大模型仅参与"
                       "路由复核、题目规范化与讲解生成，不产出最终数值。"),
        }
        stem = out / (f"{args.student}_C4C_作业解答" if args.student
                      else "C4C_作业解答")
        r = render_latex.render(problems, meta, stem,
                                font=(args.font or render_latex.FONT_STACK[0]))
        tex_path = Path(r["tex"])

        # ⑦ compile ------------------------------------------------------
        pdf_path, cinfo = None, None
        if args.compile:
            stage = "compile"
            cinfo = compile_pdf.compile_pdf(tex_path, out_dir=out)
            pdf_path = cinfo.get("pdf")
            if not cinfo["ok"]:
                (log_dir / "07_compile_error.txt").write_text(
                    f"rc={cinfo['rc']}\nengine={cinfo.get('engine')}\n"
                    f"{cinfo.get('log', '')}\n{cinfo.get('tail', '')}",
                    encoding="utf-8")
                print(f"[pipeline] LaTeX 编译失败 rc={cinfo['rc']}，"
                      f"详见 {log_dir / '07_compile_error.txt'}", file=sys.stderr)

        summary = {
            "input": str(Path(args.input).resolve()),
            "input_sha256": doc.get("sha256"),
            "course": args.course,
            "student": args.student or None,
            "n_problems": len(problems),
            "n_solved": sum(1 for p in problems if p.get("solution")),
            "n_verified": vsummary["passed"],
            "n_failed_verify": vsummary["failed"],
            "domains": sorted({p.get("domain", "unknown") for p in problems}),
            "llm": llm_status,
            "llm_used_problems": [
                {"id": p["id"], "stage": (p.get("llm") or {}).get("stage"),
                 "decision": (p.get("llm") or {}).get("decision")}
                for p in problems if p.get("llm")],
            "explained": sum(1 for p in problems if p.get("ai_explain")),
            "verify": vsummary,
            "tex": r["tex"], "md": r["md"], "pdf": pdf_path,
            "compile": cinfo,
            "elapsed_sec": round(time.time() - t0, 2),
            "deps": deps,
        }
        _dump(log_dir / "summary.json", summary)

        print(f"[pipeline] 题目 {len(problems)} 道 | 已解 "
              f"{summary['n_solved']} | 核验通过 {vsummary['passed']} | "
              f"未通过 {vsummary['failed']} | 用时 {summary['elapsed_sec']}s")
        print(f"[pipeline] LaTeX -> {r['tex']}")
        if pdf_path:
            print(f"[pipeline] PDF   -> {pdf_path}")
        if args.json:
            print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        if vsummary["failed"]:
            return 2
        return 0 if (not args.compile or (cinfo and cinfo["ok"])) else 4

    except ModuleNotFoundError as exc:
        print(f"[pipeline] 依赖缺失：{exc}\n"
              "请执行 pip install -r requirements.txt（本技能只登记、不自动安装）",
              file=sys.stderr)
        return 3
    except Exception:
        print(f"[pipeline] 阶段 `{stage}` 失败：", file=sys.stderr)
        traceback.print_exc()
        (log_dir / "99_traceback.txt").write_text(traceback.format_exc(),
                                                  encoding="utf-8")
        return 1


def _verify_summary(problems):
    per = []
    for p in problems:
        per.append({"id": p["id"], "domain": p.get("domain"),
                    "solver": p.get("solver_module"),
                    "verified": bool(p.get("verified")),
                    "checks": [{"check": r["check"], "status": r["status"]}
                               for r in p.get("verify_results", [])]})
    n_check = sum(len(p.get("verify_results", [])) for p in problems)
    n_pass = sum(1 for p in problems for r in p.get("verify_results", [])
                 if r["status"] == "PASS")
    return {"passed": sum(1 for p in problems if p.get("verified")),
            "failed": sum(1 for p in problems
                          if p.get("solution") and not p.get("verified")),
            "unsolved": sum(1 for p in problems if not p.get("solution")),
            "checks_total": n_check, "checks_passed": n_pass,
            "problems": per}


if __name__ == "__main__":
    raise SystemExit(main())
