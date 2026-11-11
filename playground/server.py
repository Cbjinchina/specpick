"""specpick 浏览器测试台后端：仅标准库，直接调用仓库里的真实引擎。

这不是另一份实现——它把页面上的 TOML 写到 playground/live-case/，
然后调用 specpick.engine.decide 与 specpick.report.render_decision，
等价于命令行 `python -m specpick decide playground/live-case`。

图片上传只做一件事：把图片存到 playground/inbox/，不做识别。
识别由对话侧的多模态能力完成，再把结果写回 TOML（/api/import）。
这样模型始终待在引擎外面：裁决仍是纯函数，零 API Key、可复现。
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
# 兼容两种布局：仓库内的 playground/（正式）与仓库外的独立副本。
REPO = next(
    (p for p in (HERE.parent, HERE.parent / "specpick")
     if (p / "specpick" / "engine.py").exists()),
    HERE.parent,
)
sys.path.insert(0, str(REPO))

from specpick.engine import decide, load_case, validate_case  # noqa: E402
from specpick.report import (  # noqa: E402
    METRIC_LABELS,
    load_reviews,
    render_decision,
    render_review,
)

LIVE = HERE / "live-case"
LIVE.mkdir(exist_ok=True)
INBOX = HERE / "inbox"
INBOX.mkdir(exist_ok=True)
EXAMPLE = REPO / "examples" / "kitchen-rack"
RECORDS = REPO / "records"
MAX_BODY = 256 * 1024
MAX_IMAGE = 12 * 1024 * 1024  # 单张图片（base64 前的原始字节）

# 图片识别结果由对话侧写回 /api/import，页面据此自动刷新。
# 这个计数只用于通知页面「有新 TOML 了」，不参与任何计算。
REVISION = 0

IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

# 测试台自带三个案例：仓库示例（厨房小件）、笔记本电脑、以及从真实
# 电商截图读出参数后建立的显卡案例。引擎不区分品类，差别只在 needs.toml 的字段。
CASE_META = {
    "kitchen": {
        "label": "小厨房的沥水架",
        "desc": "仓库自带的原示例 · 家居小件，参数靠主观权衡",
        "dir": REPO / "examples" / "kitchen-rack",
        "extra": (
            '\n[[item]]\nid = "F"\nname = "新出的窄款不锈钢架"\nprice = 99\n'
            'width_cm = 26\nmaterial = "不锈钢"\nfootprint = 1\neasy_clean = 5\n'
        ),
    },
    "laptop": {
        "label": "笔记本电脑",
        "desc": "通勤办公场景 · 3C 参数可量化，重点看硬约束淘汰",
        "dir": HERE / "examples" / "laptop",
        "extra": (
            '\n[[item]]\nid = "F"\nname = "新出的超轻长续航本"\nprice = 4999\n'
            'weight_kg = 0.89\nbattery_h = 20\nram_gb = 16\nssd_gb = 512\n'
            'screen_inch = 14\ngpu = "核显"\nos = "Windows"\n'
        ),
    },
    "gpu": {
        "label": "显卡 · 京东截图",
        "desc": "真实商品截图读出 6 款显卡 · 演示图片辅助录入与可比性分组",
        "dir": HERE / "examples" / "gpu",
        "extra": (
            '\n[[item]]\nid = "G"\nname = "新看的一款显卡（改成实际型号）"\n'
            'price = 4499\nvram_gb = 8\nfan_count = 2\ntier = 0\n'
            'source = "手动补充"\n'
        ),
    },
}


def load_cases() -> dict:
    out = {}
    for cid, meta in CASE_META.items():
        out[cid] = {
            "label": meta["label"],
            "desc": meta["desc"],
            "needs": (meta["dir"] / "needs.toml").read_text(encoding="utf-8"),
            "items": (meta["dir"] / "items.toml").read_text(encoding="utf-8"),
            "extraItem": meta["extra"],
        }
    return out


def write_inputs(needs_text: str, items_text: str) -> None:
    (LIVE / "needs.toml").write_text(needs_text, encoding="utf-8", newline="\n")
    (LIVE / "items.toml").write_text(items_text, encoding="utf-8", newline="\n")


def safe_stem(name: str) -> str:
    stem = Path(name or "image").stem
    stem = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]", "_", stem)[:40]
    return stem or "image"


def save_image(name: str, data_url: str) -> dict:
    """只把图片存到本机 inbox/，不做任何识别。

    识别这一步刻意留给对话侧的多模态能力：引擎保持零依赖、可复现，
    模型只负责把非结构化的图片翻译成可 git diff 的 TOML。
    """
    m = re.match(r"^data:(image/[a-z+]+);base64,(.*)$", data_url or "", re.S)
    if not m:
        raise ValueError("只支持 PNG / JPEG / WebP / GIF 的 data URL")
    suffix = IMAGE_TYPES.get(m.group(1))
    if not suffix:
        raise ValueError(f"不支持的图片类型：{m.group(1)}")
    try:
        raw = base64.b64decode(m.group(2), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"图片解码失败：{exc}") from exc
    if not raw:
        raise ValueError("图片内容为空")
    if len(raw) > MAX_IMAGE:
        raise ValueError(f"图片超过 {MAX_IMAGE // 1024 // 1024} MB 上限")
    filename = f"{time.strftime('%Y%m%d-%H%M%S')}-{safe_stem(name)}{suffix}"
    target = INBOX / filename
    target.write_bytes(raw)
    return {"file": filename, "path": str(target), "bytes": len(raw)}


def current_inputs() -> dict:
    needs = LIVE / "needs.toml"
    items = LIVE / "items.toml"
    return {
        "revision": REVISION,
        "needs": needs.read_text(encoding="utf-8") if needs.exists() else "",
        "items": items.read_text(encoding="utf-8") if items.exists() else "",
    }


def summary_of(result) -> dict:
    moves = result.moves
    top_move = None
    if moves:
        m = moves[0]
        label = METRIC_LABELS.get(m.metric, m.metric)
        top_move = {
            "label": label,
            "current": m.current,
            "target": m.target,
            "direction": "降到" if result.directions.get(m.metric) == "lower" else "提到",
            "percent": round(m.relative * 100),
        }
    sens = result.sensitivity or {}
    return {
        "case_id": result.case_id,
        "winner": result.winner.name if result.winner else None,
        "total": result.winner.total if result.winner else None,
        "accepted": len(result.accepted),
        "rejected": len(result.rejected),
        "verdict": sens.get("verdict"),
        "trials": sens.get("trials", 0),
        "flips": len(sens.get("flips", [])),
        "moves": len(moves),
        "top_move": top_move,
        "runner_up": result.runner_up.name if result.runner_up else None,
    }


def run_case(needs_text: str, items_text: str, mode: str) -> dict:
    write_inputs(needs_text, items_text)
    started = time.perf_counter()

    if mode == "check":
        try:
            needs, items = load_case(LIVE)
            errors = validate_case(needs, items)
        except Exception as exc:  # TOML 语法错误等
            return {
                "ok": False,
                "mode": "check",
                "errors": [f"TOML 解析失败：{exc}"],
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            }
        return {
            "ok": not errors,
            "mode": "check",
            "errors": errors,
            "check": {
                "items": len(items),
                "hard": len(needs.get("hard", [])),
                "metrics": len(needs.get("weights", {})),
            },
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        }

    try:
        result, errors = decide(LIVE)
    except Exception as exc:
        return {
            "ok": False,
            "mode": "decide",
            "errors": [f"TOML 解析失败：{exc}"],
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    if errors:
        return {
            "ok": False,
            "mode": "decide",
            "errors": errors,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        }

    markdown = render_decision(result)
    # 项目卖点是可复现：连续算两次，文本必须 byte 级一致
    result2, errors2 = decide(LIVE)
    reproducible = not errors2 and render_decision(result2) == markdown
    # 与 CLI 的 _write() 保持完全一致的落盘方式（Windows 上同样是 CRLF）
    (LIVE / "report.md").write_text(markdown, encoding="utf-8")
    return {
        "ok": True,
        "mode": "decide",
        "errors": [],
        "markdown": markdown,
        "summary": summary_of(result),
        "reproducible": reproducible,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        "paths": {
            "needs": str(LIVE / "needs.toml"),
            "items": str(LIVE / "items.toml"),
            "report": str(LIVE / "report.md"),
        },
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "specpick-playground/0.1"

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: dict, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            try:
                self._send(200, (HERE / "index.html").read_bytes(),
                           "text/html; charset=utf-8")
            except OSError as exc:
                self._json({"error": str(exc)}, 500)
            return
        if path == "/api/cases":
            self._json({"cases": load_cases()})
            return
        if path == "/api/defaults":
            self._json({
                "needs": (EXAMPLE / "needs.toml").read_text(encoding="utf-8"),
                "items": (EXAMPLE / "items.toml").read_text(encoding="utf-8"),
            })
            return
        if path == "/api/review":
            self._json({
                "markdown": render_review(load_reviews(RECORDS)),
                "count": len(load_reviews(RECORDS)),
            })
            return
        if path == "/api/current":
            self._json(current_inputs())
            return
        if path == "/api/inbox":
            files = sorted(INBOX.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
            self._json({"images": [
                {"file": p.name, "path": str(p), "bytes": p.stat().st_size}
                for p in files if p.is_file() and p.suffix.lower() in IMAGE_TYPES.values()
            ]})
            return
        self._json({"error": "not found"}, 404)

    def _read_body(self, limit: int) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > limit:
            raise ValueError(f"请求体过大（上限 {limit // 1024} KB）")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        if path not in ("/api/run", "/api/upload-image", "/api/import"):
            self._json({"error": "not found"}, 404)
            return
        try:
            if path == "/api/upload-image":
                try:
                    data = self._read_body(MAX_IMAGE * 2)
                    saved = save_image(data.get("name", ""), data.get("data", ""))
                    self._json({"ok": True, **saved})
                except ValueError as exc:
                    self._json({"ok": False, "error": str(exc)}, 400)
                return
            if path == "/api/import":
                global REVISION
                data = self._read_body(MAX_BODY)
                n, i = data.get("needs", ""), data.get("items", "")
                if not isinstance(n, str) or not isinstance(i, str) or not n.strip() or not i.strip():
                    self._json({"ok": False, "error": "needs / items 不能为空"}, 400)
                    return
                write_inputs(n, i)
                REVISION += 1
                self._json({"ok": True, "revision": REVISION})
                return
            data = self._read_body(MAX_BODY)
            needs_text = data.get("needs", "")
            items_text = data.get("items", "")
            mode = data.get("mode", "decide")
            if not isinstance(needs_text, str) or not isinstance(items_text, str):
                self._json({"ok": False, "errors": ["needs / items 必须是文本"]}, 400)
                return
            if mode not in ("decide", "check"):
                mode = "decide"
            self._json(run_case(needs_text, items_text, mode))
        except Exception as exc:  # 任何异常都以 JSON 返回，不让测试台崩掉
            self._json({"ok": False, "mode": "decide",
                        "errors": [f"服务端异常：{type(exc).__name__}: {exc}"]}, 200)

    def do_HEAD(self) -> None:
        # 预览面板 / 健康检查常用 HEAD，必须给出 200 而不是 501
        try:
            size = (HERE / "index.html").stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
        except OSError:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Allow", "GET, HEAD, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, fmt: str, *args) -> None:
        try:
            line = fmt % args
            if any(k in line for k in ("POST /api/run", "POST /api/upload-image", "POST /api/import")):
                sys.stderr.write("[playground] " + line + "\n")
        except Exception:
            pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"specpick playground running at http://127.0.0.1:{port}", flush=True)
    print(f"engine: {REPO}", flush=True)
    httpd.serve_forever()
