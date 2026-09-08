# docs/spec — 本 repo 的規格集

每個 feature 一個目錄：`docs/spec/<feature>/spec.md`，用 `devflow/templates/spec.md` 建立。
規則見 `devflow/WORKFLOW.md` 第 2、3 節（`S1`–`S6`、`V1`–`V5`）。

- 版本＝規格 PR 的 merge commit；frontmatter `version` 在同一個 PR 內 bump。
- 任務從 `git diff <上版>..<這版> -- docs/spec/<feature>/` 加影響分析推導（`S3`），不從版本位數推導。
- `devflow/WORKFLOW.md` 自己也是規格（`G2`）；它的變更走同一條路，規格檔放 `docs/spec/workflow/`。

目前為空：`stage: 0` 期間不建版，第一份規格在 Phase 2 建立。
