#!/usr/bin/env python3
"""tests/install/harness.py — devflow/install.py 的驗收測試（spec AC-1～AC-12；AC-13 由 CI 執行，不在此）。

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
import importlib.util
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

# 直接載入 install.py 以驗 read_implementer 的回傳值（AC-7 的 L；CI 的 i5 也是這樣取）。
# 子程序執行仍是判定 exit／stdout／stderr／建檔的來源，這裡只多驗讀取器本身。
sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("devflow_install", INSTALL)
install = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(install)

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


# devflow.yml 片段（#68 起的結構）。AC-7 只讀頂層投影鍵 implementer_filler；seats: 區塊是它的來源，
# 安裝器不讀（兩處一致由 CI 的 i5 比對，spec AC-13，不在本 harness 範圍）。
def projection(filler):
    return b"implementer_filler: " + filler + b"\n"


YML_CLAUDE = projection(b"claude-code")
YML_CODEX = projection(b"codex")
NESTED_CLAUDE = b"seats:\n  implementer:\n    filler: claude-code\n"   # 只有巢狀寫法、無投影
# AC-7 advisory：有 seats: 頂層行卻讀不到合規投影時，stderr 恰一行、exit 不變
ADVISORY = (b"devflow.yml: seats: present but implementer_filler unreadable (missing, malformed, "
            b"duplicated, or file is not a plain top-level mapping); defaulting to AGENTS.md\n")
# 本 repo 實際設定（含 seats:、docs:、投影鍵）：AC-12 要求它與其 CRLF 版都得 CLAUDE.md
REPO_YML = (REPO / "devflow.yml").read_bytes()


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


def agents_only(yml, why, stderr=b"", value=None):
    """兩入口檔皆無、devflow.yml 為 yml → read_implementer 恰回 value（預設 None＝不合規；合規但非
    claude-code 者傳該字串）；dry-run 與實跑皆 exit 0、stderr 恰為 stderr（預設空，advisory 案傳
    ADVISORY）；實跑只建 AGENTS.md。"""
    with project({"devflow.yml": yml}) as p:
        eq(install.read_implementer(p.root), value, "read_implementer: " + why)
        rd = p.run("--dry-run")
        eq(rd.returncode, 0, "dry-run exit code: " + why)
        eq(rd.stderr, stderr, "dry-run stderr: " + why)
        r = p.run()
        eq(r.returncode, 0, "exit code: " + why)   # 永不報錯
        eq(r.stderr, stderr, "stderr: " + why)
        eq(p.read("AGENTS.md"), T, why)
        expect(not p.exists("CLAUDE.md"), "CLAUDE.md must not be created: " + why)


def claude_only(yml, why):
    """兩入口檔皆無、devflow.yml 為 yml → read_implementer 回 claude-code；dry-run 與實跑皆 exit 0、
    stderr 空；實跑只建 CLAUDE.md。"""
    with project({"devflow.yml": yml}) as p:
        eq(install.read_implementer(p.root), "claude-code", "read_implementer: " + why)
        rd = p.run("--dry-run")
        ok_run(rd)
        r = p.run()
        ok_run(r)
        eq(p.read("CLAUDE.md"), T, why)
        expect(not p.exists("AGENTS.md"), "AGENTS.md must not be created: " + why)


# ── AC-7 皆無：投影鍵合規 → CLAUDE.md ────────────────────────────────

@case("AC-7-none-projection-claude-code")
def _():
    claude_only(YML_CLAUDE, "minimal projection")
    claude_only(b"forge: github\n" + YML_CLAUDE + b"stage: 1\n", "projection among other top-level keys")
    claude_only(b"\n# c\n   \n\t\n" + YML_CLAUDE, "leading blank/comment/whitespace-only lines are ignored")


@case("AC-7-none-projection-trailing-comment")
def _():
    claude_only(b"implementer_filler: claude-code   # claude-code | codex\n", "trailing # comment")
    claude_only(b"implementer_filler:\tclaude-code\t# c\n", "tab as separator")
    claude_only(b"implementer_filler: claude-code   \n", "trailing spaces")


@case("AC-7-none-projection-crlf")
def _():
    claude_only(b"forge: github\r\nimplementer_filler: claude-code\r\n", "all CRLF")


@case("AC-7-none-projection-crlf-valueless-top-key")
def _():
    # 抓把 \r 當行內容的實作：x:\r 就不是頂層鍵行、seats:\r／docs:\r 也不是
    claude_only(b"x:\r\n  y: 1\r\n" + YML_CLAUDE.replace(b"\n", b"\r\n"), "x:<CRLF> + candidate")
    claude_only(REPO_YML.replace(b"\n", b"\r\n"), "this repo's devflow.yml converted to CRLF")


@case("AC-7-none-projection-mixed-line-endings")
def _():
    claude_only(b"forge: github\r\nseats:\n  implementer:\r\n    filler: claude-code\n" + YML_CLAUDE,
                "LF and CRLF mixed")


@case("AC-7-none-projection-no-final-newline")
def _():
    claude_only(b"forge: github\nimplementer_filler: claude-code", "last line without newline")


@case("AC-7-none-projection-doc-start")
def _():
    claude_only(b"---\n" + YML_CLAUDE, "first line ---")
    claude_only(b"--- # c\n" + YML_CLAUDE, "first line --- # comment")
    claude_only(b"---  \n" + YML_CLAUDE, "--- with trailing spaces")
    claude_only(b"# c\n\n---\n" + YML_CLAUDE, "--- as first non-ignored line after comments")


@case("AC-7-none-projection-with-seats-block")
def _():
    claude_only(REPO_YML, "this repo's devflow.yml as is (seats: block + projection)")
    claude_only(NESTED_CLAUDE + YML_CLAUDE, "nested block followed by projection")
    claude_only(YML_CLAUDE + b"seats:\n  implementer:\n    filler: codex\n",
                "projection wins even when the nested value differs (consistency is AC-13's job)")


@case("AC-7-none-projection-codex")
def _():
    agents_only(YML_CODEX, "compliant value that is not claude-code", value="codex")
    agents_only(b"seats:\n  implementer:\n    filler: codex\n" + YML_CODEX,
                "compliant codex with seats: present: no advisory", value="codex")


@case("AC-7-none-no-devflow-yml")
def _():
    with project() as p:
        r = p.run()
        ok_run(r)
        eq(p.read("AGENTS.md"), T, "AGENTS.md created")
        expect(not p.exists("CLAUDE.md"), "CLAUDE.md must not be created")


@case("AC-7-none-envelope-ignores-values-and-indented-lines")
def _():
    # 信封成立但值層有非法 YAML：不看 `:` 之後、不看縮排行
    claude_only(b"x: [\n" + YML_CLAUDE, "unclosed flow sequence in a value")
    claude_only(b"y: \"\n" + YML_CLAUDE, "unclosed double quote in a value")
    claude_only(b"x:\n  ]]] }}} \"\"\" - ? % ---\n" + YML_CLAUDE, "arbitrary noise in indented lines")


# 切行一致性：這五個碼位在任何 YAML 版本都不是換行，以 \n 切行時 `forge: github<c>--- [` 是同一個
# 頂層鍵行、其後內容不看 → CLAUDE.md；誤用 str.splitlines() 的實作會把 `--- [` 切成頂層行 → AGENTS.md

@case("AC-7-none-split-consistency-U+000B")
def _():
    claude_only(b"forge: github\x0b--- [\n" + YML_CLAUDE + b" ]\n", "VT is not a line break")


@case("AC-7-none-split-consistency-U+000C")
def _():
    claude_only(b"forge: github\x0c--- [\n" + YML_CLAUDE + b" ]\n", "FF is not a line break")


@case("AC-7-none-split-consistency-U+001C")
def _():
    claude_only(b"forge: github\x1c--- [\n" + YML_CLAUDE + b" ]\n", "FS is not a line break")


@case("AC-7-none-split-consistency-U+001D")
def _():
    claude_only(b"forge: github\x1d--- [\n" + YML_CLAUDE + b" ]\n", "GS is not a line break")


@case("AC-7-none-split-consistency-U+001E")
def _():
    claude_only(b"forge: github\x1e--- [\n" + YML_CLAUDE + b" ]\n", "RS is not a line break")


# ── AC-7 皆無：候選行不合規 → AGENTS.md ──────────────────────────────

@case("AC-7-none-candidate-no-space-after-colon")
def _():
    agents_only(b"implementer_filler:claude-code\n", "no whitespace after the colon")


@case("AC-7-none-candidate-valueless")
def _():
    agents_only(b"implementer_filler:\n", "no value")
    agents_only(b"implementer_filler:  # c\n", "comment only")


@case("AC-7-none-candidate-extra-token")
def _():
    agents_only(b"implementer_filler: claude-code extra\n", "second token")
    agents_only(b"implementer_filler: claude-code#x\n", "# glued to the value is not a comment")


@case("AC-7-none-candidate-duplicate")
def _():
    agents_only(YML_CLAUDE + b"forge: github\n" + YML_CLAUDE, "two candidate lines, same value")
    agents_only(YML_CLAUDE + YML_CODEX, "two candidate lines, different values")


@case("AC-7-none-candidate-quoted-value")
def _():
    # 帶引號的值不是裸字面值 → 候選行不合規、L＝無（spec AC-7 不合規例、AC-13）；不是「讀到含引號的字串」
    agents_only(b"implementer_filler: \"claude-code\"\n", "double-quoted value is non-compliant")
    agents_only(b"implementer_filler: 'claude-code'\n", "single-quoted value is non-compliant")
    agents_only(NESTED_CLAUDE + b"implementer_filler: \"claude-code\"\n",
                "seats: + double-quoted value: advisory", ADVISORY)
    agents_only(NESTED_CLAUDE + b"implementer_filler: 'claude-code'  # c\n",
                "seats: + single-quoted value with comment: advisory", ADVISORY)


@case("AC-7-none-candidate-not-bare-literal")
def _():
    # 同類：值以 YAML 指示字元起始，永遠不是 plain scalar（§7.3.3）——alias／anchor／tag／區塊／流式／保留字元；
    # AC-13 把 alias 與顯式標籤列為「安裝器讀不到（L＝無）」
    for cand, what in ((b"*f", "alias"), (b"&a", "anchor"), (b"!!str", "tag"), (b"!!str claude-code", "tag + value"),
                       (b"|", "literal block indicator"), (b">", "folded block indicator"),
                       (b"[claude-code]", "flow sequence"), (b"{a: b}", "flow mapping"),
                       (b"%x", "reserved %"), (b"@x", "reserved @"), (b"`x", "reserved backtick")):
        agents_only(b"implementer_filler: " + cand + b"\n", what + " is not a bare literal")
        agents_only(NESTED_CLAUDE + b"implementer_filler: " + cand + b"\n", what + " with seats: present: advisory", ADVISORY)
    # 對照：`-`／`?`／`:` 起始者 YAML 允許為 plain scalar，是合規裸值（只是不等於 claude-code）
    agents_only(b"implementer_filler: -x\n", "plain scalar may start with -", value="-x")


@case("AC-7-none-candidate-conditional-indicator")
def _():
    # §7.3.3：`-`／`?`／`:` 只有後接 ns-plain-safe（非空白字元）時才可起首。單獨一個不是 plain scalar
    # （PyYAML ScannerError）→ None、有 seats: 時 advisory；`-x`／`?x`／`:x` 是 plain scalar → 讀到原字串、無 advisory
    for cand in (b"-", b"?", b":"):
        agents_only(b"implementer_filler: " + cand + b"\n", "lone %r is not a plain scalar" % cand)
        agents_only(NESTED_CLAUDE + b"implementer_filler: " + cand + b"\n",
                    "lone %r with seats: present: advisory" % cand, ADVISORY)
    for cand in (b"-x", b"?x", b":x"):
        agents_only(b"implementer_filler: " + cand + b"\n", "%r is a plain scalar" % cand, value=cand.decode())
        agents_only(NESTED_CLAUDE + b"implementer_filler: " + cand + b"\n",
                    "%r with seats: present: compliant, no advisory" % cand, value=cand.decode())
    # 指示字元後接空白：`: x` 是 mapping 分隔、`- x` 是序列項、`? x` 是複合鍵——值 token 不含空白，
    # `[-?:]` 之後沒有值字元 → 整行不匹配 → None
    for cand in (b": x", b"- x", b"? x"):
        agents_only(NESTED_CLAUDE + b"implementer_filler: " + cand + b"\n",
                    "%r: indicator followed by space is not a scalar" % cand, ADVISORY)


@case("AC-7-none-candidate-flow-closer-or-comma")
def _():
    # 無條件指示字元中的 `]`／`}`／`,`（flow 續行／分隔）明確反例
    for cand in (b"]", b"}", b","):
        agents_only(b"implementer_filler: " + cand + b"\n", "leading %r is not a bare literal" % cand)
        agents_only(NESTED_CLAUDE + b"implementer_filler: " + cand + b"\n",
                    "leading %r with seats: present: advisory" % cand, ADVISORY)


@case("AC-7-none-candidate-case-differs")
def _():
    # 合規的裸字面值，只是不等於 claude-code：讀得到、無 advisory
    agents_only(b"implementer_filler: Claude-Code\n", "byte comparison, no case folding", value="Claude-Code")
    agents_only(NESTED_CLAUDE + b"implementer_filler: Claude-Code\n",
                "compliant but different value with seats: present: no advisory", value="Claude-Code")


@case("AC-7-none-candidate-prefix-only-key")
def _():
    agents_only(b"implementer_filler_x: claude-code\n", "implementer_filler_x: is not a candidate")


@case("AC-7-none-candidate-indented")
def _():
    agents_only(b"forge: github\n  " + YML_CLAUDE, "space-indented line is not a top-level line")
    agents_only(b"forge: github\n\t" + YML_CLAUDE, "tab-indented line is not a top-level line")


@case("AC-7-none-empty-devflow-yml")
def _():
    agents_only(b"", "empty file")
    agents_only(b"\n  \n\t\n", "whitespace-only file")


# ── AC-7 皆無：行模型 → AGENTS.md ────────────────────────────────────

@case("AC-7-none-bare-cr-second-document")
def _():
    # PR #74 第六輪反例：\n 眼中一行，YAML 眼中是 entry ＋ 新 document 的 flow 開頭
    agents_only(b"forge: github\r--- [\n" + YML_CLAUDE + b" ]\n", "bare CR hides a second document")


@case("AC-7-none-bare-cr-in-comment")
def _():
    agents_only(b"# c\r--- [\n" + YML_CLAUDE + b" ]\n", "bare CR inside a comment line")


@case("AC-7-none-bare-cr-in-indented-line")
def _():
    agents_only(b"x:\n  model: x\r- [\n" + YML_CLAUDE + b" ]\n", "bare CR inside an indented line")


@case("AC-7-none-cr-cr-lf")
def _():
    agents_only(b"forge: github\r\r\n" + YML_CLAUDE, "first \\r of \\r\\r\\n is bare")


@case("AC-7-none-lone-cr-at-eof")
def _():
    agents_only(YML_CLAUDE + b"forge: github\r", "\\r at EOF is bare")


@case("AC-7-none-nel")
def _():
    agents_only("forge: github\x85--- [\n".encode("utf-8") + YML_CLAUDE + b" ]\n", "U+0085 NEL anywhere")


@case("AC-7-none-ls")
def _():
    agents_only("forge: github\u2028--- [\n".encode("utf-8") + YML_CLAUDE + b" ]\n", "U+2028 LS anywhere")


@case("AC-7-none-ps")
def _():
    agents_only("forge: github\u2029--- [\n".encode("utf-8") + YML_CLAUDE + b" ]\n", "U+2029 PS anywhere")


# ── AC-7 皆無：信封第 1 條（根定位）→ AGENTS.md ──────────────────────

@case("AC-7-none-root-flow-sequence")
def _():
    # YAML 1.2 Example 7.19：第 0 欄的 `[`、`key: value`、`]`；根是 sequence，不存在頂層 mapping 投影
    agents_only(b"[\n" + YML_CLAUDE + b"]\n", "root flow sequence")


@case("AC-7-none-indented-root-flow-shell")
def _():
    # PR #74 第五輪反例：外殼縮排一格、續行在第 0 欄。`seats: {},` 是 seats: 起始的頂層行 → advisory
    agents_only(b" [\nseats: {},\n" + YML_CLAUDE + b" ]\n", "indented root flow shell", ADVISORY)
    agents_only(b" [\nforge: github,\n" + YML_CLAUDE + b" ]\n", "indented root flow shell, no seats:")


@case("AC-7-none-indented-tag-flow")
def _():
    agents_only(b" !!seq [\n" + YML_CLAUDE + b" ]\n", "indented tag + flow sequence")


@case("AC-7-none-indented-quote-shell")
def _():
    agents_only(b" \"\n" + YML_CLAUDE + b" \"\n", "indented double-quote shell")


@case("AC-7-none-root-flow-mapping")
def _():
    agents_only(b"{\n" + YML_CLAUDE + b"}\n", "root flow mapping")


@case("AC-7-none-root-quoted-scalar")
def _():
    agents_only(b"\"\n" + YML_CLAUDE + b"\"\n", "root multi-line double-quoted scalar")
    agents_only(b"'\n" + YML_CLAUDE + b"'\n", "root multi-line single-quoted scalar")


@case("AC-7-none-root-block-scalar")
def _():
    agents_only(b"|\n" + YML_CLAUDE, "root literal block scalar")
    agents_only(b">\n" + YML_CLAUDE, "root folded block scalar")


@case("AC-7-none-doc-start-with-content")
def _():
    agents_only(b"--- [\n" + YML_CLAUDE + b"]\n", "--- followed by a flow sequence")
    agents_only(b"--- |\n" + YML_CLAUDE, "--- followed by a block scalar indicator")


@case("AC-7-none-doc-start-then-indented-shell")
def _():
    agents_only(b"---\n [\n" + YML_CLAUDE + b" ]\n", "--- exception does not admit an indented shell")


@case("AC-7-none-doc-start-twice")
def _():
    agents_only(b"---\n---\n" + YML_CLAUDE, "second --- is not a top-level key line")


@case("AC-7-none-first-line-property")
def _():
    agents_only(b"&a\n" + YML_CLAUDE, "anchor property on the first line")
    agents_only(b"!!map\n" + YML_CLAUDE, "tag property on the first line")


@case("AC-7-none-indented-root-mapping")
def _():
    agents_only(b"  forge: github\n" + YML_CLAUDE, "first non-ignored line is indented")


@case("AC-7-none-bom-then-key")
def _():
    # 抓誤用 utf-8-sig 的實作：BOM 不剝，首行不是頂層鍵行
    agents_only(b"\xef\xbb\xbf" + YML_CLAUDE, "BOM directly before the key")


@case("AC-7-none-bom-then-comment")
def _():
    agents_only(b"\xef\xbb\xbf# c\n" + YML_CLAUDE, "BOM + comment is neither ignored nor a key line")


@case("AC-7-none-yaml-directive")
def _():
    agents_only(b"%YAML 1.2\n---\n" + YML_CLAUDE, "%YAML directive line")


# ── AC-7 皆無：信封第 2 條（全檔）→ AGENTS.md ────────────────────────

@case("AC-7-none-second-doc-start")
def _():
    agents_only(b"forge: github\n---\n" + YML_CLAUDE, "candidate in the second document")


@case("AC-7-none-doc-end-marker")
def _():
    agents_only(YML_CLAUDE + b"...\n", "... document end marker")


@case("AC-7-none-quoted-key-elsewhere")
def _():
    agents_only(b"\"forge\": github\n" + YML_CLAUDE, "quoted key on another top-level line")


@case("AC-7-none-complex-key")
def _():
    agents_only(b"? key\n: v\n" + YML_CLAUDE, "? complex key")


@case("AC-7-none-col0-sequence-item")
def _():
    agents_only(b"- item\n" + YML_CLAUDE, "column-0 sequence item")


@case("AC-7-none-compact-sequence-value")
def _():
    agents_only(b"a:\n- x\n" + YML_CLAUDE, "compact sequence value at column 0 (conservatively rejected)")


@case("AC-7-none-flow-with-col0-closer")
def _():
    agents_only(b"x: [\n" + YML_CLAUDE + b"]\n", "column-0 ] closer")
    agents_only(b"x: {\n" + YML_CLAUDE + b"}\n", "column-0 } closer")


@case("AC-7-none-other-non-key-top-lines")
def _():
    agents_only(b"\tforge: github\n" + YML_CLAUDE, "tab-first top-level line")
    agents_only("包裝: x\n".encode("utf-8") + YML_CLAUDE, "non-ASCII key")
    agents_only(b"forge : github\n" + YML_CLAUDE, "space before the colon")
    agents_only(b"<<: *x\n" + YML_CLAUDE, "merge key")


# ── AC-7 皆無：其他 ──────────────────────────────────────────────────

@case("AC-7-none-devflow-yml-not-utf8")
def _():
    agents_only(b"\xff\xfe" + YML_CLAUDE, "undecodable devflow.yml")
    agents_only(b"\xff\xfeseats:\n", "undecodable: no advisory either (lines cannot be inspected)")


@case("AC-7-none-devflow-yml-is-directory")
def _():
    with project() as p:
        p.path("devflow.yml").mkdir()
        r = p.run()
        ok_run(r)  # 永不報錯
        eq(p.read("AGENTS.md"), T, "unreadable devflow.yml → AGENTS.md")


@case("AC-7-none-nested-only-no-projection")
def _():
    # 安裝器不讀 seats: 巢狀路徑；含 PR #74 第三輪的三個 flow 包裹反例。seats: 存在 → advisory
    agents_only(NESTED_CLAUDE, "nested block form only", ADVISORY)
    agents_only(b"seats:\n  implementer:\n    reviewer: [\n    filler: claude-code\n]\n",
                "round-3 attack: flow sequence wrapper", ADVISORY)
    agents_only(b"seats:\n  implementer:\n    reviewer: {\n    filler: claude-code\n}\n",
                "round-3 attack: flow mapping wrapper", ADVISORY)
    agents_only(b"seats:\n  implementer:\n    reviewer:\n      x: [\n    filler: claude-code\n]\n",
                "round-3 attack: opener hidden in another key", ADVISORY)


@case("AC-7-none-legacy-coder-key-ignored")
def _():
    # #68 廢除的舊鍵 coder:（不留別名）：即使值為 claude-code 也不得再被讀
    agents_only(b"coder: claude-code\n", "legacy coder: key is not read")


# ── AC-7 advisory ────────────────────────────────────────────────────

@case("AC-7-none-advisory-seats-without-candidate")
def _():
    agents_only(NESTED_CLAUDE + b"forge: github\n", "seats: present, candidate missing", ADVISORY)
    agents_only(b"seats:\r\n  implementer:\r\n    filler: claude-code\r\n", "CRLF seats: line", ADVISORY)
    agents_only(NESTED_CLAUDE + YML_CLAUDE + YML_CLAUDE, "seats: present, candidate duplicated", ADVISORY)
    agents_only(NESTED_CLAUDE + b"implementer_filler:claude-code\n", "seats: present, candidate malformed", ADVISORY)


@case("AC-7-none-advisory-each-malformed-candidate")
def _():
    # 候選行的每一類不合規（spec AC-7「不合規例」）配上 seats: → read_implementer None ＋ 恰一行 advisory
    for cand, what in ((b"implementer_filler:claude-code\n", "no whitespace after colon"),
                       (b"implementer_filler:\n", "no value"),
                       (b"implementer_filler:  # c\n", "comment only"),
                       (b"implementer_filler: claude-code extra\n", "extra token"),
                       (b"implementer_filler: claude-code#x\n", "# glued to value"),
                       (YML_CLAUDE + YML_CLAUDE, "duplicate, same value"),
                       (YML_CLAUDE + YML_CODEX, "duplicate, different values"),
                       (b"implementer_filler: \"claude-code\"\n", "double-quoted"),
                       (b"implementer_filler: 'claude-code'\n", "single-quoted"),
                       (b"implementer_filler_x: claude-code\n", "prefix-only key"),
                       (b"  " + YML_CLAUDE, "space-indented"),
                       (b"\t" + YML_CLAUDE, "tab-indented"),
                       (b"", "missing")):
        agents_only(NESTED_CLAUDE + cand, what + " with seats: present", ADVISORY)


@case("AC-7-none-advisory-seats-envelope-broken")
def _():
    agents_only(NESTED_CLAUDE + b"]\n" + YML_CLAUDE, "seats: present, envelope broken by ]", ADVISORY)
    agents_only(b"[\nseats: {},\n" + YML_CLAUDE + b"]\n", "seats: line inside a root flow shell", ADVISORY)
    agents_only(b"seats:\r\r\n" + YML_CLAUDE, "seats: present, bare CR breaks the line model", ADVISORY)


@case("AC-7-none-no-advisory-without-seats")
def _():
    agents_only(b"forge: github\n", "unreadable but no seats: line")
    agents_only(b"  seats:\n" + YML_CODEX, "indented seats: is not a top-level line")
    agents_only(b"# seats:\n[\n" + YML_CLAUDE + b"]\n", "seats: only inside a comment")


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


# 本 repo 自身 --dry-run → 兩檔 unchanged、exit 0（不是 spec 的 AC-13；那是 CI 的 i5）

@case("self-repo-dry-run-unchanged")
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
