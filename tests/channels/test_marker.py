#!/usr/bin/env python3
"""`#285`／K4c-1：`CH3` 分區標記 grammar 的實作驗證（`AC-1`～`AC-7`）。

直接執行：`/usr/bin/python3 tests/channels/test_marker.py`
全過 exit 0、任一項失敗 exit 非 0，stdout 逐項列 PASS／FAIL。

零 import-path 操作（`AC-10`，機械判準是 `grep -nE 'sys\\.path'` 無命中，故本檔連字面
都不出現）：受測模組一律以 `importlib.util.spec_from_file_location`
載入（repo 既有慣例，見 `tests/install/harness.py:57`）。受測腳本彼此的同層 import
（`devflow_topic` → `_marker`、`devflow_archive` → `_marker`）靠把已載入的模組
登錄進 `sys.modules` 滿足——那是 import 機制本身，不是搜尋路徑操作。

純字串 fixture，零 Telegram API：`AC-3` 的腳本層驗證用假的 `gh`（PATH 前置）＋ 假 `HOME`，
且以哨兵檔反證 `gh issue edit` **沒有**被呼叫。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True          # 不在受測目錄留 __pycache__（repo 慣例）

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SCRIPTS = REPO / "devflow" / "channels" / "scripts" / "telegram"
CHANNELS_README = REPO / "devflow" / "channels" / "README.md"

PY = "/usr/bin/python3"                 # python3 缺 yaml 等模組，repo 一律用這支


def _load(name: str, path: Path):
    """以 importlib 載入單檔模組，並登錄進 sys.modules 供同層 import 解析。"""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod             # devflow_topic/_archive 的 `import _marker` 靠這個
    spec.loader.exec_module(mod)
    return mod


marker = _load("_marker", SCRIPTS / "_marker.py")
topic = _load("devflow_topic", SCRIPTS / "devflow_topic.py")
archive = _load("devflow_archive", SCRIPTS / "devflow_archive.py")


# ── fixtures（字面即規格；T 的 `AC-1`～`AC-3` 逐字對應）────────────────────────
F1 = """# 單 A

散文裡提到 thread=777 這個數字（不是標記，只是散文）。
也提一次完整字面 <!-- devflow:topic thread=777 --> 當旁註。

<!-- devflow:topic thread=2620 -->
"""

F2 = """# 某單

| 形態 | 字面 |
|---|---|
| 表格列內 | `<!-- devflow:topic thread=123 -->` |

散文也提一次 <!-- devflow:topic thread=123 --> 如上。

<!-- devflow:topic thread=2620 -->
"""

F3 = """# 壞掉的單

<!-- devflow:topic thread=2620 -->

中間有別的內容。

<!-- devflow:topic thread=999 -->
"""

# 只在表格列內提及 thread=2620，無獨立一行的標記（`AC-5` 的對照）
F_TABLE_ONLY = """# 單 B

| 形態 | 字面 |
|---|---|
| 表格列內 | `<!-- devflow:topic thread=2620 -->` |
"""

F3_LINES = [
    "<!-- devflow:topic thread=2620 -->",
    "<!-- devflow:topic thread=999 -->",
]

# ── 測試框架（極簡：記錄 PASS/FAIL，不吞例外的細節）──────────────────────────
RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((label, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail else ""))
    return bool(ok)


def case(label: str):
    """把一個子測試包起來——未預期的例外算 FAIL，不中止其餘子測試。"""
    def deco(fn):
        try:
            fn()
        except Exception as e:                       # noqa: BLE001
            import traceback
            check(label, False, f"未預期例外 {type(e).__name__}: {e}\n"
                                + traceback.format_exc(limit=3))
        return fn
    return deco


# ── AC-1 讀側錨定與唯一性 ───────────────────────────────────────────────────
@case("AC-1 fixture 一：散文 thread=777 ＋ 獨立一行 thread=2620 → 讀出 2620")
def _ac1():
    got = marker.read_topic(F1)
    check("AC-1 read_topic(F1) == 2620", got == 2620, f"實得 {got!r}")
    ids, lines = marker.find_topic(F1)
    check("AC-1 F1 的 T == 1（散文與旁註都不計入）",
          len(lines) == 1 and lines == ["<!-- devflow:topic thread=2620 -->"],
          f"T={len(lines)} lines={lines!r} ids={ids!r}")
    check("AC-1 未達成候選（未錨定 re.search 取第一個）確實會讀到 777",
          re.search(r"<!-- devflow:topic thread=(\d+) -->", F1).group(1) == "777",
          "對照組：證明本 fixture 對錨定有鑑別力")


# ── AC-2 寫側錨定與 upsert ──────────────────────────────────────────────────
@case("AC-2 fixture 二：upsert 9999 後表格列與散文字面原樣不動")
def _ac2():
    out = marker.upsert_topic(F2, 9999)
    table_line = "| 表格列內 | `<!-- devflow:topic thread=123 -->` |"
    prose_line = "散文也提一次 <!-- devflow:topic thread=123 --> 如上。"
    check("AC-2 表格列字面原樣不動", table_line in out, repr(out))
    check("AC-2 散文字面原樣不動", prose_line in out, repr(out))
    ids, lines = marker.find_topic(out)
    check("AC-2 獨立一行的標記恰一個", len(lines) == 1, f"T={len(lines)} {lines!r}")
    check("AC-2 其值為新 id 9999", ids == ["9999"], f"ids={ids!r}")
    check("AC-2 舊的獨立標記 thread=2620 已不存在（取代而非新增）",
          "<!-- devflow:topic thread=2620 -->" not in out.splitlines(),
          repr(out))
    check("AC-2 body 其餘內容未被改寫（只差那一行）",
          [l for l in F2.splitlines() if l != "<!-- devflow:topic thread=2620 -->"]
          == [l for l in out.splitlines() if l != "<!-- devflow:topic thread=9999 -->"],
          repr(out))
    # 未達成候選：未錨定的 re.sub 取代全部命中 —— 正是破壞 #285 自己 T 的那段邏輯
    MARKER = "<!-- devflow:topic "
    bad = re.sub(re.escape(MARKER) + r"thread=\d+ -->",
                 f"{MARKER}thread=9999 -->", F2)
    check("AC-2 未達成候選（未錨定 re.sub）確實會改掉表格列與散文",
          table_line not in bad and prose_line not in bad,
          "對照組：證明本 fixture 對錨定有鑑別力")

    # T=0 → 追加獨立一行
    empty = "# 新單\n\n沒有標記。\n"
    out0 = marker.upsert_topic(empty, 3054)
    ids0, lines0 = marker.find_topic(out0)
    check("AC-2 T=0 時在尾端追加獨立一行",
          len(lines0) == 1 and ids0 == ["3054"] and out0.startswith(empty.rstrip()),
          repr(out0))


# ── AC-3 INVALID ────────────────────────────────────────────────────────────
@case("AC-3 fixture 三：兩個獨立一行的標記 → INVALID（函式層 raise）")
def _ac3_lib():
    ids, lines = marker.find_topic(F3)
    check("AC-3 F3 的 T == 2", len(lines) == 2 and lines == F3_LINES, f"{lines!r}")
    try:
        marker.read_topic(F3)
    except marker.InvalidMarker as e:
        msg = str(e)
        check("AC-3 read_topic 擲出 InvalidMarker", True)
        check("AC-3 例外訊息含 INVALID 字樣", "INVALID" in msg, msg)
        check("AC-3 例外訊息含兩行命中的字面",
              all(ln in msg for ln in F3_LINES), msg)
        check("AC-3 例外物件帶全部命中行", e.lines == F3_LINES, f"{e.lines!r}")
    else:
        check("AC-3 read_topic 擲出 InvalidMarker", False, "沒有擲出例外（靜默取其一）")
    # upsert 同樣不得靜默處理
    try:
        marker.upsert_topic(F3, 4242)
    except marker.InvalidMarker as e:
        check("AC-3 upsert_topic 亦 raise 且不回傳改過的 body",
              all(ln in str(e) for ln in F3_LINES), str(e))
    else:
        check("AC-3 upsert_topic 亦 raise", False, "T>1 時竟回傳了 body")
    # 未達成候選：現行讀法取第一個
    check("AC-3 未達成候選（取第一個）確實會讀到 2620",
          re.search(r"<!-- devflow:topic thread=(\d+) -->", F3).group(1) == "2620",
          "對照組")


@case("AC-3 腳本層：exit 非 0 ＋ stderr 含 INVALID 與兩行字面，且未呼叫 gh issue edit")
def _ac3_script():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        home, bin_, sentinel = td / "home", td / "bin", td / "edit-was-called"
        home.mkdir()
        bin_.mkdir()
        # 假 gh：issue view 回 fixture 三；issue edit 一律視為違規（留哨兵並 exit 非 0）
        fake = bin_ / "gh"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "args = sys.argv[1:]\n"
            "if args[:2] == ['issue', 'edit']:\n"
            f"    open({str(sentinel)!r}, 'w').write(' '.join(args))\n"
            "    print('gh issue edit 不該被呼叫', file=sys.stderr)\n"
            "    sys.exit(9)\n"
            "if args[:2] == ['issue', 'view']:\n"
            f"    print(json.dumps({{'body': {F3!r}, 'title': '🔧 壞掉的單'}}))\n"
            "    sys.exit(0)\n"
            "print('unexpected gh call: ' + ' '.join(args), file=sys.stderr)\n"
            "sys.exit(8)\n"
        )
        fake.chmod(0o755)
        env = dict(os.environ,
                   HOME=str(home),                      # cache 與 token 都隔離到假 HOME
                   PATH=f"{bin_}:{os.environ.get('PATH', '')}",
                   PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([PY, str(SCRIPTS / "devflow_topic.py"), "ensure", "285"],
                           capture_output=True, text=True, env=env,
                           stdin=subprocess.DEVNULL, timeout=60)
        detail = f"exit={r.returncode}\n--- stdout ---\n{r.stdout}--- stderr ---\n{r.stderr}"
        check("AC-3 腳本 exit 非 0", r.returncode != 0, detail)
        check("AC-3 stderr 含 INVALID 字樣", "INVALID" in r.stderr, detail)
        check("AC-3 stderr 含兩行命中的字面",
              all(ln in r.stderr for ln in F3_LINES), detail)
        check("AC-3 未呼叫 gh issue edit（不動 forge）",
              not sentinel.exists(),
              detail + (f"\n哨兵內容：{sentinel.read_text()}" if sentinel.exists() else ""))


# ── AC-4 sync 同受保護 ──────────────────────────────────────────────────────
@case("AC-4 sync：以 fixture 一作 issue list 輸入 → cache 映射為 2620")
def _ac4():
    with tempfile.TemporaryDirectory() as td:
        cache = Path(td) / "devflow-topics.json"
        listing = [{"number": 285, "title": "單 A", "body": F1, "state": "OPEN"}]

        calls = []

        def fake_gh(*args):
            calls.append(args)
            assert args[:2] == ("issue", "list"), args
            return json.dumps(listing)

        orig_gh, orig_cache = topic.gh, topic.CACHE
        topic.gh, topic.CACHE = fake_gh, cache
        try:
            n, invalid = topic.sync()
        finally:
            topic.gh, topic.CACHE = orig_gh, orig_cache
        data = json.loads(cache.read_text())
        check("AC-4 cache 映射為 2620（非散文的 777）",
              data.get("285", {}).get("thread_id") == 2620,
              json.dumps(data, ensure_ascii=False))
        check("AC-4 回報 1 筆、無 INVALID", (n, invalid) == (1, []), f"{n!r} {invalid!r}")

    # INVALID 的單：不得把錯的映射寫進 cache，且回報該單號
    with tempfile.TemporaryDirectory() as td:
        cache = Path(td) / "devflow-topics.json"
        listing = [{"number": 285, "title": "單 A", "body": F1, "state": "OPEN"},
                   {"number": 999, "title": "壞單", "body": F3, "state": "OPEN"}]
        orig_gh, orig_cache = topic.gh, topic.CACHE
        topic.gh, topic.CACHE = (lambda *a: json.dumps(listing)), cache
        try:
            n, invalid = topic.sync()
        finally:
            topic.gh, topic.CACHE = orig_gh, orig_cache
        data = json.loads(cache.read_text())
        check("AC-4 INVALID 的單不寫進 cache",
              "999" not in data and data.get("285", {}).get("thread_id") == 2620,
              json.dumps(data, ensure_ascii=False))
        check("AC-4 INVALID 的單號被回報（供腳本層 exit 非 0）",
              invalid == ["999"] and n == 1, f"n={n} invalid={invalid!r}")


# ── AC-5 archive.py:394 反向查找錨定 ───────────────────────────────────────
@case("AC-5 issue_meta：body 只在表格列提及 thread=2620 → 不命中")
def _ac5():
    listing = [{"number": 285, "title": "單 B", "body": F_TABLE_ONLY, "state": "OPEN"}]

    def fake_run(cmd, *a, **kw):
        assert cmd[:2] == ["gh", "issue"], cmd
        return subprocess.CompletedProcess(cmd, 0, json.dumps(listing), "")

    with tempfile.TemporaryDirectory() as td:
        orig_cache, orig_run = archive.CACHE, subprocess.run
        archive.CACHE = Path(td) / "nonexistent.json"     # cache 必須不存在才會查 forge
        subprocess.run = fake_run                          # issue_meta 內是 `import subprocess`
        try:
            got = archive.issue_meta("2620")
        finally:
            archive.CACHE, subprocess.run = orig_cache, orig_run
    check("AC-5 不命中該 issue（issue 號為 None、退回 thread 命名）",
          got == (None, "thread 2620", None), f"實得 {got!r}")

    # 正向對照：有獨立一行的標記時必須命中，否則本測試沒有鑑別力
    listing = [{"number": 285, "title": "單 A", "body": F1, "state": "OPEN"}]
    with tempfile.TemporaryDirectory() as td:
        orig_cache, orig_run = archive.CACHE, subprocess.run
        archive.CACHE = Path(td) / "nonexistent.json"
        subprocess.run = fake_run
        try:
            got2 = archive.issue_meta("2620")
        finally:
            archive.CACHE, subprocess.run = orig_cache, orig_run
    check("AC-5 對照組：有獨立一行標記時確實命中",
          got2 == ("285", "單 A", "OPEN"), f"實得 {got2!r}")

    check("AC-5 未達成候選（未錨定 re.search）確實會誤命中表格列",
          bool(re.search(r"<!-- devflow:topic thread=2620 -->", F_TABLE_ONLY)),
          "對照組")

    # has_topic 的散文／縮排反例
    check("AC-5 散文旁註不命中", not marker.has_topic(
        "散文 <!-- devflow:topic thread=2620 --> 旁註\n", "2620"))
    check("AC-5 縮排不命中（CH3 的 ^…$ 不理 markdown，#285 body 即靠此處置）",
          not marker.has_topic("  <!-- devflow:topic thread=2620 -->\n", "2620"))
    check("AC-5 thread 值不同不命中", not marker.has_topic(F1, "777"))


# ── AC-5（第 2 輪補）BLOCK-1：反向查找遇 T>1 必須停下，不得續掃 ─────────────
# 審查位 R1 第 1 輪的 BLOCK-1 反例：第 1 輪的 has_topic 遇 T>1 只印 stderr 後回 False，
# 於是 issue_meta 的迴圈**繼續掃**，在下一張合法的 issue 命中同一 thread 並回傳它
# ——匯出檔會掛到別人的單。T 的裁定表對 T>1／A>1 明寫「exit 非 0 ＋ stderr 印 INVALID
# 與命中的所有行，停下不動 forge」，反向查找同樣適用。
BLOCK1_ROWS = [
    {"number": 285, "title": "invalid",
     "body": "<!-- devflow:topic thread=2620 -->\n<!-- devflow:topic thread=999 -->\n",
     "state": "OPEN"},
    {"number": 286, "title": "other",
     "body": "<!-- devflow:topic thread=2620 -->\n", "state": "OPEN"},
]


def _issue_meta_with(rows, *, has_topic=None):
    """在假 gh 輸出與（可選）替換過的 has_topic 下跑 issue_meta，回傳值或擲出的例外。

    `has_topic` 參數供鑑別力子測試注入「回 False 的舊版」——證明本測試真的在
    檢驗停下的行為，而不是任何實作都會過。
    """
    def fake_run(cmd, *a, **kw):
        assert cmd[:2] == ["gh", "issue"], cmd
        return subprocess.CompletedProcess(cmd, 0, json.dumps(rows), "")

    with tempfile.TemporaryDirectory() as td:
        orig_cache, orig_run = archive.CACHE, subprocess.run
        orig_has = marker.has_topic
        archive.CACHE = Path(td) / "nonexistent.json"
        subprocess.run = fake_run
        if has_topic is not None:
            marker.has_topic = has_topic          # issue_meta 經 `_marker.has_topic` 取用
        try:
            return ("return", archive.issue_meta("2620"))
        except marker.InvalidMarker as e:
            return ("raise", e)
        finally:
            archive.CACHE, subprocess.run = orig_cache, orig_run
            marker.has_topic = orig_has


@case("AC-5／BLOCK-1 issue_meta 遇 T>1：raise INVALID，不得回傳 ('286', …)")
def _ac5_block1():
    kind, val = _issue_meta_with(BLOCK1_ROWS)
    check("AC-5／BLOCK-1 issue_meta 擲出 InvalidMarker（而非回傳值）",
          kind == "raise", f"實得 {kind}={val!r}")
    check("AC-5／BLOCK-1 不得回傳另一張 issue（#286）",
          not (kind == "return" and val and val[0] == "286"),
          f"實得 {val!r}")
    check("AC-5／BLOCK-1 不得退回 fallback `thread 2620`",
          not (kind == "return" and val == (None, "thread 2620", None)),
          f"實得 {val!r}")
    if kind == "raise":
        msg = str(val)
        check("AC-5／BLOCK-1 例外訊息含 INVALID 字樣", "INVALID" in msg, msg)
        check("AC-5／BLOCK-1 例外訊息含兩行命中的字面",
              all(ln in msg for ln in F3_LINES), msg)
        check("AC-5／BLOCK-1 例外是模組共用的那個類別（與正向同一個）",
              type(val) is marker.InvalidMarker
              and isinstance(val, marker.InvalidMarker), f"{type(val)!r}")

    # 鑑別力：換成第 1 輪「回 False」的 has_topic，本子測試必須 FAIL
    def has_topic_returning_false(body, thread):
        ids, lines = marker.find_topic(body)
        if len(lines) > 1:
            return False                      # ← 第 1 輪被 BLOCK-1 擋下的那個行為
        return bool(ids) and ids[0] == str(thread)

    kind2, val2 = _issue_meta_with(BLOCK1_ROWS, has_topic=has_topic_returning_false)
    check("AC-5／BLOCK-1 鑑別力：換回『回 False』版後 issue_meta 不再 raise",
          kind2 == "return", f"實得 {kind2}={val2!r}")
    check("AC-5／BLOCK-1 鑑別力：且確實回傳了別人的單 #286（＝BLOCK-1 的危害）",
          kind2 == "return" and val2 == ("286", "other", "OPEN"),
          f"實得 {val2!r} —— 若此處不成立，上面的斷言就不是在檢驗停下的行為")

    # 對照組：沒有 INVALID 的單時，issue_meta 照常回傳（修法不是一律 raise）
    kind3, val3 = _issue_meta_with([BLOCK1_ROWS[1]])
    check("AC-5／BLOCK-1 對照組：全部合法時照常回傳 #286",
          (kind3, val3) == ("return", ("286", "other", "OPEN")),
          f"實得 {kind3}={val3!r}")

    # has_archived 同型處置
    dup_arch = ("<!-- devflow:archived thread=2620 file=a.md -->\n"
                "<!-- devflow:archived thread=999 file=b.md -->\n")
    try:
        marker.has_archived(dup_arch, "2620")
    except marker.InvalidMarker as e:
        check("AC-5／BLOCK-1 has_archived 遇 A>1 亦 raise 同一類別",
              "INVALID" in str(e) and "file=a.md" in str(e) and "file=b.md" in str(e),
              str(e))
    else:
        check("AC-5／BLOCK-1 has_archived 遇 A>1 亦 raise", False, "回傳了布林值")


def _seed_home(home: Path):
    """種一則 thread=2620 的訊息，否則 _export 在 collect() 就 SystemExit，走不到 issue_meta。"""
    import sqlite3
    import time
    now = time.time()
    for prof in ("dfcoord", "dfmgr", "dfrev", "dfimpl"):
        d = home / ".hermes" / "profiles" / prof
        d.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(d / "state.db")
        conn.execute("create table sessions (id TEXT PRIMARY KEY, source TEXT, "
                     "thread_id TEXT, started_at REAL)")
        conn.execute("create table messages (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                     "session_id TEXT, role TEXT, content TEXT, tool_name TEXT, "
                     "tool_calls TEXT, timestamp REAL, display_kind TEXT)")
        if prof == "dfcoord":
            conn.execute("insert into sessions (id,source,thread_id,started_at) "
                         "values ('s1','telegram','2620',?)", (now,))
            conn.execute("insert into messages (session_id,role,content,timestamp) "
                         "values ('s1','user','誘餌訊息',?)", (now,))
        conn.commit()
        conn.close()


def _fake_gh(bin_: Path, rows):
    """假 gh：`issue list` 回 rows，其餘呼叫一律失敗。"""
    fake = bin_ / "gh"
    fake.write_text("#!/usr/bin/env python3\n"
                    "import json, sys\n"
                    "a = sys.argv[1:]\n"
                    "if a[:2] == ['issue', 'list']:\n"
                    f"    print(json.dumps({rows!r}))\n"
                    "    sys.exit(0)\n"
                    "print('unexpected gh call', file=sys.stderr)\n"
                    "sys.exit(8)\n")
    fake.chmod(0o755)


def _run_archive_cli(rows, label: str, *, script: Path | None = None,
                     expect_stop: bool = True):
    """以子程序跑 `devflow_archive.py export 2620`，斷言停下（或在突變下不停）。

    `script` 可指向突變複本（鑑別力子測試用）；`expect_stop=False` 時反向斷言
    ——證明這些斷言真的在檢驗停下的行為。
    """
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        home, bin_ = td / "home", td / "bin"
        bin_.mkdir()
        _fake_gh(bin_, rows)
        _seed_home(home)
        env = dict(os.environ, HOME=str(home),
                   PATH=f"{bin_}:{os.environ.get('PATH', '')}",
                   PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([PY, str(script or (SCRIPTS / "devflow_archive.py")),
                            "export", "2620"],
                           capture_output=True, text=True, env=env,
                           stdin=subprocess.DEVNULL, timeout=120)
        leftovers = [str(p) for p in (home / ".hermes" / "archives").rglob("*")
                     if p.is_file()]
        detail = (f"exit={r.returncode}\n--- stdout ---\n{r.stdout}"
                  f"--- stderr ---\n{r.stderr}")
        if expect_stop:
            check(f"{label} 腳本 exit 非 0", r.returncode != 0, detail)
            check(f"{label} stderr 含 INVALID 字樣", "INVALID" in r.stderr, detail)
            check(f"{label} stderr 含兩行命中的字面",
                  all(ln in r.stderr for ln in F3_LINES), detail)
            check(f"{label} stderr 不只是 traceback（有可讀的 INVALID 行）",
                  "Traceback" not in r.stderr, detail)
            check(f"{label} 未產生匯出檔（不得掛到 #286）",
                  not leftovers, detail + f"\n殘留：{leftovers}")
        else:
            check(f"{label} 鑑別力：突變版確實不停下（exit 0 ＋ 產生匯出檔）",
                  r.returncode == 0 and leftovers, detail + f"\n殘留：{leftovers}")
            check(f"{label} 鑑別力：突變版把匯出檔掛到了 #286",
                  any(Path(p).name.startswith("286.") for p in leftovers),
                  f"殘留：{leftovers}")
        return r, leftovers


@case("AC-5／BLOCK-1 archive 腳本層：stderr 印 INVALID 與命中行、exit 非 0、無匯出檔")
def _ac5_block1_script():
    _run_archive_cli(BLOCK1_ROWS, "AC-5／BLOCK-1")


# ── AC-5（第 3 輪補）BLOCK-1：停不停下不得取決於 gh 的回傳順序 ───────────────
# 審查位 R1 第 2 輪的 BLOCK-1 反例：第 2 輪的 issue_meta 在第一個合法命中就 return，
# 於是排在它後面的 T>1 單根本不會送進 has_topic。同一份資料只把順序反轉，
# 「停下」就變成「回傳 ('286','valid-first','OPEN')、exit 0」——那不是判定。
# 處置：掃完整個列表才回傳。
# 標題與審查位反例逐字相同（valid-first／invalid-after），body 與 BLOCK1_ROWS 同。
BLOCK1_ROWS_REVERSED = [
    {"number": 286, "title": "valid-first",
     "body": BLOCK1_ROWS[1]["body"], "state": "OPEN"},
    {"number": 285, "title": "invalid-after",
     "body": BLOCK1_ROWS[0]["body"], "state": "OPEN"},
]

# 多張不同 issue 都合法主張同一 thread（掃完才可能發現；本實作視為 INVALID）
MULTI_CLAIM_ROWS = [
    {"number": 286, "title": "claim-A",
     "body": "<!-- devflow:topic thread=2620 -->\n", "state": "OPEN"},
    {"number": 287, "title": "claim-B",
     "body": "<!-- devflow:topic thread=2620 -->\n", "state": "CLOSED"},
]


def _early_return_copy(td: Path) -> Path:
    """`issue_meta` 恢復第 2 輪「第一個命中就 return」的突變複本。

    與 `_marker.py` 放同一個暫存目錄，故突變複本的 `import _marker` 仍解析得到
    （受測的是 archive 的迴圈，不是 grammar）。
    """
    src = (SCRIPTS / "devflow_archive.py").read_text()
    mutated = src.replace(
        """        hits = []
        for item in json.loads(out or "[]"):
            # 掃完才回傳：不在第一個命中就 return，否則排在後面的 T>1 不會被看到。
            if _marker.has_topic(item.get("body") or "", thread):
                hits.append(item)""",
        """        for item in json.loads(out or "[]"):
            if _marker.has_topic(item.get("body") or "", thread):
                return str(item["number"]), item["title"], (item.get("state") or "").upper()
        hits = []""",
    )
    assert mutated != src, "突變未套用——early-return 的目標字串已變，鑑別力子測試失效"
    out = td / "devflow_archive.py"
    out.write_text(mutated)
    (td / "_marker.py").write_text((SCRIPTS / "_marker.py").read_text())
    return out


@case("AC-5／BLOCK-1(3) 反序 fixture：合法 #286 在前、INVALID #285 在後 → 仍 raise")
def _ac5_block1_order():
    kind, val = _issue_meta_with(BLOCK1_ROWS_REVERSED)
    check("AC-5／BLOCK-1(3) 反序時 issue_meta 仍 raise InvalidMarker",
          kind == "raise", f"實得 {kind}={val!r}")
    check("AC-5／BLOCK-1(3) 反序時不得回傳 ('286', …)",
          not (kind == "return" and val and val[0] == "286"), f"實得 {val!r}")
    if kind == "raise":
        msg = str(val)
        check("AC-5／BLOCK-1(3) 反序的例外訊息含 INVALID 與兩行字面",
              "INVALID" in msg and all(ln in msg for ln in F3_LINES), msg)

    # 順序無關性：正序與反序必須得到同一種結果（同一份資料，只改順序）
    kind_f, val_f = _issue_meta_with(BLOCK1_ROWS)
    check("AC-5／BLOCK-1(3) 正序與反序結果一致（順序不改變判定）",
          kind_f == kind == "raise" and str(val_f) == str(val),
          f"正序 {kind_f}={val_f!r}\n        反序 {kind}={val!r}")


@case("AC-5／BLOCK-1(3) 反序 fixture 的 CLI 層：rc 非 0、stderr 含 INVALID 與兩行、無匯出檔")
def _ac5_block1_order_cli():
    _run_archive_cli(BLOCK1_ROWS_REVERSED, "AC-5／BLOCK-1(3) 反序")


@case("AC-5／BLOCK-1(3) 鑑別力：恢復 early return 後反序子測試須 FAIL")
def _ac5_block1_order_mutation():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        mut_path = _early_return_copy(td)
        # 函式層：載入突變複本，反序時它會回傳 #286（＝BLOCK-1 的危害）
        spec = importlib.util.spec_from_file_location("devflow_archive_mut", mut_path)
        mut = importlib.util.module_from_spec(spec)
        sys.modules["devflow_archive_mut"] = mut
        spec.loader.exec_module(mut)

        def fake_run(cmd, *a, **kw):
            return subprocess.CompletedProcess(
                cmd, 0, json.dumps(BLOCK1_ROWS_REVERSED), "")

        orig_run = subprocess.run
        mut.CACHE = td / "nonexistent.json"
        subprocess.run = fake_run
        try:
            got = ("return", mut.issue_meta("2620"))
        except marker.InvalidMarker as e:
            got = ("raise", e)
        finally:
            subprocess.run = orig_run
        check("AC-5／BLOCK-1(3) 鑑別力：突變版在反序下回傳 ('286','valid-first','OPEN')",
              got == ("return", ("286", "valid-first", "OPEN")),
              f"實得 {got[0]}={got[1]!r} —— 若此處不成立，反序斷言就不是在檢驗順序無關性")
        # 突變版在正序下仍 raise——正是「同一份資料只改順序就改變判定」的證明
        subprocess.run = lambda cmd, *a, **kw: subprocess.CompletedProcess(
            cmd, 0, json.dumps(BLOCK1_ROWS), "")
        try:
            got2 = ("return", mut.issue_meta("2620"))
        except marker.InvalidMarker as e:
            got2 = ("raise", e)
        finally:
            subprocess.run = orig_run
        check("AC-5／BLOCK-1(3) 鑑別力：突變版正序 raise、反序 return（順序改變判定）",
              got2[0] == "raise" and got[0] == "return",
              f"正序 {got2[0]}　反序 {got[0]}")

        # CLI 層：突變複本在反序下 exit 0 且把匯出檔掛到 #286
        _run_archive_cli(BLOCK1_ROWS_REVERSED, "AC-5／BLOCK-1(3) 反序",
                         script=mut_path, expect_stop=False)


@case("AC-5／BLOCK-1(3) 多張不同 issue 主張同一 thread → 視為 INVALID 停下")
def _ac5_multi_claim():
    kind, val = _issue_meta_with(MULTI_CLAIM_ROWS)
    check("AC-5／BLOCK-1(3) 兩張單都合法命中 2620 時 raise（不取第一個）",
          kind == "raise", f"實得 {kind}={val!r}")
    if kind == "raise":
        msg = str(val)
        check("AC-5／BLOCK-1(3) 訊息含 INVALID 與兩張單號",
              "INVALID" in msg and "#286" in msg and "#287" in msg, msg)
        check("AC-5／BLOCK-1(3) 例外是模組共用的那個類別",
              type(val) is marker.InvalidMarker, f"{type(val)!r}")
    # 三張時數目正確
    kind3, val3 = _issue_meta_with(MULTI_CLAIM_ROWS + [
        {"number": 288, "title": "claim-C",
         "body": "<!-- devflow:topic thread=2620 -->\n", "state": "OPEN"}])
    check("AC-5／BLOCK-1(3) 三張時訊息回報 3 張",
          kind3 == "raise" and "3 張" in str(val3) and "#288" in str(val3),
          f"實得 {kind3}={val3!r}")
    # 對照組：恰一張命中時照常回傳（多張判定不影響正常路徑）
    kind1, val1 = _issue_meta_with([MULTI_CLAIM_ROWS[0]])
    check("AC-5／BLOCK-1(3) 對照組：恰一張命中時照常回傳",
          (kind1, val1) == ("return", ("286", "claim-A", "OPEN")),
          f"實得 {kind1}={val1!r}")
    # 對照組：無命中時仍退回 thread 命名（fallback 未被破壞）
    kind0, val0 = _issue_meta_with([
        {"number": 286, "title": "無關", "body": "# 沒有標記\n", "state": "OPEN"}])
    check("AC-5／BLOCK-1(3) 對照組：無命中時退回 `thread 2620`",
          (kind0, val0) == ("return", (None, "thread 2620", None)),
          f"實得 {kind0}={val0!r}")


# ── AC-6 grammar 單一來源且逐字相同 ────────────────────────────────────────
def _readme_patterns() -> list[str]:
    """從 channels/README.md 抽出 `grep -cE '…'` 的 pattern 字串（條文側的權威字面）。"""
    text = CHANNELS_README.read_text()
    return re.findall(r"grep -cE '([^']*)'", text)


@case("AC-6 grammar 與 channels/README.md:59 的 T／A 兩式逐字相同")
def _ac6():
    pats = _readme_patterns()
    check("AC-6 README 恰抽出兩個判定式 pattern", len(pats) == 2, f"{pats!r}")
    if len(pats) != 2:
        return
    t_pat, a_pat = pats

    def equals_doctrine(const: str, doctrine: str) -> bool:
        """唯一的比對函式——鑑別力子測試對它餵改過的常數，必須回 False。"""
        return const == doctrine

    check("AC-6 TOPIC_RE 逐字相同", equals_doctrine(marker.TOPIC_RE, t_pat),
          f"模組 {marker.TOPIC_RE!r}\n        條文 {t_pat!r}")
    check("AC-6 ARCHIVED_RE 逐字相同", equals_doctrine(marker.ARCHIVED_RE, a_pat),
          f"模組 {marker.ARCHIVED_RE!r}\n        條文 {a_pat!r}")

    # 鑑別力：同一個比對函式對「改一個字元」的副本須失敗，否則此 AC 不構成證據
    mutants = {
        "尾端多一字元": marker.TOPIC_RE + "x",
        "拔掉行尾錨點": marker.TOPIC_RE[:-1],
        "拔掉行首錨點": marker.TOPIC_RE[1:],
        "\\d+ 代替 [0-9]+": marker.TOPIC_RE.replace("[0-9]+", r"\d+"),
        "改一個字元（topic→topic）": marker.TOPIC_RE.replace("topic", "topiс"),
    }
    for name, bad in mutants.items():
        check(f"AC-6 鑑別力：{name} 的副本比對須失敗",
              not equals_doctrine(bad, t_pat), f"{bad!r}")
    check("AC-6 鑑別力：ARCHIVED_RE 改一字元須失敗",
          not equals_doctrine(marker.ARCHIVED_RE + "x", a_pat))

    # 已編譯物件的 pattern 必須就是那兩個常數（不是另一條等價的正則）
    check("AC-6 TOPIC.pattern 即 TOPIC_RE", marker.TOPIC.pattern == marker.TOPIC_RE)
    check("AC-6 ARCHIVED.pattern 即 ARCHIVED_RE",
          marker.ARCHIVED.pattern == marker.ARCHIVED_RE)
    check("AC-6 兩式皆以 MULTILINE 編譯（grep 是逐行比對）",
          bool(marker.TOPIC.flags & re.MULTILINE) and bool(marker.ARCHIVED.flags & re.MULTILINE),
          f"{marker.TOPIC.flags} {marker.ARCHIVED.flags}")
    # 取 id 用的 pattern 只多一個捕獲群組，其餘字面不動
    check("AC-6 TOPIC_ID 只在 thread 欄多一個捕獲群組",
          marker.TOPIC_ID.pattern == marker.TOPIC_RE.replace("thread=[0-9]+",
                                                             "thread=([0-9]+)"),
          f"{marker.TOPIC_ID.pattern!r}")
    check("AC-6 ARCHIVED_ID 只在 thread 欄多一個捕獲群組",
          marker.ARCHIVED_ID.pattern == marker.ARCHIVED_RE.replace("thread=[0-9]+",
                                                                   "thread=([0-9]+)"),
          f"{marker.ARCHIVED_ID.pattern!r}")

    # 條文的 grep 行為對照：直接跑 grep -cE 與模組計數比對（同一份 pattern，同一個答案）
    for label, body, want in (("F1", F1, 1), ("F2", F2, 1), ("F3", F3, 2),
                              ("F_TABLE_ONLY", F_TABLE_ONLY, 0)):
        g = subprocess.run(["grep", "-cE", t_pat], input=body,
                           capture_output=True, text=True)
        grep_n = int((g.stdout or "0").strip() or 0)
        mod_n = len(marker.find_topic(body)[1])
        check(f"AC-6 {label}：grep -cE 的 T({grep_n}) == 模組計數({mod_n}) == {want}",
              grep_n == mod_n == want, f"grep={grep_n} module={mod_n}")


# ── AC-7 正向與反向共用同一份 grammar 常數 ─────────────────────────────────
@case("AC-7 正向（body→id）與反向（id→是否屬此 body）共用同一份常數")
def _ac7():
    check("AC-7 模組同時提供正向與反向 API",
          all(callable(getattr(marker, n, None))
              for n in ("read_topic", "find_topic", "has_topic", "upsert_topic")),
          f"{[n for n in ('read_topic','find_topic','has_topic','upsert_topic') if not callable(getattr(marker, n, None))]}")

    # 結構：三者都經由 find_topic，find_topic 只引用 TOPIC／TOPIC_ID 這兩個已編譯物件
    check("AC-7 find_topic 只引用 TOPIC_ID／TOPIC 兩個模組常數",
          {"TOPIC_ID", "TOPIC"} <= set(marker.find_topic.__code__.co_names),
          f"{marker.find_topic.__code__.co_names!r}")
    for fn in ("read_topic", "has_topic", "upsert_topic"):
        names = set(getattr(marker, fn).__code__.co_names)
        check(f"AC-7 {fn} 經由 find_topic 取值（不自備正則）",
              "find_topic" in names and not {"compile", "search", "findall"} & names,
              f"{sorted(names)!r}")

    # 同一性：正向與反向拿到的是同一個 compiled pattern 物件
    check("AC-7 TOPIC 與 TOPIC_ID 皆為 re.Pattern 且同源字面",
          isinstance(marker.TOPIC, re.Pattern) and isinstance(marker.TOPIC_ID, re.Pattern)
          and marker.TOPIC_ID.pattern.replace("([0-9]+)", "[0-9]+") == marker.TOPIC.pattern,
          f"{marker.TOPIC_ID.pattern!r}")

    # 行為一致：對同一組 fixture，正向與反向的答案必須互相印證
    for label, body in (("F1", F1), ("F2", F2), ("F3", F3),
                        ("F_TABLE_ONLY", F_TABLE_ONLY)):
        _, lines = marker.find_topic(body)
        if len(lines) == 1:
            tid = marker.read_topic(body)
            ok = marker.has_topic(body, tid) and marker.has_topic(body, str(tid))
            check(f"AC-7 {label}：has_topic(body, read_topic(body)) 為真（int 與 str 皆然）",
                  ok, f"tid={tid!r}")
            check(f"AC-7 {label}：has_topic 對別的 thread 為假",
                  not marker.has_topic(body, tid + 1))
        elif not lines:
            check(f"AC-7 {label}：T=0 時正向 None、反向一律 False",
                  marker.read_topic(body) is None
                  and not marker.has_topic(body, "2620"))
        else:
            # T>1：正向與反向都必須 raise 同一個類別（`BLOCK-1` 的處置）。
            # 反向回 False 會讓呼叫端的掃描繼續，第 1 輪即因此被擋下。
            raised_fwd = raised_rev = raised_rev2 = False
            try:
                marker.read_topic(body)
            except marker.InvalidMarker:
                raised_fwd = True
            try:
                marker.has_topic(body, "2620")
            except marker.InvalidMarker:
                raised_rev = True
            try:
                marker.has_topic(body, "999")
            except marker.InvalidMarker:
                raised_rev2 = True
            check(f"AC-7 {label}：T>1 時正向與反向皆 raise（反向不得回 False 續掃）",
                  raised_fwd and raised_rev and raised_rev2,
                  f"正向 raise={raised_fwd} 反向(2620) raise={raised_rev} "
                  f"反向(999) raise={raised_rev2}")

    # 兩支腳本都用這同一個模組物件（不是各自複製一份）
    check("AC-7 devflow_topic 與 devflow_archive 用同一個 _marker 模組物件",
          topic._marker is marker and archive._marker is marker,
          f"topic={topic._marker!r} archive={archive._marker!r}")

    # 封存標記走同一組 API（本單不改 archive 的寫入，但 grammar 已就位供 #287／#286）
    arch_body = ("# 已封存\n\n<!-- devflow:topic thread=2620 -->\n"
                 "<!-- devflow:archived thread=2620 file=~/.hermes/archives/topics/285.md -->\n")
    check("AC-7 封存標記：正向讀出 2620",
          marker.read_archived(arch_body) == 2620,
          f"{marker.read_archived(arch_body)!r}")
    check("AC-7 封存標記：反向命中 2620", marker.has_archived(arch_body, "2620"))
    check("AC-7 封存標記：缺 file= 欄不算（CH3 的 A 式）",
          marker.read_archived("<!-- devflow:archived thread=2620 -->\n") is None)
    check("AC-7 封存標記：file= 含空白不算",
          marker.read_archived(
              "<!-- devflow:archived thread=2620 file=a b -->\n") is None)


# ════════════════════════════════════════════════════════════════════════════
# `#291`／K4c-4：寫側對稱（`archived_line`／`upsert_archived`）＋ archive 第四步
# ════════════════════════════════════════════════════════════════════════════
# 本單的 AC 編號獨立於上方 `#285` 的 AC-1～AC-7，標籤一律帶 `#291` 前綴。

MARKER_SRC = (SCRIPTS / "_marker.py").read_text()
ARCHIVE_SRC = (SCRIPTS / "devflow_archive.py").read_text()


# ── #291 AC-1 archived_line 產出合規字面，三個反例各自 raise ──────────────────
@case("#291 AC-1 archived_line 產出恰匹配 ARCHIVED_RE，三個反例 raise")
def _p291_ac1():
    line = marker.archived_line(2620, "/home/augustushsu/.hermes/archives/topics/285.md")
    check("#291 AC-1 產出 re.fullmatch(ARCHIVED_RE)",
          bool(re.fullmatch(marker.ARCHIVED_RE, line)), repr(line))
    check("#291 AC-1 產出的字面與條文形狀逐字相符",
          line == ("<!-- devflow:archived thread=2620 "
                   "file=/home/augustushsu/.hermes/archives/topics/285.md -->"),
          repr(line))
    # 以條文的 grep -cE 複驗（A=1）——不靠模組自己的計數
    pats = _readme_patterns()
    if len(pats) == 2:
        g = subprocess.run(["grep", "-cE", pats[1]], input=line + "\n",
                           capture_output=True, text=True)
        check("#291 AC-1 條文的 grep -cE 對該行計得 A=1",
              (g.stdout or "0").strip() == "1", f"grep 輸出 {g.stdout!r}")
    # thread 接受 str 與 int（呼叫端從 argparse 拿到的是 str）
    check("#291 AC-1 thread 給字串 '2620' 亦合規",
          bool(re.fullmatch(marker.ARCHIVED_RE, marker.archived_line("2620", "/a/b.md"))))
    # pathlib.Path 也要能直接餵（cmd_archive 的 md_path 是 Path）
    check("#291 AC-1 file 給 pathlib.Path 亦合規",
          bool(re.fullmatch(marker.ARCHIVED_RE,
                            marker.archived_line(2620, Path("/a/b.md")))))

    # 三個反例：不得放寬 grammar（不得引號包裹、不得百分號編碼），一律 raise
    bad_cases = [
        ("file 含空白", (2620, "/a path/285.md")),
        ("file 含 >", (2620, "/a/b>c.md")),
        ("thread 非數字", ("abc", "/a/b.md")),
    ]
    for label, (th, fi) in bad_cases:
        try:
            got = marker.archived_line(th, fi)
        except ValueError as e:
            check(f"#291 AC-1 反例（{label}）raise ValueError", True)
            check(f"#291 AC-1 反例（{label}）訊息說明原因（含 grammar 或欄位值）",
                  marker.ARCHIVED_RE in str(e) or repr(fi) in str(e) or repr(th) in str(e),
                  str(e))
        else:
            check(f"#291 AC-1 反例（{label}）raise", False,
                  f"竟回傳 {got!r} —— 不得放寬 grammar（CH3 的 [^ >]+ 是字面）")
    # 鑑別力：三個反例若「硬拼字串不驗」會產出不合規字面（A=0），正是本單在修的病
    for label, (th, fi) in bad_cases:
        naive = f"<!-- devflow:archived thread={th} file={fi} -->"
        check(f"#291 AC-1 鑑別力：硬拼（{label}）確實不合 ARCHIVED_RE（會落回 A=0）",
              not re.fullmatch(marker.ARCHIVED_RE, naive), repr(naive))
    # 不得以引號包裹／百分號編碼「繞過」：那兩種形狀本身也不合 grammar
    check("#291 AC-1 引號包裹不是合法出路（含空白仍不合）",
          not re.fullmatch(marker.ARCHIVED_RE,
                           '<!-- devflow:archived thread=2620 file="/a path/b.md" -->'))
    # 跨行的 file= 值：fullmatch 會接受（`[^ >]+` 不排除 \n），但條文的 A 是逐行比對
    try:
        marker.archived_line(2620, "/a\n/b.md")
    except ValueError as e:
        check("#291 AC-1 反例（file 含換行）raise ValueError", True, str(e).splitlines()[0])
    else:
        check("#291 AC-1 反例（file 含換行）raise", False,
              "跨行字面寫進 body 會裂成兩行、兩行都不合 grammar（A=0）")


# ── #291 AC-2 upsert_archived 三分支與 upsert_topic 同形 ────────────────────
P291_F_A0 = """# 某單

| 形態 | 字面 |
|---|---|
| 表格列內 | `<!-- devflow:archived thread=123 file=/t/123.md -->` |

散文也提一次 <!-- devflow:archived thread=123 file=/t/123.md --> 如上。
  <!-- devflow:archived thread=123 file=/t/indent.md -->

<!-- devflow:topic thread=2620 -->
"""

P291_F_A1 = P291_F_A0 + "<!-- devflow:archived thread=2620 file=/t/old.md -->\n"

P291_F_A2 = (P291_F_A0
             + "<!-- devflow:archived thread=2620 file=/t/one.md -->\n"
             + "<!-- devflow:archived thread=999 file=/t/two.md -->\n")

P291_A2_LINES = [
    "<!-- devflow:archived thread=2620 file=/t/one.md -->",
    "<!-- devflow:archived thread=999 file=/t/two.md -->",
]

P291_ANCHOR_DECOYS = [
    "| 表格列內 | `<!-- devflow:archived thread=123 file=/t/123.md -->` |",
    "散文也提一次 <!-- devflow:archived thread=123 file=/t/123.md --> 如上。",
    "  <!-- devflow:archived thread=123 file=/t/indent.md -->",
]


@case("#291 AC-2 upsert_archived：A=0 追加、A=1 取代、A>1 raise；錨定同 upsert_topic")
def _p291_ac2():
    new_file = "/home/augustushsu/.hermes/archives/topics/291.md"

    # A=0 → 尾端追加獨立一行
    out0 = marker.upsert_archived(P291_F_A0, 2620, new_file)
    ids0, lines0 = marker.find_archived(out0)
    check("#291 AC-2 A=0 時在尾端追加獨立一行",
          len(lines0) == 1 and ids0 == ["2620"]
          and out0.startswith(P291_F_A0.rstrip()), repr(out0))
    check("#291 AC-2 A=0 追加後 topic 標記未受影響（T 仍為 1）",
          marker.read_topic(out0) == 2620)
    for decoy in P291_ANCHOR_DECOYS:
        check(f"#291 AC-2 A=0 同形字串一字不動：{decoy[:28]}…", decoy in out0, repr(out0))

    # A=1 → 只取代那一行，不新增第二行
    out1 = marker.upsert_archived(P291_F_A1, 2620, new_file)
    ids1, lines1 = marker.find_archived(out1)
    check("#291 AC-2 A=1 時恰一個標記（取代而非新增）",
          len(lines1) == 1 and ids1 == ["2620"], f"A={len(lines1)} {lines1!r}")
    check("#291 AC-2 A=1 取代後舊的 file=/t/old.md 不存在",
          "<!-- devflow:archived thread=2620 file=/t/old.md -->" not in out1.splitlines(),
          repr(out1))
    check("#291 AC-2 A=1 取代後 file= 欄為新值", f"file={new_file} -->" in out1, repr(out1))
    check("#291 AC-2 A=1 時 body 其餘內容未被改寫（只差那一行）",
          [l for l in P291_F_A1.splitlines()
           if l != "<!-- devflow:archived thread=2620 file=/t/old.md -->"]
          == [l for l in out1.splitlines() if l != marker.archived_line(2620, new_file)],
          repr(out1))
    for decoy in P291_ANCHOR_DECOYS:
        check(f"#291 AC-2 A=1 同形字串一字不動：{decoy[:28]}…", decoy in out1, repr(out1))

    # A>1 → raise InvalidMarker，不回傳 body
    try:
        got = marker.upsert_archived(P291_F_A2, 2620, new_file, detail="issue #291")
    except marker.InvalidMarker as e:
        check("#291 AC-2 A>1 raise InvalidMarker（不回傳 body）", True)
        check("#291 AC-2 A>1 例外訊息含 INVALID 與兩行命中的字面",
              "INVALID" in str(e) and all(ln in str(e) for ln in P291_A2_LINES), str(e))
        check("#291 AC-2 A>1 例外物件帶全部命中行且 kind=archived",
              e.lines == P291_A2_LINES and e.kind == "archived", f"{e.kind} {e.lines!r}")
        check("#291 AC-2 A>1 例外訊息含 detail（呼叫端的上下文）",
              "issue #291" in str(e), str(e))
    else:
        check("#291 AC-2 A>1 raise InvalidMarker", False, f"竟回傳 {got!r}")

    # 不合 grammar 時 raise 且 body 不動（呼叫端拿不到半成品去寫 forge）
    for label, fi in (("含空白", "/a path/291.md"), ("含 >", "/a/b>c.md")):
        try:
            marker.upsert_archived(P291_F_A0, 2620, fi)
        except ValueError:
            check(f"#291 AC-2 file {label} 時 upsert 亦 raise ValueError", True)
        else:
            check(f"#291 AC-2 file {label} 時 upsert 亦 raise", False, "竟回傳了 body")

    # 鑑別力：未錨定的 re.sub（原實作的病）會改掉表格列、散文與縮排
    bad = re.sub(r"<!-- devflow:archived thread=\d+ file=[^>]* -->",
                 marker.archived_line(2620, new_file), P291_F_A1)
    check("#291 AC-2 鑑別力：未錨定 re.sub 確實會改掉同形字串",
          all(d not in bad for d in P291_ANCHOR_DECOYS), repr(bad))

    # 與 upsert_topic 的同形性：兩者對 T/A=0 的追加形狀一致（空行＋一行＋換行）
    t0 = marker.upsert_topic("# x\n\n內容。\n", 7)
    a0 = marker.upsert_archived("# x\n\n內容。\n", 7, "/t/7.md")
    check("#291 AC-2 與 upsert_topic 的追加形狀一致（尾端空一行、標記獨立一行）",
          t0 == "# x\n\n內容。\n\n" + marker.topic_line(7) + "\n"
          and a0 == "# x\n\n內容。\n\n" + marker.archived_line(7, "/t/7.md") + "\n",
          f"{t0!r}\n        {a0!r}")


# ── #291 AC-3 公開 API 的 topic／archived 名稱對稱 ──────────────────────────
def _public_funcs(src: str) -> list[str]:
    """`_marker.py` 源碼的公開函式名（`^def [a-z]`，`_` 開頭者自然被排除）。

    取源碼而非 `dir(module)`：鑑別力子測試要對**源碼字串**做突變（不改真檔），
    兩者必須走同一個抽取函式，否則突變證明不了斷言的鑑別力。
    """
    return re.findall(r"^def ([a-z][A-Za-z0-9_]*)\s*\(", src, re.M)


def _pair_gaps(names: list[str]) -> tuple[list[str], dict, list[str]]:
    """配對 `<verb>_topic ↔ <verb>_archived`、`topic_<noun> ↔ archived_<noun>`。

    回傳 (缺口 key 們, 配對表, 無法歸類的名稱們)。缺口 ＝ 某個 key 只有一側。
    `topic_<noun>` 一族的 key 加 `LINE:` 前綴，與 `<verb>_topic` 一族分開命名空間
    ——否則 `topic_line` 與假想的 `line_topic` 會撞在同一個 key 上。
    **只比名稱、不比簽章**（`#291` 定案 2：`archived` 側多一個 `file` 參數是
    `CH3` 要求的欄位，強求簽章同形會逼出 `file=None` 預設值，而那使「寫出沒有
    `file=` 欄的標記」變成可能，與 `A` 式的 grammar 直接衝突）。
    """
    table: dict[str, dict[str, str | None]] = {}
    other: list[str] = []
    for name in names:
        if name.endswith("_topic"):
            key, side = name[: -len("_topic")], "topic"
        elif name.endswith("_archived"):
            key, side = name[: -len("_archived")], "archived"
        elif name.startswith("topic_"):
            key, side = "LINE:" + name[len("topic_"):], "topic"
        elif name.startswith("archived_"):
            key, side = "LINE:" + name[len("archived_"):], "archived"
        else:
            other.append(name)
            continue
        table.setdefault(key, {"topic": None, "archived": None})[side] = name
    gaps = sorted(k for k, v in table.items() if not (v["topic"] and v["archived"]))
    return gaps, table, other


@case("#291 AC-3 _marker.py 公開 API 的 topic／archived 配對缺口集合須為空")
def _p291_ac3():
    names = _public_funcs(MARKER_SRC)
    gaps, table, other = _pair_gaps(names)
    detail = ("公開函式: " + repr(names) + "\n        配對: "
              + "; ".join(f"{k}=({v['topic']}|{v['archived']})"
                          for k, v in sorted(table.items()))
              + f"\n        缺口: {gaps!r} 無法歸類: {other!r}")
    check("#291 AC-3 配對缺口集合為空", gaps == [], detail)
    check("#291 AC-3 無法歸類的公開函式為空（每個都屬某一側）", other == [], detail)
    check("#291 AC-3 本單新增的兩個函式確實在公開清單內",
          {"archived_line", "upsert_archived"} <= set(names), repr(names))
    check("#291 AC-3 兩者皆為模組的可呼叫屬性（源碼與模組一致）",
          all(callable(getattr(marker, n, None))
              for n in ("archived_line", "upsert_archived")))
    check("#291 AC-3 五組配對齊備（find／has／read／upsert／LINE:line）",
          set(table) == {"find", "has", "read", "upsert", "LINE:line"},
          f"{sorted(table)!r}")


@case("#291 AC-3 鑑別力：兩個突變（對源碼字串操作、不改真檔）須使缺口非空")
def _p291_ac3_mutations():
    # 先造出「`#285` 當時的 _marker.py」——把本單新增的兩函式從源碼切掉。
    cut = MARKER_SRC.split("\ndef archived_line(")
    check("#291 AC-3 鑑別力：切點存在（archived_line 為源碼最後兩個函式之首）",
          len(cut) == 2, f"切出 {len(cut)} 段")
    if len(cut) != 2:
        return
    base_src = cut[0] + "\n"          # 等同 6b72933 的 _marker.py（寫側只有 topic）
    base_names = _public_funcs(base_src)
    base_gaps, _, _ = _pair_gaps(base_names)
    check("#291 AC-3 鑑別力：未達成候選（切掉兩函式）缺口 == ['LINE:line', 'upsert']",
          base_gaps == ["LINE:line", "upsert"],
          f"實得 {base_gaps!r}（T 的預跑值：['LINE:line', 'upsert']）")

    # 突變 A：只補 archived_line（移掉 upsert_archived）→ 缺口 1 ['upsert'] → FAIL
    mut_a = base_src + "\ndef archived_line(thread, file) -> str:\n    return ''\n"
    gaps_a, _, _ = _pair_gaps(_public_funcs(mut_a))
    check("#291 AC-3 鑑別力：突變 A（只補 archived_line）缺口 == ['upsert'] → 斷言 FAIL",
          gaps_a == ["upsert"], f"實得 {gaps_a!r}")

    # 突變 A'：兩側**個數相等**但仍有缺口 —— 證明「個數相等」不足以當判準。
    # base 是 topic 側 5（find／read／has／topic_line／upsert）、archived 側 3；
    # 補 archived_line ＋ 一個無配對的 archived_foo 後兩側皆 5，而缺口仍非空。
    mut_a2 = (base_src
              + "\ndef archived_line(thread, file) -> str:\n    return ''\n"
              + "\ndef archived_foo(x):\n    return x\n")
    names_a2 = _public_funcs(mut_a2)
    topic_side = [n for n in names_a2 if n.endswith("_topic") or n.startswith("topic_")]
    arch_side = [n for n in names_a2
                 if n.endswith("_archived") or n.startswith("archived_")]
    gaps_a2, _, _ = _pair_gaps(names_a2)
    check("#291 AC-3 鑑別力：突變 A' 兩側個數相等（5 vs 5）而缺口非空 "
          "→「個數相等」不足以當判準",
          len(topic_side) == len(arch_side) == 5 and gaps_a2 != [],
          f"topic 側 {topic_side!r}\n        archived 側 {arch_side!r}"
          f"\n        缺口 {gaps_a2!r}")
    check("#291 AC-3 鑑別力：突變 A' 的缺口 == ['LINE:foo', 'upsert']",
          gaps_a2 == ["LINE:foo", "upsert"], f"實得 {gaps_a2!r}")

    # 突變 B：多加一個無配對的 archived_foo → 缺口 3 → FAIL
    mut_b = base_src + "\ndef archived_foo(x):\n    return x\n"
    gaps_b, _, _ = _pair_gaps(_public_funcs(mut_b))
    check("#291 AC-3 鑑別力：突變 B（補無配對的 archived_foo）缺口 3 個 → 斷言 FAIL",
          gaps_b == ["LINE:foo", "LINE:line", "upsert"] and len(gaps_b) == 3,
          f"實得 {gaps_b!r}（T 的預跑值：缺口 3）")
    check("#291 AC-3 鑑別力：突變 B 證明「存在任一 archived_*」不足"
          "（無配對的新增反而增加缺口）",
          len(gaps_b) > len(base_gaps), f"base {base_gaps!r} → mutB {gaps_b!r}")

    # 突變 B'：在**達成**版上加 archived_foo → 缺口 1（達成版也擋得住無用新增）
    mut_b2 = MARKER_SRC + "\ndef archived_foo(x):\n    return x\n"
    gaps_b2, _, _ = _pair_gaps(_public_funcs(mut_b2))
    check("#291 AC-3 鑑別力：突變 B'（達成版 ＋ archived_foo）缺口 == ['LINE:foo']",
          gaps_b2 == ["LINE:foo"], f"實得 {gaps_b2!r}")


# ── #291 AC-4／AC-5／AC-6 cmd_archive 第四步 ────────────────────────────────
# `api()` 會打 api.telegram.org、`_token()` 讀 dfcoord/.env，故第四步的驗證**在
# 測試行程內**跑 `cmd_archive`，以 monkeypatch 置換 `api`／`CACHE`／`OUT`，
# forge 側走假 `gh`（PATH 前置，subprocess 繼承 os.environ）。零 Telegram API。

P291_E2E_BODY = """# K4c-4 端到端 fixture

| 形態 | 字面 |
|---|---|
| 表格列內 | `<!-- devflow:archived thread=999 file=/t/999.md -->` |

散文也提一次 <!-- devflow:archived thread=999 file=/t/999.md --> 如上。

<!-- devflow:topic thread=2620 -->
"""


def _p291_fake_gh(bin_: Path, td: Path, body: str, cache: Path, *,
                  edit_fail: bool = False) -> None:
    """假 gh。

    * `issue view` → 回 `body`。
    * `issue edit` → **在被呼叫的那一刻**把 `-F` 的檔與 `cache` 的內容各複製一份
      （`edited-body.md`／`cache-at-edit.json`），再寫 `edit-called` 哨兵。
      快照 cache 是 `AC-4` 第二個斷言的要件：寫標記與清 cache 的**相對次序**
      不能靠最終狀態判斷（兩種次序的最終狀態相同），只能在 edit 的時點觀測。
      `edit_fail=True` 時 exit 1（`AC-11` 的反例）——快照照留，供斷言 forge
      確實被叫到過。
    * `issue list` → 寫 `list-called` 哨兵並 exit 8（`AC-5`：不該走到這裡）。
    """
    fake = bin_ / "gh"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        "a = sys.argv[1:]\n"
        "if a[:2] == ['issue', 'view']:\n"
        f"    print(json.dumps({{'body': {body!r}}}))\n"
        "    sys.exit(0)\n"
        "if a[:2] == ['issue', 'edit']:\n"
        "    src = a[a.index('-F') + 1]\n"
        f"    pathlib.Path({str(td / 'edited-body.md')!r}).write_text("
        "pathlib.Path(src).read_text())\n"
        f"    cache = pathlib.Path({str(cache)!r})\n"
        f"    pathlib.Path({str(td / 'cache-at-edit.json')!r}).write_text("
        "cache.read_text() if cache.exists() else '<cache 檔不存在>')\n"
        f"    pathlib.Path({str(td / 'edit-called')!r}).write_text(' '.join(a))\n"
        f"    sys.exit({1 if edit_fail else 0})\n"
        "if a[:2] == ['issue', 'list']:\n"
        f"    pathlib.Path({str(td / 'list-called')!r}).write_text(' '.join(a))\n"
        "    print('issue list 不該被呼叫（cache 命中路徑）', file=sys.stderr)\n"
        "    sys.exit(8)\n"
        "print('unexpected gh call: ' + ' '.join(a), file=sys.stderr)\n"
        "sys.exit(8)\n")
    fake.chmod(0o755)


def _p291_run_cmd_archive(td: Path, mod, *, delete_ok: bool = True,
                          seed_md: bool = True, cache_entry: bool = True,
                          edit_fail: bool = False,
                          body: str = P291_E2E_BODY) -> dict:
    """在測試行程內跑 `mod.cmd_archive(... --yes --no-publish)`，回傳觀測結果。

    `mod` 可為受測模組或突變複本（鑑別力／未達成候選用）。
    """
    import contextlib
    import io

    bin_ = td / "bin"
    bin_.mkdir(exist_ok=True)
    out_dir = td / "archives" / "topics"
    out_dir.mkdir(parents=True, exist_ok=True)
    if seed_md:
        (out_dir / "291.md").write_text("# 匯出檔（測試用）\n")
    cache = td / "devflow-topics.json"
    cache.write_text(json.dumps(
        {"291": {"thread_id": "2620", "title": "K4c-4", "state": "OPEN"}}
        if cache_entry else {}, ensure_ascii=False, indent=2) + "\n")
    _p291_fake_gh(bin_, td, body, cache, edit_fail=edit_fail)

    calls: list[tuple[str, bool]] = []
    edited = td / "edited-body.md"

    def fake_api(method: str, **params) -> dict:
        # 順序證據：記下每次 API 呼叫時「edited-body.md 是否已存在」。
        # delete 當時必須還不存在 → 寫標記確實在 delete 之後。
        calls.append((method, edited.exists()))
        if method == "deleteForumTopic" and not delete_ok:
            return {"ok": False, "description": "boom"}
        return {"ok": True}

    snap = td / "cache-at-edit.json"
    orig = (mod.api, mod.CACHE, mod.OUT, os.environ.get("PATH", ""))
    mod.api, mod.CACHE, mod.OUT = fake_api, cache, out_dir
    os.environ["PATH"] = f"{bin_}:{orig[3]}"
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = mod.cmd_archive(argparse.Namespace(
                thread="2620", yes=True, no_publish=True, since=None, until=None))
    finally:
        mod.api, mod.CACHE, mod.OUT = orig[0], orig[1], orig[2]
        os.environ["PATH"] = orig[3]
    return {
        "rc": rc, "calls": calls, "stdout": buf.getvalue(),
        "edit_called": (td / "edit-called").exists(),
        "list_called": (td / "list-called").exists(),
        "edited_body": edited.read_text() if edited.exists() else None,
        "cache_at_edit": snap.read_text() if snap.exists() else None,
        "cache": json.loads(cache.read_text() or "{}"),
        "md_path": out_dir / "291.md",
        # `AC-11`：寫標記用的暫存檔路徑（受測程式用同一個 gettempdir，同行程）。
        "tmp_marker": Path(tempfile.gettempdir()) / "devflow-archived-291.md",
    }


def _p291_ch3(body: str) -> tuple[int, int, bool]:
    """對 body 套條文的判定式（`grep -cE`，不經模組）→ (T, A, NN 是否相同)。"""
    pats = _readme_patterns()
    assert len(pats) == 2, pats

    def count(pat: str) -> int:
        g = subprocess.run(["grep", "-cE", pat], input=body,
                           capture_output=True, text=True)
        return int((g.stdout or "0").strip() or 0)

    t, a = count(pats[0]), count(pats[1])
    tn = re.findall(r"^<!-- devflow:topic thread=([0-9]+) -->$", body, re.M)
    an = re.findall(r"^<!-- devflow:archived thread=([0-9]+) file=[^ >]+ -->$",
                    body, re.M)
    return t, a, bool(tn) and bool(an) and tn[0] == an[0]


@case("#291 AC-6 端到端：archive 2620 --yes --no-publish 後該 body 判為「已封存」")
def _p291_ac6():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        r = _p291_run_cmd_archive(td, archive)
        detail = f"rc={r['rc']} calls={r['calls']!r}\n--- 輸出 ---\n{r['stdout']}"
        check("#291 AC-6 rc == 0", r["rc"] == 0, detail)
        check("#291 AC-6 gh issue edit 被呼叫（第四步確實寫了 forge）",
              r["edit_called"], detail)
        if r["edited_body"] is None:
            check("#291 AC-6 取得寫入後的 body", False, detail)
            return
        t, a, same = _p291_ch3(r["edited_body"])
        check(f"#291 AC-6 CH3 判定式：T={t} A={a} NN 相同={same} → 已封存",
              (t, a, same) == (1, 1, True), detail + f"\n--- body ---\n{r['edited_body']}")
        check("#291 AC-6 錨定仍成立（表格列與散文的同形字串未被計入、未被改寫）",
              "| 表格列內 | `<!-- devflow:archived thread=999 file=/t/999.md -->` |"
              in r["edited_body"]
              and "散文也提一次 <!-- devflow:archived thread=999 file=/t/999.md --> 如上。"
              in r["edited_body"], r["edited_body"])
        check("#291 AC-6 cache 已清除該單（最終狀態；次序由 AC-4 的 edit 時點快照把守）",
              "291" not in r["cache"], json.dumps(r["cache"], ensure_ascii=False))
        # 順序：delete 當時 edited-body.md 還不存在 → 寫標記在 delete 之後
        deletes = [(i, seen) for i, (m, seen) in enumerate(r["calls"])
                   if m == "deleteForumTopic"]
        check("#291 AC-6 順序：deleteForumTopic 發生時標記尚未寫入",
              len(deletes) == 1 and deletes[0][1] is False, f"{r['calls']!r}")
        check("#291 AC-6 API 呼叫序恰為 close → delete",
              [m for m, _ in r["calls"]] == ["closeForumTopic", "deleteForumTopic"],
              f"{r['calls']!r}")


def _p291_no_step4_copy(td: Path) -> Path:
    """切掉第四步的 `devflow_archive.py` 複本（＝ `6b72933` 的三步 cmd_archive）。

    `AC-6` 的未達成候選：同一 fixture 下它得 `T=1 A=0`（判 active）。
    """
    src = ARCHIVE_SRC
    mutated = re.sub(
        r"    # ── 第四步：寫封存標記（CH3）──開始.*?\n"
        r"    # ── 第四步結束 ─+\n", "", src, flags=re.S)
    assert mutated != src, "突變未套用——第四步的區段標記已變，未達成候選失效"
    mutated = mutated.replace("    return marker_rc\n", "    return 0\n")
    assert "marker_rc" not in mutated, "突變殘留 marker_rc"
    out = td / "devflow_archive_nostep4.py"
    out.write_text(mutated)
    return out


# ── 突變複本的共用機制（`AC-4`／`AC-5`／`AC-11` 的未達成候選）───────────────
# 區段邊界的字面：清 cache 區塊與寫標記區段各自的起訖，突變靠它們切段。
P291_CACHE_HEAD = "    # 封存程序第 (4) 步：清 cache。"
P291_STEP4_HEAD = "    # ── 第四步：寫封存標記（CH3）──開始"
P291_STEP4_TAIL = "    # ── 第四步結束 ─"
P291_META_LINES = ("    issue_num, _title, _state = issue_meta(args.thread)\n"
                   "    md_path = OUT / f\"{stem_for(args.thread, issue_num)}.md\"\n")


def _p291_split_blocks(src: str) -> tuple[str, str, str, str]:
    """把 `cmd_archive` 的尾段切成 (前段, 清 cache 區塊, 寫標記區段, 後段)。"""
    i = src.index(P291_CACHE_HEAD)
    j = src.index(P291_STEP4_HEAD)
    k = src.index("\n", src.index(P291_STEP4_TAIL, j)) + 1
    return src[:i], src[i:j], src[j:k], src[k:]


def _p291_load_mutant(td: Path, name: str, src: str):
    """把突變後的源碼寫成複本並載入。`_marker` 已在 sys.modules，同層 import 解析得到。"""
    path = td / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _p291_v1_order_src() -> str:
    """T v1 的次序：寫標記在清 cache **之前**（＝ `2a6af87` 的實作）。

    `AC-4` 第二個斷言的未達成候選。該版本在 v1 的 AC 下全部通過，故是可重跑
    且具鑑別力的對照——它與本輪實作的差別**只有**這兩個區塊的先後。
    """
    head, cache_blk, step4_blk, tail = _p291_split_blocks(ARCHIVE_SRC)
    return head + step4_blk + cache_blk + tail


def _p291_meta_late_src() -> str:
    """`issue_meta`／`md_path` 的取值搬到清 cache **之後**（`AC-5` 的未達成候選）。

    清 cache 已把該單的條目刪掉，故 `issue_meta` 的 cache 查找落空、退回
    `gh issue list` 掃全 repo——正是 `AC-5` 要擋的事。
    """
    head, cache_blk, step4_blk, tail = _p291_split_blocks(ARCHIVE_SRC)
    assert P291_META_LINES in head, "取值兩行的字面已變，AC-5 的突變失效"
    head = head.replace(P291_META_LINES, "")
    return head + cache_blk + P291_META_LINES + step4_blk + tail


def _p291_no_finally_src() -> str:
    """把 `AC-11` 的 `try/finally` 還原成 `2a6af87`（unlink 在 check=True 之後）。"""
    old = """            try:
                subprocess.run(
                    ["gh", "issue", "edit", str(issue_num), "-R", "AugustusHsu/agent-devflow",
                     "-F", str(tmp)],
                    capture_output=True, stdin=subprocess.DEVNULL, timeout=60,
                    text=True, check=True)
            finally:
                tmp.unlink(missing_ok=True)
"""
    new = """            subprocess.run(
                ["gh", "issue", "edit", str(issue_num), "-R", "AugustusHsu/agent-devflow",
                 "-F", str(tmp)],
                capture_output=True, stdin=subprocess.DEVNULL, timeout=60,
                text=True, check=True)
            tmp.unlink(missing_ok=True)
"""
    assert old in ARCHIVE_SRC, "AC-11 的 try/finally 字面已變，突變失效"
    return ARCHIVE_SRC.replace(old, new)


@case("#291 AC-6 未達成候選：切掉第四步的複本同 fixture 得 T=1 A=0（判 active）")
def _p291_ac6_baseline():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        path = _p291_no_step4_copy(td)
        spec = importlib.util.spec_from_file_location("devflow_archive_nostep4", path)
        mut = importlib.util.module_from_spec(spec)
        sys.modules["devflow_archive_nostep4"] = mut
        spec.loader.exec_module(mut)
        r = _p291_run_cmd_archive(td, mut)
        detail = f"rc={r['rc']} calls={r['calls']!r}\n--- 輸出 ---\n{r['stdout']}"
        check("#291 AC-6 未達成候選：rc 為 0 但完全沒有呼叫 gh issue edit",
              r["rc"] == 0 and not r["edit_called"], detail)
        t, a, _ = _p291_ch3(P291_E2E_BODY)
        check(f"#291 AC-6 未達成候選：body 維持 T={t} A={a} → 判 active（＝本單在修的缺陷）",
              (t, a) == (1, 0), f"T={t} A={a}")
        check("#291 AC-6 未達成候選：cache 仍被清掉（故該單在通道側與快取皆為空）",
              "291" not in r["cache"], json.dumps(r["cache"], ensure_ascii=False))


@case("#291 AC-4 delete 失敗時：gh issue edit 未被呼叫、rc 非 0")
def _p291_ac4():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        r = _p291_run_cmd_archive(td, archive, delete_ok=False)
        detail = f"rc={r['rc']} calls={r['calls']!r}\n--- 輸出 ---\n{r['stdout']}"
        check("#291 AC-4 rc 非 0", r["rc"] != 0, detail)
        check("#291 AC-4 哨兵不存在：gh issue edit 未被呼叫"
              "（刪成功才算封存，telegram.md:14）",
              not r["edit_called"], detail)
        check("#291 AC-4 未產生寫入後的 body（forge 一字未動）",
              r["edited_body"] is None, detail)
        check("#291 AC-4 deleteForumTopic 確實被試過（否則本斷言沒有鑑別力）",
              "deleteForumTopic" in [m for m, _ in r["calls"]], f"{r['calls']!r}")
    # 鑑別力：delete 成功的同一組 fixture 下哨兵必須存在
    with tempfile.TemporaryDirectory() as td2:
        td2 = Path(td2)
        ok = _p291_run_cmd_archive(td2, archive, delete_ok=True)
        check("#291 AC-4 鑑別力：delete 成功時哨兵存在（故上面的『不存在』是條件性的）",
              ok["edit_called"], f"rc={ok['rc']}\n{ok['stdout']}")


@case("#291 AC-4(v2) 寫標記在清 cache 之後：edit 被呼叫的時點 cache 已移除該單")
def _p291_ac4_order():
    # 契約（`telegram.md:13`／`:25`）：封存程序四步的第 (4) 步是清 cache，
    # 寫標記是「四步之後」的獨立動作。相對次序只能在 edit 的時點觀測——
    # 兩種次序的**最終狀態相同**（cache 清掉、標記寫入），讀最終狀態沒有鑑別力。
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        r = _p291_run_cmd_archive(td, archive)
        detail = (f"rc={r['rc']}\n--- 輸出 ---\n{r['stdout']}"
                  f"--- edit 時點的 cache ---\n{r['cache_at_edit']}")
        check("#291 AC-4(v2) rc == 0 且 gh issue edit 被呼叫", r["rc"] == 0
              and r["edit_called"], detail)
        check("#291 AC-4(v2) 取得 edit 時點的 cache 快照",
              r["cache_at_edit"] is not None, detail)
        if r["cache_at_edit"] is not None:
            snap = json.loads(r["cache_at_edit"])
            check("#291 AC-4(v2) edit 被呼叫時 cache 內該單條目**已移除**"
                  "（清 cache 先於寫標記）",
                  "291" not in snap, f"快照 {r['cache_at_edit']!r}")
        check("#291 AC-4(v2) 最終狀態亦為已清除（兩步都做了）",
              "291" not in r["cache"], json.dumps(r["cache"], ensure_ascii=False))

    # 未達成候選：T v1 的次序（寫標記在清 cache 之前，＝ 2a6af87 的實作）。
    # 同一 fixture 下 edit 時點的 cache **仍含該單** → 上面的斷言 FAIL。
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        mut = _p291_load_mutant(td, "devflow_archive_v1order", _p291_v1_order_src())
        m = _p291_run_cmd_archive(td, mut)
        mdetail = (f"rc={m['rc']}\n--- 輸出 ---\n{m['stdout']}"
                   f"--- edit 時點的 cache ---\n{m['cache_at_edit']}")
        check("#291 AC-4(v2) 未達成候選：v1 次序複本仍寫成標記（rc 0、edit 被呼叫）",
              m["rc"] == 0 and m["edit_called"], mdetail)
        check("#291 AC-4(v2) 未達成候選：v1 次序下 edit 時點的 cache **仍含該單**"
              " → 上面的斷言 FAIL ✓",
              m["cache_at_edit"] is not None
              and "291" in json.loads(m["cache_at_edit"]),
              f"快照 {m['cache_at_edit']!r}")
        mv = _p291_ch3(m["edited_body"] or "")
        rv = _p291_ch3(r["edited_body"] or "")
        check("#291 AC-4(v2) 未達成候選：v1 次序的最終狀態與本實作無從區分"
              "（cache 皆清空、body 皆判已封存 → 讀最終狀態沒有鑑別力）",
              "291" not in m["cache"] and mv[:2] == rv[:2] == (1, 1),
              f"最終 cache {m['cache']!r} v1 判定 {mv!r} 本實作判定 {rv!r}")


@case("#291 AC-5 --no-publish：issue list 未被呼叫、file= 為存在的絕對路徑")
def _p291_ac5():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        r = _p291_run_cmd_archive(td, archive)
        detail = f"rc={r['rc']}\n--- 輸出 ---\n{r['stdout']}"
        check("#291 AC-5 issue list 未被呼叫（issue_meta 走 cache 命中路徑）",
              not r["list_called"], detail)
        check("#291 AC-5 file= 欄為絕對路徑",
              r["edited_body"] is not None
              and f"file={r['md_path']} -->" in r["edited_body"],
              f"{r['edited_body']!r}")
        if r["edited_body"]:
            got = re.findall(
                r"^<!-- devflow:archived thread=[0-9]+ file=([^ >]+) -->$",
                r["edited_body"], re.M)
            check("#291 AC-5 標記恰一個且 file= 值可解析", len(got) == 1, f"{got!r}")
            if got:
                p = Path(got[0])
                check("#291 AC-5 file= 是絕對路徑", p.is_absolute(), str(p))
                check("#291 AC-5 Path(file).is_file()（寫入時該路徑存在）",
                      p.is_file(), str(p))
                check("#291 AC-5 形狀為 <OUT>/<issue 號>.md",
                      p.name == "291.md" and p.parent.name == "topics", str(p))

    # 未達成候選：把 issue_meta／md_path 的取值搬到清 cache **之後**。
    # 清 cache 已刪掉該單條目 → cache 查找落空 → 退回 gh issue list 掃全 repo。
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        mut = _p291_load_mutant(td, "devflow_archive_metalate", _p291_meta_late_src())
        m = _p291_run_cmd_archive(td, mut)
        mdetail = f"rc={m['rc']}\n--- 輸出 ---\n{m['stdout']}"
        check("#291 AC-5 未達成候選：取值搬到清 cache 之後 → issue list **被呼叫**"
              " → 上面的斷言 FAIL ✓",
              m["list_called"], mdetail)
        check("#291 AC-5 未達成候選：退回掃全 repo 後連 issue 號都查不到，標記寫不出來",
              m["rc"] != 0 and not m["edit_called"], mdetail)


@case("#291 AC-10 三個失敗分支：rc 非 0、cache 已清、gh issue edit 未呼叫")
def _p291_ac10():
    # T v2 `AC-10` 的正式規格（第 1 輪為實作者的射程外判斷，裁決位 2026-10-05
    # 核對後採納為規格）：delete 已成功 ⇒ 分區已不存在 ⇒ cache 一律照清，
    # 而整體 rc 非 0（標記是 `CH3` 的必需步驟，寫入失敗卻回 0 會誤報整體成功）。
    # rc 與 cache 不矛盾——rc 反映「程序是否完整完成」，cache 反映「是否還有殘影」。
    branches = [
        ("分支二 匯出檔不存在", {"seed_md": False}),
        ("分支一 issue_meta 回不出 issue 號", {"cache_entry": False}),
        ("分支三 upsert 遇 A>1（InvalidMarker）", {"body": P291_F_A2}),
    ]
    for label, kwargs in branches:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            r = _p291_run_cmd_archive(td, archive, **kwargs)
            detail = f"rc={r['rc']}\n--- 輸出 ---\n{r['stdout']}"
            check(f"#291 AC-10 {label}：rc 非 0", r["rc"] != 0, detail)
            check(f"#291 AC-10 {label}：cache 已清（分區已刪，殘影就是錯的）",
                  "291" not in r["cache"], json.dumps(r["cache"], ensure_ascii=False))
            check(f"#291 AC-10 {label}：gh issue edit 未被呼叫（不動 forge）",
                  not r["edit_called"] and r["edited_body"] is None, detail)
            check(f"#291 AC-10 {label}：stdout 印 ❌（人看得到哪一步沒做成）",
                  "❌" in r["stdout"], detail)
    # 分支三另驗 `CH3` 的要求：印全部命中行到 stderr
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        r = _p291_run_cmd_archive(td, archive, body=P291_F_A2)
        check("#291 AC-10 分支三：輸出含 INVALID 與全部命中行的字面（CH3）",
              "INVALID" in r["stdout"]
              and all(ln in r["stdout"] for ln in P291_A2_LINES),
              r["stdout"])


@case("#291 AC-11 暫存檔不洩漏：gh issue edit 失敗後該檔不存在")
def _p291_ac11():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        r = _p291_run_cmd_archive(td, archive, edit_fail=True)
        detail = (f"rc={r['rc']} 暫存檔={r['tmp_marker']}\n"
                  f"--- 輸出 ---\n{r['stdout']}")
        check("#291 AC-11 gh issue edit 確實被呼叫過（否則本反例沒有鑑別力）",
              r["edit_called"], detail)
        check("#291 AC-11 rc 非 0（寫標記失敗不得誤報整體成功）", r["rc"] != 0, detail)
        check("#291 AC-11 cmd_archive 返回後暫存檔**不存在**（finally 清掉了）",
              not r["tmp_marker"].exists(), detail)
        check("#291 AC-11 cache 已清（同 AC-10：delete 已成功）",
              "291" not in r["cache"], json.dumps(r["cache"], ensure_ascii=False))
    # 成功路徑也不得留下暫存檔
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        ok = _p291_run_cmd_archive(td, archive)
        check("#291 AC-11 成功路徑亦不留暫存檔",
              ok["rc"] == 0 and not ok["tmp_marker"].exists(),
              f"rc={ok['rc']} 暫存檔={ok['tmp_marker']}")

    # 未達成候選：`2a6af87` 的實作（unlink 在 check=True 之後）。
    # CalledProcessError 直接拋出 → unlink 不執行 → 檔案留在暫存根。
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        mut = _p291_load_mutant(td, "devflow_archive_nofinally",
                                _p291_no_finally_src())
        leaked = Path(tempfile.gettempdir()) / "devflow-archived-291.md"
        leaked.unlink(missing_ok=True)          # 先確保乾淨，否則殘留不可歸因
        try:
            m = _p291_run_cmd_archive(td, mut, edit_fail=True)
            check("#291 AC-11 未達成候選：2a6af87 的實作在 edit 失敗後**留下**暫存檔"
                  " → 上面的斷言 FAIL ✓",
                  leaked.exists(),
                  f"rc={m['rc']} 期望殘留於 {leaked}\n--- 輸出 ---\n{m['stdout']}")
            check("#291 AC-11 未達成候選：殘留的內容就是要寫進 forge 的 body"
                  "（故洩漏的是完整的 issue body，不是空檔）",
                  leaked.exists()
                  and "<!-- devflow:archived thread=2620 " in leaked.read_text(),
                  leaked.read_text()[:200] if leaked.exists() else "（檔案不存在）")
        finally:
            leaked.unlink(missing_ok=True)      # 突變複本的洩漏由測試自己收拾


# ── #291 AC-7 archive.py 本單只改 cmd_archive（AST）────────────────────────
@case("#291 AC-7 devflow_archive.py 除 cmd_archive 外的既有函式 AST 逐一不變")
def _p291_ac7():
    import ast
    old = subprocess.run(
        ["git", "show", "6b72933:devflow/channels/scripts/telegram/devflow_archive.py"],
        capture_output=True, text=True, cwd=REPO).stdout
    check("#291 AC-7 取得 6b72933 的原檔", bool(old.strip()), "git show 無輸出")
    if not old.strip():
        return

    def funcs(src: str) -> dict:
        return {n.name: ast.dump(n) for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef)}

    o, n = funcs(old), funcs(ARCHIVE_SRC)
    changed = sorted(k for k in o.keys() & n.keys() if o[k] != n[k])
    # `#293` 起 `cmd_publish`／`send_document` 亦改（caption 轉 HTML parse mode
    # ＋ `esc_html` 轉義）。本子測試守的是「`#291` 的 `cmd_archive` 改動仍在、
    # 且沒有別的函式被順手改」，故期望集合隨已合併的後續單增長，不是放寬。
    check("#291 AC-7 改變的函式只有 cmd_archive（＋#293 的 cmd_publish／send_document）",
          changed == ["cmd_archive", "cmd_publish", "send_document"],
          f"改變的函式: {changed!r} | 新增: {sorted(n.keys() - o.keys())!r} "
          f"| 移除: {sorted(o.keys() - n.keys())!r}")
    check("#291 AC-7 既有函式一個都沒被移除", not (o.keys() - n.keys()),
          f"{sorted(o.keys() - n.keys())!r}")
    for name in ("cmd_scan", "cmd_export", "collect", "issue_meta",
                 "api", "stem_for", "_export"):
        check(f"#291 AC-7 {name} 的 AST 與 6b72933 相同",
              name in o and name in n and o[name] == n[name])
    check("#291 AC-7 cmd_publish 自 #293 起改動（本單之後的事實，見 #293 AC-7）",
          "cmd_publish" in o and "cmd_publish" in n
          and o["cmd_publish"] != n["cmd_publish"])


# ── #291 AC-8／AC-9 版本與 import-path 不回歸 ───────────────────────────────
@case("#291 AC-8 devflow/VERSION 恰 0.15.3.0（#293 進位後）")
def _p291_ac8():
    raw = (REPO / "devflow" / "VERSION").read_text()
    check("#291 AC-8 內容（strip 後）恰 0.15.3.0", raw.strip() == "0.15.3.0", repr(raw))


@case("#291 AC-9 telegram/*.py 與本測試檔零 import-path 操作")
def _p291_ac9():
    # 本檔連字面都不出現（同上方模組 docstring 的理由）：grep 的 pattern 以
    # 正則寫成 r"sys\.path"，檔內字面是 `sys\.path`，故 grep -nE 'sys\.path'
    # 不會命中本檔自己。
    targets = sorted(SCRIPTS.glob("*.py")) + [Path(__file__).resolve()]
    r = subprocess.run(["grep", "-nE", r"sys\.path", *[str(p) for p in targets]],
                       capture_output=True, text=True)
    check("#291 AC-9 grep -nE 'sys\\.path' 無命中（exit 1）",
          r.returncode == 1 and not r.stdout.strip(),
          f"exit={r.returncode}\n{r.stdout}")
    check("#291 AC-9 受檢集合是 glob 且含本單改動的兩支腳本",
          {"_marker.py", "devflow_archive.py"} <= {p.name for p in targets},
          f"{[p.name for p in targets]!r}")


# ════════════════════════════════════════════════════════════════════════════
# `#293`／K4c-5：`cmd_publish` 的 caption 改 HTML parse mode ＋ 轉義
# ════════════════════════════════════════════════════════════════════════════
# 本單的 AC 編號獨立於上方 `#285`／`#291`，標籤一律帶 `#293` 前綴。
# `AC-5`（真 API 對照）**不在本檔**：本檔零 Telegram API（見模組 docstring），
# 該 AC 由實作者實跑並把輸出記進 issue 留言。

# `#291` 的 issue 標題（`gh issue view 291 --json title` 實查，2026-10-06）。
# 含 `_marker.py` 的裸底線 —— 就是 `#291` 封存時讓 `sendDocument` 回
# `can't parse entities … byte offset 26` 的那一個字元。
P293_TITLE_291 = ("🐛 K4c-4: _marker.py 公開 API 不對稱——封存標記無寫側實作"
                  "（CH3 生效起每次封存產出不合規 body）")
P293_TITLE_HTML = "fix: <script> & a > b 的處理"


def _p293_caption(title: str, *, num: str = "291", thread: str = "3363",
                  n: int = 9, state: str | None = None) -> str:
    """以假的 `_export`／`issue_meta`／`send_document` 實跑 `cmd_publish`，
    取回它**實際組出**的 caption（不在測試裡重寫一份格式，否則測不到實作）。"""
    captured: list[str] = []
    orig = (archive._export, archive.issue_meta, archive.send_document)
    with tempfile.TemporaryDirectory() as td:
        md = Path(td) / f"{num}.md"
        js = Path(td) / f"{num}.json"
        md.write_text("md")
        js.write_text("{}")
        try:
            archive._export = lambda *a, **k: (md, js, n)
            archive.issue_meta = lambda *a, **k: (num, title, state)
            archive.send_document = lambda _t, _p, cap="": (captured.append(cap)
                                                            or {"ok": True})
            rc = archive.cmd_publish(argparse.Namespace(thread=thread))
        finally:
            archive._export, archive.issue_meta, archive.send_document = orig
    assert rc == 0, f"cmd_publish rc={rc}"
    return captured[0]


def _p293_old_caption(title: str, *, num: str = "291", thread: str = "3363",
                      n: int = 9, state: str | None = None) -> str:
    """`21f1258` 的舊構造，逐字自該 commit 的 `cmd_publish:536` 抄來
    （`**…**` ＋ 原樣插入）。`AC-3` 的未達成候選要的就是這一份輸出。"""
    return (f"📦 **{'#' + num if num else 'thread ' + thread}** {title}\n"
            f"{n} 則訊息 · thread {thread}"
            + (f" · {state}" if state else ""))


# ── #293 AC-1 轉義函式：恰三個字元，`&` 先行 ────────────────────────────────
@case("#293 AC-1 esc 只處理 & < >，且 & 最先（否則二次轉義）")
def _p293_ac1():
    esc = archive.esc_html
    check("#293 AC-1 esc('a&b<c>d') == 'a&amp;b&lt;c&gt;d'",
          esc("a&b<c>d") == "a&amp;b&lt;c&gt;d", repr(esc("a&b<c>d")))
    check("#293 AC-1 esc('&lt;') == '&amp;lt;'（& 先行，不二次轉義）",
          esc("&lt;") == "&amp;lt;", repr(esc("&lt;")))
    check("#293 AC-1 esc('_marker.py') == '_marker.py'（底線不是 HTML 實體起點）",
          esc("_marker.py") == "_marker.py", repr(esc("_marker.py")))
    for ch in ("_", "*", "`", "[", "]"):
        check(f"#293 AC-1 Markdown 字元 {ch!r} 一字不動", esc(ch) == ch, repr(esc(ch)))

    # 鑑別力：把 `&` 的處理移到最後 → 第一式壞（`&` 被二次轉義）。
    #
    # ⚠ T 的 `AC-1` 把鑑別力記在**第二式**（「把 `&` 的處理移到最後，第二式變成
    # `&lt;`（錯）」）。實測不是這樣：第二式的輸入 `&lt;` **不含**字面 `<`，
    # 兩種順序都只有 `&` 規則命中，皆得 `&amp;lt;` —— 該式對順序零鑑別力。
    # 真正抓到順序錯的是**第一式**（輸入含字面 `<`）：
    #     & 先行  'a&b<c>d' → 'a&amp;b&lt;c&gt;d'   （對）
    #     & 最後  'a&b<c>d' → 'a&amp;b&amp;lt;c&amp;gt;d'（錯，`&lt;` 的 `&` 被二次轉義）
    # T 的三條等式本身全部成立（上方已逐條斷言），只是「哪一式有鑑別力」記錯了；
    # 本處斷言實測事實，並一併釘住第二式的順序不敏感性，免得後人再誤記。
    def esc_amp_last(text: str) -> str:
        return text.replace("<", "&lt;").replace(">", "&gt;").replace("&", "&amp;")

    check("#293 AC-1 鑑別力：& 移到最後時第一式變 'a&amp;b&amp;lt;c&amp;gt;d' → FAIL ✓",
          esc_amp_last("a&b<c>d") == "a&amp;b&amp;lt;c&amp;gt;d"
          and esc_amp_last("a&b<c>d") != esc("a&b<c>d"),
          repr(esc_amp_last("a&b<c>d")))
    check("#293 AC-1 鑑別力：單一字面 '<' 亦抓到（& 最後 → '&amp;lt;'）",
          esc_amp_last("<") == "&amp;lt;" and esc("<") == "&lt;",
          f"amp_last={esc_amp_last('<')!r} 正確={esc('<')!r}")
    check("#293 AC-1 T 的第二式對順序零鑑別力（輸入無字面 <，兩序同得 &amp;lt;）",
          esc_amp_last("&lt;") == esc("&lt;") == "&amp;lt;",
          f"amp_last={esc_amp_last('&lt;')!r} 正確={esc('&lt;')!r}")


# ── #293 AC-2 caption 改用 HTML parse mode ─────────────────────────────────
@case("#293 AC-2 parse_mode 恰 HTML 一處；caption 用 <b>…</b> ＋ 標題經轉義")
def _p293_ac2():
    hits = re.findall(r'field\("parse_mode", "([^"]+)"\)', ARCHIVE_SRC)
    check("#293 AC-2 parse_mode 呼叫點恰 1 處且值為 HTML（射程未變）",
          hits == ["HTML"], f"{hits!r}")
    check("#293 AC-2 全檔不再出現 parse_mode 的 Markdown 值",
          'field("parse_mode", "Markdown")' not in ARCHIVE_SRC)

    cap = _p293_caption(P293_TITLE_291)
    check("#293 AC-2 caption 含 <b>#291</b>", "<b>#291</b>" in cap, repr(cap))
    check("#293 AC-2 _marker.py 的底線原樣保留",
          "_marker.py" in cap and "\\_" not in cap, repr(cap))
    check("#293 AC-2 caption 無 **（Markdown 粗體已換掉）", "**" not in cap, repr(cap))
    check("#293 AC-2 標題其餘內容完整（未被轉義吃掉）",
          "封存標記無寫側實作" in cap and "（CH3 生效起每次封存產出不合規 body）" in cap,
          repr(cap))
    check("#293 AC-2 無 issue 號時退回 thread N（分支亦走 <b>…</b>）",
          "<b>thread 3363</b>" in _p293_caption("某標題", num=""),
          repr(_p293_caption("某標題", num="")))
    check("#293 AC-2 state 欄亦經轉義（外部值無漏網）",
          " · a &amp; b" in _p293_caption("t", state="a & b"),
          repr(_p293_caption("t", state="a & b")))


# ── #293 AC-3 未達成候選：舊構造對同一標題產出不合法 caption ─────────────────
@case("#293 AC-3 未達成候選：21f1258 的舊構造在 byte 26 有奇數個裸底線")
def _p293_ac3():
    old = _p293_old_caption(P293_TITLE_291)
    b = old.encode()
    # T 的切片寫 `[26:28]`，實測該兩 byte 解為 "_m"（底線 ＋ 'm'）；Telegram 報的
    # offset 26 指的是**那一個**底線，故這裡取 `[26:27]`。兩者指同一個字元。
    check("#293 AC-3 舊 caption 的 byte 26 是裸底線（T 的 [26:28] ＝ '_m'）",
          b[26:27].decode() == "_",
          f"[26:27]={b[26:27].decode()!r} [26:28]={b[26:28].decode()!r} "
          f"[26:48]={b[26:48].decode()!r}")
    check("#293 AC-3 舊 caption 的底線個數為奇數 ⇒ 必無配對",
          old.count("_") % 2 == 1, f"count={old.count('_')}")
    check("#293 AC-3 舊構造確實是 Markdown 粗體（** 在、無 <b>）",
          "**" in old and "<b>" not in old, repr(old))

    # 對照 `AC-2`：修正後的輸出在同一位置不再是裸底線起點，且無 **。
    new = _p293_caption(P293_TITLE_291)
    check("#293 AC-3 修正後輸出確實不同於舊構造（證明改動生效）", new != old)
    check("#293 AC-3 修正後無 ** 且底線仍為奇數（底線不是 HTML 實體起點，無妨）",
          "**" not in new and new.count("_") % 2 == 1,
          f"count={new.count('_')} {new!r}")


# ── #293 AC-4 HTML 特殊字元的標題也正確 ────────────────────────────────────
@case("#293 AC-4 標題含 <script> & > 時轉義正確、不含裸標籤")
def _p293_ac4():
    esc = archive.esc_html
    got = esc(P293_TITLE_HTML)
    check("#293 AC-4 轉義結果逐字相符",
          got == "fix: &lt;script&gt; &amp; a &gt; b 的處理", repr(got))
    check("#293 AC-4 不含裸 <script>", "<script>" not in got, repr(got))
    cap = _p293_caption(P293_TITLE_HTML)
    check("#293 AC-4 caption 亦不含裸 <script>，且含轉義後字面",
          "<script>" not in cap and "&lt;script&gt;" in cap, repr(cap))
    check("#293 AC-4 caption 的 <b> 標籤自己沒被轉義（只轉外部值）",
          "<b>#291</b>" in cap, repr(cap))
    # 未達成候選：未轉義時含裸 <script>
    check("#293 AC-4 未達成候選：未轉義時含裸 <script> → 上面的斷言 FAIL ✓",
          "<script>" in P293_TITLE_HTML, repr(P293_TITLE_HTML))


# ── #293 AC-6 build_md 的 MD 內文一字不動（區段 digest）─────────────────────
def _p293_md_header() -> str:
    """`sed -n '/lines = \\[f"# /,/匯出時間/p'` 的 Python 等價：自含
    `lines = [f"# ` 的那一行起，至其後第一個含「匯出時間」的行止（含兩端）。"""
    lines = ARCHIVE_SRC.splitlines()
    start = next(i for i, ln in enumerate(lines) if 'lines = [f"# ' in ln)
    end = next(i for i, ln in enumerate(lines) if i >= start and "匯出時間" in ln)
    return "\n".join(lines[start:end + 1]) + "\n"


@case("#293 AC-6 build_md 表頭的區段 digest 與 T 所載相同（** 與反引號不動）")
def _p293_ac6():
    import hashlib
    sec = _p293_md_header()
    with_nl = hashlib.sha256(sec.encode()).hexdigest()
    without_nl = hashlib.sha256(sec.rstrip("\n").encode()).hexdigest()
    check("#293 AC-6 區段恰 20 行", len(sec.rstrip("\n").splitlines()) == 20,
          f"{len(sec.rstrip(chr(10)).splitlines())} 行")
    # T 所載 6f454f… 是 `printf '%s' "$(sed …)"`（去結尾換行）的值；
    # `sed … | sha256sum`（含結尾換行）得 606217cf…。兩者指同一段內容。
    check("#293 AC-6 digest（去結尾換行）== T 所載 6f454f47950a371d…",
          without_nl == "6f454f47950a371d59b0dac1739b7cccf345ea435d9dde287f4d9cbe23173bee",
          f"去換行={without_nl}\n        含換行={with_nl}")
    check("#293 AC-6 digest（含結尾換行，即 sed | sha256sum）== 606217cf6b13cd47…",
          with_nl == "606217cf6b13cd478260e677725188845812ca02a11065bde89581ea4e030372",
          f"含換行={with_nl}")
    # 界線：寫進 .md 檔的內文**不經** Telegram 解析，故粗體與反引號維持 Markdown。
    check("#293 AC-6 該段仍用 ** 粗體（未被換成 <b>）", "**" in sec)
    check("#293 AC-6 該段仍用反引號 inline code（未被換成 <code>）", "`" in sec)
    check("#293 AC-6 該段不出現 HTML 標籤",
          "<b>" not in sec and "<code>" not in sec, repr(sec[:120]))
    check("#293 AC-6 該段不呼叫轉義函式（不對 MD 內文的外部值轉義）",
          "esc_html" not in sec)

    # 鑑別力：T 預跑的三種突變，digest 皆須不同於候選值。
    muts = {
        "突變 A：** 換成 <b>": sec.replace("**", "<b>"),
        "突變 B：反引號換成 <code>": sec.replace("`", "<code>"),
        "突變 C：對該段的 title 做 escape":
            sec.replace("{title}", "{esc_html(title)}"),
    }
    for label, mut in muts.items():
        d = hashlib.sha256(mut.rstrip("\n").encode()).hexdigest()
        check(f"#293 AC-6 鑑別力：{label} → digest 不同 → 斷言 FAIL ✓",
              d != without_nl and mut != sec, f"突變 digest={d[:16]}")
    check("#293 AC-6 鑑別力：三種突變確實改到了內容（非空操作）",
          len({*muts.values(), sec}) == 4,
          f"{len({*muts.values(), sec})} 種相異內容（期望 4）")


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
    # __pycache__ 不得殘留在受測目錄（sys.dont_write_bytecode）
    leftovers = [str(p) for p in (SCRIPTS, HERE) if (p / "__pycache__").exists()]
    if leftovers:
        print(f"⚠ __pycache__ 殘留：{leftovers}")
    print("─" * 72)
    raise SystemExit(1 if failed or leftovers else 0)