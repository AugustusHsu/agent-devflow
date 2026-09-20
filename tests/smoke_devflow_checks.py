#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/devflow_checks.py 的煙霧測試（issue #82 AC-4）。

從 repo 根執行：

    python3 tests/smoke_devflow_checks.py

不引入任何新相依（只用標準庫 ＋ git ＋ 檢查器自己已經要求的 markdown-it-py／PyYAML）。
**不是** unit test 框架：沒有 discovery、沒有 fixture，就是「造一份輸入、跑檢查器、比 exit code」。

為什麼有這個檔：PR #81 的七輪審查裡，每一輪的驗證都是手工複製 worktree、注入突變、還原，
審查者與 orchestrator 各自實作過一次抽取邏輯、各自出過錯（見 issue #22 的執行方式教訓）。
檢查器抽成獨立腳本後，回歸就只是跑這個檔。

做法：
  1. 把「git add -A 之後會在 repo 裡的檔案」（受版控 ＋ 未忽略的未追蹤檔）複製到一個
     臨時目錄，git init ＋ git add —— 檢查器認的是 `git ls-files`，所以 index 有就夠，
     不必 commit。
  2. 先跑一次**沒有突變**的正向案例，要求 exit 0 且一個 ❌ 都沒有。
  3. 每個關卡至少注入一個「應擋」的突變，要求 exit 1，且輸出裡出現該關卡的訊息。
     每個案例都從乾淨的沙箱重造，突變之間不互相污染。
  4. 另有「突變後仍應通過」的正向案例（PASSING）：證明判準不誤擋正當變更，要求 exit 0 且 0 個 ❌。
  5. 另有「一個突變同時觸發多項」的案例（MULTI）：要求 ❌ 的條數恰好等於列出的那幾條。
     用來鎖 fail closed——某一項該報而沒報時，條數會少，本檔就失敗（issue #91 AC-1）。

正向案例 0 個 ❌ 這件事讓負向案例的 ❌ 有了歸因：乾淨輸入不產生任何 ❌，所以突變後冒出來的
每一條 ❌ 都是該突變造成的。本檔會把每個案例實際冒出的 ❌ 全部印出來，供人核對「exit 1
只能由目標項造成」（README「Phase 1 第三出口的判定方式」條件三）。
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CHECKER = REPO / "scripts" / "devflow_checks.py"

# 沙箱裡當成 head branch 的名字：合 `I1` 的 `<N>-<slug>`，讓正向案例真的跑到 i1 而不是略過。
GOOD_HEAD_REF = "82-extract-checker"


# ── 沙箱 ──────────────────────────────────────────────────────────
def repo_files():
    """git add -A 之後會在 repo 裡的檔案＝受版控 ∪（未追蹤且未被 .gitignore 忽略）。
    用這個而不是單純的 `git ls-files`，是為了讓還沒 commit 的新檔（例如本檔自己）也進沙箱。"""
    p = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        sys.exit("git ls-files 失敗：%s" % p.stderr.decode("utf-8", "replace"))
    return sorted({n.decode("utf-8") for n in p.stdout.split(b"\0") if n})


def make_sandbox(files, dest):
    """把 index 裡的檔案重造到 dest。

    **symlink 必須原樣重建，不能跟隨**：`Path.is_file()` 對 dangling symlink
    回 False（整個被略過），`shutil.copy2` 對活的 symlink 會複製目標內容、
    把 mode 120000 變成 100644。兩者都使沙箱與 index 不等價——PR #81 第五輪
    的 symlink 反例在跟隨式沙箱裡不但重現不出來，還會把正確的檢查器誤判成
    錯誤（審查者 PR #83 第一輪實測：來源 exit 0、沙箱 exit 1）。
    """
    for rel in files:
        src = REPO / rel
        dst = dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():           # mode 120000：照抄 target 字串，不跟隨
            os.symlink(os.readlink(src), dst)
            continue
        if not src.is_file():          # 已刪除但還在 index 的，跳過
            continue
        shutil.copy2(src, dst)
    for args in (["git", "-c", "init.defaultBranch=main", "init", "-q"],
                 ["git", "add", "-A"]):
        p = subprocess.run(args, cwd=dest, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
        if p.returncode != 0:
            sys.exit("沙箱建置失敗（%s）：%s"
                     % (" ".join(args), p.stdout.decode("utf-8", "replace")))


# ── 突變工具 ──────────────────────────────────────────────────────
def edit(root, rel, fn):
    path = root / rel
    text = path.read_text(encoding="utf-8")
    new = fn(text)
    if new == text:
        sys.exit("突變沒有改到任何東西：%s（檔案內容和本測試的假設不符）" % rel)
    path.write_text(new, encoding="utf-8")


def edit_bytes(root, rel, fn):
    """位元組層級的突變。`edit()` 走 str（utf-8 進、utf-8 出），造不出非 UTF-8 的輸入。"""
    path = root / rel
    raw = path.read_bytes()
    new = fn(raw)
    if new == raw:
        sys.exit("突變沒有改到任何東西：%s（檔案內容和本測試的假設不符）" % rel)
    path.write_bytes(new)


def remove(root, rel):
    """從沙箱的 index 與工作樹一起刪掉。檢查器認的是 `git ls-files`，只刪工作樹等於沒刪。
    沙箱沒有 commit，index 相對 HEAD 全是新檔，`git rm` 不加 `-f` 會拒絕。"""
    if not (root / rel).is_file():
        sys.exit("要刪的檔案不存在：%s（repo 內容和本測試的假設不符）" % rel)
    p = subprocess.run(["git", "rm", "-q", "-f", "--", rel], cwd=root,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if p.returncode != 0:
        sys.exit("git rm %s 失敗：%s" % (rel, p.stdout.decode("utf-8", "replace")))


def drop_line(text, needle):
    return "\n".join(l for l in text.split("\n") if needle not in l)


def replace_first(text, old, new):
    return text.replace(old, new, 1)


def append(text, extra):
    return text + extra


# issue #91 缺口 11：非 UTF-8 的受版控 .md 曾被 read_text 的 die() 判成 exit 2
# （＝檢查器無法執行）。它是**內容**問題，必須是 exit 1。修正前本案會以 exit 2 失敗。
BAD_BYTE = b"\xff"          # UTF-8 裡不可能出現的起始位元組（0xff 不在任何合法序列裡）


def mut_encoding(root):
    """受版控的 .md 內容不是合法 UTF-8。

    選 devflow/seats/approver.md 是照抄 issue #91 裡 orchestrator 的重現路徑
    （「在 devflow/seats/ 放一個非 UTF-8 的 .md」）。附加在檔尾、單獨一行，
    除了編碼之外不觸發別的關卡——本案才驗得了「exit 1 只由 encoding 造成」。"""
    edit_bytes(root, "devflow/seats/approver.md",
               lambda b: b + b"\n\xe9\x9d\x9e UTF-8 " + BAD_BYTE + b"\n")


def ok_encoding_bom(root):
    """帶 UTF-8 BOM 的 .md 仍是合法 UTF-8，不得誤擋。

    檢查器讀檔用 utf-8-sig（BOM 對 GitHub 的算繪無影響，不該讓 frontmatter 偵測失效），
    這一案鎖住它：BOM 被剝掉、內容一字不差，所有關卡照樣通過。"""
    edit_bytes(root, "devflow/seats/approver.md", lambda b: b"\xef\xbb\xbf" + b)


def mut_encoding_fail_closed(root):
    """同一個檔案又是非 UTF-8、又有沒關閉的 fence。

    鎖住 AC-1 的 fail closed：解不開的檔案**不得**從其他關卡的定義域裡摘掉。
    若哪天有人把 read_text 改回「解不開就跳過這個檔」，encoding 仍會 ❌、但 fence
    那條會消失，本案就會以「❌ 只有 1 條」失敗。"""
    edit_bytes(root, "README.md",
               lambda b: b + b"\n\xe9\x9d\x9e UTF-8 " + BAD_BYTE
                         + b"\n\n```\n\xe6\xb2\x92\xe6\x9c\x89\xe9\x97\x9c\xe9\x96\x89\n")


def mut_d2(root):
    """入口區塊只剩 begin，沒有 end。"""
    edit(root, "CLAUDE.md", lambda t: drop_line(t, "<!-- devflow:end -->"))


def mut_i5(root):
    """devflow.yml 的 implementer_filler 投影與 seats.implementer.filler 不一致。"""
    edit(root, "devflow.yml",
         lambda t: replace_first(t, "implementer_filler: claude-code",
                                 "implementer_filler: codex"))


# 不硬編當下版號（issue #125）：寫死 `version: 1.3.2.0` 的話，規則本體一 bump
# 這個突變就打不到，`version` 的應擋案例會變成沒突變到。抓 frontmatter 那一行的
# 四碼、砍掉最後一碼——版號怎麼變都命中，真的沒命中時 `edit()` 會中止整份測試。
VERSION_4 = re.compile(r"^(version: \d+\.\d+\.\d+)\.\d+$", re.MULTILINE)


def mut_version(root):
    """規則本體的 frontmatter version 從四碼變三碼。"""
    edit(root, "devflow/WORKFLOW.md",
         lambda t: VERSION_4.sub(r"\1", t, count=1))


def mut_fence(root):
    """留一個沒有關閉的 fenced code block。"""
    edit(root, "README.md", lambda t: append(t, "\n```\n沒有關閉的 fence\n"))


def mut_table(root):
    """對照表表頭缺「面向」欄。"""
    edit(root, "devflow/forges/github.md",
         lambda t: replace_first(t, "| 面向 |", "| 項目 |"))


# issue #90 的突變一律用 append，不用 replace_first：插入的文字不會搶走錨點。
# 對照資料用 raw HTML 寫（缺口 2 的原反例，逐字取自 issue #90）。
RAW_HTML_TABLE = ("<table><tr><td>面向</td><td>值</td><td>狀態</td></tr>"
                  "<tr><td>x</td><td>y</td><td>亂寫</td></tr></table>")


def mut_table_raw_html(root):
    """對照表檔附加 raw HTML 表格（issue #90 缺口 2）。"""
    edit(root, "devflow/orchestrators/paperclip.md",
         lambda t: append(t, "\n" + RAW_HTML_TABLE + "\n"))


def mut_table_short_row(root):
    """資料列缺狀態格（issue #90 缺口 3）：markdown-it 會把它補成 4 格、狀態格為空字串。
    codex.md 的最後一行是本機表的資料列，附加在檔尾才會接進同一張表；前面若多一個空行，
    這一行就只是段落，本案會以 exit 0 失敗而不是靜默通過。"""
    edit(root, "devflow/coders/codex.md",
         lambda t: append(t, "| 短列 | coordinator |\n"))


def mut_table_blank_status(root):
    """狀態格有寫但只有空白。欄數與本機表相同，排除「短列」那條路徑。附加位置同上。"""
    edit(root, "devflow/coders/codex.md",
         lambda t: append(t, "| 空白狀態 | — | 值 |   |\n"))


def ok_table_html_in_fence(root):
    """code fence 裡的 `<table>` 是示範（fence token），不是 html_block，不擋。"""
    edit(root, "devflow/orchestrators/paperclip.md",
         lambda t: append(t, "\n```html\n" + RAW_HTML_TABLE + "\n```\n"))


def ok_table_html_attr(root):
    """引號屬性值裡的 `<table` 是字串內容，不是標籤——GitHub 只渲染成一個 div。
    掃描前挖空引號字串（審查者 PR #92 第一輪反例）。"""
    edit(root, "devflow/orchestrators/paperclip.md",
         lambda t: append(t, '\n<div data-x="<table">x</div>\n'))


def ok_table_html_comment(root):
    """HTML 註解裡的 `<table>` 不渲染，同樣挖空後再掃。"""
    edit(root, "devflow/orchestrators/paperclip.md",
         lambda t: append(t, "\n<!-- <table> -->\n"))


def ok_table_html_attr_name(root):
    """`<table` 出現在屬性名或未閉合的引號裡——標籤內部一律不渲染成表格
    （審查者 PR #92 第二輪實查 GitHub renderer）。"""
    edit(root, "devflow/orchestrators/paperclip.md",
         lambda t: append(t, '\n<div data-<table="x">x</div>\n'))


def mut_table_quoted_text(root):
    """標籤外的引號是文字內容，不是屬性——不得拿它配對而把中間真正的
    `<table>` 吃掉（審查者 PR #92 第二輪的漏放反例）。"""
    edit(root, "devflow/orchestrators/paperclip.md",
         lambda t: append(t, '\n<div>\n"before\n' + RAW_HTML_TABLE + '\nafter"\n</div>\n'))


def mut_table_script(root):
    """`<script>` 內的 `<table>`——HTMLParser 預設把 script/style 內容當 raw text
    而看不到，但 GitHub 會清掉 script 標籤、裡面的表格照樣渲染（審查者 PR #92
    第四輪實測）。set_cdata_mode 已被覆寫成 no-op，這一案鎖住它。"""
    edit(root, "devflow/orchestrators/paperclip.md",
         lambda t: append(t, "\n<script>" + RAW_HTML_TABLE + "</script>\n"))


TABLE_INLINE_MULTILINE = "\nprefix <span>\nsecond line\nthird " + RAW_HTML_TABLE + " tail\n"
# 同上，但 `<table>` 前面的換行藏在多行 code span 裡（parser 把它轉成空格，沒有 token
# 帶著它）——#92 從兄弟 token 反推行號的做法在這裡少算一行（issue #100 本地實測）。
TABLE_INLINE_CODESPAN = "\nprefix `多行\ncode span` 之後 " + RAW_HTML_TABLE + " tail\n"


def paperclip_table_at(extra):
    """extra 附加到 paperclip.md 之後，`table` 對那個 `<table>` 的明細應有的樣子。"""
    return ("devflow/orchestrators/paperclip.md:%d 有 raw HTML 的 <table>"
            % appended_line("devflow/orchestrators/paperclip.md", extra, "<table>"))


def mut_table_inline_multiline(root):
    """多行 inline 裡的 `<table>`——`prefix <span>` 開頭使這段落成 html_inline 而非
    html_block。行號要是真實行號（審查者 PR #92 第五輪：真實 22 行曾報成 20）；
    期望的明細帶行號，鎖住這一點（issue #100 起）。"""
    edit(root, "devflow/orchestrators/paperclip.md",
         lambda t: append(t, TABLE_INLINE_MULTILINE))


def mut_table_inline_codespan(root):
    """`<table>` 前面的換行藏在 code span 裡（見 TABLE_INLINE_CODESPAN）。"""
    edit(root, "devflow/orchestrators/paperclip.md",
         lambda t: append(t, TABLE_INLINE_CODESPAN))


def ok_r9_prose(root):
    """表格外的敘述句提到舊詞——`R9` 管的是狀態欄，沒有規定散文怎麼寫。
    討論用詞沿革、引用舊格式、遷移說明都會提到舊詞（審查者 PR #95 反例）。"""
    edit(root, "devflow/orchestrators/paperclip.md",
         lambda t: append(t, "\n> 歷史：本表原本用 `✅ 實測`，#94 改為 `✅ 可用`。\n"))


def ok_dupid_deep_heading(root):
    """更深的同形標題（`### 3. 補充說明（R）`）是子節不是新家族——把它當家族節
    會讓子節裡的舉例被判成重複定義（審查者 PR #97 第一輪反例）。"""
    edit(root, "devflow/WORKFLOW.md",
         lambda t: append(t, "\n### 3. 補充說明（R）\n\n- `R3` 這裡只是舉例\n"))


def mut_link(root):
    """相對連結指向不存在的路徑。"""
    edit(root, "README.md",
         lambda t: append(t, "\n[壞掉的連結](does/not/exist.md)\n"))


# ── link：raw HTML 的連結（issue #100）──────────────────────────────────
# 突變一律以一個空行開頭附加在 README.md 檔尾（同 mut_link），自成一個區塊。5a–5e 的寫法
# 逐字取自 issue #100 的表；orchestrator 當時附加在 forges/github.md，這裡換成和既有 `link`
# 案例同一個錨點。
# 5a 在 issue 裡記成「行首 → html_block」，本地實測不是：`a` 不是 type 6 的區塊標籤，
# 標籤後面又接了文字、不合 type 7，於是整行是段落、`<a …>` 是 html_inline。html_block
# 那一路由 5c（`<img>` 單獨一行，type 7）與 html-block 案（`<div>` 包住，type 6）走到。
#
# 期望的明細帶**行號**（AC-1／AC-4）。行號由本檔在原文上自己算（檢查器之外的 oracle），
# 不寫死：README 改了行數，期望跟著變。
def appended_line(rel, extra, needle):
    """extra 附加到 rel 檔尾之後，needle 最後一次出現的行號（1-based）。"""
    text = (REPO / rel).read_text(encoding="utf-8") + extra
    return text.count("\n", 0, text.rindex(needle)) + 1


def readme_link(extra, target, suffix=""):
    """extra 附加到 README.md 之後，`link` 對 target 那一條明細應有的樣子。"""
    return "README.md:%d -> %s%s" % (appended_line("README.md", extra, target), target, suffix)


LINK_BROKEN = "有相對連結指向不存在或 repo 之外的路徑"
HTML_LINK_5A = '\n<a href="does/not/exist.md">壞</a>\n'
HTML_LINK_5B = '\n前綴 <a href="does/not/exist.md">壞</a>\n'
HTML_LINK_5C = '\n<img src="does/not/exist.png">\n'
HTML_LINK_5D = '\n<a href=".git/config">壞</a>\n'
HTML_LINK_5E = '\n看 <a href="../../etc/passwd">這</a>\n'
HTML_LINK_BLOCK = '\n<div>\n說明\n<a href="does/not/exist.md">壞</a>\n</div>\n'
# 同一段落裡，壞連結前面有兩個「不在任何 token 裡」的換行：code span 內的換行（parser
# 轉成空格）、連結目的地前的換行（被 link token 吞掉）。#92 的反推法在這裡少算兩行。
HTML_LINK_LINE = ('\n前 `多行\ncode span` 與 [連結](\nREADME.md) 之後\n'
                  '看 <a href="does/not/exist.md">這</a>\n')


def mut_link_html_a(root):
    """5a：`<a href>` 在行首，指向不存在的路徑（段落裡的 html_inline）。"""
    edit(root, "README.md", lambda t: append(t, HTML_LINK_5A))


def mut_link_html_inline(root):
    """5b：`<a href>` 前面有裸文字（html_inline，被文字切成三個 child）。"""
    edit(root, "README.md", lambda t: append(t, HTML_LINK_5B))


def mut_link_html_img(root):
    """5c：`<img src>` 單獨一行（html_block，type 7）。"""
    edit(root, "README.md", lambda t: append(t, HTML_LINK_5C))


def mut_link_html_git_config(root):
    """5d：指向 `.git/config`——runner 上存在、不受版控。缺口 6 的修正（git ls-files 當
    oracle）在 raw HTML 這一路也要成立，不能另用 os.path.exists 讓它復活。"""
    edit(root, "README.md", lambda t: append(t, HTML_LINK_5D))


def mut_link_html_escape(root):
    """5e：`../../etc/passwd` 逃出 repo，前面有裸文字（html_inline）。"""
    edit(root, "README.md", lambda t: append(t, HTML_LINK_5E))


def mut_link_html_block(root):
    """`<a href>` 在多行 html_block 的第三行（type 6，`<div>` 包住）——行號＝區塊起點＋
    HTMLParser 給的相對行，不是區塊的第一行。"""
    edit(root, "README.md", lambda t: append(t, HTML_LINK_BLOCK))


def mut_link_html_line(root):
    """AC-4：html_inline 前面有 token 看不到的換行，行號仍要是真實行號
    （見 HTML_LINK_LINE 的註解；#92 的反推法會少算兩行）。"""
    edit(root, "README.md", lambda t: append(t, HTML_LINK_LINE))


def ok_link_html_in_fence(root):
    """code fence 裡的 raw HTML 連結是示範（fence token），不進 HTML 判定。"""
    edit(root, "README.md",
         lambda t: append(t, "\n```html" + HTML_LINK_5A + HTML_LINK_5C.lstrip() + "```\n"))


def ok_link_html_in_code_span(root):
    """code span 裡的 raw HTML 連結同樣是示範（code_inline token）。"""
    edit(root, "README.md",
         lambda t: append(t, '\n寫法：`<a href="does/not/exist.md">壞</a>`、'
                             '`<img src="does/not/exist.png">`\n'))


def ok_link_html_comment(root):
    """HTML 註解裡的 `<a href>`／`<img src>` 不渲染，HTMLParser 也不把它當 start tag
    （同 table:html-comment）。區塊與行內各一。"""
    edit(root, "README.md",
         lambda t: append(t, '\n<!-- <a href="does/not/exist.md">壞</a> -->\n\n'
                             '說明 <!-- <img src="does/not/exist.png"> --> 結尾\n'))


def ok_link_html_valid(root):
    """合法的 raw HTML 連結，區塊與行內各一段。它們走的是和 markdown 連結**同一個**判定
    迴圈，所以 scheme、純 fragment、repo 根相對、query／fragment 的切法都和 markdown 那一路
    一樣不擋（AC-3：raw HTML 若另寫一套判定，這一案最先誤擋）。另含 raw HTML 才有的兩種：
    屬性值前後的空白（瀏覽器照 URL 標準剝掉）、沒有 href 的 `<a name>`。"""
    edit(root, "README.md",
         lambda t: append(t,
                          '\n<p><a href="devflow/WORKFLOW.md">規則</a>、'
                          '<a href="https://example.com/x">外部</a>、<a href="#top">錨點</a>、'
                          '<a href="/devflow/WORKFLOW.md">根相對</a>、'
                          '<img src="scripts/devflow_checks.py"></p>\n\n'
                          '看 <a href="README.md?plain=1#x">帶 query</a>、'
                          '<a href=" README.md ">前後空白</a>、<a name="x">沒有 href</a>\n'))


# ── link：srcset 承載的連結（issue #102）─────────────────────────────────
# srcset 的值是「候選 URL ＋ descriptor」的串，檢查器切出每個候選的 URL、各自送進同一個
# 判定迴圈。錨點同上（README.md 檔尾、空行開頭）。`<picture>`／`<img>` 開頭、後面還有東西
# 的那一行是段落裡的 html_inline；`<picture>` 不是 type 6 的區塊標籤。
SRCSET_SOURCE = '\n<picture><source srcset="does/not/exist.png"><img src="README.md"></picture>\n'
SRCSET_IMG = '\n<img srcset="does/not/exist.png 2x" src="README.md">\n'
# 三個候選只有中間那個壞，而且帶 descriptor：明細要是**那一個 URL**，不是整串、也不帶
# `800w`（期望以換行收尾，見 CASES 那一列的註解）。
SRCSET_MULTI = ('\n<img srcset="README.md 480w, does/not/exist.png 800w, '
                'devflow/WORKFLOW.md 1200w" src="README.md">\n')
# 沒有空白的逗號**不**分隔候選：規格裡 `README.md,devflow/WORKFLOW.md` 是一個 URL，
# 瀏覽器照原樣去抓，讀者看到壞圖。按逗號切的實作會把它切成兩個存在的路徑而放行。
SRCSET_NO_SPACE = '\n<img srcset="README.md,devflow/WORKFLOW.md">\n'
# NBSP 不是規格的 ASCII whitespace：`README.md` 後面緊接的 NBSP 是 URL 的一部分（URL 標準
# 的前處理也只剝 U+0020 以下），瀏覽器去抓 `README.md%C2%A0`。拿 str.isspace() 切的實作
# 會切出 `README.md` 而放行。
SRCSET_NBSP = '\n<img srcset="README.md  1x">\n'
# 行號：壞候選前面有兩個「不在任何 token 裡」的換行（同 HTML_LINK_LINE）——srcset 切出的
# URL 用的是同一個 HTML_POS 機制，報 `<img` 的真實行。
SRCSET_LINE = ('\n前 `多行\ncode span` 與 [連結](\nREADME.md) 之後\n'
               '看 <img srcset="README.md 1x, does/not/exist.png 2x" src="README.md">\n')


def mut_link_srcset_source(root):
    """`<picture><source srcset>` 指向不存在的路徑，fallback 的 `<img src>` 合法——
    GitHub 會保留並拿它選圖（issue #102 的缺口，PR #101 第一輪審查以 renderer 實測）。"""
    edit(root, "README.md", lambda t: append(t, SRCSET_SOURCE))


def mut_link_srcset_img(root):
    """`<img srcset>` 的候選壞、`src` 合法：兩者都要驗（AC-2）。"""
    edit(root, "README.md", lambda t: append(t, SRCSET_IMG))


def mut_link_srcset_multi(root):
    """多個候選其中一個壞（見 SRCSET_MULTI）。"""
    edit(root, "README.md", lambda t: append(t, SRCSET_MULTI))


def mut_link_srcset_no_space(root):
    """逗號後沒有空白（見 SRCSET_NO_SPACE）。"""
    edit(root, "README.md", lambda t: append(t, SRCSET_NO_SPACE))


def mut_link_srcset_nbsp(root):
    """URL 後面接 NBSP（見 SRCSET_NBSP）。"""
    edit(root, "README.md", lambda t: append(t, SRCSET_NBSP))


def mut_link_srcset_line(root):
    """行號（見 SRCSET_LINE）。"""
    edit(root, "README.md", lambda t: append(t, SRCSET_LINE))


def ok_link_srcset_valid(root):
    """合法的 srcset，不得誤擋。逐項對應 AC-1 的切法要求：
      - descriptor：`1x`／`2x`、浮點 `1.5x`、`480w`；單一候選沒有 descriptor。
      - **URL 含逗號**：`README.md?a=1,2 480w`——按逗號切會切出 `2 480w` 這種不是 URL 的段而誤擋。
      - data: URI 裡的逗號（有 scheme，判定迴圈本來就不驗；按逗號切會切出沒有 scheme 的後半段）。
      - 候選之間的空白是 space／tab／換行，URL 直接以逗號收尾（`README.md,`）。
    `<picture><source>` 與 `<img>` 各有，`<img>` 同時帶合法的 src。"""
    edit(root, "README.md",
         lambda t: append(t,
                          '\n<img srcset="README.md 1x, devflow/WORKFLOW.md 2x, '
                          'scripts/devflow_checks.py 1.5x" src="README.md">\n\n'
                          '<picture><source srcset="README.md?a=1,2 480w, '
                          'devflow/WORKFLOW.md 800w"><img src="README.md"></picture>\n\n'
                          '<img srcset="data:image/png;base64,iVBORw0KGgo= 1x,'
                          '\n\tREADME.md,\tdevflow/WORKFLOW.md 2x">\n\n'
                          '<img srcset="README.md">\n'))


def ok_link_srcset_in_code(root):
    """code fence／code span 裡的 srcset 是示範（fence／code_inline token），不進 HTML 判定。"""
    edit(root, "README.md",
         lambda t: append(t, "\n```html" + SRCSET_SOURCE + SRCSET_MULTI.lstrip() + "```\n\n"
                             '寫法：`<img srcset="does/not/exist.png 1x, x.png 2x">`\n'))


# ── dupid：規則 ID 唯一定義（issue #96 AC-4）───────────────────────────
# 突變一律附加在 devflow/WORKFLOW.md 檔尾。檔案最後一行是 `- `D4` …`，也就是
# 第 13 節「文檔（D）」的清單項——直接附加的清單項會接進同一個清單、落在同一節下，
# 家族是 `D`。要造真重複就用 `D` 家族的 ID；要造「不算定義」的反例就換節或換行首。
def mut_dupid(root):
    """真正的重複定義：`D1` 在自己的家族節裡被定義第二次。

    三個條件全部成立（在帶家族標記的節下、前綴＝家族、行首 `- `），所以它就是定義——
    這正是 dupid 要擋的東西。附加的說明裡不放別的 ID 形狀 code span，`refs` 才不會
    跟著冒出第二條 ❌。"""
    edit(root, "devflow/WORKFLOW.md",
         lambda t: append(t, "- `D1` 又寫了一次，這是真的重複定義。\n"))


def ok_dupid_appendix(root):
    """假陽性一：附錄用清單解釋既有規則（「- `R3` 常被誤讀成…」）。

    「附錄：常見誤讀」的節標題沒有 `（<家族>）` 標記，該節不產生任何定義
    ——條件 (1) 不成立，`R3` 不會被算成第二次定義。"""
    edit(root, "devflow/WORKFLOW.md",
         lambda t: append(t, "\n## 附錄：常見誤讀\n\n"
                             "- `R3` 常被誤讀成「審查者要自己重跑測試」，其實不是。\n"))


def ok_dupid_index(root):
    """假陽性二：加一節「規則索引」把 ID 列一遍。

    同樣沒有家族標記（條件 1），而且列進來的 `I1`、`I2` 和該節也談不上家族相符
    （條件 2）——兩個條件各自都足以排除，索引不會讓每個 ID 都變成重複定義。"""
    edit(root, "devflow/WORKFLOW.md",
         lambda t: append(t, "\n## 規則索引\n\n"
                             "- `I1` 一張 issue 一個任務\n"
                             "- `I2` coder 不在主 checkout\n"))


def ok_dupid_blockquote(root):
    """假陽性三：blockquote 引述既有條文。

    這一案刻意落在**家族相符**的節裡（檔尾＝第 13 節，引的也是 `D1`），條件 (1)(2)
    都成立——擋下它的只有條件 (3)：行首是 `>` 不是 `- `。判準若哪天改回看 token 而
    不看行首，本案就會以 exit 1 失敗。"""
    edit(root, "devflow/WORKFLOW.md",
         lambda t: append(t, "\n> - `D1` 一個來源、兩種投影：規範只有一份，指南引用它。\n"))


# ── dupid：ID 之前有裝飾性內容（issue #98）─────────────────────────────
# 缺口 7 及其同族：#96 的判準逐個跳過開標記，跳過清單漏了 link_close、image，`~~` 更
# 根本不是 token——五種前綴寫法四種漏認，於是「重複定義可以靠加個空連結繞過」。
# 前四個應擋案例各對應實測表的一列（判準改成「ID 前面有沒有裸文字」後全部認得出來），
# 第五個（link-newline）鎖的是條件 (3) 的錨點——裝飾裡有換行時，ID 不在本項的第一行上。
# 連結一律指 `#…` fragment、圖片一律指有 scheme 的 URL：兩者都不是 repo 路徑，
# `link` 那一關會跳過，exit 1 才只由 dupid 造成。說明文字裡不放別的 ID 形狀 code span。
def mut_dupid_empty_link(root):
    """缺口 7 的原始反例：空連結之後的重複定義（`- [](#x) `D1` …`）。

    舊判準取到的「第一個內容」是 link_close，不是 code_inline，於是整項不算定義、
    `D1` 的第二次定義沒被看見。"""
    edit(root, "devflow/WORKFLOW.md",
         lambda t: append(t, "- [](#dup) `D1` 空連結後的重複定義。\n"))


def mut_dupid_text_link(root):
    """有文字的連結之後的重複定義（`- [看這裡](#x) `D2` …`）。

    舊判準取到的是連結文字那個 text token。新判準看層級：連結文字比 code span 深一層
    （lv1 > lv0），是已經關掉的裝飾，不是裸文字。"""
    edit(root, "devflow/WORKFLOW.md",
         lambda t: append(t, "- [看這裡](#dup) `D2` 有字連結後的重複定義。\n"))


def mut_dupid_image(root):
    """圖片之後的重複定義（`- ![](x.png) `D3` …`）。

    舊判準取到的是 image token——它既不在跳過清單裡，也不是 code_inline。"""
    edit(root, "devflow/WORKFLOW.md",
         lambda t: append(t,
                          "- ![](https://example.com/x.png) `D3` 圖片後的重複定義。\n"))


def mut_dupid_strike(root):
    """刪除線之後的重複定義（`- ~~舊~~ `D4` …`）。

    這一列不是「跳過清單缺項」：commonmark preset 根本不認 `~~`，整段留成字面文字。
    解析器對齊 GFM（`MD` 的 `strikethrough`）之後才變成 s_open／內文／s_close，
    內文比 code span 深一層，判準自然放行。解析器若被改回不認 `~~`，本案會以 exit 0 失敗。"""
    edit(root, "devflow/WORKFLOW.md",
         lambda t: append(t, "- ~~舊~~ `D4` 刪除線後的重複定義。\n"))


def mut_dupid_link_newline(root):
    """裝飾裡有換行：`- [](#x)` 的下一行才寫 ID。

    ID 前面既然可以有裝飾，裝飾裡就可以有換行——那時 ID 落在縮排的續行上。條件 (3)
    若拿「ID 所在的行」判行首，這一項會被判成不是定義（又一個繞過）；改看
    list_item_open 自己那一行才擋得下來。"""
    edit(root, "devflow/WORKFLOW.md",
         lambda t: append(t, "- [](#dup)\n  `D1` 換行之後才寫的重複定義。\n"))


# ── dupid：裝飾與 ID 各在自己的容器裡（PR #99 第一輪審查）─────────────────
# 下面兩案鎖的是 `leading_code_span()` 從「比 `level` 深度數字」改成「比容器堆疊前綴」
# 的那一步。`level` 不帶容器身分：容器關掉之後深度會被重用，於是已關閉的裝飾內文
# （`[裝飾]` 的文字、`~~舊~~` 的內文）與包住 ID 的另一個容器內文（`**…**`、`*…*`）
# 碰巧同為 lv1，被當成「與 ID 同層的裸文字」而**漏認**真定義。
# 方向是漏認不是誤認：判準若退回比 level，這兩案會以 exit 0 失敗——也就是
# 「把空連結＋裸 ID 換成連結＋粗體 ID 就能藏住重複定義」那條必需關卡的繞過路徑。
def mut_dupid_link_strong(root):
    """有文字的連結 ＋ 粗體包住的 ID（`- [裝飾](#x) **`D1`** …`）。

    「裝飾」在 link 容器裡、ID 在 strong 容器裡，兩個容器是 sibling（link 已關閉）。
    堆疊快照 `(link,)` 不是 `(strong,)` 的前綴 → 裝飾，不是裸文字 → 是定義。"""
    edit(root, "devflow/WORKFLOW.md",
         lambda t: append(t, "- [裝飾](#dup) **`D1`** 連結後粗體 ID 的重複定義。\n"))


def mut_dupid_strike_em(root):
    """刪除線 ＋ 斜體包住的 ID（`- ~~舊~~ *`D2`* …`）。

    同一個形狀換一組容器：`(s,)` 不是 `(em,)` 的前綴。這一案同時仍依賴解析器認得
    `~~`（`MD` 的 `strikethrough`）——解析器若被改回不認，`~~舊~~` 整段留成字面文字，
    那就成了與 ID 同層的裸文字，本案會以 exit 0 失敗。"""
    edit(root, "devflow/WORKFLOW.md",
         lambda t: append(t, "- ~~舊~~ *`D2`* 刪除線後斜體 ID 的重複定義。\n"))


# AC-3 的散文：三案都刻意落在**家族相符**的節裡（檔尾＝第 13 節，引的也是 D 家族），
# 條件 (1)(2)(3) 全部成立——擋下它們的只有「ID 前面有裸文字」。判準若退回「取第一個
# code span、不管前面是什麼」，這三案會各冒出一條 dupid ❌ 而以 exit 1 失敗。
def ok_dupid_prose_ref(root):
    """散文一：ID 出現在句子中間（「- 這條規則參考了 `D1` 的做法」）。"""
    edit(root, "devflow/WORKFLOW.md",
         lambda t: append(t, "- 這條規則參考了 `D1` 的做法，這一項不是定義。\n"))


def ok_dupid_prose_list(root):
    """散文二：一句話列舉兩個 ID（「- 見 `D2` 與 `D3`」）。"""
    edit(root, "devflow/WORKFLOW.md",
         lambda t: append(t, "- 見 `D2` 與 `D3`，這一項不是定義。\n"))


def ok_dupid_prose_in_strong(root):
    """散文三：整句包在粗體裡（「- **注意 `D1` 在粗體裡**」）。

    這一案鎖住判準的「同層或更外層」那半句：「注意 」和 ID 同在 strong 容器裡，
    堆疊快照相等。只比頂層有沒有裸文字的實作會放它過去，本案就會以 exit 1 失敗。"""
    edit(root, "devflow/WORKFLOW.md",
         lambda t: append(t, "- **注意 `D1` 在粗體裡**，這一項不是定義。\n"))


def ok_dupid_task_list(root):
    """GFM task-list（`- [x] `D1` …`）——**斷言的是現況行為，而且它是一個已知漏認**。

    裁決與理由（PR #99 第二輪，F2 第三案）：

      * 現況：`MD` 只啟用了 `table` 與 `strikethrough`，**沒有** task-list。parser
        看不到 checkbox，`[x] ` 整段留成頂層的字面文字——那就是與 ID 同層的裸文字，
        於是本項不算定義，重複的 `D1` 不報，exit 0。本案因此放在 PASSING。
      * 這**不是判準正確**，是 issue #98 檔頭記的那一類假陰性：GitHub 認得
        task-list、讀者看到的是「☑ 後面接 `D1`」＝這一項在講 `D1`，檢查器卻看成散文。
        所以這種寫法仍藏得住重複定義。它與 `==x==` 那一類不同——`==x==` GitHub 也
        算繪成文字，兩邊一致；task-list 是**兩邊不一致**，方向是漏認。
      * 為什麼本輪不修：修法只有「讓 parser 也認得 task-list」一條，而 markdown-it-py
        本體**沒有**這個規則（`md.get_all_rules()` 實跑：core／block／inline／inline2
        四組裡沒有任何含 task 的規則），要引入 `mdit_py_plugins` 這個**新相依**
        （`PINS` 要加、CI 的準備 step 跟著動）。那超出本輪的 write scope，也該由人
        裁決要不要擴充相依，不由檢查器自己決定（`G2` 的同一個道理）。
      * 為什麼仍要留這個案例：它是**絆線**。哪天有人啟用了 task-list，`[x] ` 不再是
        字面文字，這一項就會被認成定義、本案變成 exit 1 而失敗，逼人當場把它從 PASSING
        移到 CASES（應擋）並改寫檔頭那段敘述，而不是讓判準悄悄改變。反過來，判準若被
        改鬆（不看頂層裸文字），它也會失敗。兩個方向都有人看著。
        （「啟用後會變 exit 1」是**推論、未實跑**——本機沒有 mdit_py_plugins。但絆線
        本身不依賴這個推論正確：行為只要一改，本案就失敗。）
    """
    edit(root, "devflow/WORKFLOW.md",
         lambda t: append(t, "- [x] `D1` task-list 後的重複定義（目前漏認，見 docstring）。\n"))


# ── r9：狀態欄取 R9 三值之一（issue #94 AC-4）─────────────────────────
# 四個應擋案例的突變一律附加在 devflow/coders/codex.md 檔尾——最後一行是本機表的
# 資料列，附加的列會接進同一張表（錨點同 mut_table_short_row）。每列都是四格、
# 狀態格非空，所以 `table` 的形狀判定照樣通過：exit 1 只會由 r9 造成。
# 舊詞那一案的 `✅ 實測` 落在表格的資料列上，不會另外觸發「敘述句仍用二值用語」
# ——那條只掃合格表的資料列以外的行。
def mut_r9_old_word(root):
    """舊的二值用語 `✅ 實測`：issue #94 之前七個對照表檔的寫法，不是 R9 的三值。"""
    edit(root, "devflow/coders/codex.md",
         lambda t: append(t, "| 舊詞 | — | 值 | ✅ 實測 2026-09-11（驗證方式：…） |\n"))


def mut_r9_no_sep(root):
    """標記與詞之間少了分隔符（`✅可用`）：不是 `✅ 可用`，沒取到三值。"""
    edit(root, "devflow/coders/codex.md",
         lambda t: append(t, "| 黏著 | — | 值 | ✅可用 |\n"))


def mut_r9_glued(root):
    """三值之後黏成另一個詞（`✅ 可用性佳`）：R9_SEPS 那條的反例。
    startswith 會通過，要看下一個字元是不是分隔符才擋得下來——只驗 startswith
    的實作會放它過去，本案鎖住這一點。"""
    edit(root, "devflow/coders/codex.md",
         lambda t: append(t, "| 黏著詞 | — | 值 | ✅ 可用性佳 |\n"))


def mut_r9_other_word(root):
    """三值之外的詞（`✅ 完成`）：標記對、詞不對。"""
    edit(root, "devflow/coders/codex.md",
         lambda t: append(t, "| 別的詞 | — | 值 | ✅ 完成 |\n"))


def mut_tables_forge(root):
    """刪掉 `forge: github` 指名的 devflow/forges/github.md。"""
    remove(root, "devflow/forges/github.md")


def mut_tables_coder(root):
    """刪掉 `seats.reviewer.filler: codex` 指名的 devflow/coders/codex.md。"""
    remove(root, "devflow/coders/codex.md")


def mut_tables_filler(root):
    """`seats.coordinator.filler` 改成 coders/、orchestrators/ 都沒有對照表的工具名。
    改 coordinator 不改 implementer：後者會連帶讓 i5 ❌，這個案例就不只觸發目標項。"""
    edit(root, "devflow.yml",
         lambda t: replace_first(t, "filler: hermes", "filler: no-such-tool"))


def mut_tables_no_forge(root):
    """devflow.yml 缺 `forge`：推導不出來要擋，不是跳過（issue #87 AC-3）。"""
    edit(root, "devflow.yml", lambda t: drop_line(t, "forge: github"))


def ok_tables_forge_gitlab(root):
    """`forge` 改成 gitlab 後刪 github.md：它不再是必需的。"""
    edit(root, "devflow.yml",
         lambda t: replace_first(t, "forge: github", "forge: gitlab"))
    remove(root, "devflow/forges/github.md")


def ok_tables_coordinator_omitted(root):
    """整個省略 `coordinator`（第 0 節：＝human）後刪 hermes.md：它不再是必需的。"""
    edit(root, "devflow.yml",
         lambda t: drop_line(drop_line(t, "filler: hermes"), "  coordinator:"))
    remove(root, "devflow/orchestrators/hermes.md")


# 「應擋」案例：每個關卡至少一個。
#   name    = 案例名（印出用；同一關卡有多個案例時以 `關卡:說明` 區分）
#   gate    = 目標關卡，以 DEVFLOW_GATE_<KEY>=1 打開
#   mutate  = 怎麼把輸入弄壞（None＝不改檔案，只靠環境變數）
#   env     = 疊在基準環境上的額外變數
#   expect  = 輸出裡必須出現的訊息片段，用來確認擋下來的是**這一項**而不是別的。
#             字串＝結尾摘要的 ❌ 要含它；(摘要片段, 明細片段)＝另外要求 ❌ 底下的明細含第二個
#             片段——同一關卡的多種問題共用一條摘要時（`table`），靠明細分出是哪一種擋的
def mut_tables_merge_missing(root):
    """merge key 帶進來的 `filler` 指向不存在的工具——展開後仍要擋。
    改 coordinator 不改 implementer：後者會連帶讓 i5 ❌。"""
    edit(root, "devflow.yml",
         lambda t: replace_first(t, "filler: hermes", "<<: {filler: no-such-tool}"))


def mut_tables_merge_bad_source(root):
    """`<<` 指向 scalar——PyYAML safe_load 自己會拋 ConstructorError 的輸入。
    直接鍵存在也要擋：靜默跳過等於替 parser 發明一套更寬鬆的語意（AC-3）。
    改 coordinator 不改 implementer：後者會連帶讓 i5 ❌。"""
    edit(root, "devflow.yml",
         lambda t: replace_first(t, "filler: hermes",
                                 "<<: not-a-mapping\n    filler: hermes"))


def mut_tables_merge_dup(root):
    """同一個 mapping 兩個 `<<`：PyYAML 後者覆蓋先者，本檢查先者優先，語意分歧。
    改 coordinator 不改 implementer：後者會連帶讓 i5 ❌。

    先改 coordinator 再插 anchor：反過來的話 anchor 區塊裡的 `filler: hermes`
    會變成「第一個」，replace_first 就打不到 coordinator（本檔曾犯此錯）。"""
    edit(root, "devflow.yml",
         lambda t: "_m1: &m1 {filler: hermes}\n_m2: &m2 {filler: no-such-tool}\n\n"
                   + replace_first(t, "filler: hermes", "<<: *m1\n    <<: *m2"))


def mut_tables_merge_deep_bad(root):
    """直接值命中，但可達的深層 merge 來源壞掉——結構驗證不得被 lookup 短路略過。"""
    edit(root, "devflow.yml",
         lambda t: "_deep: &deep\n  <<: scalar-here\n\n"
                   + replace_first(t, "filler: hermes", "<<: *deep\n    filler: hermes"))


def mut_tables_merge_later_bad(root):
    """第一個來源有效，後續來源壞掉——同上，不得因先命中而略過。"""
    edit(root, "devflow.yml",
         lambda t: "_good: &good {filler: hermes}\n_later: &later\n  <<: scalar-x\n\n"
                   + replace_first(t, "filler: hermes", "<<: [*good, *later]"))


CASES = [
    ("encoding", "encoding", mut_encoding, {},
     ("devflow/seats/approver.md 的內容不是合法 UTF-8", "位元組偏移")),
    ("d2", "d2", mut_d2, {}, "的 devflow 區塊沒有關閉"),
    ("i1", "i1", None, {"GITHUB_HEAD_REF": "no-issue-number"},
     "不合 I1 的 `<N>-<slug>`"),
    ("i5", "i5", mut_i5, {}, "投影與來源不一致"),
    ("version", "version", mut_version, {}, "不是四碼 a.b.c.d"),
    ("fence", "fence", mut_fence, {}, "的 fenced code block 沒有關閉"),
    ("tables:rm-forge", "tables", mut_tables_forge, {}, "指名的對照表不在版控內"),
    ("tables:rm-coder", "tables", mut_tables_coder, {}, "指名的對照表不在版控內"),
    ("tables:no-such-tool", "tables", mut_tables_filler, {}, "指名的對照表不在版控內"),
    ("tables:no-forge", "tables", mut_tables_no_forge, {}, "推導不出必需的對照表"),
    ("tables:merge-missing", "tables", mut_tables_merge_missing, {},
     "指名的對照表不在版控內"),
    ("tables:merge-bad-source", "tables", mut_tables_merge_bad_source, {},
     "推導不出必需的對照表"),
    ("tables:merge-dup", "tables", mut_tables_merge_dup, {},
     "推導不出必需的對照表"),
    ("tables:merge-deep-bad", "tables", mut_tables_merge_deep_bad, {},
     "推導不出必需的對照表"),
    ("tables:merge-later-bad", "tables", mut_tables_merge_later_bad, {},
     "推導不出必需的對照表"),
    ("table", "table", mut_table, {}, "的對照表形狀不合 R9"),
    ("table:raw-html", "table", mut_table_raw_html, {},
     ("devflow/orchestrators/paperclip.md 的對照表形狀不合 R9（1 項）", "有 raw HTML 的 <table>")),
    ("table:short-row", "table", mut_table_short_row, {},
     ("devflow/coders/codex.md 的對照表形狀不合 R9（1 項）", "列的狀態格為空")),
    ("table:blank-status", "table", mut_table_blank_status, {},
     ("devflow/coders/codex.md 的對照表形狀不合 R9（1 項）", "列的狀態格為空")),
    ("table:quoted-text", "table", mut_table_quoted_text, {},
     "的對照表形狀不合 R9"),
    ("table:script", "table", mut_table_script, {}, "的對照表形狀不合 R9"),
    ("table:inline-multiline", "table", mut_table_inline_multiline, {},
     ("的對照表形狀不合 R9", paperclip_table_at(TABLE_INLINE_MULTILINE))),
    ("table:inline-codespan", "table", mut_table_inline_codespan, {},
     ("的對照表形狀不合 R9", paperclip_table_at(TABLE_INLINE_CODESPAN))),
    ("link", "link", mut_link, {}, LINK_BROKEN),
    # issue #100：raw HTML 的連結。明細帶行號，判定與 markdown 連結同一個迴圈。
    ("link:html-a", "link", mut_link_html_a, {},
     (LINK_BROKEN, readme_link(HTML_LINK_5A, "does/not/exist.md"))),
    ("link:html-inline", "link", mut_link_html_inline, {},
     (LINK_BROKEN, readme_link(HTML_LINK_5B, "does/not/exist.md"))),
    ("link:html-img", "link", mut_link_html_img, {},
     (LINK_BROKEN, readme_link(HTML_LINK_5C, "does/not/exist.png"))),
    ("link:html-git-config", "link", mut_link_html_git_config, {},
     (LINK_BROKEN, readme_link(HTML_LINK_5D, ".git/config"))),
    ("link:html-escape", "link", mut_link_html_escape, {},
     (LINK_BROKEN, readme_link(HTML_LINK_5E, "../../etc/passwd", "（逃出 repo 之外）"))),
    ("link:html-block", "link", mut_link_html_block, {},
     (LINK_BROKEN, readme_link(HTML_LINK_BLOCK, "does/not/exist.md"))),
    ("link:html-line", "link", mut_link_html_line, {},
     (LINK_BROKEN, readme_link(HTML_LINK_LINE, "does/not/exist.md"))),
    # issue #102：srcset。明細比對到**行尾**（suffix 是換行）：送進判定的若是整個候選或整串，
    # 明細會是 `-> does/not/exist.png 2x`，與期望前綴相同，不比到行尾就分不出來。
    ("link:srcset-source", "link", mut_link_srcset_source, {},
     (LINK_BROKEN, readme_link(SRCSET_SOURCE, "does/not/exist.png", "\n"))),
    ("link:srcset-img", "link", mut_link_srcset_img, {},
     (LINK_BROKEN, readme_link(SRCSET_IMG, "does/not/exist.png", "\n"))),
    ("link:srcset-multi", "link", mut_link_srcset_multi, {},
     (LINK_BROKEN, readme_link(SRCSET_MULTI, "does/not/exist.png", "\n"))),
    ("link:srcset-no-space", "link", mut_link_srcset_no_space, {},
     (LINK_BROKEN, readme_link(SRCSET_NO_SPACE, "README.md,devflow/WORKFLOW.md", "\n"))),
    ("link:srcset-nbsp", "link", mut_link_srcset_nbsp, {},
     (LINK_BROKEN, readme_link(SRCSET_NBSP, "README.md ", "\n"))),
    ("link:srcset-line", "link", mut_link_srcset_line, {},
     (LINK_BROKEN, readme_link(SRCSET_LINE, "does/not/exist.png", "\n"))),
    ("dupid", "dupid", mut_dupid, {},
     ("規則 ID `D1` 被定義 2 次", "又寫了一次，這是真的重複定義")),
    # issue #98：ID 之前有裝飾性內容的五種寫法，舊判準四種漏認。
    ("dupid:empty-link", "dupid", mut_dupid_empty_link, {},
     ("規則 ID `D1` 被定義 2 次", "空連結後的重複定義")),
    ("dupid:text-link", "dupid", mut_dupid_text_link, {},
     ("規則 ID `D2` 被定義 2 次", "有字連結後的重複定義")),
    ("dupid:image", "dupid", mut_dupid_image, {},
     ("規則 ID `D3` 被定義 2 次", "圖片後的重複定義")),
    ("dupid:strike", "dupid", mut_dupid_strike, {},
     ("規則 ID `D4` 被定義 2 次", "刪除線後的重複定義")),
    ("dupid:link-newline", "dupid", mut_dupid_link_newline, {},
     ("規則 ID `D1` 被定義 2 次", "換行之後才寫的重複定義")),
    # PR #99 第一輪審查：裝飾與 ID 各在自己的容器裡，比 level 深度數字會漏認。
    ("dupid:link-strong", "dupid", mut_dupid_link_strong, {},
     ("規則 ID `D1` 被定義 2 次", "連結後粗體 ID 的重複定義")),
    ("dupid:strike-em", "dupid", mut_dupid_strike_em, {},
     ("規則 ID `D2` 被定義 2 次", "刪除線後斜體 ID 的重複定義")),
    # 四案共用同一條摘要（同一張表），靠明細裡的狀態格內容分出是哪一種擋的。
    ("r9:old-word", "r9", mut_r9_old_word, {},
     ("有 1 列的狀態欄不是 ✅ 可用／📝 已宣稱／⬜ 未測",
      "狀態欄=「✅ 實測 2026-09-11（驗證方式：…）」")),
    ("r9:no-sep", "r9", mut_r9_no_sep, {},
     ("有 1 列的狀態欄不是 ✅ 可用／📝 已宣稱／⬜ 未測", "狀態欄=「✅可用」")),
    ("r9:glued", "r9", mut_r9_glued, {},
     ("有 1 列的狀態欄不是 ✅ 可用／📝 已宣稱／⬜ 未測", "狀態欄=「✅ 可用性佳」")),
    ("r9:other-word", "r9", mut_r9_other_word, {},
     ("有 1 列的狀態欄不是 ✅ 可用／📝 已宣稱／⬜ 未測", "狀態欄=「✅ 完成」")),
]

# 「突變後仍應通過」的正向案例：判準不能誤擋正當變更。
# 目標關卡照樣以 DEVFLOW_GATE_<KEY>=1 打開——就算它日後被降為建議，這裡驗的仍是「當關卡也不擋」。
def ok_tables_merge_key(root):
    """`seats.reviewer.filler` 只由 merge key 提供。

    AC-13 只禁止它明列的三個 mapping（根、`seats`、`seats.implementer`）出現
    merge key；`reviewer` 不在範圍內，既有 `i5` 對它是通過的。`tables` 若不
    展開就等於自行補上規格沒有的禁令（審查者 PR #88 第二輪的精確反例）。"""
    edit(root, "devflow.yml",
         lambda t: replace_first(t, "filler: codex", "<<: {filler: codex}"))


def ok_r9_separators(root):
    """三值之後接分隔符與補充都合規（R9 要求 `✅` 附驗證方式、`📝` 標明是哪一種，
    補充本來就得接在三值後面）。三值各一列，涵蓋全形括號、全形冒號、沒有補充
    三種寫法——判準若收成「狀態格必須恰等於三值」，這一案就會誤擋。"""
    edit(root, "devflow/coders/codex.md",
         lambda t: append(t,
                          "| 可用 | — | 值 | ✅ 可用（實測 2026-09-11，驗證方式：…） |\n"
                          "| 已宣稱 | — | 值 | 📝 已宣稱：驗證未達 `✅` |\n"
                          "| 未測 | — | 值 | ⬜ 未測 |\n"))


PASSING = [
    ("encoding:bom", "encoding", ok_encoding_bom),
    ("tables:forge-gitlab", "tables", ok_tables_forge_gitlab),
    ("tables:no-coordinator", "tables", ok_tables_coordinator_omitted),
    ("tables:merge-key", "tables", ok_tables_merge_key),
    ("table:html-in-fence", "table", ok_table_html_in_fence),
    ("table:html-attr", "table", ok_table_html_attr),
    ("table:html-comment", "table", ok_table_html_comment),
    ("table:html-attr-name", "table", ok_table_html_attr_name),
    # issue #100 AC-5：示範不是資料；合法的 raw HTML 連結不誤擋。
    ("link:html-in-fence", "link", ok_link_html_in_fence),
    ("link:html-in-code-span", "link", ok_link_html_in_code_span),
    ("link:html-comment", "link", ok_link_html_comment),
    ("link:html-valid", "link", ok_link_html_valid),
    # issue #102 AC-4：合法的 srcset（含 URL 帶逗號）與示範裡的 srcset 不誤擋。
    ("link:srcset-valid", "link", ok_link_srcset_valid),
    ("link:srcset-in-code", "link", ok_link_srcset_in_code),
    ("r9:prose", "r9", ok_r9_prose),
    ("dupid:deep-heading", "dupid", ok_dupid_deep_heading),
    ("r9:separators", "r9", ok_r9_separators),
    # issue #96 的三個「修不掉」的假陽性，逐案對應判準的三個條件。
    ("dupid:appendix", "dupid", ok_dupid_appendix),
    ("dupid:index", "dupid", ok_dupid_index),
    ("dupid:blockquote", "dupid", ok_dupid_blockquote),
    # issue #98 AC-3：ID 不是本項主題的散文，三案都在家族相符的節裡。
    ("dupid:prose-ref", "dupid", ok_dupid_prose_ref),
    ("dupid:prose-list", "dupid", ok_dupid_prose_list),
    ("dupid:prose-in-strong", "dupid", ok_dupid_prose_in_strong),
    # 斷言的是**現況行為**，而且那是一個已知漏認（絆線）——理由見該函式的 docstring。
    ("dupid:task-list", "dupid", ok_dupid_task_list),
]

# 「一個突變同時觸發多項」的案例（issue #91 AC-1 的 fail closed）。
# 和 CASES 的差別只在斷言：CASES 要求恰好 1 條 ❌（歸因到目標項），這裡要求恰好等於
# expects 列出的那幾條——**少一條也是失敗**。少的那條就是被錯誤跳過的檢查。
#   name    = 案例名
#   gates   = 要打開的關卡（全部以 DEVFLOW_GATE_<KEY>=1 打開）
#   mutate  = 怎麼把輸入弄壞
#   expects = 摘要裡必須出現的 ❌ 片段，一條片段對一條 ❌
MULTI = [
    ("encoding:fail-closed", ("encoding", "fence"), mut_encoding_fail_closed,
     ["README.md 的內容不是合法 UTF-8", "的 fenced code block 沒有關閉"]),
]


# ── 執行 ──────────────────────────────────────────────────────────
def run_checker(cwd, gate=None, extra_env=None):
    env = dict(os.environ)
    env.pop("DEVFLOW_GATE_" "", None)
    for k in list(env):
        if k.startswith("DEVFLOW_GATE_"):
            del env[k]
    env["GITHUB_EVENT_NAME"] = "pull_request"
    env["GITHUB_HEAD_REF"] = GOOD_HEAD_REF
    # 煙霧測試驗的是**關卡判定**，不是相依版本是否符 pin。本機常裝別的版本，
    # 不放行的話每一案都會先撞上 pin 守衛的 exit 2 而測不到關卡（issue #91）。
    # CI 不設這個變數，pin 守衛在那裡照常生效。
    env.setdefault("DEVFLOW_ALLOW_PIN_DRIFT", "1")
    if gate:
        # 環境變數只能加嚴不能放寬：目標項就算日後被改回 advisory，這個案例仍是關卡。
        env["DEVFLOW_GATE_" + gate.upper()] = "1"
    env.update(extra_env or {})
    p = subprocess.run([sys.executable, str(CHECKER)], cwd=cwd, env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def crosses(out):
    """取結尾摘要區塊列出的 ❌。

    檢查器每條失敗會印兩次——發現當下印一次，最後的「必需關卡失敗」摘要再列一次。
    只認摘要那一份，數出來的才是「這次有幾項關卡失敗」。摘要不存在（exit 0）就是空的。"""
    lines = out.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("===== 必需關卡失敗"):
            out_lines = []
            for l in lines[i + 1:]:
                if l.strip().startswith("❌"):
                    out_lines.append(l.strip()[1:].strip())
                elif l.startswith("====="):
                    break
            return out_lines
    return []


def main():
    if not CHECKER.is_file():
        sys.exit("找不到檢查器：%s" % CHECKER)
    files = repo_files()
    failures = []

    with tempfile.TemporaryDirectory(prefix="devflow-smoke-") as tmp:
        pristine = Path(tmp) / "pristine"
        pristine.mkdir()
        make_sandbox(files, pristine)
        print("沙箱：%d 個檔案（受版控 ∪ 未忽略的未追蹤）" % len(files))
        print()

        # 正向：沒有突變，必須 exit 0 且 0 個 ❌。
        code, out = run_checker(pristine)
        marks = crosses(out)
        good = (code == 0 and not marks)
        print("正向  %-22s 通過    exit %d（期望 0）  ❌ %d 條  %s"
              % ("乾淨輸入", code, len(marks), "PASS" if good else "FAIL"))
        if not good:
            failures.append("正向案例：exit %d、%d 條 ❌" % (code, len(marks)))
            for m in marks:
                print("        ❌ %s" % m)
        print()

        # 正向：突變後仍應通過，同樣 exit 0 且 0 個 ❌。
        for n, (name, gate, mutate) in enumerate(PASSING):
            work = Path(tmp) / ("pass-%02d" % n)
            shutil.copytree(pristine, work)
            mutate(work)
            code, out = run_checker(work, gate=gate)
            marks = crosses(out)
            good = (code == 0 and not marks)
            print("正向  %-22s 通過    exit %d（期望 0）  ❌ %d 條  %s"
                  % (name, code, len(marks), "PASS" if good else "FAIL"))
            for m in marks:
                print("          ❌ %s" % m)
            if not good:
                failures.append("%s：exit %d（期望 0）、%d 條 ❌" % (name, code, len(marks)))
            shutil.rmtree(work)
            print()

        # 負向：每個關卡至少一個「應擋」案例。
        for n, (name, gate, mutate, extra_env, expect) in enumerate(CASES):
            work = Path(tmp) / ("case-%02d" % n)
            shutil.copytree(pristine, work)
            if mutate:
                mutate(work)
            code, out = run_checker(work, gate=gate, extra_env=extra_env)
            marks = crosses(out)
            expect, detail = (expect, None) if isinstance(expect, str) else expect
            hit = any(expect in m for m in marks) and (detail is None or detail in out)
            # exit 1 **只能由目標項造成**（PR #81「Phase 1 第三出口」的條件三）：
            # 只檢查「有沒有命中目標」會讓「目標錯誤 ＋ 別的錯誤」一起通過，
            # 那時 exit 1 證明不了是哪一項擋的（審查者 PR #83 第一輪以故障
            # 替身實測：七案各多一個非目標 ❌，煙霧測試仍印「全部通過」）。
            good = (code == 1 and hit and len(marks) == 1)
            print("負向  %-22s 應擋    exit %d（期望 1）  ❌ %d 條  %s"
                  % (name, code, len(marks), "PASS" if good else "FAIL"))
            for m in marks:
                print("        %s ❌ %s" % ("←" if expect in m else " ", m))
            if not good:
                failures.append(
                    "%s：exit %d（期望 1）%s"
                    % (name, code, "" if hit else "，且輸出裡找不到「%s」%s"
                       % (expect, "" if detail is None else "＋明細「%s」" % detail)))
            shutil.rmtree(work)
            print()

        # 一個突變同時觸發多項：要求恰好等於 expects 那幾條，少一條就是有檢查被跳過。
        for n, (name, gates, mutate, expects) in enumerate(MULTI):
            work = Path(tmp) / ("multi-%02d" % n)
            shutil.copytree(pristine, work)
            mutate(work)
            code, out = run_checker(
                work, extra_env={"DEVFLOW_GATE_" + g.upper(): "1" for g in gates})
            marks = crosses(out)
            missing = [e for e in expects if not any(e in m for m in marks)]
            good = (code == 1 and not missing and len(marks) == len(expects))
            print("多項  %-22s 應擋    exit %d（期望 1）  ❌ %d 條（期望 %d）  %s"
                  % (name, code, len(marks), len(expects), "PASS" if good else "FAIL"))
            for m in marks:
                print("        %s ❌ %s"
                      % ("←" if any(e in m for e in expects) else " ", m))
            if not good:
                failures.append(
                    "%s：exit %d（期望 1）、%d 條 ❌（期望 %d）%s"
                    % (name, code, len(marks), len(expects),
                       "" if not missing else "，找不到：%s" % "／".join(missing)))
            shutil.rmtree(work)
            print()

    print("=" * 60)
    if failures:
        print("煙霧測試失敗（%d 項）：" % len(failures))
        for f in failures:
            print("  - %s" % f)
        return 1
    print("煙霧測試全部通過：%d 個正向 ＋ %d 個應擋案例 ＋ %d 個多項案例（涵蓋 %d 個關卡）"
          % (1 + len(PASSING), len(CASES), len(MULTI),
             len({c[1] for c in CASES} | {g for m in MULTI for g in m[1]})))
    return 0


if __name__ == "__main__":
    sys.exit(main())
