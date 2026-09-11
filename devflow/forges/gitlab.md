# forge: gitlab

衍生值對照表。分節與狀態欄依 `R9`：**通用**節的值欄宣稱可重用的工具能力或程序（repo 與環境只是可替換的參數），**本機**節的值欄宣稱具名的環境 instance（本機安裝的工具、帳號或組織、本 repo 的設定與資源）；狀態取 `✅`／`📝`／`⬜` 三值之一，兩節的 `✅` 判準各依 `R9` 定義，非 `✅` 不得在流程中當作可用。「職位」欄記該格是哪個職位的用法（詞彙見 `seats/`），`—` 表示是工具或資源本身的性質，不專屬任一職位。
本 repo 沒有 GitLab 實例；預定在導入 AI_Server_SuperOD 時實測。

## 通用

| 面向 | 職位 | 值 | 狀態 |
|---|---|---|---|
| 審查載體 | — | Merge Request | ⬜ 未實測 |
| CLI | — | `glab` 或 `curl` REST v4 | ⬜ 未實測（依 `R9` 自原「CLI」一格拆出；原值欄的「本機未安裝」是本機 instance 事實，見本機節「CLI（本機 instance）」格） |
| issue_ref | — | 專案內 `iid`，非全域 `id` | ⬜ 未實測 |
| 建 issue／留言／label | implementer／coordinator／approver | `POST /projects/:id/issues`、`/issues/:iid/notes`、`PUT …?add_labels=`（增量；`labels=` 是全量，不用） | ⬜ 未實測 |
| 標準 label | — | 導入的 GitLab 專案須建的 label：`spec`、`process`、`bypass`、`blocked` | ⬜ 未實測（值欄依 `R9` 改寫以表明宣稱對象：本 repo 無 GitLab 實例，本格只能是導入專案應採的設定，不是任一 instance 的現況） |
| 從 issue 開分支 | coordinator | `POST /repository/branches?branch=<iid>-<slug>&ref=main` | ⬜ 未實測 |
| 分支保護 | — | 導入的 GitLab 專案的 main 應設 protected：Allowed to push＝Maintainers、force push 關；Merge method＝Merge commit；Squash＝Do not allow；Delete source branch by default 開 | ⬜ 未實測（值欄依 `R9` 改寫以表明宣稱對象：本 repo 無 GitLab 實例，本格只能是導入專案應採的設定，不是任一 instance 的現況） |
| tag 保護 | — | 導入的 GitLab 專案應設 protected tags，Allowed to create＝Maintainers | ⬜ 未實測（值欄依 `R9` 改寫以表明宣稱對象：本 repo 無 GitLab 實例，本格只能是導入專案應採的設定，不是任一 instance 的現況） |
| 開 MR | implementer／coordinator（代行） | `POST /merge_requests` | ⬜ 未實測 |
| 審查證據（`R3`／`R5`） | reviewer | MR note；approval rules 在 Free 可能 403 → verdict 寫在 note 內並含 head sha | ⬜ 未實測 |
| 合併（`I3`） | approver／coordinator（`M2`） | `PUT /merge_requests/:iid/merge` | ⬜ 未實測 |
| 已合併訊號（`C1`） | coordinator | `GET /merge_requests/:iid`（`state=merged`、`merge_commit_sha`）＋ `git merge-base --is-ancestor` | ⬜ 未實測 |
| 合併後刪分支（`C1`） | coordinator | `should_remove_source_branch` 可能不生效 → `git ls-remote --heads` 驗，多的手動刪 | ⬜ 未實測 |
| CI 位置 | — | `.gitlab-ci.yml` | ⬜ 未實測 |
| 人類站（`D3`） | — | GitLab Pages（`pages` job 產 `public/`；自架實例需管理員啟用） | ⬜ 未實測 |
| 故障退路（`F3`） | coordinator | MR 單筆端點回 500 時合併可能已成功：先讀清單端點與目標分支 sha，再決定 | 📝 已宣稱（無可執行的驗證方式：文件記錄（SuperOD 2026-09-03）——來源具名，但 500 無法由第三者現在按需重現，本格沒有可執行的驗證方式；原狀態欄寫「文件記錄（SuperOD 2026-09-03）」，非 `R9` 三值，依 `R9` 定義改標） |

## 本機

| 面向 | 職位 | 值 | 狀態 |
|---|---|---|---|
| CLI（本機 instance） | — | `glab` 本機未安裝 | ⬜ 未實測（依 `R9` 自原「CLI」一格拆出；「GitLab 的 CLI 是 `glab` 或 `curl` REST v4」見通用節「CLI」格） |

## 已知限制（文件推導，待實測）

- `done` 與 `cancelled` 在平台層同形，只能靠 label 區分。
- 自架實例的 MR 頁面與單筆 API 曾回 500；導入前重新確認當下能力。
- runner 上的 `origin` 可能指向 GitLab 而本機 `origin` 指向鏡像；canonical remote 必須明確記在專案綁定，不從 remote 名稱推導。
