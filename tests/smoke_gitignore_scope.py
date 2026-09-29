#!/usr/bin/env python3
# -*- coding: utf-8 -*-
""".gitignore 的 `.devflow-local` 規則的射程（issue #252）：四條量測路徑中只有 repo 根那一條被忽略。

從任何目錄執行（本 repo 的 `.gitignore` 由 `__file__` 定位）：

    python3 tests/smoke_gitignore_scope.py

只用標準庫＋git，exit 0（全過）／1（內容違規，含本測試無鑑別力）／2（跑不起來）。

為什麼有這個檔：無斜線的 `.devflow-local` 在 git 的語意是「任何層級的同名檔」，
於是將來預定受版控的樣本（例如 `tests/fixtures/.devflow-local`）`git add -A` 加不進去，
`tests/smoke_devflow_checks.py` 的 `git ls-files --others --exclude-standard` 也選不到它。
scripts/devflow_checks.py 說該設定檔住 repo 根目錄，規則就該錨定成 `/.devflow-local`。

**在暫存 repo 裡量，不在本 repo 裡量**（PR #266 R1 BLOCK 1）：`git check-ignore` 除了
`.gitignore`，還會讀 `core.excludesFile`（使用者全域設定）與 `.git/info/exclude`（該 clone
自己的）。兩者都不是 repo 內容，卻能讓子目錄路徑被忽略——在本 repo 裡直接量，合法的
`.gitignore` 會被使用者環境判成「內容違規」exit 1，違反下面的 1／2 分類。所以正、負兩組
都在 `git init` 出來的暫存 repo 裡量：`.gitignore` 自本 repo 當下的檔逐位元組複製（負向
再拿掉錨定），`core.excludesFile` 以 `-c` 指向 /dev/null。暫存 repo 的 `info/exclude` 不含
這條規則是**本測試主動保證的**，不是假設：`git init` 預設從 template 目錄（可被
`GIT_TEMPLATE_DIR`／`init.templateDir` 改指）複製 `info/exclude`，所以這裡以測試自建的空
template 初始化（`--template=` 優先於環境變數與設定），init 後再把 `info/exclude` 寫空
（PR #266 R1 第 2 輪 BLOCK 1）。所有 git 子程序以剝除 `GIT_*`（只保留 `GIT_EXEC_PATH`）的
環境執行，暫存 repo 不受呼叫端 `GIT_DIR`／`GIT_WORK_TREE`／`GIT_TEMPLATE_DIR` 等影響；init
後另驗 git dir 與 `info/exclude` 皆落在暫存目錄內，否則 exit 2——任何情況下都不寫暫存目錄
以外的檔（PR #266 R1 第 3 輪 BLOCK 1）。輸出的「真 repo」指的是**本 repo 的 `.gitignore` 內容**。

**`--no-index`**：`git check-ignore` 對已在 index 的路徑預設回 1（不報告）；加上它才是
純粹問忽略規則。四條路徑都不必真的存在，本檔不碰本 repo 的 index 與工作樹。

**內建負向對照**：拿掉那一行的前導 `/` 之後，同四條路徑必須恰有 3 條（三個子目錄路徑）
與期望不符。抓不到就表示這支測試對「錨定被拿掉」沒有鑑別力，自報並 exit 1——正向過了
也不算數。
"""
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GITIGNORE = REPO / ".gitignore"
RULE = ".devflow-local"

# (路徑, 期望 rc)：0＝被忽略，1＝不被忽略。
CASES = [
    (".devflow-local", 0),
    ("tests/fixtures/.devflow-local", 1),
    ("devflow.local/.devflow-local", 1),
    ("a/b/c/.devflow-local", 1),
]


# ── exit code：0 全過／1 內容違規／2 跑不起來（比照 tests/smoke_readme_refs.py） ──────
# Python 對未攔截的例外預設以 1 結束，會和內容違規撞號，而兩者的處置相反：
# 前者修環境，後者改 .gitignore。SystemExit 不經 hook，main() 的 return 值不受影響。
def _uncaught(exc_type, exc, tb):
    try:
        sys.stdout.flush()
        traceback.print_exception(exc_type, exc, tb)
        print("💥 gitignore 射程檢查無法執行：未預期的 %s: %s（未分類的例外一律 exit 2，不是內容違規）"
              % (exc_type.__name__, exc))
        sys.stdout.flush()
    finally:
        sys.exit(2)               # 連印訊息都失敗也要是 2，不能退回 Python 預設的 1


sys.excepthook = _uncaught


class CannotRun(Exception):
    """環境問題：git 回了預期以外的狀態碼，或暫存 repo 的路徑不在暫存目錄內。"""


def git_env():
    """呼叫端環境剝除所有 `GIT_*`，只留 `GIT_EXEC_PATH`（見檔頭）。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    if "GIT_EXEC_PATH" in os.environ:
        env["GIT_EXEC_PATH"] = os.environ["GIT_EXEC_PATH"]
    return env


def inside(path, root):
    """path 解析後是否落在 root（解析後）底下。"""
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def check_ignore(cwd, path):
    """`git check-ignore -q --no-index -- <path>` 的 rc；0／1 以外一律當跑不起來。

    `-c core.excludesFile=/dev/null` 關掉使用者全域的忽略檔（見檔頭）。"""
    p = subprocess.run(["git", "-c", "core.excludesFile=/dev/null",
                        "check-ignore", "-q", "--no-index", "--", path],
                       cwd=str(cwd), env=git_env(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if p.returncode not in (0, 1):
        raise CannotRun("git check-ignore %s 在 %s 回 %d：%s"
                        % (path, cwd, p.returncode, p.stderr.decode("utf-8", "replace").strip()))
    return p.returncode


def run_in_scratch(gitignore):
    """在新 `git init` 的暫存 repo 放入 gitignore（bytes），回傳 [(路徑, 期望 rc, 實得 rc)]。

    空 template ＋ 清空 `info/exclude`：暫存 repo 裡除了這份 gitignore 之外沒有別的忽略來源（見檔頭）。"""
    with tempfile.TemporaryDirectory() as tmp:
        template = Path(tmp) / "template"
        repo = Path(tmp) / "repo"
        template.mkdir()
        p = subprocess.run(["git", "init", "-q", "--template=%s" % template, str(repo)],
                           env=git_env(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if p.returncode != 0:
            raise CannotRun("git init %s 回 %d：%s"
                            % (repo, p.returncode, p.stderr.decode("utf-8", "replace").strip()))
        # 兩道路徑防護都在寫入之前：git dir 或 info/exclude 不在暫存 repo 底下就不寫、exit 2。
        p = subprocess.run(["git", "-C", str(repo), "rev-parse", "--absolute-git-dir"],
                           env=git_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode != 0:
            raise CannotRun("git rev-parse --absolute-git-dir 回 %d：%s"
                            % (p.returncode, p.stderr.decode("utf-8", "replace").strip()))
        gitdir = p.stdout.decode("utf-8").strip()
        if not inside(gitdir, repo):
            raise CannotRun("暫存 repo 的 git dir 是 %s，不在 %s 底下" % (gitdir, repo))
        p = subprocess.run(["git", "-C", str(repo), "rev-parse", "--git-path", "info/exclude"],
                           env=git_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode != 0:
            raise CannotRun("git rev-parse --git-path info/exclude 回 %d：%s"
                            % (p.returncode, p.stderr.decode("utf-8", "replace").strip()))
        exclude = repo / p.stdout.decode("utf-8").strip()   # 相對路徑以 repo 為基準；絕對路徑照用
        if not inside(exclude, repo):
            raise CannotRun("暫存 repo 的 info/exclude 是 %s，不在 %s 底下" % (exclude, repo))
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_bytes(b"")
        (repo / ".gitignore").write_bytes(gitignore)
        return [(path, want, check_ignore(repo, path)) for path, want in CASES]


def unanchor(data):
    """把 `/.devflow-local` 那一行的前導 `/` 拿掉；回傳 (新內容, 動到的行號)，找不到行號為 None。"""
    lines = data.split(b"\n")
    for n, line in enumerate(lines):
        if line.strip() in (("/" + RULE).encode(), RULE.encode()):
            lines[n] = RULE.encode()
            return b"\n".join(lines), n + 1
    return data, None


def main():
    # .gitignore 是受版控的 repo 內容：它不見了是內容違規（1），不是環境問題（PR #266 R1 第 2 輪 BLOCK 2）。
    if not GITIGNORE.exists():
        print("❌ 真 repo: 找不到 .gitignore（內容違規：受版控的 .gitignore 不存在）")
        return 1
    data = GITIGNORE.read_bytes()

    failures = []
    try:
        # 正向：本 repo 的 .gitignore 原文
        print("正向  暫存 repo，.gitignore 逐位元組複製自本 repo")
        # 失敗行只印這一次（總結不重複），`grep -c '❌ 真 repo:'` 才等於違規條數。
        for path, want, got in run_in_scratch(data):
            ok = got == want
            print("%s 真 repo: %s 期望 rc %d，實得 rc %d" % ("✅" if ok else "❌", path, want, got))
            if not ok:
                failures.append(path)
        print()

        # 負向對照：拿掉錨定，同四條路徑必須恰有 3 條與期望不符
        mutated, lineno = unanchor(data)
        diffs = []
        if lineno is None:
            print("負向對照  .gitignore 裡找不到 `%s` 那一行，無從拿掉錨定" % RULE)
        else:
            print("負向對照  暫存 repo，.gitignore 第 %d 行改成 `%s`（拿掉前導 /）" % (lineno, RULE))
            for path, want, got in run_in_scratch(mutated):
                hit = got != want
                print("  %s  %-32s 期望 rc %d、實得 rc %d"
                      % ("⚡ 差異" if hit else "   相同", path, want, got))
                if hit:
                    diffs.append(path)
        want_diffs = [p for p, w in CASES if w == 1]
        print("負向對照抓到 %d 條（期望 %d）" % (len(diffs), len(want_diffs)))
        if sorted(diffs) != sorted(want_diffs):
            print("❌ 本測試無鑑別力：拿掉錨定後的差異應恰為 %s" % "、".join(want_diffs))
            failures.append("本測試無鑑別力")
        print()
    except CannotRun as e:
        print("💥 gitignore 射程檢查無法執行：%s（exit 2，不是內容違規）" % e)
        return 2

    print("=" * 60)
    if failures:
        print("gitignore 射程檢查失敗（%d 項，見上方 ❌ 行）" % len(failures))
        return 1
    print("gitignore 射程檢查通過：四條量測路徑中只有根目錄的 `.devflow-local` 被忽略；"
          "負向對照有鑑別力")
    return 0


if __name__ == "__main__":
    sys.exit(main())
