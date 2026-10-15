#!/usr/bin/env python3
"""`#313`／K4c-9：終態交回協定 `_handback.py` 的 `AC-1`～`AC-4` 與 `AC-6`。

直接執行：`/usr/bin/python3 tests/channels/test_handback.py`
全過 exit 0、任一項失敗 exit 非 0，stdout 逐項列 PASS／FAIL（風格同 `test_relay.py`）。

`AC-5`（入口邊界）**不在本檔**：它驗的是 `devflow_relay.py` 的 `main()` 行為，與既有的
`--issue`／`--then-wake`／深度三條拒絕同一支，故補在 `tests/channels/test_relay.py`
——正例與反例跑同一個驅動（`run_mod`），分檔會讓那四個入口組合各自有一套夾具（`I5`）。

**零真 API、零真子程序、零 forge 寫入**，而且這一點在本檔是**結構性**的，不是靠紀律：
受測模組**自己不 import `subprocess`／`urllib`／`socket`**（見本檔「縫」一節的源碼斷言），
forge 與送訊一律走呼叫者傳進來的物件（`FakeForge`／`FakeSend`），檔案 I/O 走可注入的
`home`（本檔的暫存目錄，不碰真的 `~/.hermes/profiles/`）。
⚠️ 「零真 API」是**測試方式**，**不代表運行依賴不存在**——實際運行沿用 `gh` 與 `hermes send`。

**反例一律實跑**（`L1`）：以 source 字串突變後 `importlib` 載入**另一個模組名**，再把
**同一個判定述詞**餵給產品模組與突變模組——產品回 `True`、突變回 `False`，兩者輸出不同
才算有鑑別力。本檔不在註解裡宣稱「這個反例會 FAIL」，每一條都跑過。

**本檔驗的是協定的判定，不是「交接真的完成了」**（射程界線）：`emit_handback` 只被餵假
forge，forge 上真的多了一行只有端到端那次能證；`channels/telegram.md` 該格的狀態欄因此
是 `⬜`（forge 側零實跑）。
"""
# 「同形斷言」判準（`#308` `AC-1`）全 repo 只一處（`I5`）：見
# `tests/channels/test_marker.py` **檔頂**的判準註解——寫新斷言前先讀那三項判準。
from __future__ import annotations

import ast
import importlib.util
import io
import json
import re
import shutil
import sys
import tempfile
import types
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.dont_write_bytecode = True          # 不在受測目錄留 __pycache__（repo 慣例）

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SCRIPTS = REPO / "devflow" / "channels" / "scripts" / "telegram"
HB_SRC_PATH = SCRIPTS / "_handback.py"
MARKER_SRC_PATH = SCRIPTS / "_marker.py"
RELAY_SRC_PATH = SCRIPTS / "devflow_relay.py"
TELEGRAM_MD = REPO / "devflow" / "channels" / "telegram.md"
VERSION_FILE = REPO / "devflow" / "VERSION"

HB_SRC = HB_SRC_PATH.read_text()
RELAY_SRC = RELAY_SRC_PATH.read_text()

# 本檔自己的暫存目錄：待處理紀錄要落在一個**假的 HOME** 下，不能碰真的
# `~/.hermes/profiles/`（那是活體 profile，`C3`）。收尾整個刪掉。
TESTTMP = Path(tempfile.mkdtemp(prefix="devflow-test_handback."))
FAKE_HOME = TESTTMP / "home"

RESULTS: list[tuple[str, bool, str]] = []
FIXED_AT = "2026-10-15T23:50:00+0800"


def check(label: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((label, bool(ok), detail))
    print(("  ✅ " if ok else "  ❌ ") + label)
    if not ok and detail:
        print(f"      → {detail}")
    return bool(ok)


# ── 載入受測模組 ─────────────────────────────────────────────────────────────
# 零 import-path 操作：以 `importlib.util.spec_from_file_location` 從 repo 真實目錄載入。
# `_handback.py` 沒有同層 import（刻意：它不依賴 `_marker.py`，兩族字面分開），
# 故連 `sys.modules` 登錄都不需要。
def load_file(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_mutant(src: str, name: str):
    """把突變後的 source 寫進本檔的暫存目錄、以另一個模組名載入（形狀同 `test_relay.py`）。"""
    path = TESTTMP / f"{name}.py"
    path.write_text(src)
    return load_file(path, name)


def mutate(src: str, old: str, new: str) -> str:
    """字串突變。錨點須**恰一處**命中——漂移時回傳原文，由「突變確實套上」那條報出，
    不靜默變成 no-op（no-op 的反例會假 PASS，那正是反例要防的事）。"""
    return src.replace(old, new, 1) if src.count(old) == 1 else src


hb = load_file(HB_SRC_PATH, "_handback")
_marker = load_file(MARKER_SRC_PATH, "_marker_ro")


def raises(fn, exc=None) -> bool:
    """`fn()` 是否拋出預期的例外（預設 `HandbackError`）。"""
    want = exc or hb.HandbackError
    try:
        fn()
    except want:
        return True
    except Exception:  # noqa: BLE001 — 拋錯型別不對也算不成立
        return False
    return False


class FakeForge:
    """假 forge：只記留言並回放。`fail_write`／`fail_read`／`swallow` 造層1 的三種失敗。

    真實的縫是 `gh issue comment` 與 `gh issue view --json body`，但那兩條指令由**呼叫端**
    發（`_handback.py` 自己不碰 `subprocess`），故本檔連假的 `subprocess` 都不需要。
    """

    def __init__(self, *, fail_write: bool = False, fail_read: bool = False,
                 swallow: bool = False) -> None:
        self.comments: list[str] = []
        self.calls: list[str] = []
        self.fail_write = fail_write
        self.fail_read = fail_read
        self.swallow = swallow          # 寫入「成功」但內容沒落地（讀回看不到）

    def comment(self, body: str) -> int:
        self.calls.append("write")
        if self.fail_write:
            raise RuntimeError("gh: rate limited")
        if not self.swallow:
            self.comments.append(body)
        return len(self.comments)

    def read(self) -> str:
        self.calls.append("read")
        if self.fail_read:
            raise RuntimeError("gh: API down")
        return "\n".join(self.comments)


def seeded(*, eid: str, ack: bool = True, mod=hb, **kw) -> FakeForge:
    """造一個**前置層次已齊備**的假 forge：層1（handback 行）＋ 可選的層3（ack）。

    `recover()` 自第 2 輪起有前置閘門（`AC-2`，`R1` `BLOCK 2`）：進場要層1 可讀回且唯一、
    寫 `done` 前還要層3 成立。恢復的語意是「把**中斷的交接**接完」，不是「無中生有一個
    事件」——第 1 輪可以在**空 forge** 上直接寫出層4，`layers` 為
    `{1: False, 2: False, 3: False, 4: True}`，那正是本節的夾具要防的事。
    行用產品模組生成（不在測試裡重打字面）。
    """
    forge = FakeForge(**kw)
    issue, stage, _ = mod.event_fields(eid)
    forge.comments.append(mod.handback_line(event=eid, issue=issue, seat="dfmgr",
                                            stage=stage, kind="stage", outcome="done",
                                            at=FIXED_AT))
    if ack:
        forge.comments.append(mod.ack_line(event=eid, at=FIXED_AT))
    return forge


class FakeSend:
    """假送訊：記下 (thread, text)。`dead` 內的 thread 一律失敗（送訊失敗不中斷）。"""

    def __init__(self, dead: tuple[str, ...] = ()) -> None:
        self.sent: list[tuple[str, str]] = []
        self.dead = dead

    def __call__(self, thread: str, text: str) -> bool:
        self.sent.append((thread, text))
        if thread in self.dead:
            raise RuntimeError("hermes send: chat not found")
        return True

    @property
    def threads(self) -> list[str]:
        return [t for t, _ in self.sent]


# 宣告事實的「可宣告」預設值（`AC-1`）：下游全收、後處理完成、本單尚不可結（`stage`）。
# 每個案例只覆寫它要動的那一項，其餘維持可宣告——否則看不出是哪一條判準擋下的。
DECLARABLE = dict(outstanding_children=0, issue_closable=False, postprocess_done=True)


def emit(forge, mod=hb, *, eid, issue=313, seat="dfmgr", stage="r1.approve",
         kind="stage", outcome="done", at=FIXED_AT, **declare):
    facts = {**DECLARABLE, **declare}
    return mod.emit_handback(forge, event=eid, issue=issue, seat=seat, stage=stage,
                             kind=kind, outcome=outcome, at=at, **facts)


def under(root, path) -> bool:
    """`path` 是否位於 `root` 這個目錄**階層**之下（含 root 自身）。

    不用字串前綴（同 `test_relay.py` 的 `_under`，`#312` `AC-8(a)` 的實測）：
    `…/x` 與 `…/x-tmp` 互為前綴卻是兄弟目錄，階層關係只有逐段比對答得對。
    """
    try:
        return Path(path).resolve().is_relative_to(Path(root).resolve())
    except ValueError:
        return False


# ══════════════════════════════════════════════════════════════════════════
print("\n── grammar：三行、獨立一行、與 `CH3`／`handoff` 字面分開")
# ══════════════════════════════════════════════════════════════════════════
EID = hb.event_id(313, "r1.approve", "6067812345")
L_HB = hb.handback_line(event=EID, issue=313, seat="dfmgr", stage="r1.approve",
                        kind="stage", outcome="done", at=FIXED_AT)
L_ACK = hb.ack_line(event=EID, by="dfcoord", at=FIXED_AT)
L_DONE = hb.done_line(event=EID, result="merged", by="dfcoord", at=FIXED_AT)
HANDOFF_LINE = "<!-- devflow:handoff profile=dfmgr at=2026-10-15T23:50:00+0800 rc=0 -->"

check("grammar 三行各自合自己的式（獨立一行、錨行首行尾）",
      bool(hb.HANDBACK_RE.fullmatch(L_HB)) and bool(hb.ACK_RE.fullmatch(L_ACK))
      and bool(hb.DONE_RE.fullmatch(L_DONE)),
      f"{L_HB!r} / {L_ACK!r} / {L_DONE!r}")
check("grammar 三式互不誤命中（ack／done 的行不被 handback 式吃掉，反之亦然）",
      not hb.HANDBACK_RE.search(L_ACK) and not hb.HANDBACK_RE.search(L_DONE)
      and not hb.ACK_RE.search(L_HB) and not hb.ACK_RE.search(L_DONE)
      and not hb.DONE_RE.search(L_HB) and not hb.DONE_RE.search(L_ACK),
      f"{L_HB!r} / {L_ACK!r} / {L_DONE!r}")
check("grammar 三個字面互不為子字串（名稱後的補白使 `handback ` 不是另兩行的前綴）",
      all(a not in b for a in (L_HB, L_ACK, L_DONE)
          for b in (L_HB, L_ACK, L_DONE) if a is not b)
      and "<!-- devflow:handback " not in L_ACK
      and "<!-- devflow:handback " not in L_DONE,
      f"{L_HB[:44]!r} / {L_ACK[:44]!r} / {L_DONE[:44]!r}")
# 表格列內、散文或縮排裡的同形字串不得命中（同 `CH3` 判定式錨行首行尾的理由）。
check("非獨立一行者不命中（表格列、縮排、行內前置文字）",
      not hb.HANDBACK_RE.search(f"| {L_HB} |")
      and not hb.HANDBACK_RE.search(f"    {L_HB}")
      and not hb.HANDBACK_RE.search(f"見 {L_HB}")
      and bool(hb.HANDBACK_RE.search(f"前文\n{L_HB}\n後文")),
      "錨定或多行模式失效")

_body_with_hb = f"# 單\n\n{L_HB}\n{L_ACK}\n{L_DONE}\n"
check("與 `CH3` 分開：`_marker.py` 的 `TOPIC_RE`／`ARCHIVED_RE` 對三行皆零命中（`T`／`A` 不變）",
      len(re.findall(_marker.TOPIC_RE, _body_with_hb, re.M)) == 0
      and len(re.findall(_marker.ARCHIVED_RE, _body_with_hb, re.M)) == 0,
      f"T={len(re.findall(_marker.TOPIC_RE, _body_with_hb, re.M))} "
      f"A={len(re.findall(_marker.ARCHIVED_RE, _body_with_hb, re.M))}")
check("與 `#300` 的 `handoff` 行分開：三式對它零命中，且字面互不為子字串（本單不搬那條 grammar）",
      not hb.HANDBACK_RE.search(HANDOFF_LINE) and not hb.ACK_RE.search(HANDOFF_LINE)
      and not hb.DONE_RE.search(HANDOFF_LINE)
      and "devflow:handoff" not in L_HB and "devflow:handoff" not in L_ACK
      and "devflow:handoff" not in L_DONE
      and "devflow:handback" not in HANDOFF_LINE,
      f"handoff={HANDOFF_LINE!r}")
check("`devflow_relay.py` 的 `handoff` grammar 常數一字未動（本單不搬動既有 grammar）",
      'HANDOFF_FMT = "<!-- devflow:handoff profile={profile} at={at} rc={rc} -->"' in RELAY_SRC
      and "devflow:handback" not in RELAY_SRC.split("def main(")[0],
      "relay 的 HANDOFF_FMT 被改動，或 handback 字面被塞進 relay 的模組層")
check("`attempt` 不在行內（§1.3：重試不改動已落地事件的不可變內容）",
      "attempt" not in L_HB and "attempt" not in hb.HANDBACK_FMT,
      f"行={L_HB!r}")
check("`attempt` 住待處理紀錄（`write_pending` 的 payload 有它）",
      '"attempt"' in HB_SRC.split("def write_pending")[1].split("def read_pending")[0],
      "write_pending 的 payload 沒有 attempt 欄")
check("組裝自驗 grammar：kind／outcome 不合即 raise（寫出去才發現讀不回已太晚）",
      raises(lambda: hb.handback_line(event=EID, issue=313, seat="dfmgr",
                                      stage="r1.approve", kind="FINAL",
                                      outcome="done", at=FIXED_AT))
      and raises(lambda: hb.handback_line(event=EID, issue=313, seat="dfmgr",
                                          stage="r1.approve", kind="stage",
                                          outcome="approved", at=FIXED_AT)),
      "不合法的 kind／outcome 沒有被擋下")


# ══════════════════════════════════════════════════════════════════════════
print("\n── AC-1：宣告判準（下游未收 → 不得宣告；stage／final 分流；後處理不得被跳過）")
# ══════════════════════════════════════════════════════════════════════════
# 五個固定情境，表驅動。期望值寫在表裡，正例與反例（突變模組）跑**同一張表**。
AC1_CASES = [
    (dict(outstanding_children=1, kind="stage", issue_closable=False), False,
     "downstream_running", "下游仍在跑 → 不得宣告（stage）"),
    (dict(outstanding_children=2, kind="final", issue_closable=True), False,
     "downstream_running", "下游仍在跑 → 不得宣告（final，連本單可結也不例外）"),
    (dict(outstanding_children=0, kind="stage", issue_closable=False), True,
     "ok", "本階段結束、無下游 → 可宣告 stage"),
    (dict(outstanding_children=0, kind="final", issue_closable=False), False,
     "not_final_yet", "本階段結束但本單未完 → 不得宣告 final"),
    (dict(outstanding_children=0, kind="final", issue_closable=True), True,
     "ok", "下游全收 ＋ 本單可結 → 可宣告 final"),
]


def ac1_table(mod) -> list[tuple[bool, str]]:
    return [mod.may_declare(**kw) for kw, _, _, _ in AC1_CASES]


for _kw, _want, _why, _label in AC1_CASES:
    _ok, _reason = hb.may_declare(**_kw)
    check(f"AC-1 {_label}",
          _ok is _want and _reason == _why,
          f"得到 ({_ok}, {_reason!r})，期望 ({_want}, {_why!r})")

check("AC-1 宣告者恆為 mgr：非 `DECLARER_SEAT` 的 seat 一律不得宣告（coder／reviewer 不自行交回）",
      hb.may_declare(outstanding_children=0, kind="stage", issue_closable=False,
                     seat="dfimpl") == (False, "not_declarer")
      and hb.may_declare(outstanding_children=0, kind="stage", issue_closable=False,
                         seat="dfrev") == (False, "not_declarer")
      and hb.DECLARER_SEAT == "dfmgr",
      f"dfimpl={hb.may_declare(outstanding_children=0, kind='stage', issue_closable=False, seat='dfimpl')!r}")
check("AC-1 後處理不得被跳過：`postprocess_done=False` → 不得宣告（push／PR／派審未完成）",
      hb.may_declare(outstanding_children=0, kind="stage", issue_closable=False,
                     postprocess_done=False) == (False, "postprocess_pending"),
      f"得到 {hb.may_declare(outstanding_children=0, kind='stage', issue_closable=False, postprocess_done=False)!r}")
check("AC-1 下游判準優先於其餘三條（下游還在跑時連 seat／後處理都不必問）",
      hb.may_declare(outstanding_children=1, kind="stage", issue_closable=True,
                     seat="dfimpl", postprocess_done=False) == (False, "downstream_running"),
      "理由不是 downstream_running ＝ 判準順序錯")
check("AC-1 不合法輸入 raise（kind 錯字、負的子程序數）",
      raises(lambda: hb.may_declare(outstanding_children=0, kind="done",
                                    issue_closable=True))
      and raises(lambda: hb.may_declare(outstanding_children=-1, kind="stage",
                                        issue_closable=True)),
      "不合法輸入沒有被擋下")

# ── 反例（實跑）：三種被否決的寫法 ──
AC1_DOWNSTREAM = """    if outstanding_children > 0:
        return False, "downstream_running"
"""
AC1_FINAL = """    if kind == "final" and not issue_closable:
        return False, "not_final_yet"
"""
AC1_SEAT = """    if seat != DECLARER_SEAT:
        return False, "not_declarer"
"""
AC1_POST = """    if not postprocess_done:
        return False, "postprocess_pending"
"""
MUT_AC1_SELFONLY = mutate(HB_SRC, AC1_DOWNSTREAM, '    if False:\n        return False, "downstream_running"\n')
MUT_AC1_NOFINAL = mutate(HB_SRC, AC1_FINAL, '    if False and not issue_closable:\n        return False, "not_final_yet"\n')
MUT_AC1_ANYSEAT = mutate(mutate(HB_SRC, AC1_SEAT, '    if False:\n        return False, "not_declarer"\n'),
                         AC1_POST, '    if False:\n        return False, "postprocess_pending"\n')
check("AC-1 三種突變確實套上（錨點各恰一處命中）",
      MUT_AC1_SELFONLY != HB_SRC and MUT_AC1_NOFINAL != HB_SRC
      and MUT_AC1_ANYSEAT != HB_SRC,
      "錨點漂移：某個突變沒有套上去（no-op 的反例會假 PASS）")

_m1a = load_mutant(MUT_AC1_SELFONLY, "_hb_mut_selfonly")
_m1b = load_mutant(MUT_AC1_NOFINAL, "_hb_mut_nofinal")
_m1c = load_mutant(MUT_AC1_ANYSEAT, "_hb_mut_anyseat")
_want = [(w, y) for _, w, y, _ in AC1_CASES]
check("AC-1 反例①「只看自己這輪結束了沒」→ 下游仍在跑的兩例轉為放行（實跑對照）",
      ac1_table(hb) == _want
      and [r[0] for r in ac1_table(_m1a)][:2] == [True, True]
      and ac1_table(_m1a) != _want,
      f"突變表={ac1_table(_m1a)!r}")
check("AC-1 反例②「final 不另判本單可結」→ `stage`／`final` 分流消失（實跑對照）",
      ac1_table(_m1b)[3][0] is True and ac1_table(hb)[3] == (False, "not_final_yet"),
      f"突變第 4 例={ac1_table(_m1b)[3]!r}")
check("AC-1 反例③「任何 seat 都能宣告、後處理不必完成」→ coder 自行交回被放行（實跑對照）",
      _m1c.may_declare(outstanding_children=0, kind="stage", issue_closable=False,
                       seat="dfimpl", postprocess_done=False)[0] is True
      and hb.may_declare(outstanding_children=0, kind="stage", issue_closable=False,
                         seat="dfimpl", postprocess_done=False)[0] is False,
      f"突變={_m1c.may_declare(outstanding_children=0, kind='stage', issue_closable=False, seat='dfimpl', postprocess_done=False)!r}")


# ══════════════════════════════════════════════════════════════════════════
print("\n── AC-2：完成判準分層（層1 落地 → 層2 投遞 → 層3 接收 → 層4 處理）")
# ══════════════════════════════════════════════════════════════════════════
fg = FakeForge()
land = emit(fg, eid=EID)
check("AC-2 層1 首發：寫入成功 ＋ 讀回看得到該事件（恰一行）",
      land.status == "written" and land.landed is True
      and hb.landed(fg.read(), EID)[0] is True,
      f"landing={land!r} body={fg.read()!r}")
check("AC-2 層1 的順序是「先讀（去重）→ 寫 → 讀回」（呼叫序可觀測）",
      fg.calls[:3] == ["read", "write", "read"], f"calls={fg.calls!r}")

fg_w = FakeForge(fail_write=True)
land_w = emit(fg_w, eid=EID)
check("AC-2 層1 反例：forge 寫入失敗 → 不算落地",
      land_w.landed is False and land_w.status == "write_failed",
      f"landing={land_w!r}")

fg_s = FakeForge(swallow=True)
land_s = emit(fg_s, eid=EID)
check("AC-2 層1 反例：寫入「成功」但讀回看不到 → 不算落地（寫入成功不足，須讀回）",
      land_s.landed is False and land_s.status == "readback_failed",
      f"landing={land_s!r}")

fg_r = FakeForge(fail_read=True)
land_r = emit(fg_r, eid=EID)
check("AC-2 層1 反例：讀回本身失敗 → 不算落地（讀不到不是落地的證據）",
      land_r.landed is False and land_r.status == "readback_failed",
      f"landing={land_r!r}")

# 層1 失敗不得進層2：`spawn` 連呼叫都不該發生（哨兵反證）。
spawned: list[str] = []
dv_refused = hb.deliver(land_w, lambda: spawned.append("x") or 4242)
check("AC-2 層1 失敗不得進層2：`deliver` 拒絕，且 `spawn` 一次都沒被呼叫（哨兵反證）",
      dv_refused.sent is False and dv_refused.status == "refused_not_landed"
      and dv_refused.spawn_called is False and spawned == [],
      f"delivery={dv_refused!r} spawned={spawned!r}")

dv = hb.deliver(land, lambda: 4242)
check("AC-2 層2：層1 成立後投遞已發出（spawn 回 pid）",
      dv.sent is True and dv.status == "sent" and dv.spawn_called is True,
      f"delivery={dv!r}")
check("AC-2 層2 反例：`spawn` 失敗（拋例外／回 None）→ 投遞未成立",
      hb.deliver(land, lambda: (_ for _ in ()).throw(RuntimeError("boom"))).sent is False
      and hb.deliver(land, lambda: None).sent is False,
      "spawn 失敗仍被當成已投遞")

check("AC-2 **`Popen` 成功不得冒充層3**：已投遞而無 ack → 未接收、交接未完成",
      dv.sent is True and hb.received(fg.read(), EID) is False
      and hb.handoff_complete(fg.read(), EID) is False
      and hb.layers(fg.read(), EID, delivery=dv) == {1: True, 2: True, 3: False, 4: False},
      f"layers={hb.layers(fg.read(), EID, delivery=dv)!r}")

fg.comment(hb.ack_line(event=EID, at=FIXED_AT) + "\n")
check("AC-2 層3 ＝ 交接完成界線：持久 ack 落地後交接完成，而層4 仍未成立",
      hb.received(fg.read(), EID) is True and hb.handoff_complete(fg.read(), EID) is True
      and hb.processed(fg.read(), EID) is False,
      f"layers={hb.layers(fg.read(), EID, delivery=dv)!r}")

fg.comment(hb.done_line(event=EID, result="merged", at=FIXED_AT) + "\n")
check("AC-2 層4 處理結果另記（`result` 讀得回，且與層3 分開）",
      hb.processed(fg.read(), EID) is True
      and hb.done_result(fg.read(), EID) == "merged"
      and hb.layers(fg.read(), EID, delivery=dv) == {1: True, 2: True, 3: True, 4: True},
      f"layers={hb.layers(fg.read(), EID, delivery=dv)!r}")
check("AC-2 層2 不是 forge 上的東西：`layers` 不給 delivery 時層2 為假（不憑空宣稱已投遞）",
      hb.layers(fg.read(), EID)[2] is False and hb.layers(fg.read(), EID)[3] is True,
      f"layers={hb.layers(fg.read(), EID)!r}")

# ── 反例（實跑）：兩種把層3 說成成立的寫法 ──
AC2_RECEIVED = ('    return any(m.group("event") == eid and m.group("by") == by\n'
                "               for m in ACK_RE.finditer(body))\n")
AC2_GATE = """    if not landing.landed:
        return Delivery("refused_not_landed", False, False,
                        f"層1 未成立（{landing.status}：{landing.detail}），不得進層2")
"""
MUT_AC2_SENTOK = mutate(HB_SRC, AC2_RECEIVED, "    return bool(handback_rows(body, eid))\n")
MUT_AC2_NOGATE = mutate(HB_SRC, AC2_GATE, "    if False:\n        pass\n")
check("AC-2 兩種突變確實套上（錨點各恰一處命中）",
      MUT_AC2_SENTOK != HB_SRC and MUT_AC2_NOGATE != HB_SRC,
      "錨點漂移：某個突變沒有套上去")

_m2a = load_mutant(MUT_AC2_SENTOK, "_hb_mut_sentok")
fg2a = FakeForge()
emit(fg2a, eid=EID)
check("AC-2 反例①「送出即算接收」→ 無 ack 時突變判已接收、產品判未接收（實跑對照）",
      _m2a.received(fg2a.read(), EID) is True and hb.received(fg2a.read(), EID) is False
      and _m2a.handoff_complete(fg2a.read(), EID) is True
      and hb.handoff_complete(fg2a.read(), EID) is False,
      f"突變 received={_m2a.received(fg2a.read(), EID)}")

_m2b = load_mutant(MUT_AC2_NOGATE, "_hb_mut_nogate")
spawned_mut: list[str] = []
_land_w_mut = emit(FakeForge(fail_write=True), _m2b, eid=EID)
_dv_mut = _m2b.deliver(_land_w_mut, lambda: spawned_mut.append("x") or 4242)
check("AC-2 反例②「層1 失敗仍投遞」→ 突變下 spawn 被呼叫、產品下一次都沒有（實跑對照）",
      _land_w_mut.landed is False and _dv_mut.sent is True and spawned_mut == ["x"]
      and spawned == [],
      f"突變 spawned={spawned_mut!r} delivery={_dv_mut!r}")

# ── 縫：協定判定不碰外部世界，真 `gh`／送訊集中在單一處 ──
# 第 2 輪起（`R1` `BLOCK 4`）本模組多了**產品路徑**：`GhForge`／`hermes_sender` 兩個
# adapter 與接收端 CLI，它們必須真的打 `gh`／`hermes`。故判準從「整個模組不 import
# subprocess」收窄為**「縫只有一處」**（同 `devflow_relay.py:179` 的原則）：
#   (i) `subprocess` 的呼叫點恰一個，且在 `_capture()` 內；
#   (ii) 協定判定（`emit_handback`／`landed`／`received`／`recover`／`failure_exit`）
#        的函式體內一個 `subprocess`／`_capture` 都沒有——它們只吃注入的 `forge`／`send`；
#   (iii) adapter 的 `capture` 可注入（relay 傳自己的 `_capture`，整條路徑仍只有一個 run）。
# 判定走 **AST**，不是字串搜尋：docstring 裡刻意寫著這些詞，字串搜尋會把自述當成違規。
_HB_TREE = ast.parse(HB_SRC)


def _module_imports(tree) -> list[str]:
    """該模組 import 進來的**頂層模組名**（`import a.b` → `a`、`from a.b import c` → `a`）。"""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    return sorted(names)


_HB_IMPORTS = _module_imports(_HB_TREE)
_HB_ALLOWED = {"__future__", "argparse", "json", "os", "pathlib", "re", "subprocess",
               "sys", "time", "collections", "typing"}
_HB_FUNCS = {n.name: n for n in ast.walk(_HB_TREE)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
_HB_SUBPROC_CALLS = [ast.unparse(n.func) for n in ast.walk(_HB_TREE)
                     if isinstance(n, ast.Call) and "subprocess" in ast.unparse(n.func)]
_HB_SUBPROC_IN_CAPTURE = [ast.unparse(n.func) for n in ast.walk(_HB_FUNCS["_capture"])
                          if isinstance(n, ast.Call) and "subprocess" in ast.unparse(n.func)]
_HB_PROTOCOL = ("emit_handback", "landed", "received", "processed", "recover",
                "reconcile", "read_state", "failure_exit", "write_pending",
                "clear_pending", "may_declare", "declare_or_raise", "handback_line")
_HB_DIRTY = {name: [ast.unparse(c.func) for c in ast.walk(_HB_FUNCS[name])
                    if isinstance(c, ast.Call)
                    and any(t in ast.unparse(c.func)
                            for t in ("subprocess", "_capture", "urlopen", "socket"))]
             for name in _HB_PROTOCOL}
check("AC-2 縫：受測模組只 import 標準庫，且無 urllib／socket／requests（AST 判定）",
      set(_HB_IMPORTS) <= _HB_ALLOWED,
      f"import={_HB_IMPORTS!r} 超出={sorted(set(_HB_IMPORTS) - _HB_ALLOWED)!r}")
check("AC-2 縫：`subprocess` 的呼叫點**恰一個**，且在 `_capture()` 內（縫只有一處）",
      len(_HB_SUBPROC_CALLS) == 1 and len(_HB_SUBPROC_IN_CAPTURE) == 1,
      f"全檔={_HB_SUBPROC_CALLS!r} `_capture` 內={_HB_SUBPROC_IN_CAPTURE!r}")
check("AC-2 縫：協定判定的函式體內一個 `subprocess`／`_capture` 呼叫都沒有（只吃注入的縫）",
      all(v == [] for v in _HB_DIRTY.values()),
      f"命中={ {k: v for k, v in _HB_DIRTY.items() if v} !r}")
check("AC-2 縫：forge 與送訊都是注入的參數，adapter 的 `capture` 也可注入",
      "forge: Any" in HB_SRC and "send: Callable[[str, str], Any]" in HB_SRC
      and "capture: Callable[..., Any] | None = None" in HB_SRC,
      "forge／send／capture 不是注入的縫")


# ══════════════════════════════════════════════════════════════════════════
print("\n── AC-3：事件識別與去重（EID 由 issue ＋ stage ＋ 既有觸發紀錄導出）")
# ══════════════════════════════════════════════════════════════════════════
TRIGGERS = {
    "verdict_comment_id": "6067812345",
    "l3_comment_id": "6067800001",
    "disposition_comment_id": "6067800002",
    "dispatch_comment_id": "6067800003",
}
check("AC-3 重試沿用同一事件：同一 (issue, stage, basis) 兩次導出相等（與時刻無關）",
      hb.event_id_for(313, "r1.approve", "done", TRIGGERS)
      == hb.event_id_for(313, "r1.approve", "done", TRIGGERS)
      == "313-r1.approve-6067812345",
      f"eid={hb.event_id_for(313, 'r1.approve', 'done', TRIGGERS)!r}")
check("AC-3 四類出口都有明確映射（done／blocked／decide／failed 各取對應的既存紀錄）",
      [hb.basis_of(o, TRIGGERS) for o in hb.OUTCOMES]
      == ["6067812345", "6067800001", "6067800002", "6067800003"]
      and sorted(hb.BASIS_FIELD) == sorted(hb.OUTCOMES),
      f"映射={hb.BASIS_FIELD!r}")
check("AC-3 映射缺該出口的既存紀錄 → raise（不得退回猜一個值）",
      raises(lambda: hb.basis_of("blocked", {"verdict_comment_id": "1"}))
      and raises(lambda: hb.basis_of("done", {"verdict_comment_id": ""}))
      and raises(lambda: hb.basis_of("merged", TRIGGERS)),
      "缺欄位或未知出口沒有被擋下")
check("AC-3 同一 issue 的不同階段 ＝ 不同事件（合法交回多次）",
      hb.event_id(313, "r1.approve", "6067812345")
      != hb.event_id(313, "merge.done", "6067812345")
      != hb.event_id(313, "r2.approve", "6067812345"),
      "不同 stage 導出了同一個 EID")
check("AC-3 形狀封死：三欄皆不得含 `-`（`-` 只作欄位分隔，層次用 `.`）",
      raises(lambda: hb.event_id(313, "r1-approve", "6067812345"))
      and raises(lambda: hb.event_id("a313", "r1.approve", "606"))
      and bool(re.fullmatch(hb.EID_RE, EID)),
      f"EID_RE={hb.EID_RE!r}")

# 去重：同一事件重送不產生第二行、也不重寫已落地的行。
fg3 = FakeForge()
r_first = emit(fg3, eid=EID)
_body_after_first = fg3.read()
r_again = emit(fg3, eid=EID, at="2026-10-16T00:00:00+0800")   # 重試：連時刻都不同
check("AC-3 同一事件重送 → 不產生第二行（寫入前先讀、以 event 為鍵）",
      r_first.status == "written" and r_again.status == "skipped_exists"
      and r_again.landed is True and len(hb.handback_rows(fg3.read(), EID)) == 1,
      f"first={r_first!r} again={r_again!r} 行數={len(hb.handback_rows(fg3.read(), EID))}")
check("AC-3 重送**不重寫**已落地的行（§1.3：`at` 等不可變內容逐字不變）",
      fg3.read() == _body_after_first and FIXED_AT in fg3.read()
      and "2026-10-16T00:00:00+0800" not in fg3.read(),
      f"body={fg3.read()!r}")

# 「恰一行」限定當前事件，不對整張 issue 全歷史計數。
E_MERGE = hb.event_id(313, "merge.done", "6067899999")
fg3.comment(hb.handback_line(event=E_MERGE, issue=313, seat="dfmgr", stage="merge.done",
                             kind="final", outcome="done", at=FIXED_AT) + "\n")
check("AC-3 「恰一行」限定當前事件：同一 issue 兩個階段各一行 → 兩者的層1 皆成立",
      hb.landed(fg3.read(), EID)[0] is True and hb.landed(fg3.read(), E_MERGE)[0] is True
      and len(hb.HANDBACK_RE.findall(fg3.read())) == 2,
      f"全檔行數={len(hb.HANDBACK_RE.findall(fg3.read()))}")
check("AC-3 同一事件真的重複兩行時仍判不成立（「恰一行」不是「至少一行」）",
      hb.landed(fg3.read() + "\n" + L_HB, EID)[0] is False,
      "重複兩行被放行")
check("AC-3 待處理清單以 `done` 為已處理判準（不以 ack）",
      hb.pending_events(fg3.read()) == [EID, E_MERGE]
      and (lambda b: hb.pending_events(b))(
          fg3.read() + "\n" + hb.ack_line(event=EID, at=FIXED_AT)) == [EID, E_MERGE]
      and (lambda b: hb.pending_events(b))(
          fg3.read() + "\n" + hb.done_line(event=EID, result="merged", at=FIXED_AT)) == [E_MERGE],
      f"pending={hb.pending_events(fg3.read())!r}")

# ── 反例（實跑）：兩種被否決的識別／計數寫法 ──
AC3_EID = '    eid = f"{issue}-{stage}-{basis}".lower()\n'
AC3_ROWS = '    return [m for m in HANDBACK_RE.finditer(body) if m.group("event") == eid]\n'
MUT_AC3_CLOCK = mutate(HB_SRC, AC3_EID,
                       '    eid = f"{issue}-{stage}-{time.time_ns()}".lower()\n')
MUT_AC3_WHOLE = mutate(HB_SRC, AC3_ROWS, "    return list(HANDBACK_RE.finditer(body))\n")
check("AC-3 兩種突變確實套上（錨點各恰一處命中）",
      MUT_AC3_CLOCK != HB_SRC and MUT_AC3_WHOLE != HB_SRC,
      "錨點漂移：某個突變沒有套上去")

_m3a = load_mutant(MUT_AC3_CLOCK, "_hb_mut_clock")
_c1 = _m3a.event_id_for(313, "r1.approve", "done", TRIGGERS)
_c2 = _m3a.event_id_for(313, "r1.approve", "done", TRIGGERS)
check("AC-3 反例①「以發帖時刻為識別」→ 兩次重試成為兩個事件，去重失效（實跑對照）",
      _c1 != _c2
      and hb.event_id_for(313, "r1.approve", "done", TRIGGERS)
      == hb.event_id_for(313, "r1.approve", "done", TRIGGERS),
      f"突變兩次={_c1!r} vs {_c2!r}")
_fg3a = FakeForge()
emit(_fg3a, _m3a, eid=_c1)
emit(_fg3a, _m3a, eid=_m3a.event_id_for(313, "r1.approve", "done", TRIGGERS))
check("AC-3 反例① 的後果：同一邏輯事件的重送在突變下**真的寫出第二行**（實跑對照）",
      len(_m3a.HANDBACK_RE.findall(_fg3a.read())) == 2
      and len(hb.HANDBACK_RE.findall(fg3.read().split(L_HB)[0] + L_HB)) == 1,
      f"突變行數={len(_m3a.HANDBACK_RE.findall(_fg3a.read()))}")

_m3b = load_mutant(MUT_AC3_WHOLE, "_hb_mut_whole")
check("AC-3 反例②「全歷史計數」→ 合法的第二次階段交回被誤判成重複（實跑對照）",
      _m3b.landed(fg3.read(), EID)[0] is False
      and _m3b.landed(fg3.read(), E_MERGE)[0] is False
      and hb.landed(fg3.read(), EID)[0] is True
      and hb.landed(fg3.read(), E_MERGE)[0] is True,
      f"突變 landed={_m3b.landed(fg3.read(), EID)!r}")


# ══════════════════════════════════════════════════════════════════════════
print("\n── AC-4：恢復三態（resume_safe／record_only／indeterminate）")
# ══════════════════════════════════════════════════════════════════════════
E_REC = hb.event_id(313, "r1.recover", "6067812345")


def steps_of(ext: dict, names, *, seen_probe: list | None = None):
    """以外部狀態 dict 造步驟表。probe 吃 `eid`——每一步都對準本事件的目標讀回。"""
    def mk(name):
        def probe(eid):
            if seen_probe is not None:
                seen_probe.append((name, eid))
            return ext[name]
        return (name, probe)
    return [mk(n) for n in names]


def runner(ext: dict, ran: list, *, succeed: bool = True):
    def run(name, eid):
        ran.append((name, eid))
        if succeed:
            ext[name] = True
        return True          # 回傳值刻意「看起來成功」——完成判準只認執行後的讀回
    return run


check("AC-4 `UNKNOWN` 不可當布林用（讀不到不是未做，誤用即 raise）",
      raises(lambda: bool(hb.UNKNOWN)) and hb.UNKNOWN is not False
      and hb.UNKNOWN is not None and repr(hb.UNKNOWN) == "UNKNOWN",
      f"UNKNOWN={hb.UNKNOWN!r}")
check("AC-4 `read_state` 只接受約定值：`True`／`False` 原樣，`None`／字串／0／例外一律 UNKNOWN",
      hb.read_state(lambda e: True, E_REC) is True
      and hb.read_state(lambda e: False, E_REC) is False
      and hb.read_state(lambda e: None, E_REC) is hb.UNKNOWN
      and hb.read_state(lambda e: "done", E_REC) is hb.UNKNOWN
      and hb.read_state(lambda e: 0, E_REC) is hb.UNKNOWN
      and hb.read_state(lambda e: 1, E_REC) is hb.UNKNOWN
      and hb.read_state(lambda e: (_ for _ in ()).throw(RuntimeError("API down")),
                        E_REC) is hb.UNKNOWN,
      "某個非約定值沒有落到 UNKNOWN")
check("AC-4 probe 收到的是**本事件**的 id（「對準本事件的目標」是機械的，不是口頭承諾）",
      (lambda seen: (hb.reconcile(steps_of({"merge": True}, ["merge"], seen_probe=seen),
                                  E_REC), seen)[1] == [("merge", E_REC)])([]),
      "probe 沒收到本事件的 eid")

# 三態
ext_a = {"merge": True, "archive": False}
ran_a: list = []
rec_a = hb.recover(seeded(eid=E_REC), E_REC, steps_of(ext_a, ["merge", "archive"]),
                   runner(ext_a, ran_a), at=FIXED_AT)
check("AC-4 `resume_safe`：讀回 merge=已做／archive=未做 → **只跑 archive**，不重做 merge",
      rec_a.verdict == hb.RESUME_SAFE and [n for n, _ in ran_a] == ["archive"]
      and rec_a.done_written is True,
      f"verdict={rec_a.verdict} ran={ran_a!r}")

ext_b = {"merge": True, "archive": True}
ran_b: list = []
fg_b = seeded(eid=E_REC)
rec_b = hb.recover(fg_b, E_REC, steps_of(ext_b, ["merge", "archive"]),
                   runner(ext_b, ran_b), at=FIXED_AT)
check("AC-4 `record_only`：全部讀回皆已做 → **只補寫 done 紀錄，不重做任何動作**",
      rec_b.verdict == hb.RECORD_ONLY and ran_b == []
      and rec_b.done_written is True and hb.processed(fg_b.read(), E_REC) is True,
      f"verdict={rec_b.verdict} ran={ran_b!r}")

for _label, _probe in (("probe 回 None", lambda e: None),
                       ("probe 回字串", lambda e: "done"),
                       ("probe 自己拋例外", lambda e: (_ for _ in ()).throw(RuntimeError("API down")))):
    ran_c: list = []
    fg_c = seeded(eid=E_REC)
    rec_c = hb.recover(fg_c, E_REC, [("merge", lambda e: True), ("notify", _probe)],
                       runner({}, ran_c), at=FIXED_AT)
    check(f"AC-4 `indeterminate`（{_label}）→ `escalate_human`、**一步都不重播**、不寫 done",
          rec_c.verdict == "escalate_human" and ran_c == []
          and rec_c.done_written is False and hb.processed(fg_c.read(), E_REC) is False,
          f"verdict={rec_c.verdict} ran={ran_c!r} report={rec_c.report!r}")

check("AC-4 `reconcile` 的三態直接可讀（任一步 UNKNOWN → indeterminate，不看其餘步驟）",
      hb.reconcile([("a", lambda e: True), ("b", lambda e: False)], E_REC)[0] == hb.RESUME_SAFE
      and hb.reconcile([("a", lambda e: True)], E_REC)[0] == hb.RECORD_ONLY
      and hb.reconcile([("a", lambda e: None), ("b", lambda e: False)], E_REC)[0]
      == hb.INDETERMINATE,
      "三態判定不符")

# **失敗或未核實的動作不得產生 done**（裁決位反例 1 的產品側斷言）
ext_f = {"archive": False}
ran_f: list = []
fg_f = seeded(eid=E_REC)
rec_f = hb.recover(fg_f, E_REC, steps_of(ext_f, ["archive"]),
                   runner(ext_f, ran_f, succeed=False), at=FIXED_AT)
check("AC-4 動作「沒拋例外」但執行後讀回仍為未做 → **不得寫 done**，判 escalate_human",
      rec_f.verdict == "escalate_human" and [n for n, _ in ran_f] == ["archive"]
      and rec_f.done_written is False and hb.processed(fg_f.read(), E_REC) is False
      and rec_f.report["archive"] is False,
      f"verdict={rec_f.verdict} report={rec_f.report!r}")
ext_g = {"archive": False}
ran_g: list = []
fg_g = seeded(eid=E_REC)


def _boom_run(name, eid):
    ran_g.append((name, eid))
    raise RuntimeError("gh: API down")


rec_g = hb.recover(fg_g, E_REC, steps_of(ext_g, ["archive"]), _boom_run, at=FIXED_AT)
check("AC-4 動作執行時拋例外 → 同樣不寫 done、交人（不吞例外當成功）",
      rec_g.verdict == "escalate_human" and rec_g.done_written is False
      and hb.processed(fg_g.read(), E_REC) is False,
      f"verdict={rec_g.verdict} detail={rec_g.detail!r}")

ext_h = {"archive": False}
ran_h: list = []
rec_h = hb.recover(seeded(eid=E_REC, fail_write=True), E_REC, steps_of(ext_h, ["archive"]),
                   runner(ext_h, ran_h), at=FIXED_AT)
check("AC-4 動作已核實完成而 done 紀錄寫入失敗 → 結果未定交人（**不重播**，動作不做第二次）",
      rec_h.verdict == "escalate_human" and rec_h.done_written is False
      and [n for n, _ in ran_h] == ["archive"] and ext_h["archive"] is True,
      f"verdict={rec_h.verdict} ran={ran_h!r} detail={rec_h.detail!r}")

# ── 反例（實跑）：T 明列的兩個突變 ──
AC4_POSTREAD = """        after = read_state(probes[name], eid)
        if after is not True:
"""
AC4_READSTATE = "    return value if (value is True or value is False) else UNKNOWN\n"
MUT_AC4_NOEXC = mutate(HB_SRC, AC4_POSTREAD, "        after = True\n        if after is not True:\n")
MUT_AC4_NONEOK = mutate(HB_SRC, AC4_READSTATE, "    return value\n")
check("AC-4 兩種突變確實套上（錨點各恰一處命中）",
      MUT_AC4_NOEXC != HB_SRC and MUT_AC4_NONEOK != HB_SRC,
      "錨點漂移：某個突變沒有套上去")


def ac4_postcondition_ok(mod) -> tuple[bool, str]:
    """述詞：**失敗／未核實的動作不得產生 `done`**。產品須 True，突變須 False。"""
    ext = {"archive": False}
    ran: list = []
    forge = seeded(eid=E_REC, mod=mod)
    rec = mod.recover(forge, E_REC, steps_of(ext, ["archive"]),
                      runner(ext, ran, succeed=False), at=FIXED_AT)
    ok = (not mod.processed(forge.read(), E_REC)) and rec.done_written is False
    return ok, f"verdict={rec.verdict} done_written={rec.done_written} body={forge.read()!r}"


def ac4_none_is_unknown_ok(mod) -> tuple[bool, str]:
    """述詞：**讀回值 `None` 必走 `indeterminate`**。產品須 True，突變須 False。"""
    verdict, report = mod.reconcile([("notify", lambda e: None)], E_REC)
    return verdict == mod.INDETERMINATE, f"verdict={verdict} report={report!r}"


_m4a = load_mutant(MUT_AC4_NOEXC, "_hb_mut_noexc")
_m4b = load_mutant(MUT_AC4_NONEOK, "_hb_mut_noneok")
_p_ok, _p_detail = ac4_postcondition_ok(hb)
_m_ok, _m_detail = ac4_postcondition_ok(_m4a)
check("AC-4 反例①「callback 沒拋例外即記完成」→ 同一述詞在突變下轉 FAIL（實跑對照）",
      _p_ok is True and _m_ok is False,
      f"產品：{_p_detail}｜突變：{_m_detail}")
_p_ok2, _p_detail2 = ac4_none_is_unknown_ok(hb)
_m_ok2, _m_detail2 = ac4_none_is_unknown_ok(_m4b)
check("AC-4 反例②「`None` 視為已完成」→ 同一述詞在突變下轉 FAIL（實跑對照）",
      _p_ok2 is True and _m_ok2 is False,
      f"產品：{_p_detail2}｜突變：{_m_detail2}")

# 第三個突變：盲目重播整段 handler（T 的「不得盲目重播」）。
AC4_RECONCILE = """    verdict, report = reconcile(steps, eid)
    if verdict == INDETERMINATE:
"""
MUT_AC4_BLIND = mutate(HB_SRC, AC4_RECONCILE,
                       '    verdict, report = (RESUME_SAFE, {n: False for n, _ in steps})\n'
                       "    if False:\n")
check("AC-4 第三種突變確實套上（錨點恰一處命中）", MUT_AC4_BLIND != HB_SRC, "錨點漂移")
_m4c = load_mutant(MUT_AC4_BLIND, "_hb_mut_blind")
_ext_blind = {"merge": True, "archive": False}
_ran_blind: list = []
_m4c.recover(seeded(eid=E_REC, mod=_m4c), E_REC, steps_of(_ext_blind, ["merge", "archive"]),
             runner(_ext_blind, _ran_blind), at=FIXED_AT)
check("AC-4 反例③「不對帳、整段重播」→ 連已完成的 merge 也重做（產品只跑 archive，實跑對照）",
      [n for n, _ in _ran_blind] == ["merge", "archive"]
      and [n for n, _ in ran_a] == ["archive"],
      f"突變 ran={_ran_blind!r}；產品 ran={ran_a!r}")


# ══════════════════════════════════════════════════════════════════════════
print("\n── AC-6：失敗出口（topic ＋ General ＋ 待處理紀錄；忙碌具名到 session）")
# ══════════════════════════════════════════════════════════════════════════
TOPIC = "6667"
send_ok = FakeSend()
fx = hb.failure_exit(issue=313, eid=EID, reason="busy", topic_thread=TOPIC,
                     send=send_ok, home=FAKE_HOME, profile="dfcoord",
                     attempt=2, detail="同名 session 已有 chat 在跑", at=FIXED_AT)
check("AC-6 告警落**該單 topic ＋ General** 兩處（不是只送一邊）",
      send_ok.threads == [TOPIC, hb.GENERAL_THREAD] and fx.threads == [TOPIC, "1"]
      and hb.GENERAL_THREAD == "1",
      f"threads={send_ok.threads!r}")
check("AC-6 兩處收到的是**同一份**字面（一則文字只有一份，兩邊不會漂移）",
      len({t for _, t in send_ok.sent}) == 1 and send_ok.sent[0][1] == fx.text,
      "兩邊文字不同")
check("AC-6 忙碌**具名到 session**：文字含 `hermes -p dfcoord chat -c issue-313`",
      "hermes -p dfcoord chat -c issue-313" in fx.text
      and hb.busy_message(313) == "hermes -p dfcoord chat -c issue-313",
      f"text={fx.text!r}")
check("AC-6 **不得宣稱自動續接**：文字明寫不自動續接／不自動重試，且不含「自動續接」的宣稱",
      hb.NO_AUTO_RESUME in fx.text and "不自動續接" in fx.text
      and "會自動續接" not in fx.text and "已自動重試" not in fx.text,
      f"text={fx.text!r}")
check("AC-6 告警指得出單號、事件與待處理紀錄的位置（可操作、可追查）",
      "#313" in fx.text and EID in fx.text and str(fx.pending_file) in fx.text,
      f"text={fx.text!r}")

check("AC-6 待處理檔**有 profile 與本單歸屬**：`<home>/.hermes/profiles/dfcoord/handback-pending/313-<EID>.json`",
      fx.pending_file == FAKE_HOME / ".hermes" / "profiles" / "dfcoord"
      / "handback-pending" / f"313-{EID}.json" and fx.pending_file.exists(),
      f"path={fx.pending_file}")
check("AC-6 待處理檔落在該 profile 的專屬子目錄下，不是暫存根／home 根的散檔",
      under(FAKE_HOME / ".hermes" / "profiles" / "dfcoord", fx.pending_file)
      and fx.pending_file.parent.name == "handback-pending"
      and fx.pending_file.parent != FAKE_HOME
      and fx.pending_file.parent != Path(tempfile.gettempdir()).resolve()
      # 階層判定不是字串前綴：同名前綴的**兄弟**目錄不得算在其下（`#312` `AC-8(a)` 的實測）
      and not under(FAKE_HOME / ".hermes" / "profiles" / "dfcoord",
                    FAKE_HOME / ".hermes" / "profiles" / "dfcoord-tmp" / "x.json"),
      f"path={fx.pending_file}")
_payload = json.loads(fx.pending_file.read_text())
check("AC-6 待處理紀錄的內容可讀回：event／issue／profile／reason／attempt／result 齊備",
      _payload["event"] == EID and _payload["issue"] == "313"
      and _payload["profile"] == "dfcoord" and _payload["reason"] == "busy"
      and _payload["attempt"] == 2 and _payload["result"] == hb.INDETERMINATE,
      f"payload={_payload!r}")

send_dead = FakeSend(dead=(TOPIC, "1"))
fx_dead = hb.failure_exit(issue=313, eid=EID, reason="no_ack", topic_thread=TOPIC,
                          send=send_dead, home=FAKE_HOME, profile="dfcoord", at=FIXED_AT)
check("AC-6 送訊全部失敗時**紀錄仍落地**，且回傳值說得出哪幾個 thread 沒送成（不中斷）",
      fx_dead.pending_file.exists() and fx_dead.threads == []
      and fx_dead.attempted == [TOPIC, "1"],
      f"threads={fx_dead.threads!r} attempted={fx_dead.attempted!r}")
# 「不得只留 stderr」第 2 輪起用**功能判準**驗（模組有了 CLI，自然會 print）：
# 每一次 `failure_exit()` 都同時產生「兩則告警 ＋ 一個待處理檔」，而 CLI 的每一條失敗
# 路徑都呼叫它（下方 AST 斷言）——「只印一行 stderr 就回去」在這個形狀下不可能成立。
check("AC-6 **不得只留 stderr**：每次失敗出口都同時留下兩則告警與一個待處理檔（功能判準）",
      len(send_ok.sent) == 2 and fx.pending_file.exists()
      and len(send_dead.sent) == 2 and fx_dead.pending_file.exists(),
      f"sends={len(send_ok.sent)}／{len(send_dead.sent)} "
      f"pending={fx.pending_file.exists()}／{fx_dead.pending_file.exists()}")
_HB_CLI_FUNCS = ("cmd_ack", "cmd_done", "cmd_recover")
_HB_CLI_FAILS = {name: [ast.unparse(c.func) for c in ast.walk(_HB_FUNCS[name])
                        if isinstance(c, ast.Call) and ast.unparse(c.func) == "_fail"]
                 for name in _HB_CLI_FUNCS}
check("AC-6 CLI 的每一條失敗路徑都呼叫失敗出口（`_fail` → `failure_exit`，AST 判定）",
      all(len(v) >= 1 for v in _HB_CLI_FAILS.values())
      and [ast.unparse(c.func) for c in ast.walk(_HB_FUNCS["_fail"])
           if isinstance(c, ast.Call) and "failure_exit" in ast.unparse(c.func)],
      f"命中={_HB_CLI_FAILS!r}")

ok_clear, why_clear = hb.clear_pending("dfcoord", 313, EID, home=FAKE_HOME,
                                       result=hb.INDETERMINATE)
check("AC-6 **結果未定者不得被當完成而清掉**（`indeterminate` → 拒絕，檔案留著）",
      ok_clear is False and "不得清除" in why_clear and fx.pending_file.exists(),
      f"({ok_clear}, {why_clear!r}) exists={fx.pending_file.exists()}")
check("AC-6 `UNKNOWN`／`None`／未知結果同樣拒絕清除",
      hb.clear_pending("dfcoord", 313, EID, home=FAKE_HOME, result=hb.UNKNOWN)[0] is False
      and hb.clear_pending("dfcoord", 313, EID, home=FAKE_HOME, result=None)[0] is False
      and hb.clear_pending("dfcoord", 313, EID, home=FAKE_HOME, result="probably")[0] is False
      and fx.pending_file.exists(),
      "某個未定結果被放行")
check("AC-6 結果確定者才清得掉（`record_only` 等落在 `SETTLED_RESULTS`）",
      hb.read_pending("dfcoord", 313, EID, home=FAKE_HOME) is not None
      and hb.clear_pending("dfcoord", 313, EID, home=FAKE_HOME,
                           result=hb.RECORD_ONLY)[0] is True
      and not fx.pending_file.exists()
      and hb.read_pending("dfcoord", 313, EID, home=FAKE_HOME) is None,
      "確定結果清不掉")

# ── 反例（實跑）：三種被否決的失敗出口寫法 ──
AC6_LOOP = "    for thread in (str(topic_thread), str(general_thread)):\n"
AC6_DIR = '    return pathlib.Path(home) / ".hermes" / "profiles" / profile / PENDING_DIRNAME\n'
AC6_GUARD = ("    if result is UNKNOWN or result is None "
             "or result not in SETTLED_RESULTS:\n")
MUT_AC6_TOPICONLY = mutate(HB_SRC, AC6_LOOP, "    for thread in (str(topic_thread),):\n")
MUT_AC6_FLATDIR = mutate(HB_SRC, AC6_DIR,
                         '    return pathlib.Path(home) / PENDING_DIRNAME\n')
MUT_AC6_ALWAYSCLEAR = mutate(HB_SRC, AC6_GUARD, "    if False:\n")
check("AC-6 三種突變確實套上（錨點各恰一處命中）",
      MUT_AC6_TOPICONLY != HB_SRC and MUT_AC6_FLATDIR != HB_SRC
      and MUT_AC6_ALWAYSCLEAR != HB_SRC,
      "錨點漂移：某個突變沒有套上去")

_m6a = load_mutant(MUT_AC6_TOPICONLY, "_hb_mut_topiconly")
_send_a = FakeSend()
_m6a.failure_exit(issue=313, eid=EID, reason="busy", topic_thread=TOPIC, send=_send_a,
                  home=FAKE_HOME / "mut_a", profile="dfcoord", at=FIXED_AT)
check("AC-6 反例①「只送該單 topic」→ General 收不到（產品兩處都到，實跑對照）",
      _send_a.threads == [TOPIC] and send_ok.threads == [TOPIC, "1"],
      f"突變 threads={_send_a.threads!r}")

_m6b = load_mutant(MUT_AC6_FLATDIR, "_hb_mut_flatdir")
_p_b = _m6b.pending_path("dfcoord", 313, EID, home=FAKE_HOME)
_p_good = hb.pending_path("dfcoord", 313, EID, home=FAKE_HOME)
# ⚠️ 比的是**相對於 home 的那幾段**，不是整條絕對路徑：本檔的假 HOME 落在
# `$TMPDIR` 下，而真實的 `$TMPDIR` 本身就在 `…/profiles/dfimpl/cache/scratch` 裡——
# 拿整條路徑找 `profiles` 會因為**無關的祖先目錄**而命中（第 1 輪實跑踩到）。
check("AC-6 反例②「不帶 profile 歸屬的扁平目錄」→ 相對 home 的路徑裡沒有 `profiles/dfcoord`（實跑對照）",
      "profiles" not in _p_b.relative_to(FAKE_HOME).parts
      and _p_good.relative_to(FAKE_HOME).parts[:4]
      == (".hermes", "profiles", "dfcoord", "handback-pending"),
      f"突變={_p_b.relative_to(FAKE_HOME)}；產品={_p_good.relative_to(FAKE_HOME)}")

_m6c = load_mutant(MUT_AC6_ALWAYSCLEAR, "_hb_mut_alwaysclear")
_fx_c = _m6c.failure_exit(issue=313, eid=EID, reason="busy", topic_thread=TOPIC,
                          send=FakeSend(), home=FAKE_HOME / "mut_c", profile="dfcoord",
                          at=FIXED_AT)
_cleared_c = _m6c.clear_pending("dfcoord", 313, EID, home=FAKE_HOME / "mut_c",
                                result=_m6c.INDETERMINATE)
check("AC-6 反例③「無條件清除」→ 結果未定的紀錄被刪掉（產品拒絕，實跑對照）",
      _cleared_c[0] is True and not _fx_c.pending_file.exists() and ok_clear is False,
      f"突變=({_cleared_c!r}, exists={_fx_c.pending_file.exists()})")



# ══════════════════════════════════════════════════════════════════════════
print("\n── 第 2 輪 BLOCK 1：宣告判準長在**寫入邊界**上（不是旁路純函式）")
# ══════════════════════════════════════════════════════════════════════════
# 第 1 輪 `R1` 的現場：`may_declare()` 判準正確、突變測試也過，但 `emit_handback()` 根本
# 不呼叫它——`seat="dfimpl"` 實跑仍得到 `Landing(status='written', landed=True)`。
# 本節驗的是**產品邊界**：不成立時 raise，且 `forge` **一次都沒被碰過**（哨兵反證）。
B1_EID = hb.event_id(313, "r1.approve", "6067812345")
B1_CASES = [
    ("非 mgr（dfimpl）", dict(seat="dfimpl")),
    ("非 mgr（dfrev）", dict(seat="dfrev")),
    ("尚有未回收的下游", dict(outstanding_children=1)),
    ("後處理未完成", dict(postprocess_done=False)),
    ("`final` 但本單不可結", dict(kind="final", issue_closable=False)),
]
for _label, _over in B1_CASES:
    _f = FakeForge()
    _raised = raises(lambda f=_f, o=_over: emit(f, eid=B1_EID, **o))
    check(f"BLOCK 1 {_label} → `emit_handback` raise，且 `forge` 一次都沒被呼叫（哨兵反證）",
          _raised and _f.calls == [] and _f.comments == [],
          f"raised={_raised} forge.calls={_f.calls!r}")

_f_missing = FakeForge()
check("BLOCK 1 宣告事實省略（三項任一為 None）→ raise，且不碰 forge（沒有樂觀預設值）",
      raises(lambda: hb.emit_handback(_f_missing, event=B1_EID, issue=313, seat="dfmgr",
                                      stage="r1.approve", kind="stage", outcome="done",
                                      at=FIXED_AT))
      and _f_missing.calls == [],
      f"forge.calls={_f_missing.calls!r}")
_f_ok = FakeForge()
_land_ok = emit(_f_ok, eid=B1_EID)
check("BLOCK 1 正例：mgr ＋ 下游全收 ＋ 後處理完成 ＋ `stage` → 照常寫入（閘門不擋合法宣告）",
      _land_ok.status == "written" and _land_ok.landed is True
      and _f_ok.calls == ["read", "write", "read"],
      f"landing={_land_ok!r} calls={_f_ok.calls!r}")
_f_final = FakeForge()
_land_final = emit(_f_final, eid=hb.event_id(313, "merge.done", "6067899999"),
                   stage="merge.done", kind="final", issue_closable=True)
check("BLOCK 1 正例：`final` ＋ 本單可結 → 照常寫入（分流不是一律擋 final）",
      _land_final.status == "written" and _land_final.landed is True,
      f"landing={_land_final!r}")

# AST：閘門在**任何 forge 呼叫之前**，而且 `handback` 行只有這一個寫者。
_B1_EMIT = _HB_FUNCS["emit_handback"]
_b1_gate_line = next((n.lineno for n in ast.walk(_B1_EMIT) if isinstance(n, ast.Call)
                      and ast.unparse(n.func) == "declare_or_raise"), None)
_b1_forge_lines = [n.lineno for n in ast.walk(_B1_EMIT) if isinstance(n, ast.Call)
                   and ast.unparse(n.func).startswith("forge.")]
check("BLOCK 1 AST：`declare_or_raise` 的呼叫在 `emit_handback` 內**早於**任何 `forge.*`",
      _b1_gate_line is not None and _b1_forge_lines
      and _b1_gate_line < min(_b1_forge_lines),
      f"gate@{_b1_gate_line} forge@{_b1_forge_lines!r}")
_b1_line_calls = [n for n in ast.walk(_HB_TREE) if isinstance(n, ast.Call)
                  and ast.unparse(n.func) == "handback_line"]
_b1_in_emit = [n for n in ast.walk(_B1_EMIT) if isinstance(n, ast.Call)
               and ast.unparse(n.func) == "handback_line"]
check("BLOCK 1 AST：全檔只有 `emit_handback` 組 `handback` 行（唯一的宣告／寫入入口）",
      len(_b1_line_calls) == 1 and len(_b1_in_emit) == 1,
      f"全檔={len(_b1_line_calls)} emit_handback 內={len(_b1_in_emit)}")

# 反例（實跑）：把閘門拿掉 → dfimpl 又寫得出宣告行。
B1_GATE = """    declare_or_raise(seat=seat, kind=kind, issue_closable=issue_closable,
                     outstanding_children=outstanding_children,
                     postprocess_done=postprocess_done)
"""
MUT_B1 = mutate(HB_SRC, B1_GATE, "    pass\n")
check("BLOCK 1 突變確實套上（錨點恰一處命中）", MUT_B1 != HB_SRC, "錨點漂移")
_m_b1 = load_mutant(MUT_B1, "_hb_mut_nogate1")


def b1_predicate(mod) -> tuple[bool, str]:
    """述詞：**非 mgr 不得寫出宣告行**。產品須 True，突變須 False。"""
    forge = FakeForge()
    try:
        out = emit(forge, mod, eid=B1_EID, seat="dfimpl")
    except mod.HandbackError as exc:
        return forge.comments == [], f"raise：{str(exc)[:60]}"
    return False, f"landing={out!r} body={forge.read()[:120]!r}"


_b1p, _b1pd = b1_predicate(hb)
_b1m, _b1md = b1_predicate(_m_b1)
check("BLOCK 1 反例「寫入邊界不問宣告判準」→ 同一述詞在突變下轉 FAIL（實跑對照）",
      _b1p is True and _b1m is False, f"產品：{_b1pd}｜突變：{_b1md}")


# ══════════════════════════════════════════════════════════════════════════
print("\n── 第 2 輪 BLOCK 2：ack 的寫者與四層順序由產品 API 強制")
# ══════════════════════════════════════════════════════════════════════════
B2_FG = FakeForge()
B2_FG.comments.append(hb.handback_line(event=B1_EID, issue=313, seat="dfmgr",
                                       stage="r1.approve", kind="stage",
                                       outcome="done", at=FIXED_AT))
B2_FG.comments.append(hb.ack_line(event=B1_EID, by="dfimpl", at=FIXED_AT))
check("BLOCK 2 ack 的 `by` 不是指定接收端 → 層3 不成立、交接未完成（`wrong_by False False`）",
      hb.received(B2_FG.read(), B1_EID) is False
      and hb.handoff_complete(B2_FG.read(), B1_EID) is False,
      f"received={hb.received(B2_FG.read(), B1_EID)}")
check("BLOCK 2 指定接收端自己寫的 ack 才算（同一份 body 換 `by=dfimpl` 查則成立——是身分判準，不是壞掉）",
      hb.received(B2_FG.read(), B1_EID, by="dfimpl") is True
      and hb.handoff_complete(B2_FG.read(), B1_EID, by="dfimpl") is True,
      "by 參數沒有作用")
B2_FG.comments.append(hb.ack_line(event=B1_EID, by="dfcoord", at=FIXED_AT))
check("BLOCK 2 接收端補上 ack 後層3 成立",
      hb.received(B2_FG.read(), B1_EID) is True
      and hb.handoff_complete(B2_FG.read(), B1_EID) is True, "")
B2_FG.comments.append(hb.done_line(event=B1_EID, result="merged", by="dfimpl",
                                   at=FIXED_AT))
check("BLOCK 2 層4 同樣限定寫者：別人代記的 done 不算已處理",
      hb.processed(B2_FG.read(), B1_EID) is False
      and hb.processed(B2_FG.read(), B1_EID, by="dfimpl") is True
      and hb.done_result(B2_FG.read(), B1_EID) is None,
      f"processed={hb.processed(B2_FG.read(), B1_EID)}")

_b2_empty = FakeForge()
_b2_rec = hb.recover(_b2_empty, B1_EID, [("merge", lambda e: True)],
                     lambda n, e: None, at=FIXED_AT)
check("BLOCK 2 空 forge 上 `recover` → 不寫 done，四層全假（`recovery False {1..4: False}`）",
      _b2_rec.done_written is False
      and hb.layers(_b2_empty.read(), B1_EID) == {1: False, 2: False, 3: False, 4: False}
      and _b2_rec.verdict == hb.PRECONDITION_UNMET and _b2_rec.ran == [],
      f"rec={_b2_rec.verdict} layers={hb.layers(_b2_empty.read(), B1_EID)!r}")

_b2_noack = seeded(eid=B1_EID, ack=False)
_b2_ran: list = []
_b2_rec2 = hb.recover(_b2_noack, B1_EID, [("merge", lambda e: True)],
                      lambda n, e: _b2_ran.append(n), at=FIXED_AT)
check("BLOCK 2 層1 成立但層3 未成立 → 仍**不得寫 done**（層4 不得跳過層3）",
      _b2_rec2.done_written is False and _b2_rec2.verdict == hb.PRECONDITION_UNMET
      and hb.processed(_b2_noack.read(), B1_EID) is False,
      f"rec={_b2_rec2.verdict} detail={_b2_rec2.detail!r}")
_b2_ok = seeded(eid=B1_EID)
_b2_rec3 = hb.recover(_b2_ok, B1_EID, [("merge", lambda e: True)],
                      lambda n, e: None, at=FIXED_AT)
check("BLOCK 2 層1 ＋ 層3 齊備 → `record_only` 並補寫 done（閘門不擋合法恢復）",
      _b2_rec3.done_written is True and _b2_rec3.verdict == hb.RECORD_ONLY
      and hb.processed(_b2_ok.read(), B1_EID) is True,
      f"rec={_b2_rec3!r}")
_b2_badread = seeded(eid=B1_EID)
_b2_badread.fail_read = True
_b2_rec4 = hb.recover(_b2_badread, B1_EID, [("merge", lambda e: True)],
                      lambda n, e: None, at=FIXED_AT)
check("BLOCK 2 前置層次讀不回 → `precondition_unmet`、一步都不跑（讀不到不當成成立）",
      _b2_rec4.verdict == hb.PRECONDITION_UNMET and _b2_rec4.ran == []
      and _b2_rec4.done_written is False, f"rec={_b2_rec4!r}")

# 反例（實跑）：兩種把層次說成成立的寫法。
B2_BY = ('    return any(m.group("event") == eid and m.group("by") == by\n'
         "               for m in ACK_RE.finditer(body))\n")
B2_ENTRY = """    ok1, why1 = landed(body, eid)
    if not ok1:
"""
# 錨點含上一行：`cmd_done` 裡有一條同形的判斷，只取判斷那一行會命中兩處（mutate 會
# 因此退回原文，反例就靜默變成 no-op——「突變確實套上」那條擋得住，但不如一開始就鎖準）。
B2_PRE = ("    pre = layers(body, eid, by=by)\n"
          "    if not (pre[1] and pre[3]):\n")
MUT_B2_ANYBY = mutate(HB_SRC, B2_BY,
                      '    return any(m.group("event") == eid for m in ACK_RE.finditer(body))\n')
MUT_B2_NOGATE = mutate(mutate(HB_SRC, B2_ENTRY,
                              '    ok1, why1 = (True, "")\n    if not ok1:\n'),
                       B2_PRE, "    pre = layers(body, eid, by=by)\n    if False:\n")
check("BLOCK 2 兩種突變確實套上（錨點各恰一處命中）",
      MUT_B2_ANYBY != HB_SRC and MUT_B2_NOGATE != HB_SRC, "錨點漂移")
_m_b2a = load_mutant(MUT_B2_ANYBY, "_hb_mut_anyby")
_m_b2b = load_mutant(MUT_B2_NOGATE, "_hb_mut_nolayers")
check("BLOCK 2 反例①「ack 不核寫者」→ `wrong_by` 轉 True True（實跑對照）",
      _m_b2a.received(B2_FG.read(), B1_EID) is True
      and _m_b2a.handoff_complete(B2_FG.read(), B1_EID) is True
      and hb.received(B2_FG.read(), B1_EID) is True,   # 產品此刻已有合法 ack，故仍為 True
      f"突變 received(by 預設)={_m_b2a.received(B2_FG.read(), B1_EID)}")
_b2_fg_wrongonly = FakeForge()
_b2_fg_wrongonly.comments.append(hb.handback_line(
    event=B1_EID, issue=313, seat="dfmgr", stage="r1.approve", kind="stage",
    outcome="done", at=FIXED_AT))
_b2_fg_wrongonly.comments.append(hb.ack_line(event=B1_EID, by="dfimpl", at=FIXED_AT))
check("BLOCK 2 反例① 的判別情境：只有 dfimpl 的 ack 時，產品 False／突變 True（實跑對照）",
      hb.received(_b2_fg_wrongonly.read(), B1_EID) is False
      and _m_b2a.received(_b2_fg_wrongonly.read(), B1_EID) is True,
      "兩者輸出相同 ＝ 無鑑別力")
_b2_mut_forge = FakeForge()
_b2_mut_rec = _m_b2b.recover(_b2_mut_forge, B1_EID, [("merge", lambda e: True)],
                             lambda n, e: None, at=FIXED_AT)
check("BLOCK 2 反例②「不核層1～3」→ 空 forge 上寫出層4（產品不寫，實跑對照）",
      _b2_mut_rec.done_written is True
      and _m_b2b.layers(_b2_mut_forge.read(), B1_EID)[4] is True
      and _b2_rec.done_written is False,
      f"突變 layers={_m_b2b.layers(_b2_mut_forge.read(), B1_EID)!r}")


# ══════════════════════════════════════════════════════════════════════════
print("\n── 第 2 輪 BLOCK 3：EID 與行內 issue／stage 不得矛盾（`R4` 正確值在錯誤位置）")
# ══════════════════════════════════════════════════════════════════════════
check("BLOCK 3 `event_fields` 把 EID 切回三欄（`-` 只作欄位分隔）",
      hb.event_fields(B1_EID) == ("313", "r1.approve", "6067812345")
      and raises(lambda: hb.event_fields("not-an-eid-!")),
      f"fields={hb.event_fields(B1_EID)!r}")
_b3_f = FakeForge()
check("BLOCK 3 寫入端：正確 EID 在 `event=`、`issue=999`／`stage=merge.done` 在他欄 → raise，且不碰 forge",
      raises(lambda: emit(_b3_f, eid=B1_EID, issue=999, stage="merge.done"))
      and _b3_f.calls == [] and _b3_f.comments == [],
      f"forge.calls={_b3_f.calls!r}")
check("BLOCK 3 寫入端：只有 issue 矛盾、只有 stage 矛盾，各自都擋",
      raises(lambda: emit(FakeForge(), eid=B1_EID, issue=999))
      and raises(lambda: emit(FakeForge(), eid=B1_EID, stage="merge.done")),
      "單欄矛盾沒有被擋")
# 讀回端不得依賴寫入端：手寫（或別的版本寫出）的矛盾行同樣要判不成立。
_b3_row = ("<!-- devflow:handback      event=313-r1.approve-6067812345 issue=999 "
           "seat=dfimpl stage=merge.done kind=stage outcome=done "
           "at=2026-10-16T12:00:00+0800 -->")
check("BLOCK 3 讀回端：矛盾的行合 grammar 但**不算落地**（判定端自己核，不信寫入端）",
      bool(hb.HANDBACK_RE.fullmatch(_b3_row))
      and len(hb.handback_rows(_b3_row, B1_EID)) == 1
      and hb.landed(_b3_row, B1_EID)[0] is False
      and "矛盾" in hb.landed(_b3_row, B1_EID)[1],
      f"landed={hb.landed(_b3_row, B1_EID)!r}")
check("BLOCK 3 一致的行照常成立（核對不是一律擋）",
      hb.landed(seeded(eid=B1_EID).read(), B1_EID) == (True, "ok"), "")

B3_WRITE = """    same, why = fields_match_event(event, issue, stage)
    if not same:
        raise HandbackError(f"handback 行的欄位與 EID 矛盾，拒絕組出該行：{why}")
"""
B3_READ = """    same, why = fields_match_event(eid, row.group("issue"), row.group("stage"))
    if not same:
        return False, f"該事件的 handback 行自相矛盾，不算落地：{why}"
"""
MUT_B3 = mutate(mutate(HB_SRC, B3_WRITE, "    pass\n"), B3_READ, "    pass\n")
check("BLOCK 3 突變確實套上（兩個錨點各恰一處命中）", MUT_B3 != HB_SRC, "錨點漂移")
_m_b3 = load_mutant(MUT_B3, "_hb_mut_nofields")


def b3_predicate(mod) -> tuple[bool, str]:
    """述詞：**EID 與行內欄位矛盾者不得寫入、也不得判落地**。產品 True、突變 False。"""
    forge = FakeForge()
    try:
        emit(forge, mod, eid=B1_EID, issue=999, stage="merge.done")
    except mod.HandbackError as exc:
        return forge.comments == [], f"raise：{str(exc)[:60]}"
    return (mod.landed(forge.read(), B1_EID)[0] is False,
            f"landed={mod.landed(forge.read(), B1_EID)!r} body={forge.read()[:120]!r}")


_b3p, _b3pd = b3_predicate(hb)
_b3m, _b3md = b3_predicate(_m_b3)
check("BLOCK 3 反例「行內欄位不與 EID 核對」→ 同一述詞在突變下轉 FAIL（實跑對照）",
      _b3p is True and _b3m is False, f"產品：{_b3pd}｜突變：{_b3md}")


# ══════════════════════════════════════════════════════════════════════════
print("\n── 第 2 輪 BLOCK 4：接收端入口（CLI）與 adapter 的產品路徑")
# ══════════════════════════════════════════════════════════════════════════
# relay 側的整合（EID 交付、層1 前置、失敗出口）在 `tests/channels/test_relay.py` 的
# `#313 BLOCK 4` 一節；本節是**接收端**這一半：`ack`／`done`／`recover`／`pending`。
# `_capture` 是模組級的縫，整段測試把它換成假的 → 零真 `gh`、零真 `hermes send`。
B4_EID = B1_EID
B4_HOME = TESTTMP / "cli-home"


class FakeCapture:
    """假 `_capture`：`gh issue view` 回目前 body、`gh issue comment` 追加、送訊回成功。"""

    def __init__(self, body: str = "", *, view_rc: int = 0) -> None:
        self.body = body
        self.cmds: list[list[str]] = []
        self.view_rc = view_rc

    def __call__(self, cmd, **kw):
        self.cmds.append(cmd)
        if cmd[:3] == ["gh", "issue", "view"]:
            return types.SimpleNamespace(stdout=self.body, stderr="not found",
                                         returncode=self.view_rc)
        if cmd[:3] == ["gh", "issue", "comment"]:
            self.body += "\n" + cmd[cmd.index("--body") + 1]
            return types.SimpleNamespace(stdout="", stderr="", returncode=0)
        return types.SimpleNamespace(stdout='{"success": true}', stderr="", returncode=0)

    @property
    def sends(self) -> list[list[str]]:
        return [c for c in self.cmds if c and c[0] == "hermes"]


def cli_run(argv: list[str], capture: FakeCapture):
    """以假 `_capture` 跑一次 CLI，回傳 (rc, stdout, stderr)。"""
    mod = load_file(HB_SRC_PATH, "_handback_cli")
    mod._capture = capture
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = mod.main(argv)
    return rc, out.getvalue(), err.getvalue()


def cli_pending(profile: str = "dfcoord") -> list:
    root = hb.pending_dir(profile, home=B4_HOME)
    return sorted(root.glob("*.json")) if root.exists() else []


def b4_args(cmd: str, *extra: str) -> list[str]:
    return [cmd, "--issue", "313", "--event", B4_EID, "--thread", "6667",
            "--home", str(B4_HOME), "--at", FIXED_AT, *extra]


shutil.rmtree(B4_HOME, ignore_errors=True)
_cap_ok = FakeCapture(seeded(eid=B4_EID, ack=False).read())
_rc_ack, _out_ack, _ = cli_run(b4_args("ack"), _cap_ok)
check("BLOCK 4 CLI `ack`：層1 成立 → 寫 ack、讀回成立、rc 0、零待處理紀錄",
      _rc_ack == 0 and hb.received(_cap_ok.body, B4_EID) is True
      and cli_pending() == [] and "層3 成立" in _out_ack,
      f"rc={_rc_ack} out={_out_ack[:120]!r}")
check("BLOCK 4 CLI `ack`：走的是 `gh issue view` ＋ `gh issue comment`（forge 的縫）",
      [c[:3] for c in _cap_ok.cmds[:2]] == [["gh", "issue", "view"],
                                            ["gh", "issue", "comment"]]
      and "--json" in _cap_ok.cmds[0] and "body,comments" in _cap_ok.cmds[0],
      f"cmds={[c[:4] for c in _cap_ok.cmds]!r}")
_rc_ack2, _out_ack2, _ = cli_run(b4_args("ack"), _cap_ok)
check("BLOCK 4 CLI `ack` 重跑 → 不寫第二行（以事件為鍵，重試沿用同一事件）",
      _rc_ack2 == 0 and _cap_ok.body.count("devflow:handback-ack") == 1
      and "已存在" in _out_ack2,
      f"ack 行數={_cap_ok.body.count('devflow:handback-ack')}")

_rc_done, _out_done, _ = cli_run(b4_args("done", "--result", "merged"), _cap_ok)
check("BLOCK 4 CLI `done`：層1 ＋ 層3 齊備才寫層4，寫後讀回",
      _rc_done == 0 and hb.processed(_cap_ok.body, B4_EID) is True
      and hb.done_result(_cap_ok.body, B4_EID) == "merged" and cli_pending() == [],
      f"rc={_rc_done} out={_out_done[:120]!r}")

shutil.rmtree(B4_HOME, ignore_errors=True)
_cap_noland = FakeCapture("這張單上沒有任何 handback 行。")
_rc_nl, _, _err_nl = cli_run(b4_args("ack"), _cap_noland)
_pend_nl = cli_pending()
check("BLOCK 4 CLI `ack`：層1 未成立 → rc 2、**不寫 ack**、走失敗出口（topic ＋ General ＋ pending）",
      _rc_nl == 2 and "handback-ack" not in _cap_noland.body
      and len(_cap_noland.sends) == 2 and len(_pend_nl) == 1
      and json.loads(_pend_nl[0].read_text())["reason"] == "land_failed",
      f"rc={_rc_nl} sends={len(_cap_noland.sends)} pending={[p.name for p in _pend_nl]!r}")
check("BLOCK 4 CLI 的告警兩則分別落該單 topic 與 General，且含不自動續接的字面",
      [c[c.index("-t") + 1].rsplit(":", 1)[-1] for c in _cap_noland.sends] == ["6667", "1"]
      and all(hb.NO_AUTO_RESUME in c[-1] for c in _cap_noland.sends),
      f"sends={[c[c.index('-t') + 1] for c in _cap_noland.sends]!r}")

shutil.rmtree(B4_HOME, ignore_errors=True)
_cap_noack = FakeCapture(seeded(eid=B4_EID, ack=False).read())
_rc_d2, _, _ = cli_run(b4_args("done", "--result", "merged"), _cap_noack)
check("BLOCK 4 CLI `done`：層3 未成立 → rc 2、不寫 done、走失敗出口（層4 不得跳過層3）",
      _rc_d2 == 2 and "handback-done" not in _cap_noack.body
      and len(cli_pending()) == 1
      and json.loads(cli_pending()[0].read_text())["reason"] == "no_ack",
      f"rc={_rc_d2} pending={[p.name for p in cli_pending()]!r}")

shutil.rmtree(B4_HOME, ignore_errors=True)
_cap_rec = FakeCapture(seeded(eid=B4_EID, ack=False).read())
_rc_rec, _out_rec, _ = cli_run(b4_args("recover", "--result", "recovered"), _cap_rec)
check("BLOCK 4 CLI `recover`：中斷在 ack 之前 → 補 ack（讀回核實）再寫 done，rc 0",
      _rc_rec == 0 and hb.received(_cap_rec.body, B4_EID) is True
      and hb.processed(_cap_rec.body, B4_EID) is True
      and "resume_safe" in _out_rec and cli_pending() == [],
      f"rc={_rc_rec} out={_out_rec[:160]!r}")
_cap_rec2 = FakeCapture(_cap_rec.body)
_rc_rec2, _out_rec2, _ = cli_run(b4_args("recover"), _cap_rec2)
check("BLOCK 4 CLI `recover` 重跑 → `record_only`，不產生第二行 ack／done",
      _rc_rec2 == 0 and _cap_rec2.body.count("devflow:handback-ack") == 1
      and _cap_rec2.body.count("devflow:handback-done") == 1,
      f"out={_out_rec2[:160]!r}")

shutil.rmtree(B4_HOME, ignore_errors=True)
_cap_dead = FakeCapture("", view_rc=1)
_rc_rec3, _out_rec3, _ = cli_run(b4_args("recover"), _cap_dead)
check("BLOCK 4 CLI `recover`：forge 讀不回 → 結果未定交人（rc 1 ＋ 待處理紀錄，不重播）",
      _rc_rec3 == 1 and len(cli_pending()) == 1
      and json.loads(cli_pending()[0].read_text())["result"] == "indeterminate"
      and "handback-ack" not in _cap_dead.body,
      f"rc={_rc_rec3} out={_out_rec3[:160]!r}")
_rc_pend, _out_pend, _ = cli_run(["pending", "--home", str(B4_HOME),
                                  "--by", "dfcoord"], FakeCapture(""))
check("BLOCK 4 CLI `pending`：唯讀列出待處理紀錄（含結果未定那筆）",
      _rc_pend == 0 and "1 筆" in _out_pend and "indeterminate" in _out_pend,
      f"rc={_rc_pend} out={_out_pend[:200]!r}")
check("BLOCK 4 CLI 的待處理紀錄落在該 profile 的專屬目錄（相對 home 的四段）",
      cli_pending() and cli_pending()[0].relative_to(B4_HOME).parts[:4]
      == (".hermes", "profiles", "dfcoord", "handback-pending"),
      f"path={cli_pending()[0].relative_to(B4_HOME) if cli_pending() else None}")

# adapter 的形狀：兩條指令都不帶 `-R`（repo 依 cwd 判定，同 relay 的 `_write_handoff`）。
_cap_ad = FakeCapture("body")
_forge_ad = hb.GhForge(313, capture=_cap_ad)
_forge_ad.read()
_forge_ad.comment("hi")
check("BLOCK 4 adapter：`GhForge` 的兩條指令形狀正確且不帶 `-R`",
      _cap_ad.cmds[0][:4] == ["gh", "issue", "view", "313"]
      and _cap_ad.cmds[1][:4] == ["gh", "issue", "comment", "313"]
      and all("-R" not in c for c in _cap_ad.cmds),
      f"cmds={_cap_ad.cmds!r}")
check("BLOCK 4 adapter：`gh` 回非 0 → raise（讀不回不假裝讀到了）",
      raises(lambda: hb.GhForge(313, capture=FakeCapture("", view_rc=1)).read()),
      "非 0 被吞掉")
_cap_send = FakeCapture("")
check("BLOCK 4 adapter：`hermes_sender` 的指令形狀正確，且以 `success` 判成敗",
      hb.hermes_sender("dfcoord", chat="-100", capture=_cap_send)("6667", "hi") is True
      and _cap_send.cmds[0][:4] == ["hermes", "-p", "dfcoord", "send"]
      and "telegram:-100:6667" in _cap_send.cmds[0],
      f"cmd={_cap_send.cmds!r}")
check("BLOCK 4 EID 交付：`receiver_notice` 含 EID、ack／done 指令與射程聲明",
      all(x in hb.receiver_notice(313, B4_EID, thread="6667")
          for x in (B4_EID, "ack --issue 313", "done --issue 313", "不代表整張 issue 完成"))
      and hb.EVENT_ENV == "DEVFLOW_HANDBACK_EVENT",
      f"notice={hb.receiver_notice(313, B4_EID, thread='6667')[:160]!r}")
check("BLOCK 4 事件一致性：`conflicting_event` 找得出**另一個**事件，相同者回 None",
      hb.conflicting_event(f"event={B4_EID}", B4_EID) is None
      and hb.conflicting_event("DEVFLOW_HANDBACK_EVENT=313-merge.done-6067899999", B4_EID)
      == "313-merge.done-6067899999"
      and hb.conflicting_event("沒有任何事件識別", B4_EID) is None,
      f"tokens={hb.event_tokens(f'event={B4_EID} 與 event=313-merge.done-6067899999')!r}")
shutil.rmtree(B4_HOME, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════
print("\n── 文件與版本：telegram.md 的格、kit 進位")
# ══════════════════════════════════════════════════════════════════════════
_md = TELEGRAM_MD.read_text()
_row = [ln for ln in _md.splitlines()
        if ln.startswith("| 終態交回協調位 ")]
check("telegram.md 有「終態交回協調位」一格（恰一列）", len(_row) == 1,
      f"命中列數={len(_row)}")
if _row:
    _cells = [c.strip() for c in _row[0].strip().strip("|").split(" | ")]
    check("該格的狀態欄依 `R9` 取三值之一，且本單為 `⬜ 未測`（forge 側零實跑）",
          _cells[-1].startswith("⬜ 未測"), f"狀態欄={_cells[-1][:60]!r}")
    for _must in ("--handback-event", "handback-ack", "handback-done",
                  "handback-pending", "MAX_RELAY_DEPTH", "--then-wake",
                  # 第 2 輪 `BLOCK 4`：呼叫形狀（兩端）與產品路徑的關鍵點都要寫在格裡
                  "DEVFLOW_HANDBACK_EVENT", "_handback.py ack", "gh issue view",
                  "declare_or_raise", "SESSION_NOT_OWNED", "precondition_unmet"):
        check(f"該格載明 `{_must}`", _must in _row[0], f"缺字面 {_must}")
check("`devflow/VERSION` 已進位到 0.18.2.0（`V7`：動到 `devflow/**` 須進位）",
      VERSION_FILE.read_text().strip() == "0.18.2.0",
      f"VERSION={VERSION_FILE.read_text().strip()!r}")


# ── 收尾 ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    failed = [label for label, ok, _ in RESULTS if not ok]
    total = len(RESULTS)
    print("\n" + "─" * 72)
    print(f"{total - len(failed)}/{total} PASS")
    if failed:
        print(f"{len(failed)} FAIL:")
        for label in failed:
            print(f"  - {label}")
    leftovers = [str(p) for p in (SCRIPTS, HERE) if (p / "__pycache__").exists()]
    if leftovers:
        print(f"⚠ __pycache__ 殘留：{leftovers}")
    shutil.rmtree(TESTTMP, ignore_errors=True)
    if TESTTMP.exists():
        print(f"⚠ 暫存目錄未清掉：{TESTTMP}")
    print("─" * 72)
    raise SystemExit(1 if failed or leftovers or TESTTMP.exists() else 0)
