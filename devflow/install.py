#!/usr/bin/env python3
"""devflow/install.py — 把入口區塊安全插入目標專案的 CLAUDE.md／AGENTS.md。

用法：
    python3 devflow/install.py <目標 repo 路徑> [--dry-run]
    python3 devflow/install.py --help

    exit 0：成功（含 unchanged）；exit 1：內容碰撞（有 begin 無 end，AC-5；begin 之前有
    落單 end、或只有 end 沒有 begin，AC-5b）；
    exit 2：無法執行（目標路徑不對、模板不合規、入口檔不是一般檔案或 dangling symlink、
    不可寫、讀取失敗）。exit 1／2 時不寫任何檔、stdout 全部抑制——可寫性在決策階段用
    os.access 前置檢查（dry-run 與實跑皆做，AC-10）；檢查後仍發生的 OSError（檢查與寫入
    之間的競態）不在此承諾內。

規格：docs/spec/install/spec.md（AC-1～AC-12；名詞定義是法，本檔照字面實作）。
測試：python3 tests/install/harness.py（每條 AC 每個分支一案，在 /tmp 建假專案；
可寫性案例以非 root 執行，root 下標 SKIP）。

只做入口區塊：不複製 devflow/、不建 devflow.yml、不碰 .gitignore、不 commit。
Python ≥ 3.8、stdlib only；讀寫一律 bytes，區塊外逐 byte 不變（D2）。
「存在」以 os.path.lexists 判：symlink 一律視為存在；dangling symlink、目錄、指向目錄的
symlink 都是 exit 2，安裝器不替使用者決定該建到哪裡。

與 `d2` 判準 B 的關係（.github/workflows/devflow-checks.yml 的 entry_block()）：
- 標記行＝檔案 bytes 以 \\n 切行、每行 UTF-8 decode（errors="replace"）後
  `line.strip() == "<!-- devflow:begin -->"`（或 end）。字面比對，不看 markdown 結構、
  不看縮排、不看是否在 code fence 內。第一組的選取與 strip() 語意與判準 B 一致。
- 與 CI **刻意不同**的一點：檔首 UTF-8 BOM（EF BB BF）不剝除，屬第一行內容，所以
  「BOM＋begin」的首行不是標記行；CI 以 utf-8-sig 讀檔會先剝 BOM。安裝器以 bytes 為準、
  不解碼整檔。差異只影響「BOM 開頭且首行為 begin」一種輸入，記 #22 待對齊。
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
import os
import re
import sys
from pathlib import Path

BEGIN = "<!-- devflow:begin -->"
END = "<!-- devflow:end -->"
ENTRY_FILES = ("CLAUDE.md", "AGENTS.md")
D2_MAX_LINES = 30
TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "entry-block.md"
# AC-7：不做 YAML 解析。「鍵行」＝空格縮排 ＋ ASCII 裸鍵 ＋ `:` ＋（空白 ＋ 單一 token）？＋
# （空白 ＋ # 註解）？，到行尾；token 到空白或 # 為止，不去引號（同舊 ^coder: 的取法）。
# 只靠縮排判巢狀，取 seats → implementer → filler 路徑上每層的第一個匹配。#68 起讀此路徑；
# spec AC-7 仍寫 ^coder:，待修訂（見 #68 留言）。
KEY_RE = re.compile(r"^( *)([A-Za-z_][A-Za-z0-9_.-]*):(?:\s+([^\s#]+))?(?:\s+#.*)?\s*$")
SEATS_PATH = ("seats", "implementer", "filler")


class InstallError(Exception):
    """帶 exit code 的錯誤；訊息印到 stderr。1＝內容碰撞，2＝無法執行。"""

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
    「BOM＋begin」不是標記行（spec 名詞定義，與 CI 刻意不同）。
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


def read_implementer(root):
    """devflow.yml 的 seats.implementer.filler 值；任何讀不到／不匹配都回 None，永不報錯。

    `seats:` 須在第 0 欄（同舊 ^coder: 的錨定）且無值；`implementer:` 縮排大於 `seats:` 且無值；
    `filler:` 縮排大於 `implementer:` 且有值。縮排退回到某層鍵的欄位（或更外）＝離開該層。
    空行與 # 註解行不影響層級。

    fail closed：所在層在路徑上（`seats:` 之內、或 `seats.implementer:` 之內）時，出現任何不是
    「鍵行」（KEY_RE）的非空非註解行——引號鍵、非 ASCII 鍵、`- ` 序列項、流式 `{`／`}`、
    `<<:` 合併鍵、區塊純量的內容行、tab 縮排、值後接多餘 token——即回 None：那些都是 scanner
    看不見的中間父節點或無法判定的結構，繼續掃會把更深層的 `filler` 誤當成 implementer 的直接
    子項。路徑外（其他職位、其他頂層鍵）的不明行只略過：它們的縮排大於所屬區塊的鍵，任何
    縮排更深的後續行都仍在該區塊內、不會被當成路徑上的鍵，故不影響結果。
    路徑上的鍵帶值（`seats: x`、`implementer: &a`、流式 `seats: {…}`）不視為區塊，其下不再匹配。
    重複鍵是無效 YAML，取第一個匹配（同舊行為）。token 不去引號：`filler: "claude-code"`
    讀到的是帶引號的字串，不等於 claude-code。
    """
    try:
        text = (root / "devflow.yml").read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    stack = []   # 目前所在各層：(鍵的縮排, 是否在 SEATS_PATH 上)；空＝頂層
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue                                   # 空行、註解行：不影響層級
        m = KEY_RE.match(line)
        indent = len(m.group(1)) if m else len(line) - len(line.lstrip(" "))
        while stack and indent <= stack[-1][0]:
            stack.pop()                                # 縮排退回＝離開該層
        if not m:
            if stack and stack[-1][1]:
                return None                            # 路徑內的不明結構：fail closed
            continue                                   # 路徑外：略過
        if indent and not stack:
            continue                                   # 頂層鍵不在第 0 欄：略過
        key, value = m.group(2), m.group(3)
        depth = len(stack)
        if (not stack or stack[-1][1]) and depth < len(SEATS_PATH) and key == SEATS_PATH[depth]:
            if depth == len(SEATS_PATH) - 1:
                if value is not None:
                    return value                       # seats.implementer.filler: <token>
            elif value is None:
                stack.append((indent, True))           # 進入 seats／implementer 區塊
                continue
        stack.append((indent, False))                  # 路徑外的鍵、帶值的路徑鍵、無值的 filler
    return None


def choose_targets(root):
    # 「存在」＝ os.path.lexists：symlink（含 dangling）一律視為存在，由 decide() 再判形狀
    present = [name for name in ENTRY_FILES if os.path.lexists(root / name)]
    if present:
        return present
    return ["CLAUDE.md"] if read_implementer(root) == "claude-code" else ["AGENTS.md"]


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


# ── 輸出 ─────────────────────────────────────────────────────────────


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


def run(target, dry_run):
    root = Path(target)
    if not root.exists():
        raise InstallError(2, "%s: 目標路徑不存在" % target)             # AC-11
    if not root.is_dir():
        raise InstallError(2, "%s: 目標路徑不是目錄" % target)           # AC-11
    template = load_template()                                            # AC-8
    targets = choose_targets(root)                                        # AC-7
    # 原子性：先對集合內全部檔案做決策（含可寫性），任一檔出錯則皆不寫、stdout 全抑制
    decisions, errors = [], []
    for name in targets:
        try:
            decisions.append(decide(root, name, template))
        except InstallError as e:
            errors.append(e)
    if errors:
        for e in errors:
            print(e.message, file=sys.stderr)
        return max(e.code for e in errors)
    if not dry_run:
        for d in decisions:
            if d.kind != "unchanged":
                try:
                    # 直接開檔覆寫（不走 temp+rename）：CLAUDE.md 常是 AGENTS.md 的 symlink，
                    # 換 inode 會把 symlink 換成普通檔
                    (root / d.name).write_bytes(d.new)
                except OSError as e:
                    # 可寫性已前置檢查過；走到這裡是檢查與寫入之間的競態，不在原子性承諾內
                    raise InstallError(2, "%s: 寫入失敗：%s" % (d.display, e))
    out = sys.stdout.buffer
    for d in decisions:
        report(out, d, dry_run)
    out.flush()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="把 agent-devflow 入口區塊插入目標專案的 CLAUDE.md／AGENTS.md。"
                    "區塊外逐 byte 不變、重跑冪等、碰撞時報錯且不寫任何檔。",
        epilog="模板：%s。exit 0 成功、1 內容碰撞（begin 無 end、begin 前有落單 end）、"
               "2 無法執行（目標路徑、模板、非一般檔案／dangling symlink、不可寫）。" % TEMPLATE_PATH)
    parser.add_argument("target", help="目標 repo 根目錄")
    parser.add_argument("--dry-run", action="store_true",
                        help="不寫檔；exit code 與 stderr 同實際執行，成功時 stdout 印 unified diff")
    args = parser.parse_args(argv)
    try:
        return run(args.target, args.dry_run)
    except InstallError as e:
        print(e.message, file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
