# coder: claude-code

衍生值對照表。每格狀態：`✅ 實測 <日期>` 並附驗證方式，或 `⬜ 未實測`。

| 面向 | 值 | 狀態 |
|---|---|---|
| headless 執行（`L2`） | 在 worktree 內：`claude -p "<prompt>" --output-format json --max-turns <N>`；prompt 含 issue、G、T、驗證指令 | ⬜ 未實測 |
| 入口檔（`D2`） | `CLAUDE.md` | ⬜ 未實測 |
| 權限 | `--permission-mode` ／ `--allowedTools`；持憑證的環境不用 `--dangerously-skip-permissions` | ⬜ 未實測 |
| worktree（`I2`） | 由 orchestrator 建；不用 `claude -w`（它建在 repo 內的 `.claude/worktrees/`） | ⬜ 未實測 |
| HITL（`L3`） | headless 無互動 → issue 留言後停 | ⬜ 未實測 |
| 審查用法（`R1`） | fresh context：`gh pr diff <N> \| claude -p "<review-prompt>"`，或在乾淨 checkout 執行 | ⬜ 未實測 |
| 交接 | `--output-format json` 回 `session_id`，可 `--resume`；同目錄 `--continue` | ⬜ 未實測 |
| 版本 | 本機 2.1.263 | 記錄 |
