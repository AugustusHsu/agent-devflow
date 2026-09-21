"""MkDocs hook：讓 markdown 表格儲存格內 code span 的 `\\|` 渲成 `|`，與 GitHub（GFM）一致。

為什麼需要：對照表（devflow/forges/*.md 等）的值欄常含 shell／jq 的管線符號，在 markdown 表格裡
必須寫成 `\\|` 才不會被當成欄位分隔。GitHub 渲染時把 `\\|` 還原為 `|`；Python-Markdown 的 tables
擴充也把它當分隔跳脫，但**保留反斜線**留在 <code> 內（實測 Markdown 3.10.3：`x \\| y` → `<code>x \\| y</code>`）。
不處理的話站上每條這類指令都多一個反斜線，第三者照抄會錯（R8）。

作法：不碰產出的 HTML 字串，而是掛一個 Python-Markdown treeprocessor（排在 inline 之後），
走 ElementTree 裡 markdown 產生的 <table> 底下的 <code> 元素，把文字中的 `\\|` 換成 `|`。
邊界由 parser 決定，不是由我猜：
- 原始 HTML（<textarea>、<title>、<svg><![CDATA[…]]>、註解、<script>、<table> 手寫 HTML）在 Python-Markdown
  裡整段進 htmlStash、以占位符代替，根本不在樹裡——treeprocessor 看不到、改不到。
- markdown 表格裡不可能有 fenced block，<pre> 只可能來自原始 HTML → 同上，不在樹裡；仍保留一道 <pre> 守衛。
- 表格外的 code span、段落文字、fenced block 不在 <table> 底下，不動。
接進 MkDocs 的方式：on_config 把擴充實例 append 進 config.markdown_extensions（config 驗證已過，
markdown.Markdown 接受實例）。
"""
from markdown import Extension, util
from markdown.treeprocessors import Treeprocessor

_ESCAPED = "\\|"


class _UnescapeTablePipes(Treeprocessor):
    def run(self, root):
        for table in root.iter("table"):
            self._walk(table, in_pre=False)

    def _walk(self, el, in_pre):
        for child in el:
            tag = child.tag if isinstance(child.tag, str) else ""
            if tag == "pre":
                self._walk(child, True)
                continue
            if tag == "code" and not in_pre and child.text and _ESCAPED in child.text:
                child.text = util.AtomicString(child.text.replace(_ESCAPED, "|"))
            self._walk(child, in_pre)


class GfmTablePipes(Extension):
    def extendMarkdown(self, md):
        # inline 是 20、prettify 是 10；要在 code span 建好之後、序列化之前。
        md.treeprocessors.register(_UnescapeTablePipes(md), "gfm_table_pipes", 15)


def on_config(config):  # MkDocs hook 入口
    config.markdown_extensions.append(GfmTablePipes())
    return config
