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
