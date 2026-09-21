# docs/spec — 本 repo 的規格集

每個 feature 一個目錄：`docs/spec/<feature>/spec.md`，用 `devflow/templates/spec.md` 建立。
規則見 `devflow/WORKFLOW.md` 第 2、3 節（`S1`–`S6`、`V1`–`V5`）。

- 版本＝規格 PR 的 merge commit；frontmatter `version` 在同一個 PR 內 bump。
- 任務從 `git diff <上版>..<這版> -- docs/spec/<feature>/` 加影響分析推導（`S3`），不從版本位數推導。
- `devflow/WORKFLOW.md` 自己也是規格（`G2`）；它的變更依序走 issue 記錄問題與人的裁決 → 實作經 PR → 依舊版 G 由 fresh-context 審查後合入，直接改該檔，不另立規格檔。

現有兩份規格：`docs/spec/install/spec.md`（入口區塊安裝器）、`docs/spec/kit-install/spec.md`（kit 完整安裝，升級與回復皆為重裝）。
各自的版本以該檔 frontmatter 的 `version` 欄為準，本檔不複述（`I5`）。
