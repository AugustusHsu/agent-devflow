"""MkDocs hook：讓表格儲存格內 code span 的 `\\|` 渲成 `|`，與 GitHub（GFM）一致。

為什麼需要：對照表（devflow/forges/*.md 等）的值欄常含 shell／jq 的管線符號，在 markdown 表格裡
必須寫成 `\\|` 才不會被當成欄位分隔。GitHub 渲染時把 `\\|` 還原為 `|`；Python-Markdown 的 tables
擴充也把它當分隔跳脫，但**保留反斜線**留在 <code> 內（實測 Markdown 3.10.3：`x \\| y` → `<code>x \\| y</code>`）。
不處理的話站上每條這類指令都多一個反斜線，第三者照抄會錯（R8）。

作法：on_page_content 在產出 HTML 後，只對 <td>／<th> 內的 <code>…</code> 做 `\\|` → `|`。
不碰表格外的 code（那裡的 `\\|` 是作者原意）、不碰 <pre>（fenced block 不在表格內）。
"""
import re

_CELL = re.compile(r"(<t[dh]\b[^>]*>)(.*?)(</t[dh]>)", re.S)
_CODE = re.compile(r"(<code\b[^>]*>)(.*?)(</code>)", re.S)


def _fix_cell(m: "re.Match[str]") -> str:
    inner = _CODE.sub(lambda c: c.group(1) + c.group(2).replace("\\|", "|") + c.group(3), m.group(2))
    return m.group(1) + inner + m.group(3)


def unescape_table_code_pipes(html: str) -> str:
    return _CELL.sub(_fix_cell, html)


def on_page_content(html, page, config, files):  # MkDocs hook 入口
    return unescape_table_code_pipes(html)
