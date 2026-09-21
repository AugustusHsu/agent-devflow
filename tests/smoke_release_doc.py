#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""devflow/RELEASING.md 的煙霧測試（issue #166 AC-10）。

從任何目錄執行（repo 根由 `__file__` 定位）：

    python3 tests/smoke_release_doc.py

只用標準庫，exit 0（全過）／1（有失敗）。**不是** unit test 框架：沒有 discovery、
沒有 fixture，就是「解析文件、跑一組斷言、數失敗」。

為什麼有這個檔：`RELEASING.md` 的價值在於**步驟順序**與**禁止指令**，而這兩件事在
review 時最容易被看漏——調換兩個步驟、或在 push 後面多一個旗標，肉眼掃過去都像對的。
`V5`（已發版本不移動、不刪、不重打）靠 GitHub 的 tag ruleset 擋 GitHub 端，本檔擋文件端：
不讓文件先教錯。

做法：把「解析 ＋ 斷言」寫成一個純函式 `check(text, label)` → 失敗清單。
正向案例餵真的 `devflow/RELEASING.md`；負向案例把同一份文字突變後寫進暫存目錄，
再讀回來餵**同一個** `check()`——負向案例不 subprocess 自己，正反兩邊跑的才保證是同一份斷言
（`R8` 的同一個道理：分不出來源的證據不算證據）。

每個負向案例除了「要 FAIL」之外，還宣告**恰好**哪幾條斷言該被觸發：只數「有失敗」會讓
「突變 A 卻是斷言 B 在擋」這種歸因錯誤混過去，也擋不住「某條斷言其實永遠在響」。
"""
import re
import sys
import tempfile
from collections import namedtuple
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "devflow" / "RELEASING.md"

# 步驟標題：`## 1.` ～ `## 5.`（AC-2）。
STEP_RE = re.compile(r"^##\s+(\d+)\.")

# 五個步驟的固定順序（AC-2）。
WANT_STEPS = [1, 2, 3, 4, 5]

# 步驟 1 的前置檢查四項，各自的可定位字串（AC-3／AC-10(b)）。
# 只認字串不認語意：語意要靠人讀，但「這四項有沒有寫進去」機器認得出來。
PRECHECK_NEEDLES = [
    ("工作樹乾淨", "git status --porcelain"),
    ("與 origin/main 同 sha", "origin/main"),
    ("VERSION 與 tag 名一致", "devflow/VERSION"),
    ("tag 尚不存在於遠端", "ls-remote"),
]

# 全文 bash 區塊的禁詞（AC-8／AC-10(d)）。禁止事項本身寫在散文裡（行內 code span），
# 不在 bash 區塊內——文件要講得出「不要做什麼」，同時不把那些指令擺成可以照抄的樣子。
FORBIDDEN = ["--force", "--tags", "tag -d"]

ASSERTIONS = {
    "a": "AC-10(a) 恰五個步驟標題，且順序為 1→5",
    "blocks": "AC-2 每個步驟恰一個 bash 區塊",
    "b": "AC-10(b) 步驟 1 的區塊含前置檢查四項",
    "c": "AC-10(c) 步驟 2 的區塊含 `git tag -a`",
    "d": "AC-10(d) 全文的 bash 區塊不含 %s" % "／".join(FORBIDDEN),
    "e": "AC-10(e) 步驟 3 的 push 指令只含 `refs/tags/`",
}

# fence_line：```bash 那一行的 1-indexed 行號；body 的第 k 行（0-indexed）＝檔案第
# fence_line + 1 + k 行。step：該區塊隸屬的步驟號（標題之前出現的區塊為 None）。
Block = namedtuple("Block", "fence_line body step")


def parse(text):
    """把文件拆成 (lines, steps, bash 區塊)。

    steps：[(步驟號, 標題行號, 標題原文)]；bash 區塊只收 ```bash，其他語言的 fence
    照樣吃掉（避免把 fence 內的內容誤當標題），但不進斷言。"""
    lines = text.split("\n")
    steps, blocks = [], []
    cur_step = None
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            fence_line = i + 1
            body = []
            i += 1
            while i < len(lines) and lines[i].strip() != "```":
                body.append(lines[i])
                i += 1
            if lang == "bash":
                blocks.append(Block(fence_line, body, cur_step))
            i += 1
            continue
        m = STEP_RE.match(lines[i])
        if m:
            cur_step = int(m.group(1))
            steps.append((cur_step, i + 1, lines[i].strip()))
        i += 1
    return lines, steps, blocks


def check(text, label):
    """跑全部斷言，回傳 [(斷言 id, 可定位的訊息)]；空清單＝全過。"""
    lines, steps, blocks = parse(text)
    fails = []

    def bad(aid, msg):
        fails.append((aid, msg))

    def at(block, offset):
        return "%s:%d" % (label, block.fence_line + 1 + offset)

    # (a) 恰五個步驟標題且順序 1→5
    nums = [n for n, _, _ in steps]
    if nums != WANT_STEPS:
        where = "；".join("%s:%d %s" % (label, ln, t) for _, ln, t in steps) or "（找不到任何步驟標題）"
        bad("a", "步驟標題是 %s，期望 %s → %s" % (nums, WANT_STEPS, where))

    # 每個步驟恰一個 bash 區塊（AC-2）
    for n in WANT_STEPS:
        own = [b for b in blocks if b.step == n]
        if len(own) != 1:
            bad("blocks", "步驟 %d 有 %d 個 bash 區塊，期望 1（%s）"
                % (n, len(own), "、".join("%s:%d" % (label, b.fence_line) for b in own) or "無"))

    def block_of(n):
        own = [b for b in blocks if b.step == n]
        return own[0] if own else None

    # (b) 步驟 1 含前置檢查四項
    b1 = block_of(1)
    if b1 is None:
        bad("b", "%s：找不到步驟 1 的 bash 區塊" % label)
    else:
        joined = "\n".join(b1.body)
        missing = [(name, needle) for name, needle in PRECHECK_NEEDLES if needle not in joined]
        for name, needle in missing:
            bad("b", "步驟 1 的區塊（%s:%d 起）缺「%s」的 `%s`"
                % (label, b1.fence_line + 1, name, needle))

    # (c) 步驟 2 含 `git tag -a`（annotated，不是 lightweight）
    b2 = block_of(2)
    if b2 is None:
        bad("c", "%s：找不到步驟 2 的 bash 區塊" % label)
    elif not any("git tag -a" in l for l in b2.body):
        bad("c", "步驟 2 的區塊（%s:%d 起）沒有 `git tag -a`" % (label, b2.fence_line + 1))

    # (d) 全文 bash 區塊不含禁詞
    for blk in blocks:
        for k, line in enumerate(blk.body):
            for tok in FORBIDDEN:
                if tok in line:
                    bad("d", "%s 出現禁詞 `%s`：%s" % (at(blk, k), tok, line.strip()))

    # (e) 步驟 3 的 push 指令只含 refs/tags/
    b3 = block_of(3)
    if b3 is None:
        bad("e", "%s：找不到步驟 3 的 bash 區塊" % label)
    else:
        pushes = [(k, l) for k, l in enumerate(b3.body) if "git push" in l]
        if not pushes:
            bad("e", "步驟 3 的區塊（%s:%d 起）沒有任何 `git push`" % (label, b3.fence_line + 1))
        for k, line in pushes:
            if "refs/tags/" not in line:
                bad("e", "%s 的 push 沒寫 `refs/tags/`：%s" % (at(b3, k), line.strip()))

    return fails


# ── 突變工具：都以 parse() 定位，不寫死文件的字面內容 ────────────────────────

def swap_headings(text, a, b):
    """對調兩個步驟的標題行（順序壞掉，內容不動）。"""
    lines = text.split("\n")
    _, steps, _ = parse(text)
    idx = {n: ln - 1 for n, ln, _ in steps}
    lines[idx[a]], lines[idx[b]] = lines[idx[b]], lines[idx[a]]
    return "\n".join(lines)


def edit_block_line(text, step, needle, transform):
    """把 step 的 bash 區塊裡第一條含 needle 的行交給 transform；回傳 None 表示刪掉該行。"""
    lines = text.split("\n")
    _, _, blocks = parse(text)
    own = [b for b in blocks if b.step == step]
    if not own:
        raise AssertionError("突變找不到步驟 %d 的 bash 區塊" % step)
    blk = own[0]
    for i in range(blk.fence_line, blk.fence_line + len(blk.body)):
        if needle in lines[i]:
            new = transform(lines[i])
            if new is None:
                del lines[i]
            else:
                lines[i] = new
            return "\n".join(lines)
    raise AssertionError("突變找不到目標行：步驟 %d 的區塊裡沒有含 %r 的行" % (step, needle))


# 負向案例：(名稱, 突變函式, 期望觸發的斷言 id 集合)
NEGATIVE = [
    ("步驟 4／5 標題對調",
     lambda t: swap_headings(t, 4, 5),
     {"a"}),
    ("步驟 3 的 push 加 --force",
     lambda t: edit_block_line(t, 3, "git push",
                               lambda l: l.replace("git push", "git push --force")),
     {"d"}),
    ("步驟 3 改成 push --tags（整批推）",
     lambda t: edit_block_line(t, 3, "git push", lambda l: "git push --tags origin"),
     {"d", "e"}),
    ("步驟 1 刪掉 ls-remote 那項檢查",
     lambda t: edit_block_line(t, 1, "ls-remote", lambda l: None),
     {"b"}),
    ("步驟 2 的 tag 改成 lightweight",
     lambda t: edit_block_line(t, 2, "git tag -a",
                               lambda l: l.replace("git tag -a", "git tag")),
     {"c"}),
]


def show(fails, marked=frozenset()):
    for aid, msg in fails:
        print("        %s [%s] %s" % ("←" if aid in marked else " ", aid, msg))


def main():
    if not DOC.exists():
        print("💥 找不到 %s" % DOC)
        return 1

    failures = []
    label = "devflow/RELEASING.md"
    text = DOC.read_text(encoding="utf-8")

    print("斷言清單：")
    for aid, desc in ASSERTIONS.items():
        print("  [%s] %s" % (aid, desc))
    print()

    # 正向：真的那一份，一條都不准失敗。有了這個，負向案例冒出來的失敗才有歸因。
    fails = check(text, label)
    _, steps, blocks = parse(text)
    good = not fails
    print("正向  %-30s 應過    %d 條失敗（期望 0）  %s"
          % (label, len(fails), "PASS" if good else "FAIL"))
    print("        步驟 %s；bash 區塊 %d 個"
          % ([n for n, _, _ in steps], len(blocks)))
    show(fails)
    if not good:
        failures.append("%s：%d 條斷言失敗" % (label, len(fails)))
    print()

    # 負向：突變後的副本放進暫存目錄，讀回來餵同一個 check()
    with tempfile.TemporaryDirectory() as tmp:
        for n, (name, mutate, expect) in enumerate(NEGATIVE):
            path = Path(tmp) / ("mutant-%02d.md" % n)
            path.write_text(mutate(text), encoding="utf-8")
            fails = check(path.read_text(encoding="utf-8"), str(path))
            fired = {aid for aid, _ in fails}
            good = bool(fails) and fired == expect
            print("負向  %-30s 應擋    觸發 %s（期望 %s）  %s"
                  % (name, sorted(fired) or "無", sorted(expect),
                     "PASS" if good else "FAIL"))
            show(fails, expect)
            if not good:
                failures.append("%s：觸發 %s，期望 %s"
                                % (name, sorted(fired) or "無", sorted(expect)))
            print()

    print("=" * 60)
    if failures:
        print("煙霧測試失敗（%d 項）：" % len(failures))
        for f in failures:
            print("  - %s" % f)
        return 1
    print("煙霧測試全部通過：1 個正向 ＋ %d 個負向案例（涵蓋 %d 條斷言）"
          % (len(NEGATIVE), len(ASSERTIONS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
