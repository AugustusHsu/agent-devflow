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
from __future__ import annotations

import importlib.util
import io
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

    def __init__(self, lines: list[str], rc: int = 0, *, gh_rc: int = 0) -> None:
        self.sent: list[list[str]] = []        # 所有 run 的 cmd（送訊 ＋ gh）
        self.spawned: list[list[str]] = []     # 子程序的 Popen
        self.kwargs: list[dict] = []
        self.procs: list[FakeProc] = []        # 建出來的假子程序，供 waits 計數用
        self.events: list[str] = []            # 時間軸：popen／run:<argv0>
        self._lines = lines
        self._rc = rc
        self._gh_rc = gh_rc

    @property
    def gh_calls(self) -> list[list[str]]:
        return [c for c in self.sent if c and c[0] == "gh"]

    @property
    def send_calls(self) -> list[list[str]]:
        return [c for c in self.sent if c and c[0] == "hermes"]

    def run(self, cmd, **kw):
        self.sent.append(cmd)
        self.events.append(f"run:{cmd[0] if cmd else '?'}")
        rc = self._gh_rc if (cmd and cmd[0] == "gh") else 0
        return types.SimpleNamespace(stdout='{"success": true}', stderr="", returncode=rc)

    def Popen(self, cmd, **kw):               # noqa: N802 — 對齊 subprocess 的名字
        self.kwargs.append(kw)
        self.spawned.append(cmd)
        self.events.append("popen")
        proc = FakeProc(self._lines, self._rc, self.events)
        self.procs.append(proc)
        return proc


LINES = [
    '{"type":"system","subtype":"init","model":"test-model"}\n',
    '{"type":"tool_use","tool_call_id":"c1","name":"terminal","input":{"command":"git status"}}\n',
    '{"type":"tool_result","tool_call_id":"c1","name":"terminal","output":"clean"}\n',
    '{"type":"result","text":"做完了","duration_ms":1234}\n',
]


LAST_MOD: list = []            # run() 把最後一次載入的模組放這裡，供需要它的案例取用


def run(argv: list[str], fake, *, freeze_clock: bool = False):
    """以 sys.argv 餵參數呼叫 main()，回傳 (rc, stdout, stderr)。

    載入的模組另放進 `LAST_MOD[-1]`——`BLOCK 1` 要在同一個模組實例上續呼
    `_log_path`（序號是模組級狀態），回傳值不改形狀以免動搖既有案例。
    """
    mod = load(fake, freeze_clock=freeze_clock)
    LAST_MOD.append(mod)
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


def prompt_of(cmd: list[str]) -> str:
    """從 `hermes … chat -q <prompt> …` 取出 prompt。"""
    return cmd[cmd.index("-q") + 1] if "-q" in cmd else ""


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
          str(lp).startswith(tempfile.gettempdir()) and str(REPO) not in str(lp),
          f"log={lp} tmp={tempfile.gettempdir()} repo={REPO}")
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
      and len(logs_c) == 1 and "999" in logs_c[0] and "287" not in logs_c[0],
      f"prompt={wake_c[:200]!r} logs={logs_c}")
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
      all(str(p).startswith(tempfile.gettempdir()) and str(REPO) not in str(p)
          for p in (_p1, _p2, _p3)), f"{_p1}")

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
check("AC-4 then-wake 喚醒的子程序同樣拿 depth+1（深度只計巢狀，不隨輪次累加）",
      len(f4.kwargs) == 2 and f4.kwargs[1].get("env", {}).get(DEPTH_KEY) == "1",
      f"kwargs[1] depth={f4.kwargs[1].get('env', {}).get(DEPTH_KEY) if len(f4.kwargs) > 1 else None!r}")
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
# 本單不新增 seat 自律：`manager.md` 不得出現 handoff 行的義務。
# 「該檔零改動」的 git 事實由 T 的驗證指令在 shell 側取（`git diff --name-only` 恰 6 檔）。
check("#300 AC-3 本單不新增 seat 自律：manager.md 不含 handoff 字面",
      "handoff" not in MGR.lower(), "")
check("#300 AC-3 判準表的最後一列只宣稱「relay 沒接手」，不把成因說成分得開",
      "relay 沒接手" in TG300 and "不宣稱它分得開" in TG300, "")


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
