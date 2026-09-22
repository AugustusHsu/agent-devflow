#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""devflow/RELEASING.md 的煙霧測試（issue #166 AC-10）。

從任何目錄執行（repo 根由 `__file__` 定位）：

    python3 tests/smoke_release_doc.py

只用標準庫，exit 0（全過）／1（有失敗）／2（跑不起來）。**不是** unit test 框架：沒有
discovery、沒有 fixture，就是「解析文件、跑一組斷言、數失敗」。

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
另有一組**正向突變**（`POSITIVE`）：改完之後不該被擋的形狀。誤抓和漏抓一樣是關卡的洞
——會對合法寫法報紅的測試，最後會被人關掉（issue #173 R1-3）。
"""
import re
import shlex
import sys
import tempfile
import traceback
from collections import namedtuple
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "devflow" / "RELEASING.md"


# ── exit code：0 全過／1 有失敗／2 跑不起來（issue #173 R1-5） ──────────────────
# 和 scripts/devflow_checks.py 檔頭同一套守則：1 只有一個意思——被檢查的**內容**違規
# （發版程序被改壞）；2 是「這支測試本身跑不起來」。Python 對未攔截的例外預設以 1 結束，
# 會和內容違規撞號，讀 CI 的人分不出「文件寫錯」與「測試壞了」，而這兩件事的處置相反。
# SystemExit 不經 hook，所以 main() 的 return 0／1 不受影響。
def _uncaught(exc_type, exc, tb):
    try:
        sys.stdout.flush()
        traceback.print_exception(exc_type, exc, tb)
        print("💥 煙霧測試無法執行：未預期的 %s: %s（未分類的例外一律 exit 2，不是內容違規）"
              % (exc_type.__name__, exc))
        sys.stdout.flush()
    finally:
        sys.exit(2)               # 連印訊息都失敗也要是 2，不能退回 Python 預設的 1


sys.excepthook = _uncaught

# 步驟標題：`## 1.` ～ `## 5.`（AC-2）。
STEP_RE = re.compile(r"^##\s+(\d+)\.")

# 疑似步驟標題、但格式不認（`## 1)`、`## 1、`）。只在 (a) 已經失敗時當線索印出來，
# 讓「步驟 1 不見了」直接指到那一行，而不是讓人自己去找（issue #173 R1-4）。
NEAR_STEP_RE = re.compile(r"^##\s*\d")

# `#`／`##` 標題結束上一個步驟的射程（`###` 以下算步驟內的小節）。不重設的話，
# 「失敗處置」段裡貼一個示範區塊會被算進步驟 5，報成「步驟 5 有 2 個 bash 區塊」
# ——文件沒錯，是解析錯（issue #173 R1-3）。
HEADING_RE = re.compile(r"^#{1,2}\s")

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

# 全文 bash 區塊的禁止寫法（AC-8／AC-10(d)）。禁止事項本身寫在散文裡（行內 code span），
# 不在 bash 區塊內——文件要講得出「不要做什麼」，同時不把那些指令擺成可以照抄的樣子。
#
# 封閉清單（issue #173 R1-1）：原本的 `--force`／`--tags`／`tag -d` 三項保留，另補四種
# 等價寫法。比對以 token／regex 為準而不是 substring，因為兩個方向都會錯：
#   * 漏抓——`-f`、`+refs/`、`:refs/tags/` 和 `--force` 等價，substring 清單全放行。
#   * 誤抓——步驟 4 的 `trap 'rm -f "$vj"' EXIT` 裡也有 `-f`，那不是 push 旗標。
# 所以 `-f`／`-d` 這種短旗標一律綁在它所屬的指令上（`git push`／`git tag`），`[^|;&]*`
# 讓比對不跨過 `|`、`;`、`&` 到下一個指令去。`--force-with-lease` 另立一條：token 比對
# 之後它不再被 `--force` 命中（後面接的是 `-`），要顯式保留才擋得住。
FORBIDDEN = [
    ("`--force`", re.compile(r"(?<![\w-])--force(?![\w-])")),
    ("`--force-with-lease`", re.compile(r"(?<![\w-])--force-with-lease\b")),
    ("`--tags`", re.compile(r"(?<![\w-])--tags(?![\w-])")),
    ("`git tag -d`", re.compile(r"\bgit\s+tag\b[^|;&]*(?<![\w-])-[A-Za-z]*d[A-Za-z]*(?![\w-])")),
    ("`git tag -f`", re.compile(r"\bgit\s+tag\b[^|;&]*(?<![\w-])-[A-Za-z]*f[A-Za-z]*(?![\w-])")),
    ("push 的 `-f` 旗標", re.compile(r"\bgit\s+push\b[^|;&]*(?<![\w-])-[A-Za-z]*f[A-Za-z]*(?![\w-])")),
    ("強制 refspec `+refs/`", re.compile(r"\+refs/")),
    ("遠端刪除的空 refspec `:refs/`", re.compile(r"\bgit\s+push\b[^|;&]*\s[\"']?:refs/")),
]

# 步驟 3 唯一該出現的 refspec，逐字（issue #173 R2-4(e)）。推到別的 tag 名、或在後面
# 多掛一個 refspec（`git push origin "refs/tags/$tag" main`），都不是「只推這一個 tag」。
WANT_REFSPEC = '"refs/tags/$tag"'

# 以 `\` 收尾的行與下一行屬同一條語句（步驟 1 的四項檢查多是這個形狀）。
CONT_RE = re.compile(r"\\\s*$")
# 整行註解：比對前先丟掉。把檢查行原樣註解掉之後字串還在，substring 比對分不出差別
# （issue #173 R1-2）。
COMMENT_RE = re.compile(r"^\s*#")
# 「這條語句是個會中止的檢查」：以 `|| fail …` 或等效的 `|| { …; exit 1; }` 收尾。
# 只出現在 `echo` 裡的字串不是檢查——`|| fail` 換成 `|| echo`，文件就從「擋下」變成
# 「印一行繼續跑」，而四個字串一個都沒少。
FAIL_TAIL_RE = re.compile(r"\|\|\s*(fail\b.*|\{.*\bexit\s+1\b.*\})\s*$")

ASSERTIONS = {
    "a": "AC-10(a) 恰五個步驟標題，且順序為 1→5",
    "blocks": "AC-2 每個步驟恰一個 bash 區塊（fence 須逐字 ```bash）",
    "b": "AC-10(b) 步驟 1 的區塊含前置檢查四項，且各在一條 `|| fail` 檢查語句內",
    "c": "AC-10(c) 步驟 2 的區塊含 `git tag -a`",
    "d": "AC-10(d) 全文的 bash 區塊不含 %s" % "／".join(n for n, _ in FORBIDDEN),
    "e": "AC-10(e) 步驟 3 的 push refspec 恰為 %s" % WANT_REFSPEC,
}

# fence_line：``` 那一行的 1-indexed 行號；body 的第 k 行（0-indexed）＝檔案第
# fence_line + 1 + k 行。lang：fence 的 info string 原文（``` 後面整串，可能是空字串、
# `bash`、`sh`、`bash title=x`）。step：該區塊隸屬的步驟號（不在任何步驟內者為 None）。
Fence = namedtuple("Fence", "fence_line lang body step")


def bash_blocks(fences):
    """只認逐字 ```bash 的 fence。語言不認的那些要留著，才報得出「是 info string 的問題」
    而不是「這一步沒有區塊」（issue #173 R1-4）。"""
    return [f for f in fences if f.lang == "bash"]


def statements(body):
    """把區塊內容切成邏輯語句：[(涵蓋的 body offset 清單, 併起來的一行文字)]。

    先丟掉整行註解，再把以 `\\` 收尾的行與下一行併起來。"""
    out = []
    idx, txt = [], []
    for k, line in enumerate(body):
        if COMMENT_RE.match(line):
            continue
        idx.append(k)
        txt.append(CONT_RE.sub("", line).strip())
        if not CONT_RE.search(line):
            out.append((idx, " ".join(t for t in txt if t)))
            idx, txt = [], []
    if idx:
        out.append((idx, " ".join(t for t in txt if t)))
    return out


def parse(text):
    """把文件拆成 (lines, steps, near, fences)。

    steps：[(步驟號, 標題行號, 標題原文)]；near：疑似步驟標題但格式不認的 [(行號, 原文)]；
    fences：**所有** fence（含非 bash 的），fence 內的內容不會被誤當成標題。"""
    lines = text.split("\n")
    steps, near, fences = [], [], []
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
            fences.append(Fence(fence_line, lang, body, cur_step))
            i += 1
            continue
        m = STEP_RE.match(lines[i])
        if m:
            cur_step = int(m.group(1))
            steps.append((cur_step, i + 1, lines[i].strip()))
        elif HEADING_RE.match(lines[i]):
            if NEAR_STEP_RE.match(lines[i]):
                near.append((i + 1, lines[i].strip()))
            cur_step = None
        i += 1
    return lines, steps, near, fences


def check(text, label):
    """跑全部斷言，回傳 [(斷言 id, 可定位的訊息)]；空清單＝全過。"""
    lines, steps, near, fences = parse(text)
    blocks = bash_blocks(fences)
    fails = []

    def bad(aid, msg):
        fails.append((aid, msg))

    def at(block, offset):
        return "%s:%d" % (label, block.fence_line + 1 + offset)

    # (a) 恰五個步驟標題且順序 1→5
    nums = [n for n, _, _ in steps]
    if nums != WANT_STEPS:
        where = "；".join("%s:%d %s" % (label, ln, t) for _, ln, t in steps) or "（找不到任何步驟標題）"
        hint = ""
        if near:
            hint = "；疑似步驟標題但格式不認（須逐字 `## N.`）：" + \
                   "；".join("%s:%d %s" % (label, ln, t) for ln, t in near)
        bad("a", "步驟標題是 %s，期望 %s → %s%s" % (nums, WANT_STEPS, where, hint))

    # 每個步驟恰一個 bash 區塊（AC-2）
    for n in WANT_STEPS:
        own = [b for b in blocks if b.step == n]
        if len(own) == 1:
            continue
        other = [f for f in fences if f.step == n and f.lang != "bash"]
        if not own and other:
            bad("blocks", "步驟 %d 的 fence 語言／info string 不認（只認逐字的 ```bash）：%s"
                % (n, "、".join("%s:%d 是 ```%s" % (label, f.fence_line, f.lang or "（空）")
                                for f in other)))
            continue
        bad("blocks", "步驟 %d 有 %d 個 bash 區塊，期望 1（%s）"
            % (n, len(own), "、".join("%s:%d" % (label, b.fence_line) for b in own) or "無"))

    def block_of(n):
        own = [b for b in blocks if b.step == n]
        return own[0] if own else None

    # (b) 步驟 1 含前置檢查四項，而且每一項都在一條真的會中止的檢查語句裡
    b1 = block_of(1)
    if b1 is None:
        bad("b", "%s：找不到步驟 1 的 bash 區塊" % label)
    else:
        stmts = statements(b1.body)
        checks = [txt for _, txt in stmts if FAIL_TAIL_RE.search(txt)]
        for name, needle in PRECHECK_NEEDLES:
            if any(needle in txt for txt in checks):
                continue
            if any(needle in txt for _, txt in stmts):
                why = "——字串在，但不在一條以 `|| fail`（或 `|| { …; exit 1; }`）收尾的檢查語句內"
            elif any(needle in l for l in b1.body):
                why = "——字串只出現在註解行裡"
            else:
                why = ""
            bad("b", "步驟 1 的區塊（%s:%d 起）缺「%s」的 `%s`%s"
                % (label, b1.fence_line + 1, name, needle, why))

    # (c) 步驟 2 含 `git tag -a`（annotated，不是 lightweight）
    b2 = block_of(2)
    if b2 is None:
        bad("c", "%s：找不到步驟 2 的 bash 區塊" % label)
    elif not any("git tag -a" in l for l in b2.body):
        bad("c", "步驟 2 的區塊（%s:%d 起）沒有 `git tag -a`" % (label, b2.fence_line + 1))

    # (d) 全文 bash 區塊不含禁止寫法
    for blk in blocks:
        for k, line in enumerate(blk.body):
            for name, pat in FORBIDDEN:
                if pat.search(line):
                    bad("d", "%s 出現禁止寫法 %s：%s" % (at(blk, k), name, line.strip()))

    # (e) 步驟 3 的 push refspec 逐字 `"refs/tags/$tag"`，而且只有這一個
    b3 = block_of(3)
    if b3 is None:
        bad("e", "%s：找不到步驟 3 的 bash 區塊" % label)
    else:
        pushes = [(k, l) for k, l in enumerate(b3.body) if "git push" in l]
        if not pushes:
            bad("e", "步驟 3 的區塊（%s:%d 起）沒有任何 `git push`" % (label, b3.fence_line + 1))
        for k, line in pushes:
            try:
                # posix=False 保留引號，`"refs/tags/$tag"` 才比對得了逐字
                toks = shlex.split(line.strip(), posix=False)
            except ValueError as exc:
                bad("e", "%s 的 push 行拆不開（%s）：%s" % (at(b3, k), exc, line.strip()))
                continue
            pos = next((j for j in range(len(toks) - 1)
                        if toks[j] == "git" and toks[j + 1] == "push"), None)
            if pos is None:
                bad("e", "%s 有 `git push` 字樣卻拆不出 push 指令：%s" % (at(b3, k), line.strip()))
                continue
            args = [t for t in toks[pos + 2:] if not t.startswith("-")]
            refspecs = args[1:]                      # args[0] 是 remote
            if refspecs != [WANT_REFSPEC]:
                bad("e", "%s 的 push refspec 是 %s，期望恰一個 %s：%s"
                    % (at(b3, k), refspecs or "（無）", WANT_REFSPEC, line.strip()))

    return fails


# ── 突變工具：都以 parse() 定位，不寫死文件的字面內容 ────────────────────────

def swap_headings(text, a, b):
    """對調兩個步驟的標題行（順序壞掉，內容不動）。"""
    lines = text.split("\n")
    _, steps, _, _ = parse(text)
    idx = {n: ln - 1 for n, ln, _ in steps}
    lines[idx[a]], lines[idx[b]] = lines[idx[b]], lines[idx[a]]
    return "\n".join(lines)


def break_heading(text, step):
    """把 `## N.` 改成 `## N)`：看起來像步驟標題，解析器不認。"""
    lines = text.split("\n")
    _, steps, _, _ = parse(text)
    i = {n: ln - 1 for n, ln, _ in steps}[step]
    lines[i] = lines[i].replace("%d." % step, "%d)" % step, 1)
    return "\n".join(lines)


def retag_fence(text, step, lang):
    """把某一步的 ```bash 換成別的 info string（語言不認，或多帶了東西）。"""
    lines = text.split("\n")
    _, _, _, fences = parse(text)
    blk = block_by_step(fences, step)
    lines[blk.fence_line - 1] = "```" + lang
    return "\n".join(lines)


def block_by_step(fences, step):
    own = [b for b in bash_blocks(fences) if b.step == step]
    if not own:
        raise AssertionError("突變找不到步驟 %d 的 bash 區塊" % step)
    return own[0]


def edit_block_line(text, step, needle, transform):
    """把 step 的 bash 區塊裡第一條含 needle 的行交給 transform；回傳 None 表示刪掉該行。"""
    lines = text.split("\n")
    _, _, _, fences = parse(text)
    blk = block_by_step(fences, step)
    for i in range(blk.fence_line, blk.fence_line + len(blk.body)):
        if needle in lines[i]:
            new = transform(lines[i])
            if new is None:
                del lines[i]
            else:
                lines[i] = new
            return "\n".join(lines)
    raise AssertionError("突變找不到目標行：步驟 %d 的區塊裡沒有含 %r 的行" % (step, needle))


def find_checks(text, step, needle):
    """回傳 [(區塊, 該條語句涵蓋的 body offset)]：步驟 step 裡**每一條**「含 needle 且以
    `|| fail` 收尾」的檢查語句。

    同一項前置檢查可能寫成兩條語句（先把輸出接進變數、再判斷），只動第一條會留下另一條，
    突變就沒有真的把那項檢查拿掉，負向案例也就證明不了什麼。"""
    _, _, _, fences = parse(text)
    blk = block_by_step(fences, step)
    hits = [(blk, idx) for idx, txt in statements(blk.body)
            if needle in txt and FAIL_TAIL_RE.search(txt)]
    if not hits:
        raise AssertionError("突變找不到步驟 %d 裡含 %r 的 `|| fail` 檢查" % (step, needle))
    return hits


def demote_check(text, step, needle):
    """把那些檢查的 `|| fail` 降成 `|| echo`：語句在、字串也在，只是不再中止。"""
    lines = text.split("\n")
    for blk, idx in find_checks(text, step, needle):
        for k in idx:
            i = blk.fence_line + k
            if "|| fail" in lines[i]:
                lines[i] = lines[i].replace("|| fail", "|| echo")
    return "\n".join(lines)


def comment_out_check(text, step, needle):
    """把那些檢查整條註解掉：字串仍逐字留在文件裡，檢查沒了。"""
    lines = text.split("\n")
    for blk, idx in find_checks(text, step, needle):
        for k in idx:
            lines[blk.fence_line + k] = "# " + lines[blk.fence_line + k]
    return "\n".join(lines)


def drop_check(text, step, needle):
    """整條檢查語句刪掉（含 `\\` 續行）。"""
    lines = text.split("\n")
    drop = set()
    for blk, idx in find_checks(text, step, needle):
        drop |= {blk.fence_line + k for k in idx}
    return "\n".join(l for n, l in enumerate(lines) if n not in drop)


def append_to_block(text, step, snippet):
    """在某一步的 bash 區塊末尾補一行。"""
    lines = text.split("\n")
    _, _, _, fences = parse(text)
    blk = block_by_step(fences, step)
    end = blk.fence_line + len(blk.body)          # 收尾的 ``` 那行（0-indexed）
    return "\n".join(lines[:end] + [snippet] + lines[end:])


def duplicate_block(text, step):
    """把某一步的 bash 區塊原樣再貼一次（內容不變，就是多一個區塊）。"""
    lines = text.split("\n")
    _, _, _, fences = parse(text)
    blk = block_by_step(fences, step)
    start = blk.fence_line - 1                    # ```bash 那行（0-indexed）
    end = blk.fence_line + len(blk.body)          # 收尾的 ``` 那行（0-indexed）
    dup = lines[start:end + 1]
    return "\n".join(lines[:end + 1] + [""] + dup + lines[end + 1:])


def append_block(text, snippet):
    """在文件尾端（「失敗處置」段內）貼一個示範用的 bash 區塊。"""
    return text.rstrip("\n") + "\n\n```bash\n%s\n```\n" % snippet


# 負向案例：(名稱, 突變函式, 期望觸發的斷言 id 集合)
NEGATIVE = [
    ("步驟 4／5 標題對調",
     lambda t: swap_headings(t, 4, 5),
     {"a"}),
    ("步驟 1 標題改成 `## 1)`（格式不認）",
     lambda t: break_heading(t, 1),
     {"a", "blocks", "b"}),
    ("步驟 4 的 fence 改成 ```sh",
     lambda t: retag_fence(t, 4, "sh"),
     {"blocks"}),
    ("步驟 4 的 fence 帶 info string（```bash title=…）",
     lambda t: retag_fence(t, 4, 'bash title="發版"'),
     {"blocks"}),
    ("步驟 2 的區塊整個貼兩次",
     lambda t: duplicate_block(t, 2),
     {"blocks"}),
    ("步驟 3 的 push 加 --force",
     lambda t: edit_block_line(t, 3, "git push",
                               lambda l: l.replace("git push", "git push --force")),
     {"d"}),
    ("步驟 3 的 push 加 -f",
     lambda t: edit_block_line(t, 3, "git push",
                               lambda l: l.replace("git push", "git push -f")),
     {"d"}),
    ("步驟 3 的 push 加 --force-with-lease",
     lambda t: edit_block_line(t, 3, "git push",
                               lambda l: l.replace("git push", "git push --force-with-lease")),
     {"d"}),
    ("步驟 3 改成 push --tags（整批推）",
     lambda t: edit_block_line(t, 3, "git push", lambda l: "git push --tags origin"),
     {"d", "e"}),
    ("步驟 1 的 fetch 改成強制 refspec（+refs/）",
     lambda t: edit_block_line(t, 1, "git fetch",
                               lambda l: "git fetch --quiet origin '+refs/heads/main:refs/remotes/origin/main'"),
     {"d"}),
    ("步驟 2 補一行遠端刪除（push origin :refs/tags/）",
     lambda t: append_to_block(t, 2, 'git push origin ":refs/tags/$tag"'),
     {"d"}),
    ("步驟 2 補一行 git tag -f（原地重打）",
     lambda t: append_to_block(t, 2, 'git tag -f "$tag" "$sha"'),
     {"d"}),
    ("步驟 2 補一行 git tag -d（刪了重打）",
     lambda t: append_to_block(t, 2, 'git tag -d "$tag"'),
     {"d"}),
    ("步驟 3 的 push 多掛一個 refspec（… main）",
     lambda t: edit_block_line(t, 3, "git push", lambda l: l.rstrip() + " main"),
     {"e"}),
    ("步驟 3 推到寫死的別的 tag 名",
     lambda t: edit_block_line(t, 3, "git push",
                               lambda l: 'git push origin "refs/tags/v0.0.0.1"'),
     {"e"}),
    ("步驟 1 刪掉 ls-remote 那項檢查",
     lambda t: drop_check(t, 1, "ls-remote"),
     {"b"}),
    ("步驟 1 的工作樹檢查 `|| fail` 換成 `|| echo`",
     lambda t: demote_check(t, 1, "git status --porcelain"),
     {"b"}),
    ("步驟 1 的工作樹檢查整條註解掉",
     lambda t: comment_out_check(t, 1, "git status --porcelain"),
     {"b"}),
    ("步驟 2 的 tag 改成 lightweight",
     lambda t: edit_block_line(t, 2, "git tag -a",
                               lambda l: l.replace("git tag -a", "git tag")),
     {"c"}),
]

# 正向突變：改完之後**不該**被擋的形狀。誤抓也是洞——會對合法寫法報紅的關卡，
# 最後會被人關掉（issue #173 R1-1 的 `rm -f`、R1-3 的示範區塊）。
POSITIVE = [
    ("「失敗處置」段貼一個示範 bash 區塊（不屬任何步驟）",
     lambda t: append_block(t, "gh workflow run docs.yml --ref main -f tag=v0.0.0.1")),
    ("步驟 1 補一行 rm -f（不是 push 旗標）",
     lambda t: append_to_block(t, 1, 'rm -f "$tmpfile"')),
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
    _, steps, _, fences = parse(text)
    good = not fails
    print("正向  %-30s 應過    %d 條失敗（期望 0）  %s"
          % (label, len(fails), "PASS" if good else "FAIL"))
    print("        步驟 %s；bash 區塊 %d 個（fence 共 %d 個）"
          % ([n for n, _, _ in steps], len(bash_blocks(fences)), len(fences)))
    show(fails)
    if not good:
        failures.append("%s：%d 條斷言失敗" % (label, len(fails)))
    print()

    with tempfile.TemporaryDirectory() as tmp:
        # 正向突變：合法的改法不准被擋
        for n, (name, mutate) in enumerate(POSITIVE):
            path = Path(tmp) / ("positive-%02d.md" % n)
            path.write_text(mutate(text), encoding="utf-8")
            fails = check(path.read_text(encoding="utf-8"), str(path))
            good = not fails
            print("正向突變 %-27s 應過    %d 條失敗（期望 0）  %s"
                  % (name, len(fails), "PASS" if good else "FAIL"))
            show(fails)
            if not good:
                failures.append("%s：誤擋，觸發 %s" % (name, sorted({a for a, _ in fails})))
            print()

        # 負向：突變後的副本放進暫存目錄，讀回來餵同一個 check()
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

    # 涵蓋數由負向案例的期望集合聯集算出來，不是 len(ASSERTIONS)：後者只是「有幾條斷言」，
    # 寫成「涵蓋 N 條」會把沒有任何負向案例的斷言也算進去（issue #173 R2-5）。
    covered = set()
    for _, _, expect in NEGATIVE:
        covered |= expect
    uncovered = sorted(set(ASSERTIONS) - covered)

    print("=" * 60)
    if failures:
        print("煙霧測試失敗（%d 項）：" % len(failures))
        for f in failures:
            print("  - %s" % f)
        return 1
    print("煙霧測試全部通過：1 個正向 ＋ %d 個正向突變 ＋ %d 個負向案例"
          % (len(POSITIVE), len(NEGATIVE)))
    print("  負向案例涵蓋 %d 條斷言：%s%s"
          % (len(covered), "、".join(sorted(covered)),
             "；未涵蓋：" + "、".join(uncovered) if uncovered else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
