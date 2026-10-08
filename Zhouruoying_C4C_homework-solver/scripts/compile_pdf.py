"""阶段 ⑦：编译 PDF。

引擎优先级：tectonic（随技能自带/私有 _tools 目录）→ xelatex → lualatex → latexmk。
**必须**是 XeLaTeX 系引擎，否则 fontspec 与中文会直接失败 —— 这里在选引擎前
就先按序试编译，pdflatex 不在候选里。

代理：首次编译需要拉取 tectonic 宏包（约几十 MB），走 `C4C_PROXY`
（默认读环境里的 HTTPS_PROXY），失败则回退到已缓存的本地 bundle。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent

PRIVATE_ENGINES = [
    SKILL_ROOT / "_tools" / "tectonic" / "tectonic",
    Path.home() / ".cogseed-dev" / "userWorkSpace" / "检查挑战清单完成情况"
    / "_tools" / "tectonic" / "tectonic",
]
NAME_ENGINES = ["tectonic", "xelatex", "lualatex", "latexmk"]


def find_engine():
    for p in PRIVATE_ENGINES:
        if p.exists() and os.access(p, os.X_OK):
            return str(p), "private"
    for n in NAME_ENGINES:
        got = shutil.which(n)
        if got:
            return got, "path"
    return None, None


def _env():
    env = dict(os.environ)
    proxy = env.get("C4C_PROXY") or env.get("HTTPS_PROXY") or ""
    if proxy:
        env.setdefault("HTTPS_PROXY", proxy)
        env.setdefault("HTTP_PROXY", proxy)
        env.setdefault("ALL_PROXY", proxy)
    return env


def compile_pdf(tex_path, out_dir=None, timeout=600):
    tex = Path(tex_path).resolve()
    out_dir = Path(out_dir or tex.parent).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    engine, origin = find_engine()
    if engine is None:
        return {"ok": False, "rc": 3, "engine": None,
                "error": "未找到 XeLaTeX 系引擎（tectonic/xelatex/lualatex/latexmk）；"
                         "安装：brew install tectonic 或把 tectonic 放到 _tools/tectonic/",
                "log": ""}
    name = Path(engine).name
    if name == "tectonic":
        cmd = [engine, "-X", "compile", tex.name, "--keep-logs"]
    elif name == "latexmk":
        cmd = [engine, "-xelatex", "-interaction=nonstopmode", tex.name]
    else:
        cmd = [engine, "-interaction=nonstopmode", "-halt-on-error", tex.name]
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(tex.parent), env=_env(),
                              capture_output=True, text=True, timeout=timeout)
        rc, out = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        rc, out = 4, f"编译超时（>{timeout}s）"
    dt = round(time.time() - t0, 1)
    logp = out_dir / (tex.stem + ".compile.log")
    logp.write_text(f"engine={engine} ({origin})\ncmd={' '.join(cmd)}\n"
                    f"rc={rc}\ncwd={tex.parent}\nelapsed_s={dt}\n"
                    f"{'-' * 60}\n{out}", encoding="utf-8")
    produced = tex.parent / (tex.stem + ".pdf")
    final = out_dir / (tex.stem + ".pdf")
    if produced.exists() and produced != final:
        shutil.copy2(produced, final)
    ok = rc == 0 and final.exists() and final.stat().st_size > 800
    return {"ok": ok, "rc": rc, "engine": f"{name} ({origin})", "elapsed_s": dt,
            "pdf": str(final) if final.exists() else None,
            "pdf_bytes": final.stat().st_size if final.exists() else 0,
            "log": str(logp), "tail": out[-1200:]}
