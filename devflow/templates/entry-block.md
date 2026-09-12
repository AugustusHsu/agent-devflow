<!-- devflow:begin -->
## 開發流程（agent-devflow）

本專案採用 agent-devflow。規則本體：`devflow/WORKFLOW.md`（引用規則用 ID，如 `I2`、`R3`）。
設定：`devflow.yml`（forge / seats / stage / merge）。

- 開工前讀 `devflow.yml` 的 `stage`，只套用該 stage 生效的節（WORKFLOW.md 第 11 節）。
- 每個任務有兩個基準：治理基準 G（WORKFLOW.md 的 commit）與開發目標 T（規格的 commit）；以 issue 上寫的為準。
- coder 不在主 checkout 工作（`I2`）；遇未決事項先在 issue 留言，依 `L3` 的判準停或續，不猜。
- 進 main 一律 PR ＋ merge commit（`I3`）；直推 main 只在 stage 0 或依第 10 節 bypass。
- 對照表在 `devflow/forges/`、`coders/`、`orchestrators/`，未實測的格子不當作可用。
- 超過 20 KB 的檔案先 `grep -n` 定位再局部讀（`D4`）。

本區塊由 agent-devflow 管理；區塊外的內容屬專案自己，安裝與升級不會改動。
<!-- devflow:end -->
