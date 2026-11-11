"""把网页版打包成一个可以离线分发、存到手机里直接打开的 HTML 文件。

web/index.html 与 web/engine.js 是源码（便于 Node 校验与维护）；
web/specpick.html 是构建产物，只有一个文件，双击即可使用、不需要服务器。

    python web/build.py            # 重新生成
    python web/build.py --check    # CI 用：确认产物与源码没有脱节
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
INDEX = HERE / "index.html"
ENGINE = HERE / "engine.js"
OUTPUT = HERE / "specpick.html"
TAG = '<script src="engine.js"></script>'


def build() -> str:
    html = INDEX.read_text(encoding="utf-8")
    js = ENGINE.read_text(encoding="utf-8")
    if TAG not in html:
        raise RuntimeError("index.html 里找不到 engine.js 的引用标记")
    # 避免 JS 里出现 </script> 时提前闭合标签
    inline = "<script>\n" + js.replace("</script>", "<\\/script>") + "\n</script>"
    return html.replace(TAG, inline, 1)


def main() -> int:
    content = build()
    if "--check" in sys.argv:
        if not OUTPUT.exists():
            print("FAIL: 缺少 web/specpick.html，请运行 python web/build.py")
            return 1
        if OUTPUT.read_text(encoding="utf-8") != content:
            print("FAIL: web/specpick.html 与源码不一致，请运行 python web/build.py 重新生成")
            return 1
        print("OK: web/specpick.html 与源码一致")
        return 0
    OUTPUT.write_text(content, encoding="utf-8", newline="\n")
    print(f"OK: 已生成 {OUTPUT}（{OUTPUT.stat().st_size} 字节，单文件、可离线）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
