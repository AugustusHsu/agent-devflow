#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/devflow_checks.py 的煙霧測試（issue #82 AC-4）。

從 repo 根執行：

    python3 tests/smoke_devflow_checks.py

不引入任何新相依（只用標準庫 ＋ git ＋ 檢查器自己已經要求的 markdown-it-py／PyYAML）。
**不是** unit test 框架：沒有 discovery、沒有 fixture，就是「造一份輸入、跑檢查器、比 exit code」。

為什麼有這個檔：PR #81 的七輪審查裡，每一輪的驗證都是手工複製 worktree、注入突變、還原，
審查者與 orchestrator 各自實作過一次抽取邏輯、各自出過錯（見 issue #22 的執行方式教訓）。
檢查器抽成獨立腳本後，回歸就只是跑這個檔。

做法：
  1. 把「git add -A 之後會在 repo 裡的檔案」（受版控 ＋ 未忽略的未追蹤檔）複製到一個
     臨時目錄，git init ＋ git add —— 檢查器認的是 `git ls-files`，所以 index 有就夠，
     不必 commit。
  2. 先跑一次**沒有突變**的正向案例，要求 exit 0 且一個 ❌ 都沒有。
  3. 每個關卡至少注入一個「應擋」的突變，要求 exit 1，且輸出裡出現該關卡的訊息。
     每個案例都從乾淨的沙箱重造，突變之間不互相污染。
  4. 另有「突變後仍應通過」的正向案例（PASSING）：證明判準不誤擋正當變更，要求 exit 0 且 0 個 ❌。

正向案例 0 個 ❌ 這件事讓負向案例的 ❌ 有了歸因：乾淨輸入不產生任何 ❌，所以突變後冒出來的
每一條 ❌ 都是該突變造成的。本檔會把每個案例實際冒出的 ❌ 全部印出來，供人核對「exit 1
只能由目標項造成」（README「Phase 1 第三出口的判定方式」條件三）。
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CHECKER = REPO / "scripts" / "devflow_checks.py"

# 沙箱裡當成 head branch 的名字：合 `I1` 的 `<N>-<slug>`，讓正向案例真的跑到 i1 而不是略過。
GOOD_HEAD_REF = "82-extract-checker"


# ── 沙箱 ──────────────────────────────────────────────────────────
def repo_files():
    """git add -A 之後會在 repo 裡的檔案＝受版控 ∪（未追蹤且未被 .gitignore 忽略）。
    用這個而不是單純的 `git ls-files`，是為了讓還沒 commit 的新檔（例如本檔自己）也進沙箱。"""
    p = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        sys.exit("git ls-files 失敗：%s" % p.stderr.decode("utf-8", "replace"))
    return sorted({n.decode("utf-8") for n in p.stdout.split(b"\0") if n})


def make_sandbox(files, dest):
    """把 index 裡的檔案重造到 dest。

    **symlink 必須原樣重建，不能跟隨**：`Path.is_file()` 對 dangling symlink
    回 False（整個被略過），`shutil.copy2` 對活的 symlink 會複製目標內容、
    把 mode 120000 變成 100644。兩者都使沙箱與 index 不等價——PR #81 第五輪
    的 symlink 反例在跟隨式沙箱裡不但重現不出來，還會把正確的檢查器誤判成
    錯誤（審查者 PR #83 第一輪實測：來源 exit 0、沙箱 exit 1）。
    """
    for rel in files:
        src = REPO / rel
        dst = dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():           # mode 120000：照抄 target 字串，不跟隨
            os.symlink(os.readlink(src), dst)
            continue
        if not src.is_file():          # 已刪除但還在 index 的，跳過
            continue
        shutil.copy2(src, dst)
    for args in (["git", "-c", "init.defaultBranch=main", "init", "-q"],
                 ["git", "add", "-A"]):
        p = subprocess.run(args, cwd=dest, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
        if p.returncode != 0:
            sys.exit("沙箱建置失敗（%s）：%s"
                     % (" ".join(args), p.stdout.decode("utf-8", "replace")))


# ── 突變工具 ──────────────────────────────────────────────────────
def edit(root, rel, fn):
    path = root / rel
    text = path.read_text(encoding="utf-8")
    new = fn(text)
    if new == text:
        sys.exit("突變沒有改到任何東西：%s（檔案內容和本測試的假設不符）" % rel)
    path.write_text(new, encoding="utf-8")


def remove(root, rel):
    """從沙箱的 index 與工作樹一起刪掉。檢查器認的是 `git ls-files`，只刪工作樹等於沒刪。
    沙箱沒有 commit，index 相對 HEAD 全是新檔，`git rm` 不加 `-f` 會拒絕。"""
    if not (root / rel).is_file():
        sys.exit("要刪的檔案不存在：%s（repo 內容和本測試的假設不符）" % rel)
    p = subprocess.run(["git", "rm", "-q", "-f", "--", rel], cwd=root,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if p.returncode != 0:
        sys.exit("git rm %s 失敗：%s" % (rel, p.stdout.decode("utf-8", "replace")))


def drop_line(text, needle):
    return "\n".join(l for l in text.split("\n") if needle not in l)


def replace_first(text, old, new):
    return text.replace(old, new, 1)


def append(text, extra):
    return text + extra


def mut_d2(root):
    """入口區塊只剩 begin，沒有 end。"""
    edit(root, "CLAUDE.md", lambda t: drop_line(t, "<!-- devflow:end -->"))


def mut_i5(root):
    """devflow.yml 的 implementer_filler 投影與 seats.implementer.filler 不一致。"""
    edit(root, "devflow.yml",
         lambda t: replace_first(t, "implementer_filler: claude-code",
                                 "implementer_filler: codex"))


def mut_version(root):
    """規則本體的 frontmatter version 從四碼變三碼。"""
    edit(root, "devflow/WORKFLOW.md",
         lambda t: replace_first(t, "version: 1.3.2.0", "version: 1.3.2"))


def mut_fence(root):
    """留一個沒有關閉的 fenced code block。"""
    edit(root, "README.md", lambda t: append(t, "\n```\n沒有關閉的 fence\n"))


def mut_table(root):
    """對照表表頭缺「面向」欄。"""
    edit(root, "devflow/forges/github.md",
         lambda t: replace_first(t, "| 面向 |", "| 項目 |"))


def mut_link(root):
    """相對連結指向不存在的路徑。"""
    edit(root, "README.md",
         lambda t: append(t, "\n[壞掉的連結](does/not/exist.md)\n"))


def mut_tables_forge(root):
    """刪掉 `forge: github` 指名的 devflow/forges/github.md。"""
    remove(root, "devflow/forges/github.md")


def mut_tables_coder(root):
    """刪掉 `seats.reviewer.filler: codex` 指名的 devflow/coders/codex.md。"""
    remove(root, "devflow/coders/codex.md")


def mut_tables_filler(root):
    """`seats.coordinator.filler` 改成 coders/、orchestrators/ 都沒有對照表的工具名。
    改 coordinator 不改 implementer：後者會連帶讓 i5 ❌，這個案例就不只觸發目標項。"""
    edit(root, "devflow.yml",
         lambda t: replace_first(t, "filler: hermes", "filler: no-such-tool"))


def mut_tables_no_forge(root):
    """devflow.yml 缺 `forge`：推導不出來要擋，不是跳過（issue #87 AC-3）。"""
    edit(root, "devflow.yml", lambda t: drop_line(t, "forge: github"))


def ok_tables_forge_gitlab(root):
    """`forge` 改成 gitlab 後刪 github.md：它不再是必需的。"""
    edit(root, "devflow.yml",
         lambda t: replace_first(t, "forge: github", "forge: gitlab"))
    remove(root, "devflow/forges/github.md")


def ok_tables_coordinator_omitted(root):
    """整個省略 `coordinator`（第 0 節：＝human）後刪 hermes.md：它不再是必需的。"""
    edit(root, "devflow.yml",
         lambda t: drop_line(drop_line(t, "filler: hermes"), "  coordinator:"))
    remove(root, "devflow/orchestrators/hermes.md")


# 「應擋」案例：每個關卡至少一個。
#   name    = 案例名（印出用；同一關卡有多個案例時以 `關卡:說明` 區分）
#   gate    = 目標關卡，以 DEVFLOW_GATE_<KEY>=1 打開
#   mutate  = 怎麼把輸入弄壞（None＝不改檔案，只靠環境變數）
#   env     = 疊在基準環境上的額外變數
#   expect  = 輸出裡必須出現的訊息片段，用來確認擋下來的是**這一項**而不是別的
CASES = [
    ("d2", "d2", mut_d2, {}, "的 devflow 區塊沒有關閉"),
    ("i1", "i1", None, {"GITHUB_HEAD_REF": "no-issue-number"},
     "不合 I1 的 `<N>-<slug>`"),
    ("i5", "i5", mut_i5, {}, "投影與來源不一致"),
    ("version", "version", mut_version, {}, "不是四碼 a.b.c.d"),
    ("fence", "fence", mut_fence, {}, "的 fenced code block 沒有關閉"),
    ("tables:rm-forge", "tables", mut_tables_forge, {}, "指名的對照表不在版控內"),
    ("tables:rm-coder", "tables", mut_tables_coder, {}, "指名的對照表不在版控內"),
    ("tables:no-such-tool", "tables", mut_tables_filler, {}, "指名的對照表不在版控內"),
    ("tables:no-forge", "tables", mut_tables_no_forge, {}, "推導不出必需的對照表"),
    ("table", "table", mut_table, {}, "的對照表形狀不合 R9"),
    ("link", "link", mut_link, {}, "有相對連結指向不存在或 repo 之外的路徑"),
]

# 「突變後仍應通過」的正向案例：判準不能誤擋正當變更。
# 目標關卡照樣以 DEVFLOW_GATE_<KEY>=1 打開——就算它日後被降為建議，這裡驗的仍是「當關卡也不擋」。
PASSING = [
    ("tables:forge-gitlab", "tables", ok_tables_forge_gitlab),
    ("tables:no-coordinator", "tables", ok_tables_coordinator_omitted),
]


# ── 執行 ──────────────────────────────────────────────────────────
def run_checker(cwd, gate=None, extra_env=None):
    env = dict(os.environ)
    env.pop("DEVFLOW_GATE_" "", None)
    for k in list(env):
        if k.startswith("DEVFLOW_GATE_"):
            del env[k]
    env["GITHUB_EVENT_NAME"] = "pull_request"
    env["GITHUB_HEAD_REF"] = GOOD_HEAD_REF
    if gate:
        # 環境變數只能加嚴不能放寬：目標項就算日後被改回 advisory，這個案例仍是關卡。
        env["DEVFLOW_GATE_" + gate.upper()] = "1"
    env.update(extra_env or {})
    p = subprocess.run([sys.executable, str(CHECKER)], cwd=cwd, env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def crosses(out):
    """取結尾摘要區塊列出的 ❌。

    檢查器每條失敗會印兩次——發現當下印一次，最後的「必需關卡失敗」摘要再列一次。
    只認摘要那一份，數出來的才是「這次有幾項關卡失敗」。摘要不存在（exit 0）就是空的。"""
    lines = out.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("===== 必需關卡失敗"):
            out_lines = []
            for l in lines[i + 1:]:
                if l.strip().startswith("❌"):
                    out_lines.append(l.strip()[1:].strip())
                elif l.startswith("====="):
                    break
            return out_lines
    return []


def main():
    if not CHECKER.is_file():
        sys.exit("找不到檢查器：%s" % CHECKER)
    files = repo_files()
    failures = []

    with tempfile.TemporaryDirectory(prefix="devflow-smoke-") as tmp:
        pristine = Path(tmp) / "pristine"
        pristine.mkdir()
        make_sandbox(files, pristine)
        print("沙箱：%d 個檔案（受版控 ∪ 未忽略的未追蹤）" % len(files))
        print()

        # 正向：沒有突變，必須 exit 0 且 0 個 ❌。
        code, out = run_checker(pristine)
        marks = crosses(out)
        good = (code == 0 and not marks)
        print("正向  %-22s 通過    exit %d（期望 0）  ❌ %d 條  %s"
              % ("乾淨輸入", code, len(marks), "PASS" if good else "FAIL"))
        if not good:
            failures.append("正向案例：exit %d、%d 條 ❌" % (code, len(marks)))
            for m in marks:
                print("        ❌ %s" % m)
        print()

        # 正向：突變後仍應通過，同樣 exit 0 且 0 個 ❌。
        for n, (name, gate, mutate) in enumerate(PASSING):
            work = Path(tmp) / ("pass-%02d" % n)
            shutil.copytree(pristine, work)
            mutate(work)
            code, out = run_checker(work, gate=gate)
            marks = crosses(out)
            good = (code == 0 and not marks)
            print("正向  %-22s 通過    exit %d（期望 0）  ❌ %d 條  %s"
                  % (name, code, len(marks), "PASS" if good else "FAIL"))
            for m in marks:
                print("          ❌ %s" % m)
            if not good:
                failures.append("%s：exit %d（期望 0）、%d 條 ❌" % (name, code, len(marks)))
            shutil.rmtree(work)
            print()

        # 負向：每個關卡至少一個「應擋」案例。
        for n, (name, gate, mutate, extra_env, expect) in enumerate(CASES):
            work = Path(tmp) / ("case-%02d" % n)
            shutil.copytree(pristine, work)
            if mutate:
                mutate(work)
            code, out = run_checker(work, gate=gate, extra_env=extra_env)
            marks = crosses(out)
            hit = any(expect in m for m in marks)
            # exit 1 **只能由目標項造成**（PR #81「Phase 1 第三出口」的條件三）：
            # 只檢查「有沒有命中目標」會讓「目標錯誤 ＋ 別的錯誤」一起通過，
            # 那時 exit 1 證明不了是哪一項擋的（審查者 PR #83 第一輪以故障
            # 替身實測：七案各多一個非目標 ❌，煙霧測試仍印「全部通過」）。
            good = (code == 1 and hit and len(marks) == 1)
            print("負向  %-22s 應擋    exit %d（期望 1）  ❌ %d 條  %s"
                  % (name, code, len(marks), "PASS" if good else "FAIL"))
            for m in marks:
                print("        %s ❌ %s" % ("←" if expect in m else " ", m))
            if not good:
                failures.append(
                    "%s：exit %d（期望 1）%s"
                    % (name, code, "" if hit else "，且輸出裡找不到「%s」" % expect))
            shutil.rmtree(work)
            print()

    print("=" * 60)
    if failures:
        print("煙霧測試失敗（%d 項）：" % len(failures))
        for f in failures:
            print("  - %s" % f)
        return 1
    print("煙霧測試全部通過：%d 個正向 ＋ %d 個應擋案例（涵蓋 %d 個關卡）"
          % (1 + len(PASSING), len(CASES), len({c[1] for c in CASES})))
    return 0


if __name__ == "__main__":
    sys.exit(main())
