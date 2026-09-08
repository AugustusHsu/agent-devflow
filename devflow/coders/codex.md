# coder: codex

衍生值對照表。每格狀態：`✅ 實測 <日期>` 並附驗證方式，或 `⬜ 未實測`。

| 面向 | 值 | 狀態 |
|---|---|---|
| headless 執行（`L2`） | `codex exec -C <worktree> --sandbox workspace-write "<prompt>"`；`--json` 取事件、`-o <file>` 取最後訊息；不需 PTY | ⬜ 未實測 |
| 入口檔（`D2`） | `AGENTS.md` | ⬜ 未實測 |
| 權限 | `--sandbox read-only\|workspace-write`；服務環境 bubblewrap 失敗時先診斷，不自動降級到 `danger-full-access` | ⬜ 未實測 |
| worktree（`I2`） | 由 orchestrator 建 | ⬜ 未實測 |
| HITL（`L3`） | headless 無互動 → issue 留言後停 | ⬜ 未實測 |
| 審查用法（`R1`） | `codex exec review` 或 `codex exec "<review-prompt>"` 於乾淨 checkout | ⬜ 未實測 |
| 交接 | `codex exec resume <id>` | ⬜ 未實測 |
| 版本 | 本機 0.149.1 | 記錄 |
