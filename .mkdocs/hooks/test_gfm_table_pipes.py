"""最小測試：python .mkdocs/hooks/test_gfm_table_pipes.py（exit 0 即過）。
每案走真實管線：markdown.markdown(src, extensions=["tables", "fenced_code", GfmTablePipes()])，
與 .mkdocs/mkdocs.yml 的 markdown_extensions 相同（toc 不影響本題）。"""
import sys
from pathlib import Path

import markdown

sys.path.insert(0, str(Path(__file__).parent))
from gfm_table_pipes import GfmTablePipes  # noqa: E402


def render(src):
    return markdown.markdown(src, extensions=["tables", "fenced_code", GfmTablePipes()])


def render_plain(src):
    return markdown.markdown(src, extensions=["tables", "fenced_code"])


TABLE = "| a | b |\n|---|---|\n| %s | z |\n"
# (src, needle, expect)：expect=True 產出須含 needle；False 須不含；None 表示「hook 不得改變 Python-Markdown
# 的產出」（render == render_plain）——原始 HTML／表格外內容一律用這條，不猜 Python-Markdown 自己怎麼渲。
cases = [
    # 表格儲存格內 code span：還原
    (TABLE % "`x \\| y`", "<code>x | y</code>", True),
    # 標題列（th）也算
    ("| `p \\| q` |\n|---|\n| z |\n", "<code>p | q</code>", True),
    # 同格多個 code、code 外的 \| 由 tables 擴充自己處理（變成 |），與 GitHub 相同
    (TABLE % "看 `x \\| y` 與 `p \\| q`", "<code>x | y</code> 與 <code>p | q</code>", True),
    # code 內的 < 仍是 &lt;（不破壞既有轉義）
    (TABLE % "`gh pr review <N> --approve\\|--x`", "<code>gh pr review &lt;N&gt; --approve|--x</code>", True),
    # 兩個反斜線＋管線：只吃掉一個反斜線——與 GitHub /markdown API 對 github.md 第 16 行的渲染相同
    (TABLE % "`--approve\\\\|--request`", "<code>--approve\\|--request</code>", True),
    # 表格外的 code span：不動（GitHub 也不動）
    ("段落 `a \\| b` 結束\n", None, None),
    # fenced block：不動
    ("```\n| a \\| b |\n```\n", None, None),
    # 審查反例（R3-A）：<textarea> RCDATA 內的假標籤——原始 HTML 不在樹裡，外面的 <p> 不動
    ("<textarea><table><td><code></textarea><p>outside \\| text</p>\n", None, None),
    # 審查反例（R3-B）：SVG CDATA
    ("<div>\n<svg><![CDATA[<table><td><code>]]></svg>\n</div>\n<p>outside \\| text</p>\n", None, None),
    # <title> raw text
    ("<title><table><td><code></title><p>outside \\| text</p>\n", None, None),
    # 審查反例（R2）：HTML 註解裡的假標籤、<script> 內的字串
    ("<!-- <table><td><code> --><p>outside \\| text</p><!-- </code></td></table> -->\n", None, None),
    ("<script>const s=\"<table><td><code>\";</script><p>outside \\| text</p>\n", None, None),
    # 審查反例（R1）：手寫 HTML 表格內的 <pre><code>——原始 HTML，整段不動
    ("<table><tr><td><pre><code>x \\| y</code></pre></td></tr></table>\n", None, None),
    # 手寫 HTML 表格內的 <code>：原始 HTML，不動（GitHub 對原始 HTML 也不做 markdown 跳脫）
    ("<table><tr><td><code>x \\| y</code></td></tr></table>\n", None, None),
    # 原始 HTML 表格之後的 markdown 表格照常處理（狀態不互相污染）
    ("<table><tr><td><code>raw \\| x</code></td></tr></table>\n\n" + TABLE % "`md \\| y`",
     "<code>raw \\| x</code>", True),
    ("<table><tr><td><code>raw \\| x</code></td></tr></table>\n\n" + TABLE % "`md \\| y`",
     "<code>md | y</code>", True),
    # 反向斷言：真實案例不應再含反斜線
    (TABLE % "`x \\| y`", "\\|", False),
]
bad = []
for src, needle, expect in cases:
    out = render(src)
    if expect is None:
        plain = render_plain(src)
        if out != plain:
            bad.append((src, "must equal plain render", plain, out))
    elif (needle in out) != expect:
        bad.append((src, "want" if expect else "must NOT contain", needle, out))
for src, what, needle, out in bad:
    print("FAIL\n  src : %r\n  %s: %r\n  out : %r" % (src, what, needle, out))
print("%d/%d passed" % (len(cases) - len(bad), len(cases)))
sys.exit(1 if bad else 0)
