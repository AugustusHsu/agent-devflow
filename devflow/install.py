#!/usr/bin/env python3
"""devflow/install.py — 把 agent-devflow 安裝到目標專案：鏡像 devflow/、建 devflow.local/、插入口區塊。

用法：
    python3 <kit>/devflow/install.py <目標 repo 路徑> [--dry-run]
    python3 devflow/install.py --help

    來源＝執行中的本檔所在的 devflow/ 目錄（以 __file__ 定位，不是 cwd），其上層為 kit 根；
    不依賴 git、不驗 git 狀態、不驗來源是否 tag checkout。目標＝命令列給的路徑。兩者可為
    同一 repo（kit 自檢，或消費者跑自己那份副本），此時鏡像全部 unchanged。
    升級與回復不是新功能：換一個 kit checkout（另一個 tag）重跑同一支安裝。

    執行分兩階段。**決策階段**讀來源與目標、算出全部動作、檢查可寫性，**不寫任何東西，
    連 mkdir 都不做**；`--dry-run` 走完整個決策階段才停。**寫入階段**依 kit-install AC-16
    的全序落盤（階段順序 × 階段內 sorted()）。
    exit 0 成功；1 入口區塊碰撞（AC-5／5b／5c）；2 決策階段的環境或用法錯誤；
    3 寫入階段的 I/O 失敗——唯一「已寫部分檔」的結果，不回滾，重跑即為恢復。
    **exit 非 0 時 stdout 全部抑制**（含 exit 3：stdout 先寫進記憶體，寫入階段全部成功才落到
    終端），stderr 恰一行 `<路徑或項目>: <原因>`；advisory 只在 exit 0 時印，順序為
    入口規格 AC-7 先、kit-install AC-9 後。

擁有權（kit-install 規格「擁有權」表，每個行為由此推導）：
    devflow/**            kit 的——鏡像：與來源不同即覆寫、來源沒有即刪除（排除路徑除外）
    devflow.yml           消費者的——不建、不改；只讀入口規格 AC-7 的投影與 AC-9 的存在性
    devflow.local/**      消費者的——lexists 假才建，且只放 README.md；存在則整棵不碰
    CLAUDE.md／AGENTS.md  消費者的（區塊除外）——依入口規格 AC-1～AC-12
    其他一切              不寫

規格：docs/spec/kit-install/spec.md（AC-1～AC-20，含 AC-14b）；入口區塊部分由
docs/spec/install/spec.md（AC-1～AC-12）定義，本檔兩份都照字面實作，名詞定義是法。
測試：python3 tests/install/harness.py            # 全部案例
      python3 tests/install/harness.py kit        # 只跑 kit-install 案例
      python3 tests/install/harness.py AC-7       # 只跑名稱含 AC-7 的案例
（每條 AC 每個分支一案，在 /tmp 建假專案；可寫性案例以非 root 執行，root 下標 SKIP。）

不做：不建、不改 devflow.yml（附 devflow/templates/devflow.yml 供複製，缺檔時只提示）；
無 --uninstall；不裝 CI 檢查器與 docs（不在 devflow/ 下）；不建 orchestrator 的 skill
symlink；不合併內容；不碰 .gitignore、不 commit。
Python ≥ 3.8、stdlib only；讀寫一律 bytes，入口區塊外逐 byte 不變（D2）。
「存在」以 os.path.lexists 判：symlink 一律視為存在；入口檔是 dangling symlink、目錄、指向
目錄的 symlink 都是 exit 2，安裝器不替使用者決定該建到哪裡。

以下到檔尾為**入口區塊**部分的實作細節（入口規格）；鏡像部分的細節寫在「kit 鏡像」那一節。

與 `d2` 判準 B 的關係（scripts/devflow_checks.py 的 entry_block()）：
- 標記行＝檔案 bytes 以 \\n 切行、每行 UTF-8 decode（errors="replace"）後
  `line.strip() == "<!-- devflow:begin -->"`（或 end）。字面比對，不看 markdown 結構、
  不看縮排、不看是否在 code fence 內。第一組的選取與 strip() 語意與判準 B 一致。
- 與 CI **刻意不同**的一點：檔首 UTF-8 BOM（EF BB BF）不剝除，屬第一行內容，所以
  「BOM＋begin」的首行不是標記行；CI 以 utf-8-sig 讀檔會先剝 BOM。安裝器以 bytes 為準、
  不解碼整檔。影響的是**標記行的辨識**：首行是標記行的檔案，加上 BOM 之後兩邊認到的
  標記位置就不同（CI 認得首行，安裝器不認得）。#104 的處置是**維持此差異、只改訊息**。
- 「認到的標記位置不同」**不等於**「最終走哪條 AC、exit code 為何不同」——那取決於檔內
  其餘標記的排列，是一張多維的輸入→路徑對照表。**本檔頭不複述那張表**：三次嘗試用散文
  描述它、三次在某一格上寫錯（PR #105 兩輪審查）。權威來源是 tests/install/harness.py 的
  案例集；要知道某個輸入走哪一路，加一案跑它，不要讀這裡的散文推論。
- AC-5c 的觸發條件是一個**合取**，不是一類輸入的描述：命中 AC-5b（first_group 回報落單
  end）**且** bom_hides_begin() 為真（檔首恰為 EF BB BF，且去掉該 BOM 後首行依既有
  is_marker() 判為 begin）。兩者皆真才改訊息；其餘一切照舊，包括 exit code、不寫檔、
  以及 AC-5b 在其餘定義域的原訊息與行號。條件之外的輸入走哪一路，見上一條。
- AC-5c **不涵蓋**的，一律照原路走、訊息與行號不變：檔首以外的 U+FEFF；UTF-16／UTF-32 的
  BOM（那種檔案整檔不是 UTF-8，逐行 decode 以 U+FFFD 代換後不會等於標記）；以及所有
  「bom_hides_begin() 為真但沒有落單 end」的輸入——那些走哪一路由其餘標記的排列決定，
  不在此推論，見上面第二條。特別記一個**刻意**的取捨：bom_hides_begin() 為真、走 AC-5
  （begin without end）時**不**改訊息，因為拿掉 BOM 之後仍是 AC-5（只差行號），BOM 不是
  停下來的原因，改了反而是新的誤導。
- 第一組＝檔案第一個 begin 標記行到其後第一個 end 標記行。第一個 begin 之前若有任何 end
  標記行（或全檔無 begin 但有 end）＝違反 `D2`（1.0.0.0：區塊須為第一個標記組、其前不得有
  任何標記行）→ exit 1、不寫任何檔（AC-5b）——不替使用者清理，區塊外是專案的內容。
  第一組之後的任何標記行一律忽略（不計數、不報錯、不改動）。
- CI 驗第一組 ≤30 行、begin 前無落單 end；本檔用同一判準找第一組，並只對那一段做
  等值比對／取代。

`D2` 上限來源：devflow/WORKFLOW.md 的 `D2`——入口區塊 ≤30 行（含頭尾兩行標記），
與 CI 的 D2_MAX_LINES 同值。模板超過即 exit 2（AC-8）。

模板來源：本檔所在目錄的 templates/entry-block.md（以 __file__ 定位，不是 cwd）。
"""
import argparse
import difflib
import io
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parent   # 來源的 devflow/：以 __file__ 定位，不是 cwd
BEGIN = "<!-- devflow:begin -->"
END = "<!-- devflow:end -->"
BOM = b"\xef\xbb\xbf"   # 檔首 UTF-8 BOM。不剝除（見 is_marker），只在 AC-5c 用來診斷錯誤原因
ENTRY_FILES = ("CLAUDE.md", "AGENTS.md")
D2_MAX_LINES = 30
TEMPLATE_PATH = SRC / "templates" / "entry-block.md"
# AC-7：不做 YAML 解析。只讀頂層投影鍵 implementer_filler（seats.implementer.filler 的衍生投影，
# 一致性由 CI 的 i5 保證，AC-13）。以下正規式對應 spec 的名詞；行已去掉 CRLF 的 \r。
# 頂層鍵行：裸鍵 ＋ `:` ＋（行尾、或一個以上空格／tab 再接任意內容）
TOP_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*:(?:$|[ \t])")
# 純 `---`：其後只能是空格／tab，或空格／tab 再接 # 註解
DOC_START_RE = re.compile(r"^---(?:[ \t]*|[ \t]+#.*)$")
# 候選行：`implementer_filler:` ＋ 一個以上空格／tab ＋ 值 ＋〔一個以上空格／tab ＋ # 至行尾〕？＋ 尾端空格／tab？
# 值＝不含空格／tab／\r／# 的連續字元，且是**裸字面值**＝YAML 1.2 §7.3.3 的單行 plain scalar。
# 對「不含空白與 #」的 token，該文法只剩兩條約束，以下兩條即完整刻畫：
# (1) 首字元（ns-plain-first）：19 個 c-indicator `- ? : , [ ] { } # & * ! | > ' " % @ \`` 中 16 個
#     無條件不得起首（`#` 已在通用排除裡）；`-`／`?`／`:` 只有後接 ns-plain-safe（block 語境＝任何
#     非空白字元）時才可起首——單獨的 `-`／`?`／`:` 不是 plain scalar，`-x`／`?x`／`:x` 是。
# (2) 後續字元（ns-plain-char）：任何非空白字元皆可，唯 `:` 須後接 ns-plain-safe——token 內的 `:`
#     必然後接 token 字元，所以等價於**尾字元不得是 `:`**（`codex:` 在 YAML 是 mapping 分隔，
#     `a:b`、`::x` 是 plain scalar）；`#` 的前接規則因 token 不含 `#` 而不適用。其他尾字元
#     （`-`／`?`／`,`／`[`／`]`／`{`／`}`）無限制。
# 帶引號、alias、anchor、tag、區塊／流式指示都不是安裝器讀得到的裸值（spec AC-7 不合規例
# 「值帶引號」、AC-13「引號值／alias／顯式標籤 → L＝無」）。
CANDIDATE_PREFIX = "implementer_filler:"
CANDIDATE_VALUE = r"(?:[^ \t\r#\"'*&!|>\[\]{},%@`?:-][^ \t\r#]*|[?:-][^ \t\r#]+)(?<!:)"
CANDIDATE_RE = re.compile(r"^implementer_filler:[ \t]+(" + CANDIDATE_VALUE + r")(?:[ \t]+#.*)?[ \t]*$")
# 行模型排除的換行字元：NEL／LS／PS（YAML 1.1 視為換行）；bare CR 另在切行時判
FORBIDDEN_BREAKS = ("\x85", "\u2028", "\u2029")
ADVISORY = ("devflow.yml: seats: present but implementer_filler unreadable (missing, malformed, "
            "duplicated, or file is not a plain top-level mapping); defaulting to AGENTS.md")

# ── kit 鏡像的常數（kit-install 規格）────────────────────────────────
DEVFLOW_DIR = "devflow"             # 目標內的鏡像目錄（也是來源目錄名）
LOCAL_DIR = "devflow.local"         # 消費者自有目錄（AC-7）
LOCAL_README = "README.md"
CONFIG_FILE = "devflow.yml"
VERSION_PATH = SRC / "VERSION"
LOCAL_TEMPLATE_PATH = SRC / "templates" / "local-README.md"
CONFIG_TEMPLATE = "devflow/templates/devflow.yml"
YML_ADVISORY = "devflow.yml: absent; copy %s and edit (advisory)" % CONFIG_TEMPLATE
# 版本（kit-install「名詞定義」）：內容恰為一行 a.b.c.d 加恰一個 \n，四碼十進位非負整數、
# 除單獨的 0 外無前導零，無 BOM。以 bytes 比對，整檔 fullmatch——多一行、多一個 \n 都不合。
VERSION_RE = re.compile(rb"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\n")
# 排除路徑（封閉列舉，對來源與目標雙邊生效）：名為 __pycache__ 的目錄連同其下全部、副檔名 .pyc 的檔。
# .DS_Store／.gitkeep 等刻意不在列——devflow/** 是 kit 的，消費者不該在其下放東西。
EXCLUDED_DIR = "__pycache__"
EXCLUDED_SUFFIX = ".pyc"


class InstallError(Exception):
    """帶 exit code 的錯誤；訊息印到 stderr。1＝內容碰撞，2＝決策階段，3＝寫入階段。"""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class Decision:
    """一個目標檔的決策。kind：create／insert／replace／unchanged。"""

    def __init__(self, name, display, kind, old, new):
        self.name = name          # 檔名，diff 路徑用 a/<檔>／b/<檔>
        self.display = display    # 印出的 <路徑>
        self.kind = kind
        self.old = old            # 原檔 bytes；不存在時 None
        self.new = new            # 寫入 bytes；unchanged 時等於 old


# ── 行與標記 ─────────────────────────────────────────────────────────


def split_lines(data):
    """只以 \\n 切行、保留行尾（\\n 或 \\r\\n 留在行內）。

    不用 bytes.splitlines()：它也會在 \\r 切行，與 CI 的 text.split("\\n") 不一致。
    """
    lines, start = [], 0
    while start < len(data):
        i = data.find(b"\n", start)
        if i < 0:
            lines.append(data[start:])
            break
        lines.append(data[start:i + 1])
        start = i + 1
    return lines


def is_marker(line, marker):
    """標記行：每行 UTF-8 decode（errors="replace"）後 str.strip() 整行等於標記。

    用 str.strip() 而非 bytes.strip()：兩者的空白集合不同（str 多 \\x1c-\\x1f、U+00A0 等），
    判準 B 在 str 上比對，這裡同語意。errors="replace" 讓非 UTF-8 的行也能比（U+FFFD 不是
    空白，不會誤判）。逐行 decode、不剝 BOM：檔首 BOM 留在第一行內，U+FEFF 不是空白，
    「BOM＋begin」不是標記行（spec 名詞定義，與 CI 刻意不同）；判定不變，只有命中 AC-5b
    時另由 bom_hides_begin() 把錯誤訊息指回 BOM（AC-5c）。
    """
    return line.decode("utf-8", "replace").strip() == marker


def first_group(lines):
    """回傳 (stray_idx, begin_idx, end_idx)，0-based；不存在的那一項是 None。與 CI entry_block() 同義。

    stray＝第一個 begin 之前（無 begin 則全檔）最早的 end 標記行：`D2` 說區塊前不得有任何
    標記行，這是 AC-5b 的拒絕依據。begin／end 是第一組的兩端。
    """
    begin = next((i for i, line in enumerate(lines) if is_marker(line, BEGIN)), None)
    head = lines if begin is None else lines[:begin]
    stray = next((i for i, line in enumerate(head) if is_marker(line, END)), None)
    if begin is None:
        return stray, None, None
    end = next((i for i in range(begin + 1, len(lines)) if is_marker(lines[i], END)), None)
    return stray, begin, end


def bom_hides_begin(lines):
    """檔首有 BOM、且去掉 BOM 後的第一行是 begin 標記行 → True（AC-5c 的判定）。

    這個組合下第一行不是標記行（is_marker 不剝 BOM），安裝器看不見它，檔內第一個 end
    於是成為落單 end、命中 AC-5b。本函式只供錯誤訊息指回真正的原因，不參與 first_group
    的判定：拿掉 BOM 才是使用者的修法，安裝器不替他改檔。
    """
    return bool(lines) and lines[0].startswith(BOM) and is_marker(lines[0][len(BOM):], BEGIN)


# ── 模板 ─────────────────────────────────────────────────────────────


def load_template():
    """模板 bytes：正規化為 LF、無 BOM、尾端恰一個 \\n；須以 begin 行起、end 行止；≤30 行。"""
    try:
        raw = TEMPLATE_PATH.read_bytes()
    except OSError as e:
        raise InstallError(2, "%s: 讀不到模板：%s" % (TEMPLATE_PATH, e))
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    data = raw.replace(b"\r\n", b"\n").rstrip(b"\n") + b"\n"
    lines = split_lines(data)
    if not is_marker(lines[0], BEGIN) or not is_marker(lines[-1], END):
        raise InstallError(2, "%s: 模板須以 %s 行起、%s 行止" % (TEMPLATE_PATH, BEGIN, END))
    if len(lines) > D2_MAX_LINES:
        raise InstallError(2, "%s: 模板 %d 行（含兩標記行），超過 D2 上限 %d 行"
                           % (TEMPLATE_PATH, len(lines), D2_MAX_LINES))
    return data


# ── 目標檔集合（AC-7）────────────────────────────────────────────────


def load_devflow_yml(root):
    """devflow.yml 的文字（嚴格 UTF-8）；讀不到、不是檔案、無法解碼都回 None，永不報錯。"""
    try:
        return (root / "devflow.yml").read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def logical_lines(text):
    """AC-7 行模型：以 \\n 切行（不用 str.splitlines()——它還會切 \\x0b／\\x0c／\\x1c–\\x1e），
    CRLF 的 \\r 屬行尾、從行內容去掉。任何 bare CR（不緊接 \\n、位於檔尾、`\\r\\r\\n` 的第一個）
    或任何位置的 NEL／LS／PS → 整檔不合規，回 None。BOM 不剝：留在第一行內容裡。"""
    if any(ch in text for ch in FORBIDDEN_BREAKS):
        return None
    segments = text.split("\n")
    last = len(segments) - 1
    lines = []
    for i, seg in enumerate(segments):
        if i != last and seg.endswith("\r"):
            seg = seg[:-1]                        # 這個 \r 後面緊接 \n：CRLF 行尾
        if "\r" in seg:
            return None                           # bare CR
        lines.append(seg)
    return lines


def is_ignored(line):
    """忽略行＝只含空格／tab 的行，或去掉行首空格／tab 後以 # 起始的行（\\r 已在切行時去掉）。"""
    body = line.lstrip(" \t")
    return body == "" or body.startswith("#")


def is_top(line):
    """頂層行＝首字元不是空格的非忽略行（tab、BOM 起始者也是頂層行，但不是頂層鍵行）。"""
    return not is_ignored(line) and not line.startswith(" ")


def implementer_filler(text):
    """AC-7 對一段 devflow.yml 文字的判定：通過行模型與信封、且恰一合規候選行 → 其值；否則 None。

    信封（兩條皆須成立）：
    1. 根定位：第一個非忽略行——不論縮排——必須是頂層鍵行；或它是第 0 欄的純 `---`，且其後
       第一個非忽略行是頂層鍵行。這把根釘成「從第 0 欄開始的 block mapping」：根 flow／引號／
       block scalar／序列不論外殼縮排幾格、不論是否藏在 `---` 之後，第一個內容行都不是
       `裸鍵: ` 形狀，在此被擋。
    2. 全檔：其後每一個頂層行都必須是頂層鍵行——第二個 `---`、`...`、flow 續行 `]`／`}`、
       `- ` 序列項、引號鍵、`%` 指令、tab／BOM 起始者都使整檔不合規。
    信封不看頂層鍵行 `:` 之後的內容、也不看縮排行（值層的非法 YAML 不影響）。
    候選行：以 `implementer_filler:` 起始的頂層行，須恰一行且整行匹配 CANDIDATE_RE；
    值逐 byte 比對、不改大小寫。帶引號（`"claude-code"`、`'claude-code'`）、alias、anchor、tag
    等非裸字面值的候選行是不合規（回 None，不是回傳含引號的字串）——「不去引號」是指不把
    `"claude-code"` 當成 claude-code，不是把它當成合規 token。
    """
    lines = logical_lines(text)
    if lines is None:
        return None
    content = [line for line in lines if not is_ignored(line)]
    if not content:
        return None
    first = content[0]
    if DOC_START_RE.match(first):
        content = content[1:]                     # `---` 例外：只允許在第一個非忽略行
        if not content:
            return None
        first = content[0]
    if not TOP_KEY_RE.match(first):
        return None                               # 信封 1：根不是第 0 欄的裸鍵行
    candidates = []
    for line in content:
        if not line.startswith(" "):              # 頂層行
            if not TOP_KEY_RE.match(line):
                return None                       # 信封 2
            if line.startswith(CANDIDATE_PREFIX):
                candidates.append(line)
    if len(candidates) != 1:
        return None                               # 零行或重複
    m = CANDIDATE_RE.match(candidates[0])
    return m.group(1) if m else None


def has_seats_line(text):
    """advisory 的觸發條件：存在以 `seats:` 起始的頂層行。以 \\n 切行、去掉行尾 \\r 後判，
    不要求整檔通過行模型（信封不成立時也要能提示）。"""
    for line in text.split("\n"):
        if line.endswith("\r"):
            line = line[:-1]
        if is_top(line) and line.startswith("seats:"):
            return True
    return False


def read_implementer(root):
    """devflow.yml 的 implementer_filler 值（AC-7）；任何讀不到／不合規都回 None，永不報錯。
    CI 的 i5（AC-13）直接呼叫本函式取 L，本檔不得另有第二份判定。"""
    text = load_devflow_yml(root)
    return None if text is None else implementer_filler(text)


def choose_targets(root):
    """回傳 (目標檔集合, advisory 訊息序列)。

    advisory **不在這裡印**：kit-install AC-9 收窄為「只在 exit 0 時印」，而決策還沒走完，
    這裡不知道最終 exit code。緩衝給 run()，由它在決策全部成功後依序印（AC-7 先、AC-9 後）。
    """
    # 「存在」＝ os.path.lexists：symlink（含 dangling）一律視為存在，由 decide() 再判形狀
    present = [name for name in ENTRY_FILES if os.path.lexists(root / name)]
    if present:
        return present, []
    text = load_devflow_yml(root)
    value = None if text is None else implementer_filler(text)
    advisories = []
    if value is None and text is not None and has_seats_line(text):
        advisories.append(ADVISORY)               # AC-7 advisory：有 seats: 卻讀不到合規投影
    return (["CLAUDE.md"] if value == "claude-code" else ["AGENTS.md"]), advisories


# ── 決策（AC-1～AC-6、可寫性）───────────────────────────────────────


def decide(root, name, template):
    """一個目標檔的決策；exit 1／2 路徑以 InstallError 拋出。

    可寫性在這裡檢查（不是寫入時才發現）：將被寫入的既有檔查 os.access(W_OK)、將被建立的
    檔查其目錄；dry-run 與實跑皆走同一條路，exit code 與 stderr 才會一致（AC-10）。
    unchanged 與 AC-5／AC-5b 的檔不會被寫入，不檢查。
    """
    path = root / name
    display = str(path)
    if not os.path.lexists(path):
        if not os.access(root, os.W_OK | os.X_OK):   # 建檔需 write＋search（0222 目錄 W_OK 真但 open 失敗）
            raise InstallError(2, "%s: directory not writable" % display)
        return Decision(name, display, "create", None, template)                 # AC-1
    if not path.exists():
        raise InstallError(2, "%s: dangling symlink" % display)
    if not path.is_file():
        raise InstallError(2, "%s: not a regular file" % display)
    try:
        data = path.read_bytes()
    except OSError as e:
        raise InstallError(2, "%s: 讀不到：%s" % (display, e))
    lines = split_lines(data)
    stray, begin, end = first_group(lines)
    # AC-5b 先於 AC-5：落單 end 在檔案裡一定比 begin 早，先報最早的那個違規
    if stray is not None:
        if bom_hides_begin(lines):
            # AC-5c：落單 end 只是後果，原因是 BOM 遮住第一行的 begin。exit code 與「不寫檔」
            # 都同 AC-5b，只換訊息；行號固定 1（BOM 那一行），指向要動手的地方
            raise InstallError(1, "%s:1: UTF-8 BOM before devflow:begin; "
                                  "remove the BOM (see issue #104)" % display)
        raise InstallError(1, "%s:%d: stray devflow:end before begin" % (display, stray + 1))  # AC-5b
    if begin is None:
        decision = Decision(name, display, "insert", data, template + b"\n" + data)  # AC-2（無任何標記行）
    elif end is None:
        raise InstallError(1, "%s:%d: devflow:begin without end" % (display, begin + 1))  # AC-5
    else:
        start = sum(len(line) for line in lines[:begin])
        stop = sum(len(line) for line in lines[:end + 1])   # 含 end 行的行尾序列；EOF 則止於 EOF
        if data[start:stop].replace(b"\r\n", b"\n") == template:
            return Decision(name, display, "unchanged", data, data)              # AC-3
        decision = Decision(name, display, "replace", data,
                            data[:start] + template + data[stop:])               # AC-4
    if not os.access(path, os.W_OK):
        raise InstallError(2, "%s: not writable" % display)
    return decision


# ── kit 鏡像：決策（kit-install AC-1～AC-15、AC-19）──────────────────


def posix_rel(root, path):
    """path 相對於 root 的 POSIX 路徑（鏡像集合與動作行的識別字）。"""
    return os.path.relpath(str(path), str(root)).replace(os.sep, "/")


def parse_version(data):
    """合「版本」定義的 bytes → 四碼 tuple；否則 None。比較依四碼數值元組。"""
    m = VERSION_RE.fullmatch(data or b"")
    return tuple(int(g) for g in m.groups()) if m else None


def version_text(quad):
    return ".".join(str(n) for n in quad)


def read_source_version():
    """AC-12：來源 devflow/VERSION。讀不到或不合定義 → exit 2，且不讀目標、不做任何決策。"""
    try:
        data = VERSION_PATH.read_bytes()
    except OSError as e:
        raise InstallError(2, "devflow/VERSION: %s" % (e.strerror or e))
    quad = parse_version(data)
    if quad is None:
        raise InstallError(2, "devflow/VERSION: malformed; expected exactly one line a.b.c.d")
    return quad


def walk_tree(root, prefix):
    """root 下、排除路徑以外的 (dirs, files, links, others)，各自為 sorted 的 POSIX 相對路徑。

    **永不跟隨 symlink**：os.walk(followlinks=False) ＋ os.lstat。symlink 指向目錄者落在
    links 且不進入其指向；dangling 與指向檔者同。排除路徑在這裡就剪掉，來源與目標共用
    同一份判斷。others＝既非一般檔也非 symlink 者（fifo／socket／裝置），由呼叫端處置：
    來源的不進鏡像集合，目標的不算 deleted（「動作」只定義一般檔與 symlink）。
    任何一層讀不到 → exit 2（決策階段的環境錯誤），prefix 用來組出 `devflow/<rel>` 的顯示名。
    """
    dirs, files, links, others = [], [], [], []

    def where(path):
        rel = posix_rel(root, path) if path else "."
        return prefix.rstrip("/") if rel in (".", "") else prefix + rel

    def failed(e):
        raise InstallError(2, "%s: %s" % (where(getattr(e, "filename", None)), e.strerror or e))

    for dirpath, dirnames, filenames in os.walk(str(root), onerror=failed, followlinks=False):
        keep = []
        for name in dirnames:
            if name == EXCLUDED_DIR:
                continue                          # 排除路徑：連同其下全部都不看
            full = os.path.join(dirpath, name)
            rel = posix_rel(root, full)
            if os.path.islink(full):
                links.append(rel)                 # symlink 指向目錄：記錄、不進入
            else:
                dirs.append(rel)
                keep.append(name)
        dirnames[:] = keep
        for name in filenames:
            if name.endswith(EXCLUDED_SUFFIX):
                continue
            full = os.path.join(dirpath, name)
            rel = posix_rel(root, full)
            try:
                mode = os.lstat(full).st_mode
            except OSError as e:
                raise InstallError(2, "%s%s: %s" % (prefix, rel, e.strerror or e))
            (links if stat.S_ISLNK(mode) else files if stat.S_ISREG(mode) else others).append(rel)
    return sorted(dirs), sorted(files), sorted(links), sorted(others)


def source_files():
    """鏡像集合：來源 devflow/ 下、排除路徑以外的一般檔 rel -> bytes（AC-13 在此拒絕 symlink）。"""
    _, files, links, _ = walk_tree(SRC, DEVFLOW_DIR + "/")
    if links:
        # 不論指向檔、目錄或 dangling；報字典序最早的那個（stderr 恰一行）
        raise InstallError(2, "devflow/%s: symlink in source not supported" % links[0])
    data = {}
    for rel in files:
        try:
            data[rel] = (SRC / rel).read_bytes()
        except OSError as e:
            raise InstallError(2, "devflow/%s: %s" % (rel, e.strerror or e))
    return data


def check_target_devflow(dst):
    """AC-14：目標 devflow 以 lexists 存在但不是目錄 → exit 2。指向目錄的 symlink 也算。"""
    if not os.path.lexists(dst):
        return
    if os.path.islink(dst):
        raise InstallError(2, "devflow: symlink, not a directory")
    if not os.path.isdir(dst):
        raise InstallError(2, "devflow: not a directory")


def read_target_version(dst):
    """目標**安裝前**的 devflow/VERSION（AC-11 的模式）。

    None＝無 devflow/ 或無該檔（fresh）；False＝存在但不合「版本」定義、或不是一般檔、
    或讀不到（replace，舊版印 invalid）；否則四碼 tuple。純報表用，不改變行為。
    """
    path = dst / "VERSION"
    if not os.path.lexists(path):
        return None
    try:
        if not stat.S_ISREG(os.lstat(str(path)).st_mode):
            return False
        return parse_version(path.read_bytes()) or False
    except OSError:
        return False


def mode_of(old, new):
    """(舊版顯示字串, 模式)。模式取 fresh|upgrade|downgrade|same|replace 之一。"""
    if old is None:
        return "none", "fresh"
    if old is False:
        return "invalid", "replace"
    if old < new:
        return version_text(old), "upgrade"
    if old > new:
        return version_text(old), "downgrade"
    return version_text(old), "same"


class Mirror:
    """鏡像的決策結果。四個 list 都是 POSIX 相對路徑、各自 sorted。"""

    def __init__(self):
        self.created = []
        self.updated = []
        self.deleted = []
        self.unchanged = []
        self.data = {}        # created／updated 要寫入的 bytes
        self.prune = []       # 安裝前既有的子目錄，深者先；寫入階段清掉變空的

    def actions(self):
        """(路徑, 動作) 序列；unchanged 不印任何行（AC-4）。"""
        return ([(DEVFLOW_DIR + "/" + r, "created") for r in self.created]
                + [(DEVFLOW_DIR + "/" + r, "updated") for r in self.updated]
                + [(DEVFLOW_DIR + "/" + r, "deleted") for r in self.deleted])

    def touched(self):
        return sorted(set(self.created) | set(self.updated) | set(self.deleted))


def plan_mirror(src_files, dst):
    """決策階段：算出 created／updated／deleted／unchanged。不寫任何東西，連 mkdir 都不做。"""
    plan = Mirror()
    if not os.path.lexists(dst):
        plan.created = sorted(src_files)
        plan.data = dict(src_files)
        return plan
    dirs, files, links, others = walk_tree(dst, DEVFLOW_DIR + "/")
    # AC-14b：目標內某 symlink 的相對路徑若是鏡像集合任一路徑的**祖先**（來源在此為目錄）→ 拒絕。
    # 祖先關係以 POSIX 路徑段判、不 resolve（devflow/su 不是 devflow/sub/a 的祖先）；
    # 否則寫入會沿連結越出目標。非祖先的 symlink 依「動作」定義為 updated 或 deleted。
    ancestors = set()
    for rel in src_files:
        parts = rel.split("/")
        for i in range(1, len(parts)):
            ancestors.add("/".join(parts[:i]))
    for rel in links:
        if rel in ancestors:
            raise InstallError(2, "devflow/%s: symlink where source has directory" % rel)
    # 規格未定義「來源是檔、目標同路徑是目錄或 fifo」：那不是「無」、也沒有可比的 bytes。
    # 依 AC-14／AC-14b 的同一精神當決策階段的環境錯誤擋下，不替使用者決定要不要刪掉它。
    clash = sorted(set(dirs) & set(src_files))
    if clash:
        raise InstallError(2, "devflow/%s: directory where source has a file" % clash[0])
    clash = sorted(set(others) & set(src_files))
    if clash:
        raise InstallError(2, "devflow/%s: not a regular file" % clash[0])
    present_files, present_links = set(files), set(links)
    for rel in sorted(src_files):
        if rel in present_links:
            plan.updated.append(rel)              # symlink 由一般檔取代（AC-2）
        elif rel in present_files:
            try:
                old = (dst / rel).read_bytes()
            except OSError as e:
                raise InstallError(2, "devflow/%s: %s" % (rel, e.strerror or e))
            if old == src_files[rel]:
                plan.unchanged.append(rel)        # 不印任何行（AC-4）
                continue
            plan.updated.append(rel)
        else:
            plan.created.append(rel)
        plan.data[rel] = src_files[rel]
    # 目標下、排除路徑以外、不在鏡像集合的一般檔或 symlink → deleted（symlink 只移除連結本身）
    plan.deleted = sorted((present_files | present_links) - set(src_files))
    plan.prune = sorted(dirs, key=lambda d: (-d.count("/"), d))   # 深者先
    return plan


def plan_local(root):
    """AC-7：目標無 devflow.local（lexists 假）→ 回傳 README.md 的 bytes；真（目錄、空目錄、
    缺 README、檔案、symlink 皆算）→ 回 None，整棵不碰、不印。"""
    if os.path.lexists(root / LOCAL_DIR):
        return None
    try:
        return LOCAL_TEMPLATE_PATH.read_bytes()
    except OSError as e:
        raise InstallError(2, "devflow/templates/local-README.md: %s" % (e.strerror or e))


def nearest_existing_dir(path):
    """path 的最近一層已存在祖先目錄——建檔前要在它底下 mkdir 出中間層。"""
    d = path.parent
    while not os.path.isdir(d) and d != d.parent:
        d = d.parent
    return d


def need_writable_dir(path, display):
    """建檔需 write＋search 兩權限（0222 目錄 W_OK 真但建檔失敗）。"""
    if not os.access(nearest_existing_dir(path), os.W_OK | os.X_OK):
        raise InstallError(2, "%s: directory not writable" % display)


def check_writable(dst, plan, local_data, root):
    """AC-15：每個將被 created／updated／deleted 的路徑檢查所在目錄 W_OK | X_OK、
    將被 updated／deleted 的既有**一般檔**另檢查本身 W_OK；任一不可寫 → exit 2、不寫任何檔。
    dry-run 亦檢查（與入口規格「可寫性」同理，AC-10）。以路徑字串序檢查，第一個不可寫即報。

    symlink 不查本身的 W_OK：os.access 會跟隨連結，dangling symlink 恆假，會把「刪得掉的
    連結」誤判成不可寫；移除連結本身只需所在目錄的權限。
    """
    for rel in plan.touched():
        path = dst / rel
        display = DEVFLOW_DIR + "/" + rel
        need_writable_dir(path, display)
        if rel not in plan.created and not os.path.islink(path) and not os.access(path, os.W_OK):
            raise InstallError(2, "%s: not writable" % display)
    if local_data is not None:
        need_writable_dir(root / LOCAL_DIR / LOCAL_README, LOCAL_DIR + "/" + LOCAL_README)


# ── kit 鏡像：寫入（kit-install AC-16）───────────────────────────────


def assert_no_link_ancestor(dst, rel, display):
    """寫入前對每一層祖先再 lstat 一次確認非 symlink。

    決策階段已依 AC-14b 拒絕過，這是第二道：決策與寫入之間有人換了目錄的話，寫入會沿連結
    越出目標。屬寫入階段的失敗 → exit 3。
    """
    cur = dst
    for name in rel.split("/")[:-1]:
        cur = cur / name
        if os.path.islink(cur):
            raise InstallError(3, "%s: symlink appeared under devflow/ during the write phase"
                               % display)


def atomic_write(path, data, display):
    """單檔原子寫入：同目錄寫暫存檔後 os.replace。不保證多檔整體原子（AC-16）。

    os.replace 取代的是 path 這個名字本身——原本若是 symlink，換成一般檔（AC-2），不寫進
    它的指向。中間層目錄在這裡一併 mkdir（寫入階段，決策階段不做）。
    """
    tmp = None
    try:
        os.makedirs(str(path.parent), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".devflow-install-")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, str(path))
        tmp = None
    except OSError as e:
        raise InstallError(3, "%s: %s" % (display, e.strerror or e))
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)                    # 失敗時不留暫存檔；目標路徑本身未動
            except OSError:
                pass


def write_mirror(dst, plan):
    """AC-16 的前三個階段：created／updated → deleted → 空目錄移除（深者先）。
    **同一階段內依路徑字串 sorted() 逐一寫入**——這個全序與 AC-11 報表的全域 sorted() 不同。"""
    for rel in sorted(set(plan.created) | set(plan.updated)):
        display = DEVFLOW_DIR + "/" + rel
        assert_no_link_ancestor(dst, rel, display)
        atomic_write(dst / rel, plan.data[rel], display)
    for rel in sorted(plan.deleted):
        display = DEVFLOW_DIR + "/" + rel
        assert_no_link_ancestor(dst, rel, display)
        try:
            os.remove(str(dst / rel))             # symlink 只移除連結本身，不進入其指向
        except OSError as e:
            raise InstallError(3, "%s: %s" % (display, e.strerror or e))
    for rel in plan.prune:                        # 已依深者先排序；devflow/ 本身不在其中
        path = dst / rel
        try:
            if os.path.isdir(path) and not os.path.islink(path) and not os.listdir(str(path)):
                os.rmdir(str(path))
        except OSError as e:
            raise InstallError(3, "%s/%s: %s" % (DEVFLOW_DIR, rel, e.strerror or e))


def write_local(root, local_data):
    """AC-16 第四階段：devflow.local/ 只在整棵不存在時建，且只放 README.md。"""
    display = LOCAL_DIR + "/" + LOCAL_README
    try:
        os.mkdir(str(root / LOCAL_DIR))
    except OSError as e:
        raise InstallError(3, "%s: %s" % (LOCAL_DIR, e.strerror or e))
    atomic_write(root / LOCAL_DIR / LOCAL_README, local_data, display)


# ── 輸出 ─────────────────────────────────────────────────────────────


def kit_report(out, old, new, plan, local_data):
    """AC-11：stdout 第一行恰為摘要行，其後為動作行，以**路徑字串** sorted() 排序。

    排序的鍵是路徑不是整行：`devflow/a` 與 `devflow/a.b` 的先後在兩種排法下不同。
    `devflow.local/README.md` 排在 `devflow/...` 之前（`.` < `/`）。
    """
    old_text, mode = mode_of(old, new)
    lines = ["kit-install: %s -> %s (%s)" % (old_text, version_text(new), mode)]
    actions = plan.actions()
    if local_data is not None:
        actions.append((LOCAL_DIR + "/" + LOCAL_README, "created"))
    lines += ["%s: %s" % (path, action) for path, action in sorted(actions)]
    out.write("".join(line + "\n" for line in lines).encode("utf-8", "surrogateescape"))


def write_diff(out, d):
    """AC-10：恰為 difflib.diff_bytes(unified_diff) 的輸出逐行 join，不增不減
    （無尾端換行時也不加 `\\ No newline at end of file`）。"""
    old = split_lines(d.old or b"")
    new = split_lines(d.new)
    name = d.name.encode()
    out.writelines(difflib.diff_bytes(difflib.unified_diff, old, new,
                                      fromfile=b"a/" + name, tofile=b"b/" + name))


DONE = {"create": "created", "insert": "inserted", "replace": "replaced", "unchanged": "unchanged"}


def report(out, d, dry_run):
    """成功路徑的 stdout：unchanged 一律印 `<路徑>: unchanged`（AC-3）；
    其餘 dry-run 印 unified diff（AC-10），實際執行印 `<路徑>: created|inserted|replaced`
    （spec 未規定實際寫入後的 stdout，此為本檔的選擇，見 issue #46 留言）。"""
    if d.kind == "unchanged" or not dry_run:
        out.write(("%s: %s\n" % (d.display, DONE[d.kind])).encode("utf-8", "surrogateescape"))
    else:
        write_diff(out, d)


# ── 主流程 ───────────────────────────────────────────────────────────


def write_entry(root, decisions):
    """AC-16 最後一個階段：入口檔（原子性依入口規格——全部檔案的決策都成功才寫）。

    直接開檔覆寫（不走 temp+rename）：CLAUDE.md 常是 AGENTS.md 的 symlink，換 inode 會把
    symlink 換成普通檔。可寫性已在決策階段前置檢查；走到這裡的 OSError 是檢查與寫入之間的
    競態——屬寫入階段的失敗 → exit 3。
    """
    for d in decisions:
        if d.kind != "unchanged":
            try:
                (root / d.name).write_bytes(d.new)
            except OSError as e:
                raise InstallError(3, "%s: %s" % (d.display, e.strerror or e))


def run(target, dry_run):
    # ── 決策階段：不寫任何東西（連 mkdir 都不做）；--dry-run 走完這一整段就停 ──
    version = read_source_version()                                       # AC-12
    src_files = source_files()                                            # AC-13 ＋鏡像集合
    root = Path(target)
    if not root.exists():
        raise InstallError(2, "%s: 目標路徑不存在" % target)             # 入口規格 AC-11
    if not root.is_dir():
        raise InstallError(2, "%s: 目標路徑不是目錄" % target)           # 入口規格 AC-11
    dst = root / DEVFLOW_DIR
    check_target_devflow(dst)                                             # AC-14
    old = read_target_version(dst)                                        # AC-11 的模式
    plan = plan_mirror(src_files, dst)                                    # AC-1～AC-4、AC-14b
    local_data = plan_local(root)                                         # AC-7
    template = load_template()                                            # 入口規格 AC-8
    targets, advisories = choose_targets(root)                            # 入口規格 AC-7
    if not os.path.lexists(root / CONFIG_FILE):
        advisories.append(YML_ADVISORY)           # AC-9；順序在入口規格 AC-7 的 advisory 之後
    # 入口規格的原子性：先對集合內全部檔案做決策（含可寫性），任一檔出錯則皆不寫、stdout 全抑制。
    # 入口檔的決策排在鏡像可寫性之前：兩者都是 exit 2，stderr 恰一行，先報使用者自己那幾個檔。
    decisions, errors = [], []
    for name in targets:
        try:
            decisions.append(decide(root, name, template))
        except InstallError as e:
            errors.append(e)
    if errors:
        # exit 非 0 時 stderr 恰一行（kit-install「驗收標準」對入口規格的收窄）。exit code 仍取
        # 最重的那一個——入口規格的原子性是「集合內任一檔出錯就都不寫」，這點沒變；只是訊息
        # 報決定它的第一個錯，不再把集合內每個錯都印出來
        code = max(e.code for e in errors)
        print(next(e.message for e in errors if e.code == code), file=sys.stderr)
        return code
    check_writable(dst, plan, local_data, root)                           # AC-15
    # ── 報表：先寫進記憶體。exit 3 也要抑制 stdout，所以寫入階段全部成功才落到終端 ──
    buf = io.BytesIO()
    kit_report(buf, old, version, plan, local_data)                       # AC-11
    for d in decisions:
        report(buf, d, dry_run)                                           # 入口規格 AC-3／AC-10
    # ── 寫入階段：AC-16 的全序；OSError → exit 3，已完成的步驟不回滾 ──
    if not dry_run:
        write_mirror(dst, plan)
        if local_data is not None:
            write_local(root, local_data)
        write_entry(root, decisions)
    out = sys.stdout.buffer
    out.write(buf.getvalue())
    out.flush()
    for message in advisories:                    # AC-9：只在 exit 0 時印
        print(message, file=sys.stderr)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="把 agent-devflow 安裝到目標專案：鏡像 devflow/、建 devflow.local/、"
                    "插入口區塊到 CLAUDE.md／AGENTS.md。升級與回復＝換一個 kit checkout 重跑。"
                    "入口區塊外逐 byte 不變、重跑冪等、碰撞時報錯且不寫任何檔。",
        epilog="來源：%s（版本 %s）。exit 0 成功、1 入口區塊碰撞、2 決策階段的環境或用法錯誤、"
               "3 寫入階段的 I/O 失敗（不回滾，重跑即恢復）。"
               % (SRC, VERSION_PATH))
    parser.add_argument("target", help="目標 repo 根目錄")
    parser.add_argument("--dry-run", action="store_true",
                        help="不寫檔；走完整個決策階段，exit code、stderr 與 stdout 的摘要行／"
                             "動作行同實際執行，入口檔部分印 unified diff")
    args = parser.parse_args(argv)
    try:
        return run(args.target, args.dry_run)
    except InstallError as e:
        print(e.message, file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
