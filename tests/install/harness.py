#!/usr/bin/env python3
"""tests/install/harness.py — devflow/install.py 的驗收測試（spec AC-1～AC-13）。

執行：
    python3 tests/install/harness.py            # 全部案例
    python3 tests/install/harness.py AC-7       # 只跑名稱含 AC-7 的案例

規格：docs/spec/install/spec.md。每條 AC 的每個分支至少一案（AC-12）。

作法：
- 每案在 /tmp（tempfile 預設目錄）建獨立假專案，跑完清理，可獨立重跑。
- 假專案內容以 bytes 字面量寫在案例裡，不用 fixture 檔——spec 的 AC 全以 bytes 定義
  （CRLF、無尾端換行、BOM、非 UTF-8），fixture 檔會被編輯器與 git 正規化掉。
- 斷言一律 bytes 比對；「不寫檔」另以 mtime 驗證（同 bytes 重寫也算寫）。
- 需要別的模板時（AC-8 >30 行、模板正規化），把 install.py 複製到暫存目錄並放
  自己的 templates/entry-block.md——install.py 以 __file__ 定位模板，不是 cwd。
- 可寫性案例（chmod 0444 檔、0555 目錄）以非 root 為前提：root 對它們 os.access(W_OK)
  恆真，構造不出反例；偵測到 os.geteuid() == 0 時該類案例標 SKIP（不算 FAIL）。
- 輸出每案一行 `PASS|FAIL|SKIP <AC-n>-<分支名>`，失敗細節印到 stderr，最後一行總計
  （含 skip 數）；無 FAIL 即 exit 0。
"""
import difflib
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
INSTALL = REPO / "devflow" / "install.py"
TEMPLATE_PATH = REPO / "devflow" / "templates" / "entry-block.md"

BEGIN = b"<!-- devflow:begin -->"
END = b"<!-- devflow:end -->"
BEGIN_LINE = BEGIN + b"\n"
END_LINE = END + b"\n"

# 模板 bytes。harness 直接用檔案原始 bytes 當期望值，不重做正規化；
# 先驗檔案本身已是正規形（LF、無 BOM、尾端恰一個 \n、首尾為標記行），否則期望值不可信。
T = TEMPLATE_PATH.read_bytes()

# 常用的專案內容片段。PREFIX 恰 4 行，AC-5 的行號斷言依賴這點。
PREFIX = b"# My project\n\nSome custom notes.\n\n"
SUFFIX = b"\n## Team conventions\n\n- keep it simple\n"
OLD_BLOCK = BEGIN_LINE + b"## old devflow block\n\nstale content\n" + END_LINE
FIXED_MTIME = 1_000_000_000  # 2001-09-09，用來偵測「有沒有重寫檔案」


def seats(filler):
    """devflow.yml 片段：seats.implementer.filler（#68 起的結構；AC-7 只讀這一條路徑）。"""
    return b"seats:\n  implementer:\n    filler: " + filler + b"\n"


YML_CLAUDE = seats(b"claude-code")
YML_CODEX = seats(b"codex")


def block_of_lines(n):
    """含兩標記行共 n 行的區塊，尾端恰一個 \\n。"""
    body = b"".join(b"line %d\n" % i for i in range(n - 2))
    return BEGIN_LINE + body + END_LINE


def unified(old, new, name):
    """spec AC-10 指定的 diff 形式：difflib.unified_diff、路徑 a/<檔>／b/<檔>。"""
    return b"".join(difflib.diff_bytes(
        difflib.unified_diff, split_lf(old), split_lf(new),
        fromfile=b"a/" + name, tofile=b"b/" + name))


def split_lf(data):
    """只以 \\n 切行、保留行尾（bytes.splitlines 會在 \\r 切，不合用）。"""
    lines, start = [], 0
    while start < len(data):
        i = data.find(b"\n", start)
        if i < 0:
            lines.append(data[start:])
            break
        lines.append(data[start:i + 1])
        start = i + 1
    return lines


# ── 斷言 ─────────────────────────────────────────────────────────────


class Failure(Exception):
    pass


class Skip(Exception):
    pass


def require_non_root():
    """可寫性案例的前提（spec 名詞「可寫性」）：root 對 0444／0555 的 os.access(W_OK) 恆真。"""
    if os.geteuid() == 0:
        raise Skip("running as root: os.access(W_OK) is always true, cannot build a counterexample")


def short(v, n=160):
    r = repr(v)
    return r if len(r) <= n else r[:n] + "…(%d chars)" % len(r)


def expect(cond, what, actual=None, expected=None):
    if cond:
        return
    msg = what
    if actual is not None or expected is not None:
        msg += "\n      expected: %s\n      actual:   %s" % (short(expected), short(actual))
    raise Failure(msg)


def eq(actual, expected, what):
    expect(actual == expected, what, actual, expected)


# ── 假專案 ───────────────────────────────────────────────────────────


class Project:
    def __init__(self, files):
        self.root = Path(tempfile.mkdtemp(prefix="devflow-install-"))
        for name, data in files.items():
            self.write(name, data)

    def path(self, name):
        return self.root / name

    def display(self, name):
        """install.py 印出的 <路徑>：目標路徑參數與檔名相接。"""
        return str(self.root / name).encode()

    def write(self, name, data):
        self.path(name).write_bytes(data)
        # 固定 mtime，讓「有沒有重寫」可觀測
        os.utime(self.path(name), (FIXED_MTIME, FIXED_MTIME))

    def read(self, name):
        return self.path(name).read_bytes()

    def exists(self, name):
        return self.path(name).exists()

    def rewritten(self, name):
        return self.path(name).stat().st_mtime != FIXED_MTIME

    def chmod(self, name, mode):
        os.chmod(self.path(name), mode)

    def symlink(self, name, target):
        os.symlink(target, self.path(name))

    def run(self, *flags, install=INSTALL, target=None):
        cmd = [sys.executable, str(install), target or str(self.root), *flags]
        return subprocess.run(cmd, capture_output=True)

    def cleanup(self):
        os.chmod(self.root, 0o700)   # 目錄不可寫的案例先還原，否則 rmtree 刪不掉子項
        remove_tree(self.root)


def remove_tree(path):
    """清理失敗不靜默：印到 stderr，讓 /tmp 殘留可被看見。"""
    try:
        shutil.rmtree(path)
    except OSError as e:
        print("warning: could not remove %s: %s" % (path, e), file=sys.stderr, flush=True)


@contextmanager
def project(files=None):
    p = Project(files or {})
    try:
        yield p
    finally:
        p.cleanup()


@contextmanager
def sandboxed_install(template=None):
    """把 install.py 複製到暫存目錄，配上自訂模板（None＝不放模板檔）。"""
    d = Path(tempfile.mkdtemp(prefix="devflow-install-sandbox-"))
    try:
        shutil.copy(INSTALL, d / "install.py")
        if template is not None:
            (d / "templates").mkdir()
            (d / "templates" / "entry-block.md").write_bytes(template)
        yield d / "install.py"
    finally:
        remove_tree(d)


def ok_run(r):
    """exit 0、stderr 空。"""
    eq(r.returncode, 0, "exit code（stderr=%s）" % short(r.stderr))
    eq(r.stderr, b"", "stderr")


def err_run(r, code):
    """exit 1／2：stdout 全部抑制（AC-10）。"""
    eq(r.returncode, code, "exit code（stderr=%s）" % short(r.stderr))
    eq(r.stdout, b"", "stdout must be suppressed on exit %d" % code)
    expect(r.stderr != b"", "stderr must explain")


# ── 案例 ─────────────────────────────────────────────────────────────

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


# AC-1：目標檔不存在 → 建檔，bytes 恰等於模板

@case("AC-1-missing-creates-template")
def _():
    with project() as p:
        r = p.run()
        ok_run(r)
        eq(p.read("AGENTS.md"), T, "AGENTS.md == template")
        expect(not p.exists("CLAUDE.md"), "CLAUDE.md must not be created")


@case("AC-1-template-normalized-bom-crlf-trailing")
def _():
    # 模板定義：正規化為 LF、無 BOM、尾端恰一個 \n
    raw = b"\xef\xbb\xbf" + T.replace(b"\n", b"\r\n") + b"\r\n\r\n"
    with sandboxed_install(raw) as inst, project() as p:
        r = p.run(install=inst)
        ok_run(r)
        eq(p.read("AGENTS.md"), T, "created bytes == normalized template")


# AC-2：無任何標記行 → 檔首插入：模板 + \n + 原檔
# （只有 end 沒有 begin 不走這裡——那是 AC-5b 拒絕）

@case("AC-2-no-markers-inserts-at-byte-0")
def _():
    orig = PREFIX + SUFFIX
    with project({"CLAUDE.md": orig}) as p:
        r = p.run()
        ok_run(r)
        out = p.read("CLAUDE.md")
        eq(out, T + b"\n" + orig, "output == template + \\n + original")
        eq(out[len(T) + 1:], orig, "original bytes start at len(template)+1")


@case("AC-2-frontmatter-still-byte-0")
def _():
    orig = b"---\ntitle: x\n---\n" + PREFIX
    with project({"AGENTS.md": orig}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("AGENTS.md"), T + b"\n" + orig, "frontmatter is project content; insert at byte 0")


@case("AC-2-leading-newline-kept")
def _():
    orig = b"\n\n" + PREFIX
    with project({"CLAUDE.md": orig}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("CLAUDE.md"), T + b"\n" + orig, "leading newlines not deduplicated")


@case("AC-2-empty-file")
def _():
    with project({"CLAUDE.md": b""}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("CLAUDE.md"), T + b"\n", "empty original → template + \\n")


@case("AC-2-crlf-original-kept")
def _():
    orig = (PREFIX + SUFFIX).replace(b"\n", b"\r\n")
    with project({"CLAUDE.md": orig}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("CLAUDE.md"), T + b"\n" + orig, "CRLF original untouched byte-for-byte")


# AC-3：第一組等於模板 → 不寫檔、exit 0、stdout `<路徑>: unchanged`

@case("AC-3-equal-unchanged")
def _():
    data = PREFIX + T + SUFFIX
    with project({"CLAUDE.md": data}) as p:
        r = p.run()
        ok_run(r)
        eq(r.stdout, p.display("CLAUDE.md") + b": unchanged\n", "stdout")
        eq(p.read("CLAUDE.md"), data, "bytes")
        expect(not p.rewritten("CLAUDE.md"), "file must not be rewritten")


@case("AC-3-equal-after-crlf-normalization")
def _():
    data = PREFIX + T.replace(b"\n", b"\r\n") + SUFFIX
    with project({"CLAUDE.md": data}) as p:
        r = p.run()
        ok_run(r)
        eq(r.stdout, p.display("CLAUDE.md") + b": unchanged\n", "stdout")
        eq(p.read("CLAUDE.md"), data, "CRLF block left as is")
        expect(not p.rewritten("CLAUDE.md"), "file must not be rewritten")


# AC-4：第一組不等於模板 → 原檔[begin 行首前] + 模板 + 原檔[end 行行尾後]

@case("AC-4-differs-replaced")
def _():
    with project({"CLAUDE.md": PREFIX + OLD_BLOCK + SUFFIX}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("CLAUDE.md"), PREFIX + T + SUFFIX, "block replaced, outside untouched")


@case("AC-4-end-line-crlf-replaced-with-it")
def _():
    with project({"CLAUDE.md": PREFIX + OLD_BLOCK.replace(b"\n", b"\r\n") + SUFFIX}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("CLAUDE.md"), PREFIX + T + SUFFIX, "end line's \\r\\n consumed with the block")


@case("AC-4-end-at-eof-no-newline")
def _():
    with project({"CLAUDE.md": PREFIX + OLD_BLOCK[:-1]}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("CLAUDE.md"), PREFIX + T, "span ends at EOF; template's trailing \\n adds one")


@case("AC-4-later-markers-untouched")
def _():
    tail = SUFFIX + BEGIN_LINE + b"example\n" + END_LINE + b"\n" + BEGIN_LINE
    with project({"CLAUDE.md": PREFIX + OLD_BLOCK + tail}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("CLAUDE.md"), PREFIX + T + tail, "only the first group replaced")


@case("AC-4-indented-markers-match-criterion-b")
def _():
    # 判準 B 是 strip 後比對：縮排／尾端空白的標記行也是標記行，整行（含縮排）屬第一組
    old = b"  " + BEGIN + b"\n" + b"old\n" + b"\t" + END + b"  \n"
    with project({"CLAUDE.md": PREFIX + old + SUFFIX}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("CLAUDE.md"), PREFIX + T + SUFFIX, "indented markers replaced from line start")


# AC-5：有 begin、其後無 end → exit 1、不寫、stderr `<路徑>:<行號>: devflow:begin without end`

@case("AC-5-begin-without-end")
def _():
    data = PREFIX + BEGIN_LINE + b"no end here\n"  # begin 在第 5 行
    with project({"CLAUDE.md": data}) as p:
        r = p.run()
        err_run(r, 1)
        eq(r.stderr, p.display("CLAUDE.md") + b":5: devflow:begin without end\n", "stderr")
        eq(p.read("CLAUDE.md"), data, "bytes")
        expect(not p.rewritten("CLAUDE.md"), "file must not be rewritten")
        expect(not p.exists("AGENTS.md"), "AGENTS.md must not be created")


# AC-5b：第一個 begin 之前有 end 標記行、或無 begin 但有 end → exit 1、不寫、
# stderr `<路徑>:<最早的 end 行號>: stray devflow:end before begin`（D2：區塊前不得有任何標記行）


def stray_run(r, p, name, lineno, data):
    """AC-5b 的共同斷言：exit 1、stderr 格式與行號、bytes 不變、未重寫。"""
    err_run(r, 1)
    eq(r.stderr, p.display(name) + b":%d: stray devflow:end before begin\n" % lineno, "stderr")
    eq(p.read(name), data, "bytes")
    expect(not p.rewritten(name), "file must not be rewritten")


@case("AC-5b-stray-end-before-begin")
def _():
    # 分支一：落單 end 在 begin 前（begin 其後無 end）。AC-5b 先於 AC-5：報的是 end 那行，
    # 不是 begin 那行的 `devflow:begin without end`
    data = END_LINE + b"x\n" + BEGIN_LINE + b"y\n"  # end 在第 1 行、begin 在第 3 行
    with project({"AGENTS.md": data}) as p:
        stray_run(p.run(), p, "AGENTS.md", 1, data)


@case("AC-5b-only-end-no-begin")
def _():
    # 分支二：只有 end。原本是 AC-2 的插入路徑（落單 end 當專案內容），1.0.0.0 的 D2 起改為拒絕
    data = PREFIX + END_LINE + SUFFIX  # end 在第 5 行
    with project({"CLAUDE.md": data}) as p:
        stray_run(p.run(), p, "CLAUDE.md", 5, data)
        expect(not p.exists("AGENTS.md"), "AGENTS.md must not be created")


@case("AC-5b-stray-end-before-complete-group")
def _():
    # 分支三：落單 end 在 begin 前、begin 後也有正常 end（第一組等於模板，原本會走 AC-3 unchanged）
    data = b"intro\n" + END_LINE + T + SUFFIX  # end 在第 2 行
    with project({"AGENTS.md": data}) as p:
        stray_run(p.run(), p, "AGENTS.md", 2, data)


@case("AC-5b-stray-end-before-differing-group")
def _():
    # 分支三的另一面：第一組不等於模板（原本會走 AC-4 replace），一樣拒絕、不動任何 byte
    data = PREFIX + END_LINE + OLD_BLOCK + SUFFIX  # end 在第 5 行
    with project({"CLAUDE.md": data}) as p:
        stray_run(p.run(), p, "CLAUDE.md", 5, data)


@case("AC-5b-earliest-stray-end-reported")
def _():
    data = b"a\n" + END_LINE + b"b\n" + END_LINE + T  # 兩個落單 end，取第 2 行
    with project({"CLAUDE.md": data}) as p:
        stray_run(p.run(), p, "CLAUDE.md", 2, data)


@case("AC-5b-indented-stray-end-is-marker")
def _():
    # 判準 B 是 strip 後比對：縮排的 end 也是標記行，一樣算落單
    data = PREFIX + b"  " + END + b"  \n" + T  # end 在第 5 行
    with project({"CLAUDE.md": data}) as p:
        stray_run(p.run(), p, "CLAUDE.md", 5, data)


@case("AC-5b-end-inside-later-content-is-not-stray")
def _():
    # 對照：end 在第一組**之後**不算落單（AC-6），仍是 unchanged
    data = T + b"\n" + END_LINE + b"tail\n"
    with project({"CLAUDE.md": data}) as p:
        r = p.run()
        ok_run(r)
        eq(r.stdout, p.display("CLAUDE.md") + b": unchanged\n", "stdout")
        expect(not p.rewritten("CLAUDE.md"), "file must not be rewritten")


@case("AC-5b-dry-run-matches-real")
def _():
    data = b"x\n" + END_LINE + PREFIX
    with project({"AGENTS.md": data}) as dry, project({"AGENTS.md": data}) as real:
        rd = dry.run("--dry-run")
        rr = real.run()
        stray_run(rd, dry, "AGENTS.md", 2, data)
        stray_run(rr, real, "AGENTS.md", 2, data)
        eq(rd.stderr.replace(dry.display(""), b""), rr.stderr.replace(real.display(""), b""),
           "stderr same as real run (modulo tmp path)")


@case("AC-5b-atomic-other-file-not-written")
def _():
    # 原子性：CLAUDE.md 可插入、AGENTS.md 有落單 end → 兩檔皆不寫
    bad = END_LINE + PREFIX
    with project({"CLAUDE.md": PREFIX, "AGENTS.md": bad}) as p:
        stray_run(p.run(), p, "AGENTS.md", 1, bad)
        eq(p.read("CLAUDE.md"), PREFIX, "writable CLAUDE.md must not be written")
        expect(not p.rewritten("CLAUDE.md"), "CLAUDE.md must not be rewritten")


# AC-6：第一組之後的任何標記行 → 忽略（不計數、不報錯、不改動）

@case("AC-6-later-markers-ignored-unchanged")
def _():
    data = PREFIX + T + b"\n" + BEGIN_LINE + b"example\n" + END_LINE + BEGIN_LINE
    with project({"CLAUDE.md": data}) as p:
        r = p.run()
        ok_run(r)
        eq(r.stdout, p.display("CLAUDE.md") + b": unchanged\n", "later lone begin must not raise AC-5")
        eq(p.read("CLAUDE.md"), data, "bytes")
        expect(not p.rewritten("CLAUDE.md"), "file must not be rewritten")


@case("AC-6-later-lone-begin-no-error-on-replace")
def _():
    tail = SUFFIX + BEGIN_LINE
    with project({"CLAUDE.md": PREFIX + OLD_BLOCK + tail}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("CLAUDE.md"), PREFIX + T + tail, "first group replaced; later begin untouched")


# AC-7：目標檔集合

@case("AC-7-both-exist-both-processed")
def _():
    a, c = b"# agents\n", PREFIX
    with project({"CLAUDE.md": c, "AGENTS.md": a}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("CLAUDE.md"), T + b"\n" + c, "CLAUDE.md")
        eq(p.read("AGENTS.md"), T + b"\n" + a, "AGENTS.md")


@case("AC-7-only-claude-no-agents-created")
def _():
    with project({"CLAUDE.md": PREFIX}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("CLAUDE.md"), T + b"\n" + PREFIX, "CLAUDE.md")
        expect(not p.exists("AGENTS.md"), "AGENTS.md must not be created")


@case("AC-7-only-agents-no-claude-created")
def _():
    with project({"AGENTS.md": PREFIX}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("AGENTS.md"), T + b"\n" + PREFIX, "AGENTS.md")
        expect(not p.exists("CLAUDE.md"), "CLAUDE.md must not be created")


@case("AC-7-only-agents-ignores-devflow-yml")
def _():
    with project({"AGENTS.md": PREFIX, "devflow.yml": YML_CLAUDE}) as p:
        r = p.run()
        ok_run(r)
        expect(not p.exists("CLAUDE.md"), "devflow.yml only consulted when both are absent")


@case("AC-7-none-implementer-claude-code")
def _():
    # 本 repo devflow.yml 的形狀：其他頂層鍵、行尾註解、註解行、同層其他職位與選填欄位都在
    yml = (b"forge: github          # github | gitlab\n"
           b"\n"
           b"# seat bindings\n"
           b"seats:\n"
           b"  implementer:               # \xe5\xaf\xa6\xe4\xbd\x9c\xe4\xbd\x8d (UTF-8 comment)\n"
           b"    filler: claude-code      # claude-code | codex\n"
           b"  reviewer:\n"
           b"    filler: codex\n"
           b"    model: gpt-5.6-sol\n"
           b"    reasoning: high\n"
           b"stage: 1\n")
    with project({"devflow.yml": yml}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("CLAUDE.md"), T, "CLAUDE.md created")
        expect(not p.exists("AGENTS.md"), "AGENTS.md must not be created")


@case("AC-7-none-implementer-codex")
def _():
    with project({"devflow.yml": YML_CODEX}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("AGENTS.md"), T, "AGENTS.md created")
        expect(not p.exists("CLAUDE.md"), "CLAUDE.md must not be created")


@case("AC-7-none-no-devflow-yml")
def _():
    with project() as p:
        r = p.run()
        ok_run(r)
        eq(p.read("AGENTS.md"), T, "AGENTS.md created")
        expect(not p.exists("CLAUDE.md"), "CLAUDE.md must not be created")


@case("AC-7-none-non-yaml-with-seats-block")
def _():
    yml = b"{{{ this is: not: [yaml\n" + YML_CLAUDE + b"]]] ::: junk\n"
    with project({"devflow.yml": yml}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("CLAUDE.md"), T, "regex line match, no YAML parse")
        expect(not p.exists("AGENTS.md"), "AGENTS.md must not be created")


@case("AC-7-none-devflow-yml-not-utf8")
def _():
    with project({"devflow.yml": b"\xff\xfe" + YML_CLAUDE}) as p:
        r = p.run()
        ok_run(r)  # 永不報錯
        eq(p.read("AGENTS.md"), T, "undecodable devflow.yml → AGENTS.md")
        expect(not p.exists("CLAUDE.md"), "CLAUDE.md must not be created")


@case("AC-7-none-devflow-yml-is-directory")
def _():
    with project() as p:
        p.path("devflow.yml").mkdir()
        r = p.run()
        ok_run(r)  # 永不報錯
        eq(p.read("AGENTS.md"), T, "unreadable devflow.yml → AGENTS.md")


@case("AC-7-none-indented-seats-no-match")
def _():
    with project({"devflow.yml": b"tool:\n  seats:\n    implementer:\n      filler: claude-code\n"}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("AGENTS.md"), T, "seats: must be a top-level key at column 0")
        expect(not p.exists("CLAUDE.md"), "CLAUDE.md must not be created")


@case("AC-7-none-first-implementer-wins")
def _():
    with project({"devflow.yml": YML_CODEX + b"  implementer:\n    filler: claude-code\n"}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("AGENTS.md"), T, "first match is codex")
        expect(not p.exists("CLAUDE.md"), "CLAUDE.md must not be created")


@case("AC-7-none-filler-under-other-seat-no-match")
def _():
    # 正確的值出現在錯誤的位置：reviewer 的 filler 是 claude-code、implementer 是 codex
    yml = b"seats:\n  reviewer:\n    filler: claude-code\n  implementer:\n    filler: codex\n"
    with project({"devflow.yml": yml}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("AGENTS.md"), T, "only seats.implementer.filler is read")
        expect(not p.exists("CLAUDE.md"), "CLAUDE.md must not be created")


@case("AC-7-none-implementer-outside-seats-no-match")
def _():
    # implementer 巢在別的頂層鍵下、或 seats 區塊已被下一個頂層鍵關閉：都不算
    for yml in (b"other:\n  implementer:\n    filler: claude-code\n",
                b"seats:\n  reviewer:\n    filler: codex\nimplementer:\n  filler: claude-code\n"):
        with project({"devflow.yml": yml}) as p:
            r = p.run()
            ok_run(r)
            eq(p.read("AGENTS.md"), T, "implementer must be nested under seats")
            expect(not p.exists("CLAUDE.md"), "CLAUDE.md must not be created")


@case("AC-7-none-tab-indent-no-match")
def _():
    # tab 不是 YAML 縮排；含 tab 開頭的行不匹配，仍永不報錯
    with project({"devflow.yml": b"seats:\n\timplementer:\n\t\tfiller: claude-code\n"}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("AGENTS.md"), T, "tab-indented lines do not match")
        expect(not p.exists("CLAUDE.md"), "CLAUDE.md must not be created")


@case("AC-7-none-legacy-coder-key-ignored")
def _():
    # #68 廢除的舊鍵 coder:（不留別名）：即使值為 claude-code 也不得再被讀成 implementer
    with project({"devflow.yml": b"coder: claude-code\n"}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("AGENTS.md"), T, "legacy coder: key is not read")
        expect(not p.exists("CLAUDE.md"), "CLAUDE.md must not be created")


@case("AC-7-none-devflow-yml-not-created")
def _():
    with project() as p:
        r = p.run()
        ok_run(r)
        expect(not p.exists("devflow.yml"), "devflow.yml must not be created")


@case("AC-7-symlink-to-file-counts-as-present")
def _():
    # 常見配置 CLAUDE.md -> AGENTS.md：兩檔皆「存在」（lexists）、同 inode；symlink 保留
    with project({"AGENTS.md": PREFIX}) as p:
        p.symlink("CLAUDE.md", "AGENTS.md")
        r = p.run()
        ok_run(r)
        eq(p.read("AGENTS.md"), T + b"\n" + PREFIX, "shared content inserted once")
        expect(p.path("CLAUDE.md").is_symlink(), "symlink must be preserved (no inode swap)")
        ok_run(p.run())  # 第二次兩檔 unchanged


@case("AC-7-symlink-only-no-other-created")
def _():
    # 只有 CLAUDE.md（symlink 指向集合外的一般檔）→ 集合只有它，不建 AGENTS.md
    with project({"notes.md": PREFIX}) as p:
        p.symlink("CLAUDE.md", "notes.md")
        r = p.run()
        ok_run(r)
        eq(p.read("notes.md"), T + b"\n" + PREFIX, "written through the symlink")
        expect(not p.exists("AGENTS.md"), "AGENTS.md must not be created")


@case("AC-7-dangling-symlink-exit-2")
def _():
    # lexists 真、exists 假：不替使用者決定建到哪；devflow.yml 也不會被拿來選檔
    with project({"devflow.yml": YML_CLAUDE}) as p:
        p.symlink("CLAUDE.md", "AGENTS.md")
        rd = p.run("--dry-run")
        rr = p.run()
        err_run(rd, 2)
        err_run(rr, 2)
        eq(rd.stderr, rr.stderr, "stderr same in both modes")
        expect(p.display("CLAUDE.md") in rr.stderr, "stderr names the dangling path", rr.stderr)
        expect(not p.exists("AGENTS.md"), "referent must not be created")
        expect(p.path("CLAUDE.md").is_symlink(), "symlink left as is")


@case("AC-7-entry-is-directory-exit-2")
def _():
    with project({"AGENTS.md": PREFIX}) as p:
        p.path("CLAUDE.md").mkdir()
        rd = p.run("--dry-run")
        rr = p.run()
        err_run(rd, 2)
        err_run(rr, 2)
        eq(rr.stderr, p.display("CLAUDE.md") + b": not a regular file\n", "stderr")
        eq(rd.stderr, rr.stderr, "stderr same in both modes")
        eq(p.read("AGENTS.md"), PREFIX, "writable AGENTS.md must not be written (atomic)")
        expect(not p.rewritten("AGENTS.md"), "AGENTS.md must not be rewritten")


@case("AC-7-symlink-to-directory-exit-2")
def _():
    with project() as p:
        p.path("docs").mkdir()
        p.symlink("CLAUDE.md", "docs")
        rd = p.run("--dry-run")
        rr = p.run()
        err_run(rd, 2)
        err_run(rr, 2)
        eq(rr.stderr, p.display("CLAUDE.md") + b": not a regular file\n", "stderr")
        eq(rd.stderr, rr.stderr, "stderr same in both modes")
        expect(not p.exists("AGENTS.md"), "AGENTS.md must not be created")
        eq(sorted(os.listdir(p.path("docs"))), [], "nothing written into the directory")


# AC-8：模板 >30 行 → exit 2、不寫、stderr 說明行數與上限

@case("AC-8-template-31-lines-exit-2")
def _():
    with sandboxed_install(block_of_lines(31)) as inst, project({"CLAUDE.md": PREFIX}) as p:
        r = p.run(install=inst)
        err_run(r, 2)
        expect(b"31" in r.stderr and b"30" in r.stderr, "stderr names line count and limit", r.stderr)
        eq(p.read("CLAUDE.md"), PREFIX, "bytes")
        expect(not p.rewritten("CLAUDE.md"), "file must not be rewritten")


@case("AC-8-template-30-lines-ok")
def _():
    t30 = block_of_lines(30)
    with sandboxed_install(t30) as inst, project({"CLAUDE.md": PREFIX}) as p:
        r = p.run(install=inst)
        ok_run(r)
        eq(p.read("CLAUDE.md"), t30 + b"\n" + PREFIX, "30 lines is within the limit")


# AC-9：連續執行兩次，第二次每檔 unchanged、bytes 與快照相同

@case("AC-9-second-run-unchanged-insert-and-replace")
def _():
    with project({"CLAUDE.md": PREFIX, "AGENTS.md": PREFIX + OLD_BLOCK + SUFFIX}) as p:
        ok_run(p.run())
        snap = {n: p.read(n) for n in ("CLAUDE.md", "AGENTS.md")}
        r = p.run()
        ok_run(r)
        eq(r.stdout, p.display("CLAUDE.md") + b": unchanged\n"
           + p.display("AGENTS.md") + b": unchanged\n", "stdout")
        eq({n: p.read(n) for n in snap}, snap, "bytes == snapshot")


@case("AC-9-second-run-unchanged-after-create")
def _():
    with project() as p:
        ok_run(p.run())
        snap = p.read("AGENTS.md")
        r = p.run()
        ok_run(r)
        eq(r.stdout, p.display("AGENTS.md") + b": unchanged\n", "stdout")
        eq(p.read("AGENTS.md"), snap, "bytes == snapshot")
        expect(not p.exists("CLAUDE.md"), "CLAUDE.md must not be created")


# AC-10：--dry-run

@case("AC-10-dry-run-insert-diff-no-write")
def _():
    orig = PREFIX + SUFFIX
    with project({"CLAUDE.md": orig}) as p:
        r = p.run("--dry-run")
        ok_run(r)
        eq(r.stdout, unified(orig, T + b"\n" + orig, b"CLAUDE.md"), "stdout == unified diff")
        eq(p.read("CLAUDE.md"), orig, "bytes")
        expect(not p.rewritten("CLAUDE.md"), "file must not be rewritten")


@case("AC-10-dry-run-create-diff-no-write")
def _():
    with project() as p:
        r = p.run("--dry-run")
        ok_run(r)
        eq(r.stdout, unified(b"", T, b"AGENTS.md"), "stdout == diff from empty")
        expect(not p.exists("AGENTS.md") and not p.exists("CLAUDE.md"), "nothing created")


@case("AC-10-dry-run-unchanged")
def _():
    data = PREFIX + T + SUFFIX
    with project({"CLAUDE.md": data}) as p:
        r = p.run("--dry-run")
        ok_run(r)
        eq(r.stdout, p.display("CLAUDE.md") + b": unchanged\n", "stdout")
        eq(p.read("CLAUDE.md"), data, "bytes")


@case("AC-10-dry-run-two-files-in-order")
def _():
    a = b"# agents\n"
    with project({"CLAUDE.md": PREFIX + T, "AGENTS.md": a}) as p:
        r = p.run("--dry-run")
        ok_run(r)
        eq(r.stdout, p.display("CLAUDE.md") + b": unchanged\n"
           + unified(a, T + b"\n" + a, b"AGENTS.md"), "stdout: CLAUDE.md then AGENTS.md")
        eq(p.read("AGENTS.md"), a, "AGENTS.md bytes")
        expect(not p.rewritten("AGENTS.md"), "AGENTS.md must not be rewritten")


@case("AC-10-dry-run-no-trailing-newline-exact-difflib")
def _():
    # 原檔最後一行無 \n：diff 最後一行也無 \n，且**不**加 `\ No newline at end of file`
    orig = b"# Proj\n\ncustom"
    with project({"CLAUDE.md": orig}) as p:
        r = p.run("--dry-run")
        ok_run(r)
        expected = unified(orig, T + b"\n" + orig, b"CLAUDE.md")
        expect(not expected.endswith(b"\n"), "precondition: difflib output ends without newline")
        eq(r.stdout, expected, "stdout == difflib output byte for byte")
        expect(b"No newline" not in r.stdout, "no synthetic marker line", r.stdout)


@case("AC-10-dry-run-end-at-eof-replace-exact-difflib")
def _():
    orig = PREFIX + OLD_BLOCK[:-1]   # end 行在 EOF、無換行
    with project({"CLAUDE.md": orig}) as p:
        r = p.run("--dry-run")
        ok_run(r)
        eq(r.stdout, unified(orig, PREFIX + T, b"CLAUDE.md"), "stdout == difflib output byte for byte")
        eq(p.read("CLAUDE.md"), orig, "bytes")


@case("AC-10-dry-run-exit1-suppressed-matches-real")
def _():
    files = {"CLAUDE.md": PREFIX, "AGENTS.md": PREFIX + BEGIN_LINE + b"open\n"}
    with project(files) as dry, project(files) as real:
        rd = dry.run("--dry-run")
        rr = real.run()
        err_run(rd, 1)
        err_run(rr, 1)
        eq(rd.returncode, rr.returncode, "exit code same as real run")
        eq(rd.stderr.replace(dry.display(""), b""), rr.stderr.replace(real.display(""), b""),
           "stderr same as real run (modulo tmp path)")
        for p in (dry, real):
            eq(p.read("CLAUDE.md"), PREFIX, "CLAUDE.md untouched")
            expect(not p.rewritten("CLAUDE.md"), "CLAUDE.md must not be rewritten")


@case("AC-10-dry-run-exit2-suppressed-matches-real")
def _():
    files = {"CLAUDE.md": PREFIX, "AGENTS.md": PREFIX}
    with sandboxed_install(block_of_lines(40)) as inst, project(files) as dry, project(files) as real:
        rd = dry.run("--dry-run", install=inst)
        rr = real.run(install=inst)
        err_run(rd, 2)
        err_run(rr, 2)
        eq(rd.stderr, rr.stderr, "stderr same as real run")
        for p in (dry, real):
            for n in files:
                eq(p.read(n), PREFIX, n + " untouched")


# AC-11：目標路徑不存在／不是目錄 → exit 2、不讀模板、不做決策

@case("AC-11-target-missing")
def _():
    with project() as p:
        missing = str(p.root / "nope")
        r = p.run(target=missing)
        err_run(r, 2)
        expect(missing.encode() in r.stderr, "stderr names the target", r.stderr)


@case("AC-11-target-is-file")
def _():
    with project({"CLAUDE.md": PREFIX}) as p:
        f = str(p.root / "CLAUDE.md")
        r = p.run(target=f)
        err_run(r, 2)
        expect(f.encode() in r.stderr, "stderr names the target", r.stderr)
        eq(p.read("CLAUDE.md"), PREFIX, "bytes")


@case("AC-11-checked-before-template")
def _():
    # 沒有模板檔也一樣是 AC-11 的錯（不讀模板）；也不是 AC-8
    with sandboxed_install(None) as inst, project() as p:
        missing = str(p.root / "nope")
        r = p.run(target=missing, install=inst)
        err_run(r, 2)
        expect(missing.encode() in r.stderr, "stderr names the target", r.stderr)
        expect(b"entry-block.md" not in r.stderr, "template must not be read", r.stderr)


# AC-12：原子性——一檔可寫、另一檔 exit 1／2 → 皆不寫

@case("AC-12-atomic-one-ok-one-exit1")
def _():
    bad = PREFIX + BEGIN_LINE + b"open\n"
    with project({"CLAUDE.md": PREFIX, "AGENTS.md": bad}) as p:
        r = p.run()
        err_run(r, 1)
        eq(r.stderr, p.display("AGENTS.md") + b":5: devflow:begin without end\n", "stderr")
        eq(p.read("CLAUDE.md"), PREFIX, "writable file must not be written")
        expect(not p.rewritten("CLAUDE.md"), "CLAUDE.md must not be rewritten")
        eq(p.read("AGENTS.md"), bad, "AGENTS.md untouched")


@case("AC-12-atomic-both-writable-template-exit2")
def _():
    with sandboxed_install(block_of_lines(31)) as inst, project({"CLAUDE.md": PREFIX, "AGENTS.md": PREFIX}) as p:
        r = p.run(install=inst)
        err_run(r, 2)
        for n in ("CLAUDE.md", "AGENTS.md"):
            eq(p.read(n), PREFIX, n + " untouched")
            expect(not p.rewritten(n), n + " must not be rewritten")


# 可寫性（spec 名詞定義）：決策階段 os.access 檢查，dry-run 與實跑皆做；非 root 前提

@case("AC-12-readonly-file-dry-run-and-real-exit-2")
def _():
    require_non_root()
    with project({"CLAUDE.md": PREFIX}) as p:
        p.chmod("CLAUDE.md", 0o444)
        rd = p.run("--dry-run")
        rr = p.run()
        err_run(rd, 2)
        err_run(rr, 2)
        eq(rd.stderr, rr.stderr, "stderr same in both modes")
        expect(p.display("CLAUDE.md") in rr.stderr, "stderr names the file", rr.stderr)
        eq(p.read("CLAUDE.md"), PREFIX, "bytes")
        expect(not p.rewritten("CLAUDE.md"), "file must not be rewritten")


@case("AC-12-readonly-file-unchanged-is-not-a-write")
def _():
    # 走 AC-3 的檔不會被寫入，不檢查可寫性（root 下也成立，不需 SKIP）
    data = PREFIX + T + SUFFIX
    with project({"CLAUDE.md": data}) as p:
        p.chmod("CLAUDE.md", 0o444)
        r = p.run()
        ok_run(r)
        eq(r.stdout, p.display("CLAUDE.md") + b": unchanged\n", "stdout")


@case("AC-12-atomic-writable-plus-readonly-nothing-written")
def _():
    require_non_root()
    with project({"CLAUDE.md": PREFIX, "AGENTS.md": PREFIX}) as p:
        p.chmod("AGENTS.md", 0o444)
        r = p.run()
        err_run(r, 2)
        expect(p.display("AGENTS.md") in r.stderr, "stderr names the read-only file", r.stderr)
        eq(p.read("CLAUDE.md"), PREFIX, "writable CLAUDE.md must not be written first")
        expect(not p.rewritten("CLAUDE.md"), "CLAUDE.md must not be rewritten")
        eq(p.read("AGENTS.md"), PREFIX, "AGENTS.md untouched")


@case("AC-12-directory-not-writable-create-exit-2")
def _():
    require_non_root()
    with project({"devflow.yml": YML_CLAUDE}) as p:
        os.chmod(p.root, 0o555)
        rd = p.run("--dry-run")
        rr = p.run()
        err_run(rd, 2)
        err_run(rr, 2)
        eq(rd.stderr, rr.stderr, "stderr same in both modes")
        expect(p.display("CLAUDE.md") in rr.stderr, "stderr names the file to be created", rr.stderr)
        expect(not p.exists("CLAUDE.md") and not p.exists("AGENTS.md"), "nothing created")


@case("AC-12-directory-write-no-search-create-exit-2")
def _():
    # 0222：W_OK 真、X_OK 假——POSIX 建檔需 search 權限；只查 W_OK 會 dry-run 0／實跑 2
    require_non_root()
    with project({"devflow.yml": YML_CLAUDE}) as p:
        os.chmod(p.root, 0o222)
        rd = p.run("--dry-run")
        rr = p.run()
        err_run(rd, 2)
        err_run(rr, 2)
        eq(rd.stderr, rr.stderr, "stderr same in both modes")
        os.chmod(p.root, 0o700)
        expect(not p.exists("CLAUDE.md") and not p.exists("AGENTS.md"), "nothing created")


@case("AC-12-readonly-replace-path-exit-2")
def _():
    require_non_root()
    with project({"AGENTS.md": PREFIX + OLD_BLOCK + SUFFIX}) as p:
        p.chmod("AGENTS.md", 0o444)
        rd = p.run("--dry-run")
        rr = p.run()
        err_run(rd, 2)
        err_run(rr, 2)
        eq(rd.stderr, rr.stderr, "stderr same in both modes")
        eq(p.read("AGENTS.md"), PREFIX + OLD_BLOCK + SUFFIX, "bytes")


# AC-13：本 repo 自身 --dry-run → 兩檔 unchanged、exit 0

@case("AC-13-self-repo-dry-run-unchanged")
def _():
    r = subprocess.run([sys.executable, str(INSTALL), str(REPO), "--dry-run"], capture_output=True)
    ok_run(r)
    eq(r.stdout, str(REPO / "CLAUDE.md").encode() + b": unchanged\n"
       + str(REPO / "AGENTS.md").encode() + b": unchanged\n", "stdout")


# ── 執行 ─────────────────────────────────────────────────────────────


def check_template():
    problems = []
    if T.startswith(b"\xef\xbb\xbf"):
        problems.append("has BOM")
    if b"\r" in T:
        problems.append("has CR")
    if not T.endswith(b"\n") or T.endswith(b"\n\n"):
        problems.append("must end with exactly one \\n")
    lines = split_lf(T)
    if not lines or lines[0].strip() != BEGIN or lines[-1].strip() != END:
        problems.append("must start with begin marker line and end with end marker line")
    if len(lines) > 30:
        problems.append("more than 30 lines")
    if problems:
        print("template %s is not in normal form: %s" % (TEMPLATE_PATH, "; ".join(problems)),
              file=sys.stderr)
        sys.exit(2)


def main(argv):
    check_template()
    selected = [(n, f) for n, f in CASES if not argv or any(a in n for a in argv)]
    passed = failed = skipped = 0
    for name, fn in selected:
        try:
            fn()
        except Skip as e:
            skipped += 1
            print("SKIP", name, flush=True)
            print("    " + str(e), file=sys.stderr, flush=True)
        except Failure as e:
            failed += 1
            print("FAIL", name, flush=True)
            print("    " + str(e).replace("\n", "\n    "), file=sys.stderr, flush=True)
        except Exception:
            failed += 1
            print("FAIL", name, flush=True)
            print("    " + traceback.format_exc().replace("\n", "\n    "), file=sys.stderr, flush=True)
        else:
            passed += 1
            print("PASS", name, flush=True)
    print("total %d, passed %d, failed %d, skipped %d"
          % (passed + failed + skipped, passed, failed, skipped), flush=True)
    return 0 if failed == 0 and selected else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
