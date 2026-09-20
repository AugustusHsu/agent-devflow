# coder: codex

衍生值對照表。分節與狀態欄依 `R9`：**通用**節的值欄宣稱可重用的工具能力或程序（repo 與環境只是可替換的參數），**本機**節的值欄宣稱具名的環境 instance（本機安裝的工具、帳號或組織、本 repo 的設定與資源）；狀態取 `✅`／`📝`／`⬜` 三值之一，兩節的 `✅` 判準各依 `R9` 定義，非 `✅` 不得在流程中當作可用。「職位」欄記該格是哪個職位的用法（詞彙見 `seats/`），`—` 表示是工具或資源本身的性質，不專屬任一職位。

## 通用

| 面向 | 職位 | 值 | 狀態 |
|---|---|---|---|
| headless 執行（`L2`） | implementer | `codex exec -C <worktree> --sandbox workspace-write "<prompt>"`；`--json` 取事件、`-o <file>` 取最後訊息；不需 PTY | ⬜ 未測（不在 #106 範圍：需 Codex 以 implementer 角色實跑；本 repo 至 `332ab9d` 止 Codex 只擔任 reviewer，見 #106） |
| 入口檔（`D2`） | — | `AGENTS.md` | ⬜ 未測 |
| 權限 | — | `--sandbox read-only\|workspace-write` 的隔離**依賴 host 能建 user namespace**（Codex 的 Linux 沙箱用 bubblewrap 實作）；建不起來時 Codex 不拒絕執行、也不停下診斷，而是印 `warning: Codex's Linux sandbox uses bubblewrap and needs access to create user namespaces.` 後**照跑，等同 `danger-full-access`**；`workspace-write` 模式連這行 warning 都不印，靜默無隔離 | 📝 已宣稱（`R9` 的「驗證未達 `✅`」那一種：本格附有第三者現在能執行的驗證方式，重跑結果與「沙箱隔離成立」不符。驗證方式：對乾淨 `/tmp` checkout 執行 `codex exec --sandbox read-only --skip-git-repo-check -o <out> - < <probe.txt>`，probe prompt 依序要求 (1) 讀一個檔 (2) 跑 `git log` (3) 寫 checkout **外**一檔 (4) 寫 checkout **內**一檔，並對 (3)(4) 各跑一次 `ls -l` 回報；隔離成立則 (3)(4) 應被拒且兩檔不存在。orchestrator 於 `332ab9d` 實跑：四步全 `ok`，`/tmp/ro106-probe.txt` 與 `/tmp/ro106/PROBE.md` 皆真的落地——**隔離不成立**。受測環境：2026-09-20，`codex-cli 0.149.1`、模型 `gpt-5.6-sol`／reasoning low、`bwrap 0.9.0`；執行身分為本機使用者以 Codex 訂閱登入；目標 repo `AugustusHsu/agent-devflow` 於 `332ab9d` 的 `/tmp/ro106` clone。同一 host 直接跑 `bwrap` 即失敗：`setting up uid map: Permission denied`／`loopback: Failed RTM_NEWADDR: Operation not permitted`，故該 host 上兩模式皆無隔離。**要讓沙箱真的生效須改 host 的 user namespace 設定（`kernel.unprivileged_userns_clone` 或 AppArmor 限制），那是另一張單，本單不做。** 證據：https://github.com/AugustusHsu/agent-devflow/issues/106#issuecomment-5748372216） |
| worktree（`I2`） | coordinator（建）／implementer（不自建） | 由 orchestrator 建 | ⬜ 未測（不在 #106 範圍：需 Codex 以 implementer 角色實跑；本 repo 至 `332ab9d` 止 Codex 只擔任 reviewer，見 #106） |
| HITL（`L3`） | implementer | headless 無互動 → issue 留言後停 | ⬜ 未測（不在 #106 範圍：需 Codex 以 implementer 角色實跑；本 repo 至 `332ab9d` 止 Codex 只擔任 reviewer，見 #106） |
| 審查用法（`R1`） | reviewer | 於乾淨 checkout 執行 `codex exec -m <model> -c model_reasoning_effort=<level> --sandbox workspace-write --skip-git-repo-check -o <verdict.md> - < <prompt.txt>`；末尾的 `-` 表 prompt 由 **stdin** 餵入。checkout 以 `git clone --shared` 到 `/tmp`、`git remote set-url origin <https URL>`（否則 `gh` 失效）、`git checkout <head sha>` 備妥；`--skip-git-repo-check` 為必要（`/tmp` 目錄不在信任清單） | ⬜ 未測（值欄依 `R7` 改寫成實際跑過的形式——原值欄並列的 `codex exec review` 只有一種有證據，已拆成下一列。本列的證據待 #106 第二輪送審時實跑補上） |
| 審查用法：`review` 子命令（`R1`） | reviewer | `codex exec review`——Codex 內建的 code review 子命令 | ⬜ 未測（子命令存在已驗：`codex exec --help` 於 `codex-cli 0.149.1` 列出 `review  Run a code review against the current repository`。但**未驗證**它能否讀自訂 review prompt、能否輸出到指定檔；本 repo 至 `332ab9d` 止從未用過。依 `R7` 與上一列拆開各自標狀態，不共格，見 #106 AC-1） |
| 交接 | implementer（context 延續）／coordinator（重派） | `codex exec resume <id>` | ⬜ 未測 |

## 本機

| 面向 | 職位 | 值 | 狀態 |
|---|---|---|---|
| 版本 | — | 本機 0.149.1 | ✅ 可用（實測 2026-09-20，驗證方式：在本機 shell 執行 `codex --version`，stdout 恰一行 `codex-cli 0.149.1`。受測環境：2026-09-20，受測工具即 `codex-cli 0.149.1`（由 implementer 在 worktree `agent-devflow.worktrees/106` 的 shell 執行），執行身分為本機使用者以 Codex 訂閱登入（非 API key），目標 repo `AugustusHsu/agent-devflow`；受測對象是**本機 CLI 環境**，與 repo 內容無關——換機器或 Codex 升版後此格依 `R10` 須重驗。本格原狀態欄寫「記錄」而非 `R9` 三值，#106 前先降為 `⬜ 未測`，今補驗後升 `✅`） |
