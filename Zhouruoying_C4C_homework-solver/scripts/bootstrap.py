"""依赖自检与本地 LaTeX 引擎探测。

设计原则：**只做检查，不擅自安装**。缺依赖时给出可执行的修复命令并抛错，
避免「静默降级」导致产物与声称不符。
"""
from __future__ import annotations

import importlib
import importlib.metadata as md
import os
import shutil
import subprocess
import sys
from pathlib import Path

REQUIRED = [("sympy", "sympy>=1.12"), ("yaml", "pyyaml>=6.0")]
OPTIONAL = [("numpy", "numpy"), ("pdfplumber", "pdfplumber>=0.9"),
            ("docx", "python-docx>=0.8")]
LATEX_ENGINES = ["tectonic", "xelatex", "lualatex", "latexmk"]


def _version(mod_name: str) -> str:
    for dist in {mod_name, {"yaml": "PyYAML", "docx": "python-docx"}.get(mod_name, mod_name)}:
        try:
            return md.version(dist)
        except Exception:
            continue
    return "unknown"


def _find_engine() -> dict:
    """按优先级探测可用的 LaTeX 引擎（含本机 _tools 私有安装）。"""
    here = Path(__file__).resolve().parent.parent
    candidates = []
    for eng in LATEX_ENGINES:
        p = shutil.which(eng)
        if p:
            candidates.append((eng, p))
    # 私有安装：<skill>/../_tools/tectonic/tectonic 或 <skill>/_tools/...
    for base in (here, here.parent, here.parent.parent):
        for rel in ("_tools/tectonic/tectonic", "tools/tectonic/tectonic"):
            cand = base / rel
            if cand.is_file() and os.access(cand, os.X_OK):
                candidates.append(("tectonic", str(cand)))
    if not candidates:
        return {"available": False, "engine": None, "path": None}
    # tectonic 优先（自带 bundle、无需系统 TeX）
    for eng, path in candidates:
        if eng == "tectonic":
            return {"available": True, "engine": eng, "path": path}
    return {"available": True, "engine": candidates[0][0], "path": candidates[0][1]}


def check(verbose: bool = False) -> dict:
    report = {"python": sys.version.split()[0], "required": {}, "optional": {},
              "missing_required": [], "latex": None}
    for mod, spec in REQUIRED:
        try:
            importlib.import_module(mod)
            report["required"][spec] = {"ok": True, "version": _version(mod)}
        except ImportError as exc:
            report["required"][spec] = {"ok": False, "error": str(exc)}
            report["missing_required"].append(spec)
    for mod, spec in OPTIONAL:
        try:
            importlib.import_module(mod)
            report["optional"][spec] = {"ok": True, "version": _version(mod)}
        except ImportError:
            report["optional"][spec] = {"ok": False}
    report["latex"] = _find_engine()
    if verbose:
        print(f"[bootstrap] python {report['python']}")
        for spec, info in report["required"].items():
            print(f"[bootstrap]   required {spec}: {'OK' if info['ok'] else 'MISSING'}")
        for spec, info in report["optional"].items():
            print(f"[bootstrap]   optional {spec}: {'OK' if info['ok'] else 'absent'}")
        lx = report["latex"]
        print(f"[bootstrap]   latex: {lx['engine']} @ {lx['path']}"
              if lx["available"] else "[bootstrap]   latex: 未找到可用引擎")
    return report


def ensure_dependencies(verbose: bool = False) -> dict:
    report = check(verbose=verbose)
    if report["missing_required"]:
        specs = " ".join(report["missing_required"])
        raise ModuleNotFoundError(
            f"缺少必需依赖：{specs}\n修复：pip install {specs}")
    return report


def latex_smoke_test(engine_path: str, timeout: int = 300) -> tuple[bool, str]:
    """最小中文文档编译冒烟测试，用于确认引擎真的能出 PDF。"""
    import tempfile
    tex = (r"\documentclass{article}" "\n"
           r"\usepackage{fontspec}\setmainfont{PingFang SC}" "\n"
           r"\usepackage{amsmath}" "\n"
           r"\begin{document}中文测试 $\det A=-2$\end{document}" "\n")
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "smoke.tex"
        src.write_text(tex, encoding="utf-8")
        env = dict(os.environ)
        env.setdefault("HTTPS_PROXY", "http://127.0.0.1:7897")
        cmd = ([engine_path, "-X", "compile", "smoke.tex"]
               if "tectonic" in engine_path else [engine_path, "smoke.tex"])
        try:
            r = subprocess.run(cmd, cwd=td, env=env, capture_output=True,
                               text=True, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            return False, f"{exc}"
        pdf = Path(td) / "smoke.pdf"
        return (r.returncode == 0 and pdf.is_file(),
                f"rc={r.returncode} pdf={pdf.stat().st_size if pdf.is_file() else 0}B")
