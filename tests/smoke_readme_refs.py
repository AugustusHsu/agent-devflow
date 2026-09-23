#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""README.md 引用的 7 位 hex 都要在 repo 裡存在（issue #166 AC-11）。

從任何目錄執行（repo 根由 `__file__` 定位，git 指令一律在 repo 根跑）：

    python3 tests/smoke_readme_refs.py

只用標準庫，exit 0（全部存在）／1（有缺）／2（跑不起來）。

為什麼有這個檔：README 的事實表與「Phase 1 第三出口的判定方式」把證據記成 7 位 hex
（「證據欄只記能用 gh／git 讀回的識別碼」）。這些 hash 打錯一個字元、或指向一個後來
不存在的物件，讀的人不會發現——它看起來就像一個 hash。這個檔讓它變成會紅的 CI。

**不 peel、任何物件型別皆可**（issue #166 的 L3 裁決）：README 引的 hash 有 commit、
也有 blob（Phase 1 判定表的 `checker_blob`，正反兩個 run 比的就是它）與 tree
（「兩個 commit 的 tree 相同」那句），四種都是事實，都該被保護。所以判準是
`git cat-file -e <hex>`，不加 `^{commit}`／`^{tag}`。

**排除 code fence 內的行**：fence 裡是範例與佈局圖，裡面的 hash 不是本 repo 的證據。

不斷言「恰 N 個」：README 每加一筆證據就會多一個 hash，把數字寫死只會讓無關的 PR 變紅。
數量印在輸出裡供人核對（本檔寫成時是 25 個唯一值，收窄誤抓面後是 24 個）。
"""
import re
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"


# ── exit code：0 全部存在／1 有缺／2 跑不起來（issue #173 R1-5） ────────────────
# 和 scripts/devflow_checks.py 檔頭同一套守則：1 只有一個意思——被檢查的**內容**違規
# （README 引了不存在的 hash）；2 是「這支測試本身跑不起來」。Python 對未攔截的例外
# 預設以 1 結束，會和內容違規撞號，而這兩件事的處置相反：前者改 README，後者修環境。
# SystemExit 不經 hook，所以 main() 的 return 0／1 不受影響。
def _uncaught(exc_type, exc, tb):
    try:
        sys.stdout.flush()
        traceback.print_exception(exc_type, exc, tb)
        print("💥 README 引用檢查無法執行：未預期的 %s: %s（未分類的例外一律 exit 2，不是內容違規）"
              % (exc_type.__name__, exc))
        sys.stdout.flush()
    finally:
        sys.exit(2)               # 連印訊息都失敗也要是 2，不能退回 Python 預設的 1


sys.excepthook = _uncaught

# 反引號包住的 7 位小寫 hex。前後要是反引號，所以 `8029dfa12092…`（全長 sha）不會被切成 7 碼。
HEX_RE = re.compile(r"`([0-9a-f]{7})`")

# 缺物件時印的提示：README 引的 probe commit 只活在 PR 的 head ref，
# 一般 clone（含 CI 的 fetch-depth: 0，它只取 refs/heads/* 與 refs/tags/*）不會帶它。
HINT = ("若缺的是 PR 的 probe commit，先 "
        "git fetch origin '+refs/pull/*/head:refs/remotes/origin/pr/*'")


def looks_like_sha(h):
    """7 位 hex 字面上是不是一個短 sha。

    收窄誤抓面（issue #173 R1-6）：`[0-9a-f]{7}` 同時吃下兩種不是 sha 的東西——7 位
    純數字的 id（run id、留言 id 的片段）與 7 個字母剛好都落在 a-f 的英文字（`defaced`、
    `acceded`）。判準是「至少一個數字，且至少一個 a-f 字母」；`11d0fba`（README 引的
    PR #42 probe commit）兩邊都有，仍在射程內——它是這條判準的反向要求。

    代價寫在這裡，不藏著：真的短 sha 也可能剛好全是數字，README:79 的 `6717944`
    （PR #151 的 merge commit）就是，本判準之後它不再被檢查。字面上分不出它和一個
    7 位 id，正如分不出「別的 repo 的短 sha」（issue #173「不做」段同一個理由）。
    被略過的候選會印在輸出裡，讓這個代價看得見，而不是默默消失。"""
    return any(c.isdigit() for c in h) and any(c in "abcdef" for c in h)


# ── fence 辨識（issue #185 A4）：依 CommonMark，與 tests/smoke_release_doc.py 同一份定義 ──
# `strip().startswith("```")` ＋ 開關對調有三個方向都錯：縮排 ≥4 格的 ``` 是 indented code、
# 不是 fence（於是散文裡真的證據被當成範例，漏抓）；`~~~` 也是 fence 卻不被認（誤抓）；
# 關閉只認「開頭是 ```」，於是 ```` 區塊裡的一行 ``` 會把它關掉、`` ``` x `` 也會
# （都是誤抓）（PR #172 audit BLOCK 3／4）。
# 開啟：縮排 0–3 格 ＋ 三個以上的同種字元（`` ` `` 或 `~`）＋ info string；反引號 fence 的
# info string 不得含反引號。關閉：同種字元、根數 ≥ 開啟、其後只有空白、縮排 0–3 格。
FENCE_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")


def fence_open(line):
    """fence 開啟行 → (字元, 根數, info string)；不是開啟行回 None。"""
    m = FENCE_RE.match(line)
    if not m:
        return None
    marker, info = m.group(2), m.group(3)
    if marker[0] == "`" and "`" in info:
        return None
    return marker[0], len(marker), info.strip()


def fence_close(line, char, size):
    """這一行關不關得掉「以 char × size 開啟」的那個 fence。"""
    m = FENCE_RE.match(line)
    if not m:
        return False
    marker = m.group(2)
    return marker[0] == char and len(marker) >= size and not m.group(3).strip()


def extract(text):
    """回傳 (found, skipped)：兩者都是 {hex: [行號, …]}，跳過 code fence 內的行。

    skipped 是「長得像 hex、但不像短 sha」的那些——只印出來供人核對，不進判定。"""
    found, skipped = {}, {}
    fence = None                      # 不在 fence 內時是 None，否則是 (字元, 根數)
    for n, line in enumerate(text.split("\n"), 1):
        if fence is not None:
            if fence_close(line, fence[0], fence[1]):
                fence = None
            continue
        opened = fence_open(line)
        if opened:
            fence = (opened[0], opened[1])
            continue
        for m in HEX_RE.finditer(line):
            bucket = found if looks_like_sha(m.group(1)) else skipped
            bucket.setdefault(m.group(1), []).append(n)
    return found, skipped


def git(args):
    """在 repo 根跑 git，回傳 (returncode, stdout)。cwd 固定，所以從哪裡呼叫都一樣。"""
    p = subprocess.run(["git"] + args, cwd=str(REPO),
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return p.returncode, p.stdout.decode("utf-8", "replace").strip()


def check(text):
    """回傳 (found, missing, skipped)：found 是 {hex: [行號]}，missing 是缺的 [(hex, [行號])]。

    正負案例共用這一個函式：負向案例餵的是暫存目錄裡的突變副本，不另外 subprocess
    自己，正反兩邊跑的才保證是同一套判準。"""
    found, skipped = extract(text)
    missing = [(h, lines) for h, lines in sorted(found.items())
               if git(["cat-file", "-e", h])[0] != 0]
    return found, missing, skipped


def report(label, found, missing, skipped):
    """印出這一輪的明細；回傳 True＝全部存在。"""
    for h, lines in sorted(found.items()):
        where = "、".join("%s:%d" % (label, n) for n in lines)
        if any(h == m for m, _ in missing):
            print("        ✗ %s  缺（%s）" % (h, where))
        else:
            print("        · %s  %-6s %s" % (h, git(["cat-file", "-t", h])[1], where))
    for h, lines in sorted(skipped.items()):
        print("        ~ %s  略過   %s（全數字或全字母，不當短 sha 看；見 looks_like_sha）"
              % (h, "、".join("%s:%d" % (label, n) for n in lines)))
    return not missing


# 探針：四種形狀各一個，名字說明它是哪一面。
PROBE_MISSING = "deadb33"      # 合短 sha 形狀（有數字也有 a-f 字母），repo 裡不存在
PROBE_NUMERIC = "1234567"      # 7 位純數字：run id／留言 id 的形狀
PROBE_ALPHA = "defaced"        # 7 個字母剛好都落在 a-f 的英文字
PROBE_REAL = "11d0fba"         # 真的短 sha（PR #42 的 probe commit，只在 refs/pull/42/head）


def main():
    if not README.exists():
        # 讀不到受版控的檔＝這支檢查跑不起來，不是 README 引錯 hash：和 scripts/devflow_checks.py
        # 「工作樹讀不到受版控檔 → 2」同一套守則，處置也相反（修環境，不是改 README）。
        print("💥 找不到 %s（repo 佈局與本檔假設不符；exit 2，不是內容違規）" % README)
        return 2

    failures = []
    label = "README.md"
    text = README.read_text(encoding="utf-8")

    # 不是 git 版本庫＝這支檢查跑不起來，不是 README 引錯 hash（issue #185 A6；PR #178
    # audit BLOCK 3）。沒有這一關的話，`git cat-file -e` 對每一個 hex 都回 128，全部報成
    # 「缺」而 exit 1——把環境錯誤說成內容違規，處置剛好相反。
    # 為什麼要前置一條 `rev-parse`：`cat-file -e` 對「物件不存在」與「根本不在 repo 裡」
    # 回的都是 128，rc 分不出這兩件事，只能在逐個查之前先問一次環境。
    # 位置在讀 README **之後**：README 不在時該報的是缺檔（上面那條），搬到前面會讓
    # 「沒有 README 又不是 git repo」印成 git 環境錯誤，指錯要修的東西。
    if git(["rev-parse", "--git-dir"])[0] != 0:
        print("💥 %s 不是 git 版本庫，無從查證 README 引的 hash（exit 2，不是內容違規）" % REPO)
        return 2

    # 正向：真的那一份 README
    found, missing, skipped = check(text)
    good = not missing
    print("正向  %-34s 應過    %d 個唯一 hex、%d 個缺（期望 0）、略過 %d 個  %s"
          % (label, len(found), len(missing), len(skipped), "PASS" if good else "FAIL"))
    report(label, found, missing, skipped)
    if not good:
        failures.append("%s：%d 個 hex 在 repo 裡找不到（%s）"
                        % (label, len(missing), "、".join(h for h, _ in missing)))
    print()

    # 負向、誤抓面與反向保證：突變副本放進暫存目錄，讀回來餵同一個 check()。
    # (名稱, 文字, 探針, 期望抓到, 期望缺)
    with tempfile.TemporaryDirectory() as tmp:
        cases = [
            ("散文裡塞一個不存在的 hex",
             text + "\n\n假的證據：`%s`。\n" % PROBE_MISSING, PROBE_MISSING, True, True),
            ("同一個 hex 放進 code fence 內",
             text + "\n\n```\n假的證據：`%s`。\n```\n" % PROBE_MISSING, PROBE_MISSING, False, False),
            ("散文裡塞一個 7 位純數字 id",
             text + "\n\n那個 run 是 `%s`。\n" % PROBE_NUMERIC, PROBE_NUMERIC, False, False),
            ("散文裡塞一個 7 個 a-f 字母的英文字",
             text + "\n\n那句話被 `%s` 了。\n" % PROBE_ALPHA, PROBE_ALPHA, False, False),
            ("真的短 sha 仍要被抓到且判為存在",
             "證據：`%s`。\n" % PROBE_REAL, PROBE_REAL, True, False),
            # ── fence 辨識的邊界（issue #185 A4）：與 smoke_release_doc.py 的 parse() 同一張表。
            # 「fence 內不抓」與「fence 外要抓」是同一件事的兩面：把不是 fence 的行當成 fence
            # 會讓真的證據不被檢查（漏抓），把關不掉的 fence 當成關掉了會讓範例裡的 hash 被檢查
            # （誤抓）。兩個方向各三、四條。
            ("`~~~` 也是 fence，裡面的 hex 不抓",
             "~~~\n假的證據：`%s`。\n~~~\n" % PROBE_MISSING, PROBE_MISSING, False, False),
            ("四個反引號的 fence 內含一行三個反引號（關不掉），其後的 hex 不抓",
             "````\n裡面有一行 fence：\n```\n假的證據：`%s`。\n````\n" % PROBE_MISSING,
             PROBE_MISSING, False, False),
            ("縮排四格的三個反引號不是 fence，其後散文的 hex 要抓",
             "    ```\n\n證據：`%s`。\n" % PROBE_REAL, PROBE_REAL, True, False),
            ("```bash 開、`~~~` 關不掉（字元不同），其後的 hex 不抓",
             "```bash\necho 1\n~~~\n假的證據：`%s`。\n```\n" % PROBE_MISSING,
             PROBE_MISSING, False, False),
            ("``` 開、`` ``` x `` 關不掉（其後有非空白），其後的 hex 不抓",
             "```\necho 1\n``` x\n假的證據：`%s`。\n```\n" % PROBE_MISSING,
             PROBE_MISSING, False, False),
            ("``` 開、五個反引號關（比開啟長，照常關閉），其後散文的 hex 要抓",
             "```\necho 1\n`````\n\n證據：`%s`。\n" % PROBE_REAL, PROBE_REAL, True, False),
            ("開閉各縮排三格的 fence（0–3 格仍是 fence），裡面的 hex 不抓",
             "   ```\n假的證據：`%s`。\n   ```\n" % PROBE_MISSING, PROBE_MISSING, False, False),
        ]
        for n, (name, mutated, probe, want_caught, want_missing) in enumerate(cases):
            path = Path(tmp) / ("mutant-%02d.md" % n)
            path.write_text(mutated, encoding="utf-8")
            mfound, mmissing, mskipped = check(path.read_text(encoding="utf-8"))
            caught = probe in mfound
            missed = any(h == probe for h, _ in mmissing)
            good = (caught == want_caught) and (missed == want_missing)
            print("%s  %-34s %s  抓到 %s＝%s（期望 %s）、判缺＝%s（期望 %s）  %s"
                  % ("負向" if want_missing else "正向", name,
                     "應擋" if want_missing else "應過",
                     probe, caught, want_caught, missed, want_missing,
                     "PASS" if good else "FAIL"))
            for h, _ in mmissing:
                print("        ✗ %s" % h)
            for h in sorted(mskipped):
                print("        ~ %s 略過" % h)
            if not good:
                failures.append("%s：抓到=%s（期望 %s）、判缺=%s（期望 %s）"
                                % (name, caught, want_caught, missed, want_missing))
            print()

    print("=" * 60)
    if failures:
        print("README 引用檢查失敗（%d 項）：" % len(failures))
        for f in failures:
            print("  - %s" % f)
        print("  提示：%s" % HINT)
        return 1
    print("README 引用檢查通過：%d 個唯一 hex 全部存在於 repo（不 peel，型別不限）；"
          "另略過 %d 個不像短 sha 的候選" % (len(found), len(skipped)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
