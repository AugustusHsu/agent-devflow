#!/usr/bin/env python3
"""devflow topic 封存工具。

封存 = 匯出（MD 人讀 + JSON 全量）→ 發到 archives topic → 刪除原 topic → 清 cache。

用法：
    devflow_archive.py scan                    掃描群組實際存在的 topic（cache 不是權威）
    devflow_archive.py export <thread>         只匯出到 ~/.hermes/archives/topics/
    devflow_archive.py publish <thread>        匯出並發到 archives topic（不刪原 topic）
    devflow_archive.py archive <thread> --yes  publish + 刪除原 topic + 清 cache

關鍵設計（踩過的坑）：
  * manager 的工作記錄 thread_id 是 None（headless `chat --oneshot`），
    只撈 `thread_id=<N>` 會漏掉整段執行軌跡。以時間窗口補撈，按時間軸併起來。
  * cache（devflow-topics.json）會殘留已刪除的 thread，只有 scan 是權威。
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
        hits = []
        for item in json.loads(out or "[]"):
            # 掃完才回傳：不在第一個命中就 return，否則排在後面的 T>1 不會被看到。
            if _marker.has_topic(item.get("body") or "", thread):
                hits.append(item)
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
def cmd_scan(args) -> int:
    """探測實際存在的 topic。cache 不是權威（已刪 thread 會殘留）。"""
    from concurrent.futures import ThreadPoolExecutor

    def probe(tid: int):
        res = api("closeForumTopic", chat_id=CHAT, message_thread_id=tid)
        if res.get("ok"):
            api("reopenForumTopic", chat_id=CHAT, message_thread_id=tid)
            return ("open", tid)
        if "TOPIC_NOT_MODIFIED" in res.get("description", ""):
            return ("closed", tid)
        return None

    # 上界不能寫死：thread id 隨群組活動單調成長，`#247` 時已到 669，而舊的 range(2, 400)
    # 根本沒探到它——scan 因此把活著的 topic 報成「cache 過期項（指向已刪除的 thread）」。
    # 以 cache 內最大 id 再加一段餘裕為界，並保留一個不低於歷史值的下限。
    hi = 400
    if CACHE.exists():
        try:
            ids = [int(r["thread_id"]) for r in json.loads(CACHE.read_text() or "{}").values()
                   if str(r.get("thread_id", "")).isdigit()]
            hi = max([hi] + ids) + 50
        except Exception:  # noqa: BLE001 — cache 壞掉不該讓 scan 停擺
            pass

    found = []
    with ThreadPoolExecutor(max_workers=32) as pool:
        for res in pool.map(probe, range(2, hi)):
            if res:
                found.append(res)
    print(f"群組實際 topic（{len(found)}）：")
    for state, tid in sorted(found, key=lambda x: x[1]):
        num, title, _ = issue_meta(str(tid))
        tag = f"#{num} {title[:40]}" if num else ("📦 archives" if tid == ARCHIVES_THREAD else "")
        print(f"  thread {tid:>4}  {state:<6}  {tag}")

    if CACHE.exists():
        live = {t for _, t in found}
        data = json.loads(CACHE.read_text() or "{}")
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
    """`--since`／`--until` 的值：`HH:MM`（今天）或 epoch 秒。"""
    if ":" in val:
        h, m = val.split(":", 1)
        today = _dt.date.today()
        return _dt.datetime.combine(today, _dt.time(int(h), int(m))).timestamp()
    return float(val)


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
    sp_scan = sub.add_parser("scan", help="掃描群組實際存在的 topic")
    sp_scan.add_argument("--prune", action="store_true",
                         help="一併移除 cache 中指向已刪除 thread 的項")
    for name, helptext in (("export", "只匯出到本機"),
                           ("publish", "匯出並發到 archives topic"),
                           ("archive", "publish + 刪除 topic + 清 cache")):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("thread")
        sp.add_argument("--since", type=_ts, metavar="HH:MM|EPOCH",
                        help="時間窗起點（預設由 topic 訊息推導；topic session 很短時要手動給）")
        sp.add_argument("--until", type=_ts, metavar="HH:MM|EPOCH",
                        help="時間窗終點")
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
