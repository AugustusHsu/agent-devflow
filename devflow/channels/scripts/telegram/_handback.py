#!/usr/bin/env python3
"""`#313`：執行位的終態如何交回協調位——可機械判定的完成機制。

為什麼需要（`#310` 現場）：第 3 輪的 manager **完全照 `seats/manager.md:21` 做了**——
寫了完整的 `M1` 三項與「可合併」結論——仍然沒有人收到。缺的不是條文，是**完成判準**：
「最終回覆寫了『回報協調位』」在 forge 上沒有留痕、沒有接收端的確認，誰都無法機械判定
那次交接到底成立了沒。

本模組只處理**交接協定**，**不是**通用合併／收尾恢復引擎。`handback-done` 的 `result`
指**當前交接事件的處理結果**，**不代表整張 issue 已完成**，**也不授權自動合併**。

四層完成判準（`AC-2`，順序不可跳）：

    層1 落地    該 EID 的 `handback` 行**寫入成功**且**讀回**看得到（恰一行）
    層2 投遞    終態投遞已發出（relay 的 `Popen` 成立）
    層3 接收    接收端寫下持久的 `handback-ack` 行　← **交接完成界線**
    層4 處理    `handback-done` 行，處理結果**另記**

❌ **`Popen` 成功不得冒充層3**：`delivered()` 只看投遞這件事，`received()` 只讀 forge 上
的持久 ack；前者為真而後者為假是**正常狀態**（投遞已發出、還沒人確認），不是已接收。
❌ **層1 失敗不得進層2**：`deliver()` 在層1 未成立時**連 `spawn` 都不呼叫**。

**縫**（同 `devflow_relay.py:179` 的「縫只有一處」原則）：本模組**自己不 import
`subprocess`、不 import `urllib`**，forge 與送訊一律走呼叫者傳進來的 `forge`／`send`
物件，檔案 I/O 走可注入的 `home`。故測試零真 API、零真子程序、零 forge 寫入——
那是**測試方式**，**不代表運行依賴不存在**（實際運行沿用 `gh` 與 `hermes send`）。

落點為什麼是新檔、**不塞 `_marker.py`**：`_marker.py` 的自述逐字是「`CH3` 分區標記
grammar 的單一實作…`channels/README.md` 分區三態判定式的**實作**」——它整個存在理由是
那一條外部條文的實作。本協定與 `CH3` **分開、字面不共用**（見 `GRAMMAR` 那段），塞進去
不是擴寫定位，是讓它承載規範之外的東西。也**不搬動** `devflow_relay.py` 的 `handoff`
grammar（那是 relay 記自己行為的行，`#300`，零程式讀者）。

呼叫形狀與入口邊界見 `devflow/channels/telegram.md` 的「終態交回協調位」格。
"""
from __future__ import annotations

import json
import pathlib
import re
import time
from collections.abc import Callable, Iterable, Sequence
from typing import Any, NamedTuple

# ── grammar（三行，獨立一行的 HTML 註解）────────────────────────────────────────
# 與既有兩族同族（`^<!-- devflow:… -->$`、獨立一行才算）但**字面相異且互不為子字串**：
#   `CH3`：`<!-- devflow:topic … -->`／`<!-- devflow:archived … -->`（`_marker.py`）
#   `#300`：`<!-- devflow:handoff profile=… -->`（`devflow_relay.py`）
# 本族三行各自以 `devflow:handback`／`devflow:handback-ack`／`devflow:handback-done`
# 起首，其後**緊接的那個字元**在三者間不同（空白 vs `-`），故三式各自錨定自己的完整
# 字面後互不誤命中，`CH3` 的 `T`／`A` 兩式計數亦不計本族任何一行（`grep -c` 不變）。
#
# 名稱後的補白（`handback` 後 6 個空白、`-ack` 後 2 個）**是字面的一部分**，不是排版：
# 三個名稱長度不同，補白讓 `event=` 欄在 forge 上對齊成一塊，人掃一眼就讀得出同一事件的
# 三行；而寫者與讀者共用下面這組常數（regex 由同一份字面推出），不可能單邊漂移。
# ⚠️ 手打這三行時補白數目要照抄——它是 grammar，不是裝飾。
HANDBACK_FMT = ("<!-- devflow:handback      event={event} issue={issue} seat={seat} "
                "stage={stage} kind={kind} outcome={outcome} at={at} -->")
ACK_FMT = "<!-- devflow:handback-ack  event={event} by={by} at={at} -->"
DONE_FMT = "<!-- devflow:handback-done event={event} by={by} at={at} result={result} -->"

# 時刻格式：本機時區的 ISO 8601（`%z` 帶 ±HHMM 偏移），同 `#300` 的 `HANDOFF_AT_FMT`。
# 取寫者自己的時鐘，不問任何人。
AT_FMT = "%Y-%m-%dT%H:%M:%S%z"
_AT_RE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}[+\-][0-9]{4}"

# `attempt` **不在行內**（`#313` §1.3）：重試**不改動已落地事件的不可變內容**——已寫下的
# `handback` 行不重寫。嘗試次數只放待處理紀錄（`write_pending`）。
#
# `EID` 的形狀：`<issue>-<stage>-<basis>`，恰三欄，`-` **只作欄位分隔**。欄內的層次用
# `.`（`r6.approve`、`merge.done`），故三欄切得開、比較只用字串相等（本模組從不把 EID
# 切回三欄，但形狀封住才能保證兩個不同的 (issue, stage, basis) 不會組出同一個字串）。
EID_RE = r"[0-9]+-[a-z0-9]+(?:\.[a-z0-9]+)*-[a-z0-9]+(?:\.[a-z0-9]+)*"

KINDS = ("stage", "final")
OUTCOMES = ("done", "blocked", "decide", "failed")

HANDBACK_RE = re.compile(
    rf"^<!-- devflow:handback      event=(?P<event>{EID_RE}) issue=(?P<issue>[0-9]+) "
    r"seat=(?P<seat>[A-Za-z0-9_.\-]+) stage=(?P<stage>[a-z0-9][a-z0-9._]*) "
    rf"kind=(?P<kind>{'|'.join(KINDS)}) outcome=(?P<outcome>{'|'.join(OUTCOMES)}) "
    rf"at=(?P<at>{_AT_RE}) -->$", re.M)
ACK_RE = re.compile(
    rf"^<!-- devflow:handback-ack  event=(?P<event>{EID_RE}) "
    rf"by=(?P<by>[A-Za-z0-9_.\-]+) at=(?P<at>{_AT_RE}) -->$", re.M)
DONE_RE = re.compile(
    rf"^<!-- devflow:handback-done event=(?P<event>{EID_RE}) "
    rf"by=(?P<by>[A-Za-z0-9_.\-]+) at=(?P<at>{_AT_RE}) "
    r"result=(?P<result>[a-z][a-z0-9_]*) -->$", re.M)

# 宣告者恆為**完成後處理的 mgr**（`AC-1`）：coder／reviewer 那一輪結束**不是**交回事件，
# 它們回 mgr 之後 mgr 還有後處理（push／開 PR／派審／寫 `R11` 處置）。把宣告權給它們
# 等於讓那段後處理被跳過——那正是 `#310` 的形狀。
DECLARER_SEAT = "dfmgr"
# 接收端（層3 的 ack 寫者）＝協調位。
RECEIVER_PROFILE = "dfcoord"
# General（thread 1）：同 `devflow_archive.py:47`。失敗出口要同時落該單 topic 與 General
# ——該單 topic 的讀者是正在看那張單的人，General 的讀者是在值班的人，兩者不互相代償。
GENERAL_THREAD = "1"


class HandbackError(Exception):
    """協定層的輸入不合 grammar／不合判準。**寧可擋住也不寫出一行讀不回的留痕。**"""


# ── EID：由 issue ＋ stage ＋ **既有不可變觸發紀錄** 導出（`AC-3`）──────────────
# 四類出口各有明確映射，`basis` 一律是**該出口對應的既存紀錄**的 comment ID：
BASIS_FIELD = {
    "done": "verdict_comment_id",        # verdict 後交回 → 該既存 verdict 的 comment ID
    "blocked": "l3_comment_id",          # `L3` 停      → 該既存 `L3` 停下留言的 comment ID
    "decide": "disposition_comment_id",  # `R13` 升人／擱置 → `R11`／`R13` 處置留言的 ID
    "failed": "dispatch_comment_id",     # 本輪技術失敗 → 該既存派工紀錄留言的 comment ID
}
# ❌ **不用**發帖時刻（重試會變成新事件）
# ❌ **不用本次新建的交回 comment ID**（它要等寫入後才存在，用它當鍵會讓重試變成新事件；
#    `#313` 撤回提案 v3「不含 comment id」那句過廣敘述——**既存**的觸發紀錄可以引用）
# ❌ 不只靠截短 head 作唯一依據（同一 head 可被多個階段共用）


def basis_of(outcome: str, triggers: dict[str, Any]) -> str:
    """取該出口的 `basis`。`triggers` ＝ 各類**既存**觸發紀錄的 comment ID。

    為什麼吃一個 mapping 而不是吃一個裸值：四類出口的映射因此是**機械的**——呼叫者填的是
    `verdict_comment_id` 這種有名字的欄位，不是「某個 id」。填錯欄或漏填會在這裡被擋下，
    不會悄悄組出一個形狀正確但基準錯誤的 EID。
    """
    if outcome not in OUTCOMES:
        raise HandbackError(
            f"outcome 須為 {OUTCOMES} 之一，得到 {outcome!r}；四類出口的 basis 映射見 BASIS_FIELD")
    field = BASIS_FIELD[outcome]
    value = triggers.get(field)
    if value is None or str(value).strip() == "":
        raise HandbackError(
            f"outcome={outcome} 的 basis 須取 {field}（該出口對應的**既存**觸發紀錄的 "
            f"comment ID），triggers 內缺它；不得改用發帖時刻或本次新建的交回 comment ID")
    return str(value).strip()


def event_id(issue: str | int, stage: str, basis: str) -> str:
    """邏輯事件識別 `<issue>-<stage>-<basis>`。**同一邏輯事件的重試得到同一個值。**

    全部小寫；三欄皆不得含 `-`（`-` 是欄位分隔符，層次用 `.`）。不合形狀即 raise——
    一個讀不回的 EID 會讓「恰一行」永遠不成立，比擋下來更糟。
    """
    eid = f"{issue}-{stage}-{basis}".lower()
    if not re.fullmatch(EID_RE, eid):
        raise HandbackError(
            f"EID 不合形狀：{eid!r}。須為 <issue>-<stage>-<basis>（issue 為數字、"
            f"stage／basis 為小寫英數與 `.`，三欄皆不得含 `-`）")
    return eid


def event_id_for(issue: str | int, stage: str, outcome: str, triggers: dict[str, Any]) -> str:
    """四類出口的一站式導出：`event_id(issue, stage, basis_of(outcome, triggers))`。"""
    return event_id(issue, stage, basis_of(outcome, triggers))


# ── AC-1：宣告判準 ────────────────────────────────────────────────────────────
def may_declare(*, outstanding_children: int, kind: str, issue_closable: bool,
                seat: str = DECLARER_SEAT, postprocess_done: bool = True) -> tuple[bool, str]:
    """可否宣告交回。回 `(可否, 理由)`，理由是機械可比的短字串。

    `outstanding_children` ＝ **本 seat 本輪發出、尚未回收 rc 的子程序數**。> 0 時一律
    不得宣告：那時 manager 只是**先退出**，流程還在下游跑；宣告了就會有人以為這張單已經
    交回（`#310` 第 3 輪的同形：mgr 的 turn 結束不等於那一輪結束）。

    `kind=stage`（本階段交回）與 `kind=final`（整張完成）分流：`final` **另需本單可結**
    （`issue_closable`）。只看「自己這一輪結束了沒」的實作會把 `stage` 與 `final` 混為
    一談，於是任何一輪結束都被宣告成整張完成。

    `seat`／`postprocess_done`：宣告者恆為**完成後處理的 mgr**。coder／reviewer 回 mgr 的
    後處理（push／開 PR／派審／寫 `R11` 處置）**不得被跳過**，故 (a) 非 `DECLARER_SEAT`
    一律不得宣告、(b) 後處理未完成不得宣告。兩條都在下游判準之後——下游還在跑時連問都不必問。
    """
    if kind not in KINDS:
        raise HandbackError(f"kind 須為 {KINDS} 之一，得到 {kind!r}")
    if outstanding_children < 0:
        raise HandbackError(f"outstanding_children 不可為負：{outstanding_children!r}")
    if outstanding_children > 0:
        return False, "downstream_running"
    if seat != DECLARER_SEAT:
        return False, "not_declarer"
    if not postprocess_done:
        return False, "postprocess_pending"
    if kind == "final" and not issue_closable:
        return False, "not_final_yet"
    return True, "ok"


# ── 三行的組裝 ────────────────────────────────────────────────────────────────
def _now(at: str | None) -> str:
    return at if at else time.strftime(AT_FMT)


def handback_line(*, event: str, issue: str | int, seat: str, stage: str,
                  kind: str, outcome: str, at: str | None = None) -> str:
    """組層1 的 `handback` 行。組完**自己驗一次** grammar——寫出去才發現讀不回已經太晚。"""
    if kind not in KINDS:
        raise HandbackError(f"kind 須為 {KINDS} 之一，得到 {kind!r}")
    if outcome not in OUTCOMES:
        raise HandbackError(f"outcome 須為 {OUTCOMES} 之一，得到 {outcome!r}")
    line = HANDBACK_FMT.format(event=event, issue=issue, seat=seat, stage=stage,
                               kind=kind, outcome=outcome, at=_now(at))
    if not HANDBACK_RE.fullmatch(line):
        raise HandbackError(f"組出的 handback 行不合 grammar：{line!r}")
    return line


def ack_line(*, event: str, by: str = RECEIVER_PROFILE, at: str | None = None) -> str:
    """組層3 的 `ack` 行。寫者＝**接收端**（本流程為協調位）。"""
    line = ACK_FMT.format(event=event, by=by, at=_now(at))
    if not ACK_RE.fullmatch(line):
        raise HandbackError(f"組出的 ack 行不合 grammar：{line!r}")
    return line


def done_line(*, event: str, result: str, by: str = RECEIVER_PROFILE,
              at: str | None = None) -> str:
    """組層4 的 `done` 行。`result` 是**本交接事件**的處理結果，不是整張 issue 的狀態。"""
    line = DONE_FMT.format(event=event, by=by, at=_now(at), result=result)
    if not DONE_RE.fullmatch(line):
        raise HandbackError(f"組出的 done 行不合 grammar：{line!r}")
    return line


# ── AC-2：四層判準 ────────────────────────────────────────────────────────────
def handback_rows(body: str, eid: str) -> list[re.Match]:
    """body 內屬於**這個事件**的 `handback` 行。**射程限定當前事件**（`AC-3`）。"""
    return [m for m in HANDBACK_RE.finditer(body) if m.group("event") == eid]


def landed(body: str, eid: str) -> tuple[bool, str]:
    """層1：該 EID 的 `handback` 行在**讀回的** body 內**恰一行**。

    為什麼判準是「讀回且恰一行」而不是「`write→read` 呼叫序」（`#313` §2.1 的更正）：
    呼叫序只在**同一程序內的首發**可觀測；重送與接收端是**另一個程序**，它看不到別人的
    記憶體呼叫史，也不該為了取得觀測點去**重寫**一個已落地的事件。故義務**不對稱**——
    首發由 `emit_handback()` 保證「寫入成功 ＋ 讀回看得到」，重送／接收端一律以這個
    **可驗證的既存事件**為準。

    「恰一行」**不對整張 issue 的全歷史計數**：同一 issue 的**不同階段**可以合法交回多次
    （`r1.approve`、`merge.done` 各一行），全歷史計數會把第二次合法交回誤判成重複。
    """
    hits = handback_rows(body, eid)
    if len(hits) == 1:
        return True, "ok"
    return False, f"該事件的 handback 行數={len(hits)}（須恰 1，event={eid}）"


def received(body: str, eid: str) -> bool:
    """層3：**接收端的持久 ack**。界線在這裡——交接完成 ＝ 對方確認收到，不是我送出了。"""
    return any(m.group("event") == eid for m in ACK_RE.finditer(body))


def processed(body: str, eid: str) -> bool:
    """層4：處理結果。與層3 **分開**記；有 ack 無 done ＝ 收到了、還沒處理完。"""
    return any(m.group("event") == eid for m in DONE_RE.finditer(body))


def done_result(body: str, eid: str) -> str | None:
    """該事件 `done` 行的 `result`（無則 `None`）。"""
    for m in DONE_RE.finditer(body):
        if m.group("event") == eid:
            return m.group("result")
    return None


class Landing(NamedTuple):
    """層1 的結果。`landed` 為假時 `deliver()` 不得進層2。"""
    status: str          # written｜skipped_exists｜write_failed｜readback_failed
    landed: bool
    detail: str


class Delivery(NamedTuple):
    """層2 的結果。`spawn_called` 讓「層1 失敗連 spawn 都沒叫」可被機械斷言。"""
    status: str          # sent｜refused_not_landed｜spawn_failed
    sent: bool
    spawn_called: bool
    detail: str


def emit_handback(forge: Any, *, event: str, issue: str | int, seat: str, stage: str,
                  kind: str, outcome: str, at: str | None = None,
                  body_text: str = "") -> Landing:
    """層1 首發：**先讀**（去重）→ 寫 → **讀回**驗「恰一行」。

    `forge` 是注入的縫，只需兩個方法：`read() -> str`（該單目前所有可讀文字）與
    `comment(body)`（留一則）。本模組不碰 `subprocess`，故測試零真 API。

    去重（`AC-3`）：寫入前先讀，該事件的行已存在就回 `skipped_exists`——**重試不產生
    第二行**，也**不重寫**已落地的行（`#313` §1.3：已落地事件的不可變內容不因重試改動）。
    `attempt` 不進行內，它只進待處理紀錄。

    寫入失敗或讀回看不到 ＝ **層1 不成立**，回傳的 `landed` 為假，`deliver()` 會拒絕投遞。
    """
    line = handback_line(event=event, issue=issue, seat=seat, stage=stage,
                         kind=kind, outcome=outcome, at=at)
    try:
        before = forge.read()
    except Exception as exc:  # noqa: BLE001 — 讀不到就當作無法確認，不猜
        return Landing("readback_failed", False, f"寫入前讀取失敗：{exc}")
    if handback_rows(before, event):
        ok, why = landed(before, event)
        return Landing("skipped_exists", ok, why)
    head = body_text.strip() or (
        f"`#{issue}` 的 `{stage}` 階段交回（`kind={kind}`、`outcome={outcome}`）。"
        f"本則是交接留痕；接收端確認後會補一行 `handback-ack`。")
    try:
        forge.comment(f"{head}\n\n{line}\n")
    except Exception as exc:  # noqa: BLE001
        return Landing("write_failed", False, f"寫入失敗：{exc}")
    try:
        after = forge.read()
    except Exception as exc:  # noqa: BLE001
        return Landing("readback_failed", False, f"讀回失敗：{exc}")
    ok, why = landed(after, event)
    return Landing("written" if ok else "readback_failed", ok, why)


def deliver(landing: Landing, spawn: Callable[[], Any]) -> Delivery:
    """層2：單次終態投遞。**層1 未成立時連 `spawn` 都不呼叫**（`AC-2`）。

    `spawn` 由呼叫者提供（實際運行 ＝ 以 `--handback-event <EID>` 跑 relay）。回傳值
    只用來判「發出了沒」——它**不是**層3：對方確認收到要讀 forge 上的 ack。
    """
    if not landing.landed:
        return Delivery("refused_not_landed", False, False,
                        f"層1 未成立（{landing.status}：{landing.detail}），不得進層2")
    try:
        out = spawn()
    except Exception as exc:  # noqa: BLE001
        return Delivery("spawn_failed", False, True, f"投遞失敗：{exc}")
    if out is None or out is False:
        return Delivery("spawn_failed", False, True, f"投遞未成立：spawn() 回 {out!r}")
    return Delivery("sent", True, True, f"spawn={out!r}")


def layers(body: str, eid: str, *, delivery: Delivery | None = None) -> dict[int, bool]:
    """四層的當下狀態。層2 沒有 forge 上的對應物，故由 `delivery` 供給（缺 ＝ 未知為假）。"""
    return {
        1: landed(body, eid)[0],
        2: bool(delivery and delivery.sent),
        3: received(body, eid),
        4: processed(body, eid),
    }


def handoff_complete(body: str, eid: str) -> bool:
    """**交接完成 ＝ 層1 ＋ 層3**。層4 另記，層2 不足以宣稱完成（`Popen` 不冒充接收）。"""
    return landed(body, eid)[0] and received(body, eid)


def pending_events(body: str) -> list[str]:
    """尚未處理完的事件（有 `handback` 行而無 `done` 行）。已處理判準是 `done`，不是 `ack`。"""
    seen: list[str] = []
    for m in HANDBACK_RE.finditer(body):
        eid = m.group("event")
        if eid not in seen:
            seen.append(eid)
    return [e for e in seen if not processed(body, e)]


# ── AC-4：恢復三態 ────────────────────────────────────────────────────────────
class _Unknown:
    """讀不出來的哨兵。**不是** `False`——「讀不到」與「未做」是兩件事。"""

    __slots__ = ()

    def __repr__(self) -> str:  # 讓報告裡印得出來
        return "UNKNOWN"

    def __bool__(self) -> bool:
        raise HandbackError("UNKNOWN 不可當布林用——讀不到不是未做，請走 indeterminate")


UNKNOWN = _Unknown()

RESUME_SAFE = "resume_safe"
RECORD_ONLY = "record_only"
INDETERMINATE = "indeterminate"
# 待處理紀錄可以清掉的結果：**結果未定者不在其中**（`AC-6`）。
SETTLED_RESULTS = (RESUME_SAFE, RECORD_ONLY, "handled", "cancelled")


def read_state(probe: Callable[[str], Any], eid: str) -> Any:
    """讀回一步的**外部狀態**。**只接受約定值 `True`／`False`**，其餘一律 `UNKNOWN`。

    為什麼要這麼嚴（裁決位 2026-10-15 的反例 2）：`None` 是 falsy，一個寫成 `if s is False`
    的判準會判它「非未做」→ 當成已完成。字串同理。讀回**失敗**（probe 自己拋例外）也是
    `UNKNOWN`——API 掛掉不是「未做」的證據。

    `probe` 吃 `eid`：每一步都**對準本事件的目標**讀回，不是讀「某個全域狀態」。這讓
    「對準本事件」成為**機械的**（probe 收到哪個事件是可斷言的），而不是呼叫者的口頭承諾。
    """
    try:
        value = probe(eid)
    except Exception:  # noqa: BLE001 — 讀回本身失敗 ＝ 讀不出來
        return UNKNOWN
    return value if (value is True or value is False) else UNKNOWN


def reconcile(steps: Sequence[tuple[str, Callable[[str], Any]]], eid: str
              ) -> tuple[str, dict[str, Any]]:
    """對帳：逐步向外部狀態讀回。**任一步讀不出來 → 整個事件判 `indeterminate`。**

    三態：`resume_safe`（有讀回為 `False` 的步驟 → 只跑那幾步）／`record_only`（全部讀回
    為 `True` → 只補紀錄，不重做動作）／`indeterminate`（交人，**一步都不重播**）。
    """
    report: dict[str, Any] = {}
    for name, probe in steps:
        state = read_state(probe, eid)
        report[name] = state
        if state is UNKNOWN:
            return INDETERMINATE, report
    todo = [n for n, s in report.items() if s is False]
    return (RESUME_SAFE if todo else RECORD_ONLY), report


class Recovery(NamedTuple):
    verdict: str                 # resume_safe｜record_only｜indeterminate｜escalate_human
    report: dict[str, Any]
    ran: list[str]
    done_written: bool
    detail: str


def recover(forge: Any, eid: str, steps: Sequence[tuple[str, Callable[[str], Any]]],
            run: Callable[[str, str], Any], *, result: str = "recovered",
            by: str = RECEIVER_PROFILE, at: str | None = None) -> Recovery:
    """中斷後的恢復：先對帳，再**只跑讀回為未做的步驟**，每一步**執行後再讀回**才算完成。

    三條硬界線（`AC-4`）：
      1. `indeterminate` → `escalate_human`，**一步都不重播**（不得把讀不到當未做，也不得
         盲目重播整段 handler——那會重做已完成的步驟）。
      2. **失敗或未核實的動作不得產生 `done`**：`run()` 沒拋例外**不等於**做成了（裁決位
         反例 1：callback 回 `False`、外部狀態仍 `False`，舊寫法卻記了完成）。故每一步執行
         後都**對準本事件的目標**再讀回，不是 `True` 就 `escalate_human` 且**不寫 `done`**。
      3. `record_only` 時**不重做任何動作**，只補 `done` 紀錄。

    `run(name, eid)` 吃事件 id，理由同 `read_state` 的 probe。
    """
    verdict, report = reconcile(steps, eid)
    if verdict == INDETERMINATE:
        unknown = [n for n, s in report.items() if s is UNKNOWN]
        return Recovery("escalate_human", report, [], False,
                        f"結果未定（讀不回：{unknown}）→ 交人，一步都不重播")
    probes = dict(steps)
    ran: list[str] = []
    for name, state in report.items():
        if state is not False:
            continue
        try:
            run(name, eid)
        except Exception as exc:  # noqa: BLE001 — 動作失敗同樣不得寫 done
            ran.append(name)
            return Recovery("escalate_human", {**report, name: UNKNOWN}, ran, False,
                            f"步驟 {name} 執行拋例外（{exc}）→ 不寫 done，交人")
        ran.append(name)
        after = read_state(probes[name], eid)
        if after is not True:
            return Recovery("escalate_human", {**report, name: after}, ran, False,
                            f"步驟 {name} 執行後讀回為 {after!r}（非 True）→ 不寫 done，交人")
        report[name] = True
    try:
        forge.comment(done_line(event=eid, result=result, by=by, at=at) + "\n")
    except Exception as exc:  # noqa: BLE001
        return Recovery("escalate_human", report, ran, False,
                        f"動作已完成但 done 紀錄寫入失敗（{exc}）→ 結果未定，交人；"
                        f"**不得重播**（動作已核實為完成）")
    return Recovery(verdict, report, ran, True, "ok")


# ── AC-6：失敗出口 ────────────────────────────────────────────────────────────
PENDING_DIRNAME = "handback-pending"
# 忙碌是**具名到 session** 的：`hermes -p dfcoord chat -c issue-<N>` 的同名 session 已有
# chat 在跑。寫「協調位忙碌」沒有可操作性——人要知道去看哪一個 session。
BUSY_CMD_FMT = "hermes -p {profile} chat -c issue-{issue}"
# 失敗出口**不自動續接**。宣稱自動續接會讓人以為有東西在兜底而不去看——那正是 `#310`
# 「以為已經交回」的同形。這句字面進每一則告警，測試對它有斷言。
NO_AUTO_RESUME = "本出口不自動續接、不自動重試：需人介入"

FAIL_REASONS = {
    "busy": "接收端的同名 session 已有 chat 在跑（具名到 session，見指令）",
    "land_failed": "層1 未成立（寫入或讀回失敗）→ 未進層2",
    "deliver_failed": "層2 投遞未發出",
    "no_ack": "已投遞但接收端未寫下持久 ack（層3 未成立）",
    "depth_rejected": "relay 依既有深度判準拒絕派子程序（`DEPTH ≥ MAX_RELAY_DEPTH`）",
    "indeterminate": "恢復對帳判結果未定，一步都不重播",
}


def pending_dir(profile: str, *, home: pathlib.Path) -> pathlib.Path:
    """待處理紀錄的目錄：`<home>/.hermes/profiles/<profile>/handback-pending/`。

    為什麼不落共用暫存根（`#313` §2.2）：那裡有他單的產物與 runtime 的活體資源（`C3`），
    散在那裡的檔沒有 profile 也沒有本單歸屬，收尾時誰都不敢動、也看不出是誰的。
    """
    return pathlib.Path(home) / ".hermes" / "profiles" / profile / PENDING_DIRNAME


def pending_path(profile: str, issue: str | int, eid: str, *,
                 home: pathlib.Path) -> pathlib.Path:
    """`<…>/handback-pending/<issue>-<EID>.json`——**有 profile 與本單歸屬**。"""
    return pending_dir(profile, home=home) / f"{issue}-{eid}.json"


def write_pending(profile: str, issue: str | int, eid: str, *, home: pathlib.Path,
                  reason: str, attempt: int = 1, detail: str = "",
                  result: str = INDETERMINATE, at: str | None = None) -> pathlib.Path:
    """寫（或覆寫）該事件的待處理紀錄。`attempt` 住這裡，**不進已落地的行**（§1.3）。"""
    path = pending_path(profile, issue, eid, home=home)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "event": eid, "issue": str(issue), "profile": profile,
        "reason": reason, "reason_text": FAIL_REASONS.get(reason, reason),
        "attempt": int(attempt), "result": result,
        "detail": detail, "at": _now(at),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return path


def read_pending(profile: str, issue: str | int, eid: str, *,
                 home: pathlib.Path) -> dict | None:
    path = pending_path(profile, issue, eid, home=home)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def clear_pending(profile: str, issue: str | int, eid: str, *, home: pathlib.Path,
                  result: Any) -> tuple[bool, str]:
    """清掉待處理紀錄。**結果未定者不得被當完成而清掉**（`AC-6`）。

    `result` 須是 `SETTLED_RESULTS` 之一；`indeterminate`、`UNKNOWN`、`None` 一律拒絕——
    清掉一筆結果未定的紀錄，等於把「要人看一眼」這件事從系統裡刪掉。
    """
    if result is UNKNOWN or result is None or result not in SETTLED_RESULTS:
        return False, (f"result={result!r} 不在 {SETTLED_RESULTS}：結果未定不得清除，"
                       f"待處理紀錄保留待人處置")
    path = pending_path(profile, issue, eid, home=home)
    if path.exists():
        path.unlink()
    return True, "cleared"


def failure_text(*, issue: str | int, eid: str, reason: str, detail: str = "",
                 pending_file: pathlib.Path | str = "",
                 receiver: str = RECEIVER_PROFILE) -> str:
    """告警文字。一則同時送 topic 與 General，故字面只有一份、兩邊不會漂移。"""
    lines = [f"⚠️ **終態交回失敗**：`#{issue}`　事件 `{eid}`",
             f"原因（`{reason}`）：{FAIL_REASONS.get(reason, reason)}"]
    if reason == "busy":
        lines.append("具名到 session：`" + BUSY_CMD_FMT.format(profile=receiver, issue=issue)
                     + "` 的同名 session 已有 chat 在跑")
    if detail:
        lines.append(f"現場：{detail}")
    if pending_file:
        lines.append(f"待處理紀錄：`{pending_file}`")
    lines.append(NO_AUTO_RESUME)
    return "\n".join(lines)


class FailureExit(NamedTuple):
    text: str
    threads: list[str]                 # 實際送達（`send` 回真）的 thread
    attempted: list[str]               # 嘗試送出的 thread（含失敗者）
    pending_file: pathlib.Path


def failure_exit(*, issue: str | int, eid: str, reason: str,
                 topic_thread: str, send: Callable[[str, str], Any],
                 home: pathlib.Path, profile: str = RECEIVER_PROFILE,
                 attempt: int = 1, detail: str = "", at: str | None = None,
                 general_thread: str = GENERAL_THREAD) -> FailureExit:
    """失敗出口：告警落**該單 topic ＋ General**，並寫**待處理紀錄**。

    三件事都要，缺一不可（`AC-6`）：**不得只留 stderr**（oneshot 下 stderr 沒有讀者，
    那正是本族缺陷的形狀，`#287` 的 5-byte log）、**不得只留 headless 最終回覆**
    （`#310` 的現場：寫得完整、沒有人收到）。送訊失敗**不中斷**——紀錄仍要落地，否則
    通道掛掉時連「有一件事沒收尾」都查不到；哪幾個 thread 送成功在回傳值裡。

    待處理紀錄先寫、後送訊：送訊會失敗，寫檔是本機的，先把可查的那一份固定下來。
    """
    pending = write_pending(profile, issue, eid, home=home, reason=reason,
                            attempt=attempt, detail=detail, result=INDETERMINATE, at=at)
    text = failure_text(issue=issue, eid=eid, reason=reason, detail=detail,
                        pending_file=pending, receiver=profile)
    attempted: list[str] = []
    delivered_to: list[str] = []
    for thread in (str(topic_thread), str(general_thread)):
        attempted.append(thread)
        try:
            if send(thread, text):
                delivered_to.append(thread)
        except Exception:  # noqa: BLE001 — 送訊失敗不中斷，紀錄已落地
            continue
    return FailureExit(text, delivered_to, attempted, pending)


def busy_message(issue: str | int, *, receiver: str = RECEIVER_PROFILE) -> str:
    """忙碌的具名字面（供呼叫端單獨引用）。"""
    return BUSY_CMD_FMT.format(profile=receiver, issue=issue)


def describe() -> Iterable[str]:
    """一行一項的自述，給讀 log 的人。沒有副作用、不碰 forge。"""
    return (
        f"handback grammar：{HANDBACK_FMT}",
        f"ack grammar：{ACK_FMT}",
        f"done grammar：{DONE_FMT}",
        "四層：1 落地（寫入成功＋讀回恰一行）→ 2 投遞已發出 → 3 接收已確認（界線）→ 4 處理結果",
        f"EID：<issue>-<stage>-<basis>，basis 取既存觸發紀錄的 comment ID（{BASIS_FIELD}）",
        f"恢復三態：{RESUME_SAFE}／{RECORD_ONLY}／{INDETERMINATE}（未定一步都不重播）",
        f"待處理紀錄：~/.hermes/profiles/<profile>/{PENDING_DIRNAME}/<issue>-<EID>.json",
    )
