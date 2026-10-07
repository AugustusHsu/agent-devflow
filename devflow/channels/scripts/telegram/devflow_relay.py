#!/usr/bin/env python3
"""把 headless 子程序的執行過程轉播到 Telegram topic。

為什麼需要：Telegram Bot API 硬性禁止 bot 收到其他 bot 的訊息，所以 coordinator 無法
用 @提及 喚醒 manager，只能用 `hermes -p dfmgr chat --oneshot` 開子程序。子程序的
session `thread_id=None`，沒有 Telegram 介面可以渲染 `tool_progress`，整段執行在群組裡
完全看不到（`#252` 實跑 251 則工作記錄零可見度）。

做法：`--format stream-json` 會即時吐出 `tool_use` / `tool_result` / `text` 事件
（官方協定，`hermes_cli/stream_json.py`），本腳本逐行解析並轉成訊息送進該單的 topic。
可見度因此不依賴 manager 自律播報——事件是 runtime 自動產生的。

用法：
    devflow_relay.py <thread> <prompt>              # 預設 dfmgr
    devflow_relay.py <thread> <prompt> -p <profile>
    devflow_relay.py <thread> <prompt> --issue 267  # 標題顯示單號
    devflow_relay.py <thread> --file <路徑>         # prompt 從檔案讀
    devflow_relay.py <thread> <prompt> --continue-session issue-267  # 累積 context
    devflow_relay.py <thread> --file <路徑> -p dfimpl --issue 298 --then-wake dfmgr
                                                    # 子程序退出後由 relay 自己再喚醒 dfmgr
                                                    # （帶 --issue 時 --then-wake 為必給）

子程序退出後的銜接（`#298`）：被 relay 喚醒的 seat 是 oneshot 子程序，turn 結束 ＝ 程序
退出 ＝ session 消失，它自己啟動的 background 通知沒有收件人（`#287` 實證：漏 push ＋ 開 PR
＋ 派審）。`--then-wake` 把銜接放在 relay 這一層——relay 是子程序的父程序，它知道子程序何時
結束，不需要任何等待。relay 本身不懂 workflow：它只把「單號、子程序的 log 路徑、rc」交給被
喚醒者，下一步做什麼由那個 seat 讀 forge 自己判。

版面與封存 MD 一致（`devflow_archive.py`）：工具摘要走同一個 `tool_summary()`，
所以 topic 裡看到的與日後封存檔讀到的是同一種寫法。
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time

from devflow_archive import tool_summary  # noqa: E402 — 與封存檔共用摘要邏輯

CHAT = "-1003546152597"
MAX_MSG = 3500  # Telegram 單則上限 4096，留邊給標題與截斷標記

# 批次節奏：達到則數或秒數就送出，兩者先到先送。
# Telegram 對同一群組約 20 則/分鐘，`instant` 已接近上限，再快會被限流反而延遲。
PACE = {
    "instant": (3, 8),    # 追進度用；工具密集時每分鐘約 8-10 則
    "normal": (6, 15),
    "quiet": (10, 30),    # 只想看大段落，長時間任務用
}
DEFAULT_PACE = "instant"

# 短任務不值得一則「開工」：任務在這個秒數內結束就只留「完成」，避免兩則訊息說一件事。
OPENING_DELAY = 20
# 長任務（codex exec 一輪審查可跑 10-20 分鐘）在無事件期間完全安靜，
# 分不出還在跑還是死了。超過這個秒數沒有任何事件就送一則心跳。
HEARTBEAT_AFTER = 300

# 鏈結深度上限（`#298` `AC-4`）。深度**只計巢狀**（relay 內的子程序再開 relay），
# 不計同一 seat 的續接：relay 讀自身環境的 `DEVFLOW_RELAY_DEPTH`（未設 ＝ 0），對它派出的
# **每個**子程序傳 `depth+1`——首個子程序與 `--then-wake` 喚醒者皆然。被喚醒的 seat 與呼叫
# relay 的 seat 是同一 seat 的續接，深度相同，故多輪修正不累加。真實流程
# `coord(0) → mgr(1) → coder／rev(2)`，最深 **2**，上限 3 留一層餘裕；真巢狀遞迴
# （mgr 內 relay 再 then-wake mgr 再開 relay…）仍會被擋。
# 值只寫在這裡一處——散落的話下一個改上限的人會漏改。
MAX_RELAY_DEPTH = 3
DEPTH_ENV = "DEVFLOW_RELAY_DEPTH"
# 選配的可讀鏈：每層把自己的 profile 接在後面，超限時印出來才看得出是誰疊誰。
CHAIN_ENV = "DEVFLOW_RELAY_CHAIN"

# log 檔名的程序內序號。`itertools.count` 的 `next` 在 CPython 下是原子的，
# 同一程序內（含將來若有多個執行緒各派子程序）不會發出重複值。
_LOG_SEQ = itertools.count(1)


def _current_depth() -> int:
    """relay 自身所在的層數。未設 ＝ 0（最外層，由人或 gateway session 直接啟動）。"""
    try:
        return int(os.environ.get(DEPTH_ENV, "") or 0)
    except ValueError:
        return 0  # 外部亂塞值不該讓轉播掛掉；當最外層處理


def _child_env(profile: str) -> dict[str, str]:
    """子程序的環境 ＝ 本程序環境的複本 ＋ 深度覆寫。

    必須是複本：只給一個鍵的話子程序連 `PATH` 都沒有，`hermes` 找不到（實測必掛）。
    """
    env = dict(os.environ)
    env[DEPTH_ENV] = str(_current_depth() + 1)
    chain = os.environ.get(CHAIN_ENV, "")
    env[CHAIN_ENV] = f"{chain},{profile}" if chain else profile
    return env


def _log_path(issue: str | None, profile: str) -> pathlib.Path:
    """子程序的 log 檔。`$TMPDIR` 下，命名含單號與 profile——不寫進 repo。

    被 `--then-wake` 喚醒的是新的 oneshot，它看不到前一個子程序的畫面；
    原始事件流與 stderr 落成檔案，喚醒 prompt 才有東西可以指（`AC-2`）。

    檔名**不得只靠時間戳**：`--issue 287 --then-wake dfmgr` 時首棒與喚醒棒的 issue 與
    profile 都相同，兩棒在同一秒內取名就會拿到同一個路徑，喚醒棒覆寫首棒的 log，而
    prompt 指的正是首棒那個——讀到的內容已經是第二棒的（`#298` 第 2 輪 `BLOCK 1` 實測）。
    故加入 pid ＋程序內遞增序號：序號保證**同一程序內任兩次呼叫必不同**（時間戳與 pid
    在同一程序內都是常數，撐不起這個保證），pid 則讓並行的多個 relay 不互撞。
    """
    seq = next(_LOG_SEQ)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"relay-{issue or 'nonissue'}-{profile}-{stamp}-{os.getpid()}-{seq}.log"
    return pathlib.Path(tempfile.gettempdir()) / name


def _send(profile: str, thread: str, text: str) -> bool:
    """送一則到 topic。失敗只警告不中斷——轉播斷了不該讓任務跟著死。"""
    if not text.strip():
        return True
    if len(text) > MAX_MSG:
        text = text[:MAX_MSG] + "\n…（本則已截斷）"
    try:
        res = subprocess.run(
            ["hermes", "-p", profile, "send", "-t", f"telegram:{CHAT}:{thread}", "--json", text],
            capture_output=True, stdin=subprocess.DEVNULL, timeout=60, text=True)
        ok = '"success": true' in res.stdout
        if not ok:
            print(f"[relay] ⚠️ 送出失敗：{(res.stdout or res.stderr)[:200]}", file=sys.stderr)
        return ok
    except Exception as exc:  # noqa: BLE001
        print(f"[relay] ⚠️ 送出異常：{exc}", file=sys.stderr)
        return False


# Hermes 自己的工具動詞表（`agent/display.py:505-513`）。沿用同一套措辭，
# 讓 topic 裡的行與 CLI／desktop 的工具進度看起來是同一個東西。
TOOL_VERB = {
    "read_file": "Reading", "write_file": "Writing", "patch": "Editing",
    "search_files": "Searching", "terminal": "Running", "execute_code": "Running code",
    "web_search": "Searching web", "web_extract": "Fetching",
    "skill_view": "Reading skill", "skills_list": "Listing skills", "skill_manage": "Updating skill",
    "delegate_task": "Delegating", "clarify": "Asking", "memory": "Updating memory",
    "todo_list": "Updating tasks", "vision_analyze": "Looking at image",
}
TOOL_ICON = {
    "read_file": "📖", "write_file": "📝", "patch": "✏️", "search_files": "🔍",
    "terminal": "📋", "execute_code": "⚙️", "web_search": "🌐", "web_extract": "🌐",
    "skill_view": "📘", "skills_list": "📘", "skill_manage": "📘",
    "delegate_task": "👥", "clarify": "❓", "memory": "🧠", "todo_list": "✅",
    "vision_analyze": "👁", "cronjob_manage": "⏰",
}


def _target(name: str, args: dict | None) -> str:
    """工具的「對象」：一眼看出動到什麼。檔名只留最後一段——路徑前綴每行都一樣，是雜訊。"""
    if not isinstance(args, dict):
        return ""
    if name == "terminal":
        cmd = " ".join(str(args.get("command", "")).split())
        return f"`{cmd[:64]}{'…' if len(cmd) > 64 else ''}`"
    if name in ("read_file", "write_file", "patch"):
        path = str(args.get("path", ""))
        short = path.rsplit("/", 1)[-1] if "/" in path else path
        if name == "read_file" and args.get("offset"):
            short += f" L{args['offset']}"
        return short
    if name == "search_files":
        return str(args.get("pattern", ""))[:40]
    if name == "execute_code":
        code = str(args.get("code", "")).strip().split("\n")[0]
        return f"`{code[:56]}{'…' if len(code) > 56 else ''}`"
    if name in ("web_search", "web_extract"):
        return str(args.get("query") or (args.get("urls") or [""])[0])[:50]
    if name == "clarify":
        try:
            return str(args["questions"][0]["question"])[:50]
        except Exception:  # noqa: BLE001
            return ""
    if name == "skill_view":
        return str(args.get("name", ""))
    first = next((str(v) for v in args.values() if isinstance(v, (str, int))), "")
    return first[:50]


def _tool_line(name: str, args: dict | None) -> str:
    """一則工具 ＝ 一行。時間戳由 Telegram 提供，耗時與輸出摘要只在異常時才有資訊量，
    平時都是雜訊——把它們拿掉後長度約剩三分之一。"""
    icon = TOOL_ICON.get(name, "🔧")
    verb = TOOL_VERB.get(name, name)
    tgt = _target(name, args)
    return f"{icon} {verb}{' ' + tgt if tgt else ''}"


class Relay:
    """收集事件、批次送出。工具事件會累積，文字回覆立刻送。"""

    def __init__(self, profile: str, thread: str, title: str, pace: str = DEFAULT_PACE,
                 session_label: str = ""):
        self.profile, self.thread, self.title = profile, thread, title
        self.batch_size, self.batch_seconds = PACE[pace]
        self.session_label = session_label
        self.buf: list[str] = []
        self.pending: dict[str, str] = {}  # call_id -> 已格式化的工具行（tool_use 時就定案）
        self.last_flush = time.time()
        self.lock = threading.Lock()
        self.tool_count = 0
        self.started = time.time()
        self.opening: dict | None = None   # 未送出的開工資訊（等 OPENING_DELAY）
        self.opening_sent = False
        self.last_event = time.time()      # 任何事件都更新，心跳據此判定
        self.last_action = ""              # 最後一個工具名＋時間，心跳顯示用
        self.heartbeats = 0
        self.done = False

    def _header(self) -> str:
        return f"🤖 **{self.profile.replace('df', '')}** · {self.title}"

    def maybe_opening(self) -> None:
        """開工訊息延遲送出：任務若在 OPENING_DELAY 內結束就完全不送。"""
        with self.lock:
            if self.opening_sent or self.done or not self.opening:
                return
            if time.time() - self.started < OPENING_DELAY:
                return
            ev, self.opening_sent = self.opening, True
        _send(self.profile, self.thread,
              f"{self._header()}　▶️ 開工\n\n模型 `{ev.get('model', '—')}`"
              + (f" · session `{self.session_label}`" if self.session_label else ""))

    def maybe_heartbeat(self) -> None:
        """長時間無事件時報一次平安，否則 topic 安靜到分不出是在跑還是死了。"""
        with self.lock:
            if self.done or time.time() - self.last_event < HEARTBEAT_AFTER:
                return
            self.last_event = time.time()
            self.heartbeats += 1
            mins = int((time.time() - self.started) / 60)
            tail = f"，最後動作：{self.last_action}" if self.last_action else ""
        _send(self.profile, self.thread, f"{self._header()}　⏳ 執行中（已 {mins} 分鐘{tail}）")

    def flush(self, force: bool = False) -> None:
        with self.lock:
            if not self.buf:
                return
            if not force and len(self.buf) < self.batch_size and time.time() - self.last_flush < self.batch_seconds:
                return
            body = "\n".join(self.buf)
            self.buf.clear()
            self.last_flush = time.time()
        _send(self.profile, self.thread, f"{self._header()}\n\n{body}")

    def on_event(self, ev: dict) -> None:
        kind = ev.get("type")
        now = time.strftime("%H:%M:%S")

        if kind == "system" and ev.get("subtype") == "init":
            with self.lock:
                self.opening = ev            # 先存著，由 ticker 在 OPENING_DELAY 後決定送不送
                self.last_event = time.time()
            return

        if kind == "tool_use":
            cid = ev.get("tool_call_id") or ev.get("name", "")
            self.pending[cid] = _tool_line(ev.get("name", "tool"), ev.get("input"))
            return

        if kind == "tool_result":
            cid = ev.get("tool_call_id") or ev.get("name", "")
            name = ev.get("name", "tool")
            line = self.pending.pop(cid, None) or _tool_line(name, None)
            self.tool_count += 1
            # 正常結果不附摘要：那是整段轉播裡最長的部分，而「做了什麼」已經在行內。
            # 只有失敗時輸出才有資訊量——那時候你需要知道錯在哪。
            if ev.get("is_error"):
                line += f"\n　　⚠️ {tool_summary(ev.get('output') or '')[:100]}"
            with self.lock:
                self.buf.append(line)
                self.last_event = time.time()
                self.last_action = f"{name} 於 {now[:5]}"
            self.flush()
            return

        if kind == "result":
            with self.lock:
                self.done = True             # 阻止 ticker 再送開工／心跳
            self.flush(force=True)
            text = (ev.get("text") or "").strip()
            secs = (ev.get("duration_ms", 0)) / 1000
            dur = f"{secs:.0f}s" if secs < 60 else f"{int(secs // 60)}m{int(secs % 60):02d}s"
            # 統計只留有資訊量的：耗時一定有，工具數 0 時不寫，失敗才標 exit。
            parts = [f"⏱ {dur}"]
            if self.tool_count:
                parts.append(f"🔧 {self.tool_count} 項")
            if ev.get("exit_code"):
                parts.append(f"❌ exit {ev['exit_code']}")
            mark = "❌ 結束" if ev.get("exit_code") else "✅ 完成"
            _send(self.profile, self.thread,
                  f"{self._header()}　{mark}\n\n{text}\n\n──\n" + " · ".join(parts))


def _build_cmd(profile: str, prompt: str, *, thread: str, issue: str | None,
               session: str | None, fresh: bool, workdir: str | None,
               model: str | None, provider: str | None) -> tuple[list[str], str]:
    """組 `hermes … chat` 的指令列，回傳 (cmd, session_label)。

    `--then-wake` 的第二次喚醒走同一支（`#298`）：喚醒者與首個子程序的旗標語意必須一致，
    兩份組裝邏輯會漂移（同族前例見 `devflow_archive.py:665` 的註解）。
    """
    cmd = ["hermes", "-p", profile, "chat", "-q", prompt, "--oneshot", "--format", "stream-json"]
    # 旗標分兩組，插入點不能寫死索引：`-m`／`--provider` 是 `hermes` 的全域旗標，必須在子指令
    # `chat` 之前；`-c`／`--in` 是 `chat` 自己的，必須在它之後。先插全域的會把 `chat` 往後推，
    # 所以每次都重新定位 `chat`（實測寫死 cmd[4:4] 會把 `-c …` 插進 `-m` 與它的值之間）。
    if provider:
        cmd[cmd.index("chat"):cmd.index("chat")] = ["--provider", provider]
    if model:
        cmd[cmd.index("chat"):cmd.index("chat")] = ["-m", model]
    if workdir:
        # I2：coder 不在主 checkout 工作。--in 讓子程序在 worktree 內啟動，
        # 它的 terminal/file 工具因此以那裡為基準。
        at = cmd.index("chat") + 1
        cmd[at:at] = ["--in", workdir]
    if not fresh:
        # 預設續接：同一張單的多次派工共用 context，manager 記得上一輪做了什麼。
        # 這也讓封存時撈得到——session 有穩定名稱，不必靠時間窗口猜。
        name = session or (f"issue-{issue}" if issue else f"thread-{thread}")
        at = cmd.index("chat") + 1
        cmd[at:at] = ["-c", name, "--create-if-missing"]
        return cmd, name
    return cmd, ""


def _run_child(cmd: list[str], *, profile: str, thread: str, title: str, pace: str,
               session_label: str, log: pathlib.Path) -> int:
    """跑一個子程序、全程轉播，並把原始事件流與 stderr 寫進 `log`。回傳 rc。

    log 的用途（`AC-2`）：`--then-wake` 喚醒的是新的 oneshot，畫面已經不在；
    它只憑 forge（`R5`）加這個檔接續，所以必須是原始 stream-json 行，不是摘要。
    """
    relay = Relay(profile, thread, title, pace, session_label)

    # 背景定時 flush：工具數不足 BATCH_SIZE 時也不會卡著不送
    stop = threading.Event()

    def ticker() -> None:
        while not stop.wait(5):
            relay.flush()
            relay.maybe_opening()
            relay.maybe_heartbeat()

    threading.Thread(target=ticker, daemon=True).start()

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            stdin=subprocess.DEVNULL, text=True, bufsize=1,
                            env=_child_env(profile))

    # stderr 必須有人持續讀走。只在結束後 read() 會讓子程序寫滿管線緩衝而卡住，
    # 接著 proc.wait() 永遠等不到 —— 實測就是這樣掛掉並被外層 timeout 殺成 exit 2。
    err_lines: list[str] = []

    def drain_err() -> None:
        for line in proc.stderr:  # type: ignore[union-attr]
            err_lines.append(line)

    err_thread = threading.Thread(target=drain_err, daemon=True)
    err_thread.start()

    out_lines: list[str] = []
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            out_lines.append(line)
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                relay.on_event(json.loads(line))
            except json.JSONDecodeError:
                continue
    finally:
        stop.set()
        proc.wait()
        err_thread.join(timeout=5)
        relay.flush(force=True)
        # 寫 log 失敗不該讓任務跟著死（同 `_send` 的理由）——但要讓人看到。
        try:
            log.write_text("".join(out_lines)
                           + ("\n── stderr ──\n" + "".join(err_lines) if err_lines else ""))
        except OSError as exc:
            print(f"[relay] ⚠️ log 寫入失敗（{log}）：{exc}", file=sys.stderr)

    if proc.returncode:
        err = "".join(err_lines)[-400:]
        _send(profile, thread,
              f"🤖 **{profile}** ❌ 子程序 exit {proc.returncode}\n\n```\n{err}\n```")
    return proc.returncode


def _wake_prompt(issue: str | None, log: pathlib.Path, rc: int, child_profile: str) -> str:
    """交給被喚醒者的 prompt。只有「哪張單、log 在哪、rc 多少」三項事實。

    relay 不寫「接下來請 push」之類的指示：`rc=0` 與「該進下一步」不等價（coder 可能依
    `L3` 正當停下、commit 可能不完整），判斷那個差別要讀 issue 留言與 verdict，
    那是 workflow 知識，relay 不持有（`#298` 材料 ③，裁決位 2026-10-07）。
    """
    return (
        f"relay 續接通知：`#{issue}` 的子程序（`-p {child_profile}`）已退出，rc={rc}。\n"
        f"子程序的事件流 log：`{log}`\n\n"
        f"這是一個新的 oneshot，你看不到上一輪的畫面。"
        f"材料自己去 forge 讀（`gh issue view {issue} --comments`），"
        f"依該單目前的狀態判下一步；log 只是現場，不是指示。"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("thread", help="Telegram topic 的 thread id")
    ap.add_argument("prompt", nargs="?", default="", help="交給子程序的指令")
    ap.add_argument("-p", "--profile", default="dfmgr")
    ap.add_argument("--file", help="從檔案讀 prompt（取代位置參數）")
    ap.add_argument("--issue", help="標題顯示的單號，例如 267")
    ap.add_argument("--then-wake", dest="then_wake", metavar="PROFILE",
                    help="子程序退出後，由 relay 自己以同一 thread／issue 再喚醒這個 profile。"
                         "帶 --issue 時為必給（那一輪屬於某張單的執行流程，需要銜接）")
    ap.add_argument("--pace", choices=sorted(PACE), default=DEFAULT_PACE,
                    help=f"轉播節奏（預設 {DEFAULT_PACE}）：instant 3則/8秒、normal 6則/15秒、quiet 10則/30秒")
    ap.add_argument("--session", metavar="NAME",
                    help="session 名稱。預設 issue-<單號>（同一張單累積 context）；"
                         "無單號時退回 thread-<id>")
    ap.add_argument("--fresh", action="store_true",
                    help="不續接，每次全新 session（預設會續接）")
    ap.add_argument("--in", dest="workdir", metavar="DIR",
                    help="子程序的工作目錄（實作位必給 worktree 路徑，滿足 I2）")
    ap.add_argument("-m", "--model", metavar="ID",
                    help="覆寫該 profile 的模型（配額耗盡時的一次性切換，不改 config.yaml）")
    ap.add_argument("--provider", metavar="NAME",
                    help="覆寫 provider。半價備援用 or_flex_proxy（需 or-flex-proxy.py 在跑）")
    args = ap.parse_args()

    # ── 兩個拒絕條件：都必須在派子程序之前（`AC-3`／`AC-4`），否則 coder 已經跑起來才報錯 ──
    if args.issue and not args.then_wake:
        # 判準用 `--issue` 而不是 profile 名：後者要 relay 硬編碼 seat 的角色名，
        # 比 `--then-wake` 本身更接近「懂 workflow」（裁決位 2026-10-07 的否決理由）。
        # 不帶 `--issue` ＝ 一次性操作，不需鏈結——那一列必須照舊能跑。
        print("[relay] --issue 需同時帶 --then-wake <profile>；"
              f"例：devflow_relay.py {args.thread} --file x.md "
              f"-p {args.profile} --issue {args.issue} --then-wake dfmgr",
              file=sys.stderr)
        return 2

    depth = _current_depth()
    if depth >= MAX_RELAY_DEPTH:
        chain = os.environ.get(CHAIN_ENV, "") or "(未記錄)"
        print(f"[relay] 鏈結過深，拒絕派子程序："
              f"{DEPTH_ENV}={depth} ≥ {MAX_RELAY_DEPTH}（MAX_RELAY_DEPTH={MAX_RELAY_DEPTH}）\n"
              f"[relay] 已有的鏈：{chain} → (本次想派) {args.profile}"
              + (f" → (then-wake) {args.then_wake}" if args.then_wake else "") + "\n"
              f"[relay] 深度只計巢狀，不隨輪次累加；撞上限表示有 relay 在 relay 裡遞迴，"
              f"請改由最外層派工。",
              file=sys.stderr)
        return 2

    prompt = pathlib.Path(args.file).read_text() if args.file else args.prompt
    if not prompt.strip():
        return ap.error("prompt 不可為空（用位置參數或 --file）")

    cmd, session_label = _build_cmd(
        args.profile, prompt, thread=args.thread, issue=args.issue, session=args.session,
        fresh=args.fresh, workdir=args.workdir, model=args.model, provider=args.provider)

    log = _log_path(args.issue, args.profile)
    rc = _run_child(cmd, profile=args.profile, thread=args.thread,
                    title=f"`#{args.issue}`" if args.issue else f"thread {args.thread}",
                    pace=args.pace, session_label=session_label, log=log)

    if args.then_wake:
        # 銜接在 relay 這一層，不在任何 seat 的 turn 裡——故不需要等待（`#287` 證明等不住）。
        # 喚醒者一律續接 `issue-<N>`（同一 seat 的續接，不給 `--fresh`）。**不對它再
        # then-wake**：那會無限鏈，深度上限只是兜底，不是正解。
        #
        # 三項**不**承襲（`#298` 第 2 輪 `BLOCK 2`）：
        #   `--in`     worktree 是實作位的，被喚醒的管理位在主 checkout。
        #   `-m`／`--provider`  `I7`：覆寫只作用於該次子程序（配額耗盡時的一次性切換），
        #       被喚醒者是另一個 seat 的另一輪，須用**自己 profile 的綁定**。承襲等於
        #       替它換了綁定，而換綁定不是 relay 的事。
        wake_cmd, wake_label = _build_cmd(
            args.then_wake, _wake_prompt(args.issue, log, rc, args.profile),
            thread=args.thread, issue=args.issue, session=None, fresh=False,
            workdir=None, model=None, provider=None)
        _run_child(wake_cmd, profile=args.then_wake, thread=args.thread,
                   title=(f"`#{args.issue}` · 續接" if args.issue
                          else f"thread {args.thread} · 續接"),
                   pace=args.pace, session_label=wake_label,
                   log=_log_path(args.issue, args.then_wake))

    # 回傳的仍是受託子程序的 rc：喚醒者的成敗是它自己那一輪的事，不該蓋掉這一輪的結果。
    return rc


if __name__ == "__main__":
    sys.exit(main())
