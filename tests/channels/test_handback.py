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
import json
import re
import shutil
import sys
import tempfile
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


def emit(forge, mod=hb, *, eid, issue=313, seat="dfmgr", stage="r1.approve",
         kind="stage", outcome="done", at=FIXED_AT):
    return mod.emit_handback(forge, event=eid, issue=issue, seat=seat, stage=stage,
                             kind=kind, outcome=outcome, at=at)


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
AC2_RECEIVED = '    return any(m.group("event") == eid for m in ACK_RE.finditer(body))\n'
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

# ── 縫：模組自己不碰外部世界（故「零真 API」是結構性的，不是紀律）──
# 判定走 **AST**，不是字串搜尋：本模組的 docstring 刻意寫著「不 import `subprocess`」
# 這幾個詞，字串搜尋會把**自述**當成違規（假陽性），而真正要鎖的是 import 與呼叫。
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
_HB_ALLOWED = {"__future__", "json", "pathlib", "re", "time", "collections", "typing"}
_HB_CALLS = [ast.unparse(n.func) for n in ast.walk(_HB_TREE) if isinstance(n, ast.Call)]
_HB_BAD_CALLS = [c for c in _HB_CALLS
                 if any(t in c for t in ("subprocess", "urlopen", "socket", "system",
                                         "requests", "stderr", "print"))]
check("AC-2 縫：受測模組只 import 純運算與路徑的標準模組（AST 判定，不是字串搜尋）",
      set(_HB_IMPORTS) <= _HB_ALLOWED,
      f"import={_HB_IMPORTS!r} 超出={sorted(set(_HB_IMPORTS) - _HB_ALLOWED)!r}")
check("AC-2 縫：一個 subprocess／urlopen／socket／os.system／print／stderr 的呼叫都沒有",
      _HB_BAD_CALLS == [], f"命中呼叫={_HB_BAD_CALLS!r}")
check("AC-2 縫：forge 與送訊都是注入的參數（本檔給假物件即全部攔下）",
      "forge: Any" in HB_SRC and "send: Callable[[str, str], Any]" in HB_SRC,
      "forge／send 不是注入的縫")


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
rec_a = hb.recover(FakeForge(), E_REC, steps_of(ext_a, ["merge", "archive"]),
                   runner(ext_a, ran_a), at=FIXED_AT)
check("AC-4 `resume_safe`：讀回 merge=已做／archive=未做 → **只跑 archive**，不重做 merge",
      rec_a.verdict == hb.RESUME_SAFE and [n for n, _ in ran_a] == ["archive"]
      and rec_a.done_written is True,
      f"verdict={rec_a.verdict} ran={ran_a!r}")

ext_b = {"merge": True, "archive": True}
ran_b: list = []
fg_b = FakeForge()
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
    fg_c = FakeForge()
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
fg_f = FakeForge()
rec_f = hb.recover(fg_f, E_REC, steps_of(ext_f, ["archive"]),
                   runner(ext_f, ran_f, succeed=False), at=FIXED_AT)
check("AC-4 動作「沒拋例外」但執行後讀回仍為未做 → **不得寫 done**，判 escalate_human",
      rec_f.verdict == "escalate_human" and [n for n, _ in ran_f] == ["archive"]
      and rec_f.done_written is False and hb.processed(fg_f.read(), E_REC) is False
      and rec_f.report["archive"] is False,
      f"verdict={rec_f.verdict} report={rec_f.report!r}")
ext_g = {"archive": False}
ran_g: list = []
fg_g = FakeForge()


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
rec_h = hb.recover(FakeForge(fail_write=True), E_REC, steps_of(ext_h, ["archive"]),
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
    forge = FakeForge()
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
_m4c.recover(FakeForge(), E_REC, steps_of(_ext_blind, ["merge", "archive"]),
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
check("AC-6 **不得只留 stderr 或 headless 最終回覆**：模組無 stderr 出口，告警只能經注入的 send",
      "sys.stderr" not in HB_SRC and "print(" not in HB_SRC
      and "import sys" not in HB_SRC,
      "模組裡有 stderr／print 的出口")

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
                  "handback-pending", "MAX_RELAY_DEPTH", "--then-wake"):
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
