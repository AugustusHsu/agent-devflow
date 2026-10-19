#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""#316 準備階段（`L7`）分工契約的專項驗證器。

用法（一律 `/usr/bin/python3`，stdlib only）：

    /usr/bin/python3 tests/smoke_prep_roles.py contract <root>
    /usr/bin/python3 tests/smoke_prep_roles.py entrust <委託稿檔>
    /usr/bin/python3 tests/smoke_prep_roles.py selftest <root>

為什麼有這個檔：#316 把「有／無 `manager` 的建立／啟動責任分流」「常設且明確委託的準備
階段（`L7`）及其 `L1` 邊界與最低委託七欄」「階段事實一事一發布者」同時寫進規則本體
（`devflow/WORKFLOW.md`）與其實作（兩個職位檔、orchestrator 的 SKILL、兩個通道範本）。
七個檔講同一件事＝七個可以各自寫錯的地方，所以每條義務給一個 OB-ID 機械驗，並以 `selftest`
的突變矩陣證明每條義務真的擋得住對應的寫錯法（否則「全 PASS」只證明檢查沒在看）。

退出碼三態，不混用：
  0  全部義務 PASS（`selftest`：全部案例 OK）
  1  至少一條義務 FAIL（內容違規）／`selftest` 至少一案不符預期
  2  跑不起來：缺檔、缺**既有**段落、突變字面對不上（環境／契約漂移，不是內容違規）

「缺段落＝2」只適用於 base 就存在的結構（seats 的五段、SKILL 的 `### 1.`～`### 3.`、
WORKFLOW 的 frontmatter 與 `I2`／`L6`／`## 5.`、兩範本的里程碑段落錨點）。本單**新增**的
東西（`L7` 條、`### 0.`、manager 的準備條、發布者欄）一律是義務：缺了要報 FAIL 而不是 2，
否則 base 會以 2 結束，`L1` 要求的「對未達成候選實跑得到不同輸出」就拿不到 rc 1 的證據。
"""

import os
import re
import sys
import traceback

EXIT_OK = 0
EXIT_VIOLATION = 1
EXIT_ENV = 2

try:                                    # 輸出含中文；LANG=C 時不讓它死在編碼上
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:                       # pragma: no cover（舊版 Python 沒有 reconfigure）
    pass

# ── 受檢的七個檔（第八檔是本檔自己，不自檢） ──────────────────────────────
WF = "devflow/WORKFLOW.md"
KIT = "devflow/VERSION"
COOR = "devflow/seats/coordinator.md"
MGR = "devflow/seats/manager.md"
SKILL = "devflow/orchestrators/hermes/SKILL.md"
TPLC = "devflow/channels/templates/coordinator.md"
TPLM = "devflow/channels/templates/manager.md"
FILES = (WF, KIT, COOR, MGR, SKILL, TPLC, TPLM)

WF_VERSION = "1.17.0.0"
KIT_VERSION = "0.19.0.0"

# 禁止集合八項：(字面, ID 用的 slug)。slug 不含空白，讓 OB-ID 可以用空白切欄。
FORBID = (
    ("派實作位", "派實作位"),
    ("派審查位", "派審查位"),
    ("建 worktree", "建worktree"),
    ("建任務分支", "建任務分支"),
    ("開 PR", "開PR"),
    ("合併", "合併"),
    ("修改受版控檔", "修改受版控檔"),
    ("改設定", "改設定"),
)

# 最低委託七欄：(欄名, slug)
FIELDS = (
    ("單號", "單號"),
    ("問題與目標", "問題與目標"),
    ("固定 G", "固定G"),
    ("允許讀寫範圍", "允許讀寫範圍"),
    ("禁止事項", "禁止事項"),
    ("交付落點", "交付落點"),
    ("回報出口", "回報出口"),
)

# 四個階段事實與**權威期望值** (已綁定, 未綁定)。兩範本同步改錯仍要擋下來，
# 所以兩邊各自對照這張表，再比對彼此一致（CONSIST）。
EVENTS = ("PR 開出", "每輪 verdict", "合併完成", "封存完成")
PUB_EXPECT = {
    "PR 開出": ("執行位", "協調位"),
    "每輪 verdict": ("執行位", "協調位"),
    "合併完成": ("協調位", "協調位"),
    "封存完成": ("協調位", "協調位"),
}

BOUND_OK = ("該位", "執行位", "manager")
UNBOUND_OK = ("本位", "協調位")

# ── 固定文法：抽 (bound, unbound) 的行為人 ────────────────────────────────
# 兼容既有語序：coordinator.md 的「`manager` 已綁定時，派審由該位執行…；未綁定時由本位
# 執行」與能力段的「**未綁定 `manager` 時：**」。`[^。；\n]` 讓比對不跨句、不跨行——
# 跨句會把隔壁條的行為人讀進來，那是比漏檢更壞的誤判。
BOUND_RE = re.compile(r"manager`?\s*[^。；\n]{0,30}?已綁定時[^。；\n]{0,30}?由(該位|執行位|manager|本位|協調位)")
UNBOUND_RE = re.compile(r"未綁定(?:\s*`?manager`?\s*)?時[^。；\n]{0,30}?由(本位|協調位|該位|執行位)")
NOMGR_RE = re.compile(r"未綁定\s*`manager`\s*時")

SEAT_SECTIONS = ("## 職責", "## 產出物", "## 禁止", "## 規則義務", "## 填充者須具備的能力")

BLANKS = " \t\u3000\r"


class EnvError(Exception):
    """跑不起來（exit 2）：缺檔、缺既有段落。"""


class MutError(Exception):
    """突變的字面對不上（exit 2）：產品文字漂移，突變矩陣失效。"""


def _uncaught(exc_type, exc, tb):
    try:
        traceback.print_exception(exc_type, exc, tb)
        print("💥 本檢查無法執行：未預期的 %s: %s（未分類的例外一律 exit 2，不是內容違規）"
              % (exc_type.__name__, exc))
        sys.stdout.flush()
    finally:
        sys.exit(EXIT_ENV)


sys.excepthook = _uncaught


# ── 讀檔與切段 ────────────────────────────────────────────────────────────
def load(root):
    out = {}
    for rel in FILES:
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            raise EnvError("缺檔：%s（root=%s）" % (rel, root))
        with open(path, encoding="utf-8") as fh:
            out[rel] = fh.read()
    return out


def numbered(text):
    return [(i + 1, line) for i, line in enumerate(text.split("\n"))]


def seat_sections(text, rel):
    """切職位檔的五段，回 {標題: [(行號, 原文), ...]}。缺任一段＝exit 2。"""
    lines = text.split("\n")
    heads = [i for i, line in enumerate(lines) if line.startswith("## ")]
    idx = {}
    for i, line in enumerate(lines):
        if line.strip() in SEAT_SECTIONS:
            idx[line.strip()] = i
    missing = [h for h in SEAT_SECTIONS if h not in idx]
    if missing:
        raise EnvError("%s 缺段落：%s" % (rel, "／".join(missing)))
    out = {}
    for head, i in idx.items():
        end = next((j for j in heads if j > i), len(lines))
        out[head] = [(k + 1, lines[k]) for k in range(i + 1, end)]
    return out


def skill_sections(text):
    """切 SKILL 的 `### <n>.` 小節，回 {編號: [(行號, 原文), ...]}。`1`～`3` 缺＝exit 2。"""
    lines = text.split("\n")
    marks = []
    for i, line in enumerate(lines):
        m = re.match(r"^### (\d+)\.", line)
        if m:
            marks.append((i, int(m.group(1))))
    stops = [i for i, line in enumerate(lines)
             if line.startswith("### ") or line.startswith("## ")]
    out = {}
    for i, num in marks:
        end = next((j for j in stops if j > i), len(lines))
        out[num] = [(k + 1, lines[k]) for k in range(i, end)]
    for need in (1, 2, 3):
        if need not in out:
            raise EnvError("%s 缺 `### %d.` 小節" % (SKILL, need))
    return out


def body(rows):
    return "\n".join(line for _, line in rows)


def flat(rows):
    """把段落壓成一行：中文換行不插空白，所以接起來不會製造假詞界。

    為什麼需要：通道範本的清單項會折行（「派審查位、\\n  建 worktree」），逐行比對會
    把同一份八項清單看成兩段不完整的清單。
    """
    return re.sub(r"\n[ \t]*", "", body(rows))


def first_line(rows, needle):
    for lineno, line in rows:
        if needle in line:
            return lineno, line
    return None, None


def loc(rel, lineno):
    return "%s:%s" % (rel, lineno if lineno else "-")


# ── 文法抽取 ──────────────────────────────────────────────────────────────
def parse_cond(text):
    """回 (bound, unbound)；抽不到的那一側是 None。"""
    b = BOUND_RE.search(text)
    u = UNBOUND_RE.search(text)
    return (b.group(1) if b else None, u.group(1) if u else None)


def cond_ok(pair):
    bound, unbound = pair
    return bound in BOUND_OK and unbound in UNBOUND_OK


def show_cond(pair):
    return "bound=%s unbound=%s" % (pair[0], pair[1])


def segments(text):
    """回 (允許段, 禁止段)：禁止段＝第一個「不得」之後；允許段＝「允許」到該「不得」之間。

    極性這樣驗：八項要在「不得」之後出現，且不得出現在允許段——把禁止項搬進允許集合是
    最容易混過單純「字串在不在」的改法（M02 就是這個改法）。
    """
    i = text.find("不得")
    if i < 0:
        return "", ""
    j = text.find("允許")
    allow = text[j:i] if 0 <= j < i else ""
    return allow, text[i:]


# ── 契約檢查 ──────────────────────────────────────────────────────────────
class Report(object):
    def __init__(self):
        self.rows = []

    def add(self, ok, obid, where, value):
        self.rows.append((bool(ok), obid, where, value))

    @property
    def failed(self):
        return [obid for ok, obid, _, _ in self.rows if not ok]


def check_contract(files):
    """跑全部契約義務，回 Report。raise EnvError 代表 exit 2。"""
    rep = Report()
    wf_lines = numbered(files[WF])

    # ── frontmatter 版本（`V2`） ──
    fm = None
    for lineno, line in wf_lines[:20]:
        m = re.match(r"^version:\s*(\S+)\s*$", line)
        if m:
            fm = (lineno, m.group(1))
            break
    if fm is None:
        raise EnvError("%s 讀不到 frontmatter 的 version 行" % WF)
    rep.add(fm[1] == WF_VERSION, "OB-WF-VERSION", loc(WF, fm[0]), "version=%s" % fm[1])

    kit = files[KIT].strip()
    rep.add(kit == KIT_VERSION, "OB-KIT-VERSION", loc(KIT, 1), "VERSION=%s" % kit)

    # ── `I2`：行為人分流 ＋ 三句保留 ──
    i2_no, i2 = first_line(wf_lines, "- `I2`")
    if i2 is None:
        raise EnvError("%s 讀不到 `- \\`I2\\`` 行" % WF)
    keep = ("不在主 checkout 工作", "實作者只收路徑", "主 checkout 只供協調用")
    pair = parse_cond(i2)
    lost = [k for k in keep if k not in i2]
    rep.add(cond_ok(pair) and not lost, "OB-I2", loc(WF, i2_no),
            "%s 保留=%s" % (show_cond(pair), "三句齊" if not lost else "缺" + "／".join(lost)))

    # ── `L7`：新條 ──
    l6_no, _ = first_line(wf_lines, "- `L6`")
    s5_no, _ = first_line(wf_lines, "## 5.")
    if l6_no is None or s5_no is None:
        raise EnvError("%s 讀不到 `L6` 行或 `## 5.` 標題（L7 的位置無從判定）" % WF)
    l7_no, l7 = None, None
    for lineno, line in wf_lines:
        if line.startswith("- `L7`"):
            l7_no, l7 = lineno, line
            break
    if l7 is None:
        where, val = loc(WF, None), "缺 `L7` 條"
        for obid in (["OB-L7-EXIST", "OB-L7-FIELDS", "OB-L7-ALLOW", "OB-L7-BOUNDARY",
                      "OB-L7-WRITE"] + ["OB-L7-FORBID-" + s for _, s in FORBID]):
            rep.add(False, obid, where, val)
    else:
        where = loc(WF, l7_no)
        rep.add(l6_no < l7_no < s5_no, "OB-L7-EXIST", where,
                "L6=%d L7=%d 第5節=%d" % (l6_no, l7_no, s5_no))
        miss = [n for n, _ in FIELDS if n not in l7]
        rep.add(not miss, "OB-L7-FIELDS", where,
                "七欄齊" if not miss else "缺欄=" + "／".join(miss))
        allow_need = ("讀 forge", "既有檢查", ".hermes/plans/", "準備材料、非正式 T")
        amiss = [a for a in allow_need if a not in l7]
        rep.add(not amiss, "OB-L7-ALLOW", where,
                "允許集合四項齊" if not amiss else "缺=" + "／".join(amiss))
        allow_seg, forbid_seg = segments(l7)
        for item, slug in FORBID:
            ok = item in forbid_seg and item not in allow_seg
            rep.add(ok, "OB-L7-FORBID-" + slug, where,
                    "在不得段=%s 在允許段=%s" % (item in forbid_seg, item in allow_seg))
        b1, b2 = "不構成 `L1`" in l7, "未決事項為空" in l7
        rep.add(b1 and b2, "OB-L7-BOUNDARY", where,
                "不構成L1=%s 未決事項為空=%s" % (b1, b2))
        rep.add("受限寫入" in l7 and "唯讀" not in l7, "OB-L7-WRITE", where,
                "受限寫入=%s 唯讀=%s" % ("受限寫入" in l7, "唯讀" in l7))

    # ── seats/coordinator.md ──
    csec = seat_sections(files[COOR], COOR)
    duty, out_c, ban_c, oblig_c, cap_c = (csec["## 職責"], csec["## 產出物"],
                                          csec["## 禁止"], csec["## 規則義務"],
                                          csec["## 填充者須具備的能力"])

    split_rows = [(n, l) for n, l in duty if "建 worktree" in l or "啟動實作位" in l]
    if not split_rows:
        rep.add(False, "OB-COOR-SPLIT", loc(COOR, None), "職責段找不到建 worktree／啟動實作位")
    else:
        bad = []
        for n, l in split_rows:
            pair = parse_cond(l)
            if not cond_ok(pair):
                bad.append("%d(%s)" % (n, show_cond(pair)))
        rep.add(not bad, "OB-COOR-SPLIT", loc(COOR, split_rows[0][0]),
                "%d 行受檢，%s" % (len(split_rows), "全部合格" if not bad else "不合格=" + "／".join(bad)))

    # 既有語序的兼容基準：`:18` 的派審句（已綁定／未綁定）與能力段的「未綁定 `manager` 時」。
    pn, pl = first_line(duty, "派審由")
    gpair = parse_cond(pl) if pl else (None, None)
    nm_no, _ = first_line(cap_c, "未綁定 `manager` 時")
    nomgr = bool(nm_no) and bool(NOMGR_RE.search(body(cap_c)))
    rep.add(cond_ok(gpair) and nomgr, "OB-COOR-GRAMMAR-COMPAT", loc(COOR, pn),
            "派審句 %s；能力段「未綁定 `manager` 時」=%s" % (show_cond(gpair), nomgr))

    for obid, head, tail_need in (
            ("OB-COOR-CAP-WORKTREE", "建立", ("列出", "移除", "`C1`")),
            ("OB-COOR-CAP-LAUNCH", "啟動", ("停止", "已停")),
    ):
        hit_no, hit = None, None
        for n, l in cap_c:
            m = re.search(re.escape(head) + r"（([^）]*)）", l)
            if m and ("已綁定時" in m.group(1) or "未綁定時" in m.group(1)):
                hit_no, hit, inner, rest = n, l, m.group(1), l[m.end():]
                break
        if hit is None:
            rep.add(False, obid, loc(COOR, None), "能力段「%s」後緊接的子句不存在" % head)
            continue
        pair = parse_cond(inner)
        lostt = [t for t in tail_need if t not in rest]
        rep.add(cond_ok(pair) and not lostt, obid, loc(COOR, hit_no),
                "%s 子句後保留=%s" % (show_cond(pair), "齊" if not lostt else "缺" + "／".join(lostt)))

    m1c = "合併前提逐項驗（`M1`）"
    n, _ = first_line(duty, m1c)
    rep.add(n is not None, "OB-COOR-M1", loc(COOR, n), "%s=%s" % (m1c, n is not None))

    def ban_check(rep_, obid, rows, needles, rel):
        bad, firsts = [], []
        for needle in needles:
            hit = [(n, l) for n, l in rows if needle in l and l.startswith("- 不")]
            if hit:
                firsts.append(hit[0][0])
            else:
                bad.append(needle)
        rep_.add(not bad, obid, loc(rel, firsts[0] if firsts else None),
                 "三句以「- 不」起" if not bad else "不成立=" + "／".join(bad))

    ban_check(rep, "OB-COOR-BAN", ban_c,
              ("不放行未達 `M1` 的合併", "不代簽 verdict", "不把通道訊息當裁決"), COOR)
    n, _ = first_line(oblig_c, "`L7`")
    rep.add(n is not None, "OB-COOR-OBLIG-L7", loc(COOR, n), "規則義務含 `L7`=%s" % (n is not None))

    ent_no, ent = None, None
    for n, l in duty:
        if "`L7`" in l and all(f in l for f, _ in FIELDS):
            ent_no, ent = n, l
            break
    rep.add(ent is not None, "OB-COOR-ENTRUST", loc(COOR, ent_no),
            "委託句含 `L7` 與七欄=%s" % (ent is not None))

    # ── seats/manager.md ──
    msec = seat_sections(files[MGR], MGR)
    duty_m, out_m, ban_m, oblig_m = (msec["## 職責"], msec["## 產出物"],
                                     msec["## 禁止"], msec["## 規則義務"])

    prep_rows = [(n, l) for n, l in duty_m if l.startswith("- 準備階段（`L7`）：")]
    stray = [n for n, l in out_m if "- 準備階段" in l]
    rep.add(len(prep_rows) == 1 and not stray, "OB-MGR-PREP",
            loc(MGR, prep_rows[0][0] if prep_rows else None),
            "職責段 %d 條，產出物段混入 %d 條" % (len(prep_rows), len(stray)))

    prep_ids = (["OB-MGR-PREP-FIELDS", "OB-MGR-PREP-BOUNDARY"]
                + ["OB-MGR-PREP-FORBID-" + s for _, s in FORBID])
    if len(prep_rows) != 1:
        for obid in prep_ids:
            rep.add(False, obid, loc(MGR, None), "職責段無「- 準備階段（`L7`）：」條，無標的")
    else:
        pno, prep = prep_rows[0]
        where = loc(MGR, pno)
        miss = [n for n, _ in FIELDS if n not in prep]
        rep.add(not miss, "OB-MGR-PREP-FIELDS", where,
                "七欄齊" if not miss else "缺欄=" + "／".join(miss))
        w = "受限寫入" in prep
        b1, b2 = "不構成 `L1`" in prep, "未決事項為空" in prep
        rep.add(w and b1 and b2, "OB-MGR-PREP-BOUNDARY", where,
                "受限寫入=%s 不構成L1=%s 未決事項為空=%s" % (w, b1, b2))
        allow_seg, forbid_seg = segments(prep)
        for item, slug in FORBID:
            ok = item in forbid_seg and item not in allow_seg
            rep.add(ok, "OB-MGR-PREP-FORBID-" + slug, where,
                    "在不得段=%s 在允許段=%s" % (item in forbid_seg, item in allow_seg))

    ban_rows = [(n, l) for n, l in ban_m if l.startswith("- 準備階段")]
    rep.add(len(ban_rows) == 1, "OB-MGR-PREP-BAN",
            loc(MGR, ban_rows[0][0] if ban_rows else None),
            "禁止段以「- 準備階段」起首 %d 條（要恰一條）" % len(ban_rows))
    if not ban_rows:
        for _, slug in FORBID:
            rep.add(False, "OB-MGR-PREP-BAN-" + slug, loc(MGR, None), "禁止段無準備階段條，無標的")
    else:
        bno, bline = ban_rows[0]
        head = bline.split("（`L7`）")[0]      # 八項否定形只看「（`L7`）」之前的清單段
        for item, slug in FORBID:
            rep.add(("不" + item) in head, "OB-MGR-PREP-BAN-" + slug, loc(MGR, bno),
                    "不%s=%s（只看（`L7`）之前）" % (item, ("不" + item) in head))

    ban_check(rep, "OB-MGR-BAN", ban_m,
              ("不自行合併", "不代簽 verdict", "不改 issue 明列的 AC 與 write scope"), MGR)
    n, _ = first_line(duty_m, "`M1` 三項前提的核對結果")
    rep.add(n is not None, "OB-MGR-M1", loc(MGR, n), "附 `M1` 三項前提的核對結果=%s" % (n is not None))
    n, _ = first_line(oblig_m, "`L7`")
    rep.add(n is not None, "OB-MGR-OBLIG-L7", loc(MGR, n), "規則義務含 `L7`=%s" % (n is not None))
    ob = body(out_m)
    n, _ = first_line(out_m, "準備")
    rep.add("準備" in ob and "`L7`" in ob, "OB-MGR-OUTPUT", loc(MGR, n),
            "產出物含準備材料=%s 引 `L7`=%s" % ("準備" in ob, "`L7`" in ob))

    # ── orchestrators/hermes/SKILL.md ──
    ssec = skill_sections(files[SKILL])
    if 0 not in ssec:
        rep.add(False, "OB-SKILL-0", loc(SKILL, None), "缺 `### 0.` 小節")
        rep.add(False, "OB-SKILL-0-ACTOR", loc(SKILL, None), "缺 `### 0.` 小節")
    else:
        rows0 = ssec[0]
        t0 = flat(rows0)
        where = loc(SKILL, rows0[0][0])
        miss = [n for n, _ in FIELDS if n not in t0]
        banned = [b for b in ("git worktree add", "devflow_relay.py", "systemd-run", "claude -p")
                  if b in t0]
        # 位置也是義務（T v3 驗證器規格第 3 項）：內容對但擺在檔尾，流程讀起來就不是
        # 「`L1` 齊備前的那一步」。`### 1.` 不在就一樣 FAIL——沒有可比的基準。
        at0 = rows0[0][0]
        at1 = ssec[1][0][0] if 1 in ssec else None
        placed = at1 is not None and at0 < at1
        rep.add("`L7`" in t0 and not miss and not banned and placed, "OB-SKILL-0", where,
                "引 `L7`=%s 七欄=%s 禁字面=%s 位置=### 0.@%s < ### 1.@%s" % (
                    "`L7`" in t0,
                    "齊" if not miss else "缺" + "／".join(miss),
                    "無" if not banned else "／".join(banned),
                    at0, at1 if at1 is not None else "缺"))
        pair = parse_cond(t0)
        rep.add(cond_ok(pair), "OB-SKILL-0-ACTOR", where, show_cond(pair))

    for num in (2, 3):
        rows = ssec[num]
        pair = parse_cond(flat(rows))
        rep.add(cond_ok(pair), "OB-SKILL-SPLIT-%d" % num, loc(SKILL, rows[0][0]), show_cond(pair))

    # ── channels/templates ──
    tplc_lines = numbered(files[TPLC])
    tplm_lines = numbered(files[TPLM])
    if not any(l.startswith("|") and "時機" in l for _, l in tplc_lines):
        raise EnvError("%s 讀不到里程碑表的表頭（含「時機」的表格列）" % TPLC)
    if "里程碑" not in files[TPLM]:
        raise EnvError("%s 讀不到里程碑段落" % TPLM)

    def prep_block(rel, text):
        """抓「準備委託」小節：標題含「準備委託」，射程到下一個標題。"""
        lines = text.split("\n")
        start = next((i for i, l in enumerate(lines)
                      if l.startswith("#") and "準備委託" in l), None)
        if start is None:
            return None, None
        end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith("#")),
                   len(lines))
        return start + 1, [(k + 1, lines[k]) for k in range(start, end)]

    cno, crows = prep_block(TPLC, files[TPLC])
    if crows is None:
        rep.add(False, "OB-TPL-PROMPT", loc(TPLC, None), "缺「準備委託」小節")
        for _, slug in FORBID:
            rep.add(False, "OB-TPL-PROMPT-FORBID-" + slug, loc(TPLC, None), "缺「準備委託」小節")
    else:
        t = flat(crows)
        where = loc(TPLC, cno)
        miss = [n for n, _ in FIELDS if n not in t]
        need = {"`L7`": "`L7`" in t, "受限寫入": "受限寫入" in t,
                "禁止事項：": "禁止事項：" in t, "relay 入口": "devflow_relay.py" in t}
        rep.add(not miss and all(need.values()), "OB-TPL-PROMPT", where,
                "七欄=%s %s" % ("齊" if not miss else "缺" + "／".join(miss),
                                " ".join("%s=%s" % kv for kv in need.items())))
        fno, fline = first_line(crows, "禁止事項：")
        fval = fline.split("禁止事項：", 1)[1] if fline else ""
        for item, slug in FORBID:
            rep.add(item in fval, "OB-TPL-PROMPT-FORBID-" + slug, loc(TPLC, fno),
                    "稿形禁止事項含 %s=%s" % (item, item in fval))

    mno, mrows = prep_block(TPLM, files[TPLM])
    if mrows is None:
        for _, slug in FORBID:
            rep.add(False, "OB-TPL-MGR-FORBID-" + slug, loc(TPLM, None), "缺「準備委託」小節")
    else:
        allow_seg, forbid_seg = segments(flat(mrows))
        for item, slug in FORBID:
            ok = item in forbid_seg and item not in allow_seg
            rep.add(ok, "OB-TPL-MGR-FORBID-" + slug, loc(TPLM, mno),
                    "在不得段=%s 在允許段=%s" % (item in forbid_seg, item in allow_seg))

    def pub_cell(lines):
        """回 {事件: (行號, 發布者欄原文)}；沒有「發布者」欄就回空。"""
        head = None
        for n, l in lines:
            if l.startswith("|") and "發布者" in l:
                head = [c.strip() for c in l.strip().strip("|").split("|")]
                break
        if head is None or "發布者" not in head:
            return {}
        col = head.index("發布者")
        out = {}
        for n, l in lines:
            if not l.startswith("|"):
                continue
            cells = [c.strip() for c in l.strip().strip("|").split("|")]
            if len(cells) <= col:
                continue
            for ev in EVENTS:
                if cells[0] == ev:
                    out[ev] = (n, cells[col])
        return out

    def parse_pub(cell):
        b = re.search(r"(執行位|協調位|本位|該位)（已綁定）", cell)
        u = re.search(r"(執行位|協調位|本位|該位)（未綁定）", cell)
        if b and u:
            return (b.group(1), u.group(1))
        roles = set(re.findall(r"(執行位|協調位)", cell))
        if len(roles) == 1:
            one = roles.pop()
            return (one, one)
        return None

    pub = {}
    for tag, rel, lines in (("COOR", TPLC, tplc_lines), ("MGR", TPLM, tplm_lines)):
        cells = pub_cell(lines)
        pub[tag] = {}
        for ev in EVENTS:
            obid = "OB-TPL-PUB-%s-%s" % (tag, ev)
            if ev not in cells:
                rep.add(False, obid, loc(rel, None), "表中無「%s」列或無發布者欄" % ev)
                pub[tag][ev] = None
                continue
            n, cell = cells[ev]
            got = parse_pub(cell)
            pub[tag][ev] = got
            rep.add(got == PUB_EXPECT[ev], obid, loc(rel, n),
                    "抽到=%s 權威期望=%s" % (got, PUB_EXPECT[ev]))
    for ev in EVENTS:
        a, b = pub["COOR"][ev], pub["MGR"][ev]
        rep.add(a is not None and a == b, "OB-TPL-CONSIST-%s" % ev, "%s↔%s" % (TPLC, TPLM),
                "coor=%s mgr=%s" % (a, b))

    cp1_no, cp1 = None, None
    for n, l in tplc_lines:
        if l.startswith("| 1 |") and "開單" in l:
            cp1_no, cp1 = n, l
            break
    if cp1 is None:
        rep.add(False, "OB-TPL-CP1", loc(TPLC, None), "找不到確認節點 1 的列")
    else:
        need = {"`L7`": "`L7`" in cp1, "執行位": "執行位" in cp1,
                "不要直接開單": "不要直接開單" in cp1}
        rep.add(all(need.values()), "OB-TPL-CP1", loc(TPLC, cp1_no),
                " ".join("%s=%s" % kv for kv in need.items()))
    return rep


# ── 委託稿檢查 ────────────────────────────────────────────────────────────
def check_entrust(text, label):
    """七欄逐欄；值**只取欄名所在那一行**（`re.M` 下 `.` 不跨行）。

    為什麼只取同一行：欄名後換行再寫值，讀起來像填了、機器看起來也像填了，但委託的收件
    人只會讀那一行——值吞到下一行的寫法必須報 FAIL（空值吞行是原型已知的漏檢）。
    """
    rep = Report()
    vals = {}
    for name, slug in FIELDS:
        m = re.search(r"^%s[：:][ \t\u3000]*(.*)$" % re.escape(name), text, re.M)
        if m is None:
            vals[slug] = None
            rep.add(False, "OB-ENTRUST-" + slug, loc(label, None), "缺欄")
            continue
        lineno = text[:m.start()].count("\n") + 1
        val = m.group(1).strip(BLANKS)
        vals[slug] = val
        rep.add(bool(val), "OB-ENTRUST-" + slug, loc(label, lineno), "值=%r" % val)

    forbid_val = vals.get("禁止事項") or ""
    for item, slug in FORBID:
        rep.add(item in forbid_val, "OB-ENTRUST-禁止事項-" + slug, loc(label, None),
                "含 %s=%s" % (item, item in forbid_val))
    scope = vals.get("允許讀寫範圍") or ""
    rep.add(".hermes/plans/" in scope and "devflow/" not in scope,
            "OB-ENTRUST-允許讀寫範圍-受限", loc(label, None),
            "含 .hermes/plans/=%s 含 devflow/=%s" % (".hermes/plans/" in scope, "devflow/" in scope))
    g = vals.get("固定G") or ""
    rep.add(bool(re.fullmatch(r"[0-9a-f]{7,40}", g)), "OB-ENTRUST-固定G-形狀",
            loc(label, None), "固定 G=%r 是 sha=%s" % (g, bool(re.fullmatch(r"[0-9a-f]{7,40}", g))))
    return rep


# ── 輸出 ──────────────────────────────────────────────────────────────────
def emit(rep):
    for ok, obid, where, value in rep.rows:
        print("%s %s %s %s" % ("PASS" if ok else "FAIL", obid, where, value))
    failed = rep.failed
    print("SUMMARY total=%d fail=%d failed_obligations=%s" % (len(rep.rows), len(failed), failed))
    return EXIT_OK if not failed else EXIT_VIOLATION


# ── 突變：記憶體副本，各自獨立套用，不串接 ────────────────────────────────
def _span(text, start, end):
    i = text.find(start)
    if i < 0:
        raise MutError("找不到起點字面：%r" % start[:40])
    j = text.find(end, i + len(start)) if end else text.find("\n", i)
    if j < 0:
        j = len(text)
    return i, j


def edit_span(files, rel, start, end, old, new):
    text = files[rel]
    i, j = _span(text, start, end)
    seg = text[i:j]
    if old not in seg:
        raise MutError("%s 的 %r 區段內找不到 %r" % (rel, start[:24], old[:40]))
    files[rel] = text[:i] + seg.replace(old, new, 1) + text[j:]


def drop_item(files, rel, start, end, prefix, item, last):
    old = ("、" + prefix + item) if last else (prefix + item + "、")
    edit_span(files, rel, start, end, old, "")


# 五個禁止集合落點：(區段起點, 區段終點, 否定前綴, 檔)
FORBID_SITES = {
    "L7": (WF, "- `L7` 準備階段", None, "不得"),
    "MGR-PREP": (MGR, "- 準備階段（`L7`）：", None, ""),
    "MGR-BAN": (MGR, "- 準備階段不派實作位", None, "不"),
    "TPL-COOR": (TPLC, "禁止事項：", None, ""),
    "TPL-MGR": (TPLM, "該輪**不得**：", "。產物只落在", ""),
}
FORBID_PRIMARY = {
    "L7": "OB-L7-FORBID-%s",
    "MGR-PREP": "OB-MGR-PREP-FORBID-%s",
    "MGR-BAN": "OB-MGR-PREP-BAN-%s",
    "TPL-COOR": "OB-TPL-PROMPT-FORBID-%s",
    "TPL-MGR": "OB-TPL-MGR-FORBID-%s",
}

SKILL_ACTOR = "`devflow.yml` 的 `seats.manager` 已綁定時由執行位執行（`seats/manager.md`），未綁定時由協調位"


def skill_span(files, num):
    """回 SKILL 第 num 小節的 (起, 迄) 字元位移。"""
    text = files[SKILL]
    m = re.search(r"^### %d\." % num, text, re.M)
    if m is None:
        raise MutError("SKILL 缺 `### %d.` 小節" % num)
    nxt = re.search(r"^#{2,3} ", text[m.end():], re.M)
    return m.start(), (m.end() + nxt.start()) if nxt else len(text)


def edit_skill(files, num, old, new):
    i, j = skill_span(files, num)
    text = files[SKILL]
    seg = text[i:j]
    if old not in seg:
        raise MutError("SKILL `### %d.` 內找不到 %r" % (num, old[:40]))
    files[SKILL] = text[:i] + seg.replace(old, new, 1) + text[j:]


def mut_role_swap_skill(num, tail):
    def apply(files):
        edit_skill(files, num, SKILL_ACTOR + tail,
                   "`devflow.yml` 的 `seats.manager` 已綁定時由協調位執行"
                   "（`seats/coordinator.md`），未綁定時由執行位" + tail)
    return apply


def pub_rows(ev):
    return (("| %s |" % ev), )


def set_pub(files, rel, ev, old, new):
    edit_span(files, rel, "| %s |" % ev, None, old, new)


BOTH = "執行位（已綁定）／協調位（未綁定）"
REV = "協調位（已綁定）／執行位（未綁定）"
NOMGR_BAD = "執行位（已綁定）／執行位（未綁定）"


def build_mutations():
    """回 [(case_id, apply, primary, allowed_dependents), ...]；每項事先宣告預期。"""
    muts = []
    add = lambda cid, fn, primary, allowed=(): muts.append((cid, fn, list(primary), list(allowed)))

    prep_dep = (["OB-MGR-PREP-FIELDS", "OB-MGR-PREP-BOUNDARY"]
                + ["OB-MGR-PREP-FORBID-" + s for _, s in FORBID])

    # M01 coordinator 建 worktree 行的已綁定↔未綁定角色對調
    add("M01", lambda f: edit_span(f, COOR, "- 建 worktree：", None,
                                   "已綁定時由該位執行，未綁定時由本位執行",
                                   "已綁定時由本位執行，未綁定時由該位執行"),
        ["OB-COOR-SPLIT"])

    # M02 manager 準備條把「派實作位」從不得搬到允許
    def m02(f):
        edit_span(f, MGR, "- 準備階段（`L7`）：", None, "不得：派實作位、", "不得：")
        edit_span(f, MGR, "- 準備階段（`L7`）：", None, "；允許讀 forge", "；允許派實作位、讀 forge")
    add("M02", m02, ["OB-MGR-PREP-FORBID-派實作位"])

    # M03 準備條整段移到產出物段
    def m03(f):
        lines = f[MGR].split("\n")
        hit = [i for i, l in enumerate(lines) if l.startswith("- 準備階段（`L7`）：")]
        if len(hit) != 1:
            raise MutError("manager 職責段的準備條不是恰一條")
        prep = lines.pop(hit[0])
        head = next((i for i, l in enumerate(lines) if l.strip() == "## 產出物"), None)
        if head is None:
            raise MutError("manager 缺 `## 產出物`")
        end = next((j for j in range(head + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
        lines.insert(end - 1, prep)
        f[MGR] = "\n".join(lines)
    add("M03", m03, ["OB-MGR-PREP"], prep_dep)

    # M04 `L7` 不得集合刪「派實作位」
    add("M04", lambda f: drop_item(f, WF, "- `L7` 準備階段", None, "不得", "派實作位", False),
        ["OB-L7-FORBID-派實作位"])

    # M05 `L7` 刪「不構成 `L1`／未決事項為空」
    add("M05", lambda f: edit_span(f, WF, "- `L7` 準備階段", None,
                                   "準備產物不構成 `L1` 齊備，派工仍須 `L1` 各欄完整、未決事項為空，證據義務照舊。",
                                   "準備產物另案處理。"),
        ["OB-L7-BOUNDARY"])

    # M06 範本 6 的 verdict 發布者改協調位、範本 7 不動
    add("M06", lambda f: set_pub(f, TPLC, "每輪 verdict", BOTH, "協調位"),
        ["OB-TPL-PUB-COOR-每輪 verdict", "OB-TPL-CONSIST-每輪 verdict"])

    # M07 `I2` 回退「由協調者建」
    add("M07", lambda f: edit_span(f, WF, "- `I2`", None,
                                   "worktree 由執行位（職位，`seats/manager.md`；`devflow.yml` 的 "
                                   "`seats.manager` 已綁定時由執行位建）或協調者（職位，"
                                   "`seats/coordinator.md`；未綁定時由協調位建）建在",
                                   "worktree 由協調者（職位，`seats/coordinator.md`；由工具或人填）建在"),
        ["OB-I2"])

    # M08 SKILL `### 3.` 刪分流行
    add("M08", lambda f: edit_skill(f, 3, "\n\n**行為人依綁定**：" + SKILL_ACTOR + "執行。", ""),
        ["OB-SKILL-SPLIT-3"])

    # M09 SKILL `### 0.` 混入建 worktree 指令字面
    add("M09", lambda f: edit_skill(f, 0, "- 產物落點：",
                                    "- 先 `git worktree add ../<repo>.worktrees/<N> <N>-<slug>`。\n- 產物落點："),
        ["OB-SKILL-0"])

    # M10 coordinator `:58` 整句條件化（列出、移除一併交出）
    add("M10", lambda f: edit_span(f, COOR, "- 管理主 checkout", None,
                                   "建立（`manager` 已綁定時由該位執行，未綁定時由本位執行）、列出、移除",
                                   "`manager` 已綁定時由該位執行，未綁定時由本位執行——建立、列出、移除"),
        ["OB-COOR-CAP-WORKTREE"])

    # M11 manager `:21` 刪 `M1` 三項核對
    add("M11", lambda f: edit_span(f, MGR, "- 回報協調位：", None,
                                   "附 `M1` 三項前提的核對結果", "附核對結果"),
        ["OB-MGR-M1"])

    # M12 coordinator `:18` 刪「合併前提逐項驗（`M1`）」
    add("M12", lambda f: edit_span(f, COOR, "- 驗證交付：", None,
                                   "合併前提逐項驗（`M1`），", ""),
        ["OB-COOR-M1"])

    # M13 `L7` 改稱「唯讀、無副作用」
    add("M13", lambda f: edit_span(f, WF, "- `L7` 準備階段", None,
                                   "準備是受限寫入、不是無副作用", "準備是唯讀、無副作用"),
        ["OB-L7-WRITE"])

    # M14 `L7` 七欄缺「回報出口」
    add("M14", lambda f: edit_span(f, WF, "- `L7` 準備階段", None, "、回報出口", ""),
        ["OB-L7-FIELDS"])

    # M15 manager 禁止句「不代簽 verdict」去否定
    add("M15", lambda f: edit_span(f, MGR, "## 禁止", "## context",
                                   "- 不代簽 verdict", "- 代簽 verdict"),
        ["OB-MGR-BAN"])

    # M16 manager 規則義務刪 `L7`
    add("M16", lambda f: edit_span(f, MGR, "## 規則義務", "## 填充者", "`L4`、`L7`、", "`L4`、"),
        ["OB-MGR-OBLIG-L7"])

    # M17 準備條只寫在禁止段
    def m17(f):
        lines = f[MGR].split("\n")
        hit = [i for i, l in enumerate(lines) if l.startswith("- 準備階段（`L7`）：")]
        if len(hit) != 1:
            raise MutError("manager 職責段的準備條不是恰一條")
        prep = lines.pop(hit[0])
        head = next((i for i, l in enumerate(lines) if l.strip() == "## 禁止"), None)
        if head is None:
            raise MutError("manager 缺 `## 禁止`")
        end = next((j for j in range(head + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
        lines.insert(end - 1, prep)
        f[MGR] = "\n".join(lines)
    add("M17", m17, ["OB-MGR-PREP", "OB-MGR-PREP-BAN"], prep_dep)

    # M18 WORKFLOW 版本 `1.16.1.0`
    add("M18", lambda f: edit_span(f, WF, "version:", None, WF_VERSION, "1.16.1.0"),
        ["OB-WF-VERSION"])

    # M19 kit VERSION 未進位
    add("M19", lambda f: f.__setitem__(KIT, "0.18.2.0\n"), ["OB-KIT-VERSION"])

    # N01～N03 SKILL 角色反轉；N04 只寫已綁定
    add("N01", mut_role_swap_skill(2, "執行。"), ["OB-SKILL-SPLIT-2"])
    add("N02", mut_role_swap_skill(3, "執行。"), ["OB-SKILL-SPLIT-3"])
    add("N03", mut_role_swap_skill(0, "自做。"), ["OB-SKILL-0-ACTOR"])
    add("N04", lambda f: edit_skill(f, 2, "，未綁定時由協調位執行。", "。"),
        ["OB-SKILL-SPLIT-2"])

    # N05 兩範本同步改錯（彼此一致，違的是權威期望）
    for ev in EVENTS:
        bad = REV if PUB_EXPECT[ev][0] == "執行位" else "執行位"
        old = BOTH if PUB_EXPECT[ev][0] == "執行位" else "協調位"

        def both(f, ev=ev, old=old, bad=bad):
            set_pub(f, TPLC, ev, "| %s |" % old if old == "協調位" else old,
                    "| %s |" % bad if old == "協調位" else bad)
            set_pub(f, TPLM, ev, "| %s |" % old if old == "協調位" else old,
                    "| %s |" % bad if old == "協調位" else bad)
        add("N05-both-%s" % ev, both,
            ["OB-TPL-PUB-COOR-%s" % ev, "OB-TPL-PUB-MGR-%s" % ev])

    for ev in ("PR 開出", "每輪 verdict"):
        def nomgr(f, ev=ev):
            set_pub(f, TPLC, ev, BOTH, NOMGR_BAD)
            set_pub(f, TPLM, ev, BOTH, NOMGR_BAD)
        add("N05-nomgr-%s" % ev, nomgr,
            ["OB-TPL-PUB-COOR-%s" % ev, "OB-TPL-PUB-MGR-%s" % ev])

    # N06 五落點 × 八項各自獨立刪除
    for site, (rel, start, end, prefix) in FORBID_SITES.items():
        for k, (item, slug) in enumerate(FORBID):
            last = (k == len(FORBID) - 1)

            def drop(f, rel=rel, start=start, end=end, prefix=prefix, item=item, last=last):
                drop_item(f, rel, start, end, prefix, item, last)
            add("N06-forbid-%s-%s" % (site, slug), drop, [FORBID_PRIMARY[site] % slug])

    # N07 `### 0.` 內容完全正確但整塊搬到檔尾（錯位）。位置是義務，所以這一項必須擋下來：
    # 內容對而位置錯時，讀 SKILL 的人會在走完第 1～10 步之後才看到「`L1` 齊備前要做的事」。
    def n07(f):
        t = f[SKILL]
        m = re.search(r"(?ms)^### 0\..*?(?=^### 1\.)", t)
        if m is None:
            raise MutError("SKILL 找不到 `### 0.`～`### 1.` 之間的區塊")
        f[SKILL] = t[:m.start()] + t[m.end():].rstrip() + "\n\n" + m.group(0).rstrip() + "\n"
    add("N07-skill-0-misplaced", n07, ["OB-SKILL-0"])
    return muts


# ── 委託稿：正例與 31 反例（內建，不增第九檔） ────────────────────────────
POSITIVE_ENTRUST = """\
#316 準備委託（`L7`，受限寫入；不是派工）

單號：#316
問題與目標：釐清準備階段的分工與邊界，交出可貼的提案材料與基準輸出
固定 G：efd17010345a651283a431f34939619068dd50ab
允許讀寫範圍：讀 forge 與 repo；寫 .hermes/plans/316/ 之下的材料檔
禁止事項：派實作位、派審查位、建 worktree、建任務分支、開 PR、合併、修改受版控檔、改設定
交付落點：.hermes/plans/316/ 的材料檔與本單分區的 issue 留言（明標「準備材料、非正式 T」）
回報出口：本單分區，回報收件人＝協調位的 profile
"""


def entrust_cases():
    """回 [(case_id, 稿文, primary, allowed_dependents), ...]：21 缺欄/空值/純空白 ＋ 10 值不合。"""
    cases = []
    dep = {
        "固定G": ["OB-ENTRUST-固定G-形狀"],
        "禁止事項": ["OB-ENTRUST-禁止事項-" + s for _, s in FORBID],
        "允許讀寫範圍": ["OB-ENTRUST-允許讀寫範圍-受限"],
    }
    for name, slug in FIELDS:
        line = re.search(r"^%s：.*$" % re.escape(name), POSITIVE_ENTRUST, re.M).group(0)
        cases.append(("E-missing-%s" % slug, POSITIVE_ENTRUST.replace(line + "\n", ""),
                      ["OB-ENTRUST-" + slug], dep.get(slug, [])))
        cases.append(("E-empty-%s" % slug, POSITIVE_ENTRUST.replace(line, name + "："),
                      ["OB-ENTRUST-" + slug], dep.get(slug, [])))
        cases.append(("E-blank-%s" % slug,
                      POSITIVE_ENTRUST.replace(line, name + "： \t\u3000"),
                      ["OB-ENTRUST-" + slug], dep.get(slug, [])))
    cases.append(("E-bad-scope",
                  POSITIVE_ENTRUST.replace("寫 .hermes/plans/316/ 之下的材料檔",
                                           "寫 .hermes/plans/316/ 與 devflow/ 之下的檔"),
                  ["OB-ENTRUST-允許讀寫範圍-受限"], []))
    cases.append(("E-bad-G",
                  POSITIVE_ENTRUST.replace("固定 G：efd17010345a651283a431f34939619068dd50ab",
                                           "固定 G：main"),
                  ["OB-ENTRUST-固定G-形狀"], []))
    for k, (item, slug) in enumerate(FORBID):
        old = ("、" + item) if k == len(FORBID) - 1 else (item + "、")
        text = POSITIVE_ENTRUST.replace("禁止事項：", "禁止事項\u0000", 1)
        text = text.replace("\u0000", "：", 1)
        line = re.search(r"^禁止事項：.*$", text, re.M).group(0)
        cases.append(("E-bad-forbid-%s" % slug, text.replace(line, line.replace(old, "", 1)),
                      ["OB-ENTRUST-禁止事項-" + slug], []))
    return cases


# ── selftest ──────────────────────────────────────────────────────────────
def run_inmem(files):
    """在記憶體副本上跑契約檢查，回 (rc, failed_ids, err)。err 非空＝等價於 stderr 有東西。"""
    try:
        rep = check_contract(files)
    except EnvError as exc:
        return EXIT_ENV, [], "EnvError: %s" % exc
    except Exception as exc:                        # 無關錯誤不得充鑑別力
        return EXIT_ENV, [], "%s: %s" % (type(exc).__name__, exc)
    failed = rep.failed
    return (EXIT_VIOLATION if failed else EXIT_OK), failed, ""


def judge(case, rc, failed, err, primary, allowed):
    """(a) rc 1、(b) primary ⊆ actual、(c) actual ⊆ primary∪allowed、(d) 無無關錯誤。"""
    actual = set(failed)
    missing = [p for p in primary if p not in actual]
    extra = sorted(actual - set(primary) - set(allowed))
    hit = sorted(actual & set(allowed))
    ok = (rc == EXIT_VIOLATION) and not missing and not extra and not err
    print("%s %s rc=%d primary=%s hit_deps=%s missing_primary=%s extra=%s%s"
          % ("OK" if ok else "BAD", case, rc, primary, hit, missing, extra,
             "" if not err else " err=" + err))
    return ok


def selftest(root):
    files0 = load(root)                             # 缺檔／缺既有段落在這裡就 exit 2
    bad = []

    rc, failed, err = run_inmem(dict(files0))
    ok = (rc == EXIT_OK and not failed and not err)
    print("%s POSITIVE-contract rc=%d fail=%d%s"
          % ("OK" if ok else "BAD", rc, len(failed), "" if not err else " err=" + err))
    if not ok:
        bad.append("POSITIVE-contract")
    total = 1

    for case, apply, primary, allowed in build_mutations():
        total += 1
        files = dict(files0)
        try:
            apply(files)
        except MutError as exc:
            print("BAD %s MUT-NOT-APPLIED %s" % (case, exc))
            bad.append(case)
            continue
        if files == files0:
            print("BAD %s MUT-NOT-APPLIED 突變沒有改到任何位元組" % case)
            bad.append(case)
            continue
        rc, failed, err = run_inmem(files)
        if not judge(case, rc, failed, err, primary, allowed):
            bad.append(case)

    total += 1
    rep = check_entrust(POSITIVE_ENTRUST, "<內建正例>")
    ok = not rep.failed
    print("%s POSITIVE-entrust rc=%d fail=%d" % ("OK" if ok else "BAD",
                                                 EXIT_OK if ok else EXIT_VIOLATION,
                                                 len(rep.failed)))
    if not ok:
        bad.append("POSITIVE-entrust")

    for case, text, primary, allowed in entrust_cases():
        total += 1
        rep = check_entrust(text, "<%s>" % case)
        failed = rep.failed
        rc = EXIT_VIOLATION if failed else EXIT_OK
        if not judge(case, rc, failed, "", primary, allowed):
            bad.append(case)

    print("SUMMARY total=%d fail=%d failed_cases=%s" % (total, len(bad), bad))
    return EXIT_OK if not bad else EXIT_VIOLATION


# ── CLI ───────────────────────────────────────────────────────────────────
USAGE = ("用法：smoke_prep_roles.py contract <root> | entrust <委託稿檔> | selftest <root>")


def main(argv):
    if len(argv) != 3:
        print("💥 參數不符（exit 2，不是內容違規）。%s" % USAGE)
        return EXIT_ENV
    cmd, arg = argv[1], argv[2]
    try:
        if cmd == "contract":
            return emit(check_contract(load(arg)))
        if cmd == "entrust":
            if not os.path.isfile(arg):
                print("💥 讀不到委託稿：%s（exit 2，不是內容違規）" % arg)
                return EXIT_ENV
            with open(arg, encoding="utf-8") as fh:
                return emit(check_entrust(fh.read(), arg))
        if cmd == "selftest":
            return selftest(arg)
    except EnvError as exc:
        print("💥 檢查跑不起來：%s（exit 2，不是內容違規）" % exc)
        return EXIT_ENV
    print("💥 不認得的子命令 %r（exit 2）。%s" % (cmd, USAGE))
    return EXIT_ENV


if __name__ == "__main__":
    sys.exit(main(sys.argv))
