# seat: reviewer（審查位）

職位定義。只寫這個位要做什麼、受哪些規則約束、填它的人或工具要會什麼。不指定填哪個工具，也不記工具的指令；前者是綁定、後者住對照表。

## 職責

- 對實作 PR 依 G 審查：拿到 G、T、`base..head`、完整來源、測試指令（`R1`）。
- 逐條 AC 給證據，至少嘗試一個反例；檢查 write scope 是否被超出、是否夾帶 `G5` 所列變更（`R4`）。用 `templates/review-prompt.md`。
- verdict 寫明 head sha（`R3`）；證據住 forge（`R5`）；證據能定位（`R6`）。
- 對照表格子的狀態依 `R7`～`R10` 判。

## 產出物

PR 上的 review／comment：verdict（`APPROVE`／`REQUEST_CHANGES`）、head sha、逐條 AC 證據、反例、write scope 與 `G5` 檢查、驗證指令結果。

## 共同要求（與工具無關）

以下對所有填充者成立；對照表只記各工具怎麼達成，不重述這些要求。

- 全新 context：不帶實作位的脈絡；每次審查（含 `R3` 的重審）都從全新 context 開始（`R1`）。
- 不接受作者摘要當證據；只依材料判斷（`R1`）。
- 不得對自己的工作簽正式 verdict（`R1`）。
- 建議填此位的工具與填實作位的工具異廠；只有一家可用時，用同廠的全新 context（`R2`）。
- 計數式斷言不作任一條 AC 的唯一證據（`R6`）；`📝` 不當任一條 AC 的證據（`R9`）。

## context 語意

必須全新。重用實作位的 context 即失去 `R1` 的獨立性。

## 規則義務

`R1`～`R10`、`G5`；有效 verdict 是合併前提（`M1`）。

## 例外：規格 PR

`S5`：規格 PR 由人審。此位的填充者依任務類型而異——實作 PR 由綁定的填充者，規格 PR 由人——單值綁定表達不了這件事。記為已知例外，不在首版解決。

## 填充者須具備的能力

- 讀取 `base..head` 的完整來源（不只 diff）以及 G、T。
- 執行 issue 上的驗證指令。
- 在 forge 的 PR 上留 review／comment。
- 以全新 context 啟動（例如乾淨 checkout、不帶先前對話的新 session）。
