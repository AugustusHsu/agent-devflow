"""最小測試：python .mkdocs/hooks/test_gfm_table_pipes.py（exit 0 即過）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gfm_table_pipes import unescape_table_code_pipes as fix  # noqa: E402

T = "<table><tr>%s</tr></table>"
cases = [
    # 表格內 code：還原
    (T % "<td><code>a \\| b</code></td>", T % "<td><code>a | b</code></td>"),
    (T % "<th class=\"x\"><code>--jq '.a \\| .b'</code></th>", T % "<th class=\"x\"><code>--jq '.a | .b'</code></th>"),
    # 同格多個 code、code 外的文字不動
    (T % "<td>看 <code>x \\| y</code> 與 <code>p \\| q</code> \\| 文字</td>",
     T % "<td>看 <code>x | y</code> 與 <code>p | q</code> \\| 文字</td>"),
    # 表格外的 code：不動
    ("<p><code>a \\| b</code></p>", "<p><code>a \\| b</code></p>"),
    # fenced block（<pre><code>）不在表格內：不動
    ("<pre><code>a \\| b</code></pre>", "<pre><code>a \\| b</code></pre>"),
    # 跨行儲存格
    (T % "<td>\n<code>a \\| b</code>\n</td>", T % "<td>\n<code>a | b</code>\n</td>"),
    # 審查反例 1：儲存格內的 <pre><code> 是作者原文，不動
    (T % "<td><pre><code>x \\| y</code></pre></td>", T % "<td><pre><code>x \\| y</code></pre></td>"),
    # 審查反例 2：巢狀表格，內外層 code 都要改
    (T % "<td>outer<table><tr><td><code>inner \\| x</code></td></tr></table><code>outer \\| y</code></td>",
     T % "<td>outer<table><tr><td><code>inner | x</code></td></tr></table><code>outer | y</code></td>"),
    # 審查反例 3：沒有 <table> 祖先的 <td>（畸形）不動
    ("<td><code>x \\| y</code></td>", "<td><code>x \\| y</code></td>"),
    # 儲存格關閉後的 code 不動（深度歸零）
    (T % "<td><code>a \\| b</code></td>" + "<code>c \\| d</code>", T % "<td><code>a | b</code></td>" + "<code>c \\| d</code>"),
    # 標籤帶屬性、大小寫混用
    ("<TABLE><TR><TD align=\"left\"><CODE>a \\| b</CODE></TD></TR></TABLE>",
     "<TABLE><TR><TD align=\"left\"><CODE>a | b</CODE></TD></TR></TABLE>"),
    # 儲存格內 pre 之後的 code 仍要改（pre 深度已歸零）
    (T % "<td><pre><code>x \\| y</code></pre><code>p \\| q</code></td>",
     T % "<td><pre><code>x \\| y</code></pre><code>p | q</code></td>"),
    # 審查 R2 反例：HTML 註解裡的假標籤不計深度
    ("<!-- <table><td><code> --><p>outside \\| text</p><!-- </code></td></table> -->",
     "<!-- <table><td><code> --><p>outside \\| text</p><!-- </code></td></table> -->"),
    # 審查 R2 反例：<script> 內的字串不計深度
    ("<script>const s=\"<table><td><code>\";</script><p>outside \\| text</p>",
     "<script>const s=\"<table><td><code>\";</script><p>outside \\| text</p>"),
    # 註解在真表格內：註解本身不動，旁邊的 code 照改
    (T % "<td><!-- a \\| b --><code>a \\| b</code></td>", T % "<td><!-- a \\| b --><code>a | b</code></td>"),
    # <style> 內容整段跳過
    ("<style>td::after{content:\"<code>\"}</style>" + T % "<td><code>a \\| b</code></td>",
     "<style>td::after{content:\"<code>\"}</style>" + T % "<td><code>a | b</code></td>"),
    # <th> 內 <pre>：不動
    (T % "<th><pre><code>x \\| y</code></pre></th>", T % "<th><pre><code>x \\| y</code></pre></th>"),
    # 未閉合的 <td>：到 </table> 為止都算格內（深度不會因缺 </td> 而錯位到表格外）
    (T % "<td><code>a \\| b</code>" + "<code>c \\| d</code>", T % "<td><code>a | b</code>" + "<code>c \\| d</code>"),
    # 未閉合的 <td> 不得延續到下一個表格的格外區域（caption 不是格）
    (T % "<td><code>a \\| b</code>" + "<table><caption><code>c \\| d</code></caption></table>",
     T % "<td><code>a | b</code>" + "<table><caption><code>c \\| d</code></caption></table>"),
    # code 內的轉義 '<'（&lt;）不是標籤
    (T % "<td><code>gh pr review &lt;N&gt; --approve\\|--request</code></td>",
     T % "<td><code>gh pr review &lt;N&gt; --approve|--request</code></td>"),
]
bad = [(i, o, fix(i)) for i, o in cases if fix(i) != o]
for i, o, got in bad:
    print("FAIL\n  in : %r\n  want: %r\n  got : %r" % (i, o, got))
print("%d/%d passed" % (len(cases) - len(bad), len(cases)))
sys.exit(1 if bad else 0)
