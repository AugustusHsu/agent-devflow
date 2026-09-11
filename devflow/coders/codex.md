# coder: codex

衍生值對照表。分節與狀態欄依 `R9`：**通用**節的值欄宣稱可重用的工具能力或程序（repo 與環境只是可替換的參數），**本機**節的值欄宣稱具名的環境 instance（本機安裝的工具、帳號或組織、本 repo 的設定與資源）；狀態取 `✅`／`📝`／`⬜` 三值之一，兩節的 `✅` 判準各依 `R9` 定義，非 `✅` 不得在流程中當作可用。「職位」欄記該格是哪個職位的用法（詞彙見 `seats/`），`—` 表示是工具或資源本身的性質，不專屬任一職位。

## 通用

| 面向 | 職位 | 值 | 狀態 |
|---|---|---|---|
| headless 執行（`L2`） | implementer | `codex exec -C <worktree> --sandbox workspace-write "<prompt>"`；`--json` 取事件、`-o <file>` 取最後訊息；不需 PTY | ⬜ 未實測 |
| 入口檔（`D2`） | — | `AGENTS.md` | ⬜ 未實測 |
| 權限 | — | `--sandbox read-only\|workspace-write`；服務環境 bubblewrap 失敗時先診斷，不自動降級到 `danger-full-access` | ⬜ 未實測 |
| worktree（`I2`） | coordinator（建）／implementer（不自建） | 由 orchestrator 建 | ⬜ 未實測 |
| HITL（`L3`） | implementer | headless 無互動 → issue 留言後停 | ⬜ 未實測 |
| 審查用法（`R1`） | reviewer | `codex exec review` 或 `codex exec "<review-prompt>"` 於乾淨 checkout | ⬜ 未實測 |
| 交接 | implementer（context 延續）／coordinator（重派） | `codex exec resume <id>` | ⬜ 未實測 |

## 本機

| 面向 | 職位 | 值 | 狀態 |
|---|---|---|---|
| 版本 | — | 本機 0.149.1 | ⬜ 未實測（原狀態欄寫「記錄」，非 `R9` 三值：無具名來源、無驗證方式，依 `R9` 定義為 `⬜`） |
