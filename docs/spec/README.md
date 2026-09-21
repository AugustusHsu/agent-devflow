# docs/spec — 本 repo 的規格集

每個 feature 一個目錄：`docs/spec/<feature>/spec.md`，用 `devflow/templates/spec.md` 建立。
規則見 `devflow/WORKFLOW.md` 第 2、3 節（`S1`–`S6`、`V1`–`V5`）。

- 版本＝規格 PR 的 merge commit；frontmatter `version` 在同一個 PR 內 bump。
- 任務從 `git diff <上版>..<這版> -- docs/spec/<feature>/` 加影響分析推導（`S3`），不從版本位數推導。
- `devflow/WORKFLOW.md` 自己也是規格（`G2`）；它的變更依序走 issue 記錄問題與人的裁決 → 實作經 PR → 依舊版 G 由 fresh-context 審查後合入，直接改該檔，不另立規格檔。

什麼進這裡、什麼不進：`docs/spec/` 只放開發目標 T（受 `V4` 的版本規則）；派工紀錄、審查處置、實作計畫、審查報告只留在 forge 的 issue／PR（`I4`），不進 repo。
本 kit 只涵蓋收斂期——已經寫得出可驗證 AC 的工作；探索期（還在找問題、還寫不出 AC）在 kit 之外，進 kit 的時點是第一條 AC 寫得出來的時候。

現有兩份規格：`docs/spec/install/spec.md`（入口區塊安裝器）、`docs/spec/kit-install/spec.md`（kit 完整安裝，升級與回復皆為重裝）。
各自的版本以該檔 frontmatter 的 `version` 欄為準，本檔不複述（`I5`）。
