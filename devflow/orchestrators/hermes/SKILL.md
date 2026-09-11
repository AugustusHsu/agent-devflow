---
name: devflow-orchestrator
description: "Use when devflow.yml sets orchestrator: hermes"
version: 0.1.0
metadata:
  hermes:
    tags: [devflow, orchestrator, git-worktree, github, code-review, systemd]
---

# devflow orchestrator（Hermes）

本 skill 是 `devflow/WORKFLOW.md` 的流程實作：只寫「做什麼、依哪條規則」，條文本體不複製（`I5`）。
每個步驟標規則 ID 或對照表的格；語意以 issue 上寫的 G（`WORKFLOW.md` 的 commit）為準，skill 與 G 衝突時 G 勝（`G1`、`G5`）。

三張對照表：`devflow/forges/<forge>.md`、`devflow/coders/<coder>.md`、`devflow/orchestrators/hermes.md`。
引用任一格前先看狀態欄：非 `✅` 不得當作可用（第 0 節、`R9`）；`✅` 也要比對 `R10` 所載受測環境，有差異先重驗。

## 一、觸發

- 專案根目錄有 `devflow.yml` 且 `orchestrator: hermes`。
- 開工前讀 `stage`，只套用生效的節（`ST0`～`ST3`）；`ST5` 所列保護節不看 stage、永遠生效；`ST4`：stage 不是權限開關。
- 每個任務固定兩個基準（第 0 節）：G ＝ `WORKFLOW.md` 的 commit sha，T ＝ 規格的 commit sha；以 issue 上寫的為準，不另抄。
- skill 啟用邊界：本檔改動依 `G3` 在下一任務／session 邊界才生效，不默默混用（`hermes.md` 「skill 啟用邊界（`G3`）」格；「session 開始載入」屬該表「已知事實」，待實測）。

## 二、單一任務生命週期

固定序 1→10，不跳步。任一步失敗依第 7 節（F）處置，不自行 bypass（`F3`）。

### 1. 開 issue（`L1`、`I4`）

- 用 `templates/issue.md`；G／T 填 commit sha；write scope 寫路徑 glob；「未決事項」為空。
- `P1` 四欄（write scope、阻塞依賴、共用契約、外部資源）stage < 3 也填，供之後判斷（`P4`）。
- 政策問題（處置會落在 write scope 外、或會改 AC 的）先在 issue 留言裁決再派工，不留給 coder 猜（`L3` 的停路徑判準）。
- 工單只住 forge：repo 內不留副本，orchestrator 不持第二份（`I4`）。

### 2. 建 worktree（`I1`、`I2`、`L2`）

在主 checkout 執行，coder 只收路徑：

```bash
git fetch origin
git branch <N>-<slug> origin/main
git worktree add ../<repo>.worktrees/<N> <N>-<slug>
git worktree list                                   # 含該路徑與分支；主 checkout 那列不動
git -C ../<repo>.worktrees/<N> rev-parse HEAD       # 等於 base sha
```

對照 `hermes.md` 「建 worktree（`I2`）」格、`coders/claude-code.md` 「worktree（`I2`）」格。

### 3. 派 coder（`L2`；`hermes.md` 「派工（`L2`）」格）

以 Hermes `terminal(command="…", background=true)` 啟動，記下回傳的 pid。**不用 `delegate_task`**，不用 `setsid`（見第六節）。

```bash
cd ../<repo>.worktrees/<N> && \
systemd-run --user --scope --unit=coder-<N> --collect -q \
  timeout <秒> claude -p "<prompt>" \
    --output-format json --max-turns <turns> \
    --allowedTools '<白名單>' \
  > <stdout 檔> 2> <stderr 檔> < /dev/null
```

- `systemd-run --scope` 把 coder 及其所有子孫關進專用 cgroup；`--unit` 名稱是中斷把手（`hermes.md` 「中斷交接」格）。
- 白名單以 `hermes.md` 「中斷交接」格所載為底；**不含** `systemd-run`／`systemctl`／`busctl`（可逃出 cgroup）、`gh api`（政策操作）、`git push`（由 orchestrator 代行，步驟 6）。
- 啟動後讀回三項（同格）：`pstree -p <pid> | head -1` 鏈上有 `claude(<coder pid>)`；`tr '\0' ' ' < /proc/<coder pid>/cmdline` 以 `claude -p` 開頭；`readlink /proc/<coder pid>/cwd` 等於 worktree。**不用 `ps | grep 'claude -p'`**（多行 prompt 下不可靠）。
- prompt 必含（`L2`、`L3`）：worktree 路徑、base sha、write scope、G／T、驗證指令、紀律（不 push、不開 PR、工具生成物如 `.serena/` 不 add 不刪——`L3` 末段）、交付格式（含 `L3` 留言）。目標檔超過 20 KB 時明寫先 `grep -n` 定位（`D4`）。
- headless 旗標對照 `coders/claude-code.md` 「headless 執行（`L2`）」格；`--allowedTools` 語意對照同表「權限」格（引用前查狀態，`R9`）。

### 4. coder 撞 `--max-turns`（`coders/claude-code.md` 「交接（`--resume`）」格）

1. 看工作區：`git -C <worktree> status --porcelain`、`git -C <worktree> log --oneline <base>..HEAD`——commit 是否完整、diff 是否乾淨。
2. 取 `session_id`：stdout JSON 的 `session_id`；被 SIGTERM 中斷則無 JSON，改讀 `~/.claude/projects/<cwd 路徑編碼>/` 最新 `.jsonl` 首行 `sessionId`。
3. 重派前確認舊 coder 已停：`systemctl --user is-active coder-<N>.scope` 回 `inactive`——前提是該 scope 曾 `active` 且 `cgroup.procs` 含 coder pid；從未存在的 unit 也回 `inactive`，沒這步的 `inactive` 不算證據（`hermes.md` 「中斷交接」格）。
4. 同一套 `systemd-run` 包裝、同一 OS 使用者：`claude -p "<剩餘步驟＋turn 上限>" --resume <session_id> …`；prompt 明寫「你被中斷過，先讀工作區狀態」。

### 5. 複驗（`R6`、`R8`、`G5`）

- 跑 issue 的驗證指令，貼原始輸出；證據要能定位——`grep -c`／`wc -l` 不得當唯一證據（`R6`）。
- `git -C <worktree> diff --name-only <base>..HEAD` 逐一對 write scope；夾帶 CLAUDE.md／AGENTS.md／skill／CI／`WORKFLOW.md` 者標出——待審產品，不是本次依據（`G5`）。
- coder 的 `L3` 留言逐項判：停（blocked）→ 問人、答案寫回同一 issue、重派；續（工程判斷）→ 接受，或在 PR 留言記處置。
- 動到對照表的格：驗證方式第三者現在可重跑（`R8`）、值欄多項全驗（`R7`）、受測環境四要素齊（`R10`）——細節見第四節。

### 6. push ＋ 開 PR（`L4`、`G1`、`R3`）

coder 白名單不含 `git push`，`L4` 的 push 與開 PR 由 orchestrator 代行：

```bash
git -C ../<repo>.worktrees/<N> push -u origin <N>-<slug>
gh pr create --base main --head <N>-<slug> \
  --title "<gitmoji> <type>(<scope>): <標題>" \
  --body-file <填好的 templates/pr.md>
```

- `templates/pr.md`：`Closes #<N>`、G／T、head sha（每次 push 後更新，`R3`）、AC 對照、驗證輸出、write scope 自查。
- coder 回報的缺口寫進 PR body：缺口 → orchestrator 判定（接受／要求修）。
- 對照 `forges/github.md` 「開 PR」格。

### 7. 派審（`R1`、`R2`、`R4`、`R6`）

fresh context、異廠（coder 為 Claude Code 時用 Codex）、乾淨 checkout：

```bash
git clone <remote> /tmp/review<N> && git -C /tmp/review<N> checkout <head sha>
codex exec -C /tmp/review<N> --sandbox workspace-write \
  -m gpt-5.6-sol -c model_reasoning_effort=<high|xhigh> \
  -o /tmp/review<N>.verdict.md "<review prompt>"
```

prompt 以 `templates/review-prompt.md` 為底，另加：

- 材料：G／T sha、`<base sha>..<head sha>`、write scope、規格來源、驗證指令；不接受作者摘要（`R1`）。
- 「已判通過不重審」清單（前輪 PASS 且該處 diff 未變）與「逐條要判」清單。
- 要求：verdict 開頭 `APPROVE`／`REQUEST_CHANGES`、寫明 head sha（`R3`）、逐條 AC 給可定位證據並試反例（`R4`、`R6`）、一格不通過不阻擋其他格的判定。
- **功能 PR**：審查者自構輸入逐條 AC 找反例，不以 coder 的 harness 輸出為證據（`R4`、`R6`）。
- 對照 `coders/codex.md` 「審查用法（`R1`）」格——引用前查該格狀態（`R9`）；`-m` 的模型名是萃取當時的值，依當下可用模型換。

### 8. verdict 處理（`R3`、`R5`、`F1`、`F2`）

- 完整 verdict 貼成 PR 留言（`R5`；`forges/github.md` 「審查證據（`R3`／`R5`）」格），另一則留摘要表：阻擋 → 處置。
- `REQUEST_CHANGES` 分兩類：
  - 實作阻擋 → coder `--resume` 修（步驟 4 的包裝），同一 issue（`F1`）。
  - T 的漏洞 → 先修規格（`F2`）：小改隨本 PR；大改另開規格 PR，本任務暫停、無關任務繼續。
- head 變更即 verdict 失效（`R3`）；下一輪 prompt 縮窄到變更處＋未通過的 AC。
- `APPROVE` → 步驟 9。

### 9. 合併（`M1`、`M2`、`I3`、`R5`）

`M1` 全部成立才按：測試綠；verdict 的 head sha ＝ 當下 PR head；base 是當下 main——否則 `M3`（merge main 進分支後重測、重審）；無文字衝突不等於無語意衝突（`M4`）。合併者依 `devflow.yml` 的 `merge`（`M2`）。

```bash
gh pr merge <PR-N> --merge \
  --subject "<gitmoji> merge(#<N>): <一句話>" \
  --body "PR #<PR-N>; reviewer <審查者與模型>; head <head sha>
M2: <誰按、依據什麼授權>"
```

gitmoji 依變更性質選，不固定 🔀。對照 `forges/github.md` 「合併（`I3`）」格（`--match-head-commit <head sha>` 可機械綁定 `R3`，但不在該格實測範圍內）。

### 10. 收尾（`C1`～`C4`、`F4`）

`C1` 七步順序，每步判準成立才進下一步：

```bash
git fetch origin main
git merge-base --is-ancestor <head sha> origin/main     # (1) exit 0
systemctl --user is-active coder-<N>.scope               # (2) inactive；仍 active → systemctl --user kill --signal=TERM coder-<N>.scope
git -C ../<repo>.worktrees/<N> status --porcelain        # (3) 空，或確認無需保留
git worktree remove ../<repo>.worktrees/<N>              # (4)
git branch -d <N>-<slug>                                 # (5) 永不 -D
git ls-remote --heads origin <N>-<slug>                  # (6) 空則跳過；非空依 C1 驗 ancestor 後 push --delete
git ls-remote --heads origin <N>-<slug>                  # (7) 空＝成功
gh issue view <N> --json state                           # C2：CLOSED；forge 自動關閉也要讀回
```

- (2) 的判定依 `hermes.md` 「中斷交接」格：scope 曾承載 coder 才算數。
- 只清本任務的資源（`C3`）；「`worktree list` 只剩主目錄」是判準不是命令（`C4`）。
- 合併成功但收尾失敗 → 記 cleanup pending，只補收尾、不重做合併（`F4`）。
- 對照 `forges/github.md` 「已合併訊號（`C1`）」「合併後刪分支（`C1`）」格。

## 三、輪次紀律（`F1`、`R3`、`R5`）

- 每單審查輪次上限由人定，寫進 issue；同一阻擋連續兩輪未收斂、或審查者推翻自己前一輪 → 停損，記 issue 升級到人（`F1`：升級不等於放行）。
- 審查 reasoning：首輪 `xhigh`／`high`；後續範圍縮窄可降 `medium`／`low`。
- 每輪 PR 留言兩則：verdict 摘要表（阻擋 → 處置）＋完整 verdict（`R5`）。

## 四、對照表結帳（`R7`～`R10`）

任務本身就是測試，證據鏈固定四段：

1. 啟動前留言：`git worktree list`、worktree HEAD、完整啟動指令（含 `systemd-run` 包裝）。
2. coder 產物：commit、驗證輸出。
3. orchestrator 貼 stdout JSON 關鍵欄位（`session_id`、`num_turns`、`result` 摘要）。
4. 證據 URL 以 `gh api repos/<owner>/<repo>/issues/comments/<id>` 讀回確認存在。

每格必須：驗證方式第三者現在可照做（`R8`，前瞻讀法）；值欄多項全驗，部分驗證就拆列或逐項標（`R7`）；`R10` 四要素——日期、工具版本、執行身分、目標 repo／環境；狀態欄三值之一（`R9`），`📝` 不足以支持派工決策。

證據陷阱（`R8`「一次性條件」）：

- `.comments[-1]` 只在「最後一則就是那則」時成立——用留言 id 讀回。
- `createdAt == updatedAt` 在 issue close 後失效——改看 `lastEditedAt: null`。
- 驗證用 PR 永久留在 `--state all`——會留垃圾的驗證改在可丟棄 repo 做。
- `pgrep -P <pid>` 不證無殘留（reparent 後漏看）——用 cgroup：`systemctl --user is-active`、`cgroup.events` 的 `populated 0`。

## 五、規則改自己（`G2`）

`WORKFLOW.md`、模板、對照表、本 skill 都是實作，normative 變更走第 2 節：

1. 提案 issue：問題／案例／候選條文／建議，人逐項裁——裁決寫回 issue（`L3`）。
2. 實作單 → worktree → PR，同第二節。
3. **審查依舊 G**（`G2`）：prompt 明寫 `git show <舊 G sha>:devflow/WORKFLOW.md` 為依據；候選版本不得放寬對自己的審查。
4. 版本位數由審查者依舊 `V2` 判（`V1` 進位、`V3` normative／editorial）；候選規格不能自我分類。
5. 合併後依 `G3`：下一任務起用新 G，進行中的續用舊 G；新版修安全缺陷才明確暫停遷移。
6. 入口區塊三處同步（`D2`、`I5`）：`templates/entry-block.md` 為源，CLAUDE.md／AGENTS.md 是產物——`python3 devflow/install.py . --dry-run` 驗，不手抄。
7. 新規則要求的檢查器尚不存在 → 先列「建議」（`G4`，依 `ST2` 啟用）。

## 六、無人值守

- 事先授權範圍由人寫進 issue 或授權檔，逐項列：`APPROVE` 即按合併（`M2`；仍逐項驗 `M1`）、輪次上限（第三節）、停止條件、Codex 額度撞到時 sleep 到恢復再派。
- 每步邊界（派工、撞 turns、verdict、合併、收尾）在 issue 留狀態——issue 留言是持久紀錄（`L3`）。
- forge 回錯或逾時 → 標「結果未定」，讀回 PR 狀態、head sha、CI、分支後再決定；不盲目重送、不 bypass（`F3`）。
- Codex 額度撞到：一次性 cron 於恢復時間重派＋watchdog 每 3 分鐘看 verdict 檔是否落地。Claude 額度撞到：Hermes 自身靜默，人隔日看 issue 接手。
- 全用 Hermes 追蹤的 background 進程（`terminal(background=true)` ＋ `systemd-run --scope`）；不用 `setsid`——會無聲死亡且無法讀回。

## 七、已知陷阱

- 引用不生效的規則——先查 `ST` 表：例如 `G3` 依 `ST5` 永遠生效，`G4` 是 `ST5` 的例外、要 `ST2` 才生效；引用前確認該條在此 stage 是否生效。
- commit body 不能代替 issue 上的裁決（`L3`：issue 留言是持久紀錄）。
- 計數用 `grep -c` 會算進圖例句；用相同方法互驗等於沒驗（`R6`、`R8`）。
- 改大檔（如 800+ 行內嵌 Python 的 CI workflow）的 coder 易撞 max-turns——prompt 明寫 `D4` 先 `grep -n` 定位。
- `ps | grep 'claude -p'` 對多行 prompt 不可靠——用 `pstree -p`／`/proc/<pid>/cmdline`（`hermes.md` 「派工（`L2`）」格）。
- `systemctl --user is-active <unit>.scope` 對從未存在的 unit 也回 `inactive`——先證 scope 曾 `active`（`hermes.md` 「中斷交接」格）。
- 對照表引用行號會漂移——引用格用「面向」名稱，不用 `file:line`。
