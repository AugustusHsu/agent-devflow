#!/usr/bin/env python3
"""`#298`／K4c-7：`devflow_relay.py` 的 `--then-wake` 銜接（`AC-1`～`AC-7`、`AC-12`），
以及 `#300`／K4c-8：第二棒的 handoff 行（本檔下半 `#300 AC-1`～`AC-11`）。

直接執行：`/usr/bin/python3 tests/channels/test_relay.py`
全過 exit 0、任一項失敗 exit 非 0，stdout 逐項列 PASS／FAIL（風格同 `test_marker.py`）。

**縫只有一處**：relay 的對外效果全部經模組全域的 `subprocess`——`run` 是唯一的同步出口
（`_send` 送 topic、`_write_handoff` 寫 forge 都經它，`#300` 起集中在 `_capture`），
`_run_child` 的 `Popen` 是唯一的子程序出口。實查無 `requests`／`urllib`／`http`／`socket`／
`os.system`。替掉那一個名字即全部攔下，所以本檔零真 API、零真子程序（`AC-6`）——
`gh` 與送訊走**同一個名字**，故 handoff 行的驗證同樣零真 API（`#300` `AC-10`）。

零 import-path 操作（`AC-6`，機械判準 `grep -nE 'sys\\.path'` 無命中，故本檔連字面都不
出現）：受測模組以 `importlib.util.spec_from_file_location` 從 **repo 真實目錄**
`devflow/channels/scripts/telegram/` 載入。必須是真實目錄而非 `~/.hermes/scripts`：
relay 有 `from devflow_archive import tool_summary`，而 `devflow_archive.py` 自己
`import _marker`，指到未建 symlink 的目錄即 `ModuleNotFoundError`。同層 import 靠把已
載入的模組登錄進 `sys.modules` 滿足——那是 import 機制本身，不是搜尋路徑操作。

時間常數一律顯式覆寫（`AC-5`）：`OPENING_DELAY` 與 `HEARTBEAT_AFTER` 的現值是 20s／300s，
不覆寫的話下一個加測試的人會依賴 wall-clock。

**本檔驗的是「relay 發出了什麼」，不是「被喚醒的 seat 做對了什麼」**（`#298` 射程界線）：
`spawned[1]` 含 `-p dfmgr` 與正確 prompt 可驗；mgr 收到後是否真的 push 只有端到端那次能證。
同理 `#300` 只驗「relay 發出了那則留言的指令」，**不**驗 forge 上真的多了一則留言——
本檔不打真 `gh`，forge 側零實跑（`channels/telegram.md` 該格的狀態欄因此是 `⬜`）。
"""
# 「同形斷言」判準（`#308` `AC-1`）全 repo 只一處（`I5`）：見
# `tests/channels/test_marker.py` **檔頂**的判準註解——寫新斷言前先讀那三項判準；
# 守門的自檢在該檔 `#308 AC-2` 一節（它掃該檔與**本檔**的當下內容）。
from __future__ import annotations

import ast
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import types
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.dont_write_bytecode = True          # 不在受測目錄留 __pycache__（repo 慣例）

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SCRIPTS = REPO / "devflow" / "channels" / "scripts" / "telegram"
RELAY_SRC_PATH = SCRIPTS / "devflow_relay.py"
MANAGER_MD = REPO / "devflow" / "seats" / "manager.md"
TELEGRAM_MD = REPO / "devflow" / "channels" / "telegram.md"
WORKFLOW_MD = REPO / "devflow" / "WORKFLOW.md"
CHANNELS_README = REPO / "devflow" / "channels" / "README.md"
VERSION_FILE = REPO / "devflow" / "VERSION"

SELF_SRC = Path(__file__).read_text()
RELAY_SRC = RELAY_SRC_PATH.read_text()

# 本檔自己的暫存目錄：relay 的 log 走 `tempfile.gettempdir()`，不收束的話每跑一次就在
# 暫存根留下幾個 `relay-*.log`（實測累積上百個）。指向一個本檔擁有的子目錄，收尾整個刪掉。
# 仍在真實暫存根之下，故「log 不寫進 repo」那幾條斷言的語意不變。
TESTTMP = Path(tempfile.mkdtemp(prefix="devflow-test_relay."))
tempfile.tempdir = str(TESTTMP)        # relay 與本檔的 gettempdir() 都改指這裡

RESULTS: list[tuple[str, bool, str]] = []

# 真時鐘的備份。`freeze_clock` 動的是 `time` 模組物件本身（受測模組與本檔共用同一個
# 物件），所以**凍過就會留著**——`BLOCK 1` 之後的案例會一路拿到 `FIXED`。`load()` 因此
# 明寫兩個方向：要凍就凍、不凍就還原，結果只取決於它自己的參數，不取決於前面有誰凍過
# （`#300` 的 handoff 行要驗真的 ISO 8601 時刻，正是踩到這個）。
_REAL_STRFTIME = time.strftime


def check(label: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((label, bool(ok), detail))
    print(("  ✅ " if ok else "  ❌ ") + label)
    if not ok and detail:
        print(f"      → {detail}")
    return bool(ok)


# ── 載入受測模組 ─────────────────────────────────────────────────────────────
def _register(name: str, path: Path) -> None:
    """載入單檔模組並登錄進 sys.modules，供受測腳本的同層 import 解析。"""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)


def load(fake, *, freeze_clock: bool = False):
    """每個案例重新載入一份 relay（模組狀態乾淨），注入假 subprocess 並覆寫時間常數。

    `freeze_clock`：把秒級時間戳凍成常數，用來強制「兩棒落在同一秒」（`BLOCK 1`）——
    否則那條測試要靠搶時鐘才會紅。
    """
    if "devflow_archive" not in sys.modules:
        _register("_marker", SCRIPTS / "_marker.py")          # devflow_archive 內 `import _marker`
        _register("devflow_archive", SCRIPTS / "devflow_archive.py")
        # `#313`：relay 的終態投遞分支 `from _handback import …`（同目錄，同 devflow_archive
        # 的做法）。登錄進 `sys.modules` 即可解析，仍然零 import-path 操作。
        _register("_handback", SCRIPTS / "_handback.py")
    spec = importlib.util.spec_from_file_location("devflow_relay", RELAY_SRC_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.subprocess = fake
    # AC-5：顯式覆寫兩個時間常數，測試不得依賴 wall-clock（現值 20s／300s）。
    mod.OPENING_DELAY = 10 ** 9
    mod.HEARTBEAT_AFTER = 10 ** 9
    if freeze_clock:
        mod.time.strftime = lambda _fmt: "FIXED"
    else:
        mod.time.strftime = _REAL_STRFTIME   # 前面凍過的話在這裡還原（見 _REAL_STRFTIME）
    return mod


class FakeProc:
    """假子程序。每次建立都要新的 iterator——then-wake 會建第二次。

    `waits` 計數與 `events` 裡的 `wait` 事件供 `#300` `AC-1` 的時機斷言用：handoff 行
    必須在第二棒 `Popen` 之後、`wait()` **之前**寫出去（等 `wait()` 回來才寫 ＝ 等第二棒
    結束，T 明列否決）。`events` 由建立者（`FakeSub`）傳進來，與 `Popen`／`run` 共用
    同一條時間軸，所以先後次序讀得出來，不必靠時鐘。
    """

    def __init__(self, lines: list[str], rc: int,
                 events: list[str] | None = None) -> None:
        self.stdout = iter(lines)
        self.stderr = iter([])
        self.returncode = rc
        self.waits = 0
        self._events = events

    def wait(self) -> int:
        self.waits += 1
        if self._events is not None:
            self._events.append("wait")
        return self.returncode


class FakeSub:
    """假 subprocess 模組。PIPE／DEVNULL／STDOUT 三個都要（`AC-7`）：

    `_run_child` 的 `Popen` 呼叫裡用了 `subprocess.DEVNULL`，只定義 `PIPE` 會在 kwargs
    求值時就掛成 `AttributeError: 'FakeSub' object has no attribute 'DEVNULL'`——
    那是裁決位與協調位各自踩到的實測。`STDOUT` 一併定義，日後改用合流就不必再回來補。

    `#300` 起 `run` 多做三件事，都不改既有語意：
      * 回傳物件帶 `returncode`（預設 0）——`_write_handoff` 讀它判成敗，而 `_send` 仍只
        讀 stdout 的 `"success": true`，兩邊的判準各自獨立（`gh_rc` 不影響送訊）。
      * 記 `events`（與 `procs` 共用一條時間軸）供時機斷言。
      * `gh_rc` 非 0 時只對 `cmd[0] == "gh"` 的呼叫生效，`hermes send` 照舊成功。
    `sent` 仍收**所有** `run` 的 cmd（既有斷言不動）；`gh` 與 `hermes` 以 `cmd[0]` 區分，
    `gh_calls`／`send_calls` 兩個 property 讓「幾個 gh 呼叫」與「幾則送訊」各自讀得出來。
    """

    PIPE = -1
    DEVNULL = -3
    STDOUT = -2

    def __init__(self, lines: list[str], rc: int = 0, *, gh_rc: int = 0,
                 issue_body: str | None = None, err_lines: list[str] | None = None) -> None:
        self.sent: list[list[str]] = []        # 所有 run 的 cmd（送訊 ＋ gh）
        self.spawned: list[list[str]] = []     # 子程序的 Popen
        self.kwargs: list[dict] = []
        self.procs: list[FakeProc] = []        # 建出來的假子程序，供 waits 計數用
        self.events: list[str] = []            # 時間軸：popen／run:<argv0>
        self._lines = lines
        self._rc = rc
        self._gh_rc = gh_rc
        # `#313`：`gh issue view` 要回該單的可讀文字（body ＋ 留言）。預設給一份層1 ＋
        # 層3 齊備的，讓終態投遞的正向路徑跑得完；要測未達成就傳 `issue_body=""` 等。
        self.issue_body = HB_BODY if issue_body is None else issue_body
        self._err_lines = err_lines or []

    @property
    def gh_calls(self) -> list[list[str]]:
        return [c for c in self.sent if c and c[0] == "gh"]

    @property
    def gh_view_calls(self) -> list[list[str]]:
        return [c for c in self.gh_calls if c[1:3] == ["issue", "view"]]

    @property
    def gh_comment_calls(self) -> list[list[str]]:
        return [c for c in self.gh_calls if c[1:3] == ["issue", "comment"]]

    @property
    def send_calls(self) -> list[list[str]]:
        return [c for c in self.sent if c and c[0] == "hermes"]

    def run(self, cmd, **kw):
        self.sent.append(cmd)
        self.events.append(f"run:{cmd[0] if cmd else '?'}")
        rc = self._gh_rc if (cmd and cmd[0] == "gh") else 0
        stdout = '{"success": true}'
        if cmd[:3] == ["gh", "issue", "view"]:
            stdout = self.issue_body            # `#313`：層1／層3 的讀回
        return types.SimpleNamespace(stdout=stdout, stderr="", returncode=rc)

    def Popen(self, cmd, **kw):               # noqa: N802 — 對齊 subprocess 的名字
        self.kwargs.append(kw)
        self.spawned.append(cmd)
        self.events.append("popen")
        proc = FakeProc(self._lines, self._rc, self.events)
        proc.stderr = iter(self._err_lines)   # `#313`：忙碌／失敗的分辨靠它
        self.procs.append(proc)
        return proc


LINES = [
    '{"type":"system","subtype":"init","model":"test-model"}\n',
    '{"type":"tool_use","tool_call_id":"c1","name":"terminal","input":{"command":"git status"}}\n',
    '{"type":"tool_result","tool_call_id":"c1","name":"terminal","output":"clean"}\n',
    '{"type":"result","text":"做完了","duration_ms":1234}\n',
]

# ── `#313`：終態投遞的假 forge 內容 ─────────────────────────────────────────────
# relay 在 `--handback-event` 模式下，**派子程序之前**會以 `gh issue view` 讀回層1
# （該 EID 的 `handback` 行恰一行且自相一致），子程序退出後再讀一次核層3（ack）。
# 兩次都經模組全域的 `subprocess`（`_capture`），所以假類照樣全部攔下，仍零真 API。
# 三行字面**由產品模組生成**，不在本檔重打一份——grammar 漂移時這裡會跟著動，不會
# 悄悄比對到一個過期的字面。
HB_EID = "313-r1.approve-6067812345"
HB_AT = "2026-10-16T12:00:00+0800"


def _handback_mod():
    """載入並登錄 `_handback`（relay 的終態投遞分支 import 它），回傳該模組。"""
    if "_handback" not in sys.modules:
        _register("_handback", SCRIPTS / "_handback.py")
    return sys.modules["_handback"]


HB_LINE = _handback_mod().handback_line(
    event=HB_EID, issue=313, seat="dfmgr", stage="r1.approve",
    kind="stage", outcome="done", at=HB_AT)
HB_ACK = _handback_mod().ack_line(event=HB_EID, by="dfcoord", at=HB_AT)
HB_BODY_NO_ACK = f"`#313` 的 r1.approve 階段交回。\n\n{HB_LINE}\n"
HB_BODY = f"{HB_BODY_NO_ACK}\n{HB_ACK}\n"      # 層1 ＋ 層3 齊備（正向路徑）


LAST_MOD: list = []            # run() 把最後一次載入的模組放這裡，供需要它的案例取用


def run_mod(mod, argv: list[str]):
    """以 sys.argv 餵參數呼叫**某個已載入模組**的 `main()`，回傳 (rc, stdout, stderr)。

    `#312` 起與突變模組共用（反例一律實跑，見本檔下半 `#312` 一節的 `load_mutant`）：
    驅動只有這一份，正例與反例跑的才保證是同一條路徑（`I5` 的同一個道理）。
    """
    saved_argv = sys.argv
    sys.argv = ["devflow_relay.py"] + argv
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                rc = mod.main()
            except SystemExit as exc:          # argparse 的 error() 走這條
                rc = exc.code
    finally:
        sys.argv = saved_argv
    return rc, out.getvalue(), err.getvalue()


def run(argv: list[str], fake, *, freeze_clock: bool = False):
    """以 sys.argv 餵參數呼叫 main()，回傳 (rc, stdout, stderr)。

    載入的模組另放進 `LAST_MOD[-1]`——`BLOCK 1` 要在同一個模組實例上續呼
    `_log_path`（序號是模組級狀態），回傳值不改形狀以免動搖既有案例。
    """
    mod = load(fake, freeze_clock=freeze_clock)
    LAST_MOD.append(mod)
    return run_mod(mod, argv)


def prompt_of(cmd: list[str]) -> str:
    """從 `hermes … chat -q <prompt> …` 取出 prompt。"""
    return cmd[cmd.index("-q") + 1] if "-q" in cmd else ""


# ── log 路徑與單號的判定（`#312` `AC-8`）─────────────────────────────────────
# 這兩個共用判定函式是本檔對「log 在不在某個目錄下」與「這個 log 是哪一張單的」的**唯一**
# 判定（`I5`）：三條既有 check 與下方 `#312 AC-8` 一節的固定情境正反測試共用它們——正例與
# 反例跑同一支判定，對照才算對照。兩者都不讀環境；`_issue_of` 是純字串運算，`_under`
# 則以 `resolve()` 正規化兩側之後比階層——`resolve()` 會跟 symlink，故它**不是**純字串
# 運算，本檔也不對它的 I/O 面下任何更強的宣稱（`AC-8(g)`）：正規化是判定正確的前提，
# 理由見 `_under` 的 docstring。（`AC-9(c)`：故這一段不寫「純函式」——那與下兩句牴觸。）
def _under(root, path) -> bool:
    """`path` 是否位於 `root` 這個目錄**階層**之下（含 root 自身）。

    為什麼不能用字串（`AC-8(a)`；`#312` 第 3 輪 `R1` `BLOCK 1` 的實測）：審查位的丟棄式
    checkout 是 `…/agent-devflow.review/312-r3`、其暫存根是**兄弟目錄**
    `…/agent-devflow.review/312-r3-tmp`，於是 `str(REPO) in str(log)` 為 **True**
    （子字串命中）、`str(log).startswith(str(REPO))` 也為 **True**（前綴命中），
    而那個 log 根本不在 repo 內。「在不在某個目錄下」是階層關係，只有逐段比對
    （`is_relative_to`／`parents`）答得對；前綴與子字串都會被「名字剛好以它起首的
    兄弟目錄」騙過去。

    兩側都先 `resolve()`：symlink 與 `..` 不正規化的話，同一個位置有多種寫法。
    """
    try:
        return Path(path).resolve().is_relative_to(Path(root).resolve())
    except ValueError:            # 不同磁碟根等無法比較的情形 ＝ 不在其下
        return False


# log 檔名的 grammar ＝ `_log_path` 的 f-string：
#     relay-<issue>-<profile>-<stamp>-<pid>-<seq>.log
# 右邊三欄的形狀是固定的（`stamp` ＝ `%Y%m%d-%H%M%S`，本檔凍結時鐘時為 `FIXED`；
# `pid`／`seq` ＝ 純數字）且整串錨到 `$`，故 **profile 欄可以含 `-`**：以非貪婪比對從右
# 側切欄，右邊三欄先各就各位，剩下的就是 profile。`issue` 欄維持不含 `-`（單號是數字）。
#
# profile 為何必須容許 `-`（`AC-9(a)`，第 5 輪 `R1` 指出）：**產品**產生得出這種檔名——
# `_log_path` 對 profile 不設限，`HANDOFF_RE` 更明文允許 `[A-Za-z0-9_.\-]+`。原本寫成
# `[^-]+` 的 profile 欄比產品的 grammar **窄**，於是 `_issue_of` 對一個**合法**的 log
# （例 `-p df-review` 產生的 `relay-999-df-review-…`）回空字串而不是 `'999'`。
# ⚠️ 那是**這個測試 helper 的問題，不是正式 relay 派工失敗**：`_log_path`／`HANDOFF_RE`
# 的行為正確，該缺陷不影響任何實際派工（裁決位 2026-10-15 的定性）。
_LOG_NAME_RE = re.compile(
    r"^relay-(?P<issue>[^-]+)-(?P<profile>.+?)-"
    r"(?P<stamp>\d{8}-\d{6}|FIXED)-(?P<pid>\d+)-(?P<seq>\d+)\.log$")


def _issue_of(logname: str) -> str:
    """log 檔名的 `issue` **欄位**（只看檔名，不管前面的目錄）；不合 grammar 回空字串。

    為什麼不能搜尋整個檔名（`AC-8(b)`）：單號是第一欄，而 `pid` 與 `stamp` 也是數字——
    第 3 輪實測的 PID `2528717` 含 `287`，使「`287` 不在檔名裡」那個鑑別力條假 FAIL
    （`relay-999-dfmgr-20261015-051730-2528717-1.log`，單號其實是 `999`）。
    """
    m = _LOG_NAME_RE.match(Path(logname).name)
    return m.group("issue") if m else ""


def _only_pipe_probe() -> tuple[str, str]:
    """`AC-7` 的反測：只定義 `PIPE` 的假類，期望在 `Popen` 的 kwargs 求值時掛掉。

    這是裁決位與協調位各自踩到的實測；它證明 `AC-7` 的三個常數不是湊數。
    """
    class OnlyPIPE:
        PIPE = -1

        def __init__(self) -> None:
            self.spawned: list = []
            self.sent: list = []
            self.kwargs: list = []

        def run(self, cmd, **kw):
            return types.SimpleNamespace(stdout='{"success": true}', stderr="")

        def Popen(self, cmd, **kw):   # noqa: N802
            self.spawned.append(cmd)
            return FakeProc(LINES, 0)

    try:
        run(["4149", "hi"], OnlyPIPE())
    except AttributeError as exc:
        return "AttributeError", str(exc)
    return "none", ""


# ── AC-1：--then-wake 的鏈結 ─────────────────────────────────────────────────
print("\n── AC-1：--then-wake 的鏈結（現行值 1 ≠ 期望 2）")

f1 = FakeSub(LINES)
rc1, _, err1 = run(["4149", "hi", "--issue", "287", "--then-wake", "dfmgr"], f1)
check("AC-1 `--issue 287 --then-wake dfmgr` → len(spawned) == 2",
      len(f1.spawned) == 2, f"rc={rc1} spawned={len(f1.spawned)} stderr={err1[:300]!r}")
check("AC-1 spawned[1] 含 `-p dfmgr`（喚醒的是指定 profile）",
      len(f1.spawned) == 2 and "-p" in f1.spawned[1]
      and f1.spawned[1][f1.spawned[1].index("-p") + 1] == "dfmgr",
      f"spawned[1]={f1.spawned[1] if len(f1.spawned) > 1 else None}")
check("AC-1 spawned[0] 仍是受託的 profile（喚醒沒有蓋掉第一棒）",
      bool(f1.spawned) and f1.spawned[0][f1.spawned[0].index("-p") + 1] == "dfmgr",
      f"spawned[0]={f1.spawned[0] if f1.spawned else None}")
check("AC-1 rc 回傳的是受託子程序的 rc（0），不是喚醒者的",
      rc1 == 0, f"rc={rc1}")
# 鑑別力：換一個 profile，spawned[1] 必須跟著換——固定寫死 dfmgr 的實作會在這裡掛。
f1b = FakeSub(LINES)
run(["4149", "hi", "--issue", "287", "-p", "dfimpl", "--then-wake", "dfcoord"], f1b)
check("AC-1 鑑別力：`-p dfimpl --then-wake dfcoord` → spawned[0] 是 dfimpl、spawned[1] 是 dfcoord",
      len(f1b.spawned) == 2
      and f1b.spawned[0][f1b.spawned[0].index("-p") + 1] == "dfimpl"
      and f1b.spawned[1][f1b.spawned[1].index("-p") + 1] == "dfcoord",
      f"spawned={[c[:4] for c in f1b.spawned]}")
check("AC-1 喚醒者不再被 then-wake（無限鏈的防線不靠深度上限兜底）",
      len(f1b.spawned) == 2, f"spawned={len(f1b.spawned)}（>2 表示喚醒者又鏈下去）")
check("AC-1 喚醒者續接 `issue-287`（同一 seat 的續接，不給 --fresh）",
      len(f1.spawned) == 2 and "-c" in f1.spawned[1]
      and f1.spawned[1][f1.spawned[1].index("-c") + 1] == "issue-287",
      f"spawned[1]={f1.spawned[1] if len(f1.spawned) > 1 else None}")
check("AC-1 喚醒者不承襲 `--in`（worktree 是實作位的，管理位在主 checkout）",
      len(f1b.spawned) == 2 and "--in" not in f1b.spawned[1],
      f"spawned[1]={f1b.spawned[1] if len(f1b.spawned) > 1 else None}")

# ── BLOCK 2（第 2 輪 R1）：`-m`／`--provider` 不得承襲，`I7` ──
# 覆寫只作用於該次子程序（配額耗盡時的一次性切換）；被喚醒者是另一個 seat 的另一輪，
# 須用自己 profile 的綁定。承襲等於由 relay 替它換綁定——那不是 relay 的事。
f1c = FakeSub(LINES)
rc1c, _, _ = run(["4149", "hi", "-p", "dfrev", "--issue", "287", "--then-wake", "dfmgr",
                  "-m", "review-model", "--provider", "review-provider"], f1c)
check("BLOCK 2 首棒確實帶了 `-m`／`--provider`（覆寫對該次子程序有效，不是沒傳進來）",
      len(f1c.spawned) == 2
      and f1c.spawned[0][f1c.spawned[0].index("-m") + 1] == "review-model"
      and f1c.spawned[0][f1c.spawned[0].index("--provider") + 1] == "review-provider",
      f"spawned[0]={f1c.spawned[0] if f1c.spawned else None}")
check("BLOCK 2 `spawned[1]` 不含 `-m`（I7：被喚醒者用自己 profile 的綁定）",
      len(f1c.spawned) == 2 and "-m" not in f1c.spawned[1],
      f"spawned[1]={f1c.spawned[1] if len(f1c.spawned) > 1 else None}")
check("BLOCK 2 `spawned[1]` 不含 `--provider`（同上）",
      len(f1c.spawned) == 2 and "--provider" not in f1c.spawned[1],
      f"spawned[1]={f1c.spawned[1] if len(f1c.spawned) > 1 else None}")
check("BLOCK 2 連模型／provider 的值字面都不在喚醒棒的指令裡",
      len(f1c.spawned) == 2
      and "review-model" not in f1c.spawned[1] and "review-provider" not in f1c.spawned[1],
      f"spawned[1]={f1c.spawned[1] if len(f1c.spawned) > 1 else None}")
check("BLOCK 2 不承襲覆寫但其餘旗標照舊（-p 喚醒對象、-c 續接、prompt 都還在）",
      len(f1c.spawned) == 2 and rc1c == 0
      and f1c.spawned[1][f1c.spawned[1].index("-p") + 1] == "dfmgr"
      and f1c.spawned[1][f1c.spawned[1].index("-c") + 1] == "issue-287"
      and "-q" in f1c.spawned[1],
      f"rc={rc1c} spawned[1]={f1c.spawned[1] if len(f1c.spawned) > 1 else None}")


# ── AC-2：喚醒 prompt 的內容 ────────────────────────────────────────────────
print("\n── AC-2：喚醒 prompt 須含單號、子程序 log 路徑、rc")

f2 = FakeSub(LINES, rc=0)
run(["4149", "hi", "--issue", "287", "--then-wake", "dfmgr"], f2)
wake_prompt = prompt_of(f2.spawned[1]) if len(f2.spawned) == 2 else ""
check("AC-2 prompt 含 issue 號（`#287`）", "#287" in wake_prompt, repr(wake_prompt[:300]))
check("AC-2 prompt 含子程序的 rc（`rc=0`）", "rc=0" in wake_prompt, repr(wake_prompt[:300]))

logs = re.findall(r"relay-[^`\s]+\.log", wake_prompt)
check("AC-2 prompt 含一個 log 檔名（命名含 issue 與 profile）",
      len(logs) == 1 and "287" in logs[0] and "dfmgr" in logs[0],
      f"命中={logs}")
log_paths = re.findall(r"`(/[^`]+\.log)`", wake_prompt)
check("AC-2 log 路徑是絕對路徑",
      len(log_paths) == 1 and Path(log_paths[0]).is_absolute(), f"命中={log_paths}")
if log_paths:
    lp = Path(log_paths[0])
    check("AC-2 log 落在 $TMPDIR 下，不寫進 repo",
          _under(tempfile.gettempdir(), lp) and not _under(REPO, lp),
          f"log={lp} tmp={tempfile.gettempdir()} repo={REPO} "
          f"（判定為路徑階層，見 `_under`：子字串／前綴會被同名前綴的兄弟目錄騙過）")
    check("AC-2 log 檔真的存在，且內容是子程序的原始 stream-json 行（不是摘要）",
          lp.exists() and '"type":"tool_use"' in lp.read_text()
          and '"type":"result"' in lp.read_text(),
          f"exists={lp.exists()} head={lp.read_text()[:120]!r} if exists")

# 鑑別力：rc 非 0 時 prompt 裡的 rc 必須跟著變（寫死 `rc=0` 的實作在這裡掛）。
f2b = FakeSub(LINES, rc=3)
rc2b, _, _ = run(["4149", "hi", "--issue", "287", "--then-wake", "dfmgr"], f2b)
wake_b = prompt_of(f2b.spawned[1]) if len(f2b.spawned) == 2 else ""
check("AC-2 鑑別力：子程序 rc=3 時 prompt 寫 `rc=3`，且 main() 回傳 3",
      "rc=3" in wake_b and rc2b == 3, f"rc={rc2b} prompt={wake_b[:200]!r}")
check("AC-2 鑑別力：子程序失敗仍會喚醒（失敗更需要有人接手）",
      len(f2b.spawned) == 2, f"spawned={len(f2b.spawned)}")

# 鑑別力：換單號時 prompt 的單號與 log 檔名都要跟著換（寫死 287 的實作在這裡掛）。
f2c = FakeSub(LINES)
run(["4149", "hi", "--issue", "999", "--then-wake", "dfmgr"], f2c)
wake_c = prompt_of(f2c.spawned[1]) if len(f2c.spawned) == 2 else ""
logs_c = re.findall(r"relay-[^`\s]+\.log", wake_c)
check("AC-2 鑑別力：`--issue 999` → prompt 寫 `#999`、log 檔名含 999（非寫死 287）",
      "#999" in wake_c and "#287" not in wake_c
      and len(logs_c) == 1 and _issue_of(logs_c[0]) == "999",
      f"prompt={wake_c[:200]!r} logs={logs_c} "
      f"issue 欄位={_issue_of(logs_c[0]) if logs_c else None!r}"
      f"（單號取 grammar 的第一欄，見 `_issue_of`：pid／stamp 也是數字）")
check("AC-2 鑑別力：兩輪的 log 路徑互不相同（不會覆寫彼此的現場）",
      bool(logs) and bool(logs_c) and logs[0] != logs_c[0],
      f"{logs} vs {logs_c}")
check("AC-2 prompt 要被喚醒者自己去 forge 讀材料（relay 不寫下一步做什麼）",
      "forge" in wake_prompt and "gh issue view" in wake_prompt,
      repr(wake_prompt[:300]))


# ── BLOCK 1（第 2 輪 R1）：log 路徑不得碰撞 ──────────────────────────────────
print("\n── BLOCK 1：同 issue／同 profile／同秒的兩棒 log 不得互相覆寫")


class TaggedSub(FakeSub):
    """每次 `Popen` 吐**不同**的事件內容，用來分辨 prompt 指到的是哪一棒的 log。

    碰撞的病徵是「兩棒拿到同一路徑、喚醒棒覆寫首棒」，此時 prompt 指的檔案仍是首棒那個
    路徑，但內容已經是第二棒的——只比對路徑字串看不出來，必須讀檔案內容才抓得到。
    """

    def Popen(self, cmd, **kw):   # noqa: N802
        tag = "FIRST_CHILD" if not self.spawned else "WAKE_CHILD"
        self.kwargs.append(kw)
        self.spawned.append(cmd)
        self.events.append("popen")
        proc = FakeProc(
            [f'{{"type":"result","text":"{tag}","duration_ms":1}}\n'], self._rc,
            self.events)
        self.procs.append(proc)
        return proc


fb1 = TaggedSub([])
rcb1, _, errb1 = run(["4149", "hi", "--issue", "287", "--then-wake", "dfmgr"],
                     fb1, freeze_clock=True)
_m = LAST_MOD[-1]

check("BLOCK 1 前置：兩棒的 issue 與 profile 完全相同，且時間戳已凍在同一秒",
      len(fb1.spawned) == 2
      and fb1.spawned[0][fb1.spawned[0].index("-p") + 1]
      == fb1.spawned[1][fb1.spawned[1].index("-p") + 1] == "dfmgr"
      and _m.time.strftime("%Y%m%d-%H%M%S") == "FIXED",
      f"rc={rcb1} spawned={len(fb1.spawned)} err={errb1[:200]!r}")

# 兩棒的 log 路徑：首棒那個由喚醒 prompt 指出（下方以檔案內容驗指對了人）；
# 「同一程序內必不同」則在同一個模組實例上續呼 _log_path 直接驗——序號是模組級狀態。
_p1 = _m._log_path("287", "dfmgr")
_p2 = _m._log_path("287", "dfmgr")
_p3 = _m._log_path("287", "dfmgr")
check("BLOCK 1 同一程序內任兩次 _log_path（同 issue／同 profile／同秒）必不同",
      len({_p1, _p2, _p3}) == 3,
      f"{_p1.name} / {_p2.name} / {_p3.name}")
check("BLOCK 1 檔名仍含 issue 與 profile（AC-2 的可讀性不因去碰撞而失去）",
      all("287" in p.name and "dfmgr" in p.name and p.name.endswith(".log")
          for p in (_p1, _p2, _p3)),
      f"{_p1.name}")
check("BLOCK 1 檔名含 pid（並行的多個 relay 互不碰撞）",
      all(f"-{os.getpid()}-" in p.name for p in (_p1, _p2, _p3)), f"{_p1.name}")
check("BLOCK 1 仍落在 $TMPDIR 下，不寫進 repo",
      all(_under(tempfile.gettempdir(), p) and not _under(REPO, p)
          for p in (_p1, _p2, _p3)),
      f"{_p1} tmp={tempfile.gettempdir()} repo={REPO} "
      f"（判定為路徑階層，見 `_under`）")

wake_b1 = prompt_of(fb1.spawned[1]) if len(fb1.spawned) == 2 else ""
_lp_b1 = re.findall(r"`(/[^`]+\.log)`", wake_b1)
check("BLOCK 1 喚醒 prompt 仍指出一個 log 絕對路徑", len(_lp_b1) == 1, f"命中={_lp_b1}")
if _lp_b1:
    _first_log = Path(_lp_b1[0])
    _body = _first_log.read_text() if _first_log.exists() else ""
    check("BLOCK 1 prompt 指向的檔案含**首棒**事件（FIRST_CHILD）",
          "FIRST_CHILD" in _body, f"log={_first_log} body={_body[:160]!r}")
    check("BLOCK 1 prompt 指向的檔案**不含**喚醒棒事件（WAKE_CHILD）＝ 未被覆寫",
          "WAKE_CHILD" not in _body, f"log={_first_log} body={_body[:160]!r}")
    # 喚醒棒的 log 另成一檔：同目錄下應找得到含 WAKE_CHILD 的另一個檔，且不是首棒那個。
    _sibs = [p for p in TESTTMP.glob("relay-287-dfmgr-FIXED-*.log")
             if p != _first_log and "WAKE_CHILD" in p.read_text()]
    check("BLOCK 1 喚醒棒的 log 是另一個檔（兩棒的現場都保住了）",
          len(_sibs) >= 1, f"首棒={_first_log.name} 其餘含 WAKE_CHILD 的={[p.name for p in _sibs]}")


# ── AC-3：--issue 而無 --then-wake 即拒絕 ───────────────────────────────────
print("\n── AC-3：三列（拒絕／正常鏈結／兩者皆無）")

f3a = FakeSub(LINES)
rc3a, _, err3a = run(["4149", "hi", "--issue", "287"], f3a)
check("AC-3 列1 `--issue 287` 無 --then-wake → rc 非 0", rc3a not in (0, None), f"rc={rc3a}")
check("AC-3 列1 → len(spawned) == 0（拒絕必須在 Popen 之前，否則 coder 已經跑起來才報錯）",
      len(f3a.spawned) == 0, f"spawned={f3a.spawned}")
check("AC-3 列1 → stderr 含 `--then-wake` 字面", "--then-wake" in err3a, repr(err3a[:300]))
check("AC-3 列1 → stderr 給可照抄的正確形式（含腳本名、--issue 與 --then-wake 的完整例）",
      "devflow_relay.py" in err3a and "--issue" in err3a and "--then-wake" in err3a
      and "287" in err3a, repr(err3a[:400]))
check("AC-3 列1 → 連一則 Telegram 訊息都沒送（拒絕是純本機的）",
      len(f3a.sent) == 0, f"sent={f3a.sent}")

f3b = FakeSub(LINES)
rc3b, _, err3b = run(["4149", "hi", "--issue", "287", "--then-wake", "dfmgr"], f3b)
check("AC-3 列2 `--issue 287 --then-wake dfmgr` → 正常，len(spawned) == 2",
      rc3b == 0 and len(f3b.spawned) == 2, f"rc={rc3b} spawned={len(f3b.spawned)} err={err3b[:200]!r}")

f3c = FakeSub(LINES)
rc3c, _, err3c = run(["4149", "hi"], f3c)
check("AC-3 列3 兩者皆無 → 正常，len(spawned) == 1",
      rc3c == 0 and len(f3c.spawned) == 1,
      f"rc={rc3c} spawned={len(f3c.spawned)} err={err3c[:200]!r}")
check("AC-3 列3 不可省：無條件要求 --then-wake 的錯誤實作會讓既有一次性派工全部失效",
      len(f3c.spawned) == 1 and "--then-wake" not in err3c, repr(err3c[:200]))
# 第三列的另一形：不帶 --issue 但帶 --then-wake 也該能跑（一次性操作想鏈結不被禁止）。
f3d = FakeSub(LINES)
rc3d, _, _ = run(["4149", "hi", "--then-wake", "dfmgr"], f3d)
check("AC-3 無 --issue 而帶 --then-wake → 正常鏈結（len(spawned) == 2）",
      rc3d == 0 and len(f3d.spawned) == 2, f"rc={rc3d} spawned={len(f3d.spawned)}")


# ── AC-4：鏈結深度 ──────────────────────────────────────────────────────────
print("\n── AC-4：深度經 env 傳遞、上限 MAX_RELAY_DEPTH")

DEPTH_KEY = "DEVFLOW_RELAY_DEPTH"
CHAIN_KEY = "DEVFLOW_RELAY_CHAIN"


def with_env(pairs: dict[str, str | None], fn):
    """暫時改 os.environ 跑一段，結束必還原（測完不留痕）。"""
    saved = {k: os.environ.get(k) for k in pairs}
    try:
        for k, v in pairs.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return fn()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


mod_consts = load(FakeSub(LINES))
check("AC-4 上限寫成模組常數 `MAX_RELAY_DEPTH = 3`（不散落）",
      getattr(mod_consts, "MAX_RELAY_DEPTH", None) == 3,
      f"MAX_RELAY_DEPTH={getattr(mod_consts, 'MAX_RELAY_DEPTH', None)!r}")
check("AC-4 數字 3 只在常數定義處出現一次（散落的話下一個改上限的人會漏改）",
      len(re.findall(r"^MAX_RELAY_DEPTH\s*=\s*3$", RELAY_SRC, re.M)) == 1
      and "MAX_RELAY_DEPTH" in RELAY_SRC,
      f"命中={re.findall(r'^MAX_RELAY_DEPTH.*$', RELAY_SRC, re.M)}")

# 第 1 層：relay 自身未設深度（＝0），子程序拿到 "1"。
f4 = FakeSub(LINES)
rc4, _, err4 = with_env({DEPTH_KEY: None, CHAIN_KEY: None},
                        lambda: run(["4149", "hi", "--issue", "287", "--then-wake", "dfmgr"], f4))
check("AC-4 第 1 層：kwargs[0]['env'][DEVFLOW_RELAY_DEPTH] == '1'",
      bool(f4.kwargs) and f4.kwargs[0].get("env", {}).get(DEPTH_KEY) == "1",
      f"kwargs[0] keys={sorted(f4.kwargs[0]) if f4.kwargs else None} "
      f"depth={f4.kwargs[0].get('env', {}).get(DEPTH_KEY) if f4.kwargs else None!r}")
check("AC-4 env 是 os.environ 的複本＋覆寫，不是只給一個鍵（否則子程序沒 PATH，hermes 找不到）",
      bool(f4.kwargs) and len(f4.kwargs[0].get("env", {})) > 1
      and set(os.environ) - {DEPTH_KEY, CHAIN_KEY} <= set(f4.kwargs[0].get("env", {})),
      f"env 鍵數={len(f4.kwargs[0].get('env', {})) if f4.kwargs else 0}，"
      f"缺={sorted(set(os.environ) - set(f4.kwargs[0].get('env', {})))[:5] if f4.kwargs else None}")
check("AC-4／#312 AC-6(b) then-wake 喚醒者承襲呼叫者自身的深度（relay 自身未設 ＝ 0 → 喚醒者 '0'）",
      len(f4.kwargs) == 2 and f4.kwargs[1].get("env", {}).get(DEPTH_KEY) == "0",
      f"kwargs[1] depth={f4.kwargs[1].get('env', {}).get(DEPTH_KEY) if len(f4.kwargs) > 1 else None!r}")
# `#312` `AC-6(b)`：本條的期望值與標題由 `#312` 授權更新。base `1aced94` 寫的是
# 「同樣拿 depth+1」且期望 `"1"`——**那斷言的是缺陷本身**（`--then-wake` 的喚醒者是同一
# 流程的續接，拿 `caller+1` 會讓同一張單每輪 +1，第 3 輪撞上限，`#310` 現場），而同一句
# 的後半「不隨輪次累加」是當時的宣稱，兩者不能同時成立。斷言的**意圖**（喚醒者的深度要被驗）
# 仍成立，故改期望值與標題，不刪、不繞過。
check("AC-4 測完環境已還原（本程序不該留下 DEVFLOW_RELAY_DEPTH）",
      DEPTH_KEY not in os.environ, f"{DEPTH_KEY}={os.environ.get(DEPTH_KEY)!r}")

# 鑑別力：relay 自身在第 1 層時，子程序拿 "2"（寫死 "1" 的實作在這裡掛）。
f4b = FakeSub(LINES)
with_env({DEPTH_KEY: "1", CHAIN_KEY: "dfcoord"},
         lambda: run(["4149", "hi", "--issue", "287", "--then-wake", "dfmgr"], f4b))
check("AC-4 鑑別力：relay 自身 depth=1 → 子程序拿 '2'（相對遞增，非寫死）",
      bool(f4b.kwargs) and f4b.kwargs[0].get("env", {}).get(DEPTH_KEY) == "2",
      f"depth={f4b.kwargs[0].get('env', {}).get(DEPTH_KEY) if f4b.kwargs else None!r}")
check("AC-4 鏈（DEVFLOW_RELAY_CHAIN）累加 profile，供超限時印出",
      bool(f4b.kwargs) and f4b.kwargs[0].get("env", {}).get(CHAIN_KEY) == "dfcoord,dfmgr",
      f"chain={f4b.kwargs[0].get('env', {}).get(CHAIN_KEY) if f4b.kwargs else None!r}")
# 同一組的喚醒者側（`#312` `AC-6(b)` 授權更新的對應值）：relay 自身 `depth=1` 時
# primary 得 `"2"`（上面兩條，一字不改）、喚醒者得 `"1"`，鏈以 `>` 接呼叫者自己的鏈。
check("AC-4／#312 AC-6(b) 鑑別力：relay 自身 depth=1 → 喚醒者拿 '1'（＝呼叫者自身那一層）",
      len(f4b.kwargs) == 2 and f4b.kwargs[1].get("env", {}).get(DEPTH_KEY) == "1",
      f"depth={f4b.kwargs[1].get('env', {}).get(DEPTH_KEY) if len(f4b.kwargs) > 1 else None!r}")
check("AC-4／#312 AC-6(b) 鑑別力：喚醒者的鏈為 `dfcoord>dfmgr`（續接以 `>` 接，與 primary 的 `,` 分得開）",
      len(f4b.kwargs) == 2 and f4b.kwargs[1].get("env", {}).get(CHAIN_KEY) == "dfcoord>dfmgr",
      f"chain={f4b.kwargs[1].get('env', {}).get(CHAIN_KEY) if len(f4b.kwargs) > 1 else None!r}")

# 邊界：depth=2 仍放行（2 < 3）；depth=3 拒絕。
f4c = FakeSub(LINES)
rc4c, _, _ = with_env({DEPTH_KEY: "2", CHAIN_KEY: "dfcoord,dfmgr"},
                      lambda: run(["4149", "hi", "--issue", "287", "--then-wake", "dfmgr"], f4c))
check("AC-4 邊界：depth=2 仍放行（真實流程 coord→mgr→coder 最深 2，不得擋掉）",
      rc4c == 0 and len(f4c.spawned) == 2, f"rc={rc4c} spawned={len(f4c.spawned)}")

f4d = FakeSub(LINES)
rc4d, _, err4d = with_env({DEPTH_KEY: "3", CHAIN_KEY: "dfcoord,dfmgr,dfimpl"},
                          lambda: run(["4149", "hi", "--issue", "287", "--then-wake", "dfmgr"], f4d))
check("AC-4 已在第 3 層 → rc 非 0", rc4d not in (0, None), f"rc={rc4d}")
check("AC-4 已在第 3 層 → len(spawned) == 0（拒絕在 Popen 之前）",
      len(f4d.spawned) == 0, f"spawned={f4d.spawned}")
check("AC-4 已在第 3 層 → 訊息印出 `DEVFLOW_RELAY_DEPTH=3` 與 `MAX_RELAY_DEPTH=3`",
      f"{DEPTH_KEY}=3" in err4d and "MAX_RELAY_DEPTH=3" in err4d, repr(err4d[:400]))
check("AC-4 已在第 3 層 → 訊息印出鏈（各層 profile 看得出是誰疊誰）",
      "dfcoord,dfmgr,dfimpl" in err4d and "dfmgr" in err4d, repr(err4d[:400]))
check("AC-4 深度拒絕不分有無 --issue（巢狀過深本身就該停）",
      with_env({DEPTH_KEY: "3"}, lambda: run(["4149", "hi"], FakeSub(LINES))[0]) not in (0, None),
      "不帶 --issue 時 depth=3 也該拒絕")
check("AC-4 外部塞非數字不讓轉播掛掉（當最外層處理）",
      with_env({DEPTH_KEY: "abc"}, lambda: run(["4149", "hi"], FakeSub(LINES))[0]) == 0,
      "DEVFLOW_RELAY_DEPTH=abc 應被當作 0")


# ── AC-5／AC-6／AC-7：本測試檔自身的機械判準 ───────────────────────────────
print("\n── AC-5／AC-6／AC-7：本測試檔自身的機械判準")

check("AC-5 本檔顯式覆寫 `OPENING_DELAY`（字面命中）",
      len(re.findall(r"\bOPENING_DELAY\b", SELF_SRC)) >= 1
      and re.search(r"\.OPENING_DELAY\s*=", SELF_SRC) is not None,
      "需有 `mod.OPENING_DELAY = …` 的賦值")
check("AC-5 本檔顯式覆寫 `HEARTBEAT_AFTER`（字面命中）",
      len(re.findall(r"\bHEARTBEAT_AFTER\b", SELF_SRC)) >= 1
      and re.search(r"\.HEARTBEAT_AFTER\s*=", SELF_SRC) is not None,
      "需有 `mod.HEARTBEAT_AFTER = …` 的賦值")
check("AC-5 受測模組確實有這兩個常數可覆寫（名字改了要在這裡發現）",
      hasattr(mod_consts, "OPENING_DELAY") and hasattr(mod_consts, "HEARTBEAT_AFTER"),
      f"OPENING_DELAY={getattr(mod_consts, 'OPENING_DELAY', None)!r} "
      f"HEARTBEAT_AFTER={getattr(mod_consts, 'HEARTBEAT_AFTER', None)!r}")
check("AC-5 覆寫後的值確實生效（不依賴 wall-clock）",
      mod_consts.OPENING_DELAY == 10 ** 9 and mod_consts.HEARTBEAT_AFTER == 10 ** 9,
      f"{mod_consts.OPENING_DELAY} / {mod_consts.HEARTBEAT_AFTER}")

check("AC-6 本檔零 import-path 操作（機械判準：`sys` 加 `.path` 無命中）",
      re.search(r"sys\." + "path", SELF_SRC) is None,
      "本檔不得出現該字面")
check("AC-6 受測模組以 importlib.util.spec_from_file_location 載入",
      "importlib.util.spec_from_file_location" in SELF_SRC
      and "spec_from_file_location" in SELF_SRC, "")
check("AC-6 載入目錄是 repo 真實目錄（相對本檔用 pathlib 算，無絕對路徑字面）",
      SCRIPTS.is_dir() and (SCRIPTS / "_marker.py").exists()
      and RELAY_SRC_PATH.exists()
      # 判準本身不能含自己要找的字面（否則永遠自我命中），故拆開再組。
      and re.search('"' + "/" + 'home' + "/", SELF_SRC) is None
      and 'parents[1]' in SELF_SRC,
      f"SCRIPTS={SCRIPTS}")
check("AC-6 本檔零真子程序：連 subprocess 都沒 import",
      re.search(r"^import subprocess$", SELF_SRC, re.M) is None
      and re.search(r"^from subprocess", SELF_SRC, re.M) is None, "")
check("AC-6 本檔零真呼叫：無 `subprocess` 的 run／Popen 實呼叫",
      re.search(r"subprocess\.(run|Popen)\(", SELF_SRC) is None, "")
check("AC-6 縫仍只有一處：relay 的對外效果全部經模組全域的 subprocess",
      not re.search(r"^import (requests|urllib|http|socket)", RELAY_SRC, re.M)
      and "os.system" not in RELAY_SRC
      and len(re.findall(r"subprocess\.Popen\(", RELAY_SRC)) == 1
      and len(re.findall(r"subprocess\.run\(", RELAY_SRC)) == 1,
      f"Popen={len(re.findall(r'subprocess.Popen', RELAY_SRC))} "
      f"run={len(re.findall(r'subprocess.run', RELAY_SRC))}")

check("AC-7 假 subprocess 類同時定義 PIPE／DEVNULL／STDOUT",
      all(hasattr(FakeSub, k) for k in ("PIPE", "DEVNULL", "STDOUT")),
      f"缺={[k for k in ('PIPE', 'DEVNULL', 'STDOUT') if not hasattr(FakeSub, k)]}")
_probe = _only_pipe_probe()
check("AC-7 鑑別力：只定義 PIPE 的假類會在 Popen 的 kwargs 求值時掛 AttributeError",
      _probe[0] == "AttributeError" and "DEVNULL" in _probe[1],
      f"probe={_probe}")


# ── AC-12：SKILL.md 的派審指令補 --then-wake ────────────────────────────────
print("\n── AC-12：SKILL.md 的派審指令補 --then-wake（指令 ∧ 說明，合取）")

SKILL_MD = REPO / "devflow" / "orchestrators" / "hermes" / "SKILL.md"
SKILL = SKILL_MD.read_text()

# 定位 `launch: agent` 的 block 與它下方的說明清單。判準刻意不是整檔 grep：
# `--then-wake` 出現在檔案別處也會讓整檔 grep 通過，而讀者照抄的是這一個 block。
_agent_sec = SKILL.split("#### launch: agent", 1)
AGENT_SEC = _agent_sec[1].split("\n#### ", 1)[0] if len(_agent_sec) > 1 else ""
_fences = re.findall(r"```bash\n(.*?)```", AGENT_SEC, re.S)
RELAY_BLOCK = next((b for b in _fences if "devflow_relay.py" in b), "")
# 說明清單 ＝ 該 block 收尾到本小節結束之間的 `- ` 項
_after = AGENT_SEC.split("```", 2)[-1] if "```" in AGENT_SEC else ""
BULLETS = [ln for ln in _after.splitlines() if ln.startswith("- ")]

check("AC-12 `launch: agent` 小節內找得到含 devflow_relay.py 的 bash block",
      bool(RELAY_BLOCK) and "-p <instance>" in RELAY_BLOCK and "--issue" in RELAY_BLOCK,
      f"block={RELAY_BLOCK[:200]!r}")
check("AC-12 第一項：該 block 的派審指令含 `--then-wake`",
      "--then-wake" in RELAY_BLOCK, f"block={RELAY_BLOCK[:300]!r}")
_wake_val = re.search(r"--then-wake\s+<([^>]+)>", RELAY_BLOCK)
check("AC-12 第一項：`--then-wake` 的值不是 `<instance>`（那是審查位）",
      _wake_val is not None and _wake_val.group(1).strip() != "instance",
      f"值={_wake_val.group(1) if _wake_val else None!r}")

_wake_bullets = [b for b in BULLETS if "--then-wake" in b]
check("AC-12 第二項：該 block 下方的說明清單有一條講 `--then-wake`（block 鄰近，非整檔 grep）",
      len(_wake_bullets) >= 1, f"清單共 {len(BULLETS)} 條，含 --then-wake 的 {len(_wake_bullets)} 條")
check("AC-12 第二項：該條含「派工者自己」字樣（否則下一個照抄的人會填審查位的 instance）",
      any("派工者自己" in b for b in _wake_bullets),
      f"bullets={[b[:120] for b in _wake_bullets]}")
check("AC-12 第二項：該條載明「不可省」與拒絕的後果",
      any("不可省" in b and ("拒絕" in b or "AC-3" in b) for b in _wake_bullets),
      f"bullets={[b[:160] for b in _wake_bullets]}")
check("AC-12 合取：只補指令不補說明 ＝ FAIL（兩項皆須成立）",
      "--then-wake" in RELAY_BLOCK and any("派工者自己" in b for b in _wake_bullets),
      "指令與說明須同時命中")

# ── AC-12 的鑑別力：把 SKILL.md 自己那行的參數形狀餵進 relay 實跑 ──
# T v2 載 base（bdc4cc4）實測「SKILL.md:131 同形指令 → rc=2 spawned=0」。
# 這裡不另寫一份指令，直接從該 block 解析——文件與行為因此綁在一起，
# 改壞任一邊都會在這裡掛（只改測試不改文件、或只改文件把值填錯皆然）。
def _skill_argv(block: str, prompt_file: Path) -> list[str]:
    """從 block 解析 relay 的參數列，占位符代入可跑的值。"""
    line = ""
    taking = False
    for raw in block.splitlines():
        if "devflow_relay.py" in raw:
            taking = True
            line = raw.split("devflow_relay.py", 1)[1]
            if not raw.rstrip().endswith("\\"):
                break
            continue
        if taking:
            line += " " + raw
            if not raw.rstrip().endswith("\\"):
                break
    line = line.replace("\\", " ")
    line = re.sub(r"\[[^\]]*\]", " ", line)          # `[-m <model> …]` 是選配，拿掉

    def sub(m: re.Match) -> str:
        inner = m.group(1)
        if "thread" in inner:
            return "4149"
        if "派工者自己" in inner:
            return "dfmgr"
        if inner.strip() == "instance":
            return "dfrev"
        if inner.strip() == "N":
            return "287"
        return "x"

    line = re.sub(r"<([^>]+)>", sub, line)
    toks = [t for t in line.split() if t]
    return [str(prompt_file) if "prompt.md" in t else t for t in toks]


_pf = Path(tempfile.gettempdir()) / "ac12-prompt.md"
_pf.write_text("審查稿（AC-12 的測試用）")
SKILL_ARGV = _skill_argv(RELAY_BLOCK, _pf)
check("AC-12 解析出的參數列形狀正確（thread ＋ --file ＋ -p ＋ --issue ＋ --fresh ＋ --pace）",
      SKILL_ARGV[:1] == ["4149"]
      and all(k in SKILL_ARGV for k in ("--file", "-p", "--issue", "--fresh", "--pace")),
      f"argv={SKILL_ARGV}")

f12 = FakeSub(LINES)
rc12, _, err12 = run(SKILL_ARGV, f12)
check("AC-12 鑑別力：SKILL.md 那行的同形指令現在被接受（rc=0、len(spawned)==2）",
      rc12 == 0 and len(f12.spawned) == 2,
      f"rc={rc12} spawned={len(f12.spawned)} err={err12[:300]!r}")
check("AC-12 鑑別力：喚醒的是派工者（dfmgr），不是審查位（dfrev）",
      len(f12.spawned) == 2
      and f12.spawned[0][f12.spawned[0].index("-p") + 1] == "dfrev"
      and f12.spawned[1][f12.spawned[1].index("-p") + 1] == "dfmgr",
      f"spawned profiles={[c[c.index('-p') + 1] for c in f12.spawned]}")
check("AC-12 鑑別力：--fresh 仍生效（審查位不續接，R1 要每輪 fresh）",
      bool(f12.spawned) and "-c" not in f12.spawned[0], f"spawned[0]={f12.spawned[0] if f12.spawned else None}")

# 反例組：拿掉 `--then-wake <值>` 兩個 token，重現 T v2 所載的 base 實測。
_pre = [t for i, t in enumerate(SKILL_ARGV)
        if t != "--then-wake" and (i == 0 or SKILL_ARGV[i - 1] != "--then-wake")]
f12b = FakeSub(LINES)
rc12b, _, err12b = run(_pre, f12b)
check("AC-12 反例組：同一行拿掉 --then-wake → rc 非 0、len(spawned)==0（重現 T v2 的 base 實測）",
      rc12b not in (0, None) and len(f12b.spawned) == 0,
      f"rc={rc12b} spawned={len(f12b.spawned)} err={err12b[:200]!r}")
_pf.unlink(missing_ok=True)


# ── AC-8／AC-9／AC-11：文件與版本 ───────────────────────────────────────────
print("\n── AC-8／AC-9／AC-11：文件與版本")

MGR = MANAGER_MD.read_text()
check("AC-8 manager.md 含 `--then-wake` 字面", "--then-wake" in MGR, "")
blocks = [b for b in re.split(r"\n\s*\n", MGR) if "--then-wake" in b and "--issue" in b]
check("AC-8 `--then-wake` 與 `--issue` 同段",
      len(blocks) >= 1, f"含兩者的段數={len(blocks)}")
check("AC-8 該段載明「帶 --issue 時必須同時帶 --then-wake」的義務",
      any("必" in b for b in blocks), f"blocks={[b[:160] for b in blocks]}")

TG = TELEGRAM_MD.read_text()
check("AC-9 telegram.md 含 `--then-wake` 字面", "--then-wake" in TG, "")
check("AC-9 telegram.md 含 `DEVFLOW_RELAY_DEPTH` 字面", "DEVFLOW_RELAY_DEPTH" in TG, "")

raw = VERSION_FILE.read_text().strip()
check("AC-11 VERSION 合 V1 四碼形狀",
      re.fullmatch(r"\d+\.\d+\.\d+\.\d+", raw) is not None, f"raw={raw!r}")
if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", raw):
    cur = tuple(int(x) for x in raw.split("."))
    # 整數元組比較，非字串——字串下 "0.15.10.0" < "0.15.4.0" 為 True（#287 AC-8 的作法）。
    check("AC-11 VERSION 嚴格大於 0.15.5.0（整數元組比較）",
          cur > (0, 15, 5, 0), f"cur={cur}")
    # `#300` `AC-11`：下界由 `0.15.6.0`（`#298` 的值）改成嚴格大於它。沿用整數元組比較，
    # 不改成 `== 0.15.7.0`——下一張單進位後這條會再度變成「鎖死在舊值」的假 FAIL。
    check("#300 AC-11 VERSION 嚴格大於 0.15.6.0（c 位進位：修正既有能力的缺陷）",
          cur > (0, 15, 6, 0), f"cur={cur}")


# ════════════════════════════════════════════════════════════════════════════
# `#300`／K4c-8：第二棒的 handoff 行
# ════════════════════════════════════════════════════════════════════════════

# ── #300 AC-1：寫入的存在、位置與時機 ───────────────────────────────────────
print("\n── #300 AC-1：發出第二棒之後寫 handoff 行（存在、cmd 形狀、時機）")

# 現行（base `cc94a30`）實測值，兩個數字刻意分開寫：
#   **gh 呼叫數 0**（`run` 的 cmd 中 `cmd[0] == "gh"` 的個數）
#   **`gh` 文字出現處 1**（`:412` 的 prompt 字串 `gh issue view {issue} --comments`，
#   那是交給被喚醒者去讀 forge 的指令**文字**，不是本程序的呼叫）
# 只寫「0」會讓 grep 到那一處文字的人以為撰 T 者漏看（裁決位 2026-10-07 指出）。
h1 = FakeSub(LINES)
rch1, _, errh1 = run(["4149", "hi", "--issue", "287", "--then-wake", "dfmgr"], h1)
check("#300 AC-1 `--issue 287 --then-wake dfmgr` → gh 呼叫數 ≥1（現行 0）",
      len(h1.gh_calls) >= 1,
      f"rc={rch1} gh 呼叫={len(h1.gh_calls)} sent 的 argv0={[c[0] for c in h1.sent]}")
check("#300 AC-1 gh 呼叫恰 1 個（一棒一則，不重複留言）",
      len(h1.gh_calls) == 1, f"gh 呼叫={len(h1.gh_calls)}：{h1.gh_calls}")
check("#300 AC-1 cmd 為 `gh issue comment <N>` 系列，單號取自 --issue",
      bool(h1.gh_calls) and h1.gh_calls[0][:3] == ["gh", "issue", "comment"]
      and "287" in h1.gh_calls[0],
      f"cmd={h1.gh_calls[0] if h1.gh_calls else None}")
check("#300 AC-1 不帶 `-R`（repo 依 cwd 的 git remote 判，relay 不持有 repo 名）",
      bool(h1.gh_calls) and "-R" not in h1.gh_calls[0] and "--repo" not in h1.gh_calls[0],
      f"cmd={h1.gh_calls[0] if h1.gh_calls else None}")
check("#300 AC-1 既有的送訊沒有被 gh 呼叫擠掉（hermes send 仍 ≥1）",
      len(h1.send_calls) >= 1,
      f"send={len(h1.send_calls)} gh={len(h1.gh_calls)}")

# 文字處數與呼叫數分開：受測源碼裡 `gh` 字面的出現處。
_gh_text = re.findall(r"gh issue \w+", RELAY_SRC)
check("#300 AC-1 受測源碼的 `gh issue …` 文字處數 ≥2（原 prompt 那 1 處 ＋ 本單的呼叫）",
      len(_gh_text) >= 2, f"命中={_gh_text}")
check("#300 AC-1 那 1 處 prompt 文字（`gh issue view … --comments`）仍在，未被改掉",
      "gh issue view" in RELAY_SRC and "gh issue view" in prompt_of(h1.spawned[1]),
      f"源碼命中={'gh issue view' in RELAY_SRC}")

# 不帶 --then-wake（也就無 --issue）→ gh 呼叫 0。一次性操作不寫 forge。
h2 = FakeSub(LINES)
rch2, _, _ = run(["4149", "hi"], h2)
check("#300 AC-1 不帶 --then-wake（無 --issue）→ gh 呼叫 0（一次性操作不寫 forge）",
      rch2 == 0 and len(h2.gh_calls) == 0,
      f"rc={rch2} gh 呼叫={len(h2.gh_calls)}：{h2.gh_calls}")
check("#300 AC-1 該列仍照舊送訊（不寫 forge ≠ 不轉播）",
      len(h2.send_calls) >= 1, f"send={len(h2.send_calls)}")

# 帶 --then-wake 但**無** --issue：鏈結照跑，但沒有單可留言 → gh 呼叫 0。
h2b = FakeSub(LINES)
rch2b, _, _ = run(["4149", "hi", "--then-wake", "dfmgr"], h2b)
check("#300 AC-1 `--then-wake` 而無 `--issue` → 仍鏈結（spawned==2）但 gh 呼叫 0",
      rch2b == 0 and len(h2b.spawned) == 2 and len(h2b.gh_calls) == 0,
      f"rc={rch2b} spawned={len(h2b.spawned)} gh={len(h2b.gh_calls)}")

# 拒絕列（`#298` `AC-3`）：連子程序都不派，自然也不該寫 forge。
h2c = FakeSub(LINES)
rch2c, _, _ = run(["4149", "hi", "--issue", "287"], h2c)
check("#300 AC-1 拒絕列（`--issue` 無 `--then-wake`）→ gh 呼叫 0（拒絕是純本機的）",
      rch2c not in (0, None) and len(h2c.gh_calls) == 0 and len(h2c.spawned) == 0,
      f"rc={rch2c} gh={len(h2c.gh_calls)} spawned={len(h2c.spawned)}")

# ── 時機（T 明列否決「等第二棒結束再寫」）──
# 時間軸 `events` 依序記 popen／run:<argv0>／wait，三者共用同一條 list，
# 所以「gh 的 run 落在第二棒 popen 之後、該子程序 wait 之前」是純順序事實，不靠時鐘。
_ev = h1.events
_popens = [i for i, e in enumerate(_ev) if e == "popen"]
_ghs = [i for i, e in enumerate(_ev) if e == "run:gh"]
_waits = [i for i, e in enumerate(_ev) if e == "wait"]
check("#300 AC-1 時機前置：時間軸有兩次 popen、兩次 wait、一次 run:gh",
      len(_popens) == 2 and len(_waits) == 2 and len(_ghs) == 1,
      f"events={_ev}")
check("#300 AC-1 時機：gh 的 run 發生在**第二棒 Popen 之後**",
      bool(_ghs) and len(_popens) == 2 and _ghs[0] > _popens[1],
      f"gh@{_ghs} 第二棒 popen@{_popens[1:] } events={_ev}")
check("#300 AC-1 時機：gh 的 run 發生在**第二棒 wait() 之前**（不等第二棒結束才寫）",
      bool(_ghs) and len(_waits) == 2 and _ghs[0] < _waits[1],
      f"gh@{_ghs} waits@{_waits} events={_ev}")
check("#300 AC-1 時機鑑別力：第二棒的 FakeProc 在 gh 呼叫時 waits 仍為 0 之後才變 1",
      len(h1.procs) == 2 and h1.procs[1].waits == 1
      and _ghs[0] < _waits[1],
      f"procs waits={[p.waits for p in h1.procs]} events={_ev}")
check("#300 AC-1 時機：寫 forge 不耽誤第一棒——gh 的 run 在第一棒 wait() 之後",
      bool(_ghs) and bool(_waits) and _ghs[0] > _waits[0],
      f"gh@{_ghs} 第一棒 wait@{_waits[:1]} events={_ev}")
# `after_spawn` 鉤子是上面那個時機的實作手段：掛在 Popen 之後、讀 stdout 之前。
# 源碼位置以字面定位，刻意把 `Popen(` 拆成兩段再組——本檔自己的 `AC-6` 判準禁止
# 「`subprocess` 加點加 run／Popen 加左括號」的字面出現，寫全會自我命中。
_POPEN_CALL = "subprocess." + "Popen" + "("
check("#300 AC-1 `_run_child` 有 `after_spawn` 鉤子，且在 Popen 之後、proc.wait() 之前呼叫",
      "after_spawn" in RELAY_SRC
      and RELAY_SRC.index("after_spawn()") > RELAY_SRC.index(_POPEN_CALL)
      and RELAY_SRC.index("after_spawn()") < RELAY_SRC.index("proc.wait()"),
      "源碼順序：Popen → after_spawn() → proc.wait()")


# ── #300 AC-4：handoff 行的欄位與字面 ───────────────────────────────────────
print("\n── #300 AC-4：三個欄位、獨立一行、與既有兩式互不相干")

_mod = LAST_MOD[-1]
_body = h1.gh_calls[0][h1.gh_calls[0].index("--body") + 1] if h1.gh_calls else ""
_hand = [ln for ln in _body.splitlines()
         if re.fullmatch(_mod.HANDOFF_RE[1:-1], ln)]
check("#300 AC-4 --body 內恰一行合 grammar 的 handoff 行",
      len(_hand) == 1, f"命中={_hand} body={_body!r}")
check("#300 AC-4 該行是**獨立一行**（`^…$`，前後無其他字）",
      len(_hand) == 1 and _hand[0] in _body.splitlines()
      and re.search(_mod.HANDOFF_RE, _body, re.M) is not None,
      f"body={_body!r}")
check("#300 AC-4 留言另有一行人讀說明（不是只丟一行標記給人看）",
      len([ln for ln in _body.splitlines() if ln.strip() and ln not in _hand]) >= 1,
      f"body={_body!r}")
if _hand:
    _line = _hand[0]
    check("#300 AC-4 欄位一：第二棒的 profile（取自 --then-wake）",
          "profile=dfmgr" in _line, _line)
    check("#300 AC-4 欄位二：啟動時刻（relay 自己的時鐘，ISO 8601 ＋ ±HHMM 偏移）",
          re.search(r"at=[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}[+\-][0-9]{4}",
                    _line) is not None, _line)
    check("#300 AC-4 欄位三：受託子程序的 rc（本例 0）",
          "rc=0" in _line, _line)
    check("#300 AC-4 同族字面：獨立一行的 HTML 註解 `<!-- devflow:… -->`",
          _line.startswith("<!-- devflow:") and _line.endswith(" -->"), _line)

# 鑑別力：三個欄位都必須跟著輸入變，寫死任一個都會在這裡掛。
h4 = FakeSub(LINES, rc=7)
run(["4149", "hi", "-p", "dfimpl", "--issue", "999", "--then-wake", "dfcoord"], h4)
_body4 = h4.gh_calls[0][h4.gh_calls[0].index("--body") + 1] if h4.gh_calls else ""
_line4 = next((ln for ln in _body4.splitlines()
               if ln.startswith("<!-- devflow:handoff")), "")
check("#300 AC-4 鑑別力：`--then-wake dfcoord` → `profile=dfcoord`（非寫死 dfmgr）",
      "profile=dfcoord" in _line4 and "dfmgr" not in _line4, f"line={_line4!r}")
check("#300 AC-4 鑑別力：受託子程序 rc=7 → `rc=7`（非寫死 0）",
      "rc=7" in _line4, f"line={_line4!r}")
check("#300 AC-4 鑑別力：單號取自 --issue（999），不是寫死 287",
      bool(h4.gh_calls) and "999" in h4.gh_calls[0] and "287" not in h4.gh_calls[0],
      f"cmd={h4.gh_calls[0] if h4.gh_calls else None}")
check("#300 AC-4 handoff 行的 rc 是**受託子程序**的，與 relay 的回傳一致",
      "rc=7" in _line4, f"line={_line4!r}")

# 與既有兩種標記的關係：不相等、互不為子字串——故 `CH3` 的三態判定不受影響。
_marker_mod = sys.modules["_marker"]
_pairs = {"TOPIC_RE": _marker_mod.TOPIC_RE, "ARCHIVED_RE": _marker_mod.ARCHIVED_RE}
for _name, _pat in _pairs.items():
    check(f"#300 AC-4 HANDOFF_RE 與 {_name} 不相等",
          _mod.HANDOFF_RE != _pat, f"{_mod.HANDOFF_RE!r} vs {_pat!r}")
    check(f"#300 AC-4 HANDOFF_RE 與 {_name} 互不為子字串",
          _mod.HANDOFF_RE not in _pat and _pat not in _mod.HANDOFF_RE,
          f"{_mod.HANDOFF_RE!r} vs {_pat!r}")
# 行為層的同一件事：真的 handoff 行放進 body，`T`／`A` 兩式的計數不變。
_fixture = ("<!-- devflow:topic thread=4394 -->\n"
            + (_hand[0] if _hand else "") + "\n")
check("#300 AC-4 handoff 行不使 T 變動（判定式錨定自己的完整字面）",
      len(_marker_mod.TOPIC.findall(_fixture)) == 1, f"fixture={_fixture!r}")
check("#300 AC-4 handoff 行不使 A 變動（A 仍 0 ＝ 該單仍判 active）",
      len(_marker_mod.ARCHIVED.findall(_fixture)) == 0, f"fixture={_fixture!r}")


# ── #300 AC-2：grammar 住 relay.py，附理由與上移觸發條件 ────────────────────
print("\n── #300 AC-2：grammar 常數的位置、理由與上移觸發條件")

check("#300 AC-2 grammar 常數定義在 devflow_relay.py（模組屬性讀得到）",
      isinstance(getattr(_mod, "HANDOFF_RE", None), str)
      and isinstance(getattr(_mod, "HANDOFF_FMT", None), str),
      f"HANDOFF_RE={getattr(_mod, 'HANDOFF_RE', None)!r}")
_src_lines = RELAY_SRC.splitlines()
_const_idx = [i for i, ln in enumerate(_src_lines)
              if re.match(r"^HANDOFF_(FMT|RE|AT_FMT)\s*=", ln)]
check("#300 AC-2 三個常數都在模組頂層（行首賦值，不藏在函式裡）",
      len(_const_idx) >= 2, f"命中行={[i + 1 for i in _const_idx]}")
# 斷言：常數上下 5 行內要讀到「上移」與「第二個寫者」。
_near = "\n".join(_src_lines[max(0, min(_const_idx) - 5):max(_const_idx) + 6]
                  ) if _const_idx else ""
check("#300 AC-2 常數上下 5 行內含「上移」字樣（改這段的人直接讀到觸發條件）",
      "上移" in _near, f"鄰近={_near[:400]!r}")
check("#300 AC-2 常數上下 5 行內含「第二個寫者」字樣",
      "第二個寫者" in _near, f"鄰近={_near[:400]!r}")
check("#300 AC-2 上移觸發條件寫全（另一半：第一個程式讀者 ＋ 上移到 _marker.py）",
      "第一個程式讀者" in _near and "_marker.py" in _near, f"鄰近={_near[:600]!r}")
# T 要求原樣寫進註解的理由：`#287` 抽共用是消除重複，本單沒有重複可消。
check("#300 AC-2 註解載明 T 的理由（`#287` 抽共用是消除重複）",
      "#287" in RELAY_SRC and "消除重複" in RELAY_SRC, "")
check("#300 AC-2 註解載明本單沒有重複可消（一個寫者、零程式讀者）",
      "一個寫者" in RELAY_SRC and "零程式讀者" in RELAY_SRC
      and "沒有重複" in RELAY_SRC, "")
# grammar **沒有**被放進 `_marker.py`（`AC-2` 的機械斷言）。
# 這裡不跑 `git diff`：本檔的既有判準禁止任何真子程序（見上方 `AC-6` 兩條），
# 而「零改動」的 git 事實由 T 的驗證指令在 shell 側取（`git diff --name-only`
# ／`--numstat`，見該單的驗證輸出）。**內容面**的斷言比 diff 更直接命中本 AC 要防的事：
# grammar 字面與 handoff 這個概念都不得出現在 `_marker.py` 裡。
MARKER_SRC = (SCRIPTS / "_marker.py").read_text()
# ── ⚠️ **本條不在掃單（`#308`）的刪除名單內，理由如下。**（`#308` `AC-5`）────────
# 1. 它斷言的是「**grammar 沒有上移**」，那是 `#300` 的**永久設計決定**——寫在
#    `devflow/channels/telegram.md` 的格裡（出現第二個寫者或第一個程式讀者時才上移），
#    **不是**單次射程限制。`#308` 刪掉的四條都是「本單不得改 X」被實作成
#    「X 永遠不得含 Y」；本條從一開始就是永久的內容規範，標的是
#    「`_marker.py` **現在該長什麼樣**」，對未來任何人、任何單都同樣成立。
# 2. 套 `test_marker.py` 檔頂 `AC-1`(a) 的三項判準：命中 1（負向，`not in`）、
#    命中 3（內容禁令），但**不命中 2**——語言標記不指向任何一張單的射程
#    （沒有「本單」「零改動」「相對 base」）。**三項缺一即不同形**，故不刪。
#    `test_marker.py` 的 `#308 AC-2` 自檢因此**必須放過本條**；該節有一條專驗這件事
#    （判準實作若誤殺本條，那條會 FAIL）。
# 3. 為何非寫這段不可：本條與被刪的四條**外觀相同**（皆為「X 不含 Y 字面」），
#    差別**只在意圖**。下一個掃描者若只看外觀，會誤判為同形並把它刪掉——
#    `#308` 把理由寫在這裡，就是為了阻止那件事。
#    出處：https://github.com/AugustusHsu/agent-devflow/issues/308
check("#300 AC-2 `_marker.py` 不含 `handoff` 字面（grammar 沒有上移）",
      "handoff" not in MARKER_SRC.lower(), "")
check("#300 AC-2 `_marker.py` 仍只有兩個 grammar 常數（未多出第三種標記）",
      len(re.findall(r"^[A-Z_]+_RE\s*=", MARKER_SRC, re.M)) == 2,
      f"命中={re.findall(r'^[A-Z_]+_RE.*$', MARKER_SRC, re.M)}")
# ── 此處原有第三條：`test_marker.py` 不含 `handoff` 字面（該檔零改動）。已刪除。
#
# 1. 來源：該斷言源自 `#300` 的**單次射程限制**（「本單不得改此檔」）。那是一張單的
#    write scope 宣告，其 AC 的斷言形式是 `git diff --name-only origin/main...HEAD`
#    ——問「這一次有沒有改到它」。
# 2. 兩層語意不一致：它卻被**實作成永久內容約束**（「這個檔永遠不得出現該字面」），
#    射程自一張單的 diff 擴張成跨單的內容禁令。`#306` 因此被迫以字元類別繞寫同一個
#    格名五輪，而該格名本身是 `telegram.md` 的合法格名。
# 3. 處置：`#306` 依裁決位裁示刪除（2026-10-09，第三次升人 `R13` `E2` 的裁示 (a)），見
#    https://github.com/AugustusHsu/agent-devflow/issues/300#issuecomment-6075821601
#
# ⚠️ 刪除而非改寫成「只核 `_marker.py`」：上方 `_marker.py` 那兩條本來就獨立存在且
# 正確，刪掉這一條不影響它們；改寫只會留下一條語意已變的斷言。
# `#306` `AC-14` 禁止把它加回來（判準：本檔不得出現讀取 `test_marker.py` 原始碼的字面）。


# ── #300 AC-5：寫 forge 失敗只警告不中斷，但警告必須進 topic ────────────────
print("\n── #300 AC-5：gh 回非 0 → rc 不變 ＋ topic 收到警告")

h5 = FakeSub(LINES, rc=0, gh_rc=1)
rch5, _, errh5 = run(["4149", "hi", "--issue", "287", "--then-wake", "dfmgr"], h5)
check("#300 AC-5 gh 回非 0 → relay 的 rc 仍是受託子程序的 rc（0，不變）",
      rch5 == 0, f"rc={rch5}")
check("#300 AC-5 gh 回非 0 → 流程不中斷（兩棒都照樣派出）",
      len(h5.spawned) == 2, f"spawned={len(h5.spawned)}")
_warn = [c for c in h5.send_calls if any("⚠" in str(a) for a in c)]
check("#300 AC-5 `sent` 中有一則含警告字樣（topic 送警告，不得只印 stderr）",
      len(_warn) >= 1,
      f"send 數={len(h5.send_calls)} 含警告={len(_warn)}")
check("#300 AC-5 該警告指出是 handoff／寫 forge 失敗（人讀得出要處置什麼）",
      any("handoff" in str(c) for c in _warn), f"警告={[str(c)[:200] for c in _warn]}")
check("#300 AC-5 該警告含單號（人知道是哪一張單缺了 handoff 行）",
      any("287" in str(c) for c in _warn), f"警告={[str(c)[:200] for c in _warn]}")
check("#300 AC-5 stderr 也留痕（有人看 log 時讀得到），但不是唯一的通報路徑",
      "handoff" in errh5 and len(_warn) >= 1, repr(errh5[:300]))
# 鑑別力一：gh_rc=0 時不得送警告（避免「永遠送警告」的實作蒙過上面那條）。
_warn_ok = [c for c in h1.send_calls if any("⚠" in str(a) for a in c)]
check("#300 AC-5 鑑別力：gh 回 0 時**不**送警告（非無條件警告）",
      len(_warn_ok) == 0, f"警告={[str(c)[:160] for c in _warn_ok]}")
# 鑑別力二：`_send` 判 success 的邏輯不受 returncode 影響——FakeSub 對 hermes 一律回 0，
# 但 `_send` 讀的是 stdout 的 `"success": true`，兩者是不同判準。
check("#300 AC-5 `_send` 的成敗判準未被 returncode 取代（仍讀 stdout 的 success）",
      '"success": true' in RELAY_SRC and _mod._send("dfmgr", "4149", "x") is True,
      "FakeSub 的 run 回 returncode=0 ＋ success stdout，_send 應回 True")
_mod_badsend = load(FakeSub(LINES))
_mod_badsend.subprocess.run = (
    lambda cmd, **kw: types.SimpleNamespace(stdout="{}", stderr="boom", returncode=0))
check("#300 AC-5 鑑別力：stdout 無 success 時 `_send` 回 False（即使 returncode 為 0）",
      _mod_badsend._send("dfmgr", "4149", "x") is False,
      "證明 returncode 沒有被當成送訊的成敗判準")
# 鑑別力三：gh 直接拋例外時同樣只警告不中斷。
class _BoomSub(FakeSub):
    def run(self, cmd, **kw):
        if cmd and cmd[0] == "gh":
            self.events.append("run:gh")
            raise OSError("gh not found")
        return super().run(cmd, **kw)


h5b = _BoomSub(LINES)
rch5b, _, errh5b = run(["4149", "hi", "--issue", "287", "--then-wake", "dfmgr"], h5b)
_warn_b = [c for c in h5b.send_calls if any("⚠" in str(a) for a in c)]
check("#300 AC-5 gh 拋例外（如 gh 不在 PATH）→ rc 不變、仍送警告、仍派兩棒",
      rch5b == 0 and len(h5b.spawned) == 2 and len(_warn_b) >= 1,
      f"rc={rch5b} spawned={len(h5b.spawned)} 警告={len(_warn_b)} err={errh5b[:200]!r}")


# ── #300 AC-6：兩檔的條文補句（純新增一行、逐字相同）──────────────────────
print("\n── #300 AC-6：WORKFLOW.md 與 channels/README.md 各補一行、逐字相同")

# 取「新增那一行」的方式：不跑 `git diff`（本檔禁止真子程序，見上方 `AC-6` 兩條），
# 而是從兩檔各自定位該句所在的那一行。T 的 `AC-6(b)` 要的是「自兩檔各取新增那一行、
# 字串相等」——定位方式不是斷言的內容，**取到的是同一行**即滿足。
#   純新增一行（`numstat` 須 `1 0`）由 T 的驗證指令在 shell 側取，不在本檔。
#   這裡另加兩條內容面的替代擔保：該句在各檔**恰出現一次**、且**緊接在**指定段落之後
#   （若有人把原句改長而非新增一行，那一行就不會是獨立的一行，第一條即掛）。
WF_TEXT = WORKFLOW_MD.read_text()
RM_TEXT = CHANNELS_README.read_text()
CH3_ANCHOR = "- `CH3` 分區狀態的權威在 forge"
RM_ANCHOR = "**其他組合（含 `T=0 A=1`"


def _line_after(text: str, anchor: str) -> str:
    """回傳以 `anchor` 起頭那一行的**下一行**（去頭尾空白前的原文）。"""
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith(anchor):
            return lines[i + 1] if i + 1 < len(lines) else ""
    return ""


_wf_add = [_line_after(WF_TEXT, CH3_ANCHOR)]
_rm_add = [_line_after(RM_TEXT, RM_ANCHOR)]
check("#300 AC-6 WORKFLOW.md 的 `CH3` 段之後緊接著一行非空的新句",
      bool(_wf_add[0].strip()), f"實得={_wf_add[0]!r}")
check("#300 AC-6 channels/README.md 的「其他組合」段之後緊接著一行非空的新句",
      bool(_rm_add[0].strip()), f"實得={_rm_add[0]!r}")
check("#300 AC-6(b) 兩條新增行**字串相等**（逐字相同，非語意等價）",
      _wf_add[0] == _rm_add[0],
      f"WORKFLOW={_wf_add[0]!r}\n        README={_rm_add[0]!r}")
check("#300 AC-6 該句在 WORKFLOW.md 恰出現一次（是新增的獨立一行，不是把原句改長）",
      bool(_wf_add[0].strip()) and WF_TEXT.count(_wf_add[0]) == 1
      and ("\n" + _wf_add[0] + "\n") in WF_TEXT,
      f"出現次數={WF_TEXT.count(_wf_add[0]) if _wf_add[0].strip() else 0}")
check("#300 AC-6 該句在 channels/README.md 恰出現一次（同上）",
      bool(_rm_add[0].strip()) and RM_TEXT.count(_rm_add[0]) == 1
      and ("\n" + _rm_add[0] + "\n") in RM_TEXT,
      f"出現次數={RM_TEXT.count(_rm_add[0]) if _rm_add[0].strip() else 0}")
if _wf_add[0].strip():
    _sent = _wf_add[0]
    check("#300 AC-6 補句載明三態判定只讀分區狀態標記（topic／archived）",
          "三態判定" in _sent and "devflow:topic" in _sent and "devflow:archived" in _sent,
          repr(_sent))
    check("#300 AC-6 補句載明其他 `devflow:*` 標記不參與三態判定",
          "devflow:*" in _sent and "不參與三態判定" in _sent, repr(_sent))
    check("#300 AC-6 補句點名 handoff 行（讀者知道新增的那一行屬於哪一類）",
          "handoff" in _sent, repr(_sent))
# 兩檔原本那一段的字句不得被動到（`AC-6(a)` 的「不得順手改動該節其他字句」）。
check("#300 AC-6 `CH3` 原段落的關鍵字面未被改動",
      "三態加上 INVALID 這個 catch-all 分支" in WF_TEXT
      and "不以通道側的列舉或本機快取為權威" in WF_TEXT, "")
check("#300 AC-6 README「其他組合」原段落的關鍵字面未被改動",
      "加上 INVALID 這個 catch-all**，才對所有標記組合互斥且窮盡" in RM_TEXT
      and "判定程式須對 INVALID 回非 0 或明確吐 `INVALID`" in RM_TEXT, "")
check("#300 AC-6 判定式那一行（README `:59`）未被動到（`_marker.py` 的逐字來源）",
      "grep -cE '^<!-- devflow:topic thread=[0-9]+ -->$'" in RM_TEXT
      and "grep -cE '^<!-- devflow:archived thread=[0-9]+ file=[^ >]+ -->$'" in RM_TEXT,
      "")


# ── #300 AC-7：telegram.md 的格 ─────────────────────────────────────────────
print("\n── #300 AC-7：telegram.md 加一格（含判準表與已知限制，狀態不得 ✅）")

TG300 = TELEGRAM_MD.read_text()
_rows = [ln for ln in TG300.splitlines()
         if ln.startswith("|") and "handoff" in ln]
check("#300 AC-7 通用表有一列講 handoff 行", len(_rows) == 1, f"命中列數={len(_rows)}")
if len(_rows) == 1:
    _cells = _rows[0].split(" | ")
    check("#300 AC-7 該列與既有格同形（面向／職位／值／狀態 四欄）",
          len(_cells) == 4, f"欄數={len(_cells)} 列={_rows[0][:160]!r}")
    _aspect, _seat, _value, _status = (_cells + ["", "", "", ""])[:4]
    check("#300 AC-7 面向欄指明是第二棒的 handoff 行",
          "handoff" in _aspect, repr(_aspect))
    check("#300 AC-7 職位欄是 manager（或 coordinator／manager）",
          "manager" in _seat, repr(_seat))
    check("#300 AC-7 狀態欄**不含** `✅`（本單 forge 側零實跑）",
          "✅ 可用" not in _status and not _status.lstrip("| ").startswith("✅"),
          repr(_status[:200]))
    check("#300 AC-7 狀態欄取 R9 三值之一且為 `📝`／`⬜`",
          _status.lstrip("| ").startswith(("📝 已宣稱", "⬜ 未測")), repr(_status[:200]))
    check("#300 AC-7 狀態欄依 R9 寫明理由與第三者可執行的驗證方式",
          "驗證方式" in _status and "零實跑" in _status, repr(_status[:300]))
    check("#300 AC-7 狀態欄依 R10 載明受測環境",
          "R10" in _status and "受測環境" in _status, repr(_status[:300]))
    check("#300 AC-7 值欄載明 handoff 行的字面",
          "devflow:handoff" in _value, repr(_value[:200]))
    check("#300 AC-7 值欄載明三欄語意（profile／at／rc 各自是什麼）",
          "profile" in _value and "`at`" in _value and "`rc`" in _value,
          repr(_value[:300]))
    check("#300 AC-7 值欄載明寫入時機（發出第二棒之後）",
          "發出第二棒之後" in _value, repr(_value[:300]))
    check("#300 AC-7 值欄載明 AC-3 的三列判準表（正常／C／無 handoff 行）",
          "正常" in _value and "**C**" in _value and "handoff 行**無**" in _value,
          repr(_value[:400]))
    check("#300 AC-7 值欄載明 AC-5 的已知限制：「無 handoff 行」有兩種成因",
          "relay 沒接手" in _value and "寫 forge 失敗" in _value and "兩種" in _value,
          repr(_value[:400]))
    check("#300 AC-7 判準表**不宣稱**那兩種成因分得開",
          "不宣稱它分得開" in _value, repr(_value[:400]))


# ── #300 AC-10：縫不變（本檔自身的機械判準）────────────────────────────────
print("\n── #300 AC-10：縫不變——gh 也經模組全域 subprocess，零真 API")

check("#300 AC-10 gh 與送訊走同一個名字（模組內 run 的呼叫點仍恰一處）",
      len(re.findall(r"subprocess\.run\(", RELAY_SRC)) == 1
      and len(re.findall(r"subprocess\.Popen\(", RELAY_SRC)) == 1,
      f"run={len(re.findall(r'subprocess.run', RELAY_SRC))} "
      f"Popen={len(re.findall(r'subprocess.Popen', RELAY_SRC))}")
check("#300 AC-10 relay 不自己開 http／socket／os.system（縫沒有被繞過）",
      not re.search(r"^import (requests|urllib|http|socket)", RELAY_SRC, re.M)
      and "os.system" not in RELAY_SRC, "")
check("#300 AC-10 本檔的假類確實攔下 gh（gh 呼叫全部落進 FakeSub.sent）",
      bool(h1.gh_calls) and all(c in h1.sent for c in h1.gh_calls), "")
check("#300 AC-10 FakeSub.run 回傳物件帶 returncode（預設 0，不影響 _send 的判準）",
      hasattr(FakeSub(LINES).run(["hermes"]), "returncode")
      and FakeSub(LINES).run(["hermes"]).returncode == 0, "")
check("#300 AC-10 `gh_rc` 只作用於 gh（hermes send 的 returncode 仍 0）",
      FakeSub(LINES, gh_rc=1).run(["hermes", "send"]).returncode == 0
      and FakeSub(LINES, gh_rc=1).run(["gh", "issue"]).returncode == 1, "")
check("#300 AC-10 三個假常數與時間常數覆寫都還在（既有 load() 未被破壞）",
      all(hasattr(FakeSub, k) for k in ("PIPE", "DEVNULL", "STDOUT"))
      and _mod.OPENING_DELAY == 10 ** 9 and _mod.HEARTBEAT_AFTER == 10 ** 9, "")
check("#300 AC-10 本檔仍零 import-path 操作、仍以 spec_from_file_location 載入",
      re.search(r"sys\." + "path", SELF_SRC) is None
      and "importlib.util.spec_from_file_location" in SELF_SRC, "")
check("#300 AC-10 本檔仍不 import subprocess、不真呼叫 run／Popen",
      re.search(r"^import subprocess$", SELF_SRC, re.M) is None
      and re.search(r"subprocess\.(run|Popen)\(", SELF_SRC) is None, "")


# ── #300 AC-3：不寫第二行 ───────────────────────────────────────────────────
print("\n── #300 AC-3：不寫第二行、不新增 seat 自律")

check("#300 AC-3 一次派工只寫一則留言（不寫第二行結果行）",
      len(h1.gh_calls) == 1, f"gh 呼叫={len(h1.gh_calls)}：{h1.gh_calls}")
check("#300 AC-3 rc 仍只回受託子程序的（relay 不等第二棒、不蓋掉這一輪的結果）",
      rch1 == 0 and "回傳的仍是受託子程序的 rc" in RELAY_SRC, f"rc={rch1}")
check("#300 AC-3 第二棒的子程序 prompt 不要求它自報結果（否決「被喚醒 seat 自報」）",
      "handoff" not in prompt_of(h1.spawned[1]).lower()
      and "回報" not in prompt_of(h1.spawned[1]),
      f"prompt={prompt_of(h1.spawned[1])[:300]!r}")
# ── 此處原有一條（`#308` `AC-3` ❶，已刪除）──────────────────────────────────
#    「`#300` `AC-3` 本單不新增 seat 自律：`manager.md` 不含 `handoff` 字面」，
#    斷言形式 `"handoff" not in MGR.lower()`。
#
# 1. **來源**：`#300` 的**單次射程限制**。該單宣告「不新增 seat 自律」，其 AC 的
#    斷言形式是 `git diff --name-only`（恰 6 檔，`manager.md` 不在內）——
#    問的是「**這一次**有沒有改到它」。
# 2. **為何過寬**（兩層語意不一致）：它被實作成「`devflow/seats/manager.md`
#    **永遠**不得出現 `handoff` 字面」。射程自一張單的 diff 擴張成跨單的內容禁令：
#    `handoff` 行是 manager 真的要處置的事，後續任何單想在 manager 的職位檔寫
#    一句關於它的**合法**說明，都會先在這裡假 FAIL——而沒有人宣告過那道禁令。
#    實測（`#308` 探針 A，`manager.md` 加 `handoff` 字面）：原本只命中此條。
# 3. **處置與出處**：本單依裁決位 2026-10-09 裁示**刪除**，
#    https://github.com/AugustusHsu/agent-devflow/issues/308
# 4. **為何刪而非改寫**（`test_marker.py` 檔頂 `AC-1`(c)）：**意圖本身已失效**——
#    「本單不新增 seat 自律」在 `#300` 合併後**已成歷史**，無法也不需由測試持續
#    守護。`#300` 真正的設計決定（第二棒不自報結果）由上方那條 prompt 斷言守著，
#    它標的是 relay **當下**發出的 prompt，不受此條刪除影響。
check("#300 AC-3 判準表的最後一列只宣稱「relay 沒接手」，不把成因說成分得開",
      "relay 沒接手" in TG300 and "不宣稱它分得開" in TG300, "")


# ════════════════════════════════════════════════════════════════════════════
# `#312`：`--then-wake` 的續接不計巢狀深度（primary／continuation 分流）
# ════════════════════════════════════════════════════════════════════════════
# 要防的事（`#310` 現場）：`_child_env` 對 relay 派出的**每一個**子程序寫 `depth+1`，
# 含 `--then-wake` 喚醒者。喚醒者是同一流程的續接、取代呼叫者繼續跑，於是同一張單每輪
# +1，第 3 輪的 manager 以 `DEVFLOW_RELAY_DEPTH=3` 被自己的 relay 拒絕（那時的鏈
# `dfmgr,dfmgr,dfmgr` 不是遞迴，是三輪續接）。
#
# 判準（裁決位 2026-10-14 選定甲案）＝「**這個子程序是怎麼被派出的**」，**不讀 profile 名**：
#   primary（受託子程序）        → 呼叫者 `+1`，鏈以 `,` 接（行為與字面皆不變）
#   continuation（then-wake）    → **呼叫者自身的深度**（不 +1），鏈以 `>` 接
# 「呼叫者」＝啟動本次 relay 的那一層（relay 自己的 `_current_depth()`）。跨 profile 的
# continuation 同樣只是**不增深**：coder（`DEPTH=2`）的 `--then-wake dfmgr` 得 `2`，
# 不是祖先 manager 的 `1`——深度停在呼叫者那一層。
#
# 反例一律**實跑**：以 source 字串突變後 `importlib` 載入另一個模組名、走同一支 `run_mod`
# 驅動（正例與反例跑同一條路徑），或對純函式層直接以突變實作對照。矩陣 11 列與本節案例
# 的對應寫在各條標題與其上方註解裡。
print("\n── #312 AC-1／AC-2：primary 與 continuation 的深度與鏈（純函式層）")

P312_MAX = mod_consts.MAX_RELAY_DEPTH
P312_LIMIT_SENTENCE = "純 continuation 的平層循環不增深，本機制不保證擋住它"
# 空 chain 的 continuation 以 `>` 起首（`R1` 第 1 輪 `BLOCK 1`）：訊息與文件共用同一字面。
P312_LEADING_SENTENCE = "鏈以 `>` 起首 ＝ 最外層那一層即為續接"


def p312_mutate(src: str, old: str, new: str) -> str:
    """字串突變。錨點須恰一處命中——漂移時回傳原文，由呼叫處「突變確實套上」那條報出，
    不靜默變成 no-op（no-op 的反例會假 PASS，那正是反例要防的事）。"""
    return src.replace(old, new, 1) if src.count(old) == 1 else src


def load_mutant(src: str, name: str, fake):
    """把突變後的 source 寫進本檔的暫存目錄、以另一個模組名載入，並注入假 subprocess。

    形狀同 `test_marker.py` 的突變案例（寫暫存檔 ＋ `spec_from_file_location`）。
    同層 import（`devflow_archive`）由 `load()` 已登錄的 `sys.modules` 解析。
    """
    path = TESTTMP / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.subprocess = fake
    mod.OPENING_DELAY = 10 ** 9
    mod.HEARTBEAT_AFTER = 10 ** 9
    mod.time.strftime = _REAL_STRFTIME
    return mod


# 突變的錨點（都是受測檔裡恰一處的字面；錨點漂移由「突變確實套上」那幾條報出）
P312_DEPTH_LINE = "    env[DEPTH_ENV] = str(depth if continuation else depth + 1)\n"
P312_LIMIT_LINE = "    if depth >= MAX_RELAY_DEPTH:\n"
P312_CHAIN_LINE = ('    env[CHAIN_ENV] = f"{chain}{sep}{profile}"'
                   " if chain or continuation else profile\n")

# 矩陣 1：維持 `#312` 之前的行為（對每個子程序都 +1）→ AC-1(b) 的期望值不成立。
P312_MUT_ALWAYS = p312_mutate(RELAY_SRC, P312_DEPTH_LINE,
                              "    env[DEPTH_ENV] = str(depth + 1)\n")
# 矩陣 2：讓 primary 也承襲呼叫者深度 → AC-1(a) 與 AC-4（巢狀不再被擋）皆不成立。
P312_MUT_NEVER = p312_mutate(RELAY_SRC, P312_DEPTH_LINE,
                             "    env[DEPTH_ENV] = str(depth)\n")
# 矩陣 7：**以 profile 名去重**——profile 已在鏈上就不 +1（T 明列禁止的判準）。
P312_MUT_DEDUP = p312_mutate(
    RELAY_SRC, P312_DEPTH_LINE,
    '    _chain = os.environ.get(CHAIN_ENV, "").replace(CHAIN_CONT_SEP, CHAIN_NEST_SEP)\n'
    '    _seen = [p for p in _chain.split(CHAIN_NEST_SEP) if p]\n'
    "    env[DEPTH_ENV] = str(depth if (continuation or profile in _seen) else depth + 1)\n")
# 矩陣 8：把 `--then-wake` 到**不同** profile 者當成 primary（+1）→ AC-5(b) 不成立。
P312_MUT_CROSS = p312_mutate(
    RELAY_SRC, P312_DEPTH_LINE,
    '    _last = os.environ.get(CHAIN_ENV, "")'
    ".replace(CHAIN_CONT_SEP, CHAIN_NEST_SEP).split(CHAIN_NEST_SEP)[-1]\n"
    "    env[DEPTH_ENV] = str(depth if (continuation and profile == _last) else depth + 1)\n")
# 矩陣 5：上限判準改看鏈去重後的集合大小 → AC-4 的真遞迴轉為放行。
P312_MUT_SETSIZE = p312_mutate(
    RELAY_SRC, P312_LIMIT_LINE,
    '    _uniq = {p for p in os.environ.get(CHAIN_ENV, "")'
    ".replace(CHAIN_CONT_SEP, CHAIN_NEST_SEP).split(CHAIN_NEST_SEP) if p}\n"
    "    if len(_uniq) >= MAX_RELAY_DEPTH:\n")
# 矩陣 9：上限被改大 → AC-6(a) 的兩條（常數值、字面恰一次）轉為不成立。
P312_MUT_BIGGER = p312_mutate(RELAY_SRC, "\nMAX_RELAY_DEPTH = 3\n", "\nMAX_RELAY_DEPTH = 9\n")
# 矩陣 10：條件式被加上環境旁路開關 → AC-6(c) 的 AST 檢查命中。
P312_MUT_BYPASS = p312_mutate(
    RELAY_SRC, P312_LIMIT_LINE,
    '    if depth >= MAX_RELAY_DEPTH and not os.environ.get("RELAY_NO_DEPTH"):\n')
# 矩陣 11：把超限訊息裡的射程說明刪掉 → AC-5(d) 的訊息斷言轉為不成立。
P312_MUT_NOSCOPE = p312_mutate(
    RELAY_SRC,
    '              f"純 continuation 的平層循環不增深，本機制不保證擋住它。",\n',
    '              f"（射程說明已被刪除）",\n')
# `R1` 第 1 輪 `BLOCK 1` 的破壞對照：還原成 `if chain else profile`——空 chain 時
# 丟掉起首的 `>`，於是同一 profile 的 primary 與 continuation 得到相同的 chain。
P312_MUT_DROPSEP = p312_mutate(
    RELAY_SRC, P312_CHAIN_LINE,
    '    env[CHAIN_ENV] = f"{chain}{sep}{profile}" if chain else profile\n')

check("#312 突變確實套上（九種 source 突變都與受測原文不同）",
      all(m != RELAY_SRC for m in (P312_MUT_ALWAYS, P312_MUT_NEVER, P312_MUT_DEDUP,
                                   P312_MUT_CROSS, P312_MUT_SETSIZE, P312_MUT_BIGGER,
                                   P312_MUT_BYPASS, P312_MUT_NOSCOPE, P312_MUT_DROPSEP)),
      "錨點漂移：某個突變沒有套上去（no-op 的反例會假 PASS）")

# ── AC-1：深度語意（純函式層，零子程序、零網路）───────────────────────────────
f312_pure = FakeSub(LINES)
m312 = load(f312_pure)
P312_CALLER = {DEPTH_KEY: "1", CHAIN_KEY: "dfmgr"}        # 呼叫者＝manager 那一層
p312_prim = with_env(P312_CALLER, lambda: m312._child_env("dfimpl"))
p312_cont = with_env(P312_CALLER, lambda: m312._child_env("dfmgr", continuation=True))

check("#312 AC-1(a) primary 的深度 ＝ 呼叫者 +1（呼叫者 1 → primary '2'）",
      p312_prim[DEPTH_KEY] == "2", f"primary depth={p312_prim[DEPTH_KEY]!r}")
check("#312 AC-1(b) continuation 的深度 ＝ 呼叫者自身（呼叫者 1 → 喚醒者 '1'）",
      p312_cont[DEPTH_KEY] == "1", f"continuation depth={p312_cont[DEPTH_KEY]!r}")
_p312_ac1 = [lbl for lbl, _, _ in RESULTS if lbl.startswith("#312 AC-1(")]
check("#312 AC-1(c) primary 與 continuation 各有一條獨立斷言（聚合值或單一條都算未達成）",
      len([t for t in _p312_ac1 if "AC-1(a)" in t]) >= 1
      and len([t for t in _p312_ac1 if "AC-1(b)" in t]) >= 1,
      f"本節 AC-1 的斷言標題={_p312_ac1!r}")
check("#312 AC-1 這一段是純函式層：一個子程序都沒派、一則訊息都沒送",
      len(f312_pure.spawned) == 0 and len(f312_pure.sent) == 0,
      f"spawned={f312_pure.spawned} sent={f312_pure.sent}")

# 矩陣 1：維持現行（每個子程序都 +1）→ AC-1(b) 的期望值轉為不成立。
_m1 = load_mutant(P312_MUT_ALWAYS, "devflow_relay_mut_always", FakeSub(LINES))
_c1 = with_env(P312_CALLER, lambda: _m1._child_env("dfmgr", continuation=True))
check("#312 矩陣 1：對每個子程序都 +1 的突變下，喚醒者得 '2' ≠ AC-1(b) 的 '1'（實跑對照）",
      _c1[DEPTH_KEY] == "2" and _c1[DEPTH_KEY] != p312_cont[DEPTH_KEY],
      f"突變={_c1[DEPTH_KEY]!r} 正確={p312_cont[DEPTH_KEY]!r}")

# 矩陣 2：primary 也承襲呼叫者深度 → AC-1(a) 的期望值轉為不成立。
_m2 = load_mutant(P312_MUT_NEVER, "devflow_relay_mut_never", FakeSub(LINES))
_p2 = with_env(P312_CALLER, lambda: _m2._child_env("dfimpl"))
check("#312 矩陣 2：primary 也承襲呼叫者深度的突變下，primary 得 '1' ≠ AC-1(a) 的 '2'（實跑對照）",
      _p2[DEPTH_KEY] == "1" and _p2[DEPTH_KEY] != p312_prim[DEPTH_KEY],
      f"突變={_p2[DEPTH_KEY]!r} 正確={p312_prim[DEPTH_KEY]!r}")

# ── AC-2：鏈上機械可區分，超限訊息看得出哪幾層巢狀、哪幾層續接 ────────────────
check("#312 AC-2 primary 以 `,` 接、continuation 以 `>` 接（同一呼叫者，兩類鏈不同）",
      p312_prim[CHAIN_KEY] == "dfmgr,dfimpl" and p312_cont[CHAIN_KEY] == "dfmgr>dfmgr",
      f"primary={p312_prim[CHAIN_KEY]!r} continuation={p312_cont[CHAIN_KEY]!r}")
check("#312 AC-2 兩個分隔符各寫成模組常數（`,` 巢狀、`>` 續接）",
      m312.CHAIN_NEST_SEP == "," and m312.CHAIN_CONT_SEP == ">",
      f"nest={m312.CHAIN_NEST_SEP!r} cont={m312.CHAIN_CONT_SEP!r}")

# ── AC-2 的合法邊界：呼叫者的 chain 未設（relay 自身在最外層）──────────────────
# `R1` 第 1 輪 `BLOCK 1`：`_child_env` 原寫 `… if chain else profile`，空 chain 時把
# 分隔符整個丟掉，於是同一 profile 的 primary 與 continuation 都得到 `dfmgr`——
# AC-2 的「可機械區分」在這個**合法輸入**下不成立，而既有回歸（上方 `f4` 那組，relay
# 自身未設深度／鏈）走的正是這條路徑。修正：空 chain 的 continuation 保留起首的 `>`，
# primary 維持裸 profile（既有 primary 斷言的字面因此一字不變）。
P312_EMPTY = {DEPTH_KEY: None, CHAIN_KEY: None}
p312_e_prim = with_env(P312_EMPTY, lambda: m312._child_env("dfmgr"))[CHAIN_KEY]
p312_e_cont = with_env(P312_EMPTY, lambda: m312._child_env("dfmgr", continuation=True))[CHAIN_KEY]
check("#312 AC-2 空 chain 的 primary 仍是裸 profile（'dfmgr'，既有字面不變）",
      p312_e_prim == "dfmgr", f"primary={p312_e_prim!r}")
check("#312 AC-2 空 chain 的 continuation 保留起首的 `>`（'>dfmgr'）",
      p312_e_cont == ">dfmgr", f"continuation={p312_e_cont!r}")
check("#312 AC-2 空 chain 下同一 profile 的兩類 chain 相異（可機械區分）",
      p312_e_prim != p312_e_cont, f"primary={p312_e_prim!r} continuation={p312_e_cont!r}")
check("#312 AC-2 空 chain 的 continuation 可機械辨識（以 `>` 起首、切分後首段為空；primary 不是）",
      p312_e_cont.startswith(m312.CHAIN_CONT_SEP)
      and p312_e_cont.split(m312.CHAIN_CONT_SEP)[0] == ""
      and not p312_e_prim.startswith(m312.CHAIN_CONT_SEP),
      f"primary={p312_e_prim!r} continuation={p312_e_cont!r}")
# 同一組的既有 AC-6(b) 案例（`f4`，relay 自身未設）：喚醒者深度 `"0"`、鏈 `'>dfmgr'`。
check("#312 AC-2／AC-6(b) `f4` 那組的喚醒者鏈為 '>dfmgr'（與其 primary 的 'dfmgr' 分得開）",
      len(f4.kwargs) == 2
      and f4.kwargs[1].get("env", {}).get(CHAIN_KEY) == ">dfmgr"
      and f4.kwargs[0].get("env", {}).get(CHAIN_KEY) == "dfmgr",
      f"primary={f4.kwargs[0].get('env', {}).get(CHAIN_KEY)!r} "
      f"continuation={f4.kwargs[1].get('env', {}).get(CHAIN_KEY) if len(f4.kwargs) > 1 else None!r}")

# `BLOCK 1` 的破壞對照（實跑）：還原 `if chain else profile` → 空 chain 下兩類相等。
_f12 = FakeSub(LINES)
_m12 = load_mutant(P312_MUT_DROPSEP, "devflow_relay_mut_dropsep", _f12)
_m12_prim = with_env(P312_EMPTY, lambda: _m12._child_env("dfmgr"))[CHAIN_KEY]
_m12_cont = with_env(P312_EMPTY, lambda: _m12._child_env("dfmgr", continuation=True))[CHAIN_KEY]
check("#312 AC-2 BLOCK 1 反例：還原 `if chain else profile` → 空 chain 下兩類 chain 相等（實跑對照）",
      _m12_prim == _m12_cont == "dfmgr" and p312_e_prim != p312_e_cont,
      f"突變 primary={_m12_prim!r} continuation={_m12_cont!r}；"
      f"受測 primary={p312_e_prim!r} continuation={p312_e_cont!r}")
check("#312 AC-2 BLOCK 1 反例：突變只動到空 chain 那一支（非空 chain 的兩類字面不受影響）",
      with_env(P312_CALLER, lambda: _m12._child_env("dfimpl"))[CHAIN_KEY] == "dfmgr,dfimpl"
      and with_env(P312_CALLER,
                   lambda: _m12._child_env("dfmgr", continuation=True))[CHAIN_KEY] == "dfmgr>dfmgr",
      "非空 chain 下突變與受測實作的 chain 應相同（故上一條分得開的是空 chain 那一支）")

f312_over = FakeSub(LINES)
P312_MIXED_CHAIN = "dfcoord,dfmgr>dfmgr,dfimpl"
rc312_over, _, err312_over = with_env(
    {DEPTH_KEY: str(P312_MAX), CHAIN_KEY: P312_MIXED_CHAIN},
    lambda: run(["4149", "hi", "--issue", "312", "--then-wake", "dfmgr"], f312_over))
check("#312 AC-2 超限訊息印出混合鏈的原文（巢狀與續接兩種接法都在）",
      P312_MIXED_CHAIN in err312_over, repr(err312_over[:500]))
check("#312 AC-2 超限訊息解釋 `,`／`>` 的意義（讀訊息就看得出哪幾層是巢狀、哪幾層是續接）",
      "`,` ＝巢狀一層" in err312_over and "`>` ＝同一流程的續接" in err312_over
      and "continuation" in err312_over and "primary" in err312_over,
      repr(err312_over[:600]))
check("#312 AC-2 超限訊息也載明空 chain 那一支的讀法（`>` 起首 ＝ 最外層即續接）",
      P312_LEADING_SENTENCE in err312_over, repr(err312_over[:700]))

# ── AC-3：同一張單連續 6 輪（每輪 primary ＋ then-wake 續接）──────────────────
print("\n── #312 AC-3：同一張單連續 6 輪不累加")

P312_ROUNDS = 6
P312_ARGV = ["4149", "hi", "-p", "dfimpl", "--issue", "312", "--then-wake", "dfmgr"]
p312_env = {DEPTH_KEY: "1", CHAIN_KEY: "dfmgr"}       # 第 1 輪的 manager（coord → mgr 之後）
p312_log: list[tuple] = []
for _n in range(1, P312_ROUNDS + 1):
    _f = FakeSub(LINES)
    _rc, _, _ = with_env(dict(p312_env), lambda f=_f: run(list(P312_ARGV), f))
    _prim_env = _f.kwargs[0].get("env", {}) if _f.kwargs else {}
    _cont_env = _f.kwargs[1].get("env", {}) if len(_f.kwargs) > 1 else {}
    p312_log.append((_n, _rc, len(_f.spawned), _prim_env.get(DEPTH_KEY),
                     _cont_env.get(DEPTH_KEY), _prim_env.get(CHAIN_KEY),
                     _cont_env.get(CHAIN_KEY)))
    if not _cont_env:
        break
    p312_env = {DEPTH_KEY: _cont_env[DEPTH_KEY], CHAIN_KEY: _cont_env[CHAIN_KEY]}

print("     逐輪：" + "；".join(
    f"第 {n} 輪 rc={rc} spawned={sp} primary={pd} 續接={cd} 續接鏈={cc}"
    for n, rc, sp, pd, cd, _pc, cc in p312_log))

check("#312 AC-3(a) 六輪的 primary 深度恆為同一值（'2'）",
      len(p312_log) == P312_ROUNDS and {r[3] for r in p312_log} == {"2"},
      f"輪數={len(p312_log)} primary 深度集合={ {r[3] for r in p312_log} !r}")
check("#312 AC-3(b) 六輪的續接者深度恆為同一值（'1' ＝呼叫者自身那一層）",
      len(p312_log) == P312_ROUNDS and {r[4] for r in p312_log} == {"1"},
      f"續接深度集合={ {r[4] for r in p312_log} !r}")
check("#312 AC-3(c) 六輪都放行（每輪 rc 0 且恰兩個子程序）",
      len(p312_log) == P312_ROUNDS
      and all(r[1] == 0 and r[2] == 2 for r in p312_log),
      f"逐輪 (rc, spawned)={[(r[1], r[2]) for r in p312_log]!r}")
check("#312 AC-3 鏈仍逐輪成長（深度不累加，但棒次全保留，供 `#313` 的判準使用）",
      p312_log[-1][6].count(">") == P312_ROUNDS and p312_log[-1][6].startswith("dfmgr"),
      f"第 6 輪的續接鏈={p312_log[-1][6]!r}")

# 矩陣 4：現行實作（每個子程序都 +1）跑同樣六輪 → 第 3 輪即被拒。
p312_mut_env = {DEPTH_KEY: "1", CHAIN_KEY: "dfmgr"}
p312_mut_log: list[tuple] = []
for _n in range(1, P312_ROUNDS + 1):
    _f = FakeSub(LINES)
    _mm = load_mutant(P312_MUT_ALWAYS, f"devflow_relay_mut_always_r{_n}", _f)
    _rc, _, _ = with_env(dict(p312_mut_env), lambda m=_mm: run_mod(m, list(P312_ARGV)))
    p312_mut_log.append((_n, _rc, len(_f.spawned)))
    if len(_f.kwargs) < 2:
        break
    _ce = _f.kwargs[1].get("env", {})
    p312_mut_env = {DEPTH_KEY: _ce[DEPTH_KEY], CHAIN_KEY: _ce[CHAIN_KEY]}

check("#312 矩陣 4：現行實作的突變跑同一組六輪 → 第 3 輪即被拒且零子程序（實跑對照）",
      [n for n, rc, _ in p312_mut_log if rc not in (0, None)] == [3]
      and p312_mut_log[-1][2] == 0 and len(p312_mut_log) == 3,
      f"逐輪 (輪, rc, spawned)={p312_mut_log!r}")

# ── AC-4：真實巢狀仍被擋，且拒絕在派子程序之前 ───────────────────────────────
print("\n── #312 AC-4／AC-5：primary 的巢狀與遞迴仍被擋（判準不是 profile 名）")

# coordinator(0) → manager(1) → coder(2) → coder(3)：逐層以真 `_child_env` 推，不寫死值。
_e_coord = {DEPTH_KEY: None, CHAIN_KEY: None}
p312_mgr = with_env(_e_coord, lambda: m312._child_env("dfmgr"))
p312_coder = with_env({DEPTH_KEY: p312_mgr[DEPTH_KEY], CHAIN_KEY: p312_mgr[CHAIN_KEY]},
                      lambda: m312._child_env("dfimpl"))
p312_coder2 = with_env({DEPTH_KEY: p312_coder[DEPTH_KEY], CHAIN_KEY: p312_coder[CHAIN_KEY]},
                       lambda: m312._child_env("dfimpl"))
P312_NEST_ENV = {DEPTH_KEY: p312_coder2[DEPTH_KEY], CHAIN_KEY: p312_coder2[CHAIN_KEY]}
check("#312 AC-4 primary 疊 primary 疊 primary → 第三層達上限（深度 '3'、鏈三層皆以 `,` 接）",
      p312_coder2[DEPTH_KEY] == str(P312_MAX)
      and p312_coder2[CHAIN_KEY] == "dfmgr,dfimpl,dfimpl"
      and ">" not in p312_coder2[CHAIN_KEY],
      f"深度={p312_coder2[DEPTH_KEY]!r} 鏈={p312_coder2[CHAIN_KEY]!r}")

f312_nest = FakeSub(LINES)
rc312_nest, _, err312_nest = with_env(
    P312_NEST_ENV, lambda: run(["4149", "hi", "--issue", "312", "--then-wake", "dfmgr"],
                               f312_nest))
check("#312 AC-4 該層的 relay 拒絕派子程序（rc 非 0）",
      rc312_nest not in (0, None), f"rc={rc312_nest}")
check("#312 AC-4 拒絕在派子程序之前：spawned 計數 0 反證 Popen 未被呼叫",
      len(f312_nest.spawned) == 0, f"spawned={f312_nest.spawned}")

# 矩陣 2 的後半：primary 也承襲呼叫者深度時，巢狀不再被擋。
_m2b_env = {DEPTH_KEY: None, CHAIN_KEY: None}
_m2_mgr = with_env(_m2b_env, lambda: _m2._child_env("dfmgr"))
_m2_coder = with_env({DEPTH_KEY: _m2_mgr[DEPTH_KEY], CHAIN_KEY: _m2_mgr[CHAIN_KEY]},
                     lambda: _m2._child_env("dfimpl"))
_m2_coder2 = with_env({DEPTH_KEY: _m2_coder[DEPTH_KEY], CHAIN_KEY: _m2_coder[CHAIN_KEY]},
                      lambda: _m2._child_env("dfimpl"))
_f2b = FakeSub(LINES)
_m2run = load_mutant(P312_MUT_NEVER, "devflow_relay_mut_never_run", _f2b)
_rc2b, _, _ = with_env({DEPTH_KEY: _m2_coder2[DEPTH_KEY], CHAIN_KEY: _m2_coder2[CHAIN_KEY]},
                       lambda: run_mod(_m2run, ["4149", "hi"]))
check("#312 矩陣 2：primary 不增深的突變下，三層巢狀的深度停在 '0' 並被放行（實跑對照）",
      _m2_coder2[DEPTH_KEY] == "0" and _rc2b == 0 and len(_f2b.spawned) == 1,
      f"三層後深度={_m2_coder2[DEPTH_KEY]!r} rc={_rc2b} spawned={len(_f2b.spawned)}")

# 矩陣 5：上限判準改看鏈去重後的集合大小 → 同一個真遞迴情境轉為放行。
_f5 = FakeSub(LINES)
_m5 = load_mutant(P312_MUT_SETSIZE, "devflow_relay_mut_setsize", _f5)
_rc5, _, _ = with_env(P312_NEST_ENV,
                      lambda: run_mod(_m5, ["4149", "hi", "--issue", "312",
                                            "--then-wake", "dfmgr"]))
check("#312 矩陣 5：上限改看鏈去重後的集合大小 → 同一個三層巢狀轉為放行（實跑對照）",
      _rc5 == 0 and len(_f5.spawned) == 2 and rc312_nest not in (0, None),
      f"突變 rc={_rc5} spawned={len(_f5.spawned)}；正確實作 rc={rc312_nest}")

# 矩陣 6：深度檢查搬到 `Popen` 之後 → `spawned` 計數轉非零。
def p312_main_fn(src: str):
    """受測 source 的 `main()` 節點。"""
    return next(n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.FunctionDef) and n.name == "main")


def p312_limit_ifs(src: str) -> list:
    """`main()` 內**條件式含 `MAX_RELAY_DEPTH`** 的那些 `if`（base `1aced94` 恰 1 個）。"""
    return [n for n in ast.walk(p312_main_fn(src))
            if isinstance(n, ast.If) and "MAX_RELAY_DEPTH" in ast.unparse(n.test)]


def p312_move_limit_check(src: str) -> str:
    """把深度檢查那一整塊搬到第一個 `_run_child` 之後（拒絕改為發生在派工之後）。

    行號由 AST 取，不寫死——搬到 `if args.then_wake:` 之前，故首棒已經派出去了。
    """
    lines = src.splitlines(keepends=True)
    main_fn = p312_main_fn(src)
    blk = p312_limit_ifs(src)[0]
    target = next(n for n in main_fn.body
                  if isinstance(n, ast.If) and ast.unparse(n.test) == "args.then_wake")
    block = lines[blk.lineno - 1:blk.end_lineno]
    rest = lines[:blk.lineno - 1] + lines[blk.end_lineno:]
    at = target.lineno - 1 - len(block)          # 區塊被切掉後，目標行上移同樣的行數
    return "".join(rest[:at] + block + rest[at:])


P312_MUT_LATE = p312_move_limit_check(RELAY_SRC)
_f6 = FakeSub(LINES)
_m6 = load_mutant(P312_MUT_LATE, "devflow_relay_mut_late", _f6)
_rc6, _, _ = with_env(P312_NEST_ENV, lambda: run_mod(_m6, ["4149", "hi"]))
check("#312 矩陣 6：深度檢查搬到 Popen 之後 → spawned 轉非零，AC-4 的哨兵條件不成立（實跑對照）",
      P312_MUT_LATE != RELAY_SRC and len(_f6.spawned) >= 1 and _rc6 == 2,
      f"突變 spawned={len(_f6.spawned)} rc={_rc6}；正確實作 spawned={len(f312_nest.spawned)}")

# ── AC-5：判準不是 profile 名 ───────────────────────────────────────────────
# (a) 真遞迴 `coder → (primary) coder`：正確實作下子程序達上限、那一層被拒；
#     以 profile 名去重的突變下深度停在 '2'，同一情境被放行。兩者輸出不同。
P312_CODER_ENV = {DEPTH_KEY: "2", CHAIN_KEY: "dfmgr,dfimpl"}
p312_rec = with_env(P312_CODER_ENV, lambda: m312._child_env("dfimpl"))
_f7 = FakeSub(LINES)
_m7 = load_mutant(P312_MUT_DEDUP, "devflow_relay_mut_dedup", _f7)
p312_rec_mut = with_env(P312_CODER_ENV, lambda: _m7._child_env("dfimpl"))
f312_rec = FakeSub(LINES)
rc312_rec, _, _ = with_env({DEPTH_KEY: p312_rec[DEPTH_KEY], CHAIN_KEY: p312_rec[CHAIN_KEY]},
                           lambda: run(["4149", "hi"], f312_rec))
_rc7, _, _ = with_env({DEPTH_KEY: p312_rec_mut[DEPTH_KEY],
                       CHAIN_KEY: p312_rec_mut[CHAIN_KEY]},
                      lambda: run_mod(_m7, ["4149", "hi"]))
check("#312 AC-5(c) 同一 profile 的 primary 疊加（真遞迴）→ 子程序達上限、該層被拒",
      p312_rec[DEPTH_KEY] == str(P312_MAX) and rc312_rec not in (0, None)
      and len(f312_rec.spawned) == 0,
      f"深度={p312_rec[DEPTH_KEY]!r} rc={rc312_rec} spawned={f312_rec.spawned}")
check("#312 AC-5(a) 矩陣 7：以 profile 名去重的突變實跑 → 同一個真遞迴深度停在 '2' 且被放行",
      p312_rec_mut[DEPTH_KEY] == "2" and _rc7 == 0 and len(_f7.spawned) == 1,
      f"突變深度={p312_rec_mut[DEPTH_KEY]!r} rc={_rc7} spawned={len(_f7.spawned)}")
check("#312 AC-5(a) 兩者輸出不同（放行 vs 拒絕）→ 判準不得用 profile 名",
      (p312_rec_mut[DEPTH_KEY], _rc7) != (p312_rec[DEPTH_KEY], rc312_rec)
      and _rc7 == 0 and rc312_rec not in (0, None),
      f"突變=(深度 {p312_rec_mut[DEPTH_KEY]!r}, rc {_rc7})；"
      f"正確=(深度 {p312_rec[DEPTH_KEY]!r}, rc {rc312_rec})")

# (b) 跨 profile 的 continuation：放行、不 +1，停在呼叫者自身那一層（不是祖先層）。
f312_cross = FakeSub(LINES)
rc312_cross, _, _ = with_env(
    P312_CODER_ENV,
    lambda: run(["4149", "hi", "-p", "dfimpl", "--issue", "312", "--then-wake", "dfmgr"],
                f312_cross))
_cross_cont = f312_cross.kwargs[1].get("env", {}) if len(f312_cross.kwargs) > 1 else {}
check("#312 AC-5(b) 跨 profile 的 continuation 放行且不 +1：深度 ＝ 呼叫者自身那一層（'2'）",
      rc312_cross == 0 and len(f312_cross.spawned) == 2
      and _cross_cont.get(DEPTH_KEY) == "2",
      f"rc={rc312_cross} spawned={len(f312_cross.spawned)} "
      f"喚醒者深度={_cross_cont.get(DEPTH_KEY)!r}")
check("#312 AC-5(b) 它停在呼叫者那一層，≠ 祖先 manager 的 '1'（只是不增深）",
      _cross_cont.get(DEPTH_KEY) != "1" and _cross_cont.get(DEPTH_KEY) == "2"
      and _cross_cont.get(CHAIN_KEY) == "dfmgr,dfimpl>dfmgr",
      f"喚醒者深度={_cross_cont.get(DEPTH_KEY)!r} 鏈={_cross_cont.get(CHAIN_KEY)!r}")

# 矩陣 8：把跨 profile 的 then-wake 當成 primary（+1）→ AC-5(b) 的期望值不成立。
_f8 = FakeSub(LINES)
_m8 = load_mutant(P312_MUT_CROSS, "devflow_relay_mut_cross", _f8)
with_env(P312_CODER_ENV,
         lambda: run_mod(_m8, ["4149", "hi", "-p", "dfimpl", "--issue", "312",
                               "--then-wake", "dfmgr"]))
_m8_cont = _f8.kwargs[1].get("env", {}) if len(_f8.kwargs) > 1 else {}
check("#312 矩陣 8：跨 profile 的續接被當成 primary 的突變下，喚醒者得 '3' ≠ AC-5(b) 的 '2'",
      _m8_cont.get(DEPTH_KEY) == "3"
      and _m8_cont.get(DEPTH_KEY) != _cross_cont.get(DEPTH_KEY),
      f"突變={_m8_cont.get(DEPTH_KEY)!r} 正確={_cross_cont.get(DEPTH_KEY)!r}")

# (d) 射程收窄：純 continuation 的平層循環不增深，本單**不保證**擋住它（`#313` 的材料）。
#     以下不是「已修好」的證據，是把已知限制釘住：50 次純續接後深度仍為呼叫者那一層。
p312_flat = dict(P312_CALLER)
for _i in range(50):
    _nx = with_env(p312_flat, lambda: m312._child_env("dfmgr", continuation=True))
    p312_flat = {DEPTH_KEY: _nx[DEPTH_KEY], CHAIN_KEY: _nx[CHAIN_KEY]}
check("#312 AC-5(d) 已知限制：50 次純 continuation 後深度仍為 '1'（平層循環不增深，故上限擋不到它）",
      p312_flat[DEPTH_KEY] == "1" and p312_flat[CHAIN_KEY].count(">") == 50,
      f"深度={p312_flat[DEPTH_KEY]!r} 鏈長={len(p312_flat[CHAIN_KEY])}")
check("#312 AC-5(d) 超限訊息逐字載明該限制（不假稱已修好）",
      P312_LIMIT_SENTENCE in err312_over, repr(err312_over[-400:]))

# 矩陣 11 的訊息側：刪掉說明 → 同一條判定轉為不成立。
_f11 = FakeSub(LINES)
_m11 = load_mutant(P312_MUT_NOSCOPE, "devflow_relay_mut_noscope", _f11)
_rc11, _, _err11 = with_env({DEPTH_KEY: str(P312_MAX), CHAIN_KEY: P312_MIXED_CHAIN},
                            lambda: run_mod(_m11, ["4149", "hi"]))
check("#312 矩陣 11（訊息側）：刪掉射程說明的突變下，同一條判定轉為不成立（實跑對照）",
      P312_LIMIT_SENTENCE not in _err11 and P312_LIMIT_SENTENCE in err312_over
      and _rc11 == 2,
      f"突變訊息尾={_err11[-200:]!r}")

# ── AC-6：既有行為、無旁路開關（局部檢查）────────────────────────────────────
print("\n── #312 AC-6：既有判準與無旁路開關（AST 局部檢查）")

# (a) 上限的值與「字面只出現一次」由上方 AC-4 兩條既有斷言守著（維持 PASS）。
#     矩陣 9 以突變對照：改大之後那兩條的期望值都不成立。
_m9 = load_mutant(P312_MUT_BIGGER, "devflow_relay_mut_bigger", FakeSub(LINES))
check("#312 矩陣 9：上限被改大的突變下，常數值與字面計數兩條的期望值皆轉為不成立（實跑對照）",
      _m9.MAX_RELAY_DEPTH != P312_MAX
      and len(re.findall(r"^MAX_RELAY_DEPTH\s*=\s*3$", P312_MUT_BIGGER, re.M)) == 0
      and len(re.findall(r"^MAX_RELAY_DEPTH\s*=\s*3$", RELAY_SRC, re.M)) == 1,
      f"突變值={_m9.MAX_RELAY_DEPTH!r} 受測值={P312_MAX!r}")


def p312_limit_probe(src: str) -> tuple[int, list[str], bool]:
    """AC-6(c) 的那一支檢查（正例與反例共用）。

    回傳 (命中的 `if` 個數, 條件式子樹內的環境讀取清單, 條件式是否只由 `depth` 與
    `MAX_RELAY_DEPTH` 的比較構成)。環境讀取的判法：`ast.walk` 找 `Call`，其
    `ast.unparse` 含 `environ`。

    ⚠️ **偵測射程（如實，不得誇大，T `AC-6(c)` 四點）**：
      1. 本檢查**只**覆蓋「**該 `if` 的條件式裡**多了環境讀取或布林旁路」這一形狀。
      2. 它**不保證抓到別處的旁路**——例如在 `main()` 更前面插入
         `if os.environ.get(...): return 0`，或在 `_child_env`／`_current_depth` 裡動手。
      3. 行為測試（`depth=3` 應拒絕）**只有在突變路徑被激活時才抓得到**：未設該開關跑的
         `depth=3` 測試不足以保證擋住「有開關才提前 return」的實作——開關未設時那個實作
         與正確實作行為相同（本節下方以突變實跑證明這一點）。
      4. 故本單的保證是「對條件式被加上旁路這一形狀有正反測試」（矩陣第 10 列），
         **不是**「全檔語意上沒有任何旁路」。要覆蓋任意位置的旁路需要另一種檢查
         （例如對所有提前 `return` 的路徑做可達性分析），不在本單射程。
    """
    ifs = p312_limit_ifs(src)
    if len(ifs) != 1:
        return len(ifs), [], False
    test = ifs[0].test
    envs = [ast.unparse(c) for c in ast.walk(test)
            if isinstance(c, ast.Call) and "environ" in ast.unparse(c)]
    names = sorted({n.id for n in ast.walk(test) if isinstance(n, ast.Name)})
    shape = isinstance(test, ast.Compare) and names == ["MAX_RELAY_DEPTH", "depth"]
    return len(ifs), envs, shape


p312_hits, p312_envs, p312_shape = p312_limit_probe(RELAY_SRC)
check("#312 AC-6(c) main() 內條件式含 MAX_RELAY_DEPTH 的 if 恰一個（檢查位置唯一）",
      p312_hits == 1, f"命中個數={p312_hits}")
check("#312 AC-6(c) 該條件式的子樹裡一個環境讀取都沒有（ast.walk 找 Call、unparse 含 environ）",
      p312_envs == [], f"命中的環境讀取={p312_envs!r}")
check("#312 AC-6(c) 該條件式只由 depth 與 MAX_RELAY_DEPTH 的比較構成",
      p312_shape, f"命中的 Name={sorted({n.id for n in ast.walk(p312_limit_ifs(RELAY_SRC)[0].test) if isinstance(n, ast.Name)})!r}")

_h10, _e10, _s10 = p312_limit_probe(P312_MUT_BYPASS)
check("#312 矩陣 10：條件式加上 `and not os.environ.get(...)` → 同一支檢查命中環境讀取",
      _h10 == 1 and len(_e10) >= 1 and "RELAY_NO_DEPTH" in " ".join(_e10) and not _s10,
      f"突變命中={_e10!r} 形狀={_s10}")
# 射程第 3 點的實證：開關未設時，突變與正確實作的行為相同——行為測試抓不到它。
_fb = FakeSub(LINES)
_mb = load_mutant(P312_MUT_BYPASS, "devflow_relay_mut_bypass", _fb)
_rcb, _, _ = with_env({DEPTH_KEY: str(P312_MAX), CHAIN_KEY: P312_MIXED_CHAIN,
                       "RELAY_NO_DEPTH": None},
                      lambda: run_mod(_mb, ["4149", "hi"]))
check("#312 AC-6(c) 射程：開關未設時該突變的行為與正確實作相同（故只有 AST 檢查抓得到它）",
      _rcb == 2 and len(_fb.spawned) == 0 and rc312_nest not in (0, None)
      and len(_e10) >= 1,
      f"突變 rc={_rcb} spawned={len(_fb.spawned)}；AST 命中={_e10!r}")

# (d) relay 只寫**子程序環境的複本**：源碼裡一個 `os.environ[...]` 賦值都沒有，
#     兩個鍵的寫入都落在 `_child_env` 內。
_p312_tree = ast.parse(RELAY_SRC)
_p312_env_assigns = [ast.unparse(t) for n in ast.walk(_p312_tree)
                     if isinstance(n, (ast.Assign, ast.AugAssign))
                     for t in (n.targets if isinstance(n, ast.Assign) else [n.target])
                     if ast.unparse(t).startswith("os.environ")]
_p312_child_fn = next(n for n in ast.walk(_p312_tree)
                      if isinstance(n, ast.FunctionDef) and n.name == "_child_env")
_p312_key_assigns = [ast.unparse(t) for n in ast.walk(_p312_tree)
                     if isinstance(n, ast.Assign) for t in n.targets
                     if ast.unparse(t) in ("env[DEPTH_ENV]", "env[CHAIN_ENV]")]
_p312_key_in_child = [ast.unparse(t) for n in ast.walk(_p312_child_fn)
                      if isinstance(n, ast.Assign) for t in n.targets
                      if ast.unparse(t) in ("env[DEPTH_ENV]", "env[CHAIN_ENV]")]
check("#312 AC-6(d) 源碼裡一個 `os.environ[...]` 賦值都沒有（relay 不改自己的程序環境）",
      _p312_env_assigns == [], f"命中={_p312_env_assigns!r}")
check("#312 AC-6(d) 兩個鍵的寫入都落在 `_child_env` 內（寫的是子程序環境的複本）",
      sorted(_p312_key_assigns) == sorted(_p312_key_in_child)
      and sorted(_p312_key_in_child) == ["env[CHAIN_ENV]", "env[DEPTH_ENV]"],
      f"全檔={_p312_key_assigns!r} `_child_env` 內={_p312_key_in_child!r}")
check("#312 AC-6(d) 深度與鏈的鍵名沿用既有兩個（沒有第三個 DEVFLOW_RELAY_* 深度鍵）",
      m312.DEPTH_ENV == "DEVFLOW_RELAY_DEPTH" and m312.CHAIN_ENV == "DEVFLOW_RELAY_CHAIN"
      and sorted(re.findall(r'"(DEVFLOW_RELAY_[A-Z]+)"', RELAY_SRC))
      == ["DEVFLOW_RELAY_CHAIN", "DEVFLOW_RELAY_DEPTH"],
      f"命中={sorted(re.findall(r'(DEVFLOW_RELAY_[A-Z]+)', RELAY_SRC))!r}")

# ── AC-7：`telegram.md` 的「子程序退出後的銜接」格 ──────────────────────────
print("\n── #312 AC-7：telegram.md 的格與 R9 狀態")

TG312 = TELEGRAM_MD.read_text()
TG312_ROW = next((ln for ln in TG312.splitlines()
                  if ln.startswith("| 子程序退出後的銜接")), "")
TG312_VALUE, TG312_STATUS = (TG312_ROW.split(" | ")[2:4] + ["", ""])[:2]

# 該格須載明的字面（正向、位置斷言：切出那一列再比對，不用全檔禁詞）。
P312_DOC_NEEDLES = (
    "primary",
    "continuation",
    "呼叫者自身",
    "`,` ＝巢狀一層",
    "`>` ＝同一流程的續接",
    P312_LEADING_SENTENCE,
    P312_LIMIT_SENTENCE,
    "只覆蓋「該 `if` 的條件式裡多了環境讀取或布林旁路」這一形狀",
    "不保證抓到別處的旁路",
    "未設該開關跑的 `depth=3` 行為測試",
    "不是全檔語意保證",
)


def p312_doc_ok(row: str) -> list[str]:
    """該格缺了哪些必載字面（空清單＝都在）。正例與反例共用同一支。"""
    return [n for n in P312_DOC_NEEDLES if n not in row]


check("#312 AC-7 該格載明 primary／continuation 的區別、`,`／`>` 的讀法與兩段射程（逐項命中）",
      p312_doc_ok(TG312_ROW) == [], f"缺={p312_doc_ok(TG312_ROW)!r}")
check("#312 AC-7 值欄的深度宣稱與實作一致（續接承襲呼叫者自身那一層、不增深）",
      "承襲**呼叫者自身**的深度" in TG312_VALUE and "不增深" in TG312_VALUE,
      repr(TG312_VALUE[-600:]))
check("#312 AC-7 該格以「不增深」描述跨 profile 的續接，沒有「回到外層／退回祖先層」的說法",
      "回到外層" not in TG312_ROW and "退回祖先層" not in TG312_ROW
      and "不增深" in TG312_VALUE and "不是祖先 manager 的 `1`" in TG312_VALUE,
      f"值欄尾={TG312_VALUE[-300:]!r}")
check("#312 AC-7 `R9` 狀態欄為 `📝 已宣稱` 並標明子類（程式層正反測試，不逕標 `✅`）",
      TG312_STATUS.startswith("📝 已宣稱") and "驗證未達 `✅`" in TG312_STATUS,
      f"狀態欄開頭={TG312_STATUS[:120]!r}")
check("#312 AC-7 既有的 `#298` 驗證方式與受測環境記載仍在（`R9`：不得刪去）",
      "tests/channels/test_relay.py" in TG312_STATUS and "2026-10-07" in TG312_STATUS
      and "7bb4cb4" in TG312_STATUS and "298" in TG312_STATUS,
      repr(TG312_STATUS[:300]))
check("#312 AC-7 受測環境（`R10`）記載更新為本次（日期、base、worktree）",
      "2026-10-15" in TG312_STATUS and "1aced94" in TG312_STATUS
      and "worktree `312`" in TG312_STATUS, repr(TG312_STATUS[-500:]))

# 矩陣 11 的文件側：刪掉射程說明 → 同一支判定轉為不成立。
_row11 = TG312_ROW.replace(P312_LIMIT_SENTENCE, "")
check("#312 矩陣 11（文件側）：刪掉該說明後，同一支判定報出缺漏（實跑對照）",
      p312_doc_ok(_row11) == [P312_LIMIT_SENTENCE] and p312_doc_ok(TG312_ROW) == [],
      f"突變後缺={p312_doc_ok(_row11)!r}")

check("#312 AC-7 VERSION 為 `V2` 的 c 位進位（嚴格大於 0.18.0.0，整數元組比較）",
      tuple(int(x) for x in VERSION_FILE.read_text().strip().split(".")) > (0, 18, 0, 0),
      f"raw={VERSION_FILE.read_text().strip()!r}")


# ── AC-8：三條測試判準的修正（固定情境的正反測試）──────────────────────────────
# 第 3 輪 `R1` `BLOCK 1`：三條 check 以**字串**判斷路徑與單號，於是
#   * 審查位的暫存根取名為 repo 的兄弟目錄 `…/312-r3-tmp`（含 checkout 目錄名
#     `312-r3` 這個子字串）→ 兩條路徑判準誤判 log 寫進了 repo；
#   * 當次 PID `2528717` 含 `287` → 單號的鑑別力條誤判「檔名裡有 287」。
# 兩者都是**合法輸入**，缺陷在判準而不在 relay；修法是把判定換成路徑階層與 grammar
# 欄位（`_under`／`_issue_of`，見上方定義），三條 check 的標題與要驗的語意不動。
#
# 本節的情境**全部是固定字串／固定路徑**（`AC-8(c)`）：判定的輸入不含當次的 PID、暫存根
# 名稱或任何環境值，斷言也**不以當次 PID 或 fixture 是否存在作為額外的放行條件**，故
# 「修前必失敗、修後必通過」與跑在哪台機器、哪個 PID 無關——第 3 輪的 `234/237` 與
# manager 重跑的 `235/237` 差在當次 PID，那種 flake 在這裡不存在。
# ⚠️ `AC-8(g)`：本節對 I/O 面**不下宣稱**——判定本身（`_under`）會 `resolve()`，那是
# 正規化 symlink 與 `..` 的必要步驟；要說的只有「固定情境的結果只取決於階層判定，
# 不取決於那些路徑在不在」。
print("\n── #312 AC-8：log 路徑用階層判定、單號取 issue 欄位（固定情境）")

# 固定情境（形狀照第 3 輪的現場：暫存根是 repo 的**兄弟目錄**，名字以 repo 目錄名起首）。
# 路徑刻意落在一個現實中不會存在的根下，結果只取決於判定本身——`resolve()` 對不存在的
# 路徑一樣正規化得出來，故這些 fixture 存不存在都不改變下面任何一條的結果。
P312_FX_ROOT = Path("/fixture-312/agent-devflow.review")
P312_FX_REPO = P312_FX_ROOT / "312-r3"
P312_FX_TMP = P312_FX_ROOT / "312-r3-tmp"            # 兄弟目錄，名字含 `312-r3`
P312_FX_TMP2 = P312_FX_ROOT / "relay-scratch"        # 名字**不**含 repo 名的另一個暫存根
P312_FX_NAME_999 = "relay-999-dfmgr-20261015-051730-2528717-1.log"   # PID 含 `287`
P312_FX_NAME_287 = "relay-287-dfmgr-20261015-051730-2999999-1.log"   # PID 含 `999`
P312_FX_NAME_PLAIN = "relay-999-dfmgr-20261015-051730-1234561-1.log"  # PID 兩者皆不含
P312_FX_LOG = P312_FX_TMP / "devflow-test_relay.fixture" / P312_FX_NAME_999
P312_FX_LOG2 = P312_FX_TMP2 / "devflow-test_relay.fixture" / P312_FX_NAME_999
P312_FX_IN_REPO = P312_FX_REPO / "tests" / P312_FX_NAME_287      # 真的在 repo 內
P312_FX_OUTSIDE = Path("/fixture-312/elsewhere") / P312_FX_NAME_287  # 在暫存根外


def p312_old_path_ok(root, repo, path) -> bool:
    """修前的判定（字串前綴 ＋ 子字串），**只**在反例對照裡呼叫（矩陣 12）。

    逐字對應 head `43bb5a4` 的
    `str(lp).startswith(tempfile.gettempdir()) and str(REPO) not in str(lp)`。
    """
    return str(path).startswith(str(root)) and str(repo) not in str(path)


def p312_old_issue_ok(logname: str, want: str, other: str) -> bool:
    """修前的判定（對整個檔名做子字串搜尋），只在反例對照裡呼叫（矩陣 13／14）。

    逐字對應 head `43bb5a4` 的 `"999" in logs_c[0] and "287" not in logs_c[0]`。
    """
    return want in logname and other not in logname


# ── (a) 路徑：階層判定的三個固定情境 ─────────────────────────────────────────
check("#312 AC-8(a) 正例：log 落在 repo 的兄弟目錄（目錄名含 repo 名）→ 在暫存根下且不在 repo 內",
      _under(P312_FX_TMP, P312_FX_LOG) and not _under(P312_FX_REPO, P312_FX_LOG),
      f"log={P312_FX_LOG} tmp={P312_FX_TMP} repo={P312_FX_REPO}")
check("#312 AC-8(a) 反例：log 真正位於 repo 內 → 階層判定認得出來（該被擋）",
      _under(P312_FX_REPO, P312_FX_IN_REPO)
      and not (_under(P312_FX_TMP, P312_FX_IN_REPO)
               and not _under(P312_FX_REPO, P312_FX_IN_REPO)),
      f"log={P312_FX_IN_REPO}")
check("#312 AC-8(a) 反例：log 位於暫存根外 → 判定為不在暫存根下（該被擋）",
      not _under(P312_FX_TMP, P312_FX_OUTSIDE)
      and not _under(P312_FX_REPO, P312_FX_OUTSIDE),
      f"log={P312_FX_OUTSIDE}")
check("#312 AC-8(a) 判準是階層不是字串：同一組固定輸入下字串命中為真、階層判定為假",
      str(P312_FX_REPO) in str(P312_FX_LOG)
      and str(P312_FX_LOG).startswith(str(P312_FX_REPO))
      and not _under(P312_FX_REPO, P312_FX_LOG),
      f"子字串命中={str(P312_FX_REPO) in str(P312_FX_LOG)} "
      f"前綴命中={str(P312_FX_LOG).startswith(str(P312_FX_REPO))} "
      f"階層={_under(P312_FX_REPO, P312_FX_LOG)}")
check("#312 AC-8(a) `_under` 的邊界：root 自身算在其下、父目錄不算在子目錄下",
      _under(P312_FX_TMP, P312_FX_TMP) and not _under(P312_FX_LOG, P312_FX_TMP),
      "is_relative_to 的語意（含自身）")

# 矩陣 12：保留字串判定 → 同一組固定正例轉為不成立。
check("#312 矩陣 12：保留字串判定（startswith ＋ 子字串）→ 同一組固定正例轉為不成立（實跑對照）",
      p312_old_path_ok(P312_FX_TMP, P312_FX_REPO, P312_FX_LOG) is False
      and (_under(P312_FX_TMP, P312_FX_LOG)
           and not _under(P312_FX_REPO, P312_FX_LOG)) is True,
      f"舊判定={p312_old_path_ok(P312_FX_TMP, P312_FX_REPO, P312_FX_LOG)} "
      f"新判定={_under(P312_FX_TMP, P312_FX_LOG) and not _under(P312_FX_REPO, P312_FX_LOG)}")

# ── (b) 單號：只看 grammar 的 issue 欄位 ────────────────────────────────────
check("#312 AC-8(b) 正例：issue=999 而 PID 含 287 → issue 欄位取出 '999'",
      _issue_of(P312_FX_NAME_999) == "999", f"檔名={P312_FX_NAME_999}")
check("#312 AC-8(b) 鑑別力：單號寫死 287 的檔名（PID 含 999）→ 期望 issue=='999' 不成立",
      _issue_of(P312_FX_NAME_287) == "287" and _issue_of(P312_FX_NAME_287) != "999",
      f"檔名={P312_FX_NAME_287} issue 欄位={_issue_of(P312_FX_NAME_287)!r}")
_p312_fields = _LOG_NAME_RE.match(P312_FX_NAME_999)
check("#312 AC-8(b) 其餘欄位也切得開（profile／stamp／pid／seq 各就各位）",
      _p312_fields is not None and _p312_fields.groupdict()
      == {"issue": "999", "profile": "dfmgr", "stamp": "20261015-051730",
          "pid": "2528717", "seq": "1"},
      f"欄位={_p312_fields.groupdict() if _p312_fields else None}")
check("#312 AC-8(b) 帶目錄的路徑只看檔名那一段（目錄名裡的數字不影響單號）",
      _issue_of(str(P312_FX_LOG)) == "999" and _issue_of(str(P312_FX_IN_REPO)) == "287",
      f"{P312_FX_LOG} → {_issue_of(str(P312_FX_LOG))!r}")
check("#312 AC-8(b) 不合 grammar 的檔名回空字串（取不到欄位就不假裝取到）",
      _issue_of("relay-oops.log") == "" and _issue_of("whatever.txt") == "",
      "grammar 不合時不得猜")
# grammar 與 `_log_path` 的實際產出必須相符，否則上面那些固定情境只是自說自話：
# 真實檔名（AC-2 那一輪的 `--issue 287`，真時間戳）與 `BLOCK 1` 那一節（時鐘凍成
# `FIXED`）兩種形狀都要切得開——這也是 `_LOG_NAME_RE` 的 stamp 欄位容許 `FIXED` 的理由。
check("#312 AC-8(b) grammar 與 `_log_path` 的實際產出相符（真時間戳與凍結時鐘兩種形狀）",
      bool(log_paths) and _issue_of(Path(log_paths[0]).name) == "287"
      and isinstance(_p1, Path) and _issue_of(_p1.name) == "287",
      f"真實={Path(log_paths[0]).name if log_paths else None} "
      f"凍結={_p1.name if isinstance(_p1, Path) else _p1!r}")

# ── AC-9(a)(b)：profile 欄含連字號的合法 log ─────────────────────────────────
# 第 5 輪 `R1`：grammar 的 profile 欄原寫 `[^-]+`，比**產品**窄（`_log_path` 不禁
# profile 含 `-`、`HANDOFF_RE` 明文允許 `[A-Za-z0-9_.\-]+`），於是 `-p df-review` 這種
# **合法**派工產生的 log 被 `_issue_of` 判為「不合 grammar」而回 `''`。
# ⚠️ 定性（裁決位 2026-10-15）：那是**這個測試 helper 的問題，不是正式 relay 派工失敗**
# ——relay 的 `_log_path`／`HANDOFF_RE` 行為正確，缺陷不影響任何實際派工。
# 下面先以**手寫固定 fixture** 驗欄位，再以**產品實際產出的檔名**複驗（只呼叫純函式
# `_log_path`，不派任何子程序）。
P312_FX_HYPHEN_999 = "relay-999-df-review-20261015-051730-2528717-1.log"
P312_FX_HYPHEN_FIXED = "relay-999-df-review-FIXED-2528717-1.log"
P312_FX_HYPHEN_287 = "relay-287-df-999-20261015-051730-2999999-1.log"
_p312_hy = _LOG_NAME_RE.match(P312_FX_HYPHEN_999)

check("#312 AC-9(b) 正例：profile 含連字號的合法 log 取出 issue='999'",
      _issue_of(P312_FX_HYPHEN_999) == "999",
      f"檔名={P312_FX_HYPHEN_999} issue 欄位={_issue_of(P312_FX_HYPHEN_999)!r}")
check("#312 AC-9(b) 正例：該檔名的欄位逐項切對（profile 為 `df-review`，pid／seq 不被吃掉）",
      _p312_hy is not None and _p312_hy.groupdict()
      == {"issue": "999", "profile": "df-review", "stamp": "20261015-051730",
          "pid": "2528717", "seq": "1"},
      f"欄位={_p312_hy.groupdict() if _p312_hy else None}")
check("#312 AC-9(b) 正例：凍結時鐘（stamp 為 FIXED）＋ 連字號 profile 同樣取出 '999'",
      _issue_of(P312_FX_HYPHEN_FIXED) == "999",
      f"檔名={P312_FX_HYPHEN_FIXED} issue 欄位={_issue_of(P312_FX_HYPHEN_FIXED)!r}")
check("#312 AC-9(b) 反例：issue=287 而 profile 與 PID 都含 999 → 仍取出 '287'",
      _issue_of(P312_FX_HYPHEN_287) == "287" and _issue_of(P312_FX_HYPHEN_287) != "999",
      f"檔名={P312_FX_HYPHEN_287} issue 欄位={_issue_of(P312_FX_HYPHEN_287)!r}")
_p312_hy287 = _LOG_NAME_RE.match(P312_FX_HYPHEN_287)
check("#312 AC-9(b) 反例：該檔名的 `999` 落在 profile 與 pid 兩欄，不在 issue 欄",
      _p312_hy287 is not None
      and _p312_hy287.group("profile") == "df-999"
      and _p312_hy287.group("pid") == "2999999"
      and _p312_hy287.group("issue") == "287",
      f"欄位={_p312_hy287.groupdict() if _p312_hy287 else None}")
check("#312 AC-9(b) 不合 grammar 的輸入仍回空字串（缺欄位／副檔名錯／前綴缺）",
      _issue_of("relay-999-df-review-20261015-051730-1.log") == ""
      and _issue_of("relay-999-df-review-20261015-051730-2528717-1.txt") == ""
      and _issue_of("999-df-review-20261015-051730-2528717-1.log") == ""
      and _issue_of("relay-999-df-review-2026xx15-051730-2528717-1.log") == "",
      "四種殘缺輸入都不得被當成合法 grammar")
# 產品實際產出的檔名複驗（`_log_path` 是純函式：只組路徑，不建檔、不派子程序）。
_p312_prod_hy = m312._log_path("999", "df-review")
_p312_prod_287 = m312._log_path("287", "df-999")
check("#312 AC-9(b) 產品輸出複驗：`_log_path('999','df-review')` 的檔名取出 '999'",
      _issue_of(_p312_prod_hy.name) == "999",
      f"產出={_p312_prod_hy.name} issue 欄位={_issue_of(_p312_prod_hy.name)!r}")
check("#312 AC-9(b) 產品輸出複驗：`_log_path('287','df-999')` 的檔名取出 '287'",
      _issue_of(_p312_prod_287.name) == "287"
      and _issue_of(_p312_prod_287.name) != "999",
      f"產出={_p312_prod_287.name} issue 欄位={_issue_of(_p312_prod_287.name)!r}")
_p312_prod_m = _LOG_NAME_RE.match(_p312_prod_hy.name)
_p312_prod_m287 = _LOG_NAME_RE.match(_p312_prod_287.name)
check("#312 AC-9(b) 產品輸出複驗：連字號 profile 在 profile 欄被完整取回",
      _p312_prod_m is not None and _p312_prod_m287 is not None
      and _p312_prod_m.group("profile") == "df-review"
      and _p312_prod_m287.group("profile") == "df-999",
      f"{_p312_prod_hy.name} / {_p312_prod_287.name}")

# 矩陣 13：保留整個檔名的子字串搜尋 → 同一組固定正例轉為不成立。
check("#312 矩陣 13：保留整個檔名的子字串搜尋 → issue=999 而 PID 含 287 的正例轉為不成立（實跑對照）",
      p312_old_issue_ok(P312_FX_NAME_999, "999", "287") is False
      and _issue_of(P312_FX_NAME_999) == "999",
      f"舊判定={p312_old_issue_ok(P312_FX_NAME_999, '999', '287')} "
      f"新判定={_issue_of(P312_FX_NAME_999)!r}")

# ── (c) 回歸不依賴碰巧的 PID 與暫存根名稱 ──────────────────────────────────
# 矩陣 14：把固定情境換回「當次真實的 PID」→ 結果隨 PID 變動（flake 可被觀測）。
check("#312 矩陣 14：舊判定對兩個只差 PID 的固定檔名給出不同結果（flake 的來源）",
      p312_old_issue_ok(P312_FX_NAME_999, "999", "287") is False
      and p312_old_issue_ok(P312_FX_NAME_PLAIN, "999", "287") is True,
      f"PID 含 287={p312_old_issue_ok(P312_FX_NAME_999, '999', '287')} "
      f"PID 不含={p312_old_issue_ok(P312_FX_NAME_PLAIN, '999', '287')}")
check("#312 AC-8(c) 新判定對同兩個固定檔名給出相同結果（與當次 PID 無關）",
      _issue_of(P312_FX_NAME_999) == _issue_of(P312_FX_NAME_PLAIN) == "999",
      f"{_issue_of(P312_FX_NAME_999)!r} vs {_issue_of(P312_FX_NAME_PLAIN)!r}")
check("#312 AC-8(c) 新判定對兩個暫存根（名字含 repo 名／不含）給出相同結果",
      (_under(P312_FX_TMP, P312_FX_LOG) and not _under(P312_FX_REPO, P312_FX_LOG))
      == (_under(P312_FX_TMP2, P312_FX_LOG2) and not _under(P312_FX_REPO, P312_FX_LOG2))
      is True,
      f"含 repo 名的暫存根={P312_FX_TMP} 另一個={P312_FX_TMP2}")
check("#312 矩陣 14 對照：舊判定對那兩個暫存根給出不同結果（名字取得好不好決定成敗）",
      p312_old_path_ok(P312_FX_TMP, P312_FX_REPO, P312_FX_LOG) is False
      and p312_old_path_ok(P312_FX_TMP2, P312_FX_REPO, P312_FX_LOG2) is True,
      f"含 repo 名={p312_old_path_ok(P312_FX_TMP, P312_FX_REPO, P312_FX_LOG)} "
      f"不含={p312_old_path_ok(P312_FX_TMP2, P312_FX_REPO, P312_FX_LOG2)}")
# ── 此處原有一條（`#312` `AC-8(e)`，已移除）────────────────────────────────────
#    「`#312 AC-8(c)` 本節情境全為固定值：判定與當次 PID、暫存根、檔案系統狀態無關」，
#    斷言式為 `P312_FX_NAME_999.endswith(…) and str(os.getpid()) not in … and
#    not P312_FX_LOG.exists() and not P312_FX_REPO.exists()`。
#
# 1. **它不是功能判準**：上面每一條固定情境的斷言都已經自己證明了判定的行為；這條只是
#    對「本節與環境無關」下了一個**關於本節的**宣稱（meta）。
# 2. **而且它自己是本節唯一環境相依的斷言**：讀當次的 `os.getpid()`、讀兩個 fixture 路徑
#    的 `.exists()`，等於要求「當次 PID 不得撞到固定字串」與「`/fixture-312/…` 必須不
#    存在」。那正是 `AC-8(c)` 要消除的那種依賴——它重造了 flake。
#    實測（第 4 輪 `R1`，head `fb8d80f`）：`os.getpid` 固定為 `287` 時該條轉 FAIL
#    （`254/255`、rc 1）；把 `/fixture-312/` 前綴的 `Path.exists` 固定回 `True` 時同樣
#    FAIL（`254/255`、rc 1）。
# 3. **處置與出處**：裁決位 2026-10-15 授權**移除**（T `AC-8(e)`），
#    https://github.com/AugustusHsu/agent-devflow/issues/312
#    **僅這一條**；`AC-8(a)(b)(c)(d)` 的三條原功能判準、`_under`／`_issue_of`、固定情境
#    的正反測試與矩陣 12～14 的對照一律保留。亦**不**改寫成「常數互比」之類的替代斷言
#    來維持原本的總數——總數依實跑記載。
# 4. **為何刪而非改寫**（`test_marker.py` 檔頂 `AC-1`(c)）：意圖本身已失效——「本節與
#    環境無關」這件事由**情境本身是固定值**達成（固定字串、固定路徑），由一條讀環境的
#    斷言來「宣稱」它，方向相反。固定性在上方的常數定義處即可讀到。

# 三條標的 check 在實機上的同一組判定（路徑來自真實的 `_log_path`，判定共用 `_under`）：
# 上方 `AC-2 log 落在 $TMPDIR 下，不寫進 repo`、`AC-2 鑑別力：--issue 999 …`、
# `BLOCK 1 仍落在 $TMPDIR 下，不寫進 repo` 已改用這兩個純函式，故本節的固定情境與
# 它們是同一支判定——AC-8 的驗證命令（`TMPDIR=<含 repo 目錄名的兄弟目錄>`）即其端到端證據。


# ════════════════════════════════════════════════════════════════════════════
# `#313`／K4c-9 `AC-5`：終態投遞的入口邊界（`--handback-event`）
# ════════════════════════════════════════════════════════════════════════════
# 為什麼補在本檔而不是 `test_handback.py`：驗的是 `main()` 的入口行為，與既有三條拒絕
# （`--issue` 缺 `--then-wake`、深度上限）同一支，正例與反例共用同一個驅動 `run_mod`
# （`I5`——分檔會讓這四個入口組合各自長一套夾具）。協定本體的 `AC-1`～`AC-4`／`AC-6`
# 在 `tests/channels/test_handback.py`。
#
# ⚠️ **既有普通模式的功能判準一律保留**：本節**只新增**，上方 `AC-3`／`AC-4` 與
# `#312` 各節一字未動——`--handback-event` 是**新增的例外入口**，不是放寬既有防護。
print("\n── #313 AC-5：`--handback-event` 是終態投遞的唯一例外入口")

P313_EID = HB_EID
# 終態投遞的失敗出口會寫待處理紀錄到 `pathlib.Path.home()`——測試一律把 `HOME` 指到本檔
# 的暫存目錄，**不碰真的 `~/.hermes/profiles/`**（那是活體 profile，`C3`）。
P313_HOME = TESTTMP / "home"


def hb_env(depth=None, chain=None) -> dict[str, str | None]:
    """終態投遞案例的環境：深度／鏈 ＋ 假 HOME。"""
    return {DEPTH_KEY: depth, CHAIN_KEY: chain, "HOME": str(P313_HOME)}


# (a) 普通 `--issue` 呼叫**仍須** `--then-wake`：不帶新旗標時，行為與 base 完全相同。
f313a = FakeSub(LINES)
rc313a, _, err313a = run(["4149", "hi", "--issue", "313"], f313a)
check("#313 AC-5(a) 普通 `--issue` 仍須 --then-wake → rc 2、零子程序（新模式沒有放寬它）",
      rc313a == 2 and len(f313a.spawned) == 0 and "--then-wake" in err313a,
      f"rc={rc313a} spawned={len(f313a.spawned)} err={err313a[:200]!r}")
check("#313 AC-5(a) 拒絕訊息同時指出終態投遞的例外形式（可照抄）",
      "--handback-event" in err313a and "devflow_relay.py" in err313a,
      f"err={err313a[:300]!r}")
# 判準不是 profile 名：把 profile 換成接收端自己也**不**豁免（不依 profile 名猜意圖）。
f313a2 = FakeSub(LINES)
rc313a2, _, _ = run(["4149", "hi", "-p", "dfcoord", "--issue", "313"], f313a2)
check("#313 AC-5(a) 判準不是 profile 名：`-p dfcoord --issue` 無旗標時同樣 rc 2、零子程序",
      rc313a2 == 2 and len(f313a2.spawned) == 0,
      f"rc={rc313a2} spawned={len(f313a2.spawned)}")

# (b) `--issue --handback-event <EID>`：放行，派 1 個子程序，且它是 continuation。
f313b = FakeSub(LINES)
rc313b, _, err313b = with_env(
    hb_env("1", "dfmgr"),
    lambda: run(["4149", "hi", "-p", "dfcoord", "--issue", "313",
                 "--handback-event", P313_EID], f313b))
check("#313 AC-5(b) `--issue --handback-event` → 放行且恰派 1 個子程序（它之後沒有下一棒）",
      rc313b == 0 and len(f313b.spawned) == 1,
      f"rc={rc313b} spawned={len(f313b.spawned)} err={err313b[:200]!r}")
check("#313 AC-5(b) 該子程序以 continuation 啟動：env 深度 ＝ **呼叫者自身**（1 → '1'，不 +1）",
      bool(f313b.kwargs) and f313b.kwargs[0].get("env", {}).get(DEPTH_KEY) == "1",
      f"depth={f313b.kwargs[0].get('env', {}).get(DEPTH_KEY) if f313b.kwargs else None!r}")
check("#313 AC-5(b) 鏈以 `>` 接（續接，與 primary 的 `,` 機械可區分）",
      bool(f313b.kwargs)
      and f313b.kwargs[0].get("env", {}).get(CHAIN_KEY) == "dfmgr>dfcoord",
      f"chain={f313b.kwargs[0].get('env', {}).get(CHAIN_KEY) if f313b.kwargs else None!r}")
check("#313 AC-5(b) session 仍 `issue-313`（同一張單累積 context，不給 --fresh）",
      len(f313b.spawned) == 1 and "-c" in f313b.spawned[0]
      and f313b.spawned[0][f313b.spawned[0].index("-c") + 1] == "issue-313",
      f"spawned[0]={f313b.spawned[0] if f313b.spawned else None}")
check("#313 AC-5(b) handoff 行的時機不受影響：無 `--then-wake` ＝ **零 `gh issue comment`**"
      "（`#300` 的條件不變；`gh issue view` 是 `#313` 新增的層1／層3 讀回，不是寫 forge）",
      f313b.gh_comment_calls == [] and len(f313b.gh_view_calls) == 2
      and all(c[1:3] == ["issue", "view"] for c in f313b.gh_calls),
      f"comment={f313b.gh_comment_calls!r} view={len(f313b.gh_view_calls)}")
# 最外層（呼叫者的 CHAIN 未設）：continuation 仍保留起首的 `>`（`#312` `BLOCK 1` 的邊界）。
f313b2 = FakeSub(LINES)
with_env(hb_env(),
         lambda: run(["4149", "hi", "-p", "dfcoord", "--issue", "313",
                      "--handback-event", P313_EID], f313b2))
check("#313 AC-5(b) 最外層時深度 '0'、鏈 `>dfcoord`（起首的 `>` ＝ 最外層那一層即為續接）",
      bool(f313b2.kwargs)
      and f313b2.kwargs[0].get("env", {}).get(DEPTH_KEY) == "0"
      and f313b2.kwargs[0].get("env", {}).get(CHAIN_KEY) == ">dfcoord",
      f"env={{{DEPTH_KEY}: {f313b2.kwargs[0].get('env', {}).get(DEPTH_KEY)!r}, "
      f"{CHAIN_KEY}: {f313b2.kwargs[0].get('env', {}).get(CHAIN_KEY)!r}}}"
      if f313b2.kwargs else "kwargs 空")

# (c) 互斥：與 `--then-wake` 同時出現須拒絕，**且不得先派出子程序**。
f313c = FakeSub(LINES)
rc313c, _, err313c = run(["4149", "hi", "--issue", "313",
                          "--handback-event", P313_EID, "--then-wake", "dfmgr"], f313c)
check("#313 AC-5(c) `--handback-event` ＋ `--then-wake` → rc 2",
      rc313c == 2, f"rc={rc313c} err={err313c[:200]!r}")
check("#313 AC-5(c) 且 `len(spawned) == 0`——拒絕在派子程序之前（哨兵反證 Popen 未被呼叫）",
      len(f313c.spawned) == 0, f"spawned={f313c.spawned}")
check("#313 AC-5(c) 拒絕訊息指出互斥的兩個旗標與其理由（最後一棒之後沒有下一棒）",
      "--handback-event" in err313c and "--then-wake" in err313c
      and "互斥" in err313c, f"err={err313c[:300]!r}")
check("#313 AC-5(c) 拒絕是純本機的：連一則 Telegram 訊息、一個 gh 呼叫都沒有",
      f313c.sent == [], f"sent={f313c.sent!r}")
# 不帶 `--issue` 的互斥組合同樣拒絕（互斥不以 `--issue` 為前提）。
f313c2 = FakeSub(LINES)
rc313c2, _, _ = run(["4149", "hi", "--handback-event", P313_EID,
                     "--then-wake", "dfmgr"], f313c2)
check("#313 AC-5(c) 無 `--issue` 的互斥組合同樣 rc 2、零子程序",
      rc313c2 == 2 and len(f313c2.spawned) == 0,
      f"rc={rc313c2} spawned={len(f313c2.spawned)}")

# (d) 深度防護沿用既有判準：continuation 不增深 ≠ 任何深度都能啟動。
f313d = FakeSub(LINES)
rc313d, _, err313d = with_env(
    hb_env(str(P312_MAX), "dfmgr,dfimpl,dfmgr"),
    lambda: run(["4149", "hi", "-p", "dfcoord", "--issue", "313",
                 "--handback-event", P313_EID], f313d))
check("#313 AC-5(d) `DEPTH=3 --handback-event` → rc 2、零子程序（終態投遞不例外）",
      rc313d == 2 and len(f313d.spawned) == 0,
      f"rc={rc313d} spawned={len(f313d.spawned)} err={err313d[:200]!r}")
check("#313 AC-5(d) 超限訊息仍是既有那一份（鏈的讀法與射程說明都在，沒有為新模式刪弱）",
      P312_LIMIT_SENTENCE in err313d and P312_LEADING_SENTENCE in err313d
      and "dfmgr,dfimpl,dfmgr" in err313d and f"{DEPTH_KEY}={P312_MAX}" in err313d,
      f"err={err313d[-300:]!r}")
check("#313 AC-5(d) depth=2 的終態投遞仍放行（上限沒有被順手調嚴）",
      with_env(hb_env("2", "dfmgr,dfimpl"),
               lambda: run(["4149", "hi", "-p", "dfcoord", "--issue", "313",
                            "--handback-event", P313_EID], FakeSub(LINES)))[0] == 0,
      "depth=2 的終態投遞被擋掉")
# (e) 終態投遞必須指向某張單：沒有 `--issue` 就核不了層1（讀不到 forge）。
f313e = FakeSub(LINES)
rc313e, _, err313e = with_env(
    hb_env(), lambda: run(["4149", "hi", "-p", "dfcoord",
                           "--handback-event", P313_EID], f313e))
check("#313 AC-5(e) `--handback-event` 無 `--issue` → rc 2、零子程序（層1 無從核實）",
      rc313e == 2 and len(f313e.spawned) == 0 and "--issue" in err313e,
      f"rc={rc313e} spawned={len(f313e.spawned)} err={err313e[:200]!r}")

# ── 鑑別力：三種未達成候選，各自實跑並得到不同輸出 ──
P313_EXCL_IF = "    if args.handback_event and args.then_wake:\n"
P313_ISSUE_IF = "    if args.issue and not args.then_wake and not args.handback_event:\n"
P313_CONT_ARG = "                        continuation=bool(args.handback_event),\n"


def p313_move_excl_check(src: str) -> str:
    """把互斥檢查那一整塊搬到首棒 `_run_child` 之後（拒絕改為發生在派工之後）。

    手法同 `p312_move_limit_check`：行號由 AST 取、不寫死。落點取 `main()` 內**最後一個**
    `if args.handback_event:`（＝派子程序之後的層3 核對那塊）之前——搬到更前面的話它會落在
    `_run_child` 之前，就不是「派工之後才拒絕」這個未達成候選了。
    """
    lines = src.splitlines(keepends=True)
    main_fn = p312_main_fn(src)
    blk = next(n for n in main_fn.body
               if isinstance(n, ast.If)
               and ast.unparse(n.test) == "args.handback_event and args.then_wake")
    target = [n for n in main_fn.body
              if isinstance(n, ast.If) and ast.unparse(n.test) == "args.handback_event"][-1]
    block = lines[blk.lineno - 1:blk.end_lineno]
    rest = lines[:blk.lineno - 1] + lines[blk.end_lineno:]
    at = target.lineno - 1 - len(block)
    return "".join(rest[:at] + block + rest[at:])


P313_MUT_LATE = p313_move_excl_check(RELAY_SRC)
# 候選②：終態投遞仍以 primary 啟動（深度 +1）——「continuation 不增深」不成立。
P313_MUT_PRIMARY = p312_mutate(RELAY_SRC, P313_CONT_ARG,
                               "                        continuation=False,\n")
# 候選③：把例外擴及**任何** `--issue`（＝刪掉普通模式的 `--then-wake` 要求）。
P313_MUT_ANYISSUE = p312_mutate(RELAY_SRC, P313_ISSUE_IF, "    if False:\n")
check("#313 AC-5 三種突變確實套上（錨點各恰一處命中）",
      P313_MUT_LATE != RELAY_SRC and P313_MUT_PRIMARY != RELAY_SRC
      and P313_MUT_ANYISSUE != RELAY_SRC and P313_EXCL_IF in RELAY_SRC
      and RELAY_SRC.count(P313_EXCL_IF) == 1,
      "錨點漂移：某個突變沒有套上去（no-op 的反例會假 PASS）")

_f313m1 = FakeSub(LINES)
_m313a = load_mutant(P313_MUT_LATE, "devflow_relay_mut_hb_late", _f313m1)
_rc313m1, _, _ = with_env(hb_env(), lambda: run_mod(
    _m313a, ["4149", "hi", "--issue", "313",
             "--handback-event", P313_EID, "--then-wake", "dfmgr"]))
check("#313 AC-5(c) 反例①：互斥檢查搬到 Popen 之後 → spawned 轉非零（實跑對照）",
      len(_f313m1.spawned) >= 1 and _rc313m1 == 2 and len(f313c.spawned) == 0,
      f"突變 spawned={len(_f313m1.spawned)} rc={_rc313m1}；正確實作 spawned={len(f313c.spawned)}")

_f313m2 = FakeSub(LINES)
_m313b = load_mutant(P313_MUT_PRIMARY, "devflow_relay_mut_hb_primary", _f313m2)
with_env(hb_env("1", "dfmgr"),
         lambda: run_mod(_m313b, ["4149", "hi", "-p", "dfcoord", "--issue", "313",
                                  "--handback-event", P313_EID]))
check("#313 AC-5(b) 反例②：終態投遞仍以 primary 啟動 → 深度 '2'、鏈以 `,` 接（實跑對照）",
      bool(_f313m2.kwargs)
      and _f313m2.kwargs[0].get("env", {}).get(DEPTH_KEY) == "2"
      and _f313m2.kwargs[0].get("env", {}).get(CHAIN_KEY) == "dfmgr,dfcoord"
      and f313b.kwargs[0].get("env", {}).get(DEPTH_KEY) == "1",
      f"突變 depth={_f313m2.kwargs[0].get('env', {}).get(DEPTH_KEY) if _f313m2.kwargs else None!r} "
      f"chain={_f313m2.kwargs[0].get('env', {}).get(CHAIN_KEY) if _f313m2.kwargs else None!r}")

_f313m3 = FakeSub(LINES)
_m313c = load_mutant(P313_MUT_ANYISSUE, "devflow_relay_mut_hb_anyissue", _f313m3)
_rc313m3, _, _ = run_mod(_m313c, ["4149", "hi", "--issue", "313"])
check("#313 AC-5(a) 反例③：例外擴及任何 `--issue` → 普通模式缺 `--then-wake` 轉為放行（實跑對照）",
      _rc313m3 == 0 and len(_f313m3.spawned) == 1
      and rc313a == 2 and len(f313a.spawned) == 0,
      f"突變 rc={_rc313m3} spawned={len(_f313m3.spawned)}；正確實作 rc={rc313a}")

# 唯一入口：`--handback-event` 之外沒有第二個豁免 `--then-wake` 的旗標。
# 「豁免 `--then-wake`」的那個條件式 ＝ 同時提到 `args.issue` 與 `args.then_wake` 的 if
# （`main()` 內另有一個只提 `args.issue` 的——`--handback-event` 缺單號的拒絕，不是它）。
_p313_issue_if = next(
    n for n in ast.walk(p312_main_fn(RELAY_SRC))
    if isinstance(n, ast.If) and "args.issue" in ast.unparse(n.test)
    and "args.then_wake" in ast.unparse(n.test))
check("#313 AC-5 唯一例外入口：豁免 `--then-wake` 的條件只提到 `--handback-event` 一個旗標",
      sorted({ast.unparse(a) for a in ast.walk(_p313_issue_if.test)
              if isinstance(a, ast.Attribute)})
      == ["args.handback_event", "args.issue", "args.then_wake"],
      f"條件式={ast.unparse(_p313_issue_if.test)!r}")
check("#313 AC-5 `--handback-event` 的用途只有三處（互斥判斷 ＋ 其訊息、豁免條件、continuation 旗標）",
      RELAY_SRC.count("args.handback_event") >= 4
      and "bool(args.handback_event)" in RELAY_SRC
      and len([n for n in ast.walk(p312_main_fn(RELAY_SRC))
               if isinstance(n, ast.If)
               and "args.handback_event" in ast.unparse(n.test)]) >= 2,
      f"命中次數={RELAY_SRC.count('args.handback_event')}")


# ════════════════════════════════════════════════════════════════════════════
# `#313` 第 2 輪 `BLOCK 4`：終態投遞的**產品路徑**（整合，假 forge／假 send／假 child）
# ════════════════════════════════════════════════════════════════════════════
# 第 1 輪的缺口：EID 只當布林開關（接收端拿不到）、`failure_exit()` 沒有產品呼叫者、
# 深度拒絕只留 stderr。本節驗的是**relay 真的做了那三件事**，仍然零真 API——`gh` 與
# 送訊都走模組全域的 `subprocess`（假類攔下），`HOME` 指向本檔的暫存目錄。
print("\n── #313 BLOCK 4：EID 交付、層1 前置、失敗出口（產品路徑整合）")

hbm = _handback_mod()


def hb_pending_files(profile: str = "dfcoord") -> list:
    root = hbm.pending_dir(profile, home=P313_HOME)
    return sorted(root.glob("*.json")) if root.exists() else []


def hb_alerts(fake) -> list[str]:
    """失敗出口的告警（送訊的文字含 `NO_AUTO_RESUME` 那幾則）。

    為什麼要篩：`send_calls` 也收**正常轉播**的訊息（工具行批次、`✅ 完成`、子程序 exit
    的警告）。不篩的話「送了幾則告警」會被轉播量干擾——那是計到別的東西上。
    """
    return [c[-1] for c in fake.send_calls if hbm.NO_AUTO_RESUME in c[-1]]


def hb_alert_threads(fake) -> list[str]:
    return [c[c.index("-t") + 1].rsplit(":", 1)[-1]
            for c in fake.send_calls if hbm.NO_AUTO_RESUME in c[-1]]


def hb_reset_pending() -> None:
    shutil.rmtree(P313_HOME, ignore_errors=True)


# (1) EID 交付：prompt 前置通知（給模型）＋ 環境變數（給程式），兩者同一個值。
hb_reset_pending()
f4a = FakeSub(LINES)
rc4a, _, _ = with_env(hb_env("1", "dfmgr"), lambda: run(
    ["4149", "receiver prompt without eid", "-p", "dfcoord", "--issue", "313",
     "--handback-event", P313_EID], f4a))
_child_cmd = f4a.spawned[0] if f4a.spawned else []
_child_prompt = prompt_of(_child_cmd)
check("#313 BLOCK 4(1) EID 在子程序的指令裡（`eid_in_child_cmd` ＝ True）",
      rc4a == 0 and any(P313_EID in str(x) for x in _child_cmd),
      f"rc={rc4a} cmd={_child_cmd!r}")
check("#313 BLOCK 4(1) EID 在 prompt 裡（oneshot 的 seat 只看得到 prompt）",
      P313_EID in _child_prompt and "終態投遞" in _child_prompt,
      f"prompt={_child_prompt[:200]!r}")
check("#313 BLOCK 4(1) 原本的 prompt 仍在（前置通知是加上去的，不是取代）",
      "receiver prompt without eid" in _child_prompt,
      f"prompt={_child_prompt[:200]!r}")
check("#313 BLOCK 4(1) EID 也在子程序的環境變數 `DEVFLOW_HANDBACK_EVENT`（給程式讀）",
      bool(f4a.kwargs)
      and f4a.kwargs[0].get("env", {}).get("DEVFLOW_HANDBACK_EVENT") == P313_EID,
      f"env={f4a.kwargs[0].get('env', {}).get('DEVFLOW_HANDBACK_EVENT') if f4a.kwargs else None!r}")
check("#313 BLOCK 4(1) prompt 給的是**可照抄的接收端指令**（ack／done 各一條）",
      "_handback.py ack --issue 313" in _child_prompt
      and "_handback.py done --issue 313" in _child_prompt,
      f"prompt={_child_prompt[:400]!r}")
check("#313 BLOCK 4(1) 普通模式不帶這個環境變數（新鍵只在終態投遞出現）",
      "DEVFLOW_HANDBACK_EVENT" not in (
          FakeSub(LINES).kwargs[0].get("env", {}) if False else
          (lambda f: (run(["4149", "hi", "--issue", "287", "--then-wake", "dfmgr"], f),
                      f.kwargs[0].get("env", {}))[1])(FakeSub(LINES))),
      "普通模式的子程序環境多了終態投遞的鍵")

# (2) prompt 提到**另一個**事件 → 拒絕，且零子程序。
f4b = FakeSub(LINES)
_other = "313-merge.done-6067899999"
rc4b, _, err4b = with_env(hb_env(), lambda: run(
    ["4149", f"請處理 event={_other}", "-p", "dfcoord", "--issue", "313",
     "--handback-event", P313_EID], f4b))
check("#313 BLOCK 4(1) prompt 與旗標的事件不一致 → rc 2、零子程序（不猜哪一個才對）",
      rc4b == 2 and len(f4b.spawned) == 0 and _other in err4b,
      f"rc={rc4b} spawned={len(f4b.spawned)} err={err4b[:200]!r}")

# (2b) 第 3 輪 `BLOCK 3`：衝突偵測的**射程**——只認約定的結構化欄位。
# manager 取 (b)（收窄宣稱、不擴成掃散文），故這裡要有**正反兩條**：結構化欄位衝突要擋、
# 散文裡裸寫的別單 EID **不**擋。後者是宣稱射程的反向斷言，不是漏洞——交接稿常引用別單的
# 事件識別當材料，把任意提及當衝突會讓正當的終態投遞被擋下。`telegram.md` 值欄同此說法。
f4b2 = FakeSub(LINES)
rc4b2, _, _err4b2 = with_env(hb_env(), lambda: run(
    ["4149", f"請處理交接事件 `{_other}`，不要處理其他事件", "-p", "dfcoord",
     "--issue", "313", "--handback-event", P313_EID], f4b2))
check("#313 BLOCK 3 散文裡裸寫的別單 EID **不**拒絕（宣稱射程的反向斷言）",
      rc4b2 == 0 and len(f4b2.spawned) == 1,
      f"rc={rc4b2} spawned={len(f4b2.spawned)} err={_err4b2[:200]!r}")
check("#313 BLOCK 3 那一棒仍以本旗標的事件投遞（散文裡的別單 EID 不會頂替它）",
      P313_EID in f4b2.spawned[0][f4b2.spawned[0].index("-q") + 1]
      and f4b2.kwargs[0].get("env", {}).get("DEVFLOW_HANDBACK_EVENT") == P313_EID,
      f"env={f4b2.kwargs[0].get('env', {}).get('DEVFLOW_HANDBACK_EVENT')!r}")
f4b3 = FakeSub(LINES)
rc4b3, _, err4b3 = with_env(hb_env(), lambda: run(
    ["4149", f"環境裡另一個：{hbm.EVENT_ENV}={_other}", "-p", "dfcoord",
     "--issue", "313", "--handback-event", P313_EID], f4b3))
check("#313 BLOCK 3 `DEVFLOW_HANDBACK_EVENT=` 標示的衝突同樣擋（兩個約定欄位都算）",
      rc4b3 == 2 and len(f4b3.spawned) == 0 and _other in err4b3,
      f"rc={rc4b3} spawned={len(f4b3.spawned)}")

# (2c) 第 3 輪 `BLOCK 2`：`--handback-event` 的值會被拼進待處理紀錄的路徑 → 入口先驗。
for _lbl, _ev in [("逃出目錄", "../../../escaped"),
                  ("不合 grammar", "X"),
                  ("帶路徑分隔符", "313-r1.approve-/etc/passwd")]:
    hb_reset_pending()
    _f4k = FakeSub(LINES)
    _rc4k, _, _err4k = with_env(hb_env(), lambda f=_f4k, e=_ev: run(
        ["4149", "hi", "-p", "dfcoord", "--issue", "313", "--handback-event", e], f))
    check(f"#313 BLOCK 2 relay 入口拒絕不合法的 EID（{_lbl}）→ rc 2、零子程序、零 gh",
          _rc4k == 2 and len(_f4k.spawned) == 0 and _f4k.gh_calls == []
          and hb_pending_files() == [],
          f"rc={_rc4k} spawned={len(_f4k.spawned)} gh={len(_f4k.gh_calls)} "
          f"pending={hb_pending_files()!r}")
_f4k2 = FakeSub(LINES)
_rc4k2, _, _err4k2 = with_env(hb_env(), lambda: run(
    ["4149", "hi", "-p", "dfcoord", "--issue", "../../x",
     "--handback-event", P313_EID], _f4k2))
check("#313 BLOCK 2 relay 入口同樣驗單號（會進檔名的另一欄）→ rc 2、零子程序",
      _rc4k2 == 2 and len(_f4k2.spawned) == 0 and "issue=" in _err4k2,
      f"rc={_rc4k2} err={_err4k2[:200]!r}")

# (3) 層1 前置：讀不到該 EID 的 handback 行 → 不派子程序，走失敗出口。
hb_reset_pending()
f4c = FakeSub(LINES, issue_body="這張單上沒有任何 handback 行。")
rc4c, _, err4c = with_env(hb_env(), lambda: run(
    ["4149", "hi", "-p", "dfcoord", "--issue", "313",
     "--handback-event", P313_EID], f4c))
_pend_c = hb_pending_files()
check("#313 BLOCK 4(2) 層1 未成立 → rc 2、**零子程序**（哨兵反證 Popen 未被呼叫）",
      rc4c == 2 and len(f4c.spawned) == 0, f"rc={rc4c} spawned={len(f4c.spawned)}")
check("#313 BLOCK 4(2) 層1 的讀回確實發生過（`gh issue view` ≥1，且在派子程序之前）",
      len(f4c.gh_view_calls) >= 1 and "popen" not in f4c.events,
      f"events={f4c.events!r}")
check("#313 BLOCK 4(4) 層1 失敗走失敗出口：topic ＋ General 各一則、待處理紀錄一筆",
      len(hb_alerts(f4c)) == 2 and len(_pend_c) == 1
      and hb_alert_threads(f4c) == ["4149", "1"],
      f"告警 thread={hb_alert_threads(f4c)!r} pending={_pend_c!r}")
check("#313 BLOCK 4(4) 待處理紀錄有 profile 與本單歸屬，且結果記為未定",
      bool(_pend_c) and _pend_c[0].name == f"313-{P313_EID}.json"
      and json.loads(_pend_c[0].read_text())["result"] == "indeterminate"
      and json.loads(_pend_c[0].read_text())["reason"] == "land_failed",
      f"pending={[p.name for p in _pend_c]!r}")
check("#313 BLOCK 4(4) 告警內容合 AC-6（單號、事件、不自動續接、待處理紀錄位置）",
      bool(hb_alerts(f4c)) and all(
          s in hb_alerts(f4c)[0]
          for s in ("#313", P313_EID, hbm.NO_AUTO_RESUME, str(_pend_c[0]))),
      f"text={hb_alerts(f4c)[0][:300] if hb_alerts(f4c) else None!r}")

# (4) 深度拒絕也走失敗出口（第 1 輪只留 stderr 的那條路）。
hb_reset_pending()
f4d = FakeSub(LINES)
rc4d, _, err4d = with_env(hb_env(str(P312_MAX), "dfmgr,dfimpl,dfmgr"), lambda: run(
    ["4149", "hi", "-p", "dfcoord", "--issue", "313",
     "--handback-event", P313_EID], f4d))
_pend_d = hb_pending_files()
check("#313 BLOCK 4(4) `DEPTH=3` 的終態投遞：rc 2、零子程序**且**topic ＋ General ＋ pending",
      rc4d == 2 and len(f4d.spawned) == 0 and hb_alert_threads(f4d) == ["4149", "1"]
      and len(_pend_d) == 1
      and json.loads(_pend_d[0].read_text())["reason"] == "depth_rejected",
      f"rc={rc4d} 告警={hb_alert_threads(f4d)!r} pending={[p.name for p in _pend_d]!r}")
check("#313 BLOCK 4(4) 深度拒絕的既有 stderr 訊息一字未動（新出口是**加上去**的）",
      P312_LIMIT_SENTENCE in err4d and P312_LEADING_SENTENCE in err4d,
      f"err={err4d[-200:]!r}")

# (4b) 第 3 輪 `BLOCK 1`：pending 寫不成時，relay 仍要把兩則告警送出去。
# 第 2 輪的現場是兩層短路：`failure_exit()` 先寫 pending、失敗即拋，而 relay 的
# `_handback_failure()` 把整段包在一個 `try` 裡——於是 `$HOME` 不是目錄時，topic 與
# General **連嘗試都沒有**，只剩一行 stderr。這裡用「HOME 指向一個普通檔案」重現那個
# 條件（`mkdir(parents=True)` 必拋），要求兩則告警照送、且 stderr 明說紀錄沒落地。
# 鑑別力：產品修好後 relay 已**結構上**無法短路（`failure_exit()` 自己不拋了），故同述詞
# 的突變對照放在 `tests/channels/test_handback.py` 的「第 3 輪 BLOCK 1」一節（舊實作
# ＝ 先寫 pending、失敗即拋 → `send_attempts []`）。
hb_reset_pending()
P313_HOME_FILE = TESTTMP / "home-is-a-file"
P313_HOME_FILE.write_text("x")
f4i = FakeSub(LINES, issue_body="這張單上沒有任何 handback 行。")
rc4i, _, err4i = with_env({DEPTH_KEY: None, CHAIN_KEY: None, "HOME": str(P313_HOME_FILE)},
                          lambda: run(["4149", "hi", "-p", "dfcoord", "--issue", "313",
                                       "--handback-event", P313_EID], f4i))
check("#313 BLOCK 1 pending 寫不成（HOME 是檔案）→ 兩則告警仍落 topic ＋ General",
      rc4i == 2 and len(f4i.spawned) == 0
      and hb_alert_threads(f4i) == ["4149", "1"] and len(hb_alerts(f4i)) == 2,
      f"rc={rc4i} 告警={hb_alert_threads(f4i)!r}")
check("#313 BLOCK 1 告警文字自己說得出「待處理紀錄未落地」（不叫人去翻不存在的檔）",
      all(hbm.PENDING_NOT_WRITTEN in t for t in hb_alerts(f4i))
      and all("NotADirectoryError" in t for t in hb_alerts(f4i)),
      f"text={hb_alerts(f4i)[0][:300] if hb_alerts(f4i) else None!r}")
check("#313 BLOCK 1 relay 的 stderr 也分得出是「三處少一處」而不是整個出口沒跑",
      "待處理紀錄未落地" in err4i and "告警已送 thread ['4149', '1']" in err4i
      and "失敗出口自己也失敗了" not in err4i,
      f"err={err4i[-300:]!r}")

# (4c) 第 4 輪 `BLOCK 1`（`AC-3`）：合法且**自相一致**的 `313-…` 行放在假 `#999` 上，
# 配 `--issue 999` → 必須拒絕。第 3 輪的現場是 `rc 0`、`spawned 1`、`gh_targets ['999',
# '999']`、子程序開在 `issue-999`——`#999` 的交回被 `#313` 的紀錄代簽。
# `landed()` 只收 body 與 EID，分不出 body 是哪張單來的，所以核對必須長在「決定去讀哪張
# 單」的邊界上（relay 入口 ＋ forge 建構）。
hb_reset_pending()
f4j = FakeSub(LINES, issue_body=HB_BODY)   # 內含自相一致的 `313-…` handback ＋ ack
rc4j, _, err4j = with_env(hb_env(), lambda: run(
    ["4149", "hi", "-p", "dfcoord", "--issue", "999",
     "--handback-event", P313_EID], f4j))
check("#313 BLOCK 1 跨單投遞（`--issue 999` ＋ `313-…`）→ rc 2、**零子程序**",
      rc4j == 2 and len(f4j.spawned) == 0,
      f"rc={rc4j} spawned={len(f4j.spawned)} err={err4j[:200]!r}")
check("#313 BLOCK 1 拒絕發生在**任何 `gh` 之前**（`gh_calls` 恰 0，含 view 與 comment）",
      f4j.gh_calls == [] and f4j.gh_view_calls == [] and f4j.gh_comment_calls == [],
      f"gh={f4j.gh_calls!r}")
check("#313 BLOCK 1 零 ack／done／pending 寫入（沒有任何一處把這次當成有效事件）",
      hb_pending_files() == [] and hb_alerts(f4j) == [],
      f"pending={hb_pending_files()!r} 告警={len(hb_alerts(f4j))}")
check("#313 BLOCK 1 拒絕訊息指得出兩個不一致的值（999 與 EID 的 313）",
      "999" in err4j and P313_EID in err4j,
      f"err={err4j[:300]!r}")
check("#313 BLOCK 1 正例不受影響：`--issue 313` ＋ `313-…` 仍 rc 0、1 個子程序、session issue-313",
      (lambda f: (with_env(hb_env(), lambda: run(
          ["4149", "hi", "-p", "dfcoord", "--issue", "313",
           "--handback-event", P313_EID], f))[0] == 0
                  and len(f.spawned) == 1
                  and f.spawned[0][f.spawned[0].index("-c") + 1] == "issue-313"))(
          FakeSub(LINES)),
      "同一張單的終態投遞被擋掉了")

# 鑑別力：把兩道核對都從 relay 這一側拿掉 → 跨單投遞又成立（`spawned 1`、session issue-999）。
P313_KEY_GATE = "            handback_validate_key(args.profile, args.issue, args.handback_event)\n"
P313_FORGE_BIND = """            body = HandbackForge(args.issue, event=args.handback_event,
                                 capture=_capture).read()
"""
MUT_CROSS = p312_mutate(
    p312_mutate(RELAY_SRC, P313_KEY_GATE, "            pass\n"),
    P313_FORGE_BIND,
    "            body = HandbackForge(args.issue, capture=_capture).read()\n")
check("#313 BLOCK 1 突變確實套上（兩個錨點各恰一處命中）", MUT_CROSS != RELAY_SRC, "錨點漂移")
_f4j_mut = FakeSub(LINES, issue_body=HB_BODY)
_m_cross = load_mutant(MUT_CROSS, "devflow_relay_mut_crossissue", _f4j_mut)
_rc4j_mut, _, _ = with_env(hb_env(), lambda: run_mod(
    _m_cross, ["4149", "hi", "-p", "dfcoord", "--issue", "999",
               "--handback-event", P313_EID]))
check("#313 BLOCK 1 反例「不核 EID 的 issue 欄」→ 跨單投遞成立（產品拒絕，實跑對照）",
      _rc4j_mut == 0 and len(_f4j_mut.spawned) == 1
      and _f4j_mut.spawned[0][_f4j_mut.spawned[0].index("-c") + 1] == "issue-999"
      and rc4j == 2 and len(f4j.spawned) == 0,
      f"突變 rc={_rc4j_mut} spawned={len(_f4j_mut.spawned)}；產品 rc={rc4j}")

# (5) 子程序 rc 非 0：忙碌（`SESSION_NOT_OWNED`）與其他失敗分流，都走失敗出口。
hb_reset_pending()
f4e = FakeSub(LINES, rc=1, err_lines=["hermes: SESSION_NOT_OWNED issue-313\n"])
rc4e, _, _ = with_env(hb_env(), lambda: run(
    ["4149", "hi", "-p", "dfcoord", "--issue", "313",
     "--handback-event", P313_EID], f4e))
_pend_e = hb_pending_files()
check("#313 BLOCK 4(4) 忙碌（`SESSION_NOT_OWNED`）→ 失敗出口且**具名到 session**",
      rc4e == 1 and len(_pend_e) == 1
      and json.loads(_pend_e[0].read_text())["reason"] == "busy"
      and len(hb_alerts(f4e)) == 2
      and all("hermes -p dfcoord chat -c issue-313" in t for t in hb_alerts(f4e)),
      f"rc={rc4e} 告警={len(hb_alerts(f4e))} pending={[p.name for p in _pend_e]!r}")

hb_reset_pending()
f4f = FakeSub(LINES, rc=1, err_lines=["boom\n"])
rc4f, _, _ = with_env(hb_env(), lambda: run(
    ["4149", "hi", "-p", "dfcoord", "--issue", "313",
     "--handback-event", P313_EID], f4f))
_pend_f = hb_pending_files()
check("#313 BLOCK 4(4) 其他失敗 → `deliver_failed`（不誤報成忙碌）",
      rc4f == 1 and len(_pend_f) == 1
      and json.loads(_pend_f[0].read_text())["reason"] == "deliver_failed",
      f"rc={rc4f} pending={[json.loads(p.read_text())['reason'] for p in _pend_f]!r}")

# (6) 子程序 rc 0 但接收端沒寫 ack（層3 未成立）→ 失敗出口；`Popen` 不冒充接收。
hb_reset_pending()
f4g = FakeSub(LINES, issue_body=HB_BODY_NO_ACK)
rc4g, _, _ = with_env(hb_env(), lambda: run(
    ["4149", "hi", "-p", "dfcoord", "--issue", "313",
     "--handback-event", P313_EID], f4g))
_pend_g = hb_pending_files()
check("#313 BLOCK 4(4) 投遞成功但無 ack → `no_ack` 失敗出口（層2 不冒充層3）",
      rc4g == 0 and len(f4g.spawned) == 1 and len(_pend_g) == 1
      and json.loads(_pend_g[0].read_text())["reason"] == "no_ack"
      and len(hb_alerts(f4g)) == 2,
      f"rc={rc4g} pending={[json.loads(p.read_text())['reason'] for p in _pend_g]!r}")

# (7) 正向路徑：層1 成立 ＋ 子程序 rc 0 ＋ 讀得到 ack → 零告警、零待處理紀錄。
hb_reset_pending()
f4h = FakeSub(LINES)
rc4h, _, _ = with_env(hb_env(), lambda: run(
    ["4149", "hi", "-p", "dfcoord", "--issue", "313",
     "--handback-event", P313_EID], f4h))
check("#313 BLOCK 4 正向路徑：層1 ＋ 層3 齊備 → rc 0、零告警、零待處理紀錄",
      rc4h == 0 and len(f4h.spawned) == 1 and hb_alerts(f4h) == []
      and hb_pending_files() == [],
      f"rc={rc4h} 告警={hb_alerts(f4h)!r} pending={hb_pending_files()!r}")

# ── 鑑別力：三個未達成候選各自實跑 ──
P313_NOTICE = ("        prompt = (handback_receiver_notice(args.issue, args.handback_event,\n"
               "                                           thread=args.thread, profile=args.profile)\n"
               "                  + \"\\n\\n\" + prompt)\n")
P313_LAND_GATE = "        if not ok1:\n"
# 錨點取**縮排 8 格**的那一行（深度拒絕區塊內的那一個）；模組內其餘同名條件都是 4 格。
P313_DEPTH_FAIL = "        if args.handback_event:\n"
MUT4_NOEID = p312_mutate(RELAY_SRC, P313_NOTICE, "        pass\n")
MUT4_NOGATE = p312_mutate(RELAY_SRC, P313_LAND_GATE, "        if False:\n")
MUT4_STDERRONLY = p312_mutate(RELAY_SRC, P313_DEPTH_FAIL, "        if False:\n")
check("#313 BLOCK 4 三種突變確實套上（錨點各恰一處命中）",
      MUT4_NOEID != RELAY_SRC and MUT4_NOGATE != RELAY_SRC
      and MUT4_STDERRONLY != RELAY_SRC,
      "錨點漂移：某個突變沒有套上去")

hb_reset_pending()
_f4m1 = FakeSub(LINES)
_m4a = load_mutant(MUT4_NOEID, "devflow_relay_mut_hb_noeid", _f4m1)
with_env(hb_env(), lambda: run_mod(
    _m4a, ["4149", "receiver prompt without eid", "-p", "dfcoord", "--issue", "313",
           "--handback-event", P313_EID]))
check("#313 BLOCK 4 反例①「EID 不進 prompt」→ `eid_in_child_cmd` 轉 False（實跑對照）",
      bool(_f4m1.spawned)
      and not any(P313_EID in str(x) for x in _f4m1.spawned[0])
      and any(P313_EID in str(x) for x in _child_cmd),
      f"突變 prompt={prompt_of(_f4m1.spawned[0])[:120] if _f4m1.spawned else None!r}")

hb_reset_pending()
_f4m2 = FakeSub(LINES, issue_body="這張單上沒有任何 handback 行。")
_m4b = load_mutant(MUT4_NOGATE, "devflow_relay_mut_hb_nogate", _f4m2)
_rc4m2, _, _ = with_env(hb_env(), lambda: run_mod(
    _m4b, ["4149", "hi", "-p", "dfcoord", "--issue", "313",
           "--handback-event", P313_EID]))
check("#313 BLOCK 4 反例②「層1 失敗仍派 child」→ 突變下 spawned 轉非零（產品為 0，實跑對照）",
      len(_f4m2.spawned) == 1 and len(f4c.spawned) == 0,
      f"突變 spawned={len(_f4m2.spawned)} rc={_rc4m2}；產品 spawned={len(f4c.spawned)}")

hb_reset_pending()
_f4m3 = FakeSub(LINES)
_m4c = load_mutant(MUT4_STDERRONLY, "devflow_relay_mut_hb_stderronly", _f4m3)
_rc4m3, _, _err4m3 = with_env(hb_env(str(P312_MAX), "dfmgr,dfimpl,dfmgr"), lambda: run_mod(
    _m4c, ["4149", "hi", "-p", "dfcoord", "--issue", "313",
           "--handback-event", P313_EID]))
check("#313 BLOCK 4 反例③「深度拒絕只留 stderr」→ 零告警、零待處理紀錄（產品兩者都有，實跑對照）",
      _rc4m3 == 2 and hb_alerts(_f4m3) == [] and hb_pending_files() == []
      and P312_LIMIT_SENTENCE in _err4m3
      and len(hb_alerts(f4d)) == 2 and len(_pend_d) == 1,
      f"突變 告警={len(hb_alerts(_f4m3))} pending={hb_pending_files()!r}；"
      f"產品 告警={len(hb_alerts(f4d))} pending={len(_pend_d)}")
hb_reset_pending()



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
    # 本檔產生的 log 全在 TESTTMP 下，整個刪掉（暫存根不留 relay-*.log）
    shutil.rmtree(TESTTMP, ignore_errors=True)
    if TESTTMP.exists():
        print(f"⚠ 暫存目錄未清掉：{TESTTMP}")
    print("─" * 72)
    raise SystemExit(1 if failed or leftovers or TESTTMP.exists() else 0)
