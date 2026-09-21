"""MkDocs hook：讓表格儲存格內 code span 的 `\\|` 渲成 `|`，與 GitHub（GFM）一致。

為什麼需要：對照表（devflow/forges/*.md 等）的值欄常含 shell／jq 的管線符號，在 markdown 表格裡
必須寫成 `\\|` 才不會被當成欄位分隔。GitHub 渲染時把 `\\|` 還原為 `|`；Python-Markdown 的 tables
擴充也把它當分隔跳脫，但**保留反斜線**留在 <code> 內（實測 Markdown 3.10.3：`x \\| y` → `<code>x \\| y</code>`）。
不處理的話站上每條這類指令都多一個反斜線，第三者照抄會錯（R8）。

作法：on_page_content 在產出 HTML 後線性掃描 <table>／<td>／<th>／<pre>／<code> 的開閉標籤，維持深度計數；
只有「在 <table> 內的 <td>／<th> 內、不在 <pre> 內」的 <code> 文字才做 `\\|` → `|`。
- 巢狀表格：以深度計數處理，內外層儲存格都算。
- <td><pre><code>（HTML 表格才可能出現）：<pre> 內是作者原文，不動。
- 沒有 <table> 祖先的 <td>（畸形 HTML）：不動。
- HTML 註解、<script>／<style> 的內容整段原樣輸出，也不計入深度（裡面的「標籤」不是標籤）。
- 其他標籤與屬性一律原樣輸出，不重寫 HTML。
"""
import re

# 三種 token：整段跳過的區塊（註解、script、style）｜計深度的開閉標籤。
_TOKEN = re.compile(
    r"(?P<skip><!--.*?-->|<script\b[^>]*>.*?</script\s*>|<style\b[^>]*>.*?</style\s*>)"
    r"|<(?P<close>/?)(?P<name>table|td|th|pre|code)\b[^>]*>",
    re.I | re.S,
)


def unescape_table_code_pipes(html: str) -> str:
    out = []
    pos = 0
    table = cell = pre = code = 0
    for m in _TOKEN.finditer(html):
        text = html[pos:m.start()]
        if code and cell and table and not pre:
            text = text.replace("\\|", "|")
        out.append(text)
        out.append(m.group(0))
        pos = m.end()
        if m.group("skip") is not None:
            continue
        closing, name = m.group("close") == "/", m.group("name").lower()
        delta = -1 if closing else 1
        if name == "table":
            table = max(0, table + delta)
            if table == 0:          # 最外層表格關閉：未閉合的 <td>／<code> 不得延續到表格外
                cell = code = 0
        elif name in ("td", "th"):
            cell = max(0, cell + delta)
        elif name == "pre":
            pre = max(0, pre + delta)
        elif name == "code":
            code = max(0, code + delta)
    tail = html[pos:]
    if code and cell and table and not pre:
        tail = tail.replace("\\|", "|")
    out.append(tail)
    return "".join(out)


def on_page_content(html, page, config, files):  # MkDocs hook 入口
    return unescape_table_code_pipes(html)
