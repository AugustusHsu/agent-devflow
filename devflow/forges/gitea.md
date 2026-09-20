# forge: gitea

衍生值對照表，**只有通用節**（值欄宣稱可重用的工具能力或程序，repo 與環境只是可替換的參數）。本機節——具名的環境 instance——住 `devflow.local/<同路徑>`，不隨 kit 安裝。分節與狀態欄依 `R9`。
本 repo 沒有 Gitea 實例；Augustus 2026-09-21 裁決先立骨架、後續有實例再逐格實測。**全表 ⬜**：值欄是依 Gitea API v1 文件推導的候選寫法，依 `R8` 不構成任何狀態；有實例前不得引用為可用。

## 通用

| 面向 | 職位 | 值 | 狀態 |
|---|---|---|---|
| 審查載體 | — | Pull Request（Gitea 沿用 GitHub 的名稱與大致形狀） | ⬜ 未測 |
| CLI | — | `tea` 或 `curl` REST `/api/v1` | ⬜ 未測 |
| issue_ref | — | repo 內 `index`（`#N`），API 路徑用 `index` | ⬜ 未測 |
| 建 issue／留言／label | implementer／coordinator／approver | `POST /repos/{owner}/{repo}/issues`、`/issues/{index}/comments`、`POST /issues/{index}/labels`（增量；`PUT` 是全量，不用） | ⬜ 未測 |
| 標準 label | — | 導入的 Gitea repo 須建的 label：`spec`、`process`、`bypass`、`blocked` | ⬜ 未測 |
| 從 issue 開分支 | coordinator | `POST /repos/{owner}/{repo}/branches`（body `new_branch_name`、`old_branch_name=main`） | ⬜ 未測 |
| 分支保護 | — | 導入的 Gitea repo 的 main 應設 branch protection：push 限 whitelist、`enable_merge_whitelist`、禁 force push；repo 設定 merge style 只留 merge commit | ⬜ 未測 |
| tag 保護 | — | 導入的 Gitea repo 應設 protected tags（`POST /repos/{owner}/{repo}/tags/protection`，1.20+） | ⬜ 未測 |
| 開 PR | implementer／coordinator（代行） | `POST /repos/{owner}/{repo}/pulls` | ⬜ 未測 |
| 審查證據（`R3`／`R5`） | reviewer | `POST /pulls/{index}/reviews`（`event=COMMENT`），verdict 含 head sha | ⬜ 未測 |
| 合併（`I3`） | approver／coordinator（`M2`） | `POST /pulls/{index}/merge`（`Do=merge`） | ⬜ 未測 |
| 已合併訊號（`C1`） | coordinator | `GET /pulls/{index}`（`merged=true`、`merge_commit_sha`）＋ `git merge-base --is-ancestor` | ⬜ 未測 |
| 合併後刪分支（`C1`） | coordinator | 合併 body `delete_branch_after_merge=true`；`git ls-remote --heads` 驗 | ⬜ 未測 |
| CI 位置 | — | Gitea Actions `.gitea/workflows/`（需實例啟用 Actions 與 runner）；或外接 CI | ⬜ 未測 |
| 人類站（`D3`） | — | Gitea 無內建 Pages；靠外部靜態站或反向代理 | ⬜ 未測 |
| 故障退路（`F3`） | coordinator | 未知；有實例後依 `F3` 演練 | ⬜ 未測 |

## 已知限制（文件推導，待實測）

- API 形狀接近 GitHub 但不相同：review 的 `event` 值域、merge 的 `Do` 參數、label 增量端點都與 GitHub 有差，不得把 `github.md` 的格直接類推為 ✅（`R8`）。
- 版本差異大：protected tags、Actions 依實例版本而定；有實例後先記版本再填格（`R10`）。
