# orchestrator: none

沒有協調平台；協調位（`seats/coordinator.md`）由人填：人自己派工，直接啟動實作位的填充工具。這是預設值（`devflow.yml` 的 `seats.coordinator.filler` 為 `human`，或省略 `coordinator`，即為此）。

衍生值對照表，**只有通用節**（值欄宣稱可重用的工具能力或程序，repo 與環境只是可替換的參數）。本機節——具名的環境 instance——住 `devflow.local/<同路徑>`，不隨 kit 安裝。分節與狀態欄依 `R9`。

## 通用

| 面向 | 職位 | 值 | 狀態 |
|---|---|---|---|
| 派工（`L2`） | coordinator（由人填） | 人建 worktree、起 coder | ⬜ 未測 |
| HITL（`L3`） | coordinator（由人填）／approver | coder 停下後人直接回答並寫回 issue | ⬜ 未測 |
| 平行上限 | coordinator（由人填） | 人自己掌控；`P1` 由人逐項確認 | ⬜ 未測 |
| 流程指令住哪 | coordinator（由人填） | 入口檔區塊指向 `devflow/WORKFLOW.md` | ⬜ 未測 |
| 換 orchestrator（`I6`） | coordinator（由人填） | 由 `none` 切到 `hermes` 不改 repo 內任何非衍生檔 | ⬜ 未測 |
