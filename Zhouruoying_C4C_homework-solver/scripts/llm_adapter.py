"""本地大模型接入层（ollama / qwen3:8b）。

职责边界（很重要，写进 AI 日志）：
 * 模型只被用于 **规范化 / 路由兜底 / 讲解生成**；
 * **绝不**用模型产出最终数值答案 —— 数值一律来自 sympy 确定性求解，
   且要过 verify 层的独立核验。

所有调用都落盘留痕：`{prompt_sha256, raw_excerpt, latency_s, ok}`。
`--no-llm` 时本层整体旁路，管线仍可跑通（此时讲解栏留空并标注未启用）。
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request

DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("C4C_LLM_MODEL", "qwen3:8b")
TIMEOUT = float(os.environ.get("C4C_LLM_TIMEOUT", "180"))


class LLMUnavailable(RuntimeError):
    pass


def tags(host: str = DEFAULT_HOST):
    try:
        with urllib.request.urlopen(host.rstrip("/") + "/api/tags",
                                    timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:                       # pragma: no cover
        raise LLMUnavailable(f"无法连接本地模型服务 {host}: {exc}") from exc


def available(model: str = DEFAULT_MODEL, host: str = DEFAULT_HOST) -> bool:
    try:
        names = [m.get("name", "") for m in tags(host).get("models", [])]
    except LLMUnavailable:
        return False
    return any(n == model or n.split(":")[0] == model.split(":")[0]
               for n in names)


def generate(prompt: str, model: str = DEFAULT_MODEL, host: str = DEFAULT_HOST,
             think: bool = False) -> dict:
    """单次生成。返回 {text, meta}；meta 含 prompt 指纹与耗时。"""
    payload = {"model": model, "prompt": prompt, "stream": False,
               "think": think, "options": {"temperature": 0}}
    req = urllib.request.Request(
        host.rstrip("/") + "/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    import time
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = json.loads(r.read().decode("utf-8"))
        ok, text = True, (body.get("response") or "")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        ok, text, body = False, "", {"error": str(exc)}
    meta = {"model": model, "prompt_sha256":
            hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "prompt_chars": len(prompt),
            "latency_s": round(time.time() - t0, 2),
            "ok": ok, "raw_excerpt": text[:600]}
    if not ok:
        meta["error"] = body.get("error", "unknown")
    return {"text": text, "meta": meta}


def extract_json(text: str):
    """从模型输出里抠出第一个 JSON 数组/对象；失败返回 None。"""
    if not text:
        return None
    for opener, closer in (("[", "]"), ("{", "}")):
        i, j = text.find(opener), text.rfind(closer)
        if 0 <= i < j:
            try:
                return json.loads(text[i:j + 1])
            except json.JSONDecodeError:
                continue
    return None
