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
from collections import Counter
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


def _issue_meta_with(rows, *, scan_topic=None):
    """在假 gh 輸出與（可選）替換過的 `scan_topic` 下跑 issue_meta，回傳值或擲出的例外。

    `scan_topic` 參數供鑑別力子測試注入「跳過 INVALID 續掃的舊版」——證明本測試
    真的在檢驗停下的行為，而不是任何實作都會過。

    `#287` 起 `issue_meta` 的掃描走 `_marker.scan_topic`（共用函式），注入點隨之
    從 `has_topic` 移到這裡；受檢驗的行為一字未變（遇 `T>1` 必須 raise、不得續掃
    後回傳別人的單）。
    """
    def fake_run(cmd, *a, **kw):
        assert cmd[:2] == ["gh", "issue"], cmd
        return subprocess.CompletedProcess(cmd, 0, json.dumps(rows), "")

    with tempfile.TemporaryDirectory() as td:
        orig_cache, orig_run = archive.CACHE, subprocess.run
        orig_scan = marker.scan_topic
        archive.CACHE = Path(td) / "nonexistent.json"
        subprocess.run = fake_run
        if scan_topic is not None:
            marker.scan_topic = scan_topic     # issue_meta 經 `_marker.scan_topic` 取用
        try:
            return ("return", archive.issue_meta("2620"))
        except marker.InvalidMarker as e:
            return ("raise", e)
        finally:
            archive.CACHE, subprocess.run = orig_cache, orig_run
            marker.scan_topic = orig_scan


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

    # 鑑別力：換成「跳過 INVALID 續掃」的舊行為，本子測試必須 FAIL。
    # 這就是 `#285` 第 1 輪被 BLOCK-1 擋下的那個行為，`#287` 之後它的等價寫法是
    # 「給 scan_topic 一個靜默吞掉 InvalidMarker 的 on_invalid」——同樣是跳過該單
    # 續掃，於是在下一張合法的 #286 命中並回傳它。
    def scan_topic_skipping_invalid(items, *, on_invalid=None):
        return marker._scan_markers(items, kinds=("topic",),
                                    on_invalid=lambda _exc, _issue: None)

    kind2, val2 = _issue_meta_with(BLOCK1_ROWS, scan_topic=scan_topic_skipping_invalid)
    check("AC-5／BLOCK-1 鑑別力：換回『跳過 INVALID 續掃』版後 issue_meta 不再 raise",
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

    `#287` 起 `issue_meta` 的掃描走 `_marker.scan_topic`，故突變的切點改為那個
    list comprehension；突變後的行為與第 2 輪逐字等價——**在第一個命中就 return**，
    排在它後面的 `T>1` 單根本不會被解析。
    """
    src = (SCRIPTS / "devflow_archive.py").read_text()
    mutated = src.replace(
        """        hits = [by_num[num] for num, tid, kind
                in _marker.scan_topic((str(it["number"]), it.get("body") or "")
                                      for it in items)
                if kind == "topic" and str(tid) == str(thread)]""",
        """        for item in items:
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
    check("#291 AC-3 五組配對齊備（find／has／read／upsert／LINE:line）"
          "＋ `#287` 新增的 scan 一組",
          set(table) == {"find", "has", "read", "upsert", "LINE:line", "scan"},
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
    # base 是 topic 側 6（find／read／scan／has／topic_line／upsert）、archived 側 4
    # （`#287` 起兩側各多一個 scan_*）；補 archived_line ＋ 一個無配對的 archived_foo
    # 後兩側皆 6，而缺口仍非空。
    mut_a2 = (base_src
              + "\ndef archived_line(thread, file) -> str:\n    return ''\n"
              + "\ndef archived_foo(x):\n    return x\n")
    names_a2 = _public_funcs(mut_a2)
    topic_side = [n for n in names_a2 if n.endswith("_topic") or n.startswith("topic_")]
    arch_side = [n for n in names_a2
                 if n.endswith("_archived") or n.startswith("archived_")]
    gaps_a2, _, _ = _pair_gaps(names_a2)
    check("#291 AC-3 鑑別力：突變 A' 兩側個數相等（6 vs 6）而缺口非空 "
          "→「個數相等」不足以當判準",
          len(topic_side) == len(arch_side) == 6 and gaps_a2 != [],
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
    # ＋ `esc_html` 轉義）；`#287` 起再加 `_ts`／`cmd_scan`／`issue_meta`／`main`
    # （三缺陷 ＋ 共用掃描函式；`main` 僅 `--since`／`--until` 的 metavar 與 help，
    # 由審查位以 git diff 逐行核）。本子測試守的是「`#291` 的 `cmd_archive` 改動仍在、
    # 且沒有別的函式被順手改」，故期望集合隨已合併的後續單增長，不是放寬。
    # `#287` 新增的頂層 helper（`scan_upper_bound`／`_forge_scan_items`）不在
    # `changed` 內——它們是新增，不在 `o.keys() & n.keys()`，由下面的「一個都沒被
    # 移除」與 detail 的「新增」欄位把守。
    check("#291 AC-7 改變的函式只有 cmd_archive"
          "（＋#293 的 cmd_publish／send_document、#287 的 _ts／cmd_scan／issue_meta／main）",
          changed == ["_ts", "cmd_archive", "cmd_publish", "cmd_scan", "issue_meta",
                      "main", "send_document"],
          f"改變的函式: {changed!r} | 新增: {sorted(n.keys() - o.keys())!r} "
          f"| 移除: {sorted(o.keys() - n.keys())!r}")
    check("#291 AC-7 既有函式一個都沒被移除", not (o.keys() - n.keys()),
          f"{sorted(o.keys() - n.keys())!r}")
    # `#287` 起 `cmd_scan`／`issue_meta` 移出本清單（它們是本單修的缺陷所在）。
    for name in ("cmd_export", "collect", "api", "stem_for", "_export"):
        check(f"#291 AC-7 {name} 的 AST 與 6b72933 相同",
              name in o and name in n and o[name] == n[name])
    check("#291 AC-7 cmd_publish 自 #293 起改動（本單之後的事實，見 #293 AC-7）",
          "cmd_publish" in o and "cmd_publish" in n
          and o["cmd_publish"] != n["cmd_publish"])


# ── #291 AC-8／AC-9 版本與 import-path 不回歸 ───────────────────────────────
# `#287` `AC-8` 治本：原斷言寫死 `== "0.15.4.0"`（`#286` 的治標），每次 `V7` 進位
# 就假 FAIL 一次 —— 與本單在修的那一族同形（程式持有的假設在狀態變動後失效）。
# 改為「合 `V1` 四碼形狀 **且嚴格大於下界**」。
#
# 下界寫死 `0.15.4.0` 這個字面（協調位依技術判斷，`#287` 未決 5）：取自
# `git show origin/main~1:devflow/VERSION` 會引入另一個會失效的假設——
# `origin/main~1` 在 rebase／多單並行時不是本單的 base，**正是本單在修的那一族**。
# 寫死的是**下界**不是等值，故不隨每次進位失效；下次要抬高下界時是明確的一次決定。
#
# **嚴格大於、不是 `≥`**（裁決位 2026-10-06）：`≥` 會讓「忘記進位」也通過。
VERSION_SHAPE = re.compile(r"\d+\.\d+\.\d+\.\d+")
P287_VERSION_FLOOR = "0.15.4.0"       # 前一單（#286）的版本＝本單的下界
P287_VERSION_NEXT = "0.15.5.0"        # 本單的期望值（V2 的 c 位；#287 未決 6）


def _version_gt(val: str, floor: str) -> tuple[bool, str]:
    """`val` 是否合四碼形狀**且**嚴格大於 `floor`。回 (結果, 理由)。

    **元組比較，不是字串比較**：字串比較下 `"0.15.10.0" < "0.15.4.0"`（逐字元比
    `1` < `4`），於是進位到第十個修正版時斷言會假 FAIL。唯一的判定函式——鑑別力
    子測試對它餵三個對照值，必須給出 T 預跑的答案。
    """
    if not VERSION_SHAPE.fullmatch(val):
        return False, "形狀不合四碼（^\\d+\\.\\d+\\.\\d+\\.\\d+$）"
    got = tuple(int(x) for x in val.split("."))
    want = tuple(int(x) for x in floor.split("."))
    return got > want, f"{got} > {want} ＝ {got > want}"


@case("#291 AC-8 devflow/VERSION 合四碼形狀且嚴格大於 0.15.4.0（#287 治本）")
def _p291_ac8():
    raw = (REPO / "devflow" / "VERSION").read_text()
    check("#291 AC-8 形狀合 V1 的四碼（^\\d+\\.\\d+\\.\\d+\\.\\d+$）",
          bool(VERSION_SHAPE.fullmatch(raw.strip())), repr(raw))
    ok, why = _version_gt(raw.strip(), P287_VERSION_FLOOR)
    check(f"#291 AC-8 嚴格大於下界 {P287_VERSION_FLOOR}（元組比較，非字串比較）",
          ok, f"{raw.strip()!r}：{why}")

    # 鑑別力：同一個判定函式對三個對照值須給出 T の預跑值
    for val, want, label in ((P287_VERSION_NEXT, True, "本單的 0.15.5.0 → PASS"),
                             (P287_VERSION_FLOOR, False,
                              "下界自身 0.15.4.0 → FAIL（嚴格大於，不是 ≥）"),
                             ("0.15.4", False, "三碼 0.15.4 → FAIL（四碼形狀）")):
        got, why = _version_gt(val, P287_VERSION_FLOOR)
        check(f"#291 AC-8 鑑別力：{label}", got is want, f"實得 {got}（{why}）")

    # 元組比較而非字串比較的鑑別力：`0.15.10.0` 字串上小於 `0.15.4.0`，元組上大於。
    got_str = "0.15.10.0" > P287_VERSION_FLOOR
    got_tuple, _ = _version_gt("0.15.10.0", P287_VERSION_FLOOR)
    check("#291 AC-8 鑑別力：0.15.10.0 字串比較為 False、元組比較為 True "
          "→ 證明用的是元組",
          got_str is False and got_tuple is True,
          f"字串 {got_str} 元組 {got_tuple}")


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


# ════════════════════════════════════════════════════════════════════════════
# `#287`／K4c-3：`archive.py` 三缺陷（同族）＋ 共用 marker 掃描 ＋ 版本斷言治本
# ════════════════════════════════════════════════════════════════════════════
# 本單的四個缺陷**是同一族**：程式持有的位置／時間假設在狀態變動後失效。
#   ① `cmd_scan` 的上界取自 cache，而封存會清 cache
#   ② `_ts` 的裸 `HH:MM` 假設「指今天」，跨午夜時失效
#   ③ `issue_meta` 的 cache 命中假設「命中即有效」，封存刪 topic 後失效
#   ④ `test_marker.py` 的版本硬編碼假設「VERSION 恆為某字面」，每次 `V7` 進位失效
# 故 AC 一律驗「假設在狀態變動後是否仍成立」，而**不以量測當下的實況為基準**。
# 本區段零 Telegram API、零 `gh`：所有 fixture 都是純字串（`AC-3` 的真 API 佐證
# 由實作者實跑一次並記進 issue 留言，見 `#287` `AC-3`）。
#
# `AC-1` 的四張 fixture body。每張都刻意放入**表格列內與散文裡的同形字串**——
# 錨定（`^…$`）成立時它們一律不算，拔掉錨定就會被計入，列數變多（鑑別力）。
P287_F_TOPIC = """# 只有 topic 的單

| 形態 | 字面 |
|---|---|
| 表格列內 | `<!-- devflow:topic thread=111 -->` |

散文也提一次 <!-- devflow:topic thread=222 --> 當旁註。

<!-- devflow:topic thread=3054 -->
"""

P287_F_BOTH = """# topic ＋ archived 的單（已封存但 topic 標記仍在）

| 表格列內 | `<!-- devflow:archived thread=333 file=/t/333.md -->` |

<!-- devflow:topic thread=3363 -->
<!-- devflow:archived thread=3363 file=/home/x/.hermes/archives/topics/291.md -->
"""

P287_F_ARCH = """# 只有 archived 的單（topic 標記被清掉、只剩封存標記）

散文提一次 <!-- devflow:archived thread=444 file=/t/444.md --> 當旁註。

<!-- devflow:archived thread=3724 file=/home/x/.hermes/archives/topics/286.md -->
"""

P287_F_NONE = """# 無標記的單

| 表格列內 | `<!-- devflow:topic thread=555 -->` |

散文提一次 thread=666，以及完整字面 <!-- devflow:topic thread=666 --> 當旁註。
"""

P287_ITEMS = [("285", P287_F_TOPIC), ("291", P287_F_BOTH),
              ("286", P287_F_ARCH), ("999", P287_F_NONE)]


def _p287_noanchor_marker(td: Path):
    """載入「拔掉 `^…$` 錨定」的 `_marker.py` 突變複本（對源碼字串操作，不改真檔）。

    `AC-1` 的鑑別力：錨定是共用掃描函式正確性的全部依據——拔掉它，表格列內與
    散文裡的同形字串都會被計入，回傳的列數變多（且混進錯的 thread id）。
    """
    mutated = (MARKER_SRC
               .replace('r"^<!-- devflow:topic thread=[0-9]+ -->$"',
                        'r"<!-- devflow:topic thread=[0-9]+ -->"')
               .replace('r"^<!-- devflow:archived thread=[0-9]+ file=[^ >]+ -->$"',
                        'r"<!-- devflow:archived thread=[0-9]+ file=[^ >]+ -->"'))
    assert mutated != MARKER_SRC, "突變未套用——grammar 常數的字面已變，鑑別力失效"
    assert "^<!-- devflow:topic" not in mutated, "突變殘留行首錨點"
    path = td / "_marker_noanchor.py"
    path.write_text(mutated)
    spec = importlib.util.spec_from_file_location("_marker_noanchor", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_marker_noanchor"] = mod
    spec.loader.exec_module(mod)
    return mod


# ── #287 AC-1 共用掃描函式：一批 (issue, body) → (issue, thread, kind) 的列 ───
@case("#287 AC-1 scan_topic／scan_archived 對四張 fixture 回傳正確的列")
def _p287_ac1():
    topic_rows = marker.scan_topic(P287_ITEMS)
    arch_rows = marker.scan_archived(P287_ITEMS)
    check("#287 AC-1 topic 側的列逐項正確（表格列與散文的同形字串不計入）",
          topic_rows == [("285", 3054, "topic"), ("291", 3363, "topic")],
          f"實得 {topic_rows!r}")
    check("#287 AC-1 archived 側的列逐項正確",
          arch_rows == [("291", 3363, "archived"), ("286", 3724, "archived")],
          f"實得 {arch_rows!r}")
    check("#287 AC-1 kind 恰為 topic／archived 兩種（AC-2 的過濾依據）",
          {k for _, _, k in topic_rows + arch_rows} == {"topic", "archived"},
          f"{sorted({k for _, _, k in topic_rows + arch_rows})!r}")
    check("#287 AC-1 無標記的單不產出任何列",
          not [r for r in topic_rows + arch_rows if r[0] == "999"],
          f"{topic_rows + arch_rows!r}")
    check("#287 AC-1 兩式一起掃時掃完才回傳（順序即輸入順序、同單先 topic 後 archived）",
          marker._scan_markers(P287_ITEMS) == [
              ("285", 3054, "topic"), ("291", 3363, "topic"),
              ("291", 3363, "archived"), ("286", 3724, "archived")],
          f"{marker._scan_markers(P287_ITEMS)!r}")

    # 不打網路／子程序：函式自身與其呼叫鏈只引用模組內的 read_*／grammar 常數。
    names = set(marker._scan_markers.__code__.co_names)
    check("#287 AC-1 掃描函式不引用 subprocess／urllib／gh／run 之類的名稱",
          not ({"subprocess", "urllib", "run", "gh", "Popen", "urlopen", "open"}
               & names),
          f"{sorted(names)!r}")
    check("#287 AC-1 `_marker.py` 全檔零網路／子程序 import（模組層的保證）",
          not re.search(r"^\s*import (subprocess|urllib|socket|http)", MARKER_SRC,
                        re.M)
          and not re.search(r"^\s*from (subprocess|urllib|socket|http)", MARKER_SRC,
                            re.M),
          "MARKER_SRC 的 import 區段：" + repr(
              [ln for ln in MARKER_SRC.splitlines() if ln.startswith("import ")]))

    # INVALID：預設穿出去（issue_meta 要的），給 on_invalid 則跳過該單續掃（sync 要的）
    bad = [("285", F3), ("286", P287_F_TOPIC)]
    try:
        marker.scan_topic(bad)
        check("#287 AC-1 預設（on_invalid=None）遇 T>1 raise InvalidMarker",
              False, "沒有擲出例外")
    except marker.InvalidMarker as e:
        check("#287 AC-1 預設（on_invalid=None）遇 T>1 raise InvalidMarker",
              "INVALID" in str(e) and all(ln in str(e) for ln in F3_LINES), str(e))
    seen = []
    rows = marker.scan_topic(bad, on_invalid=lambda exc, issue: seen.append(issue))
    check("#287 AC-1 給了 on_invalid → 回報該單並跳過，續掃其餘的單",
          seen == ["285"] and rows == [("286", 3054, "topic")],
          f"seen={seen!r} rows={rows!r}")


@case("#287 AC-1 鑑別力：拔掉 ^…$ 錨定的突變 → 同形字串被計入 → 斷言須 FAIL")
def _p287_ac1_mutation():
    with tempfile.TemporaryDirectory() as td:
        mut = _p287_noanchor_marker(Path(td))
        # (1) 計數層：錨定拔掉後，表格列內與散文裡的同形字串都被計入 → 命中行變多。
        counts = {}
        for label, body in (("只有 topic", P287_F_TOPIC), ("兩式都有", P287_F_BOTH),
                            ("只有 archived", P287_F_ARCH), ("無標記", P287_F_NONE)):
            good_t = len(marker.find_topic(body)[1])
            mut_t = len(mut.find_topic(body)[1])
            good_a = len(marker.find_archived(body)[1])
            mut_a = len(mut.find_archived(body)[1])
            counts[label] = ((good_t, mut_t), (good_a, mut_a))
            check(f"#287 AC-1 鑑別力：{label} 的命中行數變多（T {good_t}→{mut_t}、"
                  f"A {good_a}→{mut_a}）",
                  mut_t + mut_a > good_t + good_a,
                  f"錨定版 T={good_t} A={good_a}；突變版 T={mut_t} A={mut_a}")
        check("#287 AC-1 鑑別力：無標記的單在突變版下也有命中（＝誤判，T 從 0 變 2）",
              counts["無標記"][0] == (0, 2), f"{counts['無標記']!r}")

        # (2) 掃描層：列數變多的直接後果是 `T>1` → AC-1 的主斷言拿不到那四列。
        #     突變版對四張 fixture 全部擲 InvalidMarker（連「無標記」那張都是），
        #     而錨定版回傳正確的列 —— 斷言值不同，故 AC-1 確實有鑑別力。
        outcomes = {}
        for label, body in (("只有 topic", P287_F_TOPIC), ("無標記", P287_F_NONE)):
            try:
                outcomes[label] = ("return", mut.scan_topic([("x", body)]))
            except mut.InvalidMarker as e:
                outcomes[label] = ("raise", f"T={len(e.lines)}")
        check("#287 AC-1 鑑別力：突變版對「只有 topic」擲 INVALID（錨定版回 1 列）",
              outcomes["只有 topic"][0] == "raise"
              and marker.scan_topic([("x", P287_F_TOPIC)]) == [("x", 3054, "topic")],
              f"突變版 {outcomes['只有 topic']!r}")
        check("#287 AC-1 鑑別力：突變版對「無標記」亦擲 INVALID（錨定版回 0 列）",
              outcomes["無標記"][0] == "raise"
              and marker.scan_topic([("x", P287_F_NONE)]) == [],
              f"突變版 {outcomes['無標記']!r}")
        # (3) 跳過 INVALID 時突變版的列與錨定版不同（兩種處置下都 FAIL）
        mut_rows = mut.scan_topic(P287_ITEMS, on_invalid=lambda *a: None)
        good_rows = marker.scan_topic(P287_ITEMS)
        check("#287 AC-1 鑑別力：即使跳過 INVALID，突變版的列仍與錨定版不同",
              mut_rows != good_rows,
              f"錨定版 {good_rows!r}\n        突變版 {mut_rows!r}")


# ── #287 AC-2 sync／issue_meta 改用共用函式後對外行為一字不變 ─────────────────
@case("#287 AC-2 issue_meta 以 kind == topic 過濾：只有 archived 標記的單不得命中")
def _p287_ac2_kind():
    # 已封存的單（只剩 archived 標記）。若共用函式的 archived 列也被算進反向查找，
    # 這裡會回傳 ("286", …) ——那就是對外行為改變，AC-2 FAIL。
    kind, val = _issue_meta_with(
        [{"number": 286, "title": "已封存", "body": P287_F_ARCH, "state": "CLOSED"}])
    check("#287 AC-2 只有 archived 標記時不命中（退回 thread 命名）",
          (kind, val) == ("return", (None, "thread 2620", None)), f"實得 {kind}={val!r}")
    # 以該單自己的 thread 查也不得命中（archived 標記不是 topic 標記）
    def _meta_for(thread, rows):
        def fake_run(cmd, *a, **kw):
            return subprocess.CompletedProcess(cmd, 0, json.dumps(rows), "")
        with tempfile.TemporaryDirectory() as td:
            orig_cache, orig_run = archive.CACHE, subprocess.run
            archive.CACHE = Path(td) / "nonexistent.json"
            subprocess.run = fake_run
            try:
                return archive.issue_meta(thread)
            finally:
                archive.CACHE, subprocess.run = orig_cache, orig_run

    got = _meta_for("3724", [{"number": 286, "title": "已封存",
                              "body": P287_F_ARCH, "state": "CLOSED"}])
    check("#287 AC-2 以封存單自己的 thread 查亦不命中（kind 過濾生效）",
          got == (None, "thread 3724", None), f"實得 {got!r}")
    # 對照組：topic 標記在時照常命中（過濾不是一律不命中）
    got2 = _meta_for("3363", [{"number": 291, "title": "兩式都有",
                               "body": P287_F_BOTH, "state": "OPEN"}])
    check("#287 AC-2 對照組：topic 標記在時照常命中（含同時有 archived 的單）",
          got2 == ("291", "兩式都有", "OPEN"), f"實得 {got2!r}")
    check("#287 AC-2 未達成候選：若不以 kind 過濾，封存單會被 archived 列命中",
          [r for r in marker.scan_archived([("286", P287_F_ARCH)])] ==
          [("286", 3724, "archived")],
          "對照組：archived 側確實有 (286, 3724) 這一列")


@case("#287 AC-2 sync 改用共用函式後：映射、INVALID 跳過、回傳值形狀皆不變")
def _p287_ac2_sync():
    with tempfile.TemporaryDirectory() as td:
        cache = Path(td) / "devflow-topics.json"
        listing = [{"number": 285, "title": "單 A", "body": P287_F_TOPIC,
                    "state": "OPEN"},
                   {"number": 999, "title": "壞單", "body": F3, "state": "CLOSED"},
                   {"number": 286, "title": "只有封存標記", "body": P287_F_ARCH,
                    "state": "CLOSED"}]
        orig_gh, orig_cache = topic.gh, topic.CACHE
        topic.gh, topic.CACHE = (lambda *a: json.dumps(listing)), cache
        try:
            n, invalid = topic.sync()
        finally:
            topic.gh, topic.CACHE = orig_gh, orig_cache
        data = json.loads(cache.read_text())
    check("#287 AC-2 sync 映射取獨立一行的 3054（非表格列的 111／散文的 222）",
          data.get("285", {}).get("thread_id") == 3054,
          json.dumps(data, ensure_ascii=False))
    check("#287 AC-2 sync 遇 T>1 跳過該單續掃（#286 仍被掃到、#999 不入 cache）",
          "999" not in data and invalid == ["999"], f"invalid={invalid!r} {data!r}")
    check("#287 AC-2 sync 只認 topic 標記（只有 archived 的 #286 不入 cache）",
          "286" not in data, json.dumps(data, ensure_ascii=False))
    check("#287 AC-2 sync 回傳 (映射數, INVALID 單號清單)，映射數與 cache 筆數一致",
          (n, invalid) == (1, ["999"]) and len(data) == n, f"n={n} invalid={invalid!r}")
    check("#287 AC-2 sync 保留 state／title 欄（cache 形狀不變）",
          data["285"] == {"thread_id": 3054, "state": "open", "title": "單 A"},
          json.dumps(data["285"], ensure_ascii=False))


# ── #287 AC-3 cmd_scan 的上界改從 forge 推 ─────────────────────────────────
@case("#287 AC-3 scan_upper_bound 是純函式：三組 fixture 的 hi 逐組正確")
def _p287_ac3():
    hi_a = archive.scan_upper_bound([("286", P287_F_ARCH), ("291", P287_F_BOTH)])
    check("#287 AC-3(a) 含 thread=3724 → hi > 3724",
          hi_a > 3724 and hi_a == 3724 + archive.SCAN_HI_MARGIN, f"hi={hi_a}")
    hi_b = archive.scan_upper_bound([("999", P287_F_NONE)])
    check(f"#287 AC-3(b) 全無標記 → hi ＝ 寫死值 {archive.SCAN_HI_FLOOR}",
          hi_b == archive.SCAN_HI_FLOOR == 400, f"hi={hi_b}")
    hi_c = archive.scan_upper_bound([("286", P287_F_ARCH)])
    check("#287 AC-3(c) 只有 archived 標記（已封存的單）→ 仍計入",
          hi_c == 3724 + archive.SCAN_HI_MARGIN, f"hi={hi_c}")
    check("#287 AC-3 空輸入 → 退回寫死值（零命中的極端）",
          archive.scan_upper_bound([]) == archive.SCAN_HI_FLOOR)
    check("#287 AC-3 未達成候選：舊來源（cache 為 {} ）得 hi=450 < 3724",
          max([400]) + 50 == 450 < 3724,
          "舊實作 hi = max([400] + cache 內的 ids) + 50，cache 空時即 450")
    # 純函式：不讀 CACHE、不開子程序
    names = set(archive.scan_upper_bound.__code__.co_names)
    check("#287 AC-3 scan_upper_bound 不引用 CACHE／subprocess／api",
          not ({"CACHE", "subprocess", "api", "urlopen", "read_text"} & names),
          f"{sorted(names)!r}")
    check("#287 AC-3 T>1 的單交給 on_invalid 並跳過（算的是探測範圍，不是分區歸屬）",
          archive.scan_upper_bound([("285", F3), ("286", P287_F_ARCH)],
                                   on_invalid=lambda *a: None)
          == 3724 + archive.SCAN_HI_MARGIN)


def _p287_cmd_scan_hi(cache_state: str) -> tuple[int | None, str]:
    """在指定的 CACHE 狀態下跑 `cmd_scan`，回傳它實際用的 `hi` 與全部輸出。

    `api` 與 `_forge_scan_items` 都換成假的 → 零 Telegram API、零 `gh`。
    `cache_state` ∈ {`"missing"`, `"empty"`, `"corrupt"`}。
    """
    import contextlib
    import io

    with tempfile.TemporaryDirectory() as td:
        cache = Path(td) / "devflow-topics.json"
        if cache_state == "empty":
            cache.write_text("{}\n")
        elif cache_state == "corrupt":
            cache.write_text("{not json at all")
        orig = (archive.CACHE, archive.api, archive._forge_scan_items)
        archive.CACHE = cache
        archive.api = lambda *a, **kw: {"ok": False, "description": ""}
        archive._forge_scan_items = lambda *a, **kw: list(P287_ITEMS)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                # cache 損壞時 `cmd_scan` 的「cache 過期項」區段會自己拋——那段不在
                # 本 AC 的範圍（上界已在它之前印出）。
                with contextlib.suppress(Exception):
                    # `full=True`：上界那行自 `#296` 起**只在 `--full` 印出**（預設
                    # 模式改探「本 kit 管理過的」候選集合，不再掃 `range(2, hi)`）。
                    # 本 helper 以 `上界 hi=(\d+)` 讀輸出、驗的本來就是上界推導那條
                    # 路徑，故須走 `--full`；`#287` 的斷言語意一字不變。
                    archive.cmd_scan(argparse.Namespace(prune=False, full=True))
        finally:
            archive.CACHE, archive.api, archive._forge_scan_items = orig
        out = buf.getvalue()
    m = re.search(r"上界 hi=(\d+)", out)
    return (int(m.group(1)) if m else None), out


@case("#287 AC-3／AC-5① cache 不存在／為 {}／損壞三種狀態下 hi 皆由 forge 推出")
def _p287_ac3_cache_states():
    want = 3724 + archive.SCAN_HI_MARGIN
    got = {}
    for state in ("missing", "empty", "corrupt"):
        hi, out = _p287_cmd_scan_hi(state)
        got[state] = hi
        check(f"#287 AC-3 cache {state}：hi == {want}（> 3724，由 forge 的標記推出）",
              hi == want and hi > 3724, f"hi={hi!r}\n--- 輸出 ---\n{out}")
    check("#287 AC-3 三種 cache 狀態的 hi 完全相同 → 上界不再依賴 cache",
          len(set(got.values())) == 1, f"{got!r}")
    check("#287 AC-5① 狀態變動（cache 被封存清空）後 hi 仍 > 3724",
          got["empty"] == want, f"{got!r}")
    # 註解要求：代價須寫明（`AC-3` 明文）
    hi_seg = ARCHIVE_SRC.split("def cmd_scan(")[1].split("found = []")[0]
    check("#287 AC-3 cmd_scan 的上界段註解寫明「從 forge 推」與 cache 的失效",
          "forge" in hi_seg and "封存" in hi_seg and "cache" in hi_seg, hi_seg)
    check("#287 AC-3 :480-482 的舊註解已更新（不再寫「以 cache 內最大 id 為界」）",
          "以 cache 內最大 id 再加一段餘裕為界" not in ARCHIVE_SRC
          and "那次的修法是把一個會" in ARCHIVE_SRC, hi_seg)
    fetch_doc = archive._forge_scan_items.__doc__ or ""
    check("#287 AC-3 代價寫在來源函式的 docstring（依賴一次 gh 查詢、慢、要網路）",
          "gh" in fetch_doc and "網路" in fetch_doc and "代價" in fetch_doc,
          fetch_doc)


# ── #287 AC-4／AC-5② `_ts` 改為要求日期或 epoch ─────────────────────────────
@case("#287 AC-4 _ts 拒絕裸 HH:MM、接受明確日期與 epoch（兩者同一時間戳）")
def _p287_ac4():
    import datetime as _dt
    try:
        archive._ts("19:00")
        check("#287 AC-4 裸 19:00 被拒（擲 ArgumentTypeError）", False, "竟回傳了值")
    except argparse.ArgumentTypeError as e:
        msg = str(e)
        check("#287 AC-4 裸 19:00 被拒（擲 ArgumentTypeError）", True)
        check("#287 AC-4 訊息印出可照抄的正確形式（YYYY-MM-DDTHH:MM ＋ epoch）",
              "2026-10-06T19:00" in msg and "+%s" in msg, msg)
        check("#287 AC-4 訊息說明理由（跨午夜無法表達意圖），不靜默猜日期",
              "跨午夜" in msg and "HH:MM" in msg, msg)

    want = _dt.datetime(2026, 10, 6, 19, 0).timestamp()
    got_iso = archive._ts("2026-10-06T19:00")
    got_epoch = archive._ts(str(int(want)))
    check("#287 AC-4 2026-10-06T19:00 與對應 epoch 解出同一時間戳",
          got_iso == got_epoch == want,
          f"iso={got_iso!r} epoch={got_epoch!r} 期望={want!r}")
    check("#287 AC-4 等義的明確日期形式亦接受（空白分隔、純日期）",
          archive._ts("2026-10-06 19:00") == want
          and archive._ts("2026-10-06") == _dt.datetime(2026, 10, 6).timestamp())
    check("#287 AC-4 小數 epoch 亦接受（collect 的時間戳是浮點）",
          archive._ts("1759748400.5") == 1759748400.5)
    for bad in ("19:00", "9:5", "下午七點", "", "2026-13-45T99:99"):
        raised = False
        try:
            archive._ts(bad)
        except argparse.ArgumentTypeError:
            raised = True
        check(f"#287 AC-4 {bad!r} 被拒（不猜日期）", raised)

    # main 的 metavar／help 同步（`AC-4` 明文；`main` 的改動僅限這兩個欄位）
    main_src = ARCHIVE_SRC.split("def main(")[1]
    check("#287 AC-4 main 的 --since／--until metavar 已改為 YYYY-MM-DDTHH:MM|EPOCH",
          main_src.count('metavar="YYYY-MM-DDTHH:MM|EPOCH"') == 2
          and 'metavar="HH:MM|EPOCH"' not in ARCHIVE_SRC,
          "\n".join(ln for ln in main_src.splitlines() if "metavar" in ln))
    check("#287 AC-4 help 文字亦同步（明文寫出不接受裸 HH:MM）",
          "不接受裸 HH:MM" in main_src,
          "\n".join(ln for ln in main_src.splitlines() if "help=" in ln))


@case("#287 AC-5② 跨午夜：當前時刻 < --since 的 HH:MM → 明確錯誤（CLI 層 rc 非 0）")
def _p287_ac5_midnight():
    import datetime as _dt
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        home, bin_ = td / "home", td / "bin"
        bin_.mkdir()
        _fake_gh(bin_, [])
        _seed_home(home)
        env = dict(os.environ, HOME=str(home),
                   PATH=f"{bin_}:{os.environ.get('PATH', '')}",
                   PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([PY, str(SCRIPTS / "devflow_archive.py"),
                            "export", "2620", "--since", "19:00",
                            "--until", "04:10"],
                           capture_output=True, text=True, env=env,
                           stdin=subprocess.DEVNULL, timeout=120)
        leftovers = [str(p) for p in (home / ".hermes" / "archives").rglob("*")
                     if p.is_file()]
    detail = f"exit={r.returncode}\n--- stdout ---\n{r.stdout}--- stderr ---\n{r.stderr}"
    check("#287 AC-5② CLI 對 --since 19:00 回非 0", r.returncode != 0, detail)
    check("#287 AC-5② stderr 含可照抄的正確形式",
          "2026-10-06T19:00" in r.stderr, detail)
    check("#287 AC-5② 未靜默匯出（不得產生以錯誤時間窗撈出的檔）",
          not leftovers, detail + f"\n殘留：{leftovers}")
    check("#287 AC-5② 未印「沒有任何訊息」（那是舊實作的靜默失敗面貌）",
          "沒有任何訊息" not in r.stdout, detail)

    # 未達成候選：`6b72933` 的 `_ts` 在「當前時刻 < HH:MM」時解出**未來**時刻。
    def _ts_old(val: str, now: _dt.datetime) -> float:
        h, m = val.split(":", 1)
        return _dt.datetime.combine(now.date(),
                                    _dt.time(int(h), int(m))).timestamp()

    now = _dt.datetime(2026, 10, 7, 4, 6)       # #286 封存實地發生的時刻
    old_since = _ts_old("19:00", now)
    check("#287 AC-5② 未達成候選：舊 _ts 在 04:06 把 19:00 解成未來時刻",
          old_since > now.timestamp(),
          f"舊 since={old_since} ({_dt.datetime.fromtimestamp(old_since)}) "
          f"> now={now.timestamp()} ({now})")
    check("#287 AC-5② 未達成候選：舊版的時間窗因此為負（故匯出 0 則且無告警）",
          _ts_old("04:10", now) - old_since < 0,
          f"until-since = {_ts_old('04:10', now) - old_since}")


# ── #287 AC-6 issue_meta 的 cache 死條目：不驗活、不宣稱存在 ─────────────────
@case("#287 AC-6／AC-5③ cache 含已刪 thread 的條目：issue 號正確且不宣稱該 thread 存在")
def _p287_ac6():
    calls = []
    with tempfile.TemporaryDirectory() as td:
        cache = Path(td) / "devflow-topics.json"
        # 3958 是本單自己的 thread；假設它已被刪除而 cache 殘留（封存刪 topic 後的狀態）
        cache.write_text(json.dumps(
            {"287": {"thread_id": 3958, "state": "open", "title": "🐛 K4c-3"}},
            ensure_ascii=False))
        orig = (archive.CACHE, archive.api, subprocess.run)
        archive.CACHE = cache
        archive.api = lambda method, **kw: (calls.append(method)
                                            or {"ok": False,
                                                "description": "TOPIC_ID_INVALID"})
        subprocess.run = lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("cache 命中時不得查 forge"))
        try:
            got = archive.issue_meta("3958")
        finally:
            archive.CACHE, archive.api, subprocess.run = orig
    check("#287 AC-6 issue 號與標題取自 cache 且正確",
          got == ("287", "🐛 K4c-3", "OPEN"), f"實得 {got!r}")
    check("#287 AC-6 不額外打 API 驗活（熱路徑上不多一次網路往返）",
          calls == [], f"實際 API 呼叫：{calls!r}")
    check("#287 AC-6 回傳值是三元組 (issue, title, issue 的 state)，不含存活狀態",
          len(got) == 3 and got[2] in ("OPEN", "CLOSED", "", None)
          and not any(isinstance(x, bool) for x in got),
          f"實得 {got!r}")
    check("#287 AC-6 issue_meta 不呼叫 api／_alive（源碼層）",
          not ({"api", "_alive"} & set(archive.issue_meta.__code__.co_names)),
          f"{sorted(archive.issue_meta.__code__.co_names)!r}")
    doc = archive.issue_meta.__doc__ or ""
    check("#287 AC-6 docstring 寫明分工（cache 只取 issue 號與標題、存活由呼叫端探）",
          "存活" in doc and "呼叫端" in doc and "不宣稱" in doc, doc)
    check("#287 AC-6／AC-5③ 呼叫端的既有探活仍在（ensure 的 _alive、archive 的 delete）",
          "_alive(tid)" in (SCRIPTS / "devflow_topic.py").read_text()
          and "deleteForumTopic" in ARCHIVE_SRC)


# ── #287 AC-9 `#293` 的結論重驗：parse_mode 仍一處、caption 外部值全轉義 ──────
@case("#287 AC-9 parse_mode 恰一處、cmd_publish 的四個外部值仍全過 esc_html")
def _p287_ac9():
    r = subprocess.run(["grep", "-c", "parse_mode",
                        *[str(p) for p in sorted(SCRIPTS.glob("*.py"))]],
                       capture_output=True, text=True)
    counts = dict(ln.rsplit(":", 1) for ln in r.stdout.strip().splitlines())
    total = sum(int(v) for v in counts.values())
    check("#287 AC-9 telegram/*.py 的 parse_mode 總數恰 1（僅 archive.py）",
          total == 1 and int(counts.get(
              str(SCRIPTS / "devflow_archive.py"), "0")) == 1,
          f"{counts!r}")
    pub = ARCHIVE_SRC.split("def cmd_publish(")[1].split("\ndef ")[0]
    for val in ("esc_html(head)", "esc_html(title)", "esc_html(args.thread)",
                "esc_html(state)"):
        check(f"#287 AC-9 cmd_publish 的 {val} 仍在", val in pub, pub)
    check("#287 AC-9 本單未新增送訊息路徑（sendDocument 的字面數與 7f7b2bb 相同）",
          ARCHIVE_SRC.count("sendDocument") == 2
          and ARCHIVE_SRC.count("sendMessage") == 0,
          f"sendDocument={ARCHIVE_SRC.count('sendDocument')}（期望 2："
          f"`send_document` 的 URL 一處 ＋ 其 docstring 的 `#293` 紀錄一處）"
          f" sendMessage={ARCHIVE_SRC.count('sendMessage')}")
    base = subprocess.run(
        ["git", "show", "7f7b2bb:devflow/channels/scripts/telegram/devflow_archive.py"],
        capture_output=True, text=True, cwd=REPO).stdout
    check("#287 AC-9 與 base（7f7b2bb）逐項比對：送訊息字面數一字未增",
          bool(base) and base.count("sendDocument") == ARCHIVE_SRC.count("sendDocument")
          and base.count("sendMessage") == ARCHIVE_SRC.count("sendMessage")
          and base.count("api(\"send") == ARCHIVE_SRC.count("api(\"send"),
          f"base sendDocument={base.count('sendDocument')} "
          f"本單={ARCHIVE_SRC.count('sendDocument')}")


# ── #296 AC-1～AC-5／AC-7 scan 的探活集合改由「管理過的 thread id」決定 ──────
# fixtures 沿用 `#287` 的四張（它們已含表格列內與散文裡的同形字串＝錨定的鑑別力），
# 另加一張把 `AC-2` 要求的其餘反例集中起來：缺 `file=` 欄、`thread=` 非數字、
# `file=` 值含空白、縮排。每個反例旁邊都有一個**會命中**的真標記（4100），
# 否則「不命中」與「整張單沒掃到」分不開。
P296_F_BAD = """# 反例集中的單

缺 file= 欄（archived 式要求 file=）：
<!-- devflow:archived thread=4001 -->

thread= 非數字：
<!-- devflow:topic thread=abc -->

file= 值含空白（`[^ >]+` 不收空白）：
<!-- devflow:archived thread=4002 file=/t/a b.md -->

縮排（不是行首）：
  <!-- devflow:topic thread=4003 -->

| 表格列內 | `<!-- devflow:topic thread=4004 -->` |

散文旁註一次 <!-- devflow:topic thread=4005 --> 如上。

<!-- devflow:topic thread=4100 -->
"""

# 只有 topic 標記、且**不**在 cache 內的單（`AC-3` 第三組對照要移除的就是它）
P296_F_BAD_NOTOPIC = P296_F_BAD.replace(
    "<!-- devflow:topic thread=4100 -->\n", "")

P296_ITEMS = [("285", P287_F_TOPIC),      # topic 3054（亦在 cache → 去重對照）
              ("291", P287_F_BOTH),       # topic ＋ archived 同為 3363
              ("286", P287_F_ARCH),       # 只有 archived 3724（已封存的單）
              ("999", P287_F_NONE),       # 無標記
              ("295", P296_F_BAD)]        # 反例集中 ＋ 真標記 4100

# 自造 cache（**不得**用真 cache：本機現為 `{}`，拿它驗會讓 cache 那組恆真，`R6`）。
#   * `"300"` → 4394：只有 cache 記得的 thread（`ensure` 建了 topic 但寫回 forge
#     失敗的形態，`#285` ⑤-c）——拿掉 cache 來源就漏掉它。
#   * `"285"` → 3054：與 forge 標記重複 —— 聯集須去重，不得出現兩次。
P296_CACHE = {"300": {"thread_id": 4394, "state": "open", "title": "單 X"},
              "285": {"thread_id": 3054, "state": "open", "title": "單 A"}}

P296_WANT = [261, 3054, 3363, 3724, 4100, 4394]

# `R1` 第 1 輪 `BLOCK 1` 的交叉形態：**一式 INVALID、另一式合法**。
# 第 1 輪的實作把 `on_invalid` 直接交給 `scan_topic`／`scan_archived` 兩次呼叫，
# 於是 `_marker.py:141` 的「跳過時整張單都跳過」只在各自那一次內成立 ——
# 壞單**另一式**的 id 仍進候選（複驗得 `[7999]`／`[8001]`，期望 `[]`）。
# 這兩張 fixture 的字面即 BLOCK 1 複驗腳本的 body，逐字相同。
P296_F_T2_A1 = ("<!-- devflow:topic thread=7001 -->\n"
                "<!-- devflow:topic thread=7002 -->\n"
                "<!-- devflow:archived thread=7999 file=/t/x.md -->\n")
P296_F_T1_A2 = ("<!-- devflow:topic thread=8001 -->\n"
                "<!-- devflow:archived thread=8998 file=/t/a.md -->\n"
                "<!-- devflow:archived thread=8999 file=/t/b.md -->\n")
# 兩式都 INVALID：`on_invalid` 對**一張**單只該被呼叫一次（第 1 輪叫兩次）
P296_F_T2_A2 = ("<!-- devflow:topic thread=9001 -->\n"
                "<!-- devflow:topic thread=9002 -->\n"
                "<!-- devflow:archived thread=9998 file=/t/a.md -->\n"
                "<!-- devflow:archived thread=9999 file=/t/b.md -->\n")


@case("#296 AC-2／BLOCK-1 交叉形態：一式 INVALID → 該單**全部** id 都不進候選")
def _p296_block1_cross():
    # ① 單獨驗（＝ BLOCK 1 複驗腳本的兩個 case，期望 candidates == []）
    for label, body, kind, leaked in (
            ("T>1 + A=1", P296_F_T2_A1, "topic", 7999),
            ("T=1 + A>1", P296_F_T1_A2, "archived", 8001)):
        seen = []
        got = archive.scan_candidates(
            [("900", body)], {}, None,
            on_invalid=lambda exc, issue: seen.append((issue, exc.kind)))
        check(f"#296 BLOCK-1 {label}：候選為空（整張單跳過）",
              got == [], f"實得 {got!r}；期望 []")
        check(f"#296 BLOCK-1 {label}：on_invalid 收到該單號恰一次，kind=={kind}",
              seen == [("900", kind)], f"實得 {seen!r}")
        check(f"#296 BLOCK-1 {label}：另一式的合法 id {leaked} 未漏進候選"
              f"（第 1 輪的實作在此回 [{leaked}]）",
              leaked not in got, f"實得 {got!r}")

    # ② 同批其他合法單不受影響 —— 期望集合逐一相等（不比長度）
    for label, body in (("T>1 + A=1", P296_F_T2_A1),
                        ("T=1 + A>1", P296_F_T1_A2),
                        ("T>1 + A>1", P296_F_T2_A2)):
        seen = []
        got = archive.scan_candidates(
            P296_ITEMS + [("900", body)], P296_CACHE, archive.ARCHIVES_THREAD,
            on_invalid=lambda exc, issue: seen.append(issue))
        check(f"#296 BLOCK-1 {label} 混在合法單中：其餘 id 一字不少、壞單一個不進",
              got == P296_WANT, f"實得 {got!r}\n期望 {P296_WANT!r}")
        check(f"#296 BLOCK-1 {label}：on_invalid 對同一壞單恰呼叫一次"
              "（非阻擋建議：第 1 輪的 T>1＋A>1 會叫兩次）",
              seen == ["900"], f"實得 {seen!r}")
        for leaked in (7001, 7002, 7999, 8001, 8998, 8999, 9001, 9002, 9998, 9999):
            if leaked in got:
                check(f"#296 BLOCK-1 {label}：壞單的 id {leaked} 不在集合內",
                      False, f"實得 {got!r}")

    # ③ `on_invalid is None` 時語意不變：`InvalidMarker` 原樣穿出去（不靜默跳過）
    for label, body in (("T>1 + A=1", P296_F_T2_A1), ("T=1 + A>1", P296_F_T1_A2)):
        raised = False
        try:
            archive.scan_candidates([("900", body)], {}, None)
        except marker.InvalidMarker:
            raised = True
        check(f"#296 BLOCK-1 {label}：未給 on_invalid → InvalidMarker 穿出"
              "（與 scan_upper_bound 的預設一致）", raised)

    # ④ 鑑別力：同一壞單若「只有 INVALID 的那一式」，第 1 輪也會回 [] ——
    #    故交叉形態（另一式合法）才是有鑑別力的 fixture。
    only_t2 = archive.scan_candidates([("900", F3)], {}, None,
                                      on_invalid=lambda *a: None)
    check("#296 BLOCK-1 鑑別力：單一式 INVALID（F3，無 archived 式）兩版實作都回 []"
          " → 本 BLOCK 只有交叉形態驗得出來",
          only_t2 == [], f"實得 {only_t2!r}")

    # ⑤ scan_sources 亦整張跳過，且 on_invalid 不因分解而重複呼叫
    seen = []
    src = archive.scan_sources(
        P296_ITEMS + [("900", P296_F_T2_A1)], P296_CACHE, archive.ARCHIVES_THREAD,
        on_invalid=lambda exc, issue: seen.append(issue))
    check("#296 BLOCK-1 scan_sources 的 all 與 marks 亦不含壞單的 id",
          src["all"] == P296_WANT and src["marks"] == [3054, 3363, 3724, 4100],
          f"{src!r}")
    check("#296 非阻擋建議：scan_sources 不重複解析 → on_invalid 恰一次",
          seen == ["900"], f"實得 {seen!r}")


@case("#296 AC-1／R2-BLOCK-1 三來源聯集只有一處定義：scan_sources[\"all\"] "
      "逐一等於 scan_candidates(...)")
def _p296_r2_block1_single_union():
    # ① 合法批：`all` 與直接呼叫 `scan_candidates` 逐一相等
    direct = archive.scan_candidates(P296_ITEMS, P296_CACHE,
                                     archive.ARCHIVES_THREAD)
    src = archive.scan_sources(P296_ITEMS, P296_CACHE, archive.ARCHIVES_THREAD)
    check("#296 R2-BLOCK-1 合法批：scan_sources['all'] == scan_candidates(...)",
          src["all"] == direct == P296_WANT,
          f"all={src['all']!r}\ndirect={direct!r}\n期望={P296_WANT!r}")

    # ② 交叉 INVALID 批（一式 INVALID、另一式合法）：兩者仍逐一相等
    #    —— 第 2 輪的第二套聯集是 `set(marks) | set(cids) | set(arch)`，而 `marks`
    #    那次餵的來源組合與 `all` 不同，兩處定義一旦漂移就在這裡分岔。
    for label, body in (("T>1 + A=1", P296_F_T2_A1),
                        ("T=1 + A>1", P296_F_T1_A2),
                        ("T>1 + A>1", P296_F_T2_A2)):
        items = P296_ITEMS + [("900", body)]
        quiet = (lambda *_a: None)
        direct = archive.scan_candidates(items, P296_CACHE,
                                         archive.ARCHIVES_THREAD,
                                         on_invalid=quiet)
        src = archive.scan_sources(items, P296_CACHE, archive.ARCHIVES_THREAD,
                                   on_invalid=quiet)
        check(f"#296 R2-BLOCK-1 {label}：scan_sources['all'] == "
              "scan_candidates(...) 逐一相等",
              src["all"] == direct == P296_WANT,
              f"all={src['all']!r}\ndirect={direct!r}\n期望={P296_WANT!r}")

    # ③ 三來源的各種空／非空組合：`all` 恆等於直接呼叫（不是只在滿載時相等）
    for label, items, cache, arch in (
            ("三來源皆空", [], {}, None),
            ("只有標記", P296_ITEMS, {}, None),
            ("只有 cache", [], P296_CACHE, None),
            ("只有 archives", [], {}, 261),
            ("標記 ＋ cache（無 archives）", P296_ITEMS, P296_CACHE, None),
            ("cache ＋ archives（無標記）", [], P296_CACHE, 261)):
        direct = archive.scan_candidates(items, cache, arch)
        src = archive.scan_sources(items, cache, arch)
        check(f"#296 R2-BLOCK-1 {label}：all == scan_candidates(...)",
              src["all"] == direct,
              f"all={src['all']!r} direct={direct!r}")

    # ④ 四欄全部是 scan_candidates 的回傳值（子集呼叫，不是另一套邏輯）
    src = archive.scan_sources(P296_ITEMS, P296_CACHE, archive.ARCHIVES_THREAD)
    check("#296 R2-BLOCK-1 marks 欄 == scan_candidates(items, {}, None)",
          src["marks"] == archive.scan_candidates(P296_ITEMS, {}, None),
          f"{src['marks']!r}")
    check("#296 R2-BLOCK-1 cache 欄 == scan_candidates([], cache, None)",
          src["cache"] == archive.scan_candidates([], P296_CACHE, None),
          f"{src['cache']!r}")
    check("#296 R2-BLOCK-1 archives 欄 == scan_candidates([], {}, archives)",
          src["archives"] == archive.scan_candidates(
              [], {}, archive.ARCHIVES_THREAD) == [261],
          f"{src['archives']!r}")

    # ⑤ 源碼層反向斷言：第二套聯集的字面與 cmd_scan 的取用路徑都須 0 命中
    check("#296 R2-BLOCK-1 全檔 `\"all\": sorted(set` 0 命中"
          "（聯集不得在 scan_candidates 外再定義一次）",
          ARCHIVE_SRC.count('"all": sorted(set') == 0,
          "\n".join(ln for ln in ARCHIVE_SRC.splitlines() if "sorted(set" in ln))
    check("#296 R2-BLOCK-1 全檔 `sorted(set` 0 命中（含任何改寫形態）",
          ARCHIVE_SRC.count("sorted(set") == 0,
          "\n".join(ln for ln in ARCHIVE_SRC.splitlines() if "sorted(set" in ln))
    scan_src = ARCHIVE_SRC.split("def cmd_scan(")[1].split("\ndef ")[0]
    check("#296 R2-BLOCK-1 cmd_scan 段內 `src[\"all\"]` 0 命中"
          "（targets 不經分解字典）",
          scan_src.count('src["all"]') == 0,
          "\n".join(ln for ln in scan_src.splitlines() if 'src["all"]' in ln))
    check("#296 R2-BLOCK-1 cmd_scan 的 targets 直接來自 "
          "scan_candidates(items, cache_data, ARCHIVES_THREAD, …)",
          "targets = scan_candidates(items, cache_data, ARCHIVES_THREAD,"
          in scan_src,
          "\n".join(ln for ln in scan_src.splitlines() if "targets" in ln))
    sources_src = ARCHIVE_SRC.split("def scan_sources(")[1].split("\ndef ")[0]
    # 去掉函式自己的 docstring（maxsplit=2：只切到主 docstring 結束，`_quiet` 的
    # 巢狀 docstring 留在函式體內，它本身也不得含集合運算）。
    body_only = (sources_src.split('"""', 2)[2] if '"""' in sources_src
                 else sources_src)
    check("#296 R2-BLOCK-1 scan_sources 的函式體無任何集合運算"
          "（set(／|／sorted( 皆 0 命中）",
          body_only.count("set(") == 0 and body_only.count("sorted(") == 0
          and "|" not in body_only, body_only)
    check("#296 R2-BLOCK-1 scan_sources 的四欄各是一次 scan_candidates 呼叫",
          body_only.count("scan_candidates(") == 4, body_only)


@case("#296 AC-1／AC-2 候選集合＝標記 ∪ cache ∪ archives，逐一相等（含反例）")
def _p296_ac1_ac2():
    got = archive.scan_candidates(P296_ITEMS, P296_CACHE, archive.ARCHIVES_THREAD)
    check("#296 AC-2 候選集合逐一相等（不是只比長度）",
          got == P296_WANT, f"實得 {got!r}\n期望 {P296_WANT!r}")
    check("#296 AC-1 回傳已排序、去重、全為 int（3054 同時來自標記與 cache）",
          got == sorted(set(got)) and all(isinstance(x, int) for x in got)
          and got.count(3054) == 1, f"{got!r}")

    # 反例：P296_F_BAD 的六個同形字串一個都不得命中，只有 4100 在集合內
    only_bad = archive.scan_candidates([("295", P296_F_BAD)], {}, None)
    check("#296 AC-2 反例單只命中 4100（缺 file=／非數字／file 含空白／縮排／"
          "表格列／散文旁註一律不計）",
          only_bad == [4100], f"實得 {only_bad!r}")
    for bad in (4001, 4002, 4003, 4004, 4005):
        check(f"#296 AC-2 反例 thread={bad} 不在集合內", bad not in only_bad,
              f"{only_bad!r}")
    # 鑑別力：拔掉錨定後，縮排／表格列內／散文裡的同形字串都會被計入（fixture 有效）
    check("#296 AC-2 鑑別力：未錨定的 re.search 在同一 body 讀到 4003（縮排那行）",
          re.search(r"<!-- devflow:topic thread=(\d+) -->",
                    P296_F_BAD).group(1) == "4003",
          "對照組：證明反例 fixture 對錨定有鑑別力")
    check("#296 AC-2 鑑別力：未錨定的 findall 命中 3 個（4003 縮排／4004 表格／"
          "4005 散文），錨定下一個都不算",
          re.findall(r"<!-- devflow:topic thread=(\d+) -->", P296_F_BAD)
          == ["4003", "4004", "4005", "4100"],
          repr(re.findall(r"<!-- devflow:topic thread=(\d+) -->", P296_F_BAD)))

    # T>1 的單：經 on_invalid 回報並跳過**該單**，其餘 id 仍在集合內
    seen = []
    with_bad = archive.scan_candidates(
        P296_ITEMS + [("288", F3)], P296_CACHE, archive.ARCHIVES_THREAD,
        on_invalid=lambda exc, issue: seen.append(issue))
    check("#296 AC-2 T>1 的單經 on_invalid 回報（單號正確）",
          seen == ["288"], f"實得 {seen!r}")
    check("#296 AC-2 一張壞單不得吃掉整個集合（其餘 id 一字不少）",
          with_bad == P296_WANT, f"實得 {with_bad!r}\n期望 {P296_WANT!r}")
    check("#296 AC-2 壞單自己的 id（2620／999）不進集合（分區歸屬無單一答案）",
          2620 not in with_bad and 999 not in with_bad, f"{with_bad!r}")

    # A>1 亦同（archived 式的 INVALID）
    seen_a = []
    f_a2 = ("<!-- devflow:archived thread=5001 file=/t/a.md -->\n\n中間\n\n"
            "<!-- devflow:archived thread=5002 file=/t/b.md -->\n")
    got_a = archive.scan_candidates([("289", f_a2), ("286", P287_F_ARCH)], {}, None,
                                    on_invalid=lambda exc, i: seen_a.append(i))
    check("#296 AC-2 A>1 的單亦經 on_invalid 跳過，其餘單不受影響",
          seen_a == ["289"] and got_a == [3724],
          f"on_invalid={seen_a!r} 集合={got_a!r}")

    # 三個來源皆空 → 空集合
    check("#296 AC-2 三來源皆空 → 空集合（不是 None、不是 [0]）",
          archive.scan_candidates([], {}, None) == [],
          repr(archive.scan_candidates([], {}, None)))
    check("#296 AC-2 只有無標記的單 ＋ 空 cache ＋ 無 archives → 空集合",
          archive.scan_candidates([("999", P287_F_NONE)], {}, None) == [])

    # `AC-1`：解析一律經 `_marker`，不自備正則
    names = set(archive.scan_candidates.__code__.co_names)
    check("#296 AC-1 scan_candidates 經 _marker 解析（不自備正則、不碰 I/O）",
          "_marker" in names
          and not ({"re", "compile", "search", "findall", "finditer",
                    "CACHE", "subprocess", "api", "read_text"} & names),
          f"{sorted(names)!r}")
    check("#296 AC-1 scan_candidates 是頂層純函式（模組屬性、可直接餵 fixture）",
          callable(getattr(archive, "scan_candidates", None)))


@case("#296 AC-3 鑑別力：三個來源各移除一筆 → 集合恰少該 id、其餘不變")
def _p296_ac3():
    base = archive.scan_candidates(P296_ITEMS, P296_CACHE, archive.ARCHIVES_THREAD)
    check("#296 AC-3 基準集合 == 期望", base == P296_WANT, f"{base!r}")

    # ① 移除 cache 的那一筆（4394 只有 cache 記得）
    cache_minus = {k: v for k, v in P296_CACHE.items() if k != "300"}
    got = archive.scan_candidates(P296_ITEMS, cache_minus, archive.ARCHIVES_THREAD)
    check("#296 AC-3① 移除 cache 的 4394 → 集合恰少 4394，其餘不變",
          got == [i for i in P296_WANT if i != 4394],
          f"實得 {got!r}；差集 {sorted(set(base) - set(got))!r}")

    # ② 移除 archived 標記（3724 只有 archived 式承載）
    items_minus_arch = [(n, b) for n, b in P296_ITEMS if n != "286"]
    got = archive.scan_candidates(items_minus_arch, P296_CACHE,
                                  archive.ARCHIVES_THREAD)
    check("#296 AC-3② 移除 archived 標記 3724 → 集合恰少 3724，其餘不變",
          got == [i for i in P296_WANT if i != 3724],
          f"實得 {got!r}；差集 {sorted(set(base) - set(got))!r}")

    # ③ 移除 topic 標記（4100 只有 topic 式承載、且不在 cache）
    items_minus_topic = [(n, P296_F_BAD_NOTOPIC if n == "295" else b)
                         for n, b in P296_ITEMS]
    got = archive.scan_candidates(items_minus_topic, P296_CACHE,
                                  archive.ARCHIVES_THREAD)
    check("#296 AC-3③ 移除 topic 標記 4100 → 集合恰少 4100，其餘不變",
          got == [i for i in P296_WANT if i != 4100],
          f"實得 {got!r}；差集 {sorted(set(base) - set(got))!r}")

    # ④ archives 來源亦有貢獻（261 無 issue、不會有標記）
    got = archive.scan_candidates(P296_ITEMS, P296_CACHE, None)
    check("#296 AC-3④ archives_thread=None → 集合恰少 261，其餘不變",
          got == [i for i in P296_WANT if i != 261],
          f"實得 {got!r}；差集 {sorted(set(base) - set(got))!r}")

    # cache 的補位語意：3054 的 topic 標記不見了，但 cache 記得 → 仍在集合
    # （`#285` ⑤-c：`ensure` 建了 topic 而寫回 forge 失敗的單只有 cache 記得）
    items_no_3054 = [(n, P287_F_NONE if n == "285" else b) for n, b in P296_ITEMS]
    got = archive.scan_candidates(items_no_3054, P296_CACHE,
                                  archive.ARCHIVES_THREAD)
    check("#296 AC-3 cache 的補位：forge 標記消失但 cache 記得 → 3054 仍在集合",
          got == P296_WANT, f"實得 {got!r}")
    check("#296 AC-3 同一情形若拿掉 cache 來源就漏掉 3054（cache 不可省的證據）",
          archive.scan_candidates(items_no_3054, {}, archive.ARCHIVES_THREAD)
          == [i for i in P296_WANT if i not in (3054, 4394)],
          repr(archive.scan_candidates(items_no_3054, {},
                                       archive.ARCHIVES_THREAD)))

    # 來源分解與聯集一致（`AC-5` 那一行的數字來源）
    src = archive.scan_sources(P296_ITEMS, P296_CACHE, archive.ARCHIVES_THREAD)
    check("#296 AC-5 scan_sources 的 all 與 scan_candidates 逐一相等",
          src["all"] == base, f"{src!r}")
    check("#296 AC-5 三欄分解正確：標記 4 ／ cache 2 ／ archives 1",
          src["marks"] == [3054, 3363, 3724, 4100]
          and src["cache"] == [3054, 4394] and src["archives"] == [261],
          f"{src!r}")
    check("#296 AC-5 分解之和 > 聯集大小（3054 重複）→ 去重確實發生",
          len(src["marks"]) + len(src["cache"]) + len(src["archives"])
          > len(src["all"]) == 6,
          f"4+2+1=7 vs 聯集 {len(src['all'])}")


@case("#296 AC-4 full=True 的集合與 range(2, hi) 逐一相等（零 API）")
def _p296_ac4():
    for H in (400, 450, 3774, 4442):
        got = archive.scan_candidates([], {}, None, full=True, hi=H)
        check(f"#296 AC-4 hi={H}：scan_candidates(full=True) == list(range(2, {H}))",
              got == list(range(2, H)),
              f"len={len(got)} 期望 {H - 2}；首尾={got[:1]!r}…{got[-1:]!r}")
    # `--full` 是「全區間」：給了 items／cache 也不改變結果（＝ `#287` 的舊行為）
    check("#296 AC-4 full=True 時 items／cache 不參與（舊行為一字不變）",
          archive.scan_candidates(P296_ITEMS, P296_CACHE, archive.ARCHIVES_THREAD,
                                  full=True, hi=450) == list(range(2, 450)))
    # hi 未給 → 明確錯誤，不靜默猜一個上界
    raised = False
    try:
        archive.scan_candidates(P296_ITEMS, P296_CACHE, 261, full=True)
    except ValueError:
        raised = True
    check("#296 AC-4 full=True 而 hi=None → ValueError（不靜默猜上界）", raised)
    # 未達成候選：舊實作在**預設**模式也走 range(2, hi) → 4442 個
    check("#296 AC-4 未達成候選：#287 的預設模式探 4442 個（本單降為 6 個 fixture 候選）",
          len(archive.scan_candidates([], {}, None, full=True, hi=4442)) == 4440
          and len(archive.scan_candidates(P296_ITEMS, P296_CACHE,
                                          archive.ARCHIVES_THREAD)) == 6,
          "全區間 4440 vs 候選 6 —— 同一 fixture 下的成本差")


def _p296_run_cmd_scan(items, cache_obj, *, full, archives=261):
    """以假 `api`／假 `_forge_scan_items`／假 CACHE 跑 `cmd_scan`，回 (stdout, stderr)。

    零 Telegram API、零 `gh`（`AC-5` 明文要求以假 `api` 攔截驗輸出字面）。
    """
    import contextlib
    import io

    with tempfile.TemporaryDirectory() as td:
        cache = Path(td) / "devflow-topics.json"
        if cache_obj is not None:
            cache.write_text(cache_obj if isinstance(cache_obj, str)
                             else json.dumps(cache_obj, ensure_ascii=False))
        orig = (archive.CACHE, archive.api, archive._forge_scan_items,
                archive.ARCHIVES_THREAD)
        archive.CACHE = cache
        archive.api = lambda *a, **kw: {"ok": False, "description": ""}
        archive._forge_scan_items = (items if callable(items)
                                     else (lambda *a, **kw: list(items)))
        archive.ARCHIVES_THREAD = archives
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                archive.cmd_scan(argparse.Namespace(prune=False, full=full))
        finally:
            (archive.CACHE, archive.api, archive._forge_scan_items,
             archive.ARCHIVES_THREAD) = orig
    return out.getvalue(), err.getvalue()


@case("#296 AC-5 預設模式印出候選量與三來源分解；--full 印出上界那行")
def _p296_ac5():
    out, _err = _p296_run_cmd_scan(P296_ITEMS, P296_CACHE, full=False)
    want = "（候選 6 個：forge 標記 4 ／ cache 2 ／ archives 1；探測 6 個 thread）"
    check("#296 AC-5 預設模式的輸出字面逐字相等", want in out,
          f"期望字面：{want}\n--- 實際輸出 ---\n{out}")
    check("#296 AC-5 預設模式**不**印上界那行（上界不再等於探活集合）",
          "上界 hi=" not in out, out)
    check("#296 AC-5 預設模式的宣稱字面為「本 kit 管理過的」，不是「群組實際」",
          "本 kit 管理過的 topic（" in out and "群組實際 topic（" not in out, out)

    full_out, _err = _p296_run_cmd_scan(P296_ITEMS, P296_CACHE, full=True)
    want_full = "（上界 hi=4150，由 forge 的分區標記推出；探測 range(2, 4150)）"
    check("#296 AC-5 --full 印出現行那行（字面與 #287 相同，hi=4100+50）",
          want_full in full_out,
          f"期望字面：{want_full}\n--- 實際輸出 ---\n{full_out[:600]}")
    check("#296 AC-5 --full 的宣稱字面維持「群組實際」",
          "群組實際 topic（" in full_out, full_out[:600])
    check("#296 AC-5 --full 不印候選分解那行（兩種模式的宣稱不混用）",
          "（候選 " not in full_out, full_out[:600])

    # 三來源皆空 → 不得靜默當成「群組沒有 topic」
    zero_out, _err = _p296_run_cmd_scan([("999", P287_F_NONE)], {},
                                        full=False, archives=None)
    check("#296 AC-2／AC-5 候選 0 時印出「候選 0 個」",
          "（候選 0 個：forge 標記 0 ／ cache 0 ／ archives 0；探測 0 個 thread）"
          in zero_out, zero_out)
    check("#296 AC-2／AC-5 候選 0 時明說沒探測任何 thread（不靜默）",
          "候選 0" in zero_out and "沒有探測任何 thread" in zero_out, zero_out)
    check("#296 AC-2／AC-5 候選 0 時提示 --full，且不宣稱群組沒有 topic",
          "`scan --full`" in zero_out
          and "這不代表群組沒有 topic" in zero_out, zero_out)

    # cache 損壞／不存在：候選少掉 cache 來源，但 scan 不停擺（prune 語意不動）
    broken, err = _p296_run_cmd_scan(P296_ITEMS, "{not json at all", full=False)
    check("#296 AC-5 cache 損壞 → 候選不計 cache 來源，scan 仍跑完",
          "（候選 5 個：forge 標記 4 ／ cache 0 ／ archives 1；探測 5 個 thread）"
          in broken, f"--- stdout ---\n{broken}--- stderr ---\n{err}")
    check("#296 AC-5 cache 損壞時 stderr 有警告（不靜默）",
          "cache 無法解析" in err, err)
    missing, _err = _p296_run_cmd_scan(P296_ITEMS, None, full=False)
    check("#296 AC-5 cache 不存在 → 同樣視為 {}（候選 5 個）",
          "（候選 5 個：forge 標記 4 ／ cache 0 ／ archives 1；探測 5 個 thread）"
          in missing, missing)

    # cache 過期項那段語意不動（`#296` 射程外）：fake api 全失敗 → 兩筆都算過期
    check("#296 預設模式仍報 cache 過期項（prune 語意不動）",
          "cache 過期項（2）" in out and "（加 --prune 可清除）" in out, out)
    check("#296 cache 過期項列出的是 cache 的兩筆（#300 → 4394、#285 → 3054）",
          "#300 → thread 4394" in out and "#285 → thread 3054" in out, out)

    # forge 不可用 → items 視為 []，stderr 警告，不停擺
    def _forge_down(*_a, **_kw):
        raise RuntimeError("gh 不可用")

    down, err2 = _p296_run_cmd_scan(_forge_down, {}, full=False)
    check("#296 AC-5 forge 不可用 → 候選只剩 archives，scan 不停擺",
          "（候選 1 個：forge 標記 0 ／ cache 0 ／ archives 1；探測 1 個 thread）"
          in down, f"--- stdout ---\n{down}--- stderr ---\n{err2}")
    check("#296 AC-5 forge 不可用時 stderr 警告（照現行 try/except 風格）",
          "無法從 forge 取 issue body" in err2 and "RuntimeError" in err2, err2)
    # `--full` 路徑的 forge 不可用：退回寫死地板（`#287` 的行為一字不變）
    full_down, err3 = _p296_run_cmd_scan(_forge_down, {}, full=True)
    check("#296 AC-5 --full 且 forge 不可用 → 退回寫死值 400（#287 行為不變）",
          f"（上界 hi={archive.SCAN_HI_FLOOR}，由 forge 的分區標記推出；"
          f"探測 range(2, {archive.SCAN_HI_FLOOR})）" in full_down,
          f"--- stdout ---\n{full_down[:400]}--- stderr ---\n{err3}")


@case("#296 AC-1 cmd_scan 只呼叫 scan_candidates，不自算 id 集合")
def _p296_ac1_cmd_scan():
    names = set(archive.cmd_scan.__code__.co_names)
    check("#296 AC-1 cmd_scan 呼叫 scan_candidates／scan_sources",
          {"scan_candidates", "scan_sources"} <= names, f"{sorted(names)!r}")
    check("#296 AC-1 cmd_scan 不自備標記解析（不引用 _marker、不引用 re）",
          not ({"_marker", "re", "scan_topic", "scan_archived"} & names),
          f"{sorted(names)!r}")
    seg = ARCHIVE_SRC.split("def cmd_scan(")[1].split("\ndef ")[0]
    check("#296 AC-1 cmd_scan 的探活迴圈餵 targets（不是 range(2, hi)）",
          "pool.map(probe, targets)" in seg
          and "pool.map(probe, range(" not in seg, seg)
    check("#296 AC-1 cmd_scan 以 getattr(args, \"full\", False) 讀旗標"
          "（既有測試以 Namespace(prune=False) 呼叫）",
          'getattr(args, "full", False)' in seg, seg)
    check("#296 AC-1 --full 路徑仍呼叫 scan_upper_bound（故它不是死碼）",
          "scan_upper_bound" in names and "scan_upper_bound(items" in seg, seg)

    # 宣稱字面的分化（usage 行 ＋ argparse help）
    check("#296 usage 行分化：預設＝本 kit 管理過的、--full＝群組實際存在的",
          "scan                    掃描**本 kit 管理過的** topic" in ARCHIVE_SRC
          and "scan --full             掃描**群組實際存在的** topic" in ARCHIVE_SRC,
          ARCHIVE_SRC[:1400])
    main_src = ARCHIVE_SRC.split("def main(")[1]
    check("#296 argparse：scan 的 help 改為「掃描本 kit 管理過的 topic」",
          'add_parser("scan", help="掃描本 kit 管理過的 topic' in main_src,
          "\n".join(ln for ln in main_src.splitlines() if "add_parser(\"scan\"" in ln))
    check("#296 argparse：--full 旗標存在且 help 寫明是全區間與其成本",
          '"--full"' in main_src and "群組實際存在的 topic" in main_src
          and "16.5 分鐘" in main_src,
          "\n".join(ln for ln in main_src.splitlines() if "full" in ln))
    check("#296 argparse：--prune 仍在（prune 語意不動）",
          '"--prune"' in main_src, main_src[:400])
    # CLI 層確實收 --full（不是只有 help 寫著）
    r = subprocess.run([PY, str(SCRIPTS / "devflow_archive.py"), "scan", "--help"],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL,
                       timeout=60, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    check("#296 CLI `scan --help` rc=0 且列出 --full",
          r.returncode == 0 and "--full" in r.stdout,
          f"rc={r.returncode}\n{r.stdout}{r.stderr}")


@case("#296 AC-7 射程：scan_upper_bound／_forge_scan_items 的 AST 與 base 逐一相同")
def _p296_ac7():
    import ast
    old = subprocess.run(
        ["git", "show", "1f4368d:devflow/channels/scripts/telegram/devflow_archive.py"],
        capture_output=True, text=True, cwd=REPO).stdout
    check("#296 AC-7 取得 base（1f4368d）的原檔", bool(old.strip()), "git show 無輸出")
    if not old.strip():
        return

    def funcs(src: str) -> dict:
        return {n.name: ast.dump(n) for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef)}

    o, n = funcs(old), funcs(ARCHIVE_SRC)
    for name in ("scan_upper_bound", "_forge_scan_items"):
        check(f"#296 AC-7 {name} 的 AST 與 base 逐一相同（不動上界來源的機械證明）",
              name in o and name in n and o[name] == n[name],
              f"base 有={name in o} 本單有={name in n}")
    check("#296 AC-7 既有函式一個都沒被移除",
          not (o.keys() - n.keys()), f"{sorted(o.keys() - n.keys())!r}")
    changed = sorted(k for k in o.keys() & n.keys() if o[k] != n[k])
    check("#296 AC-7 相對 base 改變的函式恰為 cmd_scan ＋ main（write scope 之內）",
          changed == ["cmd_scan", "main"], f"改變的函式: {changed!r}")
    added = sorted(n.keys() - o.keys())
    check("#296 AC-7 scan_candidates 在新增集合內（故不落在 o.keys() & n.keys()）",
          "scan_candidates" in added, f"新增: {added!r}")
    check("#296 AC-7 新增的頂層函式恰為本單宣告的三個",
          added == ["_scan_read_cache", "scan_candidates", "scan_sources"],
          f"新增: {added!r}")
    # 上界的兩個常數亦不動（來源不只是函式）
    check("#296 AC-7 SCAN_HI_FLOOR／SCAN_HI_MARGIN 的字面與 base 相同",
          "SCAN_HI_FLOOR = 400" in old and "SCAN_HI_FLOOR = 400" in ARCHIVE_SRC
          and "SCAN_HI_MARGIN = 50" in old
          and "SCAN_HI_MARGIN = 50" in ARCHIVE_SRC)
    check("#296 AC-7 上界推導未退回以 cache 為來源",
          "CACHE" not in set(archive.scan_upper_bound.__code__.co_names),
          f"{sorted(archive.scan_upper_bound.__code__.co_names)!r}")


@case("#296 AC-9 devflow/VERSION 嚴格大於 0.15.7.0（#296 進 b 位至 0.16.0.0 之後的下界）")
def _p296_ac9():
    raw = (REPO / "devflow" / "VERSION").read_text().strip()
    # `#304` 改法：原斷言寫死 `== "0.16.0.0"`，而 `#296` 合併後的**每一次**進位都會
    # 讓它假 FAIL 一次（本單進 c 位至 `0.16.1.0` 即第一次）。這與 `#287` `AC-8` 治本
    # 掉的那條同形（見 `:1593` 的註解：「程式持有的假設在狀態變動後失效」），故照同一
    # 個模式改成「合四碼形狀 ＋ **嚴格大於下界**」。
    # 下界取 `0.16.0.0`——它就是 `#296` 當時的期望值，故 `#296` 的宣稱（VERSION 已達
    # `0.16.0.0`）仍被守住，只是不再禁止後續單進位。本單自己的等值斷言在 `AC-10`。
    check("#296 AC-9 形狀合 V1 的四碼", bool(VERSION_SHAPE.fullmatch(raw)), repr(raw))
    ok, why = _version_gt(raw, "0.15.7.0")
    check("#296 AC-9 嚴格大於前一單（#300）的 0.15.7.0", ok, f"{raw!r}：{why}")
    ok2, why2 = _version_gt(raw, "0.15.7.0")
    check("#296 AC-9 已達 #296 的 0.16.0.0（≥，本單之後由 #304 AC-10 定等值）",
          ok2 and tuple(int(x) for x in raw.split(".")) >= (0, 16, 0, 0),
          f"{raw!r}：{why2}")


# ── #304 探活的寫入副作用：三態分支、還原失敗回報、射程 ─────────────────────
# 本族全部**零 Telegram API**：`api` 被換成記錄呼叫序列的樁。
#
# ⚠ 斷言為何同時驗「回傳值」與「API 呼叫序列」（`AC-2`）：缺陷版實作在
# `TOPIC_NOT_MODIFIED` 那一支也回 `True`（它 reopen 完才回 True），**只驗回傳值的
# 斷言在修正前後同樣 PASS**，零鑑別力。有鑑別力的是「呼叫序列不含 reopen」。
P304_BASE = "11e5c13"           # 本單的 base（＝ origin/main，`#296` 合併後）

# 真 API 的字面（`#304` 誘餌分區 thread 4863 與 `#296` 的 `--full` 那輪實測形態）
P304_INVALID = {"ok": False, "description": "Bad Request: TOPIC_ID_INVALID"}
P304_NOT_MOD = {"ok": False, "description": "Bad Request: TOPIC_NOT_MODIFIED"}
P304_OK = {"ok": True, "result": True}
P304_REOPEN_FAIL_DESC = "Bad Request: TOPIC_ID_INVALID (reopen 在尾延遲下 timeout)"
P304_REOPEN_FAIL = {"ok": False, "description": P304_REOPEN_FAIL_DESC}


def _p304_alive(responses, thread_id=4863, mod=None):
    """以 `api` 樁跑 `_alive`，回 `(回傳值, API 呼叫序列, stderr)`。

    `mod` 可指定別的模組物件（用來對 base 的實作跑同一組斷言，證明有鑑別力）。
    """
    import contextlib
    import io

    target = mod or topic
    calls = []
    # 未在 `responses` 內的呼叫**不 raise**：缺陷版實作會對 `TOPIC_NOT_MODIFIED`
    # 那支多發一次 reopen，raise 會讓整個子測試以「未預期例外」收場、後面的斷言跑不到，
    # 看不出是哪一條在擋。回一個 `ok: false` 讓那一條斷言自己 FAIL 得明確。
    unexpected = {"ok": False, "description": "stub: 未預期的 API 呼叫"}

    def fake_api(method, **kw):
        calls.append(method)
        return responses.get(method, unexpected)

    orig = target.api
    target.api = fake_api
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            got = target._alive(thread_id)
    finally:
        target.api = orig
    return got, calls, err.getvalue()


@case("#304 AC-1／AC-2／AC-4 _alive 的四支：回傳值 ＋ API 呼叫序列（零 API）")
def _p304_alive_states():
    # ① 不存在 → 不動、回 False
    got, calls, err = _p304_alive({"closeForumTopic": P304_INVALID})
    check("#304 AC-4① TOPIC_ID_INVALID → 回 False",
          got is False, f"實得 {got!r}")
    check("#304 AC-4① TOPIC_ID_INVALID → 呼叫序列僅 closeForumTopic（不 reopen 不存在的分區）",
          calls == ["closeForumTopic"], f"實際序列 {calls!r}")

    # ② 原本 closed（本呼叫沒改到它）→ **不動**、回 True ← 本單的核心反例
    got, calls, err = _p304_alive({"closeForumTopic": P304_NOT_MOD})
    check("#304 AC-2 TOPIC_NOT_MODIFIED → 回 True（分區存在）",
          got is True, f"實得 {got!r}")
    check("#304 AC-2 TOPIC_NOT_MODIFIED → **呼叫序列不含 reopenForumTopic**"
          "（刻意關閉的分區探活後仍為 closed）",
          calls == ["closeForumTopic"] and "reopenForumTopic" not in calls,
          f"實際序列 {calls!r}")
    check("#304 AC-2 TOPIC_NOT_MODIFIED → 不印警示（沒有任何狀態需要還原）",
          err == "", repr(err))

    # ③ 原本 open（本呼叫剛關了它）→ reopen 還原、回 True
    got, calls, err = _p304_alive({"closeForumTopic": P304_OK,
                                   "reopenForumTopic": P304_OK})
    check("#304 AC-4③ ok: true → 回 True", got is True, f"實得 {got!r}")
    check("#304 AC-4③ ok: true → 呼叫序列恰為 close 後 reopen（還原本呼叫改掉的狀態）",
          calls == ["closeForumTopic", "reopenForumTopic"], f"實際序列 {calls!r}")
    check("#304 AC-4③ 還原成功時不印警示", err == "", repr(err))

    # ④ 還原失敗 → 回 True、警示含 thread id 與 description 字面、**不重試**
    got, calls, err = _p304_alive({"closeForumTopic": P304_OK,
                                   "reopenForumTopic": P304_REOPEN_FAIL})
    check("#304 AC-3／AC-4④ 還原失敗仍回 True（分區存在是已知事實）",
          got is True, f"實得 {got!r}")
    check("#304 AC-3 還原失敗**不重試**（reopenForumTopic 恰一次）",
          calls == ["closeForumTopic", "reopenForumTopic"], f"實際序列 {calls!r}")
    check("#304 AC-3(a) 警示含 thread id（4863）與 API 的 description 字面",
          "4863" in err and P304_REOPEN_FAIL_DESC in err, repr(err))
    check("#304 AC-3(a) 警示明說狀態未還原（不只是「有印東西」）",
          "未還原" in err and "closed" in err, repr(err))
    check("#304 AC-3(a) 警示為單行（可定位、不是多行堆疊）",
          len([ln for ln in err.strip().splitlines() if ln.strip()]) == 1, repr(err))


@case("#304 AC-1 _alive 的 docstring 前提已修正（不再寫無條件的「回到原點」保證）")
def _p304_alive_doc():
    import ast
    doc = topic._alive.__doc__ or ""
    base_src = subprocess.run(
        ["git", "show",
         f"{P304_BASE}:devflow/channels/scripts/telegram/devflow_topic.py"],
        capture_output=True, text=True, cwd=REPO).stdout
    stale = "一關一開後狀態回到原點"
    check("#304 AC-1 docstring 載三態的判準字面（TOPIC_NOT_MODIFIED／TOPIC_ID_INVALID）",
          "TOPIC_NOT_MODIFIED" in doc and "TOPIC_ID_INVALID" in doc, doc[:400])
    check("#304 AC-1 docstring 寫明只對原本 open 的分區還原",
          "open" in doc and "還原" in doc, doc[:400])
    # 鑑別力：base 的 docstring **有**那句無條件保證，本單的**沒有**。
    check(f"#304 AC-1 鑑別力：base（{P304_BASE}）的 docstring 確實含「{stale}」",
          stale in base_src, "git show 無輸出或字面不符")
    check(f"#304 AC-1 本單的 docstring 不再出現「{stale}」"
          "（它只在原本 open 時成立）", stale not in doc, doc[:400])
    check("#304 AC-3 docstring 寫明還原失敗只回報不重試",
          "不重試" in doc, doc[:600])

    # ── `R1` 第 1 輪 BLOCK 1：禁同義的錯誤通則，不只禁 base 的精確舊字串 ──────
    # 第 1 輪的斷言只擋 `stale`（base 的原句），於是修正稿自己寫出的
    # 「現在『狀態回到原點』對三態都成立」通則**穿過了全部斷言**——而該通則與同函式
    # 的還原失敗分支矛盾（reopen 失敗時狀態停在 closed，並未回到原點）。判準因此改為
    # 一正一反兩條：**禁**「對三態都成立」、**要求**「只有 reopen 成功才回到原點」。
    #
    # 以 `ast.get_docstring` 取（不是 `__doc__`）：前者讀的是**原始碼**的 docstring
    # 節點，不受 `-OO`／快取影響，且與 manager 的複驗指令同一取法。
    # 去空白後比對：docstring 會因折行而在字串中間插入換行與縮排，
    # 「只有 reopen 成功才回到原點」在原文裡跨行（`**只有 reopen 成功才回到原點**`
    # 被 `——` 斷開），不去空白的 `in` 會漏判。
    def _doc_norm(src: str, fname: str = "_alive") -> str:
        fn = [n for n in ast.parse(src).body
              if isinstance(n, ast.FunctionDef) and n.name == fname][0]
        return re.sub(r"\s+", "", ast.get_docstring(fn) or "")

    def _doc_ok(d: str) -> bool:
        """BLOCK 1 的判準本體——唯一的判定函式，正反兩個 fixture 共用。"""
        return "對三態都成立" not in d and "只有reopen成功" in d

    cur = _doc_norm((SCRIPTS / "devflow_topic.py").read_text())
    check("#304 AC-1／BLOCK 1 docstring 不含錯誤通則「對三態都成立」"
          "（它與還原失敗那支矛盾）", "對三態都成立" not in cur, cur[:300])
    check("#304 AC-1／BLOCK 1 docstring 逐字含「只有 reopen 成功才回到原點」"
          "（收窄的前提，非通則）", "只有reopen成功" in cur, cur[:300])
    check("#304 AC-1／BLOCK 1 現行 docstring 過判準（與 manager 複驗指令同一取法）",
          _doc_ok(cur), cur[:300])

    # 鑑別力：同一個判準對三份構造的 docstring 須給出 T 預跑的答案。
    # ① 第 1 輪被 BLOCK 的那份原文（通則版）→ 必須 FAIL
    # ② 只刪通則、沒補收窄句 → 仍 FAIL（禁止項不是唯一條件）
    # ③ base 的原句（`stale`）→ FAIL（它連三態都沒寫）
    P304_DOC_GENERAL = ('''"""探活。

        現在「狀態回到原點」對三態都成立，代價是多一個分支。
        """''')
    P304_DOC_SILENT = ('''"""探活。

        依 closeForumTopic 的回傳分三態，只在本呼叫改到狀態時還原。
        """''')
    P304_DOC_BASE = ('''"""探活。

        一關一開後狀態回到原點，且不碰名稱。
        """''')
    for fixture, want, label in (
            (P304_DOC_GENERAL, False,
             "第 1 輪被 BLOCK 的通則版（含「對三態都成立」）→ FAIL"),
            (P304_DOC_SILENT, False,
             "只刪通則、未補「只有 reopen 成功才回到原點」→ FAIL"),
            (P304_DOC_BASE, False, "base 的原句（無條件保證）→ FAIL")):
        got = _doc_ok(_doc_norm(f"def _alive(t):\n    {fixture}\n"))
        check(f"#304 AC-1／BLOCK 1 鑑別力：{label}", got is want,
              f"實得 {got}（期望 {want}）")

    # 反向鑑別力：修正稿的那段話單獨餵進同一判準須 PASS
    # ——證明上面三個 FAIL 不是因為判準恆假。
    P304_DOC_FIXED = ('''"""探活。

        `ok: true` 那支是唯一會改到狀態的路徑，而**只有 reopen 成功才回到原點**
        ——reopen 失敗時狀態**停在 closed**，只回報、不重試。
        """''')
    check("#304 AC-1／BLOCK 1 鑑別力：修正稿的收窄句 → PASS（判準非恆假）",
          _doc_ok(_doc_norm(f"def _alive(t):\n    {P304_DOC_FIXED}\n")) is True)

    # 與 reopen 失敗那支的一致性：docstring 既然宣稱「失敗時停在 closed」，
    # 實作就必須真的在那支不重試（上面 `_p304_alive_states` 的 ④ 已驗呼叫序列）。
    # 這一條把文件宣稱與該實測綁在一起——文件改了而實作沒改會被這裡攔下。
    _got, _calls, _err = _p304_alive({"closeForumTopic": P304_OK,
                                      "reopenForumTopic": P304_REOPEN_FAIL})
    check("#304 AC-1／BLOCK 1 docstring 宣稱的例外與實作一致："
          "reopen 失敗時狀態停在 closed（不重試）且有回報",
          _calls == ["closeForumTopic", "reopenForumTopic"]
          and "未還原" in _err and "closed" in _err,
          f"序列 {_calls!r} | stderr {_err!r}")


def _p304_run_cmd_scan(per_tid, cache_obj, *, archives=None):
    """以 `api` 樁跑 `cmd_scan`，回 `(stdout, stderr, {tid: 該 tid 的呼叫序列})`。

    `per_tid` ＝ `{tid: {method: 回傳}}`。零 Telegram API、零 `gh`（候選與
    `issue_meta` 全部由自造 cache 餵），故 `probe` 的四支可逐一驗（`AC-4`）。
    """
    import contextlib
    import io

    calls: dict[int, list[str]] = {}
    with tempfile.TemporaryDirectory() as td:
        cache = Path(td) / "devflow-topics.json"
        cache.write_text(json.dumps(cache_obj, ensure_ascii=False))
        orig = (archive.CACHE, archive.api, archive._forge_scan_items,
                archive.ARCHIVES_THREAD)

        def fake_api(method, **kw):
            tid = kw.get("message_thread_id")
            calls.setdefault(tid, []).append(method)
            return per_tid.get(tid, {}).get(method, P304_INVALID)

        archive.CACHE = cache
        archive.api = fake_api
        archive._forge_scan_items = lambda *a, **kw: []
        archive.ARCHIVES_THREAD = archives
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                archive.cmd_scan(argparse.Namespace(prune=False, full=False))
        finally:
            (archive.CACHE, archive.api, archive._forge_scan_items,
             archive.ARCHIVES_THREAD) = orig
    return out.getvalue(), err.getvalue(), calls


# 四個 thread 各對應 probe 的一支；id 取 9001-9004（本群組不存在，純樁）
P304_SCAN_CACHE = {
    "901": {"thread_id": 9001, "state": "open", "title": "單 不存在"},
    "902": {"thread_id": 9002, "state": "open", "title": "單 closed"},
    "903": {"thread_id": 9003, "state": "open", "title": "單 open"},
    "904": {"thread_id": 9004, "state": "open", "title": "單 還原失敗"},
}
P304_SCAN_API = {
    9001: {"closeForumTopic": P304_INVALID},
    9002: {"closeForumTopic": P304_NOT_MOD},
    9003: {"closeForumTopic": P304_OK, "reopenForumTopic": P304_OK},
    9004: {"closeForumTopic": P304_OK, "reopenForumTopic": P304_REOPEN_FAIL},
}


@case("#304 AC-3／AC-4 probe（cmd_scan 內嵌）的四支：呼叫序列 ＋ 結果那一行（零 API）")
def _p304_probe_states():
    out, err, calls = _p304_run_cmd_scan(P304_SCAN_API, P304_SCAN_CACHE)
    ctx = f"--- stdout ---\n{out}--- stderr ---\n{err}--- calls ---\n{calls!r}"

    # 四支的呼叫序列（逐 tid 比，執行緒池的完成順序不影響）
    check("#304 AC-4① probe 不存在 → 僅 closeForumTopic",
          calls.get(9001) == ["closeForumTopic"], ctx)
    check("#304 AC-2／AC-4② probe closed → 僅 closeForumTopic"
          "（**不含 reopenForumTopic**）",
          calls.get(9002) == ["closeForumTopic"], ctx)
    check("#304 AC-4③ probe open → close 後 reopen 還原",
          calls.get(9003) == ["closeForumTopic", "reopenForumTopic"], ctx)
    check("#304 AC-3／AC-4④ probe 還原失敗 → reopen 恰一次（不重試）",
          calls.get(9004) == ["closeForumTopic", "reopenForumTopic"], ctx)

    # 回傳值（經 cmd_scan 的 stdout 觀測：探不到的不列入結果區、closed／open 如實標）
    # ⚠ 不可寫成 `"thread 9001" not in out`：探不到的 thread 會以 cache 過期項的面貌
    # 出現在**另一區**（`  #901 → thread 9001`），那是既有語意（`#296` 射程外）。
    results = out.split("本 kit 管理過的 topic")[1].split("\ncache 過期項")[0]
    check("#304 AC-4 probe 的回傳值：9001 探不到故不在結果區內",
          "thread 9001" not in results, ctx)
    check("#304 AC-4 9001 仍以 cache 過期項的面貌被報出（既有語意不動）",
          "#901 → thread 9001" in out, ctx)
    check("#304 AC-4② probe closed → 結果那一行標 closed",
          "thread 9002  closed  #902 單 closed" in results, ctx)
    check("#304 AC-4③ probe open → 結果那一行標 open 且無未還原標記",
          "thread 9003  open    #903 單 open\n" in results, ctx)

    # `AC-3`(b)：未還原的狀態印進**該 thread 的結果那一行**
    want = (f"thread 9004  open    #904 單 還原失敗 "
            f"⚠ 狀態未還原（仍為 closed）：{P304_REOPEN_FAIL_DESC}")
    check("#304 AC-3(b) cmd_scan 把未還原狀態印進該 thread 的結果那一行"
          "（含 description 字面）", want in out, f"期望字面：{want}\n{ctx}")
    check("#304 AC-3(b) 未還原的標記只落在該 thread 那一行，不汙染其他行",
          out.count("狀態未還原") == 1, ctx)

    # `AC-3`(a)：stderr 亦有一行可定位的警示（含 thread id 與 description 字面）
    check("#304 AC-3(a) probe 的 stderr 警示含 thread id 與 description 字面",
          "thread 9004" in err and P304_REOPEN_FAIL_DESC in err, ctx)
    check("#304 AC-3(a) probe 的 stderr 警示只對還原失敗那一個 thread 發出",
          err.count("狀態未還原") == 1, ctx)
    check("#304 AC-3 還原成功的 9003 不留任何警示",
          "9003" not in err, ctx)

    # 鑑別力的對照：缺陷版實作會對 9002 發 reopen，上面 `calls.get(9002)` 那條會轉 FAIL
    check("#304 AC-2 鑑別力記錄：本組斷言驗的是呼叫序列，"
          "只驗回傳值的版本在缺陷實作下同樣 PASS（故不可只驗回傳值）",
          "reopenForumTopic" not in calls.get(9002, []), ctx)


@case("#304 AC-5 射程：devflow_archive.py 的掃描函式 AST 與 base 逐一相同")
def _p304_scope_archive():
    import ast
    old = subprocess.run(
        ["git", "show",
         f"{P304_BASE}:devflow/channels/scripts/telegram/devflow_archive.py"],
        capture_output=True, text=True, cwd=REPO).stdout
    check(f"#304 AC-5 取得 base（{P304_BASE}）的 devflow_archive.py",
          bool(old.strip()), "git show 無輸出")
    if not old.strip():
        return

    def funcs(src: str) -> dict:
        return {n.name: ast.dump(n) for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef)}

    o, n = funcs(old), funcs(ARCHIVE_SRC)
    # `#296` 的成果本單一字不動（候選集合與上界來源）
    for name in ("scan_upper_bound", "scan_candidates", "_forge_scan_items",
                 "scan_sources"):
        check(f"#304 AC-5 {name} 的 AST 與 base 逐一相同（不動 #296／#287 的成果）",
              name in o and name in n and o[name] == n[name],
              f"base 有={name in o} 本單有={name in n}")
    check("#304 AC-5 devflow_archive.py 既有函式一個都沒被移除",
          not (o.keys() - n.keys()), f"{sorted(o.keys() - n.keys())!r}")
    changed = sorted(k for k in o.keys() & n.keys() if o[k] != n[k])
    # 期望集合**不放寬**：本單只改 `cmd_scan`（內嵌的 `probe` ＋ 結果那一行）。
    # `cmd_scan` 自 `#287` 起已在 `:1577` 那條的期望集合內，本單不必動它。
    check("#304 AC-5 相對 base 改變的函式恰為 cmd_scan（write scope 之內，不含 main）",
          changed == ["cmd_scan"], f"改變的函式: {changed!r}")
    check("#304 AC-5 本單不新增任何頂層函式（不抽共用 helper、不新開 _probe.py）",
          not (n.keys() - o.keys()), f"新增: {sorted(n.keys() - o.keys())!r}")


@case("#304 AC-5 射程：devflow_topic.py 除 _alive 外的頂層函式 AST 與 base 相同")
def _p304_scope_topic():
    import ast
    old = subprocess.run(
        ["git", "show",
         f"{P304_BASE}:devflow/channels/scripts/telegram/devflow_topic.py"],
        capture_output=True, text=True, cwd=REPO).stdout
    check(f"#304 AC-5 取得 base（{P304_BASE}）的 devflow_topic.py",
          bool(old.strip()), "git show 無輸出")
    if not old.strip():
        return

    def funcs(src: str) -> dict:
        return {n.name: ast.dump(n) for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef)}

    o, n = funcs(old), funcs((SCRIPTS / "devflow_topic.py").read_text())
    changed = sorted(k for k in o.keys() & n.keys() if o[k] != n[k])
    check("#304 AC-5 devflow_topic.py 相對 base 改變的函式恰為 _alive",
          changed == ["_alive"], f"改變的函式: {changed!r}")
    for name in ("ensure", "close", "sync", "api", "_from_forge", "_to_forge",
                 "_topic_name", "_cache", "_save"):
        check(f"#304 AC-5 {name} 的 AST 與 base 相同",
              name in o and name in n and o[name] == n[name],
              f"base 有={name in o} 本單有={name in n}")
    check("#304 AC-5 devflow_topic.py 既有函式一個都沒被移除",
          not (o.keys() - n.keys()), f"{sorted(o.keys() - n.keys())!r}")
    check("#304 AC-5 devflow_topic.py 不新增頂層函式（不抽共用 helper）",
          not (n.keys() - o.keys()), f"新增: {sorted(n.keys() - o.keys())!r}")
    # `ensure` 未動，故「呼叫端不依賴 reopen 副作用」在機械層亦可見：
    # 它只讀 `_alive` 的布林回傳（`if tid and _alive(tid)`）。
    check("#304 AC-10 ensure 仍只用 _alive 的布林回傳（不依賴狀態被改變的副作用）",
          "_alive(tid)" in (SCRIPTS / "devflow_topic.py").read_text()
          and o["ensure"] == n["ensure"])


@case("#304 AC-7／AC-8 telegram.md 新增兩格：分區探活（📝）與 scan 探活集合（✅）")
def _p304_telegram_md():
    md = (REPO / "devflow" / "channels" / "telegram.md").read_text()
    rows = [ln for ln in md.splitlines() if ln.startswith("| ")]
    probe_row = [ln for ln in rows if ln.startswith("| 分區探活 |")]
    scan_row = [ln for ln in rows if ln.startswith("| `scan` 探活集合 |")]
    check("#304 AC-7 有恰一格「分區探活」（單行、`|` 分欄）", len(probe_row) == 1,
          f"命中 {len(probe_row)} 行")
    check("#304 AC-8 有恰一格「`scan` 探活集合」", len(scan_row) == 1,
          f"命中 {len(scan_row)} 行")
    if not (probe_row and scan_row):
        return
    pr, sr = probe_row[0], scan_row[0]

    # `AC-7`：三態判準、只對原本 open 還原、還原失敗處置、兩處實作位置、狀態 📝
    for frag, why in (("TOPIC_ID_INVALID", "三態判準之一"),
                      ("TOPIC_NOT_MODIFIED", "三態判準之一"),
                      ("只對原本 open", "只對原本 open 的分區還原"),
                      ("不重試", "還原失敗的處置"),
                      ("`_alive`", "實作位置一"),
                      ("`probe`", "實作位置二"),
                      ("devflow_topic.py", "實作位置一的檔"),
                      ("devflow_archive.py", "實作位置二的檔"),
                      ("administrator", "`R10` 受測環境")):
        check(f"#304 AC-7 分區探活格載「{frag}」（{why}）", frag in pr,
              pr[:200])
    check("#304 AC-7 分區探活格的狀態欄為 📝（R9 子類「驗證未達 ✅」）",
          "| 📝 " in pr and "| ✅ " not in pr and "| ⬜ " not in pr,
          pr[-300:])

    # ── `R1` 第 1 輪 BLOCK 2 ＋ 裁決位第二次升人裁示 A：狀態欄的判準須時間無關 ──
    # 兩輪的病是**同一型**，第二輪才看清：受版控的文字（以及**要求該文字存在的斷言**）
    # 不得宣稱一個會自行變動的狀態——真值取決於何時讀，與 `#303` `AC-3` 同族。
    #
    #   第 1 輪：格子寫「由協調位以自建誘餌分區實跑」「證據：見 `#304` `AC-6` 留言」，
    #            而那則留言當時**不存在** → 記載不是當前事實。
    #   第 2 輪：改成「`AC-6` 由協調位於收尾前執行／該留言尚未出現／待 `AC-6` 留言」，
    #            仍是時間依賴——`AC-6` 跑完之後這些句子就變成假陳述，而**本檔原有四條
    #            斷言正向要求它們存在**，等於把同一型缺陷留在測試裡（實跑 539/543）。
    #            裁示 A：射程擴為 `telegram.md` ＋ 本檔 2 檔，判準改時間無關。
    #            https://github.com/AugustusHsu/agent-devflow/issues/304#issuecomment-6053215354
    #            https://github.com/AugustusHsu/agent-devflow/issues/304#issuecomment-6058727866
    #
    # 判準因此是一禁一要求，兩者都與「何時讀」無關：
    #   (a) **禁用詞**（下列 `P304_MD_BANNED_TIME`，裁示逐字）不得出現於**狀態欄**
    #   (b) **要求穩定的證據把手字面**（`P304_MD_HANDLES`）：留言 id 與兩個誘餌
    #       thread id。它們指向**已發生且可讀回**的紀錄，不隨時間改變真值。
    #
    # ⚠ 判準的作用域是**狀態欄**（` | ` 分欄後的最後一欄），不是整列：值欄描述的是
    # 機制本身（三態判準、處置、實作位置），那裡出現「不重試」這類詞與時間無關，
    # 不在本判準射程。裁示明文如此界定。
    #
    # ⚠ 本段刻意不寫那個第二棒標記的英文字面：`test_relay.py` 的 `#300 AC-2` 斷言
    # **本檔不得含該字面**（它是 `#300` 的射程證明——grammar 沒有上移到共用模組、
    # 本檔零改動）。寫進來會讓那條假 FAIL，那是另一張單的判準，不在本單射程。
    # 下面兩份 fixture 取自 git，已逐一核對不含它。
    P304_MD_BANNED_TIME = ("待", "尚未", "屆時", "合併時", "收尾前")
    # 第一組的前身：第 1 輪那兩個完成式字面。它們同樣是時間依賴（宣稱一件當時還沒
    # 發生的事已完成），故留在禁用清單裡，但主判準是上面那五個詞。
    P304_MD_BANNED_CLAIM = ("見 `#304` `AC-6` 留言", "由協調位以自建誘餌分區實跑")
    P304_MD_HANDLES = ("issuecomment-6052326088", "5034", "5039")

    def _status_col(row: str) -> str:
        """狀態欄 ＝ 該列以 ` | ` 分欄後的最後一欄（裁示的定義）。"""
        return row.split(" | ")[-1]

    def _md_ok(row: str) -> bool:
        """BLOCK 2 的判準本體——現行這格與兩份反例 fixture 共用。

        時間無關：只問「狀態欄有沒有自行變動的宣稱」與「有沒有指向既有紀錄的把手」，
        不問任何「現在是什麼時候」。
        """
        st = _status_col(row)
        return (not any(w in st for w in P304_MD_BANNED_TIME)
                and not any(w in st for w in P304_MD_BANNED_CLAIM)
                and all(h in st for h in P304_MD_HANDLES))

    st_cur = _status_col(pr)
    hit_time = [w for w in P304_MD_BANNED_TIME if w in st_cur]
    check("#304 AC-7／裁示 A(1) 狀態欄不含時間依賴的禁用詞"
          f"（{'／'.join(P304_MD_BANNED_TIME)}）",
          not hit_time, f"命中 {hit_time!r}\n--- 狀態欄 ---\n{st_cur[-600:]}")
    hit_claim = [w for w in P304_MD_BANNED_CLAIM if w in st_cur]
    check("#304 AC-7／裁示 A(1) 狀態欄不含第 1 輪的完成式字面"
          "（宣稱當時尚未發生的事已完成）",
          not hit_claim, f"命中 {hit_claim!r}\n--- 狀態欄 ---\n{st_cur[-600:]}")
    for frag, why in (("issuecomment-6052326088", "AC-6 實測的留言 id"),
                      ("5034", "head 側誘餌 thread（第 4 步 closed）"),
                      ("5039", "base 側誘餌 thread（第 4 步 open，對照組）")):
        check(f"#304 AC-7／裁示 A(2) 狀態欄載穩定的證據把手「{frag}」（{why}）",
              frag in st_cur, st_cur[-600:])
    # `R10` 的受測環境須載程式層那一輪的環境（它與真 API 層是兩套，`R7`）
    for frag, why in (("3.14.7", "程式層的 python 版本"),
                      ("Linux 7.0.0", "程式層的 OS"),
                      ("tests/channels/test_marker.py", "程式層的實跑對象"),
                      ("不打任何 API", "程式層不需權限")):
        check(f"#304 AC-7 受測環境載程式層的「{frag}」（{why}）",
              frag in st_cur, st_cur[-900:])
    # 證據欄引的全是**已發生**的東西：PR #305、issue body 根因段的誘餌 thread 4863
    check("#304 AC-7 證據欄引 PR #305 與 issue body 根因段的誘餌 thread 4863"
          "（兩者皆現存可讀回）",
          "PR #305" in st_cur and "4863" in st_cur and "issue body" in st_cur,
          st_cur[-600:])
    check("#304 AC-7／裁示 A(3) 現行這格過判準", _md_ok(pr), st_cur[-600:])

    # ── 裁示 A(4)：鑑別力——兩個被判不合格的前版原文在新判準下必須 FAIL ─────────
    # 裁示明文「第 4 項是最關鍵的一項」：少了它，新判準可能**恆真**，那只是把一個
    # 有時間依賴的斷言換成一個沒有鑑別力的斷言，不是改善（`R6`）。
    # 兩份 fixture 取 git 的原文而非手抄——手抄會漂移，而「fixture 與受測對象不同步」
    # 正是本族缺陷的另一個形態。各自命中判準的**不同**一支，故兩份都要留：
    #   `0754549` → 五個時間詞全中（第 2 輪的病）
    #   `42fc42d` → 兩個完成式字面全中（第 1 輪的病）
    # 兩者皆缺三個把手。pin 住 sha 的代價與本檔既有的 AST 射程斷言相同（`11e5c13`／
    # `1f4368d`）：該 commit 必須仍可達；取不到時下面第一條 check 會 FAIL 並指出原因。
    P304_MD_PRIOR = (
        ("0754549", P304_MD_BANNED_TIME, "第 2 輪：五個時間依賴的禁用詞"),
        ("42fc42d", P304_MD_BANNED_CLAIM, "第 1 輪：完成式字面"),
    )
    for sha, expect_hit, why in P304_MD_PRIOR:
        old_md = subprocess.run(
            ["git", "show", f"{sha}:devflow/channels/telegram.md"],
            capture_output=True, text=True, cwd=REPO).stdout
        old_rows = [ln for ln in old_md.splitlines()
                    if ln.startswith("| 分區探活 |")]
        if not check(f"#304 AC-7／裁示 A(4) 取得 {sha} 的「分區探活」那一列原文",
                     len(old_rows) == 1,
                     f"命中 {len(old_rows)} 行（git show 無輸出表示該 commit 不可達）"):
            continue
        old_row = old_rows[0]
        old_st = _status_col(old_row)
        hit = [w for w in expect_hit if w in old_st]
        check(f"#304 AC-7／裁示 A(4) {sha} 的狀態欄確實命中{why}"
              "（反例有效，不是空跑）",
              hit == list(expect_hit), f"命中 {hit!r} 期望 {list(expect_hit)!r}")
        check(f"#304 AC-7／裁示 A(4) 鑑別力：{sha} 的原文在新判準下 FAIL",
              _md_ok(old_row) is False, old_st[-400:])
        check(f"#304 AC-7／裁示 A(4) {sha} 的狀態欄缺全部三個證據把手"
              "（故正向那一組亦有鑑別力）",
              not any(h in old_st for h in P304_MD_HANDLES), old_st[-400:])
    # 反向鑑別力：現行這格 PASS ——證明上面那些 FAIL 不是因為判準恆假。
    check("#304 AC-7／裁示 A(4) 鑑別力：現行這格 → PASS（判準非恆假）",
          _md_ok(pr) is True, st_cur[-600:])

    # `AC-8`：兩種宣稱、兩個集合、實測值、差集判準、狀態 ✅、牆鐘不作門檻
    for frag, why in (("標記 ∪ cache ∪ archives", "預設的探活集合"),
                      ("range(2, hi)", "--full 的探活集合"),
                      ("26", "預設實測探活量"),
                      ("36.5s", "預設實測牆鐘"),
                      ("4639", "--full 實測探活量"),
                      ("4641", "--full 的 hi"),
                      ("15m14s", "--full 實測牆鐘"),
                      ("本 kit 管理過的", "預設的宣稱"),
                      ("群組實際存在的", "--full 的宣稱"),
                      ("261, 4591", "兩模式的命中相同"),
                      ("尾延遲", "牆鐘受尾延遲支配"),
                      ("不設上限門檻", "牆鐘不得寫成門檻"),
                      ("issues/296#issuecomment", "證據連結指向 #296 的 AC-6 留言")):
        check(f"#304 AC-8 scan 探活集合格載「{frag}」（{why}）", frag in sr,
              sr[:200])
    check("#304 AC-8 scan 探活集合格的狀態欄為 ✅（#296 有真 API 實跑可引）",
          "| ✅ " in sr, sr[-300:])
    check("#304 AC-8 差集判準三項俱在（full ⊇ 預設、差集全為探活失敗、反向差集空）",
          "⊇" in sr and "差集" in sr and "反向差集" in sr, sr[:400])


@case("#304 AC-10 devflow/VERSION 嚴格大於 0.16.0.0（#304 進 c 位至 0.16.1.0 之後的下界）")
def _p304_version():
    raw = (REPO / "devflow" / "VERSION").read_text().strip()
    # `#306` 改法：原斷言寫死 `== "0.16.1.0"`，而 `#304` 合併後的**每一次**進位都會讓它
    # 假 FAIL 一次（本單進 b 位至 `0.17.0.0` 即第一次）。這與 `:1593` 的 `#287` `AC-8`
    # 治本、`:2911` 的 `#296` `AC-9` 治本同形（「程式持有的假設在狀態變動後失效」），
    # 故照同一個模式改成「合四碼形狀 ＋ **嚴格大於下界**」、不刪整條。
    # 下界取 `0.16.0.0`——它是 `#304` 的 base（`#296` 當時的值），故 `#304` 的宣稱
    # （VERSION 已超過 base）仍被守住，只是不再禁止後續單進位。
    # 本單自己的等值斷言在 `_p306_version`。
    check("#304 AC-10 形狀合 V1 的四碼", bool(VERSION_SHAPE.fullmatch(raw)), repr(raw))
    ok, why = _version_gt(raw, "0.16.0.0")
    check("#304 AC-10 嚴格大於 base（#296）的 0.16.0.0", ok, f"{raw!r}：{why}")
    check("#304 AC-10 已達 #304 的 0.16.1.0（≥，本單之後由 #306 定等值）",
          tuple(int(x) for x in raw.split(".")) >= (0, 16, 1, 0), repr(raw))


# ── #306 人格檔範本（channels/templates/）的靜態斷言 ────────────────────────
# 本族**只讀 repo 內的檔**：範本、`WORKFLOW.md`、`telegram.md`、`channels/README.md`。
# 不讀協調平台的 profile 目錄（那在 repo 外、在 AC 視野外，見 `templates/README.md`
# 的「(c) 的已知上限」），也不讀任何快照目錄——測試的輸入必須與受版控的內容同步。
#
# ⚠ 本族的字面常數為何寫死而不從別處讀：
#   - persona 前言（`P306_PERSONA`）寫死，因為它的來源在 repo 外；從檔案讀會讓測試
#     依賴一個不受版控的輸入。
#   - 共用句（`P306_SHARED`）寫死，因為 `AC-8` 要驗的正是「四份逐字相同且等於這一句」；
#     從範本讀會讓該斷言退化成恆真。
P306_TPL = REPO / "devflow" / "channels" / "templates"
P306_SEATS = ("coordinator", "manager", "reviewer", "implementer")
P306_FILES = P306_SEATS + ("README",)

# `AC-2` 的規則行定義：`^- \`ID\` ` 開頭者，去掉該前綴、空白折疊為單一空格。
P306_RULE_RE = re.compile(r"^- `([A-Z]+[0-9]+)` (.*)$")
P306_WIN = 20                           # 滑動視窗長度（Python len，中英同計）
# `AC-2` 正向：範本內的 ID 引用只認 `` `ID` `` 反引號形式（裸 ID 不算引用）。
P306_ID_RE = re.compile(r"`([A-Z]+[0-9]+)`")

# `AC-2` 正向的必含 ID：**逐檔的現況完整集合**——該範本現在所有的 `` `ID` `` 引用。
# 來源：head `90324c0` 的範本現況，以 `re.findall(P306_ID_RE, …)` 跑一次寫死；範本增刪
# 引用時同步更新本常數。
#
# 為什麼不手選「該引的那幾條」：手選集合只擋得住被選中的那幾個 ID，移除集合外的既有
# 引用（例如 manager 的 `R2`、coordinator 的 `G2`）會被放過。以現況全集為下界，
# **任一既有引用被移除都擋得住**。
#
# 為什麼是 ⊇ 而非 ==：常數是**下界**。範本新增 ID 引用是好事（`AC-2` 的方向正是
# 「凡述及條文可套之處皆以 ID 引用」），等值斷言會讓每次補引用都得先改測試，與該方向
# 相反。反方向（新增引用）刻意不擋。
P306_REQUIRED_IDS: dict[str, set[str]] = {
    "coordinator": {"C5", "CH1", "CH2", "CH3", "G2", "I5", "L1", "M1", "R1"},
    "manager": {"CH1", "I1", "I2", "I5", "I7", "L2", "L3", "R1", "R10", "R11",
                "R12", "R2"},
    "reviewer": {"CH1", "I5", "R1", "R10", "R12", "R5"},
    "implementer": {"CH1", "I1", "I2", "I5", "L3", "R1"},
    "README": {"I5", "I6", "I7"},
}

# `AC-3` 的 locator 多重集合：逐檔現況的 `telegram.md「格名」`／
# `channels/README.md「節名」` 全部命中與其**次數**。鍵為 `(來源檔, 格名或節名)`。
# 來源：head `90324c0` 的範本現況，以同一組正則跑一次寫死；範本增刪引用時同步更新。
#
# 為什麼要帶次數、不只驗「每檔 ≥1」：只驗存在時，移掉某一處 locator、保留敘述與該檔
# 其他引用會被放過（例如 manager 的兩處「子程序退出後的銜接」拔掉一處）。逐鍵 ≥ 的
# 多重集合下界擋得住「任一處 locator 被拔掉」。
#
# 同樣是**下界**而非等值，理由同 `P306_REQUIRED_IDS`。
#
# ⚠ 一處缺漏仍在：`coordinator.md` 另引用了 `telegram.md` 的「第二棒的…行」那一格，
# 其格名含一個英文詞，而 `#300` `AC-2` 的既有斷言（`test_relay.py`）要求本檔**零**該
# 字面；`test_relay.py` 不在本單的 write scope 內，故本常數不收那一鍵（連註解也不能
# 寫出該詞）。該鍵的下界已由 `_p306_ac3_omitted_locator` 以**位置型**斷言補上：格名以
# 字元類別捕獲、不寫出字面，因此不觸發 `#300` `AC-2`。
P306_REQUIRED_LOCATORS: dict[str, dict[tuple[str, str], int]] = {
    "coordinator": {
        ("channels/README.md", "分區三態"): 1,
        ("channels/README.md", "四職能"): 1,
        ("channels/README.md", "通道側收尾（`C5`、`CH3`）"): 1,
        ("telegram.md", "`scan` 探活集合"): 1,
        ("telegram.md", "seat 間喚醒"): 1,
        ("telegram.md", "session 與 thread 的綁定"): 1,
        ("telegram.md", "分區探活"): 1,
        ("telegram.md", "分區狀態 INVALID 判定"): 1,
        ("telegram.md", "分區狀態判準"): 1,
        ("telegram.md", "在 General 下指令的限制"): 1,
        ("telegram.md", "子程序退出後的銜接"): 1,
        ("telegram.md", "封存標記 upsert 反測"): 1,
        ("telegram.md", "封存標記寫入"): 1,
        ("telegram.md", "封存程序"): 2,
    },
    "manager": {
        ("telegram.md", "seat 間喚醒"): 1,
        ("telegram.md", "子程序退出後的銜接"): 2,
    },
    "reviewer": {
        ("channels/README.md", "四職能"): 1,
        ("telegram.md", "seat 間喚醒"): 1,
        ("telegram.md", "子程序退出後的銜接"): 1,
    },
    "implementer": {
        ("channels/README.md", "四職能"): 1,
        ("telegram.md", "seat 間喚醒"): 1,
        ("telegram.md", "子程序退出後的銜接"): 1,
    },
    "README": {
        ("channels/README.md", "為什麼這層會有實作"): 1,
    },
}

# `AC-5`：persona 前言（四份人格檔的第 1 行逐字相同，default profile 亦有）。
# **完整存全句**：只存開頭會讓後段（例如 “finished work gets a short report”）的 20 字
# 視窗落在判準之外——那正是 `R1` 第 1 輪指出的假陰性。
P306_PERSONA = (
    "You are Hermes Agent, built by Nous Research. Be direct: match the length "
    "of your reply to the weight of the ask — a one-line question gets a "
    "one-line answer, and finished work gets a short report of what changed, "
    "what's verified, and what's left, never a replay of the process. No "
    "filler (\"Great question,\" \"I'd be happy to\"), no restating the request "
    "back, no re-summarizing what you already said, no narrating tool calls "
    "the user can see. Plain claims over adjectives; when unsure, say so "
    "plainly. Agree because it's right, not because the user said it. Depth "
    "is earned — give it when the user asks for detail, teaches, or the stakes "
    "demand it, not by default."
)
# 後段的一個 20 字視窗，另作「常數確實涵蓋整句」的錨點（`R1` 第 1 輪的候選字面）。
P306_PERSONA_TAIL = "finished work gets a short report"

# `AC-8`：那一行逐字重複四次的共用句。
P306_SHARED = ("**本檔只能收窄或細化 `devflow/seats/**` 與 "
               "`devflow/WORKFLOW.md`，不得牴觸。**")

# `AC-4`：禁字面（本機具名 instance）。掃描**整檔**，含程式碼區塊內外。
P306_BANNED_LOCAL = ("augustushsu", "AugustusHsu", "1003546152597",
                     "/home/", "~/.hermes/scripts/")
# `AC-7` 反向：不得宣稱 profile 漂移已被處置。
P306_BANNED_CLAIM = ("已解決", "解決了", "不再")
# `AC-6` 例外的允許集合（不是「跳過 README」）：來源單與抽出門檻的理由單。
P306_README_ISSUES = {"#306", "#285"}


def _p306_flat(s: str) -> str:
    """空白折疊為單一空格（`AC-2`／`AC-5` 兩側共用同一個正規化）。"""
    return re.sub(r"\s+", " ", s)


def _p306_tpl_text(name: str) -> str:
    return (P306_TPL / f"{name}.md").read_text()


def _p306_tpl_ids(name: str) -> list[str]:
    """範本內以 `` `ID` `` 形式出現的條文 ID（裸 ID 不計）。"""
    return P306_ID_RE.findall(_p306_tpl_text(name))


def _p306_rule_bodies() -> dict[str, str]:
    """`WORKFLOW.md` 的規則行集合：ID → 去前綴且折疊空白後的本文。"""
    out: dict[str, str] = {}
    for ln in (REPO / "devflow" / "WORKFLOW.md").read_text().splitlines():
        m = P306_RULE_RE.match(ln)
        if m:
            out[m.group(1)] = _p306_flat(m.group(2))
    return out


def _p306_windows(text: str, n: int = P306_WIN) -> list[str]:
    return [text[i:i + n] for i in range(max(0, len(text) - n + 1))]


def _p306_copy_hits(body: str, rules: dict[str, str]) -> list[tuple[str, str]]:
    """`AC-2` 反向判準本體：回傳 (視窗, 來源 ID) 清單，空 ＝ 過關。"""
    flat = _p306_flat(body)
    hits = []
    for rid, rbody in rules.items():
        for win in _p306_windows(rbody):
            if win in flat:
                hits.append((win, rid))
    return hits


@case("#306 AC-2 反向：WORKFLOW.md 規則行的 20 字視窗零命中於五檔範本")
def _p306_ac2_reverse():
    rules = _p306_rule_bodies()
    check("#306 AC-2 規則行集合非空（否則本條空轉）", len(rules) >= 80,
          f"{len(rules)} 條")
    for name in P306_FILES:
        hits = _p306_copy_hits(_p306_tpl_text(name), rules)
        check(f"#306 AC-2 {name}.md 零命中規則原文的 20 字視窗",
              not hits,
              "命中 " + "；".join(f"{w!r}←{r}" for w, r in hits[:8]))


@case("#306 AC-2 鑑別力：把任一規則行的 20 字貼進範本（記憶體內）→ 判準須 FAIL")
def _p306_ac2_mutation():
    # 不寫檔：取現行範本的內容，在記憶體中接上一段真的條文原文再跑同一個判準函式。
    # 少了這條，`AC-2` 可能只是「範本剛好沒抄」而判準本身零鑑別力（`R6`）。
    rules = _p306_rule_bodies()
    victim = sorted(rules)[0]
    snippet = rules[victim][:P306_WIN]
    check("#306 AC-2 鑑別力：取到的片段恰 20 字", len(snippet) == P306_WIN,
          repr(snippet))
    for name in P306_FILES:
        base = _p306_tpl_text(name)
        check(f"#306 AC-2 鑑別力：{name}.md 現狀 → 零命中（判準非恆假）",
              not _p306_copy_hits(base, rules))
        for label, mutant in (
            ("散文行", base + f"\n照抄一段：{snippet}\n"),
            ("程式碼區塊內", base + f"\n```\n{snippet}\n```\n"),
        ):
            got = _p306_copy_hits(mutant, rules)
            check(f"#306 AC-2 鑑別力：{name}.md 插入條文原文於{label} → 判準 FAIL",
                  any(r == victim for _, r in got),
                  f"命中 {got[:3]!r}（期望含 {victim}）")


@case("#306 AC-2 正向：範本內每個 `ID` 形式的引用都存在於 WORKFLOW.md 的規則行")
def _p306_ac2_forward():
    rules = _p306_rule_bodies()
    total = 0
    for name in P306_FILES:
        ids = set(_p306_tpl_ids(name))
        total += len(ids)
        dangling = sorted(ids - rules.keys())
        check(f"#306 AC-2 {name}.md 的 ID 引用零懸空（{len(ids)} 個相異 ID）",
              not dangling, f"懸空 {dangling!r}")
        # 零懸空只擋「引用了不存在的 ID」，擋不住「該引而未引」——後者才是 (c) 會漂的
        # 方向：述及條文可套之處若不以 ID 引用，就是在複述規則而非引用它。故另驗現況
        # 全集為下界（移除任一既有引用即 FAIL）。
        missing = sorted(P306_REQUIRED_IDS[name] - ids)
        check(f"#306 AC-2 {name}.md 的 ID 引用涵蓋現況全集"
              f"（{len(P306_REQUIRED_IDS[name])} 個，下界非等值）",
              not missing, f"缺 {missing!r}；實得 {sorted(ids)!r}")
    check("#306 AC-2 五檔合計的相異 ID 引用數非 0（否則懸空檢查空轉）", total >= 20,
          f"{total} 個")
    # 鑑別力：捏一個不存在的 ID，同一個判準須判懸空。
    fake = "ZZ99"
    check("#306 AC-2 鑑別力：不存在的 ID 會被判懸空",
          fake not in rules and P306_ID_RE.findall(f"`{fake}`") == [fake],
          f"{fake} in rules={fake in rules}")


@case("#306 AC-2 鑑別力：移除任一既有 ID 引用的反引號 → 正向判準 FAIL")
def _p306_ac2_forward_mutation():
    """記憶體內反測（不寫檔）：逐檔逐 ID 把 `` `ID` `` 的反引號拆掉。

    拆掉反引號模擬的正是「述及該條文但不以 ID 引用」——文字還在、引用沒了。
    迴圈跑的是 `P306_REQUIRED_IDS`（現況全集），所以每一個既有引用都各有一條反測；
    `R1` 第 2 輪的候選（manager 的 `R2`、coordinator 的 `G2`）因此自然涵蓋。
    """
    for name in P306_FILES:
        base_ids = set(_p306_tpl_ids(name))
        check(f"#306 AC-2 鑑別力：{name}.md 現狀涵蓋現況全集（判準非恆假）",
              P306_REQUIRED_IDS[name] <= base_ids,
              f"缺 {sorted(P306_REQUIRED_IDS[name] - base_ids)!r}")
        for rid in sorted(P306_REQUIRED_IDS[name]):
            mutant = _p306_tpl_text(name).replace(f"`{rid}`", rid)
            got = set(P306_ID_RE.findall(mutant))
            check(f"#306 AC-2 鑑別力：{name}.md 移除 `{rid}` 的引用 → 判準 FAIL",
                  not (P306_REQUIRED_IDS[name] <= got),
                  f"變異後仍含齊：{sorted(got)!r}")


def _p306_cell_names() -> set[str]:
    """`telegram.md` 表格「面向」欄的格名集合。"""
    out = set()
    for ln in (REPO / "devflow" / "channels" / "telegram.md").read_text().splitlines():
        if ln.startswith("| ") and not ln.startswith("|---"):
            first = ln.split(" | ")[0][2:].strip()
            if first and first != "面向":
                out.add(first)
    return out


def _p306_readme_headings() -> set[str]:
    """`channels/README.md` 的 `^##+ ` 標題集合。"""
    return {ln.lstrip("#").strip()
            for ln in CHANNELS_README.read_text().splitlines()
            if re.match(r"^##+ ", ln)}


P306_CELL_RE = re.compile(r"telegram\.md「([^」]+)」")
P306_HEAD_RE = re.compile(r"channels/README\.md「([^」]+)」")


def _p306_locators(text: str) -> Counter[tuple[str, str]]:
    """文本內的 locator 多重集合：`(來源檔, 格名或節名)` → 出現次數。

    固定寫法：`telegram.md「<格名>」` 與 `channels/README.md「<節名>」`（全形引號）。
    帶次數是 `AC-3` 的一部分——只驗「存在」時，拔掉同檔的其中一處引用會被放過。
    """
    c: Counter[tuple[str, str]] = Counter(
        ("telegram.md", x) for x in P306_CELL_RE.findall(text))
    c.update(("channels/README.md", x) for x in P306_HEAD_RE.findall(text))
    return c


@case("#306 AC-3 範本引用的 telegram.md 格名與 channels/README.md 節名零懸空")
def _p306_ac3():
    cells, heads = _p306_cell_names(), _p306_readme_headings()
    check("#306 AC-3 telegram.md 的格名集合非空", len(cells) >= 8, f"{len(cells)} 格")
    check("#306 AC-3 channels/README.md 的節名集合非空", len(heads) >= 5,
          f"{len(heads)} 節")
    for name in P306_FILES:
        got = _p306_locators(_p306_tpl_text(name))
        # 「每份至少一處」只擋得住「一處都沒有」；逐鍵 ≥ 現況多重集合才擋得住
        # 「拔掉其中一處、保留敘述與其他引用」（`R1` 第 2 輪的候選 3）。
        need = P306_REQUIRED_LOCATORS[name]
        short = {k: (need[k], got[k]) for k in need if got[k] < need[k]}
        check(f"#306 AC-3 {name}.md 的 locator 涵蓋現況多重集合"
              f"（{sum(need.values())} 處，逐鍵 ≥、下界非等值）",
              not short, f"不足 {short!r}（期望, 實得）")
        check(f"#306 AC-3 {name}.md 至少一處對照表引用（實得 {sum(got.values())} 處）",
              sum(got.values()) >= 1, f"{sorted(got.items())!r}")
        bad = sorted(k for k in got
                     if not (k[1] in cells if k[0] == "telegram.md"
                             else k[1] in heads))
        check(f"#306 AC-3 {name}.md 的對照表引用零懸空", not bad, f"懸空 {bad!r}")
    # 鑑別力：捏一個不存在的格名，同一組判準須判懸空。
    fake = "telegram.md「這格不存在」"
    check("#306 AC-3 鑑別力：不存在的格名會被判懸空",
          P306_CELL_RE.findall(fake) == ["這格不存在"] and "這格不存在" not in cells)


@case("#306 AC-3 鑑別力：拔掉任一處 locator（保留敘述）→ 判準 FAIL")
def _p306_ac3_mutation():
    """記憶體內反測（不寫檔）：`R1` 第 2 輪的候選 3。

    逐檔逐 locator 把 `telegram.md「X」`／`channels/README.md「X」` 換成無 locator 的
    裸文字「那格」／「那節」，敘述仍在、定位沒了。只驗「每檔 ≥1」時這種變異會被放過。
    """
    for name in P306_FILES:
        need = P306_REQUIRED_LOCATORS[name]
        base = _p306_locators(_p306_tpl_text(name))
        check(f"#306 AC-3 鑑別力：{name}.md 現狀涵蓋現況多重集合（判準非恆假）",
              all(base[k] >= v for k, v in need.items()),
              f"實得 {sorted(base.items())!r}")
        for src, label in sorted(need):
            bare = "那格" if src == "telegram.md" else "那節"
            # 只換掉第一處（count=1）：同鍵有多處時，拔一處即應 FAIL。
            mutant = _p306_tpl_text(name).replace(f"{src}「{label}」", bare, 1)
            got = _p306_locators(mutant)
            short = {k: (need[k], got[k]) for k in need if got[k] < need[k]}
            check(f"#306 AC-3 鑑別力：{name}.md 拔掉 {src}「{label}」一處 → 判準 FAIL",
                  bool(short), f"變異後仍涵蓋：{sorted(got.items())!r}")
            # 對偶證明舊判準（每檔 ≥1）放過了這個候選——除非該檔本來只有一處。
            if sum(need.values()) > 1:
                check(f"#306 AC-3 鑑別力：{name}.md 拔掉 {src}「{label}」後"
                      f"舊判準（≥1）仍 PASS（假陰性）",
                      sum(got.values()) >= 1, f"實得 {sum(got.values())} 處")


@case("#306 AC-3 常數缺漏的那一鍵：以位置型斷言補上下界（不寫出禁字面）")
def _p306_ac3_omitted_locator():
    """`coordinator.md` 引用 `telegram.md` 的「第二棒的 ⟨英文詞⟩ 行」那一格。

    該格名含 `#300` `AC-2` 禁在本檔出現的英文詞，故 `P306_REQUIRED_LOCATORS` 不收該鍵
    （鍵是字串字面，寫進去就會觸發那條斷言）。這裡改以**位置型**判準釘住下界：格名用
    字元類別捕獲、不寫出字面，並連同它後面那段敘述一起錨定——拔掉 locator、只留敘述
    就會 FAIL。
    """
    # 該格名含 `#300` `AC-2` 禁在本檔出現的英文詞，故以字元類別捕獲、不寫出字面。
    pat = re.compile(r"telegram\.md「(第二棒的 [A-Za-z]+ 行)」那格記載轉播器發出第二棒")
    t = _p306_tpl_text("coordinator")
    got = pat.findall(t)
    check("#306 AC-3 coordinator.md 命中該 locator 恰 1 次（位置型，含後續敘述）",
          len(got) == 1, f"實得 {len(got)} 次：{got!r}")
    cells = _p306_cell_names()
    check("#306 AC-3 telegram.md 的格名集合非空（否則下方核對空轉）",
          len(cells) >= 8, f"{len(cells)} 格")
    check("#306 AC-3 捕獲的格名存在於 telegram.md 的「面向」欄（零懸空）",
          bool(got) and got[0] in cells, f"捕獲 {got!r}")
    # 反測 1（記憶體內，不寫檔）：拔掉 locator、保留敘述 → 位置型主斷言 FAIL。
    bare = t.replace(f"telegram.md「{got[0]}」", "那格", 1) if got else t
    check("#306 AC-3 鑑別力：該 locator 換成「那格」（敘述留著）→ 主斷言 FAIL",
          len(pat.findall(bare)) == 0, f"變異後仍命中 {pat.findall(bare)!r}")
    check("#306 AC-3 鑑別力：變異後敘述仍在（證明只拔掉定位、不是整段消失）",
          "那格記載轉播器發出第二棒" in bare, "")
    # 反測 2（記憶體內）：格名改成不存在的格名 → 面向欄核對 FAIL。
    # 變異落在中段那個英文詞（`[A-Za-z]+` 捕獲得到，故位置型仍命中）；若改尾字
    # 「行」→「列」，位置型自己就不命中了，那驗到的是另一件事。
    if got:
        fake = got[0].replace(got[0].split(" ")[1], "zzz")
        check("#306 AC-3 鑑別力：變異格名與原格名不同", fake != got[0], f"{fake!r}")
        mutant = t.replace(f"telegram.md「{got[0]}」",
                           f"telegram.md「{fake}」", 1)
        mut_got = pat.findall(mutant)
        check("#306 AC-3 鑑別力：改格名後位置型仍命中（變異落在格名、不在位置）",
              mut_got == [fake], f"實得 {mut_got!r}")
        check("#306 AC-3 鑑別力：改過的格名不在「面向」欄 → 零懸空核對 FAIL",
              fake not in cells, f"{fake!r} 竟存在於面向欄")
        # 另一種變異：改尾字「行」→「列」，位置型判準自己就擋下（兩層各有效）。
        tail = t.replace(f"telegram.md「{got[0]}」",
                         f"telegram.md「{got[0][:-1]}列」", 1)
        check("#306 AC-3 鑑別力：格名尾字改「列」→ 位置型主斷言 FAIL",
              pat.findall(tail) == [], f"變異後仍命中 {pat.findall(tail)!r}")


@case("#306 AC-3 反向：範本不得含「沒有條文依據」字面（該缺口已由 CH3／C5 補上）")
def _p306_ac3_reverse():
    for name in P306_FILES:
        t = _p306_tpl_text(name)
        check(f"#306 AC-3 {name}.md 不含「沒有條文依據」", "沒有條文依據" not in t)
    # 正向對偶：封存那一節須實際引用條文 ID（不是只把那句話刪掉）。
    coord = _p306_tpl_text("coordinator")
    check("#306 AC-3 coordinator.md 的封存節引用 `C5` 與 `CH3`",
          "`C5`" in coord and "`CH3`" in coord)


def _p306_local_hits(text: str) -> list[str]:
    """`AC-4` 判準本體：掃描**整檔**（含程式碼區塊內外）。"""
    return [b for b in P306_BANNED_LOCAL if b in text]


@case("#306 AC-4 範本不含本機具名 instance（整檔掃描，含程式碼區塊內）")
def _p306_ac4():
    for name in P306_FILES:
        t = _p306_tpl_text(name)
        hits = _p306_local_hits(t)
        check(f"#306 AC-4 {name}.md 不含禁字面 {P306_BANNED_LOCAL}", not hits,
              f"命中 {hits!r}")
    # 以占位符表達——正向對偶，否則「不含具名值」可由「什麼都不寫」滿足。
    for name, need in (("coordinator", "<scripts-dir>"),
                       ("manager", "<repo>"),
                       ("implementer", "<worktree>"),
                       ("reviewer", "<本次日期>"),
                       ("README", "<scripts-dir>")):
        check(f"#306 AC-4 {name}.md 以占位符表達（含 `{need}`）",
              need in _p306_tpl_text(name))


@case("#306 AC-4 鑑別力：禁字面插入散文行與程式碼區塊內各一次 → 兩者皆 FAIL")
def _p306_ac4_mutation():
    # 不寫檔：在記憶體中變異。兩種位置各跑一次，證明判準不是只掃散文。
    for name in P306_FILES:
        base = _p306_tpl_text(name)
        check(f"#306 AC-4 鑑別力：{name}.md 現狀 → 零命中（判準非恆假）",
              not _p306_local_hits(base))
        for banned in P306_BANNED_LOCAL:
            prose = base + f"\n工作目錄在 {banned} 底下。\n"
            fenced = base + f"\n```\ncd {banned}\n```\n"
            check(f"#306 AC-4 鑑別力：{name}.md 散文行含 `{banned}` → FAIL",
                  _p306_local_hits(prose) == [banned],
                  f"命中 {_p306_local_hits(prose)!r}")
            check(f"#306 AC-4 鑑別力：{name}.md 程式碼區塊內含 `{banned}` → FAIL",
                  _p306_local_hits(fenced) == [banned],
                  f"命中 {_p306_local_hits(fenced)!r}")


@case("#306 AC-5 persona 前言的 20 字視窗零命中於五檔範本")
def _p306_ac5():
    # 常數寫死（見本族檔頭）：前言的來源在 repo 外，從檔案讀會讓測試依賴不受版控的輸入。
    wins = _p306_windows(P306_PERSONA)
    check("#306 AC-5 前言的視窗數非 0（否則本條空轉）", len(wins) >= 50,
          f"{len(wins)} 個")
    # 常數須涵蓋**完整**前言，不只開頭：後段若落在判準外，貼後段就逃得掉。
    check("#306 AC-5 常數涵蓋前言後段（視窗判準及於整句）",
          P306_PERSONA_TAIL in P306_PERSONA
          and len(P306_PERSONA) >= 600, f"{len(P306_PERSONA)} 字")
    check(f"#306 AC-5 後段錨點「{P306_PERSONA_TAIL}」本身長於視窗（可被切出視窗）",
          len(P306_PERSONA_TAIL) > P306_WIN, f"{len(P306_PERSONA_TAIL)} 字")
    for name in P306_FILES:
        flat = _p306_flat(_p306_tpl_text(name))
        hits = [w for w in wins if w in flat]
        check(f"#306 AC-5 {name}.md 零命中前言的 20 字視窗", not hits,
              f"命中 {hits[:5]!r}")
    # 鑑別力：把前言貼進任一範本（記憶體內）→ 須命中。
    for name in P306_FILES:
        mutant = _p306_flat(_p306_tpl_text(name) + "\n" + P306_PERSONA + "\n")
        check(f"#306 AC-5 鑑別力：{name}.md 插入前言 → 判準 FAIL",
              any(w in mutant for w in wins))


@case("#306 AC-5 鑑別力：只插入前言後段（非開頭）→ 判準仍 FAIL")
def _p306_ac5_mutation():
    """記憶體內反測（不寫檔）：`R1` 第 1 輪的候選——貼後段而不貼開頭。

    常數只存開頭時，後段的視窗不在 `wins` 裡，這個變異會被放過。
    """
    wins = _p306_windows(P306_PERSONA)
    tail_wins = [w for w in _p306_windows(P306_PERSONA_TAIL) if w in wins]
    check(f"#306 AC-5 鑑別力：後段可切出 {len(tail_wins)} 個視窗且皆在判準內",
          len(tail_wins) >= 10, f"{len(tail_wins)} 個")
    for name in P306_FILES:
        base = _p306_flat(_p306_tpl_text(name))
        check(f"#306 AC-5 鑑別力：{name}.md 現狀零命中（判準非恆真）",
              not [w for w in wins if w in base])
        mutant = _p306_flat(_p306_tpl_text(name) + "\n" + P306_PERSONA_TAIL + "\n")
        got = [w for w in wins if w in mutant]
        check(f"#306 AC-5 鑑別力：{name}.md 插入後段「{P306_PERSONA_TAIL}」→ 判準 FAIL",
              got != [], f"命中 {got[:3]!r}")


@case("#306 AC-5 templates/README.md 寫明這是機械事實而非偏好")
def _p306_ac5_readme():
    t = _p306_tpl_text("README")
    for frag, why in (("機械事實", "裁示逐字要求的性質判定"),
                      ("runtime 注入", "前言的真正來源"),
                      ("第 1 行", "四份人格檔的位置"),
                      ("default profile", "與 devflow 無關的 profile 亦有")):
        check(f"#306 AC-5 README 載「{frag}」（{why}）", frag in t)


@case("#306 AC-6 四份範本不含本 repo 的經驗史（`#NNN` 與「實測」）")
def _p306_ac6():
    iss_re = re.compile(r"#[0-9]{3}")
    for name in P306_SEATS:
        t = _p306_tpl_text(name)
        check(f"#306 AC-6 {name}.md 零 issue 引用（`#` ＋三位數）",
              not iss_re.findall(t), f"命中 {sorted(set(iss_re.findall(t)))!r}")
        check(f"#306 AC-6 {name}.md 不含「實測」", "實測" not in t)
    # README 的例外是一個**明確的允許集合**，不是跳過該檔。
    rt = _p306_tpl_text("README")
    got = set(iss_re.findall(rt))
    check(f"#306 AC-6 README 的 issue 引用落在允許集合 {sorted(P306_README_ISSUES)}",
          got <= P306_README_ISSUES, f"實得 {sorted(got)!r}")
    check("#306 AC-6 README 確實引用了來源單 #306（允許集合非空轉）",
          "#306" in got, f"實得 {sorted(got)!r}")
    check("#306 AC-6 README 亦禁「實測」（例外只放寬 issue 引用）",
          "實測" not in rt)
    # 鑑別力：允許集合外的編號須被判出。
    check("#306 AC-6 鑑別力：允許集合不含 #287",
          "#287" not in P306_README_ISSUES
          and not ({"#306", "#287"} <= P306_README_ISSUES))


def _p306_section(text: str, head_re: str) -> str:
    """切出 `^##+ <head_re>` 到下一個同級或更高級標題之間的節文（不含標題行）。

    `AC-7` 要的是「三句在那一節內」——全檔搜尋會讓三句搬到別節、該節留空仍 PASS。
    """
    lines = text.splitlines()
    start = None
    level = 0
    for i, ln in enumerate(lines):
        if re.match(rf"^##+ .*{head_re}", ln):
            start = i
            level = len(ln) - len(ln.lstrip("#"))
            break
    if start is None:
        return ""
    body = []
    for ln in lines[start + 1:]:
        m = re.match(r"^(#+) ", ln)
        if m and len(m.group(1)) <= level:
            break
        body.append(ln)
    return "\n".join(body)


@case("#306 AC-7 templates/README.md 載「(c) 的已知上限」三句與範本層定義")
def _p306_ac7():
    t = _p306_tpl_text("README")
    check("#306 AC-7 有「(c) 的已知上限」這一節",
          bool(re.search(r"^##+ .*\(c\) 的已知上限", t, re.M)),
          repr([ln for ln in t.splitlines() if ln.startswith("#")]))
    # T 的三句，逐字，且**只在該節內**找（搬到別節不算）。
    sect = _p306_section(t, r"\(c\) 的已知上限")
    check("#306 AC-7 該節的節文非空（否則節內檢查空轉）", len(sect.strip()) >= 100,
          f"{len(sect.strip())} 字")
    for frag, why in (
        ("**範本引用條文只保證「範本不漂移」，不保證「使用者照範本做」。**",
         "上限第一句"),
        ("仍在 AC 視野外", "上限第二句：profile 的位置"),
        ("該缺口留給 K6", "上限第三句：缺口的歸屬"),
    ):
        check(f"#306 AC-7 「(c) 的已知上限」節內逐字載「{frag}」（{why}）",
              frag in sect, "")
    # 範本是什麼、怎麼用、不由安裝產生且為刻意。
    for frag, why in (("## 怎麼用", "用法節"),
                      ("複製", "用法：自行複製到人格檔位置"),
                      ("占位符", "用法：再填占位符"),
                      ("不由安裝產生", "刻意不由安裝產生"),
                      ("刻意，不是遺漏", "寫明這是刻意的"),
                      ("`I6`", "理由：由 kit 寫協調平台的設定與 I6 相反")):
        check(f"#306 AC-7 README 載「{frag}」（{why}）", frag in t, "")


@case("#306 AC-7 鑑別力：三句搬出「(c) 的已知上限」節、節留空 → 判準 FAIL")
def _p306_ac7_mutation():
    """記憶體內反測（不寫檔）：`R1` 第 1 輪的候選——三句還在檔內、但不在那一節。

    全檔搜尋時三句仍命中，故此變異會被放過；節內搜尋才擋得住。
    """
    t = _p306_tpl_text("README")
    head = "## ⚠️ (c) 的已知上限"
    check("#306 AC-7 鑑別力：README 含該節標題（變異可施作）", head in t, "")
    sect = _p306_section(t, r"\(c\) 的已知上限")
    three = ("**範本引用條文只保證「範本不漂移」，不保證「使用者照範本做」。**",
             "仍在 AC 視野外", "該缺口留給 K6")
    check("#306 AC-7 鑑別力：現狀三句皆在節內（判準非恆假）",
          all(f in sect for f in three), "")
    # 變異：把整節節文搬到檔首（另一節之內），原節只留一行無關文字。
    mutant = t.replace(head + "\n" + sect, head + "\n\n（本節留空）\n")
    mutant = sect + "\n" + mutant
    mut_sect = _p306_section(mutant, r"\(c\) 的已知上限")
    for f in three:
        check(f"#306 AC-7 鑑別力：變異後「{f[:12]}…」仍在檔內（全檔搜尋放過）",
              f in mutant, "")
        check(f"#306 AC-7 鑑別力：變異後「{f[:12]}…」已不在節內 → 判準 FAIL",
              f not in mut_sect, f"節文 {mut_sect[:80]!r}")


@case("#306 AC-7 反向：五檔範本不得宣稱 profile 漂移已被處置")
def _p306_ac7_reverse():
    for name in P306_FILES:
        t = _p306_tpl_text(name)
        hits = [b for b in P306_BANNED_CLAIM if b in t]
        check(f"#306 AC-7 {name}.md 不含 {P306_BANNED_CLAIM}", not hits,
              f"命中 {hits!r}")
    # 鑑別力：插入任一宣稱字面 → 同一判準須 FAIL。
    base = _p306_tpl_text("README")
    for banned in P306_BANNED_CLAIM:
        mutant = base + f"\n本單{banned} profile 漂移。\n"
        check(f"#306 AC-7 鑑別力：插入「{banned}」→ 判準 FAIL",
              [b for b in P306_BANNED_CLAIM if b in mutant] != [])


def _p306_shared_lines() -> list[list[str]]:
    """四份範本各自的「去空白行、排除 `---` 與 ``` 」行**序列**（保留重複）。

    用 list 而非 set：`AC-8` 的門檻以「逐字共同行的行數」為判準，set 會把同一份內
    重複一次的共用句壓成一個，使「`[2,1,1,1]` 次」這種未達候選被放過。
    """
    out = []
    for name in P306_SEATS:
        out.append([ln for ln in _p306_tpl_text(name).splitlines()
                    if ln.strip() and ln.strip() not in ("---", "```")])
    return out


def _p306_common_lines(seqs: list[list[str]]) -> set[str]:
    """四份皆出現、且每份**恰出現一次**的行（共同行的定義）。

    「恰一次」是 `AC-8` 的一部分：共用句在某一份重複，那一份就不只是「照抄一行」，
    門檻句數不再對應四份的實際共同結構。
    """
    sets = [set(s) for s in seqs]
    return {ln for ln in set.intersection(*sets)
            if all(s.count(ln) == 1 for s in seqs)}


@case("#306 AC-8 抽出門檻句存在，且四份逐字交集恰為那一行共用句")
def _p306_ac8():
    t = _p306_tpl_text("README")
    threshold = "若將來四份範本的逐字共同行增至 3 行以上，重新評估抽出共用檔"
    check(f"#306 AC-8 README 載門檻句（含數字 3）「{threshold}」",
          threshold in t and "3" in threshold, "")
    for frag, why in (("逐字相同", "判準是逐字"),
                      ("意思相近", "明寫不是意思相近"),
                      ("#285", "該限定的理由單")):
        check(f"#306 AC-8 README 載「{frag}」（{why}）", frag in t, "")
    # 實算核：四份的共同行恰 1 行且等於共用句。
    seqs = _p306_shared_lines()
    check("#306 AC-8 四份各自的行序列皆非空", all(len(s) > 20 for s in seqs),
          f"{[len(s) for s in seqs]!r}")
    inter = _p306_common_lines(seqs)
    check("#306 AC-8 逐字共同行恰 1 行", len(inter) == 1,
          f"{len(inter)} 行：{sorted(inter)!r}")
    check("#306 AC-8 該行即共用句（逐字）", inter == {P306_SHARED},
          f"實得 {sorted(inter)!r}\n期望 {[P306_SHARED]!r}")
    # 次數：四份**各恰 1 次**、合計恰 4。多一次即非「逐字重複四次」那個結構。
    counts = [s.count(P306_SHARED) for s in seqs]
    check("#306 AC-8 共用句在四份各恰 1 次（合計恰 4）",
          counts == [1, 1, 1, 1] and sum(counts) == 4, f"實得 {counts!r}")
    for name, n in zip(P306_SEATS, counts):
        check(f"#306 AC-8 {name}.md 含共用句恰 1 次", n == 1, f"{n} 次")


@case("#306 AC-8 鑑別力：任一份的共用句改掉一個字 → 交集斷言 FAIL")
def _p306_ac8_mutation():
    # 不寫檔：在記憶體中對每一份各變異一次，確認交集不再等於那一句。
    for i, name in enumerate(P306_SEATS):
        seqs = _p306_shared_lines()
        mutated = P306_SHARED.replace("不得牴觸", "不得牴觸。")
        check(f"#306 AC-8 鑑別力：變異字面與原句不同（{name}）",
              mutated != P306_SHARED)
        seqs[i] = [mutated if ln == P306_SHARED else ln for ln in seqs[i]]
        inter = _p306_common_lines(seqs)
        check(f"#306 AC-8 鑑別力：{name}.md 的共用句被改 → 交集不再等於共用句",
              inter != {P306_SHARED}, f"實得 {sorted(inter)!r}")
        check(f"#306 AC-8 鑑別力：{name}.md 被改後交集為空（該行是唯一共同行）",
              inter == set(), f"實得 {sorted(inter)!r}")


@case("#306 AC-8 鑑別力：共用句在某一份重複一次（`[2,1,1,1]`）→ 判準 FAIL")
def _p306_ac8_dup_mutation():
    """記憶體內反測（不寫檔）：`R1` 第 1 輪的候選。

    set 交集在次數 `[2,1,1,1]` 下仍為 `{共用句}`，故舊判準放過；`count` 判準擋得住。
    """
    for i, name in enumerate(P306_SEATS):
        seqs = _p306_shared_lines()
        base_counts = [s.count(P306_SHARED) for s in seqs]
        check(f"#306 AC-8 鑑別力：現狀四份各 1 次（判準非恆假，{name} 回合）",
              base_counts == [1, 1, 1, 1], f"實得 {base_counts!r}")
        seqs[i] = seqs[i] + [P306_SHARED]      # 該份重複一次
        counts = [s.count(P306_SHARED) for s in seqs]
        check(f"#306 AC-8 鑑別力：{name}.md 重複共用句 → 次數判準 FAIL",
              counts != [1, 1, 1, 1] and sum(counts) == 5, f"實得 {counts!r}")
        # 同時證明舊的 set 交集放過了這個候選——這就是假陰性的機械證據。
        set_inter = set.intersection(*[set(s) for s in seqs])
        check(f"#306 AC-8 鑑別力：{name}.md 重複時舊 set 交集仍為共用句（假陰性）",
              set_inter == {P306_SHARED}, f"實得 {sorted(set_inter)!r}")
        check(f"#306 AC-8 鑑別力：{name}.md 重複時新共同行判準已排除該行",
              _p306_common_lines(seqs) == set(),
              f"實得 {sorted(_p306_common_lines(seqs))!r}")


@case("#306 AC-1 templates/ 恰 5 個 .md（反向：不新增 seat-common.md）")
def _p306_ac1():
    mds = sorted(p.name for p in P306_TPL.glob("*.md"))
    check("#306 AC-1 templates/ 下恰 5 個 .md", len(mds) == 5, f"{mds!r}")
    check("#306 AC-1 五檔即四份 seat 範本 ＋ README",
          mds == sorted(f"{n}.md" for n in P306_FILES), f"{mds!r}")
    check("#306 AC-1 無 seat-common.md（裁示 A：共用句逐字重複四次）",
          not (P306_TPL / "seat-common.md").exists())
    # 每檔首段點明對應的職位檔（`AC-1`：各自完整、可獨立閱讀）。
    for name in P306_SEATS:
        head = "\n".join(_p306_tpl_text(name).splitlines()[:10])
        check(f"#306 AC-1 {name}.md 首段點明對應 seats/{name}.md",
              "devflow/seats/" in head and f"`{name}.md`" in head, head)
        check(f"#306 AC-1 {name}.md 首段聲明職位本體不複製（引用 `I5`）",
              "`I5`" in head, head)


@case("#306 AC-13 devflow/VERSION ＝ 0.17.0.0（V2 的 b 位：新增一層範本）")
def _p306_version():
    raw = (REPO / "devflow" / "VERSION").read_text().strip()
    check("#306 AC-13 形狀合 V1 的四碼", bool(VERSION_SHAPE.fullmatch(raw)),
          repr(raw))
    check("#306 AC-13 VERSION == 0.17.0.0", raw == "0.17.0.0", repr(raw))
    ok, why = _version_gt(raw, "0.16.1.0")
    check("#306 AC-13 嚴格大於 base（#304）的 0.16.1.0", ok, f"{raw!r}：{why}")


@case("#306 AC-9／AC-10 channels/README.md 與 seats/README.md 的記載")
def _p306_indexes():
    ch = CHANNELS_README.read_text()
    # `AC-9`：新增一節指向 templates/，說明承載什麼、與 seats/ 的分工，引用不複製。
    check("#306 AC-9 channels/README.md 有指向 templates/ 的一節",
          bool(re.search(r"^##+ .*`templates/`", ch, re.M)),
          repr([ln for ln in ch.splitlines() if ln.startswith("#")]))
    for frag, why in (("職位本體", "與 seats/ 的分工：那一側是什麼"),
                      ("人格檔範本", "與 seats/ 的分工：這一側是什麼"),
                      ("`templates/README.md`", "引用而不複製的落點"),
                      ("`I5`", "引用不複製的條文依據")):
        check(f"#306 AC-9 channels/README.md 的該節載「{frag}」（{why}）",
              frag in ch, "")
    # 反向：本節不得重複 (c) 已知上限那三句（`I5`：一個事實只住一處）。
    for frag in ("不保證「使用者照範本做」", "仍在 AC 視野外", "該缺口留給 K6"):
        check(f"#306 AC-9 channels/README.md 不重複上限句「{frag}」",
              frag not in ch, "")
    # 末節的過期陳述已改：「人格檔範本」不得仍掛在 K4d 的未納管清單裡。
    tail = ch.split("## 本層不管的事", 1)
    check("#306 AC-9 channels/README.md 仍有「本層不管的事」節", len(tail) == 2)
    if len(tail) == 2:
        last = tail[1]
        check("#306 AC-9 末節不再把人格檔範本列為 K4d（過期陳述已改）",
              "人格檔範本：K4d" not in last
              and "環境結帳、人格檔範本" not in last, last)
        check("#306 AC-9 末節明寫人格檔範本已納入本層",
              "人格檔範本已納入本層" in last, last)
    # `AC-10`：seats/README.md 補一行分工。
    se = (REPO / "devflow" / "seats" / "README.md").read_text()
    for frag, why in (("職位本體、不綁工具", "seats/ 這一側"),
                      ("`devflow/channels/templates/`", "範本那一側的位置"),
                      ("通道側操作規範", "範本那一側的內容")):
        check(f"#306 AC-10 seats/README.md 載「{frag}」（{why}）", frag in se, "")


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