# forge: gitlab

衍生值對照表。每格狀態：`✅ 實測 <日期>` 並附驗證方式，或 `⬜ 未實測`。未實測的格子不得在流程中當作可用。
本 repo 沒有 GitLab 實例；預定在導入 AI_Server_SuperOD 時實測。

| 面向 | 值 | 狀態 |
|---|---|---|
| 審查載體 | Merge Request | ⬜ 未實測 |
| CLI | `glab`（本機未安裝）或 `curl` REST v4 | ⬜ 未實測 |
| issue_ref | 專案內 `iid`，非全域 `id` | ⬜ 未實測 |
| 建 issue／留言／label | `POST /projects/:id/issues`、`/issues/:iid/notes`、`PUT …?add_labels=`（增量；`labels=` 是全量，不用） | ⬜ 未實測 |
| 標準 label | `spec`、`process`、`bypass`、`blocked` | ⬜ 未實測 |
| 從 issue 開分支 | `POST /repository/branches?branch=<iid>-<slug>&ref=main` | ⬜ 未實測 |
| 分支保護 | main protected：Allowed to push＝Maintainers、force push 關；Merge method＝Merge commit；Squash＝Do not allow；Delete source branch by default 開 | ⬜ 未實測 |
| tag 保護 | protected tags，Allowed to create＝Maintainers | ⬜ 未實測 |
| 開 MR | `POST /merge_requests` | ⬜ 未實測 |
| 審查證據（`R3`／`R5`） | MR note；approval rules 在 Free 可能 403 → verdict 寫在 note 內並含 head sha | ⬜ 未實測 |
| 合併（`I3`） | `PUT /merge_requests/:iid/merge` | ⬜ 未實測 |
| 已合併訊號（`C1`） | `GET /merge_requests/:iid`（`state=merged`、`merge_commit_sha`）＋ `git merge-base --is-ancestor` | ⬜ 未實測 |
| 合併後刪分支（`C1`） | `should_remove_source_branch` 可能不生效 → `git ls-remote --heads` 驗，多的手動刪 | ⬜ 未實測 |
| CI 位置 | `.gitlab-ci.yml` | ⬜ 未實測 |
| 人類站（`D3`） | GitLab Pages（`pages` job 產 `public/`；自架實例需管理員啟用） | ⬜ 未實測 |
| 故障退路（`F3`） | MR 單筆端點回 500 時合併可能已成功：先讀清單端點與目標分支 sha，再決定 | 文件記錄（SuperOD 2026-09-03） |

## 已知限制（文件推導，待實測）

- `done` 與 `cancelled` 在平台層同形，只能靠 label 區分。
- 自架實例的 MR 頁面與單筆 API 曾回 500；導入前重新確認當下能力。
- runner 上的 `origin` 可能指向 GitLab 而本機 `origin` 指向鏡像；canonical remote 必須明確記在專案綁定，不從 remote 名稱推導。
