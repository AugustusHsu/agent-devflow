# seat: coordinator（協調位）

職位定義。只寫這個位要做什麼、受哪些規則約束、填它的人或工具要會什麼。不指定填哪個工具，也不記工具的指令；前者是綁定、後者住對照表。

## 職責

確認範圍、固定 G／T、建 worktree、啟動實作位、向人提問、驗證交付、收尾。

- 確認範圍：派工前 issue 具備 `L1` 各欄，「未決事項」為空；第 12 節生效時逐項確認 `P1` 並寫進 issue（`P4`）。
- 固定 G／T：寫進 issue 與 PR（第 0 節、`G1`）。
- 建 worktree：從最新 main 建分支與 worktree 於 `../<repo>.worktrees/<N>`（`I2`、`L2`）。
- 啟動實作位：交付 issue、G、T、worktree 路徑、驗證指令（`L2`）；同一時間一張 issue 只有一個實作者（`I1`）。
- 向人提問：實作位停下時，把問題帶給裁決位，答案寫回 issue，再重派（`L3`）。
- 驗證交付：PR 形狀（`L4`）；派審並把 verdict 帶回 forge（`R1`、`R5`）；合併前提逐項驗（`M1`）；main 前進時 merge main、重測、重審（`M3`、`M4`）。
- 收尾：`C1` 七步依序、`C2` 關 issue 並讀回、`C3` 只清本任務資源、`C4`。
- 失敗路徑：forge 回錯先讀回再決定（`F3`）；收尾失敗記 cleanup pending（`F4`）；取消任務先問人（`L6`）。
- 中斷與重派：確認舊填充者已停、工作區狀態讀回後才重派。

## 產出物

issue 上的 G／T 與裁決寫回、分支、worktree、（代行時）push 與 PR、verdict 的 forge 紀錄、收尾結果。

## 禁止

- 不持有工單的第二份拷貝（`I4`）。
- 不放行未達 `M1` 的合併；只在 `devflow.yml` 的 `merge` 允許且有機械 guard 能驗 `M1` 時才按（`M2`）。
- 不自行 bypass（`F3`）；不用 `-D`（`C1`）；不清其他任務的資源（`C3`）；分支已有 commit 不逕自刪（`L6`）。
- 不代簽 verdict——審查由審查位以全新 context 做（`R1`）。

## context 語意

長駐：跨任務持續。規則版本的切換點是任務／session 邊界（`G3`），此位在邊界重新載入 G。

## 規則義務

`I1`、`I2`、`I4`、`L1`～`L6`、`R1`（派審）、`R5`、`M1`～`M4`、`F3`、`F4`、`C1`～`C4`、`G3`、`P1`、`P4`。

## 填充者

工具或人。沒有工具填此位時，各步由人親自執行；換填充者不改變 issue、分支、worktree、PR 的形狀（`I6`）。

## 填充者須具備的能力

- 在主 checkout 執行 git：建分支與 worktree、`merge-base --is-ancestor`、`worktree remove`、`branch -d`、`ls-remote`、刪遠端分支（`C1`）。
- 操作 forge：開、讀、留言、關 issue；開 PR、讀回 PR 狀態與 CI 結果（`L1`、`L4`、`C2`、`F3`）。
- 啟動與停止實作位的填充者，並能判定它已停（`C1` 第 (2) 步）。
- 啟動審查位的填充者，餵入 `templates/review-prompt.md`（`R1`）。
- 向人提問並等答案（`L3`）；持久紀錄在 issue，提問通道只是通道。
- 長駐，並在任務邊界重新載入 G（`G3`）。
