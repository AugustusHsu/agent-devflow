#!/usr/bin/env python3
"""`CH3` 分區標記 grammar 的單一實作（telegram 通道的參考實作共用）。

本模組是 `devflow/channels/README.md` 「分區三態」判定式的**實作**，不是近似邏輯。
兩個 grammar 常數的字面須與該檔 `:59` 的 `T`／`A` 兩式**逐字相同**
（`tests/channels/test_marker.py` 的 `AC-6` 以字串相等比對，並對「改一個字元」有鑑別力）。

為什麼要集中在這裡（`#285`／K4c-1）：三支腳本原本各寫一份近似邏輯，五處讀寫點全都
既不錨定也不計數——`re.search` 取第一個命中、`re.sub` 取代全部命中。後果不是假想的：
撰 `#285` 的 T 之後、建分區時，`devflow_topic.py:79-80` 把那張 issue body 內**所有**
`<!-- devflow:topic thread=<數字> -->` 字樣（含 fixture 定義與驗證輸出原文）一律改寫成
新 thread id，而改寫後條文式仍是 `T=1`，故**不觸發 INVALID、無任何告警**。

三條判定式都錨行首行尾（`^…$`）。**這不解析 markdown，也不得解析**：寫在表格列裡
（行首是 `|`）、縮排、或成為散文的一部分都不算標記（`channels/README.md:63`
「標記必須是獨立一行才算」）。**不得**在此加上「排除 fenced code block」「跳過表格」
之類的寬鬆化——那會使實作再次偏離條文，正是本模組要消滅的病。要改判準得走 `G2`
開新單改條文。

`T>1`／`A>1` ＝ INVALID（`channels/README.md:61`：「判定程式須對 INVALID 回非 0 或
明確吐 `INVALID`，不得靜默取其一」）。本模組的做法是 raise `InvalidMarker`，
訊息含**全部命中行的字面**；腳本層接住後 exit 非 0 並印 stderr，**不動 forge**。
"""
from __future__ import annotations

import re

# ── grammar（單一來源）──────────────────────────────────────────────────────
# ⚠ 下列兩個字面須與 devflow/channels/README.md:59 的 grep -cE '…' 逐字相同。
#   改這裡就要同步改條文（`G2`），反之亦然；test_marker.py 的 AC-6 會擋住單邊漂移。
TOPIC_RE = r"^<!-- devflow:topic thread=[0-9]+ -->$"
ARCHIVED_RE = r"^<!-- devflow:archived thread=[0-9]+ file=[^ >]+ -->$"

# grep 是逐行比對，故 re.MULTILINE —— `^…$` 套在每一行上，等價於
# `printf '%s\n' "$B" | grep -cE '…'`。正向與反向查找共用這兩個已編譯物件（`AC-7`）。
TOPIC = re.compile(TOPIC_RE, re.MULTILINE)
ARCHIVED = re.compile(ARCHIVED_RE, re.MULTILINE)

# 取 thread id 用。與 TOPIC／ARCHIVED 同構，只多一個捕獲群組——不另立一套 grammar：
# 由 _with_group() 從上面的常數機械產生，避免兩份字面各自漂移。
def _with_group(pattern: str) -> re.Pattern[str]:
    """把 grammar 常數的 `[0-9]+`（thread 欄）加上捕獲群組，其餘字面不動。"""
    out, n = re.subn(r"thread=\[0-9\]\+", "thread=([0-9]+)", pattern, count=1)
    if n != 1:
        raise AssertionError(f"grammar 常數不含預期的 thread 欄：{pattern!r}")
    return re.compile(out, re.MULTILINE)


TOPIC_ID = _with_group(TOPIC_RE)
ARCHIVED_ID = _with_group(ARCHIVED_RE)


class InvalidMarker(Exception):
    """`T>1` 或 `A>1`：該單的分區「是哪一個」沒有單一答案，只能停。

    `channels/README.md:61` 的 INVALID 收容分支。訊息含全部命中行的字面，
    供腳本層原樣印到 stderr。
    """

    def __init__(self, kind: str, lines: list[str], detail: str = "",
                 summary: str = ""):
        self.kind = kind            # "topic" / "archived"
        self.lines = list(lines)    # 全部命中行的字面
        body = "\n".join(f"  {ln}" for ln in self.lines)
        self.detail = detail
        suffix = f"（{detail}）" if detail else ""
        # `summary` 供「同一 thread 被多張 issue 主張」這種跨 issue 的歧義改寫開頭句；
        # 省略時用預設的「標記出現 N 次」（單一 body 內 T>1／A>1 的情形）。
        head = summary or f"{kind} 標記出現 {len(self.lines)} 次"
        super().__init__(
            f"INVALID: {head}，"
            f"依 CH3（channels/README.md:61）不得視為任一態{suffix}\n{body}"
        )


# ── 正向：issue body → thread id ─────────────────────────────────────────────
def find_topic(body: str) -> tuple[list[str], list[str]]:
    """回傳 (thread id 字串們, 命中行的字面們)。不判斷 INVALID，純計數。

    `len(lines)` 即條文的 `T`。
    """
    text = body or ""
    return TOPIC_ID.findall(text), TOPIC.findall(text)


def find_archived(body: str) -> tuple[list[str], list[str]]:
    """同 find_topic，對封存標記。`len(lines)` 即條文的 `A`。"""
    text = body or ""
    return ARCHIVED_ID.findall(text), ARCHIVED.findall(text)


def read_topic(body: str, *, detail: str = "") -> int | None:
    """`T=0` → None；`T=1` → int；`T>1` → raise InvalidMarker。

    `detail` 供呼叫端補上「哪一張單」之類的上下文，只進訊息、不影響判定。
    """
    ids, lines = find_topic(body)
    if not lines:
        return None
    if len(lines) > 1:
        raise InvalidMarker("topic", lines, detail)
    return int(ids[0])


def read_archived(body: str, *, detail: str = "") -> int | None:
    """`A=0` → None；`A=1` → int；`A>1` → raise InvalidMarker。"""
    ids, lines = find_archived(body)
    if not lines:
        return None
    if len(lines) > 1:
        raise InvalidMarker("archived", lines, detail)
    return int(ids[0])


# ── 批次掃描：一批 (issue, body) → 所有命中的 (issue, thread, kind) ───────────
# 為什麼住在這裡（`#287` 乙案）：「從一批 issue body 抽出所有 thread id」就是 marker
# 讀取，屬本模組的定位（見模組 docstring：`CH3` grammar 的**單一實作**）。三個呼叫端
# 原本各寫一份掃描迴圈——`devflow_topic.sync`、`devflow_archive.issue_meta`，以及
# `#287` 的新上界會是第三份；`devflow_archive.py:665` 的註解「故此處重寫一次而非抽
# 常數」就是「已被迫寫第二次」的紀錄，不是可接受的現狀。
#
# ⚠ **本區段不打 `gh`、不開子程序、不碰網路**（`#287` `AC-1`）：查詢留在呼叫端，
# 模組只吃字串。這讓三個呼叫端的掃描都能以純字串 fixture 驗證（不必真的掃 forge），
# 也使本模組維持零 I/O ——「grammar 的實作」與「資料從哪來」是兩件事。
def _scan_markers(items, *, kinds=("topic", "archived"), on_invalid=None):
    """一批 `(issue_number, body)` → `[(issue_number, thread_id, kind), …]`。

    `kind` ∈ {`"topic"`, `"archived"`}。**`kind` 不是附帶資訊**：呼叫端據它過濾
    （`#287` `AC-2`：`issue_meta` 只認 `topic` 標記，若把 `archived` 也算進反向
    查找，已封存的單會被命中 → 對外行為就變了）。

    `T>1`／`A>1` 的處置由呼叫端決定，語意與 `read_topic`／`read_archived` 一致：

      * `on_invalid is None`（預設）→ `InvalidMarker` 直接穿出去。
        `issue_meta` 要的是這個：INVALID 不得被它的 `except Exception` 吞掉
        （`#285` `BLOCK-1`：續掃可能在別張單命中同一 thread，匯出檔就掛錯單）。
      * 給了 `on_invalid(exc, issue_number)` → 呼叫它之後**跳過該單續掃**。
        `sync` 要的是這個：一張壞單不該讓其餘兩百多張單重建不了，而呼叫端仍以
        回報的單號 exit 非 0（`channels/README.md:61`：不得靜默取其一）。

    跳過時整張單都跳過（不續掃它的另一式）：該單的分區「是哪一個」已無單一答案。

    **掃完才回傳**，順序即輸入順序（同一張單先 `topic` 後 `archived`）。
    `issue_meta` 的「多張單主張同一 thread」只有掃完才發現得了（`#285`
    `BLOCK-1` 第 3 輪：早退使「停不停下」取決於 `gh issue list` 的回傳順序）。
    """
    rows: list[tuple] = []
    for issue, body in items:
        for kind in kinds:
            try:
                # 讀側一律走本模組的既有 `read_*`（同一份 grammar、同一個 `InvalidMarker`）。
                # 以模組全域名稱解析、不預先綁進表格：呼叫端換掉 `read_topic` 時這裡
                # 跟著換，否則會出現「共用模組有兩條讀路徑」的分歧。
                tid = (read_topic if kind == "topic" else read_archived)(
                    body or "", detail=f"issue #{issue}")
            except InvalidMarker as exc:
                if on_invalid is None:
                    raise
                on_invalid(exc, issue)
                break
            if tid is not None:
                rows.append((issue, tid, kind))
    return rows


def scan_topic(items, *, on_invalid=None):
    """批次掃 `topic` 標記 → `[(issue, thread, "topic"), …]`。細節見 `_scan_markers`。"""
    return _scan_markers(items, kinds=("topic",), on_invalid=on_invalid)


def scan_archived(items, *, on_invalid=None):
    """批次掃 `archived` 標記 → `[(issue, thread, "archived"), …]`。見 `_scan_markers`。

    封存過的單**沒有** `topic` 標記以外的另一條線索：`archived` 標記是它在 forge 上
    唯一留下的 thread id（`#291` 之後），故推 thread id 上界時必須把它算進去
    （`#287` `AC-3`(c)）。
    """
    return _scan_markers(items, kinds=("archived",), on_invalid=on_invalid)


# ── 反向：thread id → 此 body 是否屬該 thread ────────────────────────────────
def has_topic(body: str, thread) -> bool:
    """body 是否有**獨立一行**恰等於 `<!-- devflow:topic thread=<thread> -->`。

    供 `devflow_archive.py` 的反向查找（thread → issue）。只認獨立一行：
    表格列內、散文旁註、縮排的同形字串一律不算，否則匯出檔會掛到錯的 issue。

    `T>1` → raise `InvalidMarker`（與正向的 `read_topic`／`upsert_topic` **同一個
    類別**）。`#285` 第 1 輪曾選「回 `False` 續掃」，被 `R1` 以 `BLOCK-1` 擋下：
    T 的裁定表對 `T>1`／`A>1` 明寫「exit 非 0 ＋ stderr 印 INVALID 與命中的所有行，
    停下不動 forge」，反向查找同樣適用。回 `False` 不是「把後果限制在該單身上」，
    而是**讓掃描繼續**——審查位的反例：#285 的 body 有 `thread=2620` 與 `thread=999`
    兩行而 #286 的 body 有 `thread=2620` 一行時，續掃會在 #286 命中並回傳它，
    匯出檔就掛到了另一張單。停下才是 `CH3` 要的行為。
    """
    ids, lines = find_topic(body)
    if len(lines) > 1:
        raise InvalidMarker("topic", lines, f"反向查找 thread={thread}")
    return bool(ids) and ids[0] == str(thread)


def has_archived(body: str, thread) -> bool:
    """同 has_topic，對封存標記（`file=` 欄不限）。`A>1` → raise `InvalidMarker`。"""
    ids, lines = find_archived(body)
    if len(lines) > 1:
        raise InvalidMarker("archived", lines, f"反向查找 thread={thread}")
    return bool(ids) and ids[0] == str(thread)


# ── 寫入：upsert ────────────────────────────────────────────────────────────
def topic_line(thread) -> str:
    """標記的正規字面。寫入與比對都從這裡取，不各自拼字串。"""
    return f"<!-- devflow:topic thread={thread} -->"


def upsert_topic(body: str, thread, *, detail: str = "") -> str:
    """寫入分區標記，回傳新 body。

    `T=0` → 在尾端追加**獨立一行**；`T=1` → **只**取代那一行；`T>1` → raise。

    錨定是這裡的要點：表格列內、散文旁註、縮排的同形字串**一字不動**——
    `^…$` 根本不匹配它們。原實作用未錨定的 `re.sub` 取代全部命中，
    把 T 自己的 fixture 定義改掉過一次（見模組 docstring）。
    """
    text = body or ""
    line = topic_line(thread)
    _, lines = find_topic(text)
    if len(lines) > 1:
        raise InvalidMarker("topic", lines, detail)
    if not lines:
        return text.rstrip() + "\n\n" + line + "\n"
    # count=1 是多餘的保險：T=1 時只有一個命中。用 lambda 避免 line 內的
    # 反斜線被當成取代字串的轉義（此 grammar 不含反斜線，但不靠這點成立）。
    return TOPIC.sub(lambda _m: line, text, count=1)


def archived_line(thread, file) -> str:
    """封存標記的正規字面。寫入與比對都從這裡取，不各自拼字串。

    **不合 grammar 就 raise `ValueError`，不放寬 grammar**（`#291` 的硬要求）：
    `channels/README.md:51` 的 `file=` 值明文「不含空白與 `>`」，`ARCHIVED_RE` 的
    `[^ >]+` 是 `CH3` 的字面。遇含空白的路徑**不得**改成引號包裹或百分號編碼——
    那是在實作裡放寬判準，要改判準得走 `G2`（`#285` 的教訓）。raise 的代價是
    呼叫端得停下，而靜默產出不合規字面的代價是寫完 body 落回 `A=0`
    ——與本單在修的缺陷同形，故選前者。

    為什麼這裡驗、`topic_line` 不驗：`topic_line` 唯一的欄位是 Telegram 配發的
    thread id（呼叫端從 API 或 cache 拿到的整數）；`archived_line` 的 `file=`
    是自由形狀的路徑，`CH3` 對它有明文約束，是真的會不合的那一欄。

    兩道檢查（都只收窄、不放寬）：
      1. 產出須 `re.fullmatch(ARCHIVED_RE)`——grammar 本身。
      2. 產出須是**單一行**。`[^ >]+` 的否定字元集只排除空白與 `>`，故 `\\n`
         也在它的字集內，`re.fullmatch` 會接受含換行的 `file=` 值；但條文的
         `A` 是 `grep -cE` 逐行比對，含換行的字面寫進 body 就裂成兩行、
         兩行都不合 grammar（`A=0`）。故額外擋掉。
    """
    line = f"<!-- devflow:archived thread={thread} file={file} -->"
    bad = [c for c in ("\n", "\r") if c in line]
    if bad:
        raise ValueError(
            f"封存標記不得跨行（{bad!r} 出現在字面內）：thread={thread!r} file={file!r}"
            f"\n  條文的 A 是 grep -cE 逐行比對，跨行的字面寫進 body 落回 A=0"
        )
    if not re.fullmatch(ARCHIVED_RE, line):
        raise ValueError(
            f"封存標記不合 CH3 的 A 式：{line!r}"
            f"\n  grammar：{ARCHIVED_RE}"
            f"\n  thread={thread!r} 須為十進位數字；file={file!r} 不得含空白或 '>'"
            f"（channels/README.md:51）"
        )
    return line


def upsert_archived(body: str, thread, file, *, detail: str = "") -> str:
    """寫入封存標記，回傳新 body。與 `upsert_topic` 同形的三分支。

    `A=0` → 在尾端追加**獨立一行**；`A=1` → **只**取代那一行；`A>1` → raise
    `InvalidMarker`（**不**回傳 body——`telegram.md:14`：寫入須是 upsert，否則
    重跑封存產生 `A>1` 落入 INVALID）。

    錨定同 `upsert_topic`：表格列內、散文旁註、縮排的同形字串**一字不動**，
    `^…$` 根本不匹配它們。

    `file` 的 grammar 由 `archived_line` 先驗；不合時 raise `ValueError` 且
    **body 不動**（呼叫端不會拿到半成品去寫 forge）。
    """
    text = body or ""
    line = archived_line(thread, file)      # 先驗 grammar：不合就 raise，body 不動
    _, lines = find_archived(text)
    if len(lines) > 1:
        raise InvalidMarker("archived", lines, detail)
    if not lines:
        return text.rstrip() + "\n\n" + line + "\n"
    # count=1 ＋ lambda 的理由同 upsert_topic（錨定下只有一個命中；避免反斜線轉義）。
    return ARCHIVED.sub(lambda _m: line, text, count=1)
