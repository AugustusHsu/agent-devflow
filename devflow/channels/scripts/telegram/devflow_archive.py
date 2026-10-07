#!/usr/bin/env python3
"""devflow topic 封存工具。

封存 = 匯出（MD 人讀 + JSON 全量）→ 發到 archives topic → 刪除原 topic → 清 cache。

用法：
    devflow_archive.py scan                    掃描**本 kit 管理過的** topic（標記 ∪ cache ∪ archives）
    devflow_archive.py scan --full             掃描**群組實際存在的** topic（全區間探活，慢）
    devflow_archive.py export <thread>         只匯出到 ~/.hermes/archives/topics/
    devflow_archive.py publish <thread>        匯出並發到 archives topic（不刪原 topic）
    devflow_archive.py archive <thread> --yes  publish + 刪除原 topic + 清 cache

關鍵設計（踩過的坑）：
  * manager 的工作記錄 thread_id 是 None（headless `chat --oneshot`），
    只撈 `thread_id=<N>` 會漏掉整段執行軌跡。以時間窗口補撈，按時間軸併起來。
  * cache（devflow-topics.json）會殘留已刪除的 thread，只有探活是權威。
    `scan` 預設只探「本 kit 管理過的 thread id」（標記 ∪ cache ∪ archives），
    `--full` 才掃全區間——探活成本因此與 thread id 上界脫鉤（`#296`）。
  * Telegram 的 MD 檢視器不支援 <details> 折疊與 <a id> 錨點，但支援
    巢狀清單、表格、刪除線、核取清單（2026-09-29 實測）。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import re
import sqlite3
import sys
import tempfile
import urllib.parse
import urllib.request

# marker 的 grammar 一律走共用模組（`CH3` 判定式的實作）。本檔於 `#285` **只**把
# `issue_meta` 的反向查找（原 `:394` 的未錨定 `re.search`）改走它；`scan`／`publish`／
# cache 三缺陷屬 `#287`，本單一字不動。同層 import，零 import-path 操作（`AC-10`）。
import _marker

HERMES = pathlib.Path.home() / ".hermes"
PROFILES = ("dfcoord", "dfmgr", "dfrev", "dfimpl")
CHAT = "-1003546152597"
ARCHIVES_THREAD = 261
# General（thread 1）也要撈：協調者在 General 收到派工時，它自己的 session 綁的是 thread 1，
# 發到單 topic 的訊息是 `hermes send` 出去的、不落在該 topic 的 session。只撈 thread=<N>
# 會漏掉整段協調軌跡（#247 實測：38 則 vs 實際 378 則，漏 90%）。
GENERAL_THREAD = "1"
OUT = HERMES / "archives" / "topics"
CACHE = HERMES / "cache" / "devflow-topics.json"

BOT = {
    "dfcoord": ("coordinator", "@devflow_coord_bot"),
    "dfmgr": ("manager", "@devflow_mgr_bot"),
    "dfrev": ("reviewer", "@devflow_rev_bot"),
    "dfimpl": ("implementer", "@devflow_impl_bot"),
}


# ── Telegram ────────────────────────────────────────────────────────────────
def _token() -> str:
    env = HERMES / "profiles" / "dfcoord" / ".env"
    for line in env.read_text().splitlines():
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"no TELEGRAM_BOT_TOKEN in {env}")


def api(method: str, **params) -> dict:
    url = f"https://api.telegram.org/bot{_token()}/{method}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=30) as fh:
            return json.load(fh)
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode())
        except Exception:
            return {"ok": False, "description": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "description": str(exc)}


def esc_html(text: str) -> str:
    """把外部字串轉義成 Telegram HTML parse mode 的合法內文。

    只處理 HTML 的三個實體字元，且 `&` **必須最先**——否則 `<` → `&lt;` 產生的
    `&` 會被後續的 `&` 規則二次轉義成 `&amp;lt;`（`#293` `AC-1` 的鑑別力）。

    底線、星號、反引號一律**不動**：HTML parse mode 不以它們為實體起點，這正是
    `#293` 捨 Markdown 改用 HTML 的理由（`#291` 封存時 issue 標題裡 `_marker.py`
    的裸底線被 Markdown 當成斜體起點，`sendDocument` 回 `can't parse entities`）。

    界線（`#293` `AC-6`）：本函式只用於**要被 parse mode 解析的文字**（caption、
    訊息文字）。`build_md` 寫進 `.md` 檔的內文由檢視器渲染、不經 Telegram 解析，
    一律不得經過本函式。
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_document(thread: int, path: pathlib.Path, caption: str = "") -> dict:
    """multipart 上傳，urllib 手工組（避免依賴 requests）。"""
    boundary = "----devflowarchive" + _dt.datetime.now().strftime("%H%M%S%f")
    parts: list[bytes] = []

    def field(name: str, value: str) -> None:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )

    field("chat_id", CHAT)
    field("message_thread_id", str(thread))
    if caption:
        field("caption", caption[:1024])
        # HTML 而非 Markdown（`#293`）：caption 要插入 issue 標題這類外部字串，
        # HTML 的實體起點只有 `&` `<` `>` 三個、可由 `esc_html` 機械轉義乾淨；
        # Markdown 的 `_` `*` `` ` `` 散落在正常文字裡（`_marker.py`），
        # 轉義清單長且易漏。呼叫端的 caption 須自行對外部值套 `esc_html`。
        field("parse_mode", "HTML")
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="document"; '
        f'filename="{path.name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
    )
    parts.append(path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{_token()}/sendDocument",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as fh:
            return json.load(fh)
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode())
        except Exception:
            return {"ok": False, "description": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "description": str(exc)}


# ── 訊息蒐集 ────────────────────────────────────────────────────────────────
def _db(profile: str) -> pathlib.Path:
    return HERMES / "profiles" / profile / "state.db"


def _rows(profile: str, sql: str, args: tuple) -> list[dict]:
    path = _db(profile)
    if not path.exists():
        return []
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        cols = ("id", "role", "content", "tool_name", "tool_calls", "timestamp",
                "display_kind", "session_id")
        return [dict(zip(cols, r), profile=profile) for r in conn.execute(sql, args)]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


_SEL = ("select m.id,m.role,m.content,m.tool_name,m.tool_calls,m.timestamp,"
        "m.display_kind,m.session_id ")


def collect(thread: str, since: float | None = None, until: float | None = None) -> list[dict]:
    """topic 內的訊息 + 同時段的 headless 與 General 記錄，按時間軸合併。

    三個來源，缺一不可：
      * `thread_id=<N>`  該 topic 自己的 session（裁決位在 topic 內發言時開的）
      * `thread_id IS NULL`  headless 子程序（manager／implementer／reviewer 的工作軌跡）
      * `thread_id='1'`  General——協調者在 General 收到派工時，它整段工作都記在 thread 1 的
        session 裡；發到單 topic 的訊息是 `hermes send` 出去的，不會落在該 topic 的 session。

    時間窗：預設由前兩者的訊息範圍推出，但那個範圍可能遠窄於實際工作區間（`#247` 的 topic
    session 只有最後三分鐘）。`since`／`until` 可明確指定，指定時直接取代推導值。
    """
    rows: list[dict] = []
    for prof in PROFILES:
        rows += _rows(prof, _SEL + "from sessions s join messages m on m.session_id=s.id "
                      "where s.thread_id=? and m.role!='session_meta' order by m.id", (thread,))
    lo = since if since is not None else (min(r["timestamp"] for r in rows) - 300 if rows else None)
    hi = until if until is not None else (max(r["timestamp"] for r in rows) + 300 if rows else None)
    if lo is not None and hi is not None:
        for prof in PROFILES:
            rows += _rows(prof, _SEL + "from sessions s join messages m on m.session_id=s.id "
                          "where m.role!='session_meta' and m.timestamp between ? and ? "
                          "and (s.thread_id is null or s.thread_id=?) order by m.id",
                          (lo, hi, GENERAL_THREAD))
    rows.sort(key=lambda r: (r["timestamp"], r["profile"], r["id"]))

    # 同一則真人訊息會被多個 profile 各收一份
    seen: dict = {}
    out: list[dict] = []
    for m in rows:
        if kind(m) == "human":
            key = (m["timestamp"], clean(m["content"])[:80])
            if key in seen:
                seen[key].setdefault("recips", []).append(m["profile"])
                continue
            m["recips"] = [m["profile"]]
            seen[key] = m
        out.append(m)
    return out


# ── 格式化 ──────────────────────────────────────────────────────────────────
def hm(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def full(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def day(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def clean(text: str | None) -> str:
    out = text or ""
    if out.startswith("[Augustus] "):
        out = out[11:]
    out = re.sub(r"\n*Gateway message origin \(JSON data[^\n]*\n\{.*?\}\n"
                 r"(?:Do not guess[^\n]*\n?)?", "\n", out, flags=re.S)
    return out.strip()


def first_line(text: str | None, limit: int = 90) -> str:
    for line in (text or "").split("\n"):
        line = line.strip()
        if line and line not in ("{", "}", "[", "]"):
            return line[:limit] + ("…" if len(line) > limit else "")
    return ""


def _lenient(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        if "Extra data" in str(exc):
            try:
                return json.JSONDecoder().raw_decode(raw)[0]
            except Exception:  # noqa: BLE001
                return None
    except Exception:  # noqa: BLE001
        pass
    return None


def tool_summary(content: str | None) -> str:
    body = (content or "").strip()
    data = _lenient(body)
    if isinstance(data, dict):
        rc = data.get("exit_code", data.get("returncode"))
        tail = f"　`exit {rc}`" if isinstance(rc, int) and rc != 0 else ""
        for key in ("output", "content", "stdout", "result", "body", "summary"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                inner = _lenient(val)
                if isinstance(inner, dict):
                    for k2 in ("output", "content", "body", "stdout"):
                        if isinstance(inner.get(k2), str) and inner[k2].strip():
                            return first_line(inner[k2]) + tail
                    return "JSON{" + ", ".join(list(inner)[:3]) + "}" + tail
                return first_line(val) + tail
        if "responses" in data:
            try:
                return "回覆：" + " ／ ".join(r.get("question", "")[:40] for r in data["responses"])
            except Exception:  # noqa: BLE001
                pass
        if "matches" in data:
            return f"{len(data['matches'])} 個結果"
        if data.get("error"):
            return f"⚠️ {first_line(str(data['error']), 60)}"
        return "JSON{" + ", ".join(list(data)[:3]) + "}" + tail
    if isinstance(data, list):
        return f"[{len(data)} 項]"
    return first_line(body)


def kind(msg: dict) -> str:
    if msg["display_kind"] == "internal_notification":
        return "gateway"
    if msg["display_kind"] == "hidden":
        return "hidden"
    return "human" if msg["role"] == "user" else msg["role"]


def build_md(thread: str, rows: list[dict], title: str, issue: str | None,
             state: str | None, stem: str) -> str:
    profs = sorted({m["profile"] for m in rows if kind(m) == "assistant"})
    counts: dict[str, int] = {}
    for m in rows:
        label = {"human": "真人", "gateway": "系統通知", "tool": "工具呼叫",
                 "hidden": "隱藏"}.get(kind(m)) or BOT.get(m["profile"], (m["profile"],))[0]
        counts[label] = counts.get(label, 0) + 1

    days = sorted({day(m["timestamp"]) for m in rows})
    headless = sum(1 for m in rows if m.get("session_id", "") and kind(m) != "human")
    idx = [m for m in rows if kind(m) == "human"
           or (kind(m) == "assistant" and clean(m["content"]))]

    lines = [f"# {'#' + issue if issue else 'General'} · {title}\n"]
    lines.append(f"> **時間**：{full(rows[0]['timestamp'])} → "
                 + (hm(rows[-1]['timestamp']) if len(days) == 1 else full(rows[-1]['timestamp'])) + "  ")
    lines.append(f"> **群組**：`devflow`（Telegram forum，chat `{CHAT}`）  ")
    lines.append(f"> **主題**：thread `{thread}`  ")
    if issue:
        lines.append(f"> **議題**：[#{issue}](https://github.com/AugustusHsu/agent-devflow/issues/{issue})"
                     f" — {title}（{state}）  ")
    else:
        lines.append("> **議題**：無（General 常駐討論區）  ")
    for i, prof in enumerate(profs):
        name, handle = BOT.get(prof, (prof, f"@{prof}"))
        label = "**參與助理**" if i == 0 else "　　　　　　"
        lines.append(f"> {label}：🤖 **{name}** `{handle}` — profile `{prof}`  ")
    lines.append(f"> **訊息統計**：共 {len(rows)} 則 — "
                 + "、".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1])) + "  ")
    lines.append(f"> **對話往返**：{len(idx)} 次（真人 {counts.get('真人', 0)}、"
                 f"助理回覆 {len(idx) - counts.get('真人', 0)}）  ")
    lines.append(f"> **完整記錄**：`{stem}.json`（含工具原文等全欄，以 `id=N` 對應）  ")
    lines.append(f"> **匯出時間**：{_dt.datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    if idx:
        lines.append(f"**對話索引（{len(idx)}）**　時間戳可用搜尋跳至該段\n")
        for m in idx:
            who = "👤 **Augustus**" if kind(m) == "human" else \
                f"🤖 **{BOT.get(m['profile'], (m['profile'],))[0]}**"
            lines.append(f"- `{hm(m['timestamp'])}`　{who}")
        lines.append("")
    lines.append("---\n")

    buf: list[str] = []
    buf_prof: str | None = None
    last: tuple | None = None
    had = False

    def flush() -> None:
        nonlocal had, buf_prof
        had = bool(buf)
        if buf:
            name = BOT.get(buf_prof, (buf_prof or "—",))[0]
            lines.append(f"- 🤖 **{name}** 執行 {len(buf)} 項")
            lines.extend(buf)
            lines.append("")
            buf.clear()
        buf_prof = None

    for m in rows:
        k = kind(m)
        body = clean(m["content"])
        name = BOT.get(m["profile"], (m["profile"],))[0]
        if k in ("tool", "hidden", "gateway"):
            if buf_prof and m["profile"] != buf_prof:
                flush()
            buf_prof = m["profile"]
            if k == "tool":
                buf.append(f"  - `{hm(m['timestamp'])}` 🔧 **{m['tool_name'] or 'tool'}** — "
                           f"{tool_summary(m['content'])} · `id={m['id']}`")
            elif k == "hidden":
                buf.append(f"  - `{hm(m['timestamp'])}` 🙈 系統隱藏訊息 · {len(body)} 字元 · `id={m['id']}`")
            else:
                proc = re.search(r"proc_[0-9a-f]+", body)
                cmd = re.search(r"Command: (.+?)(?:\n\n|\nOutput:|$)", body, re.S)
                line = (f"  - `{hm(m['timestamp'])}` ⚙️ **系統通知** — 背景程序 "
                        f"`{proc.group(0) if proc else '—'}` "
                        f"{'正常結束 exit 0' if 'exit code 0' in body else '結束'} · `id={m['id']}`")
                if cmd:
                    line += f"\n    `{' '.join(cmd.group(1).split())[:110]}…`"
                buf.append(line)
            continue
        if k == "assistant" and not body:
            last = ("assistant", m["profile"])
            continue
        flush()
        if k == "human":
            recips = m.get("recips", [])
            to = "".join(f"　→ `{BOT.get(p, (p,))[0]}`" for p in recips) if len(recips) > 1 else ""
            lines.append(f"#### `{hm(m['timestamp'])}`　👤 **Augustus**{to}\n\n{body}\n")
            last = ("human", None)
        else:
            if last == ("assistant", m["profile"]) and not had:
                lines.append(body + "\n")
            else:
                lines.append(f"#### `{hm(m['timestamp'])}`　🤖 **{name}**\n\n{body}\n")
            last = ("assistant", m["profile"])
    flush()
    return "\n".join(lines)


def dump_json(thread: str, rows: list[dict], stem: str, issue: str | None) -> pathlib.Path:
    path = OUT / f"{stem}.json"
    path.write_text(json.dumps(
        {"thread_id": thread, "issue": issue,
         "exported_at": _dt.datetime.now().isoformat(), "messages": rows},
        ensure_ascii=False, indent=1))
    return path


# ── issue 中介資料 ──────────────────────────────────────────────────────────
def issue_meta(thread: str) -> tuple[str | None, str, str | None]:
    """(issue 號, 標題, 狀態)。cache 優先，其次掃 issue body 的 topic marker。

    封存完成後 cache 會被清掉，重跑 export/publish 就查不到 issue 號了 —— 改由 forge
    回填：marker (`<!-- devflow:topic thread=N -->`) 是 `ensure` 寫進 issue body 的，
    topic 刪除後仍留著。

    ⚠ **cache 命中只代表「曾經有過這個對應」，不代表該 thread 還存在**（`#287`
    `AC-6`）。本函式**刻意不**為 cache 命中補打一次 API 驗活：它在
    `cmd_publish`／`cmd_archive` 的熱路徑上，每次多一次網路往返的代價落在每一次
    封存上。分工是——**cache 只用於取 issue 號與標題（以及 issue 自身的 state），
    thread 是否存在由呼叫端既有的探活負責**（`cmd_archive` 的 `deleteForumTopic`
    本就會回報失敗，`devflow_topic.ensure` 有 `_alive`）。回傳的第三個元素是
    **issue 的 state（OPEN／CLOSED）**，不是 thread 的存活狀態；本函式的回傳值
    不宣稱該 thread 存在。

    掃到 `T>1` 的 issue 時 raise `_marker.InvalidMarker`——**不**退回 `thread NNNN`
    的 fallback、**不**續掃。下面的 `except Exception` 是給「forge 不可用」用的，
    INVALID 必須穿過它（`#285` `BLOCK-1` 第 2 輪：續掃可能在另一張 issue 命中同一
    thread 而把匯出檔掛到那張單）。

    迴圈**掃完整個列表才回傳**，不在第一個命中就 return（`#285` `BLOCK-1` 第 3 輪）：
    早退使「停不停下」取決於 `gh issue list` 的回傳順序——INVALID 的單排在命中之後
    就不會被 `has_topic` 看到。同一份資料只改順序就改變判定，那不是判定。
    掃完才決定也使下述「多張單主張同一 thread」得以被發現。

    兩種 INVALID 都停下：
      * 任一張 issue 的 body 自身 `T>1`（由 `has_topic` raise）
      * 掃完有**多張不同 issue** 都合法命中同一 thread（本函式 raise）。
        理論上不該發生（`ensure` 的 upsert 對單張單維持 `T=1`，而 thread id 由
        Telegram 配發、不重複），但真的發生時「該 thread 屬哪一張單」沒有單一答案，
        與 `T>1` 同型，故同樣停下而非取第一個——取第一個就是把匯出檔掛到
        「排序上剛好在前」的那張單，正是本單在修的病。
    """
    if CACHE.exists():
        data = json.loads(CACHE.read_text() or "{}")
        for num, rec in data.items():
            if str(rec.get("thread_id")) == str(thread):
                return num, rec.get("title", f"thread {thread}"), rec.get("state", "").upper()
    if str(thread) == "1":
        return None, "群組常駐討論", None
    try:
        import subprocess
        out = subprocess.run(
            ["gh", "issue", "list", "-R", "AugustusHsu/agent-devflow", "--state", "all",
             "--limit", "300", "--json", "number,title,body,state"],
            capture_output=True, stdin=subprocess.DEVNULL, timeout=60, text=True).stdout
        items = json.loads(out or "[]")
        by_num = {str(it["number"]): it for it in items}
        # 掃描走共用模組（`#287` `AC-1`／`AC-2`）：`gh` 查詢留在這裡，marker 解析
        # 交給 `_marker.scan_topic`。對外行為一字不變的三個要點：
        #   1. 不給 `on_invalid` → `T>1` 的 `InvalidMarker` 直接穿出去，被下面的
        #      `except _marker.InvalidMarker: raise` 接住再拋，不落入 `except Exception`。
        #   2. **掃完才回傳**：共用函式自己掃完整個列表，故「多張單主張同一 thread」
        #      仍發現得了（`#285` `BLOCK-1` 第 3 輪）。
        #   3. **只掃 `topic` 一式**，且仍以 `kind == "topic"` 過濾。兩個理由：
        #      (a) 本函式的語意是「thread → 寫過 topic 標記的那張單」，已封存的單
        #          （只剩 `archived` 標記）不得被命中，否則對外行為就變了；
        #      (b) 若改掃兩式，某張單的 `A>1` 會在這裡變成新的 `InvalidMarker`
        #          ——本函式原本只對 `T>1` 停下，那同樣是對外行為的改變。
        hits = [by_num[num] for num, tid, kind
                in _marker.scan_topic((str(it["number"]), it.get("body") or "")
                                      for it in items)
                if kind == "topic" and str(tid) == str(thread)]
        if len(hits) > 1:
            raise _marker.InvalidMarker(
                "topic",
                [f"#{h['number']} {h.get('title', '')}".rstrip() for h in hits],
                f"反向查找 thread={thread}",
                summary=f"thread={thread} 被 {len(hits)} 張不同的 issue 主張",
            )
        if hits:
            return (str(hits[0]["number"]), hits[0]["title"],
                    (hits[0].get("state") or "").upper())
    except _marker.InvalidMarker:
        raise                      # INVALID 要停下，不是 forge 不可用——不得被下面吞掉
    except Exception:  # noqa: BLE001 — forge 不可用時退回 thread 命名
        pass
    return None, f"thread {thread}", None


def stem_for(thread: str, issue: str | None) -> str:
    """檔名。issue 號是唯一穩定的識別；標題會被編輯，截斷後也總是漏掉關鍵字。
    內容要看什麼單，MD 表頭第一行就是完整標題。"""
    return issue if issue else f"thread{thread}"


# ── 指令 ────────────────────────────────────────────────────────────────────
# `scan` 的 thread id 上界（`#287` `AC-3`）。寫死值只是**零命中時**的退路，不是來源。
SCAN_HI_FLOOR = 400        # 歷史下限：`#247` 時 thread id 已到 669，故 400 僅為地板
SCAN_HI_MARGIN = 50        # 餘裕：最大已知 id 之後可能已新建、尚未寫進任何 issue body


def scan_upper_bound(items, *, floor: int = SCAN_HI_FLOOR,
                     margin: int = SCAN_HI_MARGIN, on_invalid=None) -> int:
    """給定一批 `(issue, body)` → `scan` 要探到的 thread id 上界 `hi`。

    **純函式、零 I/O**（`#287` `AC-3` 要求可對純字串 fixture 驗證）：`gh` 查詢在
    `_forge_scan_items`，marker 解析在 `_marker`，本函式只做「取最大值加餘裕」。

    `topic` 與 `archived` 兩式**都算**：封存過的單在 forge 上只剩 `archived` 標記
    （`#291` 之後），而它承載的 thread id 一樣是群組活動上界的證據
    （`AC-3`(c)）。零命中 → 回 `floor`（`AC-3`(b)）。

    `T>1`／`A>1` 的單：交給 `on_invalid` 並跳過（預設靜默跳過）。這裡不停下——
    本函式算的是**探測範圍**，不是「該單的分區是哪一個」，`CH3` 的 INVALID 收容
    分支管的是後者。`cmd_scan` 會把 `on_invalid` 接到 stderr，人工處置的線索不丟。
    """
    rows = list(items)
    hits = (_marker.scan_topic(rows, on_invalid=on_invalid)
            + _marker.scan_archived(rows, on_invalid=on_invalid))
    ids = [int(tid) for _num, tid, _kind in hits]
    return max(ids) + margin if ids else floor


def _forge_scan_items(repo: str = "AugustusHsu/agent-devflow"):
    """從 forge 取 `[(issue, body), …]`。`scan` 上界的**來源**（`#287` `AC-3`）。

    ⚠ **代價**：`scan` 因此從「純本機讀 cache」變成**依賴一次 `gh` 查詢**——慢
    （掃 300 張單的 body）、要網路、forge 不可用時取不到。接受這個代價的理由是
    舊來源（cache）**與封存動作耦合**：封存會把條目從 cache 移除，於是封存得越
    乾淨 `scan` 能探到的範圍越小（`#287` 材料 ①；實測 cache 為 `{}` 時 `hi=450`
    而現行 thread id 已到 3724，`scan` 探不到任何現存 topic）。issue body 的
    `topic`／`archived` 標記不隨封存消失 —— **這個來源與封存動作無關，正是循環
    依賴的斷點**。
    """
    import subprocess
    out = subprocess.run(
        ["gh", "issue", "list", "-R", repo, "--state", "all",
         "--limit", "300", "--json", "number,body"],
        capture_output=True, stdin=subprocess.DEVNULL, timeout=60, text=True).stdout
    return [(str(it["number"]), it.get("body") or "") for it in json.loads(out or "[]")]


def scan_candidates(items, cache, archives_thread, *, full=False, hi=None,
                    on_invalid=None) -> list[int]:
    """決定 `scan` 要探活哪些 thread id。**純函式、零 I/O**（`#296` `AC-1`）。

    預設（`full=False`）＝「**本 kit 管理過的** thread id」：

        forge 的 `topic`／`archived` 標記 ∪ cache 的 `thread_id` ∪ {`archives_thread`}

    `full=True` ＝ `sorted(range(2, hi))`，即 `#287` 的全區間掃描（`hi` 必須給）。

    **為什麼改**（`#296` 材料 ①）：`#287` 把上界來源從 cache 改為 forge 標記是對的
    （斷掉「封存清 cache → `scan` 探得越少」的循環依賴），但探活仍是對 `range(2, hi)`
    的連續區間掃描 —— 成本 `O(上界)`，而 `thread_id` 單調成長且 forge 標記不隨封存
    消失，故**上界只增不減、再無天花板**。2026-10-08 實測：上界 4442 個 ／ 候選 25 個
    ＝ 178 倍浪費，且分子每天 ＋400 餘而分母只隨單數成長，**倍數本身單調上升**。
    推上界的那組標記本身就是候選集合，現行實作只取了它的 `max()`。

    **三個來源都有貢獻**，少一個就漏候選（`AC-3` 以鑑別力守）：

      * forge 標記 —— 本 kit 建過分區的單，封存後只剩 `archived` 式仍承載 thread id。
      * cache —— 補「`ensure` 建了 topic 但寫回 forge 失敗」的單（`#285` ⑤-c）：
        那種單在 forge 上**沒有**標記，只有 cache 記得。
      * `archives_thread` —— 封存目的地本身沒有 issue、不會有標記。

    標記解析一律經 `_marker`（`scan_topic`／`scan_archived`），**不自備正則**
    （`#285` `AC-7` 的單一來源原則：錨定 `^…$` 只有一份實作）。
    `T>1`／`A>1` 的單交給 `on_invalid` 並**跳過該單**，其餘 id 仍在集合內 ——
    一張壞單不得吃掉整個集合（`AC-2`）；語意與 `scan_upper_bound` 一致。

    `cmd_scan` 不得另算任何 id 集合（`AC-1`）：候選的定義只在這裡。
    """
    if full:
        if hi is None:
            raise ValueError("full=True 時必須給 hi（全區間掃描的上界）")
        return sorted(range(2, int(hi)))

    rows = list(items)

    # **任一式 INVALID → 整張單跳過**（`_marker.py:141`：「跳過時整張都跳過（不續掃
    # 它的另一式）：該單的分區「是哪一個」已無單一答案」）。
    #
    # ⚠ 第 1 輪的實作把 `on_invalid` 直接交給兩次呼叫，於是 `_marker` 的「整張跳過」
    # 只在**各自那一次**內成立：`T>1` ＋ `A=1` 的單，`scan_topic` 跳過了它，
    # `scan_archived` 仍回它的 hit —— 壞單的 archived id 因此進了候選
    # （`#296` `R1` 第 1 輪 `BLOCK 1`，複驗得 `[7999]`／`[8001]`，期望 `[]`）。
    # 故在這裡收集 INVALID 的**單號**，兩式都掃完後把該單的**全部** hit 濾掉。
    # 兩式分別呼叫是 `AC-1` 的明文（解析一律經 `scan_topic`／`scan_archived`），
    # 跨兩次呼叫的「整張跳過」只能在呼叫端收攏。
    #
    # `on_invalid is None` 時**不**包裝 → `InvalidMarker` 原樣穿出去，與
    # `scan_upper_bound` 的預設行為一致（跳過是「給了 `on_invalid`」才有的語意）。
    bad: set[str] = set()
    report = on_invalid

    def _collect(exc, issue):
        # 同一單只轉發一次：`T>1` 且 `A>1` 時兩式都會回報，但那是**一張**壞單。
        first = issue not in bad
        bad.add(issue)
        if first:
            report(exc, issue)

    cb = None if report is None else _collect
    hits = (_marker.scan_topic(rows, on_invalid=cb)
            + _marker.scan_archived(rows, on_invalid=cb))
    ids = {int(tid) for issue, tid, _kind in hits if issue not in bad}

    for rec in (cache or {}).values():
        tid = (rec or {}).get("thread_id") if isinstance(rec, dict) else None
        if tid is not None:
            # cache 的值歷來是 int，但損壞／手改的 cache 不得讓整個 scan 停擺
            # （`cmd_scan` 對損壞 cache 的容忍見其讀取段）。
            try:
                ids.add(int(tid))
            except (TypeError, ValueError):
                pass

    if archives_thread is not None:
        ids.add(int(archives_thread))

    return sorted(ids)


def scan_sources(items, cache, archives_thread, *, on_invalid=None) -> dict:
    """候選集合的**來源分解**，供 `cmd_scan` 的那一行輸出（`#296` `AC-5`）。

    回 `{"marks": [...], "cache": [...], "archives": [...], "all": [...]}`。

    **四欄全部是 `scan_candidates` 的回傳值**，本函式不含任何聯集／去重／排序：

      * `all` ＝ 一次 `scan_candidates(items, cache, archives_thread, …)`
        —— 三來源的聯集**只定義在 `scan_candidates` 裡一處**（`AC-1`）。
      * `marks`／`cache`／`archives` ＝ 同一函式只餵單一來源的**子集呼叫**
        （其餘兩個來源給空值），不是另一套邏輯。

    ⚠ 第 2 輪的實作在這裡另以 set 聯集算了一遍 `all`，於是三來源的聯集有兩處
    定義、而 `cmd_scan` 取的是這一處
    （`#296` `R1` 第 2 輪 `BLOCK 1`：違反 `AC-1`「候選集合的定義集中在一個
    純函式……`cmd_scan` 只呼叫它，不自備任何集合邏輯」）。

    `on_invalid` **只交給 `all` 那一次呼叫**：`marks` 那次餵的是同一批 `items`，
    若也轉發就會對同一壞單回報兩次（`R1` 第 1 輪非阻擋建議）。`cmd_scan` 另有
    自己的 `scan_candidates` 呼叫負責 stderr 回報，故它呼叫本函式時把
    `on_invalid` 吞掉——回報的單一來源是那一次，不是分解。

    分解的用途不是美觀：`AC-5` 的那一行是本單的達成證據載體 —— 未達成的面貌是
    「候選 ＝ 4442」，達成的面貌是「候選 25 ／ 探測 25」。三個來源各報一個數字，
    才看得出「拿掉 cache 會不會漏」這類問題該往哪查。
    """
    def _quiet(_exc, _issue):
        """吞掉回報：壞單的處置由 `all` 那一次（或呼叫端自己那一次）負責。"""

    return {"marks": scan_candidates(items, {}, None, on_invalid=_quiet),
            "cache": scan_candidates([], cache, None),
            "archives": scan_candidates([], {}, archives_thread),
            "all": scan_candidates(items, cache, archives_thread,
                                   on_invalid=on_invalid)}


def _scan_read_cache() -> dict:
    """讀 cache 給候選集合用；不存在／損壞一律視為 `{}`，不讓 `scan` 停擺。

    cache 在此是**候選的來源之一**（`#296`），不是上界的來源 —— 上界自 `#287`
    起只由 forge 標記推出，`--full` 路徑不讀 cache。
    """
    if not CACHE.exists():
        return {}
    try:
        return json.loads(CACHE.read_text() or "{}") or {}
    except Exception as exc:  # noqa: BLE001 — 損壞的 cache 只該少幾個候選，不該停擺
        print(f"  ⚠ cache 無法解析（{type(exc).__name__}: {exc}），候選不計 cache 來源",
              file=sys.stderr)
        return {}


def cmd_scan(args) -> int:
    """探測 topic 是否存在。cache 不是權威（已刪 thread 會殘留），探活才是。

    **兩種宣稱、兩種成本**（`#296`，宣稱字面依裁決位 2026-10-08 裁示分化）：

      * 預設 —— 探「**本 kit 管理過的** thread id」，集合由 `scan_candidates`
        決定（標記 ∪ cache ∪ archives）。成本 `O(管理過的數量)`。
      * `--full` —— 探「**群組實際存在的** topic」，即 `range(2, hi)` 全區間
        （`#287` 的行為，上界仍由 `scan_upper_bound` 從 forge 標記推出）。
        成本 `O(上界)`，而上界單調成長：2026-10-08 實測 4442 個／約 16.5 分鐘。

    本函式**不自算任何 id 集合**（`AC-1`）：候選的定義只在 `scan_candidates`。
    """
    from concurrent.futures import ThreadPoolExecutor

    def probe(tid: int):
        res = api("closeForumTopic", chat_id=CHAT, message_thread_id=tid)
        if res.get("ok"):
            api("reopenForumTopic", chat_id=CHAT, message_thread_id=tid)
            return ("open", tid)
        if "TOPIC_NOT_MODIFIED" in res.get("description", ""):
            return ("closed", tid)
        return None

    # 既有測試以 `argparse.Namespace(prune=False)` 呼叫（無 `full` 欄）→ 用 getattr。
    want_full = getattr(args, "full", False)

    def _warn(exc, issue):
        print(f"  ⚠ #{issue} {exc}", file=sys.stderr)

    # forge 的 issue body 是兩條路徑**共用的唯一輸入**：預設模式取它的標記當候選，
    # `--full` 取它的最大 thread id 當上界。只查一次（代價見 `_forge_scan_items`）。
    try:
        items = _forge_scan_items()
    except Exception as exc:  # noqa: BLE001 — forge 不可用時不讓 scan 停擺
        print(f"  ⚠ 無法從 forge 取 issue body（{type(exc).__name__}: {exc}），"
              f"視為零標記", file=sys.stderr)
        items = []

    cache_data = _scan_read_cache()

    # 上界的**來源**是 forge，不是 cache（`#287` `AC-3`）。
    #
    # 這段註解原本記載的是前一次發作（`#247`：thread id 已到 669 而上界寫死 400，
    # `scan` 因此把活著的 topic 報成「cache 過期項」），而**那次的修法是把一個會
    # 失效的來源換成另一個會失效的來源**——改取自 cache，而 cache 的生命週期由
    # 封存程序決定：封存會清 cache，於是「封存得越乾淨，`scan` 能探到的範圍越小」。
    # 寫死 400 與取自 cache 是同一個病的兩種形態，不是一個修好了另一個。
    #
    # 現在改從 forge 推：所有 issue body 的 `topic`／`archived` 標記的最大 thread id
    # ＋餘裕。issue body 的標記不隨封存消失（`#291` 之後封存標記也在），**與封存
    # 動作無關**。代價見 `_forge_scan_items` 的 docstring：多一次 `gh` 查詢。
    # cache 在這裡**不再參與上界計算**，故 cache 不存在／為 `{}`／損壞都不影響 `hi`。
    #
    # `#296` 起這段**只在 `--full` 走**：`scan_upper_bound` 一字不動（它算的上界仍
    # 正確），但「上界」不再等於「要探活的集合」—— 推上界的那組標記本身就是候選，
    # 只取 `max()` 再掃連續區間是 178 倍的浪費，且倍數每天上升（`#296` 材料 ①）。
    if want_full:
        try:
            hi = scan_upper_bound(items, on_invalid=_warn)
        except Exception as exc:  # noqa: BLE001 — 推不出上界時退回寫死地板
            print(f"  ⚠ 無法從 forge 推上界（{type(exc).__name__}: {exc}），"
                  f"退回寫死值 {SCAN_HI_FLOOR}", file=sys.stderr)
            hi = SCAN_HI_FLOOR
        print(f"（上界 hi={hi}，由 forge 的分區標記推出；探測 range(2, {hi})）")
        targets = scan_candidates(items, {}, None, full=True, hi=hi)
    else:
        # targets 直接來自 `scan_candidates`（`AC-1`：候選的定義集中在那一處，
        # `cmd_scan` 只呼叫它）。`#296` `R1` 第 2 輪 `BLOCK 1` 的修正：第 2 輪
        # 取的是 `scan_sources` 回傳字典裡那個自己算的聯集欄，那是第二套定義。
        targets = scan_candidates(items, cache_data, ARCHIVES_THREAD,
                                  on_invalid=_warn)
        # 分解只為了那一行的三個數字。`on_invalid` 吞掉——INVALID 的 stderr 回報
        # 已由上面那次做過，分解再轉發會對同一壞單印兩次。
        src = scan_sources(items, cache_data, ARCHIVES_THREAD,
                           on_invalid=lambda _exc, _issue: None)
        print(f"（候選 {len(targets)} 個：forge 標記 {len(src['marks'])}"
              f" ／ cache {len(src['cache'])} ／ archives {len(src['archives'])}；"
              f"探測 {len(targets)} 個 thread）")
        if not targets:
            # 三個來源皆空 ≠「群組沒有 topic」—— 不得靜默（`AC-2`）。
            print("  ⚠ 候選 0 —— 三個來源（forge 標記／cache／archives）皆空，"
                  "本次沒有探測任何 thread。")
            print("  （這不代表群組沒有 topic；要掃群組實際存在的 topic 請用 "
                  "`scan --full`）")

    found = []
    with ThreadPoolExecutor(max_workers=32) as pool:
        for res in pool.map(probe, targets):
            if res:
                found.append(res)
    print(f"{'群組實際' if want_full else '本 kit 管理過的'} topic（{len(found)}）：")
    for state, tid in sorted(found, key=lambda x: x[1]):
        num, title, _ = issue_meta(str(tid))
        tag = f"#{num} {title[:40]}" if num else ("📦 archives" if tid == ARCHIVES_THREAD else "")
        print(f"  thread {tid:>4}  {state:<6}  {tag}")

    # cache 過期項的語意不動（`#296` 射程外）：cache 指向的 thread 探不到就是死條目。
    # 預設模式下 cache 的每一筆都在候選內（它是來源之一），故「探不到」仍可歸因。
    if cache_data:
        live = {t for _, t in found}
        data = cache_data
        stale = [(n, r["thread_id"]) for n, r in data.items() if r.get("thread_id") not in live]
        if stale:
            print(f"\ncache 過期項（{len(stale)}）— 指向已刪除的 thread：")
            for num, tid in sorted(stale, key=lambda x: -int(x[0])):
                print(f"  #{num} → thread {tid}")
            if getattr(args, "prune", False):
                for num, _tid in stale:
                    del data[num]
                CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
                print(f"  ✅ 已移除 {len(stale)} 筆")
            else:
                # 不自動清：ensure 的 _alive() 本來就擋得住死 thread 並重建，
                # 所以殘留無害；但留著會讓每次 scan 都報一次雜訊。
                print("  （加 --prune 可清除）")
    return 0


def _ts(val: str) -> float:
    """`--since`／`--until` 的值：**明確日期**（`YYYY-MM-DDTHH:MM`）或 epoch 秒。

    **裸 `HH:MM` 不再接受**（`#287` `AC-4`）。原實作把 `HH:MM` 補成「今天」，而
    那個假設在**跨午夜**時失效：`#286` 封存從 2026-10-06 19:0x 跑到 10-07 04:06，
    `--since 19:00` 於 04:06 被解成「今天（10-07）19:00」＝**未來時刻**，時間窗
    為負、`collect` 撈到 0 則、只印「沒有任何訊息」，**無任何告警**。

    這不是「時間窗算錯」，是 `HH:MM` 這個介面**本身**在跨午夜時無法表達使用者的
    意圖。故處置是**改介面要求明確日期**，而不是「自動退一天」——後者會讓「真的
    想指今天稍晚」變成無法表達，只是把失效的假設換個方向（`#287` 裁定 1）。

    接受的形式：
      * `_dt.datetime.fromisoformat` 吃得下的明確日期形式（`2026-10-06T19:00`、
        `2026-10-06 19:00`、`2026-10-06`、含秒／時區者亦可）
      * epoch 秒（整數或小數，如 `$(date -d 'yesterday 18:30' +%s)`）

    不合者一律 `argparse.ArgumentTypeError`（argparse 會印訊息並 exit 2）——
    **不猜日期**。訊息含可照抄的正確形式。
    """
    raw = (val or "").strip()
    try:
        return float(raw)                       # epoch 秒
    except ValueError:
        pass
    try:
        return _dt.datetime.fromisoformat(raw).timestamp()
    except ValueError:
        pass
    raise argparse.ArgumentTypeError(
        f"看不懂的時間值 {val!r}——需要**明確日期**或 epoch 秒，不接受裸 HH:MM。\n"
        f"  正確形式（可照抄）：\n"
        f"    --since 2026-10-06T19:00                   # 明確日期＋時間\n"
        f"    --until 2026-10-07T04:10\n"
        f"    --since $(date -d 'yesterday 18:30' +%s)   # epoch 秒\n"
        f"  裸 HH:MM（例如 19:00）已移除：它在跨午夜時無法表達意圖——被解成\n"
        f"  「今天 HH:MM」可能是未來時刻，時間窗為負而匯出 0 則且無告警（#286 實地發生）。")


def _export(thread: str, since: float | None = None,
            until: float | None = None) -> tuple[pathlib.Path, pathlib.Path, int]:
    rows = collect(thread, since, until)
    if not rows:
        raise SystemExit(f"thread {thread} 沒有任何訊息")
    num, title, state = issue_meta(thread)
    stem = stem_for(thread, num)
    OUT.mkdir(parents=True, exist_ok=True)
    md_path = OUT / f"{stem}.md"
    md_path.write_text(build_md(thread, rows, title, num, state, stem))
    json_path = dump_json(thread, rows, stem, num)
    return md_path, json_path, len(rows)


def cmd_export(args) -> int:
    md, js, n = _export(args.thread, getattr(args, "since", None), getattr(args, "until", None))
    print(f"✅ 匯出 {n} 則")
    print(f"   {md}  {md.stat().st_size / 1024:.0f} KB")
    print(f"   {js}  {js.stat().st_size / 1024:.0f} KB")
    return 0


def cmd_publish(args) -> int:
    md, js, n = _export(args.thread, getattr(args, "since", None), getattr(args, "until", None))
    num, title, state = issue_meta(args.thread)
    # caption 走 HTML parse mode（`send_document:93`）：粗體用 `<b>…</b>`，
    # 外部值（issue 標題、state）一律先過 `esc_html`。`#291` 封存時標題含
    # `_marker.py` 的裸底線，Markdown 解析失敗、MD 封存檔整個送不出去（`#293`）。
    head = "#" + num if num else "thread " + args.thread
    caption = (f"📦 <b>{esc_html(head)}</b> {esc_html(title)}\n"
               f"{n} 則訊息 · thread {esc_html(args.thread)}"
               + (f" · {esc_html(state)}" if state else ""))
    ok = True
    for path, cap in ((md, caption), (js, "")):
        res = send_document(ARCHIVES_THREAD, path, cap)
        status = "✅" if res.get("ok") else f"❌ {res.get('description')}"
        print(f"  {status} {path.name}")
        ok = ok and res.get("ok", False)
    if not ok:
        print("\n⚠️ 發送未全部成功，未執行後續步驟")
        return 1
    print(f"\n已發到 📦 archives（thread {ARCHIVES_THREAD}）。確認檔案可讀後再 archive。")
    return 0


def cmd_archive(args) -> int:
    """`publish` → close → delete → 清 cache → **寫封存標記**。

    封存程序本身是**四步**（`telegram.md:13`「封存程序」格逐字：「分區封存是四步，
    順序固定」）：(1) 匯出 (2) 發到 archives 分區 (3) close ＋ delete (4) 清 cache。
    寫封存標記是**四步之後的獨立動作**（同格逐字：「四步之後還要在 issue body 寫
    封存標記」；`telegram.md:14`「封存標記寫入」格逐字：「封存程序四步完成後」）。

    三個順序約束（`#291` `AC-4`／`AC-5`；第 2 輪依 `R1` BLOCK-1 的裁示改正）：

    * 寫標記在 **delete 成功之後**。「時機在刪分區**之後** —— 刪成功才算封存，
      先寫標記而刪失敗會留下『已封存』的假象」（`telegram.md:14` 逐字）。
    * 寫標記在 **清 cache 之後**，不塞進四步之間。契約的結構理由：`telegram.md:13`
      明載「第 (4) 步失敗時前三步已生效…殘影會讓下一次建分區拿到已不存在的
      thread id，故第 (4) 步須讀回驗證」——清 cache 是**四步裡須讀回驗證的收尾
      動作**；寫標記是 `CH3` 的**獨立動作**，契約依 `R7` 刻意把兩者拆成兩格
      （兩者實測狀態不同：四步有既有紀錄、寫標記從未執行過）。把寫標記塞進
      四步之間會模糊這個刻意的劃分。
      ⚠ 本單第 1 輪（`2a6af87`）依 T v1 把寫標記放在清 cache **之前**，被 `R1`
      以 BLOCK-1 擋下（`L3`(b)：T 與它宣告不修改的共用契約矛盾）。裁決位
      2026-10-05 選定「契約優先、T 改」，故這裡是契約的次序，不是工程偏好。
    * `issue_meta` 與 `md_path` 仍在 **delete 之前**取齊（`AC-5`）。`issue_meta`
      先讀 cache，命中就不打 forge；取值一旦落到清 cache 之後會退回
      `gh issue list` 掃全 repo（多一次 API，且任一張單 `T>1` 時 raise，
      使封存的最後一步失敗）。**取值的位置與寫入的位置是兩件事**：前者受
      cache 還在與否約束，後者受契約的四步劃分約束。

    三個失敗分支的處置見 `AC-10`（T v2 正式規格）：`delete` 已成功 ⇒ 分區已不
    存在 ⇒ **cache 一律照清**，而**整體 rc 非 0**（標記是 `CH3` 的必需步驟，
    寫入失敗卻回 0 會誤報整體成功）。rc 與 cache 不是矛盾——rc 反映「封存程序
    是否完整完成」，cache 反映「本機快取是否還有殘影」；分區已刪，殘影就是錯的。
    """
    if not args.yes:
        print("⚠️ archive 會刪除 topic 及其所有訊息（不可逆）。確認後加 --yes 重跑。")
        return 2
    # 正常流程是先 publish 求確認、再 archive，此時檔案已在 archives topic 內；
    # 預設再送一次會出現兩份重複。--no-publish 跳過，只做 close → delete → 清 cache。
    if args.no_publish:
        print("（--no-publish：沿用先前 publish 的檔案，不重送）")
    elif cmd_publish(args) != 0:
        return 1
    # 寫標記要用的兩個值在這裡就**取齊**（delete 與清 cache 之前；`AC-5`）：
    # `--no-publish` 會跳過 cmd_publish，而 issue 號與匯出檔路徑原本只在
    # `_export`／`cmd_publish` 內算得出來，故這裡自己取。取值早、寫入晚——
    # 寫入的位置由 `AC-4` 規定在清 cache 之後（見 docstring 的契約理由）。
    # 變數不叫 `num`：下面清 cache 的迴圈用的就是那個名字（既有碼），
    # 共用一個名字會被該迴圈覆寫。
    issue_num, _title, _state = issue_meta(args.thread)
    md_path = OUT / f"{stem_for(args.thread, issue_num)}.md"
    # close 再 delete。實測（3 次複驗）開啟中的 topic 也能直接刪除，close 不是 API 前置條件；
    # 保留它是為了「封存＝先停止寫入，再移除」這個語意順序，並讓中途失敗留下可辨識的狀態。
    closed = api("closeForumTopic", chat_id=CHAT, message_thread_id=int(args.thread))
    if closed.get("ok"):
        print("  ✅ 已關閉 topic（停止寫入）")
    elif "TOPIC_NOT_MODIFIED" in closed.get("description", ""):
        print("  ✅ topic 本來就是關閉的")
    else:
        print(f"  ⚠️ close 失敗：{closed.get('description')}（續行刪除）")
    res = api("deleteForumTopic", chat_id=CHAT, message_thread_id=int(args.thread))
    print(f"  {'✅ 已刪除 topic' if res.get('ok') else '❌ ' + str(res.get('description'))}")
    if not res.get("ok"):
        return 1
    # 封存程序第 (4) 步：清 cache。寫標記在這**之後**（`AC-4`：契約的四步劃分）。
    if CACHE.exists():
        data = json.loads(CACHE.read_text() or "{}")
        drop = [n for n, r in data.items() if str(r.get("thread_id")) == str(args.thread)]
        for num in drop:
            del data[num]
        if drop:
            CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            print(f"  ✅ cache 移除 {', '.join('#' + n for n in drop)}")
    # ── 第四步：寫封存標記（CH3）──開始（#291；此標記供測試的突變複本切除本段）──
    # 命名沿用「第四步」只為區段標記的穩定（測試的突變複本靠它切段）；就契約而言
    # 這是**四步之後**的獨立動作，不是四步裡的第四步（見 docstring）。
    marker_rc = 0
    if issue_num is None:
        # `AC-10` 分支一：rc 非 0、cache 已清（上面做完了）、不呼叫 gh issue edit。
        print("  ❌ 查不到該 thread 對應的 issue 號，不寫封存標記"
              "（該單在 forge 上維持 T=1 A=0 ＝ active，依 F4 人工補寫）")
        marker_rc = 1
    elif not md_path.is_file():
        # `AC-10` 分支二：不寫指向不存在檔的標記——`file=` 欄的語意是「封存的
        # 實體所在」（`channels/README.md:51`）。
        print(f"  ❌ 匯出檔不存在，不寫指向不存在檔的封存標記：{md_path}")
        marker_rc = 1
    else:
        import subprocess
        try:
            # repo 與 issue_meta 的 `gh issue list` 同一個字面（該函式本單不得改，
            # 故此處重寫一次而非抽常數——`#291` `AC-7` 的 AST 比對要求）。
            body = json.loads(subprocess.run(
                ["gh", "issue", "view", str(issue_num), "-R", "AugustusHsu/agent-devflow",
                 "--json", "body"],
                capture_output=True, stdin=subprocess.DEVNULL, timeout=60,
                text=True, check=True).stdout)["body"]
            # upsert：A=0 追加獨立一行、A=1 只取代那一行、A>1 raise（不動 forge）。
            # file= 寫絕對路徑（OUT 在 ~/.hermes 下），形狀同 #283／#285 的先例。
            body = _marker.upsert_archived(body, args.thread, md_path,
                                           detail=f"issue #{issue_num}")
            tmp = pathlib.Path(tempfile.gettempdir()) / f"devflow-archived-{issue_num}.md"
            tmp.write_text(body)
            # `AC-11`：暫存檔在**任何路徑**都要清掉，含 gh 失敗時。第 1 輪
            # （`2a6af87`）把 unlink 放在 check=True 之後，故 edit 失敗時
            # CalledProcessError 直接拋出、檔案留在暫存根——那就是 `C5` 第一項
            # 要抓的散檔，而且是收尾動作自己製造的。
            try:
                subprocess.run(
                    ["gh", "issue", "edit", str(issue_num), "-R", "AugustusHsu/agent-devflow",
                     "-F", str(tmp)],
                    capture_output=True, stdin=subprocess.DEVNULL, timeout=60,
                    text=True, check=True)
            finally:
                tmp.unlink(missing_ok=True)
            print(f"  ✅ 已寫封存標記到 #{issue_num}"
                  f"（thread={args.thread} file={md_path}）")
        except _marker.InvalidMarker as exc:
            # `AC-10` 分支三：`CH3` 要求印全部命中行到 stderr、不動 forge。
            # cache 已在上面清掉——分區已刪，殘影就是錯的（見 docstring）。
            print(str(exc), file=sys.stderr)
            print("  ❌ 封存標記寫入停下（INVALID），依 F4 人工處置")
            marker_rc = 1
        except Exception as exc:  # noqa: BLE001 — forge 不可用／grammar 不合都在此收容
            print(f"  ❌ 寫封存標記失敗：{type(exc).__name__}: {exc}", file=sys.stderr)
            marker_rc = 1
    # ── 第四步結束 ──────────────────────────────────────────────────────────
    return marker_rc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sp_scan = sub.add_parser("scan", help="掃描本 kit 管理過的 topic（加 --full 掃群組實際存在的）")
    sp_scan.add_argument("--prune", action="store_true",
                         help="一併移除 cache 中指向已刪除 thread 的項")
    sp_scan.add_argument("--full", action="store_true",
                         help="掃描群組實際存在的 topic：探活 range(2, hi) 全區間"
                              "（上界由 forge 的分區標記推出）。慢——2026-10-08 實測"
                              "4442 個 thread／約 16.5 分鐘；預設模式只探本 kit"
                              "管理過的 25 個")
    for name, helptext in (("export", "只匯出到本機"),
                           ("publish", "匯出並發到 archives topic"),
                           ("archive", "publish + 刪除 topic + 清 cache")):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("thread")
        sp.add_argument("--since", type=_ts, metavar="YYYY-MM-DDTHH:MM|EPOCH",
                        help="時間窗起點，明確日期或 epoch 秒（不接受裸 HH:MM）"
                             "（預設由 topic 訊息推導；topic session 很短時要手動給）")
        sp.add_argument("--until", type=_ts, metavar="YYYY-MM-DDTHH:MM|EPOCH",
                        help="時間窗終點，形式同 --since")
        if name == "archive":
            sp.add_argument("--yes", action="store_true", help="確認執行刪除")
            sp.add_argument("--no-publish", action="store_true",
                            help="跳過重送（先前已 publish 過），只做 close → delete → 清 cache")
    args = parser.parse_args()
    return {"scan": cmd_scan, "export": cmd_export,
            "publish": cmd_publish, "archive": cmd_archive}[args.cmd](args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except _marker.InvalidMarker as e:
        # `CH3`：exit 非 0 ＋ stderr 印 INVALID 與命中的所有行，停下不動 forge。
        # 這裡接住是為了不讓它只留一段 traceback——訊息本身已含全部命中行的字面。
        print(str(e), file=sys.stderr)
        sys.exit(1)
