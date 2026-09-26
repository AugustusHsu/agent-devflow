#!/usr/bin/env python3
"""tests/install/preflight.py — 某個目標 repo 的環境與安裝結果巡檢（issue #196 AC-7～AC-9）。

與 tests/install/harness.py 的分工（#196 的裁決）：harness 驗**安裝器行為**——在 /tmp 建假
專案、以 bytes 斷言；本檔驗**某個目標 repo 的環境與安裝結果**。定義域不同，所以分成兩支入口：
共用一支會讓兩種受檢對象混在同一個腳本裡。**共用輸出格式**，見下。

執行：
    python3 tests/install/preflight.py            # 受檢目標 ＝ cwd
    python3 tests/install/preflight.py <路徑>      # 受檢目標 ＝ 該路徑

AC-7～AC-9 是 **issue #196 的編號**，不是 docs/spec/install/spec.md 或
docs/spec/kit-install/spec.md 的（那兩份的 AC 由 harness 驗）：
- AC-7 工具鏈檢核：git、forge CLI（依目標的 devflow.yml `forge`）、Python
- AC-8 目錄完整度：devflow.yml、devflow/VERSION、devflow/WORKFLOW.md、devflow.local/
- AC-9 orchestrator 接入 symlink（依 `seats.coordinator.filler`）；附加項：devflow/ 下無 symlink

輸出（與 harness 同格式）：每項一行 `PASS|FAIL|SKIP <name>` 到 stdout，細節與 advisory 到
stderr，末行總計。無 FAIL 即 exit 0，有 FAIL exit 1。

exit 2 專留給「無法執行」：缺 PyYAML、引數不是目錄、引數過多。與 scripts/devflow_checks.py
同慣例——缺相依不是內容違規，兩者撞同一個狀態碼會讓「環境壞了」和「目標不合格」分不開。

**零 token、不連網**：登入狀態用 `gh auth token`（只讀本機設定）。不用 `gh auth status`，
它會連網。`gh auth token` 的 stdout 就是 token 本身，本檔只取它的 exit code，一個 byte 都不印。
"""
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError as e:
    print("💥 巡檢無法執行：缺少相依模組 %s（PyYAML 不是 stdlib，而 AC-7 的 forge、AC-8、"
          "AC-9 的 seats.coordinator.filler 都要讀目標的 devflow.yml）" % e.name)
    sys.exit(2)

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"

# 排除路徑（docs/spec/kit-install/spec.md:28 的封閉列舉）：名為 __pycache__ 的目錄連同其下
# 全部、副檔名 .pyc 的檔。AC-9 附加項的 symlink 掃描依此排除，與 harness 的 kit-AC-17 一致。
EXCLUDED_DIR = "__pycache__"
EXCLUDED_SUFFIX = ".pyc"

# 「版本」定義（docs/spec/kit-install/spec.md:27）的 fallback：與 devflow/install.py 的
# VERSION_RE 等價。只在載不進目標的安裝器時才用——正則有兩份就會漂移，見 version_re()。
FALLBACK_VERSION_RE = re.compile(
    rb"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\n")


def show(value):
    return "（無）" if value is None else repr(value)


class Report:
    """每項一行到 stdout、細節到 stderr、末行總計（與 harness.py main() 同格式）。"""

    def __init__(self):
        self.counts = {PASS: 0, FAIL: 0, SKIP: 0}

    def item(self, verdict, name, note=None):
        self.counts[verdict] += 1
        print(verdict, name, flush=True)
        if note:
            print("    " + str(note).replace("\n", "\n    "), file=sys.stderr, flush=True)

    def advisory(self, text):
        """不影響 exit code、不計入總計——advisory 不是一項判定。"""
        print("    advisory: " + text, file=sys.stderr, flush=True)

    def total(self):
        print("total %d, passed %d, failed %d, skipped %d"
              % (sum(self.counts.values()), self.counts[PASS], self.counts[FAIL],
                 self.counts[SKIP]), flush=True)
        return 0 if self.counts[FAIL] == 0 else 1


def run_cmd(argv):
    """(exit code 或 None, 說明)。找不到執行檔不是例外，是「這台機器沒有它」。

    說明只由 argv 與 exit code 組出來，**永不含 stdout**：`gh auth token` 的 stdout 是 token。
    """
    line = " ".join(argv)
    try:
        r = subprocess.run(argv, capture_output=True)
    except OSError as e:
        return None, "%s 執行不起來：%s" % (line, e.strerror or e)
    return r.returncode, "%s → exit %d" % (line, r.returncode)


def dig(conf, *keys):
    """巢狀取值；路上任一層不是 mapping 或缺鍵就回 None。"""
    node = conf
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def read_config(target):
    """(頂層 mapping 或 None, 說明)。

    解析出 mapping 才算「可解析」（AC-8）；其餘一律回 None，讓 AC-7 的 forge 與 AC-9 的
    filler 落進各自的「其他值」分支（SKIP 並印實際值）——讀不到就不是 github／hermes。
    """
    path = target / "devflow.yml"
    try:
        data = path.read_bytes()
    except OSError as e:
        return None, "devflow.yml 讀不到：%s" % (e.strerror or e)
    try:
        # bytes 直接交給 PyYAML：BOM 與編碼由它依 YAML 規則判，和真正讀這個檔的 parser 一致
        conf = yaml.safe_load(data)
    except yaml.YAMLError as e:
        return None, "devflow.yml 不可解析：%s: %s" % (type(e).__name__, str(e).replace("\n", " "))
    if not isinstance(conf, dict):
        return None, "devflow.yml 解析出 %s，不是頂層 mapping" % type(conf).__name__
    return conf, "devflow.yml 存在且可解析（頂層鍵 %d 個）" % len(conf)


def version_re(target):
    """(正則, fallback 說明或 None)：「版本」定義（spec.md:27）用的正則。

    優先從目標的 devflow/install.py 取 VERSION_RE——那是唯一來源，自己再寫一份就會漂移。
    載入方式與 scripts/devflow_checks.py:2119、harness.py:57 相同。
    不可寫 `from devflow.install import VERSION_RE`：devflow/ 無 __init__.py，且以
    `python3 tests/install/preflight.py` 執行時 sys.path[0] 是 tests/install、cwd 不在 path，
    那個 import 必定 ModuleNotFoundError。
    """
    installer = target / "devflow" / "install.py"
    sys.dont_write_bytecode = True        # 別在目標的 devflow/ 留 __pycache__
    try:
        spec = importlib.util.spec_from_file_location("devflow_install_preflight", installer)
        module = importlib.util.module_from_spec(spec)
        # 語法錯、import 錯、import 期的 sys.exit 都算載不進來（同 devflow_checks 的 foreign()）
        spec.loader.exec_module(module)
        pattern = module.VERSION_RE
        if pattern.fullmatch(b"0.0.0.1\n") is None:
            raise ValueError("取到的 VERSION_RE 認不得 b'0.0.0.1\\n'")
        return pattern, None
    except BaseException as e:
        return FALLBACK_VERSION_RE, ("devflow/install.py 取不到 VERSION_RE（%s: %s），"
                                     "改用本檔的等價正則" % (type(e).__name__, e))


# ── AC-7：工具鏈檢核 ─────────────────────────────────────────────────


def check_toolchain(rep, conf):
    code, note = run_cmd(["git", "--version"])
    rep.item(PASS if code == 0 else FAIL, "AC-7-toolchain-git", note)

    forge = conf.get("forge") if isinstance(conf, dict) else None
    if forge == "github":
        code, note = run_cmd(["gh", "--version"])
        rep.item(PASS if code == 0 else FAIL, "AC-7-toolchain-forge-cli", note)
        if code == 0:
            # 只看 exit code，stdout 不讀不印（那是 token）。exit 非 0 ＝ 未登入 → advisory，
            # 不影響 exit code：巡檢報告環境狀態，不替使用者決定他該不該登入。
            auth, _ = run_cmd(["gh", "auth", "token"])
            if auth != 0:
                rep.advisory("gh auth token → exit %s：這台機器未登入 gh。"
                             "forge 操作會失敗，但不影響本巡檢的 exit code" % show(auth))
    else:
        rep.item(SKIP, "AC-7-toolchain-forge-cli",
                 "devflow.yml 的 forge ＝ %s，不是 github；其他 forge 的 CLI 對照在 "
                 "devflow/forges/，未實測的格子不當作可用" % show(forge))

    # 不設版本門檻：repo 內無此依據——.github/workflows/docs.yml 用 3.12、harness 無門檻、
    # devflow/install.py 宣稱 stdlib only。憑空設一個下限是無依據的收緊，只印實際版本。
    rep.item(PASS, "AC-7-toolchain-python", "sys.version ＝ " + sys.version.replace("\n", " "))


# ── AC-8：目錄完整度 ─────────────────────────────────────────────────


def check_layout(rep, target, conf, conf_note):
    rep.item(PASS if isinstance(conf, dict) else FAIL, "AC-8-layout-devflow-yml", conf_note)

    pattern, fallback = version_re(target)
    if fallback:
        rep.advisory(fallback)
    path = target / "devflow" / "VERSION"
    try:
        data = path.read_bytes()
    except OSError as e:
        rep.item(FAIL, "AC-8-layout-version", "devflow/VERSION 讀不到：%s" % (e.strerror or e))
    else:
        ok = pattern.fullmatch(data) is not None
        rep.item(PASS if ok else FAIL, "AC-8-layout-version",
                 "devflow/VERSION ＝ %r%s" % (data, "" if ok else "，不合「版本」定義"
                                              "（spec.md:27：恰一行 a.b.c.d ＋ 恰一個 \\n、無 BOM）"))

    workflow = target / "devflow" / "WORKFLOW.md"
    rep.item(PASS if workflow.is_file() else FAIL, "AC-8-layout-workflow-md",
             "devflow/WORKFLOW.md %s" % ("存在" if workflow.is_file() else "不存在或不是一般檔"))

    local = target / "devflow.local"
    rep.item(PASS if local.is_dir() else FAIL, "AC-8-layout-devflow-local",
             "devflow.local/ %s" % ("存在" if local.is_dir() else "不存在或不是目錄"))


# ── AC-9：orchestrator 接入 symlink ─────────────────────────────────


def check_orchestrator(rep, target, conf):
    filler = dig(conf, "seats", "coordinator", "filler")
    if filler != "hermes":
        rep.item(SKIP, "AC-9-orchestrator-symlink",
                 "seats.coordinator.filler ＝ %s，不是 hermes；接入方式住 "
                 "devflow/orchestrators/<name>.md（spec.md:38：安裝器不建這個連結）" % show(filler))
    else:
        link = target / ".hermes" / "skills" / "devflow-orchestrator"
        want = target / "devflow" / "orchestrators" / "hermes"
        if not os.path.islink(str(link)):
            rep.item(FAIL, "AC-9-orchestrator-symlink",
                     ".hermes/skills/devflow-orchestrator %s（orchestrators/hermes.md 的"
                     "「流程指令住哪」格明訂它是 hermes 的接入方式）"
                     % ("缺席" if not os.path.lexists(str(link)) else "存在但不是 symlink"))
        else:
            # 兩端都取 realpath。只 resolve 一端、另一端用原字串會誤判：目標路徑本身含
            # symlink（/tmp → /private/tmp 之類）或引數是相對路徑時，字串就對不起來。
            # 不用 os.path.samefile：它要兩端都存在，dangling 連結會拋 OSError——
            # 而 dangling 正是本項要報的情形之一。
            got, expected = os.path.realpath(str(link)), os.path.realpath(str(want))
            rep.item(PASS if got == expected else FAIL, "AC-9-orchestrator-symlink",
                     ".hermes/skills/devflow-orchestrator → %s（期望 %s）" % (got, expected))

    # 附加項：目標 devflow/ 下（排除路徑以外）有任一 symlink → FAIL，無則 PASS。
    # 與 harness 的 kit-AC-17 是同一斷言、不同受檢對象：那邊驗**執行中的 kit 來源**，
    # 本項驗**安裝後的目標**。目標 ≠ kit 自身時兩者不重疊。
    root = target / "devflow"
    links = []
    for dirpath, dirnames, filenames in os.walk(str(root), followlinks=False):
        dirnames[:] = [d for d in dirnames if d != EXCLUDED_DIR]
        for name in dirnames + filenames:
            full = Path(dirpath) / name
            if not name.endswith(EXCLUDED_SUFFIX) and full.is_symlink():
                links.append(str(full.relative_to(target)))
    if links:
        note = "devflow/ 下有 symlink：" + "、".join(sorted(links))
    elif not root.is_dir():
        # 判定仍依字面（無 symlink → PASS）；devflow/ 缺席由 AC-8 的三項報，這裡只寫清楚
        # 這個 PASS 是空掃出來的，免得輸出看起來像「目標沒問題」
        note = "devflow/ 不存在或不是目錄，沒有可掃的 symlink"
    else:
        note = "devflow/ 下（排除路徑以外）無 symlink"
    rep.item(FAIL if links else PASS, "AC-9-no-symlink-under-devflow", note)


# ── 執行 ─────────────────────────────────────────────────────────────


def main(argv):
    if len(argv) > 1:
        print("用法：python3 tests/install/preflight.py [<目標 repo 路徑>]（省略 ＝ cwd）")
        return 2
    given = Path(argv[0]) if argv else Path.cwd()
    if not given.is_dir():
        print("💥 巡檢無法執行：%s 不是目錄" % given)
        return 2
    # resolve 後印出的路徑才是絕對且穩定的；AC-9 的比對另外兩端都取 realpath，不靠這一步
    target = given.resolve()
    # 受檢目標印到 stderr：stdout 只放「每項一行 ＋ 末行總計」，與 harness 的格式逐字相同
    print("preflight target: %s" % target, file=sys.stderr, flush=True)

    rep = Report()
    conf, conf_note = read_config(target)
    check_toolchain(rep, conf)
    check_layout(rep, target, conf, conf_note)
    check_orchestrator(rep, target, conf)
    return rep.total()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
