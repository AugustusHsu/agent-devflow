# orchestrator: none

沒有協調平台；人自己派工，直接開 coder。這是預設值（`devflow.yml` 省略 `orchestrator` 即為此）。

| 面向 | 值 | 狀態 |
|---|---|---|
| 派工（`L2`） | 人建 worktree、起 coder | ⬜ 未實測 |
| HITL（`L3`） | coder 停下後人直接回答並寫回 issue | ⬜ 未實測 |
| 平行上限 | 人自己掌控；`P1` 由人逐項確認 | ⬜ 未實測 |
| 流程指令住哪 | 入口檔區塊指向 `devflow/WORKFLOW.md` | ⬜ 未實測 |
| 換 orchestrator（`I6`） | 由 `none` 切到 `hermes` 不改 repo 內任何非衍生檔 | ⬜ 未實測 |
