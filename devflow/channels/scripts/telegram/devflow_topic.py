#!/usr/bin/env python3
"""devflow topic 映射——forge 為權威，本機僅 cache。

決策 1(c)：thread_id 記在 issue body 的機器可讀行，本機 JSON 只是加速用的 cache。
Bot API 無法列舉 forum topic，故映射一旦遺失無法重建——除非 forge 上有記錄。

用法：
    python3 devflow_topic.py ensure <issue>     取得或建立 topic，印出 thread_id
    python3 devflow_topic.py close  <issue>     關閉 topic（issue 結案時）
    python3 devflow_topic.py sync               從 forge 重建本機 cache
"""
import json, os, re, subprocess, sys, urllib.error, urllib.parse, urllib.request
from pathlib import Path

# marker 的 grammar 一律走共用模組——它是 `CH3`（channels/README.md「分區三態」）判定式的
# 實作。本檔不自己寫正則：三處讀寫點（_from_forge／_to_forge／sync）原本各寫一份未錨定的
# 近似邏輯，`#285` 修掉。同層 import，零 import-path 操作（`AC-10`）。
import _marker

CHAT = os.environ.get("DEVFLOW_CHAT", "-1003546152597")
REPO = os.environ.get("DEVFLOW_REPO", "AugustusHsu/agent-devflow")
CACHE = Path.home() / ".hermes/cache/devflow-topics.json"
MARKER = "<!-- devflow:topic "          # issue body 內的機器可讀行
SEAT = os.environ.get("DEVFLOW_SEAT", "dfcoord")


def _token(profile=SEAT):
    env = Path.home() / f".hermes/profiles/{profile}/.env"
    for line in env.read_text().splitlines():
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"no token in {env}")


def api(method, **kw):
    url = f"https://api.telegram.org/bot{_token()}/{method}"
    if kw:
        url += "?" + urllib.parse.urlencode(kw)
    try:
        return json.loads(urllib.request.urlopen(url, timeout=20).read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"gh failed: {r.stderr.strip()}")
    return r.stdout


def _topic_name(issue, title):
    """topic 顯示名：類型 emoji + 編號。

    issue 標題慣例以類型 emoji 起頭（🔧 ci／🐛 fix／📊 tracking／🔐 rules／🏗️ design…）。
    取該 emoji 加編號，一眼可辨類型且幾乎不佔寬度——完整標題在 issue 上，不必在 topic 名重複。
    無法辨識 emoji 時退回純編號。
    """
    first = (title or "").strip().split(" ", 1)[0]
    # 純 ASCII（含 `ci:` 這種）不是 emoji，退回純編號
    emoji = first if first and not first.isascii() else ""
    return (f"{emoji} #{issue}" if emoji else f"#{issue}")[:128]


def _cache():
    return json.loads(CACHE.read_text()) if CACHE.exists() else {}


def _save(data):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _from_forge(issue):
    """讀 issue body 的 marker 行。forge 是權威來源。

    `T=0` → None、`T=1` → thread id、`T>1` → raise `_marker.InvalidMarker`
    （由 `__main__` 接住：stderr 印 INVALID 與全部命中行、exit 非 0、不動 forge）。
    """
    body = json.loads(gh("issue", "view", str(issue), "-R", REPO, "--json", "body"))["body"]
    return _marker.read_topic(body, detail=f"issue #{issue}")


def _to_forge(issue, thread_id):
    body = json.loads(gh("issue", "view", str(issue), "-R", REPO, "--json", "body"))["body"]
    # upsert：T=0 追加獨立一行、T=1 只取代那一行、T>1 raise（gh issue edit 不會被呼叫）。
    # 表格列內／散文旁註／縮排的同形字串一字不動——原實作的未錨定 re.sub 會全部改掉。
    body = _marker.upsert_topic(body, thread_id, detail=f"issue #{issue}")
    p = Path(os.environ.get("TMPDIR", "/tmp")) / f"devflow-topic-{issue}.md"
    p.write_text(body)
    gh("issue", "edit", str(issue), "-R", REPO, "-F", str(p))
    p.unlink(missing_ok=True)


def _alive(thread_id):
    """thread 是否還存在。**只對原本 open 的分區還原狀態。**

    ⚠ 三個雷，都實測過：

    1. ``editForumTopic`` 不帶任何可改欄位時形同 no-op，對**已刪除的 thread 也回
       ok=True**，探活完全失效。必須帶一個可改欄位。
    2. 帶 ``name`` 會**真的改掉 topic 名稱**。若探活時傳的值與原名不同（例如 cache
       缺 title 而用了 fallback），每次探活都在重命名 topic。
    3. ``closeForumTopic`` 對**已關閉**的 topic 回 ``ok: false`` ＋
       ``TOPIC_NOT_MODIFIED``、對**開啟中**的回 ``ok: true``。原實作只排除
       ``TOPIC_ID_INVALID``、其餘一律 ``reopenForumTopic``，於是**把刻意關閉的分區
       打開了**（`#304` 誘餌分區 thread 4863 實測：關閉 → 探活 → 狀態變回 open）。

    解法：依 ``closeForumTopic`` 的回傳分三態，只在「本呼叫真的改到狀態」時還原：

    ====================  ========  ==========  ======
    closeForumTopic 回傳  原狀態    動作        回傳
    ====================  ========  ==========  ======
    TOPIC_ID_INVALID      不存在    不動        False
    TOPIC_NOT_MODIFIED    closed    **不動**    True
    ok: true              open      reopen 還原 True
    ====================  ========  ==========  ======

    ⚠ **前提修正**：原 docstring 把「狀態回到原點」寫成了**無條件**的保證（原文是
    「一關一開後」那一句，可在 base 的版本讀到）——**那只在分區原本是 open 時成立**。
    寫註解的人只測了 open 的情況，把特例寫成了通則，而該註解此後一直在為缺陷背書
    （讀者想確認這函式是否唯讀，會讀到一句明確的保證）。現在「狀態回到原點」對三態
    都成立，代價是多一個分支。

    還原失敗**只回報、不重試**（`#304` 裁決位 2026-10-08）：重試會讓一個唯讀查詢
    變成帶重試的寫入操作，問題更大。回報走 stderr，含 thread id 與 API 的
    ``description`` 字面（`#304` `AC-3`）。

    第四種回傳（既非 INVALID 亦非 NOT_MODIFIED 的失敗，如權限／限流／網路）**維持
    原行為回 True**：那不是「分區不存在」的證據，回 False 會讓 ``ensure`` 誤判為死
    thread 而重建分區——`#304` 不改這一支的語意（`probe` 在此支回 ``None``，兩者的
    差異是既有事實，本單不動 ``probe`` 的分支）。
    """
    r = api("closeForumTopic", chat_id=CHAT, message_thread_id=thread_id)
    if r.get("ok"):
        # 本呼叫剛把一個 open 的分區關了 —— 只有這一支需要還原。
        back = api("reopenForumTopic", chat_id=CHAT, message_thread_id=thread_id)
        if not back.get("ok"):
            print(f"# ⚠ thread {thread_id} 狀態未還原（探活關閉後 reopenForumTopic "
                  f"失敗，仍為 closed）：{back.get('description')}", file=sys.stderr)
        return True
    desc = r.get("description", "")
    if "TOPIC_ID_INVALID" in desc:
        return False
    if "TOPIC_NOT_MODIFIED" in desc:
        return True            # 原本就是 closed，本呼叫沒改到它 → 不動
    return True


def ensure(issue):
    """取得或建立 topic。建立前必查，避免重複。"""
    c = _cache()
    key = str(issue)

    for src, tid in (("cache", c.get(key, {}).get("thread_id")), ("forge", None)):
        if src == "forge" and tid is None:
            tid = _from_forge(issue)
        if tid and _alive(tid):
            c.setdefault(key, {}).update(thread_id=tid, state="open")
            _save(c)
            if src == "forge":
                print(f"# recovered from forge", file=sys.stderr)
            return tid
        if tid:
            print(f"# {src} thread {tid} is dead, recreating", file=sys.stderr)

    title = json.loads(gh("issue", "view", str(issue), "-R", REPO, "--json", "title"))["title"]
    name = _topic_name(issue, title)
    r = api("createForumTopic", chat_id=CHAT, name=name, icon_color=7322096)
    if not r.get("ok"):
        raise SystemExit(f"createForumTopic failed: {r.get('description')}")
    tid = r["result"]["message_thread_id"]
    c[key] = {"thread_id": tid, "state": "open", "title": title}
    _save(c)
    _to_forge(issue, tid)          # forge 是權威，一定要寫回
    return tid


def close(issue):
    """issue 結案時關閉 topic——不刪除，保留歷史。"""
    c = _cache()
    key = str(issue)
    tid = c.get(key, {}).get("thread_id") or _from_forge(issue)
    if not tid:
        raise SystemExit(f"no topic for #{issue}")
    r = api("closeForumTopic", chat_id=CHAT, message_thread_id=tid)
    c.setdefault(key, {}).update(thread_id=tid, state="closed")
    _save(c)
    return r.get("ok")


def sync():
    """從 forge 重建本機 cache（cache 遺失或換機器時）。

    回傳 `(映射數, INVALID 的單號清單)`。遇 `T>1` 的單：**不**把錯的映射寫進 cache
    （該單的分區是哪一個沒有單一答案），stderr 印 `INVALID` 與該單號、該單全部命中行的
    字面，跳過該單繼續掃其餘的單，最後由 `__main__` exit 非 0。

    「跳過而非整批中止」的理由：這條路徑是 cache 遺失時的重建手段，一張壞單不該讓
    其餘兩百多張單也重建不了；但 exit 非 0 使它不被當成成功，人工處置的義務仍在
    （`channels/README.md:61`：不得靜默取其一）。
    """
    out = gh("issue", "list", "-R", REPO, "--state", "all", "--limit", "300", "--json", "number,title,body,state")
    items = json.loads(out)
    c, invalid = {}, []
    by_num = {str(it["number"]): it for it in items}

    def _skip(exc, issue):
        """`T>1`：回報單號、印 INVALID、跳過該單續掃（exit 非 0 由 `__main__` 帶出）。"""
        invalid.append(str(issue))
        print(f"# {exc}", file=sys.stderr)

    # 掃描走共用模組（`#287` `AC-1`／`AC-2`）：查詢留在這裡（上面的 `gh`），
    # marker 解析交給 `_marker.scan_topic`。對外行為一字不變——`on_invalid` 即
    # 原本的 `except … continue`（跳過該單續掃），回傳的 `(n, invalid)` 同形。
    for num, tid, _kind in _marker.scan_topic(
            ((str(it["number"]), it["body"] or "") for it in items), on_invalid=_skip):
        it = by_num[num]
        c[num] = {
            "thread_id": tid,
            "state": (it.get("state") or "OPEN").lower(),
            "title": it["title"],
        }
    _save(c)
    return len(c), invalid


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cmd = sys.argv[1]
    try:
        if cmd == "ensure":
            print(ensure(sys.argv[2]))
        elif cmd == "close":
            print("ok" if close(sys.argv[2]) else "failed")
        elif cmd == "sync":
            n, invalid = sync()
            print(f"{n} mappings recovered")
            if invalid:
                # 已逐單印過命中行；這行是收尾的摘要，exit 非 0 由 SystemExit 帶出。
                raise SystemExit(
                    f"INVALID: {len(invalid)} 張單有重複分區標記，已跳過不寫入 cache："
                    + " ".join(f"#{x}" for x in invalid)
                )
        else:
            raise SystemExit(__doc__)
    except _marker.InvalidMarker as e:
        # `CH3`：exit 非 0 ＋ stderr 印 INVALID 與全部命中行，停下**不動 forge**。
        # 走到這裡表示 gh issue edit 尚未被呼叫（upsert 在寫檔前就 raise）。
        raise SystemExit(str(e))
