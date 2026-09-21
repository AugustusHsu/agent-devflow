"""最小測試：python .mkdocs/hooks/test_gfm_table_pipes.py（exit 0 即過）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gfm_table_pipes import unescape_table_code_pipes as fix  # noqa: E402

cases = [
    # 表格內 code：還原
    ("<td><code>a \\| b</code></td>", "<td><code>a | b</code></td>"),
    ("<th class=\"x\"><code>--jq '.a \\| .b'</code></th>", "<th class=\"x\"><code>--jq '.a | .b'</code></th>"),
    # 同格多個 code、code 外的文字不動
    ("<td>看 <code>x \\| y</code> 與 <code>p \\| q</code> \\| 文字</td>",
     "<td>看 <code>x | y</code> 與 <code>p | q</code> \\| 文字</td>"),
    # 表格外的 code：不動
    ("<p><code>a \\| b</code></p>", "<p><code>a \\| b</code></p>"),
    # fenced block（<pre><code>）不在表格內：不動
    ("<pre><code>a \\| b</code></pre>", "<pre><code>a \\| b</code></pre>"),
    # 跨行儲存格
    ("<td>\n<code>a \\| b</code>\n</td>", "<td>\n<code>a | b</code>\n</td>"),
]
bad = [(i, o, fix(i)) for i, o in cases if fix(i) != o]
for i, o, got in bad:
    print("FAIL\n  in : %r\n  want: %r\n  got : %r" % (i, o, got))
print("%d/%d passed" % (len(cases) - len(bad), len(cases)))
sys.exit(1 if bad else 0)
