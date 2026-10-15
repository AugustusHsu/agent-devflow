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

**縫**（同 `devflow_relay.py:179` 的「縫只有一處」原則）：協定判定（`emit_handback`、
`landed`／`received`／`processed`、`recover`、`failure_exit` …）**一律吃注入的 `forge`／
`send`**，自己不碰 `subprocess`；真正打 `gh`／`hermes` 的只有**單一處** `_capture()`，
它只被 adapter（`GhForge`／`hermes_sender`）與本檔的 CLI 用，而且連那一處都可以注入
（relay 呼叫本檔時傳自己的 `_capture`，故整條產品路徑上仍只有 relay 那一個 `run`）。
檔案 I/O 走可注入的 `home`。故測試零真 API、零真子程序、零 forge 寫入——那是**測試
方式**，**不代表運行依賴不存在**（實際運行沿用 `gh` 與 `hermes send`）。

**接收端入口**：`_handback.py ack｜done｜recover｜pending`（見檔末 CLI）。relay 以
`--handback-event <EID>` 投遞時，把 EID 同時放進 `DEVFLOW_HANDBACK_EVENT` 與 prompt 的
前置通知裡，接收端因此拿得到**同一個**事件識別（`#313` 第 1 輪 `R1` `BLOCK 4`）。

落點為什麼是新檔、**不塞 `_marker.py`**：`_marker.py` 的自述逐字是「`CH3` 分區標記
grammar 的單一實作…`channels/README.md` 分區三態判定式的**實作**」——它整個存在理由是
那一條外部條文的實作。本協定與 `CH3` **分開、字面不共用**（見 `GRAMMAR` 那段），塞進去
不是擴寫定位，是讓它承載規範之外的東西。也**不搬動** `devflow_relay.py` 的 `handoff`
grammar（那是 relay 記自己行為的行，`#300`，零程式讀者）。

呼叫形狀與入口邊界見 `devflow/channels/telegram.md` 的「終態交回協調位」格。
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
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


def event_fields(eid: str) -> tuple[str, str, str]:
    """把 EID 切回 `(issue, stage, basis)`。不合形狀即 raise。

    切得開是 `EID_RE` 封死「三欄皆不得含 `-`」的用處（`#313` `AC-3`）：有了這個，行內
    **重複出現**的 `issue`／`stage` 就能與 EID **逐欄核對**，而不是各說各話。
    `#313` 第 1 輪 `R1` `BLOCK 3` 的現場：正確 EID 放在 `event=`、`issue=999`
    `stage=merge.done` 放在別的欄位，整行仍被判 `landed`——那正是 `R4` 的「正確值出現在
    錯誤位置」。
    """
    if not re.fullmatch(EID_RE, eid):
        raise HandbackError(f"EID 不合形狀，無法切欄：{eid!r}")
    issue, stage, basis = eid.split("-")
    return issue, stage, basis


def fields_match_event(event: str, issue: str | int, stage: str) -> tuple[bool, str]:
    """行內 `issue`／`stage` 是否與 EID 的對應欄相符。回 `(相符, 理由)`。

    `seat` **不在這裡核**：它不是 EID 的組成欄位，其約束是「宣告者恆為完成後處理的 mgr」
    ——那一條由 `declare_or_raise()`／`may_declare()` 在**寫入邊界**強制（`AC-1`）。
    """
    want_issue, want_stage, _ = event_fields(event)
    got_issue, got_stage = str(issue).strip().lower(), str(stage).strip().lower()
    if got_issue != want_issue:
        return False, (f"行內 issue={got_issue!r} 與 EID 的 issue={want_issue!r} 矛盾"
                       f"（event={event}）")
    if got_stage != want_stage:
        return False, (f"行內 stage={got_stage!r} 與 EID 的 stage={want_stage!r} 矛盾"
                       f"（event={event}）")
    return True, "ok"


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


def declare_or_raise(*, seat: str, kind: str, issue_closable: bool | None,
                     outstanding_children: int | None,
                     postprocess_done: bool | None) -> None:
    """寫 forge **之前**的宣告閘門。不成立即 raise，呼叫者因此不可能「寫了才發現不該寫」。

    為什麼要有這一層、而不是讓呼叫者自己先問 `may_declare()`（`#313` 第 1 輪 `R1`
    `BLOCK 1`）：第 1 輪的 `may_declare()` 判準正確、突變測試也過，但**真正寫 forge 的
    `emit_handback()` 根本不呼叫它**，於是 `seat=dfimpl` 照樣寫得出宣告行——「正確判準
    出現在錯誤位置」（`R4`）。判準必須長在**寫入邊界**上，否則它只是一個沒人問的意見。

    **宣告事實不得省略**：三項（`outstanding_children`／`issue_closable`／
    `postprocess_done`）皆為 `None` 時一律 raise，**不預設成樂觀值**——「不知道下游收完了
    沒」與「下游已收完」是兩件事，後者要有人負責說出來。
    """
    missing = [name for name, value in (("outstanding_children", outstanding_children),
                                        ("issue_closable", issue_closable),
                                        ("postprocess_done", postprocess_done))
               if value is None]
    if missing:
        raise HandbackError(
            f"宣告事實不得省略（`AC-1`）：缺 {missing}。"
            f"不知道下游收完了沒、本單可不可結、後處理做完了沒，就不得宣告交回"
            f"——這三項沒有樂觀預設值。")
    ok, reason = may_declare(outstanding_children=int(outstanding_children),
                             kind=kind, issue_closable=bool(issue_closable),
                             seat=seat, postprocess_done=bool(postprocess_done))
    if not ok:
        raise HandbackError(
            f"不得宣告交回（`AC-1`：{reason}）：seat={seat!r} kind={kind!r} "
            f"outstanding_children={outstanding_children!r} "
            f"issue_closable={issue_closable!r} postprocess_done={postprocess_done!r}。"
            f"宣告者恆為完成後處理的 `{DECLARER_SEAT}`；本次未寫任何東西。")


# ── 三行的組裝 ────────────────────────────────────────────────────────────────
def _now(at: str | None) -> str:
    return at if at else time.strftime(AT_FMT)


def handback_line(*, event: str, issue: str | int, seat: str, stage: str,
                  kind: str, outcome: str, at: str | None = None) -> str:
    """組層1 的 `handback` 行。組完**自己驗一次** grammar 與**欄位一致性**。

    一致性（`AC-3`，第 1 輪 `R1` `BLOCK 3`）：行內的 `issue`／`stage` 與 `event=` 的
    EID **逐欄核對**，矛盾即 raise。行內重複這兩欄是為了人讀，但重複的值如果可以和 EID
    各說各話，讀的人就無從知道哪一個才是真的——而機器只比 EID，於是矛盾的行照樣「成立」。
    """
    if kind not in KINDS:
        raise HandbackError(f"kind 須為 {KINDS} 之一，得到 {kind!r}")
    if outcome not in OUTCOMES:
        raise HandbackError(f"outcome 須為 {OUTCOMES} 之一，得到 {outcome!r}")
    same, why = fields_match_event(event, issue, stage)
    if not same:
        raise HandbackError(f"handback 行的欄位與 EID 矛盾，拒絕組出該行：{why}")
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
    """body 內屬於**這個事件**的 `handback` 行。**射程限定當前事件**（`AC-3`）。

    ⚠️ 只按 `event=` 選列，**不判**該列自身是否自相一致——一致性由 `landed()` 判，
    因為「有一列但它矛盾」與「沒有那一列」是兩個不同的理由，合併成一個布林會讓人看不出
    是哪一種（第 1 輪 `R1` `BLOCK 3`）。
    """
    return [m for m in HANDBACK_RE.finditer(body) if m.group("event") == eid]


def landed(body: str, eid: str) -> tuple[bool, str]:
    """層1：該 EID 的 `handback` 行在**讀回的** body 內**恰一行**，且該行**自相一致**。

    為什麼判準是「讀回且恰一行」而不是「`write→read` 呼叫序」（`#313` §2.1 的更正）：
    呼叫序只在**同一程序內的首發**可觀測；重送與接收端是**另一個程序**，它看不到別人的
    記憶體呼叫史，也不該為了取得觀測點去**重寫**一個已落地的事件。故義務**不對稱**——
    首發由 `emit_handback()` 保證「寫入成功 ＋ 讀回看得到」，重送／接收端一律以這個
    **可驗證的既存事件**為準。

    「恰一行」**不對整張 issue 的全歷史計數**：同一 issue 的**不同階段**可以合法交回多次
    （`r1.approve`、`merge.done` 各一行），全歷史計數會把第二次合法交回誤判成重複。

    **自相一致**（`AC-3`，第 1 輪 `R1` `BLOCK 3`）：行內 `issue`／`stage` 須與 EID 的對應
    欄相符。寫入端已經擋了（`handback_line()`），但讀回端**不能依賴寫入端**——`gh` 誰都能
    打，手寫或別的版本寫出來的矛盾行同樣會被讀到，判定端自己核才算判準。
    """
    hits = handback_rows(body, eid)
    if len(hits) != 1:
        return False, f"該事件的 handback 行數={len(hits)}（須恰 1，event={eid}）"
    row = hits[0]
    same, why = fields_match_event(eid, row.group("issue"), row.group("stage"))
    if not same:
        return False, f"該事件的 handback 行自相矛盾，不算落地：{why}"
    return True, "ok"


def received(body: str, eid: str, *, by: str = RECEIVER_PROFILE) -> bool:
    """層3：**指定接收端**寫下的持久 ack。界線在這裡——交接完成 ＝ 對方確認收到。

    `by` 必須是**指定的接收端**（`AC-2`，第 1 輪 `R1` `BLOCK 2`）：只比 EID 的版本會把
    任何人寫的 ack 都算成「對方收到了」——實跑 `by=dfimpl` 的 ack 曾讓 `received` 與
    `handoff_complete` 同時回 `True`。交接的完成界線是**那個指定的人**確認收到，不是
    「有人說了一聲」；誰都能算的話，執行位可以自己替協調位簽收。
    """
    return any(m.group("event") == eid and m.group("by") == by
               for m in ACK_RE.finditer(body))


def processed(body: str, eid: str, *, by: str = RECEIVER_PROFILE) -> bool:
    """層4：**指定接收端**寫下的處理結果。與層3 **分開**記；有 ack 無 done ＝ 還沒處理完。

    `by` 的理由同 `received()`：處理結果要由**負責處理的人**記，別人代記不算。
    """
    return any(m.group("event") == eid and m.group("by") == by
               for m in DONE_RE.finditer(body))


def done_result(body: str, eid: str, *, by: str = RECEIVER_PROFILE) -> str | None:
    """該事件 `done` 行的 `result`（無則 `None`）。同樣限定寫者為指定接收端。"""
    for m in DONE_RE.finditer(body):
        if m.group("event") == eid and m.group("by") == by:
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
                  body_text: str = "", outstanding_children: int | None = None,
                  issue_closable: bool | None = None,
                  postprocess_done: bool | None = None) -> Landing:
    """層1 首發：**宣告閘門** → 先讀（去重）→ 寫 → **讀回**驗「恰一行且自相一致」。

    **這是本模組唯一寫 `handback` 行的函式**，所以 `AC-1` 的宣告判準長在這裡（第 1 輪
    `R1` `BLOCK 1`）：`declare_or_raise()` 在**任何 forge 呼叫之前**執行，不成立即 raise，
    因此「非 mgr／尚有下游／後處理未完／`final` 不可結」四類**連 `forge.read()` 都不會
    發生**，更不可能 `forge.comment()`。宣告事實（`outstanding_children`／
    `issue_closable`／`postprocess_done`）**不得省略**——省略即 raise。

    `forge` 是注入的縫，只需兩個方法：`read() -> str`（該單目前所有可讀文字）與
    `comment(body)`（留一則）。協定判定不碰 `subprocess`；真 `gh` 的 adapter 是
    `GhForge`，它把兩個方法接到**單一處** `_capture()` 上。

    去重（`AC-3`）：寫入前先讀，該事件的行已存在就回 `skipped_exists`——**重試不產生
    第二行**，也**不重寫**已落地的行（`#313` §1.3）。`attempt` 不進行內，只進待處理紀錄。

    寫入失敗或讀回看不到 ＝ **層1 不成立**，回傳的 `landed` 為假，`deliver()` 會拒絕投遞。
    """
    # 宣告閘門在最前面：它不成立時，本函式**不得產生任何對外效果**。
    declare_or_raise(seat=seat, kind=kind, issue_closable=issue_closable,
                     outstanding_children=outstanding_children,
                     postprocess_done=postprocess_done)
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


def layers(body: str, eid: str, *, delivery: Delivery | None = None,
           by: str = RECEIVER_PROFILE) -> dict[int, bool]:
    """四層的當下狀態。層2 沒有 forge 上的對應物，故由 `delivery` 供給（缺 ＝ 未知為假）。

    層3／層4 限定寫者為 `by`（指定接收端，`AC-2`）。
    """
    return {
        1: landed(body, eid)[0],
        2: bool(delivery and delivery.sent),
        3: received(body, eid, by=by),
        4: processed(body, eid, by=by),
    }


def handoff_complete(body: str, eid: str, *, by: str = RECEIVER_PROFILE) -> bool:
    """**交接完成 ＝ 層1 ＋ 層3**。層4 另記，層2 不足以宣稱完成（`Popen` 不冒充接收）。"""
    return landed(body, eid)[0] and received(body, eid, by=by)


def pending_events(body: str, *, by: str = RECEIVER_PROFILE) -> list[str]:
    """尚未處理完的事件（有 `handback` 行而無 `done` 行）。已處理判準是 `done`，不是 `ack`。"""
    seen: list[str] = []
    for m in HANDBACK_RE.finditer(body):
        eid = m.group("event")
        if eid not in seen:
            seen.append(eid)
    return [e for e in seen if not processed(body, e, by=by)]


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


PRECONDITION_UNMET = "precondition_unmet"


def recover(forge: Any, eid: str, steps: Sequence[tuple[str, Callable[[str], Any]]],
            run: Callable[[str, str], Any], *, result: str = "recovered",
            by: str = RECEIVER_PROFILE, at: str | None = None) -> Recovery:
    """中斷後的恢復：**先核前置層次**，再對帳，再只跑讀回為未做的步驟，每一步執行後再讀回。

    四條硬界線：
      0. **前置層次（`AC-2`，第 1 輪 `R1` `BLOCK 2`）**：`done` 是層4，它只能記在層1～3
         之後。故 (i) **進場**先讀 forge，該 EID 的 `handback` 行不可讀回且唯一 → 判
         `precondition_unmet`、**一步都不跑**（替一個不存在的事件補步驟是在無中生有）；
         (ii) 寫 `done` **之前**再讀一次，要求層1 仍成立**且**層3（指定接收端的 ack）已
         成立，否則不寫。第 1 輪的實跑現場：空 forge 上 `recover()` 直接寫出層4，
         `layers` 為 `{1: False, 2: False, 3: False, 4: True}`。
         層2 沒有 forge 上的對應物，其成立由層3 **蘊含**——對方寫得出 ack，投遞必然發生過。
      1. `indeterminate` → `escalate_human`，**一步都不重播**（不得把讀不到當未做，也不得
         盲目重播整段 handler——那會重做已完成的步驟）。
      2. **失敗或未核實的動作不得產生 `done`**：`run()` 沒拋例外**不等於**做成了（裁決位
         反例 1：callback 回 `False`、外部狀態仍 `False`，舊寫法卻記了完成）。故每一步執行
         後都**對準本事件的目標**再讀回，不是 `True` 就 `escalate_human` 且**不寫 `done`**。
      3. `record_only` 時**不重做任何動作**，只補 `done` 紀錄。

    `run(name, eid)` 吃事件 id，理由同 `read_state` 的 probe。
    """
    def _snapshot() -> tuple[str | None, str]:
        try:
            return forge.read(), ""
        except Exception as exc:  # noqa: BLE001 — 讀不到就不假設，交人
            return None, f"forge 讀取失敗（{exc}）"

    body, why = _snapshot()
    if body is None:
        return Recovery(PRECONDITION_UNMET, {}, [], False,
                        f"前置層次無法核實：{why} → 一步都不跑、不寫 done")
    ok1, why1 = landed(body, eid)
    if not ok1:
        return Recovery(PRECONDITION_UNMET, {}, [], False,
                        f"層1 未成立（{why1}）→ 不得恢復、不得寫 done；一步都不跑")

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

    # 寫 done 前**再讀一次**：步驟可能剛改變了層3（例如本次才補寫 ack），而層1 也可能
    # 在這段時間被別人動過。以寫入當下的狀態為準，不以進場時的快照為準。
    body, why = _snapshot()
    if body is None:
        return Recovery(PRECONDITION_UNMET, report, ran, False,
                        f"寫 done 前無法核實前置層次：{why} → 不寫 done，交人")
    pre = layers(body, eid, by=by)
    if not (pre[1] and pre[3]):
        return Recovery(PRECONDITION_UNMET, report, ran, False,
                        f"前置層次未齊備（層1={pre[1]}、層3={pre[3]}，層3 須為 by={by} 的 ack）"
                        f"→ **不得寫 done**")
    if processed(body, eid, by=by):
        # 去重同 `emit_handback`：以**事件**為鍵，重跑不產生第二行（`AC-3`）。恢復本來就
        # 可能被跑很多次，每次都補一行 `done` 會讓同一個事件的處理結果出現 N 份。
        return Recovery(verdict, report, ran, True, "done 已存在，不寫第二行（以事件為鍵）")
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
# 待處理紀錄沒落地時，兩則告警裡要出現的字面（第 2 輪 `R1` `BLOCK 1`）。三處出口少了一處
# 這件事本身就是要被看見的訊息，不能只在回傳值裡。
PENDING_NOT_WRITTEN = "⚠️ 待處理紀錄**未落地**"

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


# 檔名三欄的合法字元（`#313` 第 2 輪 `R1` `BLOCK 2`）：`profile` 只收 ASCII 單字字元、
# `.` 與 `-`；路徑分隔符、`..`、空白一律不收。issue 只收數字、EID 須合 `EID_RE` **整串**。
_PROFILE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_ISSUE_RE = re.compile(r"[0-9]+")


def validate_pending_key(profile: str, issue: str | int, eid: str) -> tuple[str, str, str]:
    """把要拼進檔名的三欄驗過再回傳，不合即 raise（`AC-6`／`BLOCK 2`）。

    為什麼在這裡擋而不是只靠最後一道 `is_relative_to`：EID 來自**公開入口**
    （`devflow_relay.py --handback-event`、本檔 CLI 的 `--event`），`../../../escaped`
    這種值會讓待處理紀錄落在 `handback-pending` 外面——那個檔從此沒有 profile 歸屬、
    `pending` 子命令也列不到它，等於「結果未定」這件事被靜悄悄地丟掉（`AC-6` 正是在防
    這件事）。路徑拼接前先驗，比事後發現檔案在奇怪的地方好查。
    """
    bad: list[str] = []
    if not _PROFILE_RE.fullmatch(str(profile)):
        bad.append(f"profile={profile!r}（只收 ASCII 單字字元、`.`、`-`，不得含路徑分隔符）")
    if not _ISSUE_RE.fullmatch(str(issue)):
        bad.append(f"issue={issue!r}（只收數字）")
    if not re.fullmatch(EID_RE, str(eid)):
        bad.append(f"event={eid!r}（須合 EID grammar `<issue>-<stage>-<basis>` 整串）")
    if bad:
        raise HandbackError("待處理紀錄的鍵不合法，拒絕拼出路徑（`AC-6`）："
                            + "；".join(bad))
    return str(profile), str(issue), str(eid)


def pending_path(profile: str, issue: str | int, eid: str, *,
                 home: pathlib.Path) -> pathlib.Path:
    """`<…>/handback-pending/<issue>-<EID>.json`——**有 profile 與本單歸屬**。

    三欄先過 `validate_pending_key()`，拼完再加一道 `is_relative_to(root)` 的最後防線：
    驗證規則可能有人日後放寬，但「不得解析到 `handback-pending` 外」這條不該靠規則的
    周全度來保證（`#312` 的 `startswith` 教訓：前綴相同的**兄弟**目錄也會被誤判為在其下，
    故一律用 `resolve()` ＋ `is_relative_to`，不比字串）。
    """
    profile, issue, eid = validate_pending_key(profile, issue, eid)
    root = pending_dir(profile, home=home)
    path = root / f"{issue}-{eid}.json"
    if not path.resolve().is_relative_to(root.resolve()):
        raise HandbackError(f"待處理紀錄的路徑逃出 {PENDING_DIRNAME}，拒絕：{path}")
    return path


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
                 receiver: str = RECEIVER_PROFILE,
                 pending_error: str = "") -> str:
    """告警文字。一則同時送 topic 與 General，故字面只有一份、兩邊不會漂移。

    `pending_error`（第 2 輪 `R1` `BLOCK 1`）：待處理紀錄沒落地時，**告警自己要說出來**。
    否則收到告警的人會去翻一個不存在的檔，而「本機還有一份可查的紀錄」這個預設也就靜悄悄
    地失效了——三處出口裡少了一處，必須在剩下兩處的文字裡看得到。
    """
    lines = [f"⚠️ **終態交回失敗**：`#{issue}`　事件 `{eid}`",
             f"原因（`{reason}`）：{FAIL_REASONS.get(reason, reason)}"]
    if reason == "busy":
        lines.append("具名到 session：`" + BUSY_CMD_FMT.format(profile=receiver, issue=issue)
                     + "` 的同名 session 已有 chat 在跑")
    if detail:
        lines.append(f"現場：{detail}")
    if pending_error:
        lines.append(f"{PENDING_NOT_WRITTEN}：{pending_error}"
                     f"（本機沒有可查的那一份，只剩這則告警——請直接處置本事件）")
    elif pending_file:
        lines.append(f"待處理紀錄：`{pending_file}`")
    lines.append(NO_AUTO_RESUME)
    return "\n".join(lines)


class FailureExit(NamedTuple):
    text: str
    threads: list[str]                 # 實際送達（`send` 回真）的 thread
    attempted: list[str]               # 嘗試送出的 thread（含失敗者）
    pending_file: pathlib.Path | None   # 落地的待處理紀錄；`None` ＝ 沒寫成
    pending_error: str = ""             # 沒寫成的原因（空字串 ＝ 寫成了）

    @property
    def pending_written(self) -> bool:
        return self.pending_file is not None and not self.pending_error


def failure_exit(*, issue: str | int, eid: str, reason: str,
                 topic_thread: str, send: Callable[[str, str], Any],
                 home: pathlib.Path, profile: str = RECEIVER_PROFILE,
                 attempt: int = 1, detail: str = "", at: str | None = None,
                 general_thread: str = GENERAL_THREAD) -> FailureExit:
    """失敗出口：告警落**該單 topic ＋ General**，並寫**待處理紀錄**。

    三件事都要，缺一不可（`AC-6`）：**不得只留 stderr**（oneshot 下 stderr 沒有讀者，
    那正是本族缺陷的形狀，`#287` 的 5-byte log）、**不得只留 headless 最終回覆**
    （`#310` 的現場：寫得完整、沒有人收到）。

    **三處各自嘗試、各自記錄成敗，任何一處失敗都不短路**（第 2 輪 `R1` `BLOCK 1`）：
    先寫 pending 的版本有一個致命形狀——`home` 不是目錄、磁碟滿、權限不足時 `write_pending`
    會拋，於是 topic 與 General **連嘗試都沒有**，整個出口退化成只剩 stderr，正是本 AC
    要防的那件事。現在 pending 寫入失敗只是**一個獨立的壞消息**：它會寫進告警文字裡
    （讓收到告警的人知道「本機那份紀錄沒落地」），而兩則告警照送。
    反過來也一樣：送訊失敗不影響已落地的 pending。
    """
    pending: pathlib.Path | None = None
    pending_error = ""
    try:
        pending = write_pending(profile, issue, eid, home=home, reason=reason,
                                attempt=attempt, detail=detail,
                                result=INDETERMINATE, at=at)
    except Exception as exc:  # noqa: BLE001 — 寫不成就寫不成，不得吃掉另外兩處
        pending_error = f"{type(exc).__name__}: {exc}"
    text = failure_text(issue=issue, eid=eid, reason=reason, detail=detail,
                        pending_file=pending or "", receiver=profile,
                        pending_error=pending_error)
    attempted: list[str] = []
    delivered_to: list[str] = []
    for thread in (str(topic_thread), str(general_thread)):
        attempted.append(thread)
        try:
            if send(thread, text):
                delivered_to.append(thread)
        except Exception:  # noqa: BLE001 — 一處送訊失敗不影響另一處與 pending
            continue
    return FailureExit(text, delivered_to, attempted, pending, pending_error)


def busy_message(issue: str | int, *, receiver: str = RECEIVER_PROFILE) -> str:
    """忙碌的具名字面（供呼叫端單獨引用）。"""
    return BUSY_CMD_FMT.format(profile=receiver, issue=issue)


# ══════════════════════════════════════════════════════════════════════════════
# 產品路徑（`#313` 第 1 輪 `R1` `BLOCK 4`）
# ══════════════════════════════════════════════════════════════════════════════
# 第 1 輪的缺口不是判準錯，是**沒有人呼叫這些判準**：`--handback-event` 的 EID 只當布林
# 開關、接收端拿不到它；`failure_exit()`／ack／done 在 repo 內只有測試會呼叫；深度拒絕
# 只留 stderr。以下三段把路徑接起來——
#   relay 側（`devflow_relay.py` 的 `--handback-event` 分支）：把 EID 機械可讀地交給
#       接收端（環境變數 ＋ prompt 前置通知）、派子程序**之前**核層1、各失敗出口呼叫
#       `failure_exit()`。
#   接收端側（本檔的 CLI）：`ack`／`done`／`recover`／`pending` 四個子命令。
#   adapter：`GhForge`／`hermes_sender`，把 forge 與送訊接到**單一處** `_capture()`。
# ⚠️ 接收端 seat **是否真的呼叫** `ack` 屬操作層（`I7`），不在本單；本單只保證那條路
#    存在、可執行、且失敗時有可查的出口。**不新增**排程器、輪詢、watchdog 或鎖。

# 交付 EID 的兩條路（兩條都要，理由不同）：
#   環境變數——給程式讀（接收端的工具或下一支腳本可以直接取，不必解析自然語言）。
#   prompt 前置通知——給**模型**讀（oneshot 的 seat 只看得到 prompt；EID 不在 prompt 裡
#     就等於沒收到，第 1 輪的 `eid_in_child_cmd False` 即此）。
EVENT_ENV = "DEVFLOW_HANDBACK_EVENT"
# CLI 的腳本名：通知裡要給接收端**可照抄**的指令，故寫成 kit 內的相對路徑。
CLI_PATH = "devflow/channels/scripts/telegram/_handback.py"


def ack_command(issue: str | int, eid: str, *, thread: str | int,
                profile: str = RECEIVER_PROFILE, python: str = "/usr/bin/python3") -> str:
    """接收端寫 ack 的可照抄指令（層3）。"""
    return (f"{python} {CLI_PATH} ack --issue {issue} --event {eid} "
            f"--thread {thread} --by {profile}")


def done_command(issue: str | int, eid: str, *, thread: str | int, result: str = "handled",
                 profile: str = RECEIVER_PROFILE, python: str = "/usr/bin/python3") -> str:
    """接收端寫處理結果的可照抄指令（層4）。"""
    return (f"{python} {CLI_PATH} done --issue {issue} --event {eid} "
            f"--thread {thread} --result {result} --by {profile}")


def receiver_notice(issue: str | int, eid: str, *, thread: str | int,
                    profile: str = RECEIVER_PROFILE) -> str:
    """prompt 的前置通知：含 EID、ack／done 的指令、以及「它不代表整張單完成」的射程。

    一行以上但只有一個事實來源（`eid`），故 prompt 與環境變數**不可能**不一致：relay 由
    同一個值生成兩者，並在派子程序前以 `conflicting_event()` 核對呼叫者自帶的 prompt。
    """
    return (
        f"relay 終態投遞（`#313`）：本棒是交接事件 `{eid}`（`#{issue}`）的**最後一棒**，"
        f"之後沒有下一棒。\n"
        f"收到後**先**寫並讀回 ack（層3 ＝ 交接完成界線）：`{ack_command(issue, eid, thread=thread, profile=profile)}`\n"
        f"處理完再記結果（層4，**不代表整張 issue 完成、不授權合併**）："
        f"`{done_command(issue, eid, thread=thread, profile=profile)}`\n"
        f"事件識別同時放在環境變數 `{EVENT_ENV}`。"
    )


# prompt／環境裡出現的事件識別：**只認約定的結構化欄位**——`handback` 系三行的 `event=`
# 與 `DEVFLOW_HANDBACK_EVENT=`。**不掃散文裡裸寫的 EID**（第 2 輪 `R1` `BLOCK 3`，manager
# 取 (b)）：那會誤殺合法的 prompt——交接稿本來就常引用別單的事件識別當材料（「`#312` 的
# `312-…` 那次」），把任意提及當衝突會讓正當投遞被擋下。射程寫在 `telegram.md` 的值欄，
# 兩邊必須一致（`R7`）。
_EVENT_TOKEN_RE = re.compile(rf"(?:event=|{EVENT_ENV}=)(?P<eid>{EID_RE})")


def event_tokens(text: str) -> list[str]:
    """文字裡以 `event=`／`DEVFLOW_HANDBACK_EVENT=` 標示的事件識別（去重、保序）。

    ⚠️ **射程**：只認上面兩個前綴。散文裡裸寫的 ``313-r1.approve-…`` 不算（見上方註解）。
    """
    out: list[str] = []
    for m in _EVENT_TOKEN_RE.finditer(text or ""):
        if m.group("eid") not in out:
            out.append(m.group("eid"))
    return out


def conflicting_event(text: str, eid: str) -> str | None:
    """文字裡以約定欄位標示的**另一個**事件識別（有則回第一個，無則 `None`）。

    `--handback-event` 說這是事件 A 的最後一棒，而呼叫者給的 prompt 裡用 `event=` 標著
    事件 B：兩者必有一個是錯的，而**猜哪一個**會讓接收端替錯誤的事件簽收。故 relay 拒絕。

    ⚠️ **不是 EID 的全文搜尋**：散文裡提到另一個 EID 回 `None`（刻意，見上方註解）。
    這條防護擋的是「機械可讀的兩個值互相矛盾」，不是「文字裡有別的單號」。
    """
    return next((t for t in event_tokens(text) if t != eid), None)


# ── adapter：forge 與送訊的**單一處**出口 ──────────────────────────────────────
# 本模組的協定判定一律吃注入的 `forge`／`send`（故測試零真 API、零真子程序）；真正打
# `gh`／`hermes` 的只有下面這一處 `_capture()`，與 `devflow_relay.py:179` 的「縫只有一處」
# 同一個理由與同一種寫法。relay 呼叫本檔時**傳自己的 `_capture`**，所以整條產品路徑上
# 仍然只有 relay 那一個 `subprocess.run` 呼叫點。
# 具名 instance（群組 id）可由環境覆寫，寫法同 `devflow_topic.py:23`。
CHAT = os.environ.get("DEVFLOW_CHAT", "-1003546152597")
# `gh issue view` 的 jq：body **＋全部留言**——三行 grammar 住留言，只讀 body 讀不到。
GH_VIEW_JQ = ".body, (.comments[].body)"


def _capture(cmd: list[str], *, timeout: int = 60) -> Any:
    """跑一條短命指令並收回 stdout／stderr／rc。**本模組唯一的 `run` 呼叫點。**"""
    return subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL,
                          timeout=timeout, text=True)


class GhForge:
    """真 forge 的 adapter：`gh issue view --json body,comments` 讀、`gh issue comment` 寫。

    **不帶 `-R`**：repo 依 cwd 的 git remote 判定（同 `devflow_relay.py` 的
    `_write_handoff`——轉播器與本模組都不持有 repo 名）。`capture` 可注入，測試給假的。
    """

    def __init__(self, issue: str | int, *, capture: Callable[..., Any] | None = None) -> None:
        self.issue = str(issue)
        self._capture = capture or _capture
        self.calls: list[str] = []

    def read(self) -> str:
        self.calls.append("read")
        res = self._capture(["gh", "issue", "view", self.issue,
                             "--json", "body,comments", "-q", GH_VIEW_JQ])
        if getattr(res, "returncode", 0):
            raise HandbackError(
                f"讀不回 `#{self.issue}`：{(getattr(res, 'stderr', '') or '')[:200]}")
        return getattr(res, "stdout", "") or ""

    def comment(self, body: str) -> bool:
        self.calls.append("write")
        res = self._capture(["gh", "issue", "comment", self.issue, "--body", body])
        if getattr(res, "returncode", 0):
            raise HandbackError(
                f"寫不進 `#{self.issue}`：{(getattr(res, 'stderr', '') or '')[:200]}")
        return True


def hermes_sender(profile: str, *, chat: str = CHAT,
                  capture: Callable[..., Any] | None = None) -> Callable[[str, str], bool]:
    """送訊 adapter：`hermes -p <profile> send -t telegram:<chat>:<thread> --json <text>`。"""
    cap = capture or _capture

    def send(thread: str, text: str) -> bool:
        res = cap(["hermes", "-p", profile, "send",
                   "-t", f"telegram:{chat}:{thread}", "--json", text])
        return '"success": true' in (getattr(res, "stdout", "") or "")

    return send


# ── 接收端的入口（CLI）──────────────────────────────────────────────────────────
def ack_steps(forge: Any, *, eid: str, by: str, at: str | None = None
              ) -> tuple[list[tuple[str, Callable[[str], Any]]], Callable[[str, str], Any]]:
    """`recover` 用的協定步驟：唯一一步是「該事件的 ack 已由 `by` 寫下」。

    probe **向 forge 讀回**（不是讀記憶體裡的旗標），action 寫 ack；`recover()` 會在執行
    後再讀回同一個 probe，故「寫了但讀不回」不會被記成完成（`AC-4`）。
    """
    def probe(event: str) -> Any:
        return received(forge.read(), event, by=by)

    def run(name: str, event: str) -> Any:
        return forge.comment(ack_line(event=event, by=by, at=at) + "\n")

    return [("ack", probe)], run


def _fail(args, reason: str, detail: str = "") -> FailureExit:
    """CLI 的失敗出口：topic ＋ General ＋ 待處理紀錄（`AC-6`）。"""
    return failure_exit(issue=args.issue, eid=args.event, reason=reason,
                        topic_thread=str(args.thread),
                        send=hermes_sender(args.by, capture=_capture),
                        home=pathlib.Path(args.home), profile=args.by,
                        attempt=args.attempt, detail=detail)


def cmd_ack(args) -> int:
    """層3：依**收到的同一個 EID** 寫 ack 並**讀回**。層1 不成立即拒絕並走失敗出口。"""
    forge = GhForge(args.issue, capture=_capture)
    try:
        body = forge.read()
    except HandbackError as exc:
        print(f"[handback] 讀不回該單，層1 無法核實：{exc}", file=sys.stderr)
        print(_fail(args, "land_failed", str(exc)).text)
        return 2
    ok1, why1 = landed(body, args.event)
    if not ok1:
        print(f"[handback] 層1 未成立，拒絕寫 ack：{why1}", file=sys.stderr)
        print(_fail(args, "land_failed", why1).text)
        return 2
    if received(body, args.event, by=args.by):
        print(f"[handback] ack 已存在，不寫第二行：{args.event}")
        return 0
    try:
        forge.comment(ack_line(event=args.event, by=args.by, at=args.at) + "\n")
    except HandbackError as exc:
        print(f"[handback] ack 寫入失敗：{exc}", file=sys.stderr)
        print(_fail(args, "no_ack", str(exc)).text)
        return 1
    try:
        after = forge.read()
    except HandbackError as exc:
        print(f"[handback] ack 寫了但讀不回，結果未定：{exc}", file=sys.stderr)
        print(_fail(args, "indeterminate", str(exc)).text)
        return 1
    if not received(after, args.event, by=args.by):
        print("[handback] ack 寫了但讀回看不到（層3 未成立）", file=sys.stderr)
        print(_fail(args, "no_ack", "寫入後讀回看不到 ack").text)
        return 1
    print(f"[handback] 層3 成立（交接完成界線）：event={args.event} by={args.by}")
    return 0


def cmd_done(args) -> int:
    """層4：前置層次（層1 ＋ 層3）齊備才寫 done，寫後讀回。"""
    forge = GhForge(args.issue, capture=_capture)
    try:
        body = forge.read()
    except HandbackError as exc:
        print(f"[handback] 讀不回該單：{exc}", file=sys.stderr)
        print(_fail(args, "indeterminate", str(exc)).text)
        return 2
    pre = layers(body, args.event, by=args.by)
    if not (pre[1] and pre[3]):
        why = f"前置層次未齊備（層1={pre[1]}、層3={pre[3]}）→ 不得寫 done"
        print(f"[handback] {why}", file=sys.stderr)
        print(_fail(args, "no_ack" if pre[1] else "land_failed", why).text)
        return 2
    if processed(body, args.event, by=args.by):
        print(f"[handback] done 已存在，不寫第二行：{args.event}")
        return 0
    try:
        forge.comment(done_line(event=args.event, result=args.result,
                                by=args.by, at=args.at) + "\n")
        after = forge.read()
    except HandbackError as exc:
        print(f"[handback] done 寫入或讀回失敗，結果未定：{exc}", file=sys.stderr)
        print(_fail(args, "indeterminate", str(exc)).text)
        return 1
    if not processed(after, args.event, by=args.by):
        print("[handback] done 寫了但讀回看不到，結果未定", file=sys.stderr)
        print(_fail(args, "indeterminate", "寫入後讀回看不到 done").text)
        return 1
    print(f"[handback] 層4 已記（本交接事件的處理結果，不代表整張 issue 完成）："
          f"result={args.result}")
    return 0


def cmd_recover(args) -> int:
    """中斷後的恢復：對帳 → 只補未做的步驟（ack）→ 前置齊備才寫 done。結果未定一律交人。"""
    forge = GhForge(args.issue, capture=_capture)
    steps, run = ack_steps(forge, eid=args.event, by=args.by, at=args.at)
    rec = recover(forge, args.event, steps, run, result=args.result,
                  by=args.by, at=args.at)
    print(f"[handback] verdict={rec.verdict} ran={rec.ran} "
          f"done_written={rec.done_written} detail={rec.detail}")
    if rec.verdict in (RESUME_SAFE, RECORD_ONLY) and rec.done_written:
        ok, why = clear_pending(args.by, args.issue, args.event,
                                home=pathlib.Path(args.home), result=rec.verdict)
        print(f"[handback] 待處理紀錄：{'已清除' if ok else why}")
        return 0
    reason = "indeterminate" if rec.verdict in ("escalate_human", INDETERMINATE) else "land_failed"
    print(_fail(args, reason, rec.detail).text)
    return 1


def cmd_pending(args) -> int:
    """唯讀：列該 profile 的待處理紀錄，以及（給了 `--issue` 時）該單未處理完的事件。"""
    root = pending_dir(args.by, home=pathlib.Path(args.home))
    files = sorted(root.glob("*.json")) if root.exists() else []
    print(f"[handback] 待處理紀錄 {len(files)} 筆（{root}）")
    for path in files:
        try:
            rec = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            print(f"  ⚠️ {path.name}：讀不出來（{exc}）")
            continue
        print(f"  {path.name}：reason={rec.get('reason')} result={rec.get('result')} "
              f"attempt={rec.get('attempt')} at={rec.get('at')}")
    if args.issue:
        try:
            body = GhForge(args.issue, capture=_capture).read()
        except HandbackError as exc:
            print(f"[handback] 該單讀不回：{exc}", file=sys.stderr)
            return 2
        print(f"[handback] `#{args.issue}` 未處理完的事件："
              f"{pending_events(body, by=args.by) or '（無）'}")
    return 0


def build_parser():
    """CLI。`--home` 顯式可注入（測試不碰真的 `~/.hermes/profiles/`）。"""
    import argparse  # noqa: PLC0415 — 只有 CLI 需要它，import 進函式讓 library 用法不付代價

    ap = argparse.ArgumentParser(
        prog=CLI_PATH, description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, *, need_thread: bool = True):
        p.add_argument("--issue", required=True, help="單號")
        p.add_argument("--event", required=True, help="交接事件識別（EID）")
        p.add_argument("--thread", required=need_thread, default="",
                       help="該單 topic 的 thread id（失敗出口要送進去）")
        p.add_argument("--by", default=RECEIVER_PROFILE, help="接收端 profile（層3／層4 的寫者）")
        p.add_argument("--at", default=None, help="時刻（預設取本機時鐘）")
        p.add_argument("--attempt", type=int, default=1, help="第幾次嘗試（只進待處理紀錄）")
        p.add_argument("--home", default=str(pathlib.Path.home()),
                       help="待處理紀錄的 HOME（預設本機 HOME）")

    common(sub.add_parser("ack", help="寫並讀回 ack（層3 ＝ 交接完成界線）"))
    p_done = sub.add_parser("done", help="記本交接事件的處理結果（層4）")
    common(p_done)
    p_done.add_argument("--result", default="handled", help="處理結果（小寫英數與 `_`）")
    p_rec = sub.add_parser("recover", help="中斷後對帳並補未做的步驟（三態）")
    common(p_rec)
    p_rec.add_argument("--result", default="recovered", help="恢復後記的處理結果")
    p_pending = sub.add_parser("pending", help="唯讀：列待處理紀錄與未處理完的事件")
    p_pending.add_argument("--issue", default="", help="單號（給了才讀 forge）")
    p_pending.add_argument("--event", default="", help="（未用，與其餘子命令同形）")
    p_pending.add_argument("--thread", default="", help="（未用）")
    p_pending.add_argument("--by", default=RECEIVER_PROFILE, help="profile")
    p_pending.add_argument("--at", default=None, help="（未用）")
    p_pending.add_argument("--attempt", type=int, default=1, help="（未用）")
    p_pending.add_argument("--home", default=str(pathlib.Path.home()), help="HOME")
    return ap


COMMANDS = {"ack": cmd_ack, "done": cmd_done, "recover": cmd_recover, "pending": cmd_pending}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # 公開入口的鍵驗證（第 2 輪 `R1` `BLOCK 2`）：`--event`／`--issue`／`--by` 會被拼進
    # 待處理紀錄的路徑，`../../../escaped` 這種值在進任何一條程式路徑之前就要被擋掉。
    # `pending` 子命令只列目錄、不吃 EID，故只驗 profile（其 `--event` 是同形佔位）。
    try:
        if args.cmd == "pending":
            # `pending` 只列目錄、不吃 EID：拿一個固定的合法樣本填另兩欄，驗的是 profile。
            validate_pending_key(args.by, "0", "0-x-x")
        else:
            validate_pending_key(args.by, args.issue, args.event)
    except HandbackError as exc:
        print(f"[handback] 入口拒絕：{exc}", file=sys.stderr)
        return 2
    return COMMANDS[args.cmd](args)


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
        f"EID 交付：環境變數 {EVENT_ENV} ＋ prompt 前置通知（兩者由同一個值生成）",
        f"接收端入口：{CLI_PATH} ack｜done｜recover｜pending",
    )


if __name__ == "__main__":
    sys.exit(main())
