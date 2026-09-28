#!/usr/bin/env python3
# -*- coding: utf-8 -*-
""".gitignore 的 `.devflow-local` 規則只忽略 repo 根目錄那一份（issue #252）。

從任何目錄執行（repo 根由 `__file__` 定位，git 指令一律在 repo 根跑）：

    python3 tests/smoke_gitignore_scope.py

只用標準庫＋git，exit 0（全過）／1（內容違規，含本測試無鑑別力）／2（跑不起來）。

為什麼有這個檔：無斜線的 `.devflow-local` 在 git 的語意是「任何層級的同名檔」，
於是將來預定受版控的樣本（例如 `tests/fixtures/.devflow-local`）`git add -A` 加不進去，
`tests/smoke_devflow_checks.py` 的 `git ls-files --others --exclude-standard` 也選不到它。
scripts/devflow_checks.py 說該設定檔住 repo 根目錄，規則就該錨定成 `/.devflow-local`。

**`--no-index`**：`git check-ignore` 對已在 index 的路徑預設回 1（不報告），
會讓受版控目錄下的路徑測出假陰性；加上它才是純粹問 `.gitignore` 規則。
四條路徑都不必真的存在，本檔不動 index、不改工作樹。

**內建負向對照**：在暫存 git repo 裡放一份本 repo 的 `.gitignore`、把那一行的前導 `/`
拿掉，同四條路徑必須恰有 3 條（三個子目錄路徑）與期望不符。抓不到就表示這支測試
對「錨定被拿掉」沒有鑑別力，自報並 exit 1——正向過了也不算數。
"""
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
    """環境問題：git 回了 0／1 以外的狀態碼。"""


def check_ignore(cwd, path):
    """`git check-ignore -q --no-index -- <path>` 的 rc；0／1 以外一律當跑不起來。"""
    p = subprocess.run(["git", "check-ignore", "-q", "--no-index", "--", path],
                       cwd=str(cwd), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if p.returncode not in (0, 1):
        raise CannotRun("git check-ignore %s 在 %s 回 %d：%s"
                        % (path, cwd, p.returncode, p.stderr.decode("utf-8", "replace").strip()))
    return p.returncode


def run_cases(cwd):
    """回傳 [(路徑, 期望 rc, 實得 rc)]。"""
    return [(path, want, check_ignore(cwd, path)) for path, want in CASES]


def unanchor(text):
    """把 `/.devflow-local` 那一行的前導 `/` 拿掉；回傳 (新文字, 動到的行號)，找不到行號為 None。"""
    lines = text.split("\n")
    for n, line in enumerate(lines):
        if line.strip() in ("/" + RULE, RULE):
            lines[n] = RULE
            return "\n".join(lines), n + 1
    return text, None


def main():
    if not GITIGNORE.exists():
        print("💥 找不到 %s（repo 佈局與本檔假設不符；exit 2，不是內容違規）" % GITIGNORE)
        return 2
    rc = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=str(REPO),
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    if rc != 0:
        print("💥 %s 不是 git 版本庫（exit 2，不是內容違規）" % REPO)
        return 2

    failures = []
    try:
        # 正向：真 repo 的 .gitignore
        print("正向  真 repo 的 .gitignore")
        # 失敗行只印這一次（總結不重複），`grep -c '❌ 真 repo:'` 才等於違規條數。
        for path, want, got in run_cases(REPO):
            ok = got == want
            print("%s 真 repo: %s 期望 rc %d，實得 rc %d" % ("✅" if ok else "❌", path, want, got))
            if not ok:
                failures.append(path)
        print()

        # 負向對照：暫存 repo 裡拿掉錨定，同四條路徑必須恰有 3 條與期望不符
        text, lineno = unanchor(GITIGNORE.read_text(encoding="utf-8"))
        if lineno is None:
            print("負向對照  .gitignore 裡找不到 `%s` 那一行，無從拿掉錨定" % RULE)
            diffs = []
        else:
            with tempfile.TemporaryDirectory() as tmp:
                subprocess.run(["git", "init", "-q", tmp], check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                (Path(tmp) / ".gitignore").write_text(text, encoding="utf-8")
                print("負向對照  暫存 repo，.gitignore 第 %d 行改成 `%s`（拿掉前導 /）" % (lineno, RULE))
                diffs = []
                for path, want, got in run_cases(tmp):
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
    print("gitignore 射程檢查通過：`.devflow-local` 只忽略 repo 根目錄那一份；負向對照有鑑別力")
    return 0


if __name__ == "__main__":
    sys.exit(main())
