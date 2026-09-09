# coder: claude-code

衍生值對照表。每格狀態：`✅ 實測 <日期>` 並附驗證方式，或 `⬜ 未實測`。

| 面向 | 值 | 狀態 |
|---|---|---|
| headless 執行（`L2`） | 在 worktree 內：`claude -p "<prompt>" --output-format json --max-turns <N>`；prompt 含 issue、G、T、驗證指令 | ✅ 實測 2026-09-09（PR #2 的 coder1：`claude -p "$(cat /tmp/coder1.txt)" --output-format json --max-turns 25`，在 `../agent-devflow.worktrees/1` 內單次跑完 issue #1 並 commit） |
| 入口檔（`D2`） | `CLAUDE.md` | ✅ 實測 2026-09-09（worktree 內的 `CLAUDE.md` devflow 區塊被自動載入並遵守：未進主 checkout、單一 commit、gitmoji ＋繁中標題） |
| 權限 | `--permission-mode` ／ `--allowedTools`；持憑證的環境不用 `--dangerously-skip-permissions` | ✅ 實測 2026-09-09（coder1 用白名單 `--allowedTools 'Read,Edit,Bash(git add *),Bash(git commit *),Bash(git diff *),Bash(git log *),Bash(git status *),Bash(grep *),Bash(cat *)'`；全程未用 `--dangerously-skip-permissions`，白名單外的指令確實被擋下） |
| worktree（`I2`） | 由 orchestrator 建；不用 `claude -w`（它建在 repo 內的 `.claude/worktrees/`） | ✅ 實測 2026-09-09（worktree 由 orchestrator 以 `git branch` ＋ `git worktree add ../agent-devflow.worktrees/1` 建好，coder 只收路徑；未用 `claude -w`） |
| HITL（`L3`） | headless 無互動 → issue 留言後停 | ✅ 實測 2026-09-09（coder 在工作區遇到非本任務產生的 `.serena/`，未自行 add 或刪除，回報 orchestrator 後停下） |
| 審查用法（`R1`） | fresh context：`gh pr diff <N> \| claude -p "<review-prompt>"`，或在乾淨 checkout 執行 | ⬜ 未實測 |
| 交接 | `--output-format json` 回 `session_id`，可 `--resume`；同目錄 `--continue` | ⬜ 未實測 |
| 版本 | 本機 2.1.263 | 記錄 |
