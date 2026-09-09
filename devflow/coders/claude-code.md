# coder: claude-code

衍生值對照表。每格狀態：`✅ 實測 <日期>` 並附驗證方式，或 `⬜ 未實測`。

| 面向 | 值 | 狀態 |
|---|---|---|
| headless 執行（`L2`） | 在 worktree 內：`claude -p "<prompt>" --output-format json --max-turns <N>`；prompt 含 issue、G、T、驗證指令 | ⬜ 未實測（PR #2 的 coder1 記錄為 `claude -p "$(cat /tmp/coder1.txt)" --output-format json --max-turns 25`，產出 commit `6eb62d4`。但原始 prompt、CLI stdout 與 terminal transcript 均未留存，該 commit 不足以證明那次確以完整值欄參數執行。補測：把該次呼叫的 `--output-format json` stdout 貼進 PR／issue） |
| 入口檔（`D2`） | `CLAUDE.md` | ⬜ 未實測（coder1 的行為確實符合 devflow 區塊要求——未進主 checkout、單一 commit、gitmoji ＋繁中標題——但派工 prompt 同時載明這些要求，行為符合無法區分來源是 `CLAUDE.md` 還是 prompt，依 `R8` 視同未測。補測方式：放一項只寫在 `CLAUDE.md`、不寫進 prompt 的可觀察約定，看 coder 是否遵守） |
| 權限 | `--allowedTools`（已驗證）／`--permission-mode`（未測）；持憑證的環境不用 `--dangerously-skip-permissions`（已驗證：全程未用） | ⬜ 未實測（`--allowedTools` 部分已於 2026-09-09 驗證：coder1 以白名單 `--allowedTools 'Read,Edit,Bash(git add *),Bash(git commit *),Bash(git diff *),Bash(git log *),Bash(git status *),Bash(grep *),Bash(cat *)'` 啟動，全程未用 `--dangerously-skip-permissions`。`--permission-mode` 從未帶過，依 `R7` 全格取最保守者） |
| worktree（`I2`） | 由 orchestrator 建；不用 `claude -w`（它建在 repo 內的 `.claude/worktrees/`） | ⬜ 未實測（PR #2 記錄為 orchestrator 以 `git branch` ＋ `git worktree add ../agent-devflow.worktrees/1` 建立、coder 只收路徑。但該 worktree 已於收尾移除，相同 commit 也可能出自其他 checkout，「由誰建立」與「未用 `claude -w`」都無從核對。補測：建立當下把 `git worktree list` 輸出與 coder 啟動指令貼進 issue） |
| HITL（`L3`） | headless 無互動 → issue 留言後停 | ⬜ 未實測（`L3` 的「issue 留言 ＋ 停下（blocked）」在 forge 內無紀錄可查：issue #1 上沒有 blocked 留言，PR #2 的分支以 commit `6eb62d4` 走完並合併。repo 內可核對的是另一件事——write scope 紀律：工具生成的 `.serena/` 未進版控） |
| 審查用法（`R1`） | fresh context：`gh pr diff <N> \| claude -p "<review-prompt>"`，或在乾淨 checkout 執行 | ⬜ 未實測 |
| 交接 | `--output-format json` 回 `session_id`，可 `--resume`（曾操作，但證據未達 `R8`）；同目錄 `--continue`（未測） | ⬜ 未實測（issue #4 首輪回 `session_id` `c5014a9f-ec42-41a7-9e57-74436b1be4c2`，orchestrator 以 `--resume` 接續同一 session 完成修正輪。但該 session_id 只存在於本機 session 狀態、commit 訊息與本表自身，repo／forge 內無 JSON stdout 或 transcript 可供第三者核對，依 `R8` 不成立——同樣兩個 commit 由 fresh session 或人工修改也能產生；`--continue` 則完全未測，依 `R7` 全格取最保守者。補測方式：把兩次呼叫的 `--output-format json` stdout 貼進 PR／issue，使「兩次回傳同一 session_id」成為 forge 內可查的產物） |
| 版本 | 本機 2.1.263 | 記錄 |
