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
            raised = False
            try:
                marker.read_topic(body)
            except marker.InvalidMarker:
                raised = True
            check(f"AC-7 {label}：T>1 時正向 raise、反向不主張擁有該 thread",
                  raised and not marker.has_topic(body, "2620")
                  and not marker.has_topic(body, "999"))

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
