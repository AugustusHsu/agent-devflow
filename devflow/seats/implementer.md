# seat: implementer（實作位）

職位定義。只寫這個位要做什麼、受哪些規則約束、填它的人或工具要會什麼。不指定填哪個工具，也不記工具的指令；前者是綁定、後者住對照表。

## 職責

- 在指定的 worktree 內，依 issue 上寫的 G、T、AC 與 write scope 完成實作（`L2`）。
- 遇未決事項依 `L3` 分兩路徑：命中停的判準即 issue 留言後停；未命中者為工程判斷，issue 留言記錄情況、暫定處置、位置後繼續。不猜。
- 完成：測試綠 → push 分支 → 開 PR，引用 issue、G、T、head sha（`L4`）。push 與開 PR 可由本位或協調位執行，`L4` 只定義結果。
- 審查未過（`F1`）：在同一 issue 修正；head 變更後原 verdict 失效，重新受審（`R3`）。

## 產出物

分支上的 commit、PR、issue 留言（`L3` 的持久紀錄）。

## 禁止

- 不在主 checkout 工作；不自建 worktree，只收路徑（`I2`）。
- 不動 write scope 外的東西、不改 issue 明列的 AC（`L3`）。
- 工作區內出現非本任務產生的檔案或工具生成物：回報，不自行 add、不自行刪除（`L3`）。
- 不對自己的工作簽正式 verdict（`R1`）。
- 不自行 bypass（`F3`、`B1`）。

## context 語意

延續：同一任務內跨輪保留脈絡——修正輪（`F1`）、中斷後續接。

## 規則義務

`I1`、`I2`、`L2`、`L3`、`L4`、`F1`、`R1`（末句）、`R3`。

## 填充者須具備的能力

- 在給定路徑的 worktree 內工作；不需要、也不得自己建 worktree。
- 執行 issue 上的驗證指令與測試。
- 在 forge 的 issue 上留言（`L3` 的通道），停下時能以可辨識的方式回報 blocked。
- commit。push 與開 PR 若由本位執行，須具備對應的 forge 權限。
- 中斷後能續接同一脈絡（context 語意）。
