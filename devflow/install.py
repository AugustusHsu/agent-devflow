#!/usr/bin/env python3
"""devflow/install.py — 把入口區塊安全插入目標專案的 CLAUDE.md／AGENTS.md。

用法：
    python3 devflow/install.py <目標 repo 路徑> [--dry-run]
    python3 devflow/install.py --help

    exit 0：成功（含 unchanged）；exit 1：內容碰撞（有 begin 無 end，AC-5）；
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
- 第一組＝檔案第一個 begin 標記行到其後第一個 end 標記行；begin 之前的落單 end 不算，
  第一組之後的任何標記行一律忽略（不計數、不報錯、不改動）。
- CI 只驗第一組 ≤30 行；本檔用同一判準找第一組，並只對那一段做等值比對／取代。

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
# AC-7：不做 YAML 解析，逐行取第一個匹配
CODER_RE = re.compile(r"^coder:\s*([^\s#]+)")


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
    """回傳 (begin_idx, end_idx)，0-based；找不到的那一端是 None。與 CI entry_block() 同義。"""
    begin = next((i for i, line in enumerate(lines) if is_marker(line, BEGIN)), None)
    if begin is None:
        return None, None
    end = next((i for i in range(begin + 1, len(lines)) if is_marker(lines[i], END)), None)
    return begin, end


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


def read_coder(root):
    """devflow.yml 的 coder 值；任何讀不到／不匹配都回 None，永不報錯。"""
    try:
        text = (root / "devflow.yml").read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for line in text.splitlines():
        m = CODER_RE.match(line)
        if m:
            return m.group(1)
    return None


def choose_targets(root):
    # 「存在」＝ os.path.lexists：symlink（含 dangling）一律視為存在，由 decide() 再判形狀
    present = [name for name in ENTRY_FILES if os.path.lexists(root / name)]
    if present:
        return present
    return ["CLAUDE.md"] if read_coder(root) == "claude-code" else ["AGENTS.md"]


# ── 決策（AC-1～AC-6、可寫性）───────────────────────────────────────


def decide(root, name, template):
    """一個目標檔的決策；exit 1／2 路徑以 InstallError 拋出。

    可寫性在這裡檢查（不是寫入時才發現）：將被寫入的既有檔查 os.access(W_OK)、將被建立的
    檔查其目錄；dry-run 與實跑皆走同一條路，exit code 與 stderr 才會一致（AC-10）。
    unchanged 與 AC-5 的檔不會被寫入，不檢查。
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
    begin, end = first_group(lines)
    if begin is None:
        decision = Decision(name, display, "insert", data, template + b"\n" + data)  # AC-2
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
        epilog="模板：%s。exit 0 成功、1 內容碰撞（begin 無 end）、2 無法執行"
               "（目標路徑、模板、非一般檔案／dangling symlink、不可寫）。" % TEMPLATE_PATH)
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
