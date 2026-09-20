# devflow.local/

這個目錄是**你的**，不是 kit 的。安裝與升級 kit 都不會寫入或覆蓋這裡。

## 放什麼

本機驗證留下的證據——只對這台機器、這個 repo、這個帳號成立的事實：

- 工具的本機版本（`gh`／`claude`／`codex` 等 `--version` 讀回的值）
- 這個 repo 在 forge 上的設定（分支保護、合併選項、已建的 label）
- 執行身分（哪個帳號登入、有哪些權限）

`devflow/` 下的對照表只留**通用節**：值欄宣稱可重用的工具能力或程序，repo 與環境
只是可替換的參數。一格的值欄一旦指向具名的 instance（某個版本號、某個 repo、
某個帳號），它就屬於這裡。

## 怎麼放

建議鏡像 `devflow/` 的路徑：`devflow.local/forges/<forge>.md`、
`devflow.local/coders/<coder>.md`、`devflow.local/orchestrators/<orchestrator>.md`；
表頭沿用 `| 面向 | 職位 | 值 | 狀態 |`，狀態取 `R9` 的 `✅`／`📝`／`⬜` 三值。

以上是**建議，不強制**——這裡的格式由你決定。kit 的 CI（`scripts/devflow_checks.py`）
只掃 `devflow/` 下的三個對照表目錄，不掃這裡；這裡的內容靠你自己的審查把關。
