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
- 輸出每案一行 `PASS|FAIL <AC-n>-<分支名>`，失敗細節印到 stderr，最後一行總計；
  全數 PASS 才 exit 0。
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

    def run(self, *flags, install=INSTALL, target=None):
        cmd = [sys.executable, str(install), target or str(self.root), *flags]
        return subprocess.run(cmd, capture_output=True)

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


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
        shutil.rmtree(d, ignore_errors=True)


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


# AC-2：無 begin 標記行 → 檔首插入：模板 + \n + 原檔

@case("AC-2-no-begin-inserts-at-byte-0")
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


@case("AC-2-stray-end-is-project-content")
def _():
    orig = PREFIX + END_LINE + SUFFIX
    with project({"CLAUDE.md": orig}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("CLAUDE.md"), T + b"\n" + orig, "stray end ignored; inserted at head")


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


@case("AC-3-stray-end-before-begin-ignored")
def _():
    data = b"intro\n" + END_LINE + T + SUFFIX
    with project({"AGENTS.md": data}) as p:
        r = p.run()
        ok_run(r)
        eq(r.stdout, p.display("AGENTS.md") + b": unchanged\n", "stdout")
        eq(p.read("AGENTS.md"), data, "bytes")


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


@case("AC-5-end-before-begin-does-not-pair")
def _():
    data = END_LINE + b"x\n" + BEGIN_LINE + b"y\n"  # begin 在第 3 行
    with project({"AGENTS.md": data}) as p:
        r = p.run()
        err_run(r, 1)
        eq(r.stderr, p.display("AGENTS.md") + b":3: devflow:begin without end\n", "stderr")
        eq(p.read("AGENTS.md"), data, "bytes")


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
    with project({"AGENTS.md": PREFIX, "devflow.yml": b"coder: claude-code\n"}) as p:
        r = p.run()
        ok_run(r)
        expect(not p.exists("CLAUDE.md"), "devflow.yml only consulted when both are absent")


@case("AC-7-none-coder-claude-code")
def _():
    yml = b"forge: github\ncoder: claude-code     # claude-code | codex\nstage: 1\n"
    with project({"devflow.yml": yml}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("CLAUDE.md"), T, "CLAUDE.md created")
        expect(not p.exists("AGENTS.md"), "AGENTS.md must not be created")


@case("AC-7-none-coder-codex")
def _():
    with project({"devflow.yml": b"coder: codex\n"}) as p:
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


@case("AC-7-none-non-yaml-with-coder-line")
def _():
    yml = b"{{{ this is: not: [yaml\ncoder: claude-code\n]]] ::: junk\n"
    with project({"devflow.yml": yml}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("CLAUDE.md"), T, "regex line match, no YAML parse")
        expect(not p.exists("AGENTS.md"), "AGENTS.md must not be created")


@case("AC-7-none-devflow-yml-not-utf8")
def _():
    with project({"devflow.yml": b"\xff\xfecoder: claude-code\n"}) as p:
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


@case("AC-7-none-indented-coder-no-match")
def _():
    with project({"devflow.yml": b"tool:\n  coder: claude-code\n"}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("AGENTS.md"), T, "^coder: is anchored at line start")
        expect(not p.exists("CLAUDE.md"), "CLAUDE.md must not be created")


@case("AC-7-none-first-coder-line-wins")
def _():
    with project({"devflow.yml": b"coder: codex\ncoder: claude-code\n"}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("AGENTS.md"), T, "first match is codex")
        expect(not p.exists("CLAUDE.md"), "CLAUDE.md must not be created")


@case("AC-7-none-devflow-yml-not-created")
def _():
    with project() as p:
        r = p.run()
        ok_run(r)
        expect(not p.exists("devflow.yml"), "devflow.yml must not be created")


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
    passed = failed = 0
    for name, fn in selected:
        try:
            fn()
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
    print("total %d, passed %d, failed %d" % (passed + failed, passed, failed), flush=True)
    return 0 if failed == 0 and selected else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
