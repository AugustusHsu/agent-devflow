#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""README.md 引用的 7 位 hex 都要在 repo 裡存在（issue #166 AC-11）。

從任何目錄執行（repo 根由 `__file__` 定位，git 指令一律在 repo 根跑）：

    python3 tests/smoke_readme_refs.py

只用標準庫，exit 0（全部存在）／1（有缺）。

為什麼有這個檔：README 的事實表與「Phase 1 第三出口的判定方式」把證據記成 7 位 hex
（「證據欄只記能用 gh／git 讀回的識別碼」）。這些 hash 打錯一個字元、或指向一個後來
不存在的物件，讀的人不會發現——它看起來就像一個 hash。這個檔讓它變成會紅的 CI。

**不 peel、任何物件型別皆可**（issue #166 的 L3 裁決）：README 引的 hash 有 commit、
也有 blob（Phase 1 判定表的 `checker_blob`，正反兩個 run 比的就是它）與 tree
（「兩個 commit 的 tree 相同」那句），四種都是事實，都該被保護。所以判準是
`git cat-file -e <hex>`，不加 `^{commit}`／`^{tag}`。

**排除 code fence 內的行**：fence 裡是範例與佈局圖，裡面的 hash 不是本 repo 的證據。

不斷言「恰 N 個」：README 每加一筆證據就會多一個 hash，把數字寫死只會讓無關的 PR 變紅。
數量印在輸出裡供人核對（本檔寫成時是 25 個唯一值）。
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"

# 反引號包住的 7 位小寫 hex。前後要是反引號，所以 `8029dfa12092…`（全長 sha）不會被切成 7 碼。
HEX_RE = re.compile(r"`([0-9a-f]{7})`")

# 缺物件時印的提示：README 引的 probe commit 只活在 PR 的 head ref，
# 一般 clone（含 CI 的 fetch-depth: 0，它只取 refs/heads/* 與 refs/tags/*）不會帶它。
HINT = ("若缺的是 PR 的 probe commit，先 "
        "git fetch origin '+refs/pull/*/head:refs/remotes/origin/pr/*'")


def extract(text):
    """回傳 {hex: [行號, …]}，跳過 code fence 內的行。"""
    found = {}
    in_fence = False
    for n, line in enumerate(text.split("\n"), 1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for m in HEX_RE.finditer(line):
            found.setdefault(m.group(1), []).append(n)
    return found


def git(args):
    """在 repo 根跑 git，回傳 (returncode, stdout)。cwd 固定，所以從哪裡呼叫都一樣。"""
    p = subprocess.run(["git"] + args, cwd=str(REPO),
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return p.returncode, p.stdout.decode("utf-8", "replace").strip()


def check(text):
    """回傳 (found, missing)：found 是 {hex: [行號]}，missing 是缺的 [(hex, [行號])]。

    正負案例共用這一個函式：負向案例餵的是暫存目錄裡的突變副本，不另外 subprocess
    自己，正反兩邊跑的才保證是同一套判準。"""
    found = extract(text)
    missing = [(h, lines) for h, lines in sorted(found.items())
               if git(["cat-file", "-e", h])[0] != 0]
    return found, missing


def report(label, found, missing):
    """印出這一輪的明細；回傳 True＝全部存在。"""
    for h, lines in sorted(found.items()):
        where = "、".join("%s:%d" % (label, n) for n in lines)
        if any(h == m for m, _ in missing):
            print("        ✗ %s  缺（%s）" % (h, where))
        else:
            print("        · %s  %-6s %s" % (h, git(["cat-file", "-t", h])[1], where))
    return not missing


def main():
    if not README.exists():
        print("💥 找不到 %s" % README)
        return 1

    failures = []
    label = "README.md"
    text = README.read_text(encoding="utf-8")

    # 正向：真的那一份 README
    found, missing = check(text)
    good = not missing
    print("正向  %-34s 應過    %d 個唯一 hex、%d 個缺（期望 0）  %s"
          % (label, len(found), len(missing), "PASS" if good else "FAIL"))
    report(label, found, missing)
    if not good:
        failures.append("%s：%d 個 hex 在 repo 裡找不到（%s）"
                        % (label, len(missing), "、".join(h for h, _ in missing)))
    print()

    # 負向與「fence 內不該被抓」的反向保證：突變副本放進暫存目錄，讀回來餵同一個 check()
    fake = "deadbee"
    with tempfile.TemporaryDirectory() as tmp:
        cases = [
            ("散文裡塞一個不存在的 hex",
             text + "\n\n假的證據：`%s`。\n" % fake,
             True),
            ("同一個 hex 放進 code fence 內（不該被抓）",
             text + "\n\n```\n假的證據：`%s`。\n```\n" % fake,
             False),
        ]
        for n, (name, mutated, want_fail) in enumerate(cases):
            path = Path(tmp) / ("mutant-%02d.md" % n)
            path.write_text(mutated, encoding="utf-8")
            mfound, mmissing = check(path.read_text(encoding="utf-8"))
            caught = fake in mfound
            failed = bool(mmissing)
            good = (failed == want_fail) and (caught == want_fail)
            print("%s  %-34s %s  抓到 %s＝%s、缺 %d 個  %s"
                  % ("負向" if want_fail else "正向", name,
                     "應擋" if want_fail else "應過", fake, caught, len(mmissing),
                     "PASS" if good else "FAIL"))
            for h, _ in mmissing:
                print("        ✗ %s" % h)
            if not good:
                failures.append("%s：抓到=%s、缺 %d 個，期望%s"
                                % (name, caught, len(mmissing),
                                   "抓到且缺" if want_fail else "不抓也不缺"))
            print()

    print("=" * 60)
    if failures:
        print("README 引用檢查失敗（%d 項）：" % len(failures))
        for f in failures:
            print("  - %s" % f)
        print("  提示：%s" % HINT)
        return 1
    print("README 引用檢查通過：%d 個唯一 hex 全部存在於 repo（不 peel，型別不限）"
          % len(found))
    return 0


if __name__ == "__main__":
    sys.exit(main())
