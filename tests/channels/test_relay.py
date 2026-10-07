#!/usr/bin/env python3
"""`#298`／K4c-7：`devflow_relay.py` 的 `--then-wake` 銜接（`AC-1`～`AC-7`、`AC-12`）。

直接執行：`/usr/bin/python3 tests/channels/test_relay.py`
全過 exit 0、任一項失敗 exit 非 0，stdout 逐項列 PASS／FAIL（風格同 `test_marker.py`）。

**縫只有一處**：relay 的對外效果全部經模組全域的 `subprocess`——`_send` 的 `run`
是唯一的送訊息出口，`_run_child` 的 `Popen` 是唯一的子程序出口。實查無 `requests`／
`urllib`／`http`／`socket`／`os.system`。替掉那一個名字即全部攔下，所以本檔零真 API、
零真子程序（`AC-6`）。

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
"""
from __future__ import annotations

import importlib.util
import io
import os
import re
import sys
import tempfile
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
VERSION_FILE = REPO / "devflow" / "VERSION"

SELF_SRC = Path(__file__).read_text()
RELAY_SRC = RELAY_SRC_PATH.read_text()

RESULTS: list[tuple[str, bool, str]] = []


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


def load(fake):
    """每個案例重新載入一份 relay（模組狀態乾淨），注入假 subprocess 並覆寫時間常數。"""
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
    return mod


class FakeProc:
    """假子程序。每次建立都要新的 iterator——then-wake 會建第二次。"""

    def __init__(self, lines: list[str], rc: int) -> None:
        self.stdout = iter(lines)
        self.stderr = iter([])
        self.returncode = rc

    def wait(self) -> int:
        return self.returncode


class FakeSub:
    """假 subprocess 模組。PIPE／DEVNULL／STDOUT 三個都要（`AC-7`）：

    `_run_child` 的 `Popen` 呼叫裡用了 `subprocess.DEVNULL`，只定義 `PIPE` 會在 kwargs
    求值時就掛成 `AttributeError: 'FakeSub' object has no attribute 'DEVNULL'`——
    那是裁決位與協調位各自踩到的實測。`STDOUT` 一併定義，日後改用合流就不必再回來補。
    """

    PIPE = -1
    DEVNULL = -3
    STDOUT = -2

    def __init__(self, lines: list[str], rc: int = 0) -> None:
        self.sent: list[list[str]] = []        # _send 的 run
        self.spawned: list[list[str]] = []     # 子程序的 Popen
        self.kwargs: list[dict] = []
        self._lines = lines
        self._rc = rc

    def run(self, cmd, **kw):
        self.sent.append(cmd)
        return types.SimpleNamespace(stdout='{"success": true}', stderr="")

    def Popen(self, cmd, **kw):               # noqa: N802 — 對齊 subprocess 的名字
        self.kwargs.append(kw)
        self.spawned.append(cmd)
        return FakeProc(self._lines, self._rc)


LINES = [
    '{"type":"system","subtype":"init","model":"test-model"}\n',
    '{"type":"tool_use","tool_call_id":"c1","name":"terminal","input":{"command":"git status"}}\n',
    '{"type":"tool_result","tool_call_id":"c1","name":"terminal","output":"clean"}\n',
    '{"type":"result","text":"做完了","duration_ms":1234}\n',
]


def run(argv: list[str], fake, rc_lines=LINES):
    """以 sys.argv 餵參數呼叫 main()，回傳 (rc, stdout, stderr)。"""
    mod = load(fake)
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
    check("AC-11 VERSION == 0.15.6.0（c 位進位：修正既有能力的缺陷）",
          cur == (0, 15, 6, 0), f"cur={cur}")


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
    print("─" * 72)
    raise SystemExit(1 if failed or leftovers else 0)
