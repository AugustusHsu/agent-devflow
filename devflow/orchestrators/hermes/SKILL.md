---
name: devflow-orchestrator
description: "Use when devflow.yml sets orchestrator: hermes"
version: 0.1.0
metadata:
  hermes:
    tags: [devflow, orchestrator, git-worktree, github, code-review, systemd]
---

# devflow orchestrator（Hermes）

本 skill 是 `devflow/WORKFLOW.md` 的流程實作：只寫「做什麼 → 依哪條規則」，條件內容不複述（`I5`）——要知道條件就翻 `WORKFLOW.md`。
語意以 issue 上寫的 G 為準，skill 與 G 衝突時 G 勝（`G1`、`G5`）。

對照表：`devflow/forges/<forge>.md`、`devflow/coders/<coder>.md`、`devflow/orchestrators/hermes.md`。引用任一格前先看狀態欄（第 0 節、`R9`、`R10`）。

## 一、觸發

- 專案根目錄有 `devflow.yml` 且 `orchestrator: hermes`。
- 開工前讀 `stage`，只套用生效的節（`ST0`～`ST3`）；保護節依 `ST5`；stage 與權限的關係依 `ST4`。
- 每個任務兩個基準 G／T（第 0 節），以 issue 上寫的為準。
- 本檔改動的啟用邊界依 `G3`（`hermes.md` 「skill 啟用邊界（`G3`）」格；「session 開始載入」屬該表「已知事實」，待實測）。

## 二、單一任務生命週期（stage ≥ 1）

固定序 1→10，不跳步；`ST0` 直推 main，不走此流程。任一步失敗依第 7 節（F）處置，不自行 bypass（`F3`）。

### 1. 開 issue（`L1`、`I4`）

- 用 `templates/issue.md`，欄位依 `L1`；G／T 填 commit sha。
- 平行前提四欄 stage < 3 時依 `L1` 填；`P1`／`P4` 的判定 `ST3` 起。
- 命中 `L3` 停判準的政策問題先在 issue 留言裁決，再派工。

### 2. 建 worktree（`I1`、`I2`、`L2`）

主 checkout 執行，coder 只收路徑（`hermes.md` 「建 worktree（`I2`）」格、`coders/claude-code.md` 「worktree（`I2`）」格）：

```bash
git fetch origin && git branch <N>-<slug> origin/main
git worktree add ../<repo>.worktrees/<N> <N>-<slug>
git -C ../<repo>.worktrees/<N> rev-parse HEAD       # 等於 base sha；git worktree list 含該路徑
```

### 3. 派 coder（`L2`；`hermes.md` 「派工（`L2`）」格）

以 Hermes `terminal(command="…", background=true)` 啟動，記下回傳的 pid。**不用 `delegate_task`**，不用 `setsid`（第六節）。

```bash
cd ../<repo>.worktrees/<N> && systemd-run --user --scope --unit=coder-<N> --collect -q \
  timeout <秒> claude -p "<prompt>" --output-format json --max-turns <turns> --allowedTools '<白名單>' \
  > <stdout 檔> 2> <stderr 檔> < /dev/null
```

- `--unit` 名稱是中斷把手；白名單以 `hermes.md` 「中斷交接」格所載為底，**不含** `systemd-run`／`systemctl`／`busctl`、`gh api`、`git push`（push 由 orchestrator 代行，步驟 6）。
- 啟動後依「派工」格讀回三項（`pstree -p`、`/proc/<pid>/cmdline`、`/proc/<pid>/cwd`）；**不用 `ps | grep 'claude -p'`**。headless 旗標對照 `coders/claude-code.md` 「headless 執行（`L2`）」格、「權限」格。
- prompt 必含（`L2`）：worktree 路徑、base sha、write scope、G／T、驗證指令、紀律（不 push、不開 PR、工具生成物依 `L3` 末段）、交付格式（含 `L3` 留言）；大檔明寫 `D4`。

### 4. coder 撞 `--max-turns`（`coders/claude-code.md` 「交接（`--resume`）」格）

1. 看工作區：`git -C <worktree> status --porcelain`、`git -C <worktree> log --oneline <base>..HEAD`。
2. 取 `session_id`：stdout JSON；被 SIGTERM 則依 `hermes.md` 「中斷交接」格從 `~/.claude/projects/<cwd 路徑編碼>/` 取。
3. 確認舊 coder 已停：`systemctl --user is-active coder-<N>.scope`，判定依 `hermes.md` 「中斷交接」格。
4. 同一套 `systemd-run` 包裝、同一 OS 使用者：`claude -p "<剩餘步驟＋turn 上限>" --resume <session_id> …`；prompt 明寫「你被中斷過，先讀工作區狀態」。

### 5. 複驗（`R6`、`G5`）

- 跑 issue 的驗證指令，貼原始輸出；證據可定位性依 `R6`。
- `git -C <worktree> diff --name-only <base>..HEAD` 對 write scope；夾帶物依 `G5` 標出。
- coder 的 `L3` 留言逐項判：停 → 問人、答案寫回同一 issue、重派；續 → 接受，或在 PR 留言記處置。
- 動到對照表的格 → 第四節。

### 6. push ＋ 開 PR（`L4`、`G1`、`R3`）

```bash
git -C ../<repo>.worktrees/<N> push -u origin <N>-<slug>
gh pr create --base main --head <N>-<slug> --title "<gitmoji> <type>(<scope>): <標題>" --body-file <填好的 templates/pr.md>
```

- coder 白名單不含 `git push`，`L4` 的 push 與開 PR 由 orchestrator 代行（`forges/github.md` 「開 PR」格）。
- body 用 `templates/pr.md`；head sha 每次 push 後更新（`R3`）；coder 回報的缺口寫進 body 並附 orchestrator 判定。

### 7. 派審（`R1`、`R2`、`R4`、`R6`）

fresh context、異廠、乾淨 checkout（`coders/codex.md` 「審查用法（`R1`）」格，引用前查狀態 `R9`）：

```bash
git clone <remote> /tmp/review<N> && git -C /tmp/review<N> checkout <head sha>
codex exec -C /tmp/review<N> --sandbox workspace-write -m gpt-5.6-sol -c model_reasoning_effort=<high|xhigh> \
  -o /tmp/review<N>.verdict.md "<review prompt>"
```

prompt 以 `templates/review-prompt.md` 為底，另加：
- 「已判通過不重審」清單（前輪 PASS 且該處 diff 未變）與「逐條要判」清單。
- verdict 開頭 `APPROVE`／`REQUEST_CHANGES`、寫明 head sha（`R3`）；一格不通過不阻擋其他格的判定。
- 功能 PR：審查者自構輸入逐條 AC 找反例，不以 coder 的 harness 輸出為證據（`R4`、`R6`）。
- `-m` 是萃取當時的模型名，依當下可用者換。

### 8. verdict 處理（`R3`、`R5`、`F1`、`F2`）

- 完整 verdict 貼成 PR 留言（`R5`；`forges/github.md` 「審查證據（`R3`／`R5`）」格），另一則留摘要表：阻擋 → 處置。
- `REQUEST_CHANGES` 分兩類：
  - 實作阻擋 → coder `--resume` 修（步驟 4），同一 issue（`F1`）。
  - T 的漏洞 → 受影響任務暫停，依 `F2` 先修規格。stage 1 第 2 節未生效時：spec 改動另開 PR、依 `G2` 審、合併後更新 issue 的 T、影響分析留言、任務續。
- head 變更後重審（`R3`）；下一輪 prompt 縮窄到變更處＋未通過的 AC。
- `APPROVE` → 步驟 9。

### 9. 合併（`M1`～`M4`、`I3`、`R5`）

前提依 `M1` 逐項驗；main 前進依 `M3`、`M4`；合併者依 `M2`。

```bash
gh pr merge <PR-N> --merge --subject "<gitmoji> merge(#<N>): <一句話>" \
  --body "PR #<PR-N>; reviewer <審查者與模型>; head <head sha>
M2: <誰按、依據什麼授權>"
```

gitmoji 依變更性質選。對照 `forges/github.md` 「合併（`I3`）」格（`--match-head-commit <head sha>` 不在該格實測範圍）。

### 10. 收尾（`C1`～`C4`、`F4`）

`C1` 七步照序執行，判準見條文；Hermes 側對應：

- (1) 兩項全驗：`git merge-base --is-ancestor <head sha> origin/main` ＋ `gh pr view <PR-N> --json state,mergedAt,mergeCommit` 讀回 `MERGED`（`forges/github.md` 「已合併訊號（`C1`）」格）。
- (2) coder 已停：`systemctl --user is-active coder-<N>.scope`，判定依 `hermes.md` 「中斷交接」格。
- (6)(7) 依 `forges/github.md` 「合併後刪分支（`C1`）」格。
- `C2`：`gh issue view <N> --json state` 讀回 `CLOSED`。範圍依 `C3`、`C4`；收尾失敗依 `F4`。

## 三、輪次紀律（`F1`、`R3`、`R5`）

- 每單審查輪次上限由人定，寫進 issue；同一阻擋連續兩輪未收斂、或審查者推翻自己前一輪 → 停損，依 `F1` 升級。
- 審查 reasoning：首輪 `xhigh`／`high`；後續範圍縮窄可降 `medium`／`low`。
- 每輪 PR 留言兩則：verdict 摘要表＋完整 verdict（`R5`）。

## 四、對照表結帳（`R7`～`R10`）

格的成立條件依 `R7`、`R8`、`R9`、`R10`。Hermes 側證據鏈：啟動前留言（`git worktree list`、worktree HEAD、完整啟動指令）→ coder 產物（commit、驗證輸出）→ orchestrator 貼 stdout JSON 關鍵欄位（`session_id`、`num_turns`、`result` 摘要）→ 證據 URL 以 `gh api repos/<owner>/<repo>/issues/comments/<id>` 讀回。

`R8` 一次性條件的已知例：`.comments[-1]`（用留言 id）；`createdAt == updatedAt` 在 close 後失效（看 `lastEditedAt: null`）；驗證用 PR 永久留在 `--state all`（改可丟棄 repo）；`pgrep -P` 不證無殘留（用 cgroup）。

## 五、規則改自己（`G2`）

`WORKFLOW.md`、模板、對照表、本 skill 都是實作。流程依 `G2`：規格核准 → 實作 → 依舊 G 審。

- 規格核准：`ST2` 起走第 2 節；stage 1 第 2 節未生效時，提案 issue（問題／案例／候選／建議，人逐項裁）的人類裁決**暫代**規格核准。
- 審查 prompt 明寫 `git show <舊 G sha>:devflow/WORKFLOW.md` 為依據（`G2`）。
- 版本位數依 `V1`～`V3`（依 `ST2`）；stage 1 下 orchestrator 依 `V2` 語意自判位數、審查者依舊 G 核。
- 合併後啟用邊界依 `G3`；檢查器門檻依 `G4`（依 `ST2`）。
- 入口區塊同步依 `D2`、`I5`：`python3 devflow/install.py . --dry-run` 驗。

## 六、無人值守

- 事先授權由人寫進 issue 或授權檔，逐項列：`APPROVE` 即按合併（仍依 `M1`、`M2`）、輪次上限（第三節）、停止條件、Codex 額度撞到時 sleep 到恢復再派。
- 每步邊界（派工、撞 turns、verdict、合併、收尾）在 issue 留狀態（`L3`）。
- forge 回錯或逾時依 `F3`。
- Codex 額度撞到：一次性 cron 於恢復時間重派＋watchdog 每 3 分鐘看 verdict 檔。Claude 額度撞到：Hermes 自身靜默，人隔日看 issue 接手。
- 全用 Hermes 追蹤的 background 進程（`terminal(background=true)` ＋ `systemd-run --scope`）；不用 `setsid`——會無聲死亡且無法讀回。

## 七、已知陷阱

- 引用不生效的規則——先查 `ST` 表（例：`G3` 依 `ST5`、`G4` 依 `ST2`）。
- commit body 不能代替 issue 上的裁決（`L3`）。
- 計數用 `grep -c` 會算進圖例句；用相同方法互驗等於沒驗（`R6`、`R8`）。
- 改大檔（如 800+ 行內嵌 Python 的 CI workflow）的 coder 易撞 max-turns——prompt 明寫 `D4`。
- `ps | grep 'claude -p'` 對多行 prompt 不可靠——用 `pstree -p`／`/proc/<pid>/cmdline`（`hermes.md` 「派工（`L2`）」格）。
- `systemctl --user is-active <unit>.scope` 對從未存在的 unit 也回 `inactive`——先證 scope 曾 `active`（`hermes.md` 「中斷交接」格）。
- 對照表引用行號會漂移——引用格用「面向」名稱，不用 `file:line`。
