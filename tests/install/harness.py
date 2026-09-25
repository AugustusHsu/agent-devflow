#!/usr/bin/env python3
"""tests/install/harness.py — devflow/install.py 的驗收測試。

涵蓋兩份規格：
- docs/spec/install/spec.md（入口區塊，AC-1～AC-12；AC-13 由 CI 執行，不在此）——案例名
  以 `AC-n-` 開頭。
- docs/spec/kit-install/spec.md（完整安裝，AC-1～AC-20 含 AC-14b）——案例名以 `kit-AC-n-`
  開頭，每條 AC 每個分支至少一案（kit-install AC-20）。

執行：
    python3 tests/install/harness.py            # 全部案例
    python3 tests/install/harness.py kit        # 只跑 kit-install 案例
    python3 tests/install/harness.py AC-7       # 只跑名稱含 AC-7 的案例

作法：
- 每案在 /tmp（tempfile 預設目錄）建獨立假專案，跑完清理，可獨立重跑。
- 假專案內容以 bytes 字面量寫在案例裡，不用 fixture 檔——spec 的 AC 全以 bytes 定義
  （CRLF、無尾端換行、BOM、非 UTF-8），fixture 檔會被編輯器與 git 正規化掉。
- 斷言一律 bytes 比對；「不寫檔」另以 mtime 驗證（同 bytes 重寫也算寫）。
- 需要別的模板時（AC-8 >30 行、模板正規化），用 sandboxed_install() 把 install.py 複製到
  暫存目錄並放自己的 templates/entry-block.md——install.py 以 __file__ 定位模板，不是 cwd。
- 需要變造**來源 kit**時（kit-install AC-6／AC-12／AC-13／AC-16）用 kit_copy()：整個
  devflow/ 複製到 /tmp 再變造，repo 的 kit 一個 byte 都不動。
- 可寫性案例（chmod 0444 檔、0555 目錄）以非 root 為前提：root 對它們 os.access(W_OK)
  恆真，構造不出反例；偵測到 os.geteuid() == 0 時該類案例標 SKIP（不算 FAIL）。
- 輸出每案一行 `PASS|FAIL|SKIP <AC-n>-<分支名>`，失敗細節印到 stderr，最後一行總計
  （含 skip 數）；無 FAIL 即 exit 0。

入口規格案例與 kit-install 的介面（AC-20）：安裝器現在的 stdout 前面多了 kit-install 的
摘要行與動作行、stderr 在沒有 devflow.yml 的假專案裡多了 AC-9 的 advisory。入口規格既有
案例的期望值**逐字不變**，只是套在剝掉這兩個前／後綴之後的部分——見 entry_out() 與
entry_stderr()。exit code 的期望一個字都沒動。
"""
import difflib
import importlib.util
import os
import re
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
LOCAL_TEMPLATE = REPO / "devflow" / "templates" / "local-README.md"
KIT_VERSION = (REPO / "devflow" / "VERSION").read_bytes()
V = KIT_VERSION.strip()          # 摘要行裡的版本字串（kit-install AC-11）

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
    """把 install.py 複製到暫存目錄，配上自訂模板（None＝不放 entry-block.md）。

    這個暫存目錄是安裝器眼中的「來源 devflow/」，所以得是合規的 kit：VERSION 要合
    kit-install 的「版本」定義（AC-12，否則一律 exit 2），local-README.md 要在（AC-7 的
    bytes 來源）。兩者都照抄 repo 的 kit，本函式只換 entry-block.md。
    """
    d = Path(tempfile.mkdtemp(prefix="devflow-install-sandbox-"))
    try:
        shutil.copy(INSTALL, d / "install.py")
        shutil.copy(REPO / "devflow" / "VERSION", d / "VERSION")
        (d / "templates").mkdir()
        shutil.copy(LOCAL_TEMPLATE, d / "templates" / "local-README.md")
        if template is not None:
            (d / "templates" / "entry-block.md").write_bytes(template)
        yield d / "install.py"
    finally:
        remove_tree(d)


@contextmanager
def kit_copy(version=None, mutate=None):
    """整個 kit 的 devflow/ 複製到 /tmp，改 VERSION、套 mutate，回傳副本的 install.py 路徑。

    kit-install AC-20：需變造**來源**的案例一律在副本上變造（AC-6 的 A／B 即兩份副本），
    repo 的 kit 一個 byte 都不動。version 是 VERSION 的完整 bytes（None＝照抄）；
    mutate 收到副本的 devflow/ 路徑（Path），可任意增刪改。
    排除路徑（__pycache__／*.pyc）不複製：它們在兩邊都不算數，帶進副本只會讓斷言難讀。
    """
    d = Path(tempfile.mkdtemp(prefix="devflow-kit-"))
    try:
        src = d / "devflow"
        shutil.copytree(str(REPO / "devflow"), str(src), symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        if version is not None:
            (src / "VERSION").write_bytes(version)
        if mutate is not None:
            mutate(src)
        yield src / "install.py"
    finally:
        remove_tree(d)


def ok_run(r):
    """exit 0、stderr 除 kit-install AC-9 的 advisory 外為空。"""
    eq(r.returncode, 0, "exit code（stderr=%s）" % short(r.stderr))
    eq(entry_stderr(r), b"", "stderr")


def err_run(r, code):
    """exit 非 0：stdout 全部抑制（入口規格 AC-10、kit-install「驗收標準」開頭）。"""
    eq(r.returncode, code, "exit code（stderr=%s）" % short(r.stderr))
    eq(r.stdout, b"", "stdout must be suppressed on exit %d" % code)
    expect(r.stderr != b"", "stderr must explain")


# ── kit-install 的前綴／後綴（AC-11、AC-9、AC-20）─────────────────────

KIT_SUMMARY_RE = re.compile(
    rb"kit-install: (?:none|invalid|[0-9]+(?:\.[0-9]+){3}) -> [0-9]+(?:\.[0-9]+){3}"
    rb" \((?:fresh|upgrade|downgrade|same|replace)\)\n")
KIT_ACTION_RE = re.compile(rb"devflow(?:\.local)?/[^\n]*: (?:created|updated|deleted)\n")
# AC-9 的 advisory。入口檔的路徑一律是絕對路徑，不會與動作行的 devflow… 前綴相混
KIT_YML_ADVISORY = b"devflow.yml: absent; copy devflow/templates/devflow.yml and edit (advisory)\n"


def split_stdout(stdout):
    """(摘要行, 動作行 list, 入口檔那一段)；前兩項已去掉行尾 \\n。

    AC-11：第一行恰為摘要行，其後為動作行，再接入口檔輸出。入口規格的既有斷言套在第三項上。
    """
    lines = split_lf(stdout)
    expect(bool(lines) and KIT_SUMMARY_RE.fullmatch(lines[0]),
           "stdout 第一行須為 kit-install 摘要行（AC-11）", short(stdout))
    i = 1
    while i < len(lines) and KIT_ACTION_RE.fullmatch(lines[i]):
        i += 1
    return lines[0][:-1], [line[:-1] for line in lines[1:i]], b"".join(lines[i:])


def entry_out(r):
    """stdout 去掉 kit-install 前綴後，入口檔那一段（AC-20）。"""
    return split_stdout(r.stdout)[2]


def summary_of(r):
    return split_stdout(r.stdout)[0]


def actions_of(r):
    return split_stdout(r.stdout)[1]


def entry_stderr(r):
    """stderr 去掉 AC-9 的 advisory（依 AC-9 的優先序固定在最後）後的部分。

    假專案多數沒有 devflow.yml，AC-9 要求 exit 0 時必印這一行。入口規格既有案例的 stderr
    期望逐字不變，只是套在這上面——與 stdout 的前綴同理（AC-20）。exit 非 0 時 stderr 只有
    錯誤那一行，本函式等同恆等式。
    """
    if r.stderr.endswith(KIT_YML_ADVISORY):
        return r.stderr[:-len(KIT_YML_ADVISORY)]
    return r.stderr


def snapshot(root):
    """整棵樹的 bytes 與存在性（AC-18／AC-5：比 bytes 與 lexists，不比 stat）。

    symlink 記其指向、不跟隨；os.walk(followlinks=False) 不進入 symlink 指向的目錄。
    """
    out = {}
    for dirpath, dirnames, filenames in os.walk(str(root), followlinks=False):
        for name in dirnames + filenames:
            full = Path(dirpath) / name
            rel = str(full.relative_to(root))
            if full.is_symlink():
                out[rel] = ("link", os.readlink(str(full)))
            elif full.is_dir():
                out[rel] = ("dir", None)
            elif full.is_file():
                out[rel] = ("file", full.read_bytes())
            else:
                out[rel] = ("other", None)
    return out


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
        eq(entry_out(r), p.display("CLAUDE.md") + b": unchanged\n", "stdout")
        eq(p.read("CLAUDE.md"), data, "bytes")
        expect(not p.rewritten("CLAUDE.md"), "file must not be rewritten")


@case("AC-3-equal-after-crlf-normalization")
def _():
    data = PREFIX + T.replace(b"\n", b"\r\n") + SUFFIX
    with project({"CLAUDE.md": data}) as p:
        r = p.run()
        ok_run(r)
        eq(entry_out(r), p.display("CLAUDE.md") + b": unchanged\n", "stdout")
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
        eq(entry_out(r), p.display("CLAUDE.md") + b": unchanged\n", "stdout")
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


# AC-5c：命中 AC-5b、且「檔首 UTF-8 BOM ＋ 去掉 BOM 後的首行是 begin」→ exit 1、不寫檔
# （與 AC-5b 同），但 stderr 改指 BOM、行號固定 1。落單 end 是後果，BOM 才是原因（#104）。
# 條件的兩個「且」各有界線案：沒有 BOM、或首行不是 begin，都走回 AC-5b 的原訊息。

BOM = b"\xef\xbb\xbf"
BOM_LINE = b":1: UTF-8 BOM before devflow:begin; remove the BOM (see issue #104)\n"


def bom_run(r, p, name, data):
    """AC-5c 的共同斷言：exit 1、訊息指 BOM 且行號為 1、bytes 不變、未重寫。"""
    err_run(r, 1)
    eq(r.stderr, p.display(name) + BOM_LINE, "stderr")
    eq(p.read(name), data, "bytes")
    expect(not p.rewritten(name), "file must not be rewritten")


@case("AC-5c-bom-begin-then-end-reports-bom")
def _():
    # 主案：BOM ＋首行 begin ＋其後有 end。安裝器不剝 BOM，首行不是標記行，模板自己的
    # end 成了落單 end——訊息指第 1 行的 BOM，不是那個 end 的行號
    data = BOM + T
    with project({"CLAUDE.md": data}) as dry, project({"CLAUDE.md": data}) as real:
        rd = dry.run("--dry-run")
        rr = real.run()
        bom_run(rd, dry, "CLAUDE.md", data)
        bom_run(rr, real, "CLAUDE.md", data)
        expect(not dry.exists("AGENTS.md"), "AGENTS.md must not be created")


@case("AC-5c-bom-begin-with-surrounding-spaces")
def _():
    # 「去掉 BOM 後的首行」照 is_marker 的 strip 語意判：前後空白不影響
    data = BOM + b"  " + BEGIN + b"  \n" + b"body\n" + END_LINE + SUFFIX
    with project({"AGENTS.md": data}) as p:
        bom_run(p.run(), p, "AGENTS.md", data)


@case("AC-5c-no-bom-stray-end-keeps-old-message")
def _():
    # 迴歸保護（條件的「有 BOM」那半）：沒有 BOM 的真正落單 end 仍是 AC-5b 的訊息與行號
    data = b"intro\n" + END_LINE + T
    with project({"CLAUDE.md": data}) as p:
        stray_run(p.run(), p, "CLAUDE.md", 2, data)


@case("AC-5c-bom-first-line-not-begin-keeps-old-message")
def _():
    # 迴歸保護（條件的「首行是 begin」那半）：BOM 在、首行卻是普通文字 → 不走新分支。
    # 這個檔的落單 end 是真的落單，報它的行號
    data = BOM + b"intro\n" + END_LINE + T
    with project({"CLAUDE.md": data}) as p:
        stray_run(p.run(), p, "CLAUDE.md", 2, data)


@case("AC-5c-bom-plain-text-still-inserts")
def _():
    # 迴歸保護：BOM ＋首行是普通文字、全檔無標記行 → 照原邏輯走 AC-2 檔首插入、exit 0
    orig = BOM + PREFIX + SUFFIX
    with project({"AGENTS.md": orig}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("AGENTS.md"), T + b"\n" + orig, "AC-2 insert: BOM is project content")


@case("AC-5c-no-bom-same-content-installs")
def _():
    # 對照組：同樣的 bytes 少了 BOM 就是一組完整區塊 → AC-3 unchanged、exit 0。
    # 兩案並排指出唯一的差別就是那 3 個 byte
    with project({"CLAUDE.md": T}) as p:
        r = p.run()
        ok_run(r)
        eq(entry_out(r), p.display("CLAUDE.md") + b": unchanged\n", "stdout")
        expect(not p.rewritten("CLAUDE.md"), "file must not be rewritten")


@case("AC-5c-bom-begin-without-end-still-inserts")
def _():
    # 界線一（issue #104 AC-2 要求判定的組合）：BOM ＋首行 begin ＋全檔無 end。
    # 首行不是標記行、也沒有 end → **無任何標記行** ＝ AC-2 檔首插入，exit 0、照常寫檔。
    # 不是 AC-5、也不是 AC-5b；新分支掛在 AC-5b 的路徑上，碰不到這裡
    orig = BOM + BEGIN_LINE + b"body\n"
    with project({"CLAUDE.md": orig}) as p:
        r = p.run()
        ok_run(r)
        eq(p.read("CLAUDE.md"), T + b"\n" + orig, "AC-2 insert: template + \\n + original")


@case("AC-5c-bom-begin-then-begin-then-end-installs")
def _():
    # PR #105 第二輪審查的反例二。檔頭與規格一度寫成「BOM ＋首行 begin ＋檔內有 end
    # 那一類照樣裝不起來」——錯的：第二行的可見 begin 先於 end，first_group 取
    # 第 2–4 行為第一組（第 2 行 begin、第 3 行 body、第 4 行 end），走 AC-3／4、exit 0、照常寫檔。
    # 散文把這格寫錯了三次，所以它現在是一個案例而不是一句話。
    orig = BOM + BEGIN_LINE + BEGIN_LINE + b"body\n" + END_LINE
    with project({"CLAUDE.md": orig}) as p:
        r = p.run()
        ok_run(r)
        after = p.read("CLAUDE.md")
        expect(after != orig, "AC-3/4: file was rewritten, not rejected",
               short(after), "anything != original")
        eq(after.count(BEGIN_LINE.strip()), 2,
           "first group replaced; the BOM-hidden begin line is untouched")


@case("AC-5c-bom-begin-then-second-begin-without-end-stays-ac5")
def _():
    # 界線二：BOM ＋首行 begin，其後另有一個真的 begin 而全檔無 end → AC-5，訊息與行號
    # 都不變。去掉 BOM 仍是 AC-5（只差行號），BOM 不是停下來的原因，改訊息反而誤導
    data = BOM + BEGIN_LINE + b"body\n" + BEGIN_LINE + b"tail\n"
    with project({"AGENTS.md": data}) as p:
        r = p.run()
        err_run(r, 1)
        eq(r.stderr, p.display("AGENTS.md") + b":3: devflow:begin without end\n", "stderr")
        eq(p.read("AGENTS.md"), data, "bytes")
        expect(not p.rewritten("AGENTS.md"), "file must not be rewritten")


# AC-6：第一組之後的任何標記行 → 忽略（不計數、不報錯、不改動）

@case("AC-6-later-markers-ignored-unchanged")
def _():
    data = PREFIX + T + b"\n" + BEGIN_LINE + b"example\n" + END_LINE + BEGIN_LINE
    with project({"CLAUDE.md": data}) as p:
        r = p.run()
        ok_run(r)
        eq(entry_out(r), p.display("CLAUDE.md") + b": unchanged\n", "later lone begin must not raise AC-5")
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


@case("AC-7-none-candidate-trailing-colon")
def _():
    # §7.3.3 ns-plain-char：`:` 只有後接 ns-plain-safe 時才是內容；行尾的 `:` 是 mapping 分隔——
    # `implementer_filler: codex:` 在 YAML 是「值為以 codex 為鍵的 mapping」（PyYAML ScannerError）→ None
    for cand in (b"codex:", b"claude-code:", b"x:", b"a::", b"::"):
        agents_only(b"implementer_filler: " + cand + b"\n", "trailing colon %r is not a plain scalar" % cand)
        agents_only(NESTED_CLAUDE + b"implementer_filler: " + cand + b"\n",
                    "trailing colon %r with seats: present: advisory" % cand, ADVISORY)
    agents_only(NESTED_CLAUDE + b"implementer_filler: codex:  # c\n",
                "trailing colon before a comment: advisory", ADVISORY)
    # 回歸保護：中間的 `:` 與起首的 `:`＋字元仍是 plain scalar → 讀到原字串、有 seats: 不印
    for cand in (b"a:b", b":x", b"::x", b"a::b", b":-"):
        agents_only(NESTED_CLAUDE + b"implementer_filler: " + cand + b"\n",
                    "%r keeps passing" % cand, value=cand.decode())


@case("AC-7-none-candidate-other-trailing-chars-allowed")
def _():
    # 尾字元除 `:` 外無限制（§7.3.3 只對 `:` 與 `#` 設鄰接條件，token 不含 `#`）：
    # 尾端 -／?／,／[／]／{／} 都是合法 plain scalar，讀到原字串、有 seats: 不印 advisory
    for cand in (b"abc-", b"abc?", b"abc,", b"abc[", b"abc]", b"abc{", b"abc}", b"a:-"):
        agents_only(NESTED_CLAUDE + b"implementer_filler: " + cand + b"\n",
                    "%r is a plain scalar" % cand, value=cand.decode())


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
        eq(entry_out(r), p.display("CLAUDE.md") + b": unchanged\n"
           + p.display("AGENTS.md") + b": unchanged\n", "stdout")
        eq({n: p.read(n) for n in snap}, snap, "bytes == snapshot")


@case("AC-9-second-run-unchanged-after-create")
def _():
    with project() as p:
        ok_run(p.run())
        snap = p.read("AGENTS.md")
        r = p.run()
        ok_run(r)
        eq(entry_out(r), p.display("AGENTS.md") + b": unchanged\n", "stdout")
        eq(p.read("AGENTS.md"), snap, "bytes == snapshot")
        expect(not p.exists("CLAUDE.md"), "CLAUDE.md must not be created")


# AC-10：--dry-run

@case("AC-10-dry-run-insert-diff-no-write")
def _():
    orig = PREFIX + SUFFIX
    with project({"CLAUDE.md": orig}) as p:
        r = p.run("--dry-run")
        ok_run(r)
        eq(entry_out(r), unified(orig, T + b"\n" + orig, b"CLAUDE.md"), "stdout == unified diff")
        eq(p.read("CLAUDE.md"), orig, "bytes")
        expect(not p.rewritten("CLAUDE.md"), "file must not be rewritten")


@case("AC-10-dry-run-create-diff-no-write")
def _():
    with project() as p:
        r = p.run("--dry-run")
        ok_run(r)
        eq(entry_out(r), unified(b"", T, b"AGENTS.md"), "stdout == diff from empty")
        expect(not p.exists("AGENTS.md") and not p.exists("CLAUDE.md"), "nothing created")


@case("AC-10-dry-run-unchanged")
def _():
    data = PREFIX + T + SUFFIX
    with project({"CLAUDE.md": data}) as p:
        r = p.run("--dry-run")
        ok_run(r)
        eq(entry_out(r), p.display("CLAUDE.md") + b": unchanged\n", "stdout")
        eq(p.read("CLAUDE.md"), data, "bytes")


@case("AC-10-dry-run-two-files-in-order")
def _():
    a = b"# agents\n"
    with project({"CLAUDE.md": PREFIX + T, "AGENTS.md": a}) as p:
        r = p.run("--dry-run")
        ok_run(r)
        eq(entry_out(r), p.display("CLAUDE.md") + b": unchanged\n"
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
        eq(entry_out(r), expected, "stdout == difflib output byte for byte")
        expect(b"No newline" not in r.stdout, "no synthetic marker line", r.stdout)


@case("AC-10-dry-run-end-at-eof-replace-exact-difflib")
def _():
    orig = PREFIX + OLD_BLOCK[:-1]   # end 行在 EOF、無換行
    with project({"CLAUDE.md": orig}) as p:
        r = p.run("--dry-run")
        ok_run(r)
        eq(entry_out(r), unified(orig, PREFIX + T, b"CLAUDE.md"), "stdout == difflib output byte for byte")
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
        eq(entry_out(r), p.display("CLAUDE.md") + b": unchanged\n", "stdout")


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
    eq(entry_out(r), str(REPO / "CLAUDE.md").encode() + b": unchanged\n"
       + str(REPO / "AGENTS.md").encode() + b": unchanged\n", "stdout")


# ════════════════════════════════════════════════════════════════════
# kit-install（docs/spec/kit-install/spec.md）：鏡像 devflow/ ＋ devflow.local/
# 案例名一律以 `kit-AC-n-` 開頭，`python3 tests/install/harness.py kit` 只跑這一段。
# ════════════════════════════════════════════════════════════════════


def kit_files(src=REPO / "devflow"):
    """鏡像集合：src 下、排除路徑以外的一般檔，POSIX 相對路徑、sorted。"""
    out = []
    for dirpath, dirnames, filenames in os.walk(str(src), followlinks=False):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if not name.endswith(".pyc"):
                out.append(str((Path(dirpath) / name).relative_to(src)))
    return sorted(out)


def created_lines(files, local=True):
    """全新安裝的期望動作行：全部 created，依**路徑字串** sorted()（AC-11）。"""
    actions = [(b"devflow/" + f.encode(), b"created") for f in files]
    if local:
        actions.append((b"devflow.local/README.md", b"created"))
    return [path + b": " + action for path, action in sorted(actions)]


def outside_snapshot(root):
    """devflow/、devflow.local/、入口檔集合以外的整棵樹（AC-18）。"""
    owned = ("devflow", "devflow.local", "CLAUDE.md", "AGENTS.md")
    return {k: v for k, v in snapshot(root).items() if k.split(os.sep)[0] not in owned}


def local_snapshot(root):
    return {k: v for k, v in snapshot(root).items() if k.split(os.sep)[0] == "devflow.local"}


# kit-AC-1：目標無 devflow/ → 建立；每檔 bytes 等於來源；devflow.local 依 AC-7；模式 fresh

@case("kit-AC-1-fresh-mirrors-whole-tree")
def _():
    src = REPO / "devflow"
    files = kit_files()
    with project() as p:
        r = p.run()
        ok_run(r)
        eq(summary_of(r), b"kit-install: none -> " + V + b" (fresh)", "摘要行模式 fresh")
        eq(actions_of(r), created_lines(files), "動作行：鏡像集合全部 created ＋ devflow.local")
        for rel in files:
            eq((p.root / "devflow" / rel).read_bytes(), (src / rel).read_bytes(),
               "devflow/%s bytes == 來源" % rel)
        eq(p.read("devflow.local/README.md"), LOCAL_TEMPLATE.read_bytes(), "devflow.local/README.md")
        eq(entry_out(r), p.display("AGENTS.md") + b": created\n", "入口檔依入口規格")
        eq(p.read("AGENTS.md"), T, "入口區塊 bytes")


# kit-AC-2：bytes 不同、或目標是 symlink → updated

@case("kit-AC-2-updated-different-bytes")
def _():
    with project() as p:
        ok_run(p.run())
        p.write("devflow/WORKFLOW.md", b"stale\n")
        r = p.run()
        ok_run(r)
        eq(actions_of(r), [b"devflow/WORKFLOW.md: updated"], "恰一行 updated")
        eq(p.read("devflow/WORKFLOW.md"), (REPO / "devflow" / "WORKFLOW.md").read_bytes(),
           "覆寫為來源 bytes")


@case("kit-AC-2-updated-symlink-replaced-by-file")
def _():
    with project({"outside.md": b"outside\n"}) as p:
        ok_run(p.run())
        os.remove(str(p.path("devflow/WORKFLOW.md")))
        p.symlink("devflow/WORKFLOW.md", "../outside.md")
        r = p.run()
        ok_run(r)
        eq(actions_of(r), [b"devflow/WORKFLOW.md: updated"], "symlink（任何指向）→ updated")
        expect(not p.path("devflow/WORKFLOW.md").is_symlink(), "symlink 由一般檔取代")
        eq(p.read("devflow/WORKFLOW.md"), (REPO / "devflow" / "WORKFLOW.md").read_bytes(), "bytes")
        eq(p.read("outside.md"), b"outside\n", "不寫進連結的指向")


# kit-AC-3：不在鏡像集合的一般檔或 symlink → deleted；刪後空目錄移除（devflow/ 本身保留）

@case("kit-AC-3-deleted-extra-file")
def _():
    with project() as p:
        ok_run(p.run())
        p.write("devflow/stray.md", b"mine\n")
        r = p.run()
        ok_run(r)
        eq(actions_of(r), [b"devflow/stray.md: deleted"], "恰一行 deleted")
        expect(not os.path.lexists(str(p.path("devflow/stray.md"))), "已刪除")


@case("kit-AC-3-deleted-symlink-and-empty-dirs-pruned")
def _():
    with project({"outside.md": b"outside\n"}) as p:
        ok_run(p.run())
        (p.root / "devflow" / "extra" / "deep").mkdir(parents=True)
        p.write("devflow/extra/deep/x.md", b"x\n")
        p.symlink("devflow/extra/link.md", "../../../outside.md")
        r = p.run()
        ok_run(r)
        eq(actions_of(r), [b"devflow/extra/deep/x.md: deleted", b"devflow/extra/link.md: deleted"],
           "一般檔與 symlink 都 deleted，依路徑字串排序")
        expect(not os.path.lexists(str(p.path("devflow/extra"))), "刪後空目錄一併移除（深者先）")
        expect(p.path("devflow").is_dir(), "devflow/ 本身保留")
        eq(p.read("outside.md"), b"outside\n", "symlink 只移除連結本身，不進入其指向")


# kit-AC-4：unchanged 不印任何行；排除路徑雙邊不複製、不刪除、不印

@case("kit-AC-4-unchanged-prints-nothing")
def _():
    with project() as p:
        ok_run(p.run())
        r = p.run()
        ok_run(r)
        eq(actions_of(r), [], "全部 unchanged → 一行動作行都沒有")


@case("kit-AC-4-excluded-paths-both-sides")
def _():
    def add_junk(src):
        (src / "__pycache__").mkdir()
        (src / "__pycache__" / "install.cpython-99.pyc").write_bytes(b"source cache\n")
        (src / "stale.pyc").write_bytes(b"source pyc\n")

    with kit_copy(mutate=add_junk) as inst, project() as p:
        ok_run(p.run(install=inst))
        expect(not os.path.lexists(str(p.path("devflow/__pycache__"))), "來源的 __pycache__ 不複製")
        expect(not os.path.lexists(str(p.path("devflow/stale.pyc"))), "來源的 .pyc 不複製")
        (p.root / "devflow" / "__pycache__").mkdir()
        p.write("devflow/__pycache__/x.cpython-99.pyc", b"target cache\n")
        p.write("devflow/other.pyc", b"target pyc\n")
        r = p.run(install=inst)
        ok_run(r)
        eq(actions_of(r), [], "目標的排除路徑不刪除、不印")
        eq(p.read("devflow/__pycache__/x.cpython-99.pyc"), b"target cache\n", "留著")
        eq(p.read("devflow/other.pyc"), b"target pyc\n", "留著")


# kit-AC-5：連續兩次 → 第二次恰為摘要行（same）＋入口規格 AC-3 的 unchanged 行；快照相同

@case("kit-AC-5-second-run-same-and-snapshot")
def _():
    with project({"CLAUDE.md": PREFIX}) as p:
        ok_run(p.run())
        snap = snapshot(p.root)
        r = p.run()
        ok_run(r)
        eq(summary_of(r), b"kit-install: " + V + b" -> " + V + b" (same)", "模式 same")
        eq(actions_of(r), [], "第二次沒有動作行")
        eq(entry_out(r), p.display("CLAUDE.md") + b": unchanged\n", "入口規格 AC-3 的 unchanged 行")
        eq(snapshot(p.root), snap, "整棵樹的 bytes 與存在性 == 第一次執行後的快照")


# kit-AC-6：A（0.0.0.1）→ B（0.0.0.2，恰一檔改、一檔增、一檔刪）→ A，逐 byte 回到原狀。
# 「一檔改」就是 VERSION 自己——A 與 B 的版本不同是這條 AC 的前提，那一檔必然 updated。

@case("kit-AC-6-upgrade-then-downgrade")
def _():
    def b_changes(src):
        (src / "seats" / "added.md").write_bytes(b"added by B\n")      # 增
        os.remove(str(src / "seats" / "approver.md"))                  # 刪

    with kit_copy(version=b"0.0.0.1\n") as a, project() as p:
        ok_run(p.run(install=a))
        first = snapshot(p.root / "devflow")
        with kit_copy(version=b"0.0.0.2\n", mutate=b_changes) as b:
            r = p.run(install=b)
            ok_run(r)
            eq(summary_of(r), b"kit-install: 0.0.0.1 -> 0.0.0.2 (upgrade)", "模式 upgrade")
            eq(actions_of(r), [b"devflow/VERSION: updated",
                               b"devflow/seats/added.md: created",
                               b"devflow/seats/approver.md: deleted"],
               "updated／created／deleted 各一")
        r = p.run(install=a)
        ok_run(r)
        eq(summary_of(r), b"kit-install: 0.0.0.2 -> 0.0.0.1 (downgrade)", "模式 downgrade")
        eq(actions_of(r), [b"devflow/VERSION: updated",
                           b"devflow/seats/added.md: deleted",
                           b"devflow/seats/approver.md: created"], "反向三個動作")
        eq(snapshot(p.root / "devflow"), first, "整棵樹逐 byte 回到第一次安裝後")


# kit-AC-7：devflow.local

@case("kit-AC-7-local-created-when-absent")
def _():
    with project() as p:
        r = p.run()
        ok_run(r)
        expect(b"devflow.local/README.md: created" in actions_of(r), "動作行", actions_of(r))
        eq(p.read("devflow.local/README.md"), LOCAL_TEMPLATE.read_bytes(),
           "bytes == devflow/templates/local-README.md")
        eq(sorted(os.listdir(str(p.path("devflow.local")))), ["README.md"], "只放 README.md")


@case("kit-AC-7-local-existing-forms-untouched")
def _():
    def a_dir(p):
        (p.root / "devflow.local").mkdir()

    def a_dir_missing_readme(p):
        (p.root / "devflow.local").mkdir()
        p.write("devflow.local/notes.md", b"mine\n")

    def a_file(p):
        p.write("devflow.local", b"not a directory\n")

    def a_dangling_symlink(p):
        p.symlink("devflow.local", "nowhere")

    for make, why in ((a_dir, "空目錄"), (a_dir_missing_readme, "目錄但缺 README"),
                      (a_file, "一般檔"), (a_dangling_symlink, "dangling symlink")):
        with project() as p:
            make(p)
            before = local_snapshot(p.root)
            r = p.run()
            ok_run(r)
            expect(not any(b"devflow.local" in line for line in actions_of(r)),
                   "lexists 真 → 不印任何 devflow.local 行（%s）" % why, actions_of(r))
            eq(local_snapshot(p.root), before, "devflow.local 整棵不碰（%s）" % why)


# kit-AC-8：devflow.yml 不建、不改

@case("kit-AC-8-devflow-yml-untouched")
def _():
    with project({"devflow.yml": REPO_YML}) as p:
        ok_run(p.run())
        eq(p.read("devflow.yml"), REPO_YML, "安裝前後 bytes 相同")
        expect(not p.rewritten("devflow.yml"), "devflow.yml must not be rewritten")
    with project() as p:
        ok_run(p.run())
        expect(not os.path.lexists(str(p.path("devflow.yml"))), "目標無 devflow.yml → 不建")


# kit-AC-9：advisory 與其優先序

@case("kit-AC-9-advisory-when-yml-absent")
def _():
    with project() as p:
        rd = p.run("--dry-run")
        eq(rd.returncode, 0, "dry-run exit 0")
        eq(rd.stderr, KIT_YML_ADVISORY, "--dry-run 同樣印，且恰一行")
        r = p.run()
        eq(r.returncode, 0, "exit 0（advisory 不影響 exit）")
        eq(r.stderr, KIT_YML_ADVISORY, "stderr 恰一行")


@case("kit-AC-9-no-advisory-when-yml-present")
def _():
    with project({"devflow.yml": YML_CLAUDE}) as p:
        r = p.run()
        eq(r.returncode, 0, "exit 0")
        eq(r.stderr, b"", "有 devflow.yml → 不印")


@case("kit-AC-9-entry-advisory-alone-when-yml-present")
def _():
    # AC-9 的優先序條款（AC-7 先、本條後）在**一致的檔案系統下不可達**：AC-7 的 advisory
    # 要 devflow.yml 讀得到且有 seats: 頂層行，本條的要 devflow.yml 不存在——兩者互斥，
    # 實際 stderr 永遠至多一行 advisory。要讓兩行同時出現，只能在安裝器的兩次存在性判斷
    # 之間讓檔案消失，那是在測一個人為競態，不是規格的行為，本 harness 不做
    #（PR #138 第一輪阻擋 1 的處置）。實作的順序（choose_targets() 的 AC-7 advisory 先
    # append、AC-9 的後 append）以 devflow/install.py run() 的程式碼為準。
    # 本案驗的是：有 AC-7 advisory 時本條不出現，且 stderr 逐字如入口規格所期望。
    with project({"devflow.yml": NESTED_CLAUDE}) as p:
        r = p.run()
        eq(r.returncode, 0, "exit 0")
        eq(r.stderr, ADVISORY, "只有入口規格 AC-7 的 advisory")


@case("kit-AC-9-no-advisory-on-exit-2")
def _():
    # exit 非 0 時 stderr 只有錯誤那一行（本例的目標無 devflow.yml，exit 0 時會有 advisory）
    with project() as p:
        p.write("devflow", b"not a directory\n")
        r = p.run()
        err_run(r, 2)
        eq(r.stderr, b"devflow: not a directory\n", "stderr 恰一行錯誤，無 advisory")


# AC-15 依路徑字串序檢查，第一個不可寫的即報——哪個檔案是第一個取決於 kit 當下的檔案集合
# （#196：RELEASING.md 加入後由 VERSION 變成它），故下一案只斷言形狀不綁檔名。
# 字元類排掉 \n 是刻意的：只寫 [^:]+ 會跨行，「第二行無冒號」的 stderr 就漏網（#196）。
UNWRITABLE_RE = re.compile(rb"devflow/[^:\n]+: directory not writable\n")


@case("kit-AC-9-entry-advisory-buffered-until-exit-0-on-exit-2")
def _():
    # 入口規格 AC-7 的 advisory 原本在 choose_targets() 中途就 print——那樣 exit 2 的
    # stderr 會變兩行。構造：兩入口檔皆無 ＋ seats: 有但投影讀不到（advisory 觸發），
    # 再讓決策階段在 choose_targets() **之後**失敗（devflow/ 不可寫 → AC-15）
    require_non_root()
    with project({"devflow.yml": NESTED_CLAUDE}) as p:
        (p.root / "devflow").mkdir()
        p.write("devflow/stray.md", b"mine\n")
        os.chmod(str(p.path("devflow")), 0o555)
        try:
            r = p.run()
            err_run(r, 2)
            # 本案驗的是「advisory 在 exit 2 時被緩衝掉、stderr 只剩錯誤那一行」
            # （kit-install AC-9）；哪個檔先被判不可寫不是本案要驗的性質
            expect(bool(UNWRITABLE_RE.fullmatch(r.stderr)),
                   "stderr 恰一行錯誤，advisory 被緩衝掉", r.stderr, UNWRITABLE_RE.pattern)
            eq(r.stderr.count(b"\n"), 1, "stderr 恰一行")
        finally:
            os.chmod(str(p.path("devflow")), 0o755)


@case("kit-AC-9-entry-advisory-buffered-until-exit-0-on-exit-3")
def _():
    # 同上，但失敗發生在**寫入階段**（exit 3）：advisory 一樣不印，stdout 一樣全部抑制。
    # 目標的 devflow/a、devflow/b 直接鋪好，不先跑一次安裝——跑過就會有入口檔，
    # 有入口檔就不會觸發入口規格 AC-7 的 advisory
    def v2(src):
        (src / "a").write_bytes(b"A2\n")
        (src / "b").write_bytes(b"B2\n")
        path = src / "install.py"
        path.write_bytes(FAIL_SHIM + path.read_bytes())

    with kit_copy(mutate=v2) as inst, project({"devflow.yml": NESTED_CLAUDE}) as p:
        (p.root / "devflow").mkdir()
        p.write("devflow/a", b"A0\n")
        p.write("devflow/b", b"B0\n")
        r = p.run(install=inst)
        err_run(r, 3)
        eq(r.stderr, b"devflow/b: Permission denied\n", "stderr 恰一行錯誤，無 advisory")
        eq(p.read("devflow/a"), b"A2\n", "失敗路徑之前的動作已落盤")
        eq(p.read("devflow/b"), b"B0\n", "失敗路徑未動")
        expect(not os.path.lexists(str(p.path("AGENTS.md"))),
               "入口檔在最後一階段，沒走到")


@case("kit-stderr-exactly-one-line-both-entry-files-fail")
def _():
    # kit-install「驗收標準」開頭：exit 非 0 時 stderr **恰一行**。入口規格的原子性會把集合內
    # 每個檔的錯都收集起來，兩個入口檔同時壞掉時原本會印兩行——收窄為只報決定 exit code 的
    # 那一個；exit code 仍取最重的（這裡兩個都是 1）
    bad = PREFIX + BEGIN_LINE + b"open\n"
    with project({"CLAUDE.md": bad, "AGENTS.md": bad}) as p:
        r = p.run()
        err_run(r, 1)
        eq(r.stderr, p.display("CLAUDE.md") + b":5: devflow:begin without end\n",
           "stderr 恰一行，報集合內第一個錯")
        for name in ("CLAUDE.md", "AGENTS.md"):
            eq(p.read(name), bad, name + " 不寫")
        expect(not os.path.lexists(str(p.path("devflow"))), "鏡像也不寫")


# kit-AC-10：--dry-run 走完整決策、不寫；決策階段的結果與實跑逐字相同

@case("kit-AC-10-dry-run-no-write-matches-real")
def _():
    files = {"CLAUDE.md": PREFIX}
    with project(files) as dry, project(files) as real:
        before = snapshot(dry.root)
        rd = dry.run("--dry-run")
        rr = real.run()
        ok_run(rd)
        ok_run(rr)
        eq(snapshot(dry.root), before, "--dry-run 前後整棵樹的 bytes 與存在性相同")
        eq(summary_of(rd), summary_of(rr), "摘要行逐字相同")
        eq(actions_of(rd), actions_of(rr), "動作行逐字相同")
        eq(rd.stderr, rr.stderr, "stderr 逐字相同")
        eq(entry_out(rd), unified(PREFIX, T + b"\n" + PREFIX, b"CLAUDE.md"),
           "入口檔部分依入口規格 AC-10")


@case("kit-AC-10-dry-run-exit-2-matches-real")
def _():
    with project() as dry, project() as real:
        for p in (dry, real):
            p.write("devflow", b"not a directory\n")
        before = snapshot(dry.root)
        rd = dry.run("--dry-run")
        rr = real.run()
        err_run(rd, 2)
        err_run(rr, 2)
        eq(rd.stderr, rr.stderr, "exit 2 的 stderr 逐字相同")
        eq(snapshot(dry.root), before, "兩者都不寫任何檔")
        eq(snapshot(real.root), before, "兩者都不寫任何檔")


# kit-AC-11：摘要行的五個模式與動作行的排序

@case("kit-AC-11-summary-mode-replace-and-fresh")
def _():
    with project() as p:
        ok_run(p.run())
        p.write("devflow/VERSION", b"not a version\n")
        r = p.run()
        ok_run(r)
        eq(summary_of(r), b"kit-install: invalid -> " + V + b" (replace)",
           "舊版存在但不合「版本」定義 → 印 invalid、模式 replace")
    with project() as p:
        ok_run(p.run())
        os.remove(str(p.path("devflow/VERSION")))
        r = p.run()
        ok_run(r)
        eq(summary_of(r), b"kit-install: none -> " + V + b" (fresh)",
           "有 devflow/ 但無 VERSION → fresh")


@case("kit-AC-11-action-lines-sorted-by-path")
def _():
    # 排序鍵是**路徑字串**不是整行：`devflow/a` 與 `devflow/a.md` 的先後在兩種排法下相反
    # （`:` > `.`）。devflow.local/README.md 排在 devflow/… 之前（`.` < `/`）。
    def add(src):
        (src / "a").write_bytes(b"a\n")
        (src / "a.md").write_bytes(b"a.md\n")

    with kit_copy(mutate=add) as inst, project() as p:
        r = p.run(install=inst)
        ok_run(r)
        lines = actions_of(r)
        eq(lines[0], b"devflow.local/README.md: created", "devflow.local 排在最前")
        eq([line for line in lines if line.startswith(b"devflow/a")],
           [b"devflow/a: created", b"devflow/a.md: created"], "依路徑字串，不是整行")
        paths = [line.rsplit(b": ", 1)[0] for line in lines]
        eq(paths, sorted(paths), "全域依路徑字串 sorted()")


# kit-AC-12：來源 VERSION 缺或不合定義 → exit 2，不讀目標、不做任何決策

@case("kit-AC-12-source-version-missing")
def _():
    def drop(src):
        os.remove(str(src / "VERSION"))

    with kit_copy(mutate=drop) as inst, project() as p:
        before = snapshot(p.root)
        r = p.run(install=inst)
        err_run(r, 2)
        expect(r.stderr.startswith(b"devflow/VERSION: "), "stderr 指 devflow/VERSION", r.stderr)
        eq(r.stderr.count(b"\n"), 1, "stderr 恰一行")
        eq(snapshot(p.root), before, "不寫任何檔")


@case("kit-AC-12-source-version-checked-before-target")
def _():
    # AC-12 的「不讀目標、不做任何決策」：來源 VERSION 無效 ＋ **目標路徑根本不存在** →
    # 仍須報 VERSION 那一行。先讀目標的實作會報入口規格 AC-11 的「目標路徑不存在」
    with kit_copy(version=b"not a version\n") as inst, project() as p:
        missing = str(p.root / "nope")
        r = p.run(target=missing, install=inst)
        err_run(r, 2)
        eq(r.stderr, b"devflow/VERSION: malformed; expected exactly one line a.b.c.d\n",
           "報 VERSION 的錯，證明版本檢查排在讀目標之前")
        expect(missing.encode() not in r.stderr, "沒有報目標路徑", r.stderr)


@case("kit-AC-12-source-version-malformed")
def _():
    for bad, why in ((b"0.0.1\n", "三碼"), (b"0.0.0.1.2\n", "五碼"),
                     (b"0.0.0.1", "無尾端換行"), (b"0.0.0.1\n\n", "多一個換行"),
                     (b"0.0.0.1\n0.0.0.2\n", "兩行"), (b"01.0.0.1\n", "前導零"),
                     (b"\xef\xbb\xbf0.0.0.1\n", "BOM"), (b"v0.0.0.1\n", "前綴 v"),
                     (b" 0.0.0.1\n", "前導空白"), (b"0.0.0.1 \n", "尾端空白"),
                     (b"0.0.0.a\n", "非數字"), (b"", "空檔")):
        with kit_copy(version=bad) as inst, project() as p:
            r = p.run(install=inst)
            err_run(r, 2)
            eq(r.stderr, b"devflow/VERSION: malformed; expected exactly one line a.b.c.d\n",
               "stderr（%s）" % why)
    # 對照：合定義的邊界值照樣裝得起來，且摘要行用它
    for good in (b"0.0.0.0\n", b"10.20.30.40\n"):
        with kit_copy(version=good) as inst, project() as p:
            r = p.run(install=inst)
            ok_run(r)
            eq(summary_of(r), b"kit-install: none -> " + good.strip() + b" (fresh)",
               "合定義的版本（%s）" % short(good))


# kit-AC-13：來源有 symlink → exit 2

@case("kit-AC-13-source-symlink-rejected")
def _():
    def to_file(src):
        os.symlink("WORKFLOW.md", str(src / "alias.md"))

    def to_dir(src):
        os.symlink("seats", str(src / "roles"))

    def dangling(src):
        os.symlink("nowhere.md", str(src / "gone.md"))

    for mutate, rel, why in ((to_file, b"alias.md", "指向檔"),
                             (to_dir, b"roles", "指向目錄"),
                             (dangling, b"gone.md", "dangling")):
        with kit_copy(mutate=mutate) as inst, project() as p:
            before = snapshot(p.root)
            r = p.run(install=inst)
            err_run(r, 2)
            eq(r.stderr, b"devflow/" + rel + b": symlink in source not supported\n",
               "stderr（%s）" % why)
            eq(snapshot(p.root), before, "不寫任何檔（%s）" % why)


# kit-AC-14：目標 devflow 存在但不是目錄 → exit 2

@case("kit-AC-14-target-devflow-not-a-directory")
def _():
    def a_file(p):
        p.write("devflow", b"not a directory\n")

    def symlink_to_dir(p):
        (p.root / "elsewhere").mkdir()
        p.symlink("devflow", "elsewhere")

    def dangling(p):
        p.symlink("devflow", "nowhere")

    for make, expected, why in (
            (a_file, b"devflow: not a directory\n", "一般檔"),
            (symlink_to_dir, b"devflow: symlink, not a directory\n", "指向目錄的 symlink"),
            (dangling, b"devflow: symlink, not a directory\n", "dangling symlink")):
        with project() as p:
            make(p)
            before = snapshot(p.root)
            r = p.run()
            err_run(r, 2)
            eq(r.stderr, expected, "stderr（%s）" % why)
            eq(snapshot(p.root), before, "不寫任何檔（%s）" % why)


# kit-AC-14b：目標 symlink 是鏡像集合某路徑的祖先 → exit 2；非祖先者照「動作」定義走

@case("kit-AC-14b-symlink-ancestor-rejected")
def _():
    # 來源有 devflow/seats/<檔>，目標 devflow/seats 是指向別處的 symlink：必須 exit 2，
    # 且連結指向的目錄一個新檔都沒有（否則寫入會沿連結越出目標）
    with project() as p, project() as out:
        (p.root / "devflow").mkdir()
        p.symlink("devflow/seats", str(out.root))
        before, out_before = snapshot(p.root), snapshot(out.root)
        r = p.run()
        err_run(r, 2)
        eq(r.stderr, b"devflow/seats: symlink where source has directory\n", "stderr")
        eq(snapshot(p.root), before, "不寫任何檔")
        eq(snapshot(out.root), out_before, "連結指向的目錄沒有新檔")


@case("kit-AC-14b-non-ancestor-symlink-is-deleted")
def _():
    # 祖先關係以 POSIX 路徑段判、不 resolve：devflow/sea 不是 devflow/seats/… 的祖先，
    # 來源也沒有這個路徑 → 照「動作」定義是 deleted（來源同路徑是檔者 → updated，見 kit-AC-2）
    with project({"outside.md": b"outside\n"}) as p:
        ok_run(p.run())
        p.symlink("devflow/sea", "../outside.md")
        r = p.run()
        ok_run(r)
        eq(actions_of(r), [b"devflow/sea: deleted"], "非祖先的 symlink → deleted")
        eq(p.read("outside.md"), b"outside\n", "只移除連結本身")


# kit-AC-15：可寫性（決策階段，dry-run 亦檢查）

@case("kit-AC-15-unwritable-existing-file-exit-2")
def _():
    require_non_root()
    with project() as p:
        ok_run(p.run())
        p.write("devflow/WORKFLOW.md", b"stale\n")
        p.chmod("devflow/WORKFLOW.md", 0o444)
        before = snapshot(p.root)
        rd = p.run("--dry-run")
        rr = p.run()
        err_run(rd, 2)
        err_run(rr, 2)
        eq(rd.stderr, rr.stderr, "dry-run 亦檢查，stderr 相同")
        eq(rr.stderr, b"devflow/WORKFLOW.md: not writable\n", "stderr")
        eq(snapshot(p.root), before, "不寫任何檔")


@case("kit-AC-15-unwritable-directory-exit-2")
def _():
    require_non_root()
    with project({"CLAUDE.md": PREFIX, "devflow.yml": YML_CLAUDE}) as p:
        ok_run(p.run())
        p.write("devflow/stray.md", b"mine\n")
        os.chmod(str(p.path("devflow")), 0o555)
        try:
            before = snapshot(p.root)
            rd = p.run("--dry-run")
            rr = p.run()
            err_run(rd, 2)
            err_run(rr, 2)
            eq(rd.stderr, rr.stderr, "dry-run 亦檢查，stderr 相同")
            eq(rr.stderr, b"devflow/stray.md: directory not writable\n", "stderr")
            eq(snapshot(p.root), before, "不寫任何檔")
        finally:
            os.chmod(str(p.path("devflow")), 0o755)


# kit-AC-16：寫入全序與 exit 3。副本的 install.py 前面注入 shim 讓對 devflow/b 的
# os.replace 拋 OSError——變造的是 /tmp 的副本，repo 的 install.py 不含任何測試鉤子。

FAIL_SHIM = (b"import os as _os\n"
             b"_real_replace = _os.replace\n"
             b"def _replace(src, dst, **kw):\n"
             b"    if str(dst).endswith('/devflow/b'):\n"
             b"        raise OSError(13, 'Permission denied', str(dst))\n"
             b"    return _real_replace(src, dst, **kw)\n"
             b"_os.replace = _replace\n")


@case("kit-AC-16-write-order-and-exit-3")
def _():
    def v1(src):
        (src / "a").write_bytes(b"A1\n")
        (src / "b").write_bytes(b"B1\n")

    def v2(src):
        (src / "a").write_bytes(b"A2\n")
        (src / "b").write_bytes(b"B2\n")
        path = src / "install.py"
        path.write_bytes(FAIL_SHIM + path.read_bytes())

    with kit_copy(mutate=v1) as first, project() as p:
        ok_run(p.run(install=first))
        outside = outside_snapshot(p.root)
        entry_before = p.read("AGENTS.md")
        with kit_copy(mutate=v2) as second:
            r = p.run(install=second)
            err_run(r, 3)
            eq(r.stderr, b"devflow/b: Permission denied\n",
               "stderr 恰一行 <失敗路徑>: <OSError strerror>")
        # 全序＝階段順序 × 階段內 sorted()：created／updated 這一階段是 a → b → install.py
        eq(p.read("devflow/a"), b"A2\n", "失敗路徑之前的動作已落盤")
        eq(p.read("devflow/b"), b"B1\n", "失敗路徑未動")
        expect(FAIL_SHIM not in p.read("devflow/install.py"), "失敗路徑之後的動作未動")
        eq(p.read("AGENTS.md"), entry_before, "入口檔在最後一階段，未動")
        eq(outside_snapshot(p.root), outside, "AC-18：exit 3 的情境下其他路徑仍不動")


def prune_swap_shim(outside):
    """同型的 shim，但注入的是**動作**不是失敗：deleted 階段移除 devflow/zz/deep/x.md 之後、
    prune 之前，把 devflow/zz 換成指向 outside 的 symlink（決策之後才出現的 TOCTOU）。

    與 FAIL_SHIM 一樣只寫進 /tmp 副本的 install.py，repo 的 install.py 不含任何測試鉤子。
    """
    return ("import os as _os\n"
            "_real_remove = _os.remove\n"
            "def _remove(path, **kw):\n"
            "    _real_remove(path, **kw)\n"
            "    if str(path).endswith('/devflow/zz/deep/x.md'):\n"
            "        zz = _os.path.dirname(_os.path.dirname(str(path)))\n"
            "        _os.rmdir(_os.path.join(zz, 'deep'))\n"
            "        _os.rmdir(zz)\n"
            "        _os.symlink(%r, zz)\n"
            "_os.remove = _remove\n" % str(outside)).encode()


@case("kit-AC-16-prune-refuses-link-ancestor")
def _():
    # 第二道 symlink 祖先檢查在 prune 也要有：os.path.isdir 與 os.listdir 都會跟隨連結，
    # 祖先在決策之後變成 symlink 的話，os.rmdir 會刪掉目標外的目錄（PR #138 阻擋 3）。
    # prune 深者先，devflow/zz/deep 排在 devflow/zz 之前——正是會沿著新連結出去的那一步。
    with project() as outside, project() as p:
        (outside.root / "deep").mkdir()
        outside.write("keep.md", b"keep\n")
        outside_before = snapshot(outside.root)

        def swap(src):
            path = src / "install.py"
            path.write_bytes(prune_swap_shim(outside.root) + path.read_bytes())

        with kit_copy(mutate=swap) as inst:
            ok_run(p.run(install=inst))           # 第一次安裝：沒有 deleted，shim 不觸發
            (p.root / "devflow" / "zz" / "deep").mkdir(parents=True)
            p.write("devflow/zz/deep/x.md", b"x\n")
            r = p.run(install=inst)
            err_run(r, 3)
            eq(r.stderr,
               b"devflow/zz/deep: symlink appeared under devflow/ during the write phase\n",
               "stderr 恰一行，走與其他寫入失敗相同的 exit 3 路徑")
        expect(p.path("devflow/zz").is_symlink(), "前提：shim 真的把 zz 換成 symlink 了")
        eq(snapshot(outside.root), outside_before, "連結指向的外部目錄一個 byte 都沒動")


# kit-AC-17：對執行中的 kit 本身的四項檢查

@case("kit-AC-17-kit-self-check")
def _():
    src = REPO / "devflow"
    problems = []
    if install.parse_version(KIT_VERSION) is None:
        problems.append("devflow/VERSION 不合「版本」定義：%s" % short(KIT_VERSION))
    for rel in ("templates/devflow.yml", "templates/local-README.md"):
        if not (src / rel).is_file():
            problems.append("devflow/%s 不存在" % rel)
    for dirpath, dirnames, filenames in os.walk(str(src), followlinks=False):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in dirnames + filenames:
            full = Path(dirpath) / name
            if not name.endswith(".pyc") and full.is_symlink():
                problems.append("devflow/%s 是 symlink" % full.relative_to(src))
    for table_dir in ("coders", "forges", "orchestrators"):
        for md in sorted((src / table_dir).glob("*.md")):
            for n, line in enumerate(md.read_text(encoding="utf-8").split("\n"), 1):
                if line.lstrip().startswith("## 本機"):
                    problems.append("%s:%d 有「## 本機」標題行" % (md.relative_to(REPO), n))
    expect(not problems, "kit 本身不合 AC-17：\n      " + "\n      ".join(problems))


# kit-AC-18：devflow/、devflow.local/、入口檔以外的路徑，安裝前後 bytes 與存在性相同

@case("kit-AC-18-other-paths-untouched")
def _():
    with project({"README.md": b"# mine\n", "notes.txt": b"notes\n"}) as p:
        (p.root / "src").mkdir()
        p.write("src/app.py", b"print(1)\n")
        p.symlink("link.md", "README.md")
        before = outside_snapshot(p.root)
        ok_run(p.run())
        eq(outside_snapshot(p.root), before, "第一次執行不動其他路徑")
        p.write("devflow/stray.md", b"mine\n")
        ok_run(p.run())
        eq(outside_snapshot(p.root), before, "有 created／deleted 的執行也不動其他路徑")


# kit-AC-19：來源＝目標

@case("kit-AC-19-source-equals-target")
def _():
    with kit_copy() as inst:
        root = inst.parent.parent          # <tmp>/devflow/install.py → <tmp>
        r = subprocess.run([sys.executable, str(inst), str(root)], capture_output=True)
        ok_run(r)
        eq(summary_of(r), b"kit-install: " + V + b" -> " + V + b" (same)", "模式 same")
        eq(actions_of(r), [b"devflow.local/README.md: created"],
           "鏡像全部 unchanged、無 deleted；devflow.local 依 AC-7")
        eq(entry_out(r), str(root / "AGENTS.md").encode() + b": created\n", "入口檔依入口規格")
        eq(kit_files(root / "devflow"), kit_files(), "鏡像集合沒有被自己的安裝改動")


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
