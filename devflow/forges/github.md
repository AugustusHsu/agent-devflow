# forge: github

衍生值對照表。每格狀態：`✅ 實測 <日期>` 並附驗證方式，或 `⬜ 未實測`。未實測的格子不得在流程中當作可用。

| 面向 | 值 | 狀態 |
|---|---|---|
| 審查載體 | Pull Request | ⬜ 未實測 |
| CLI | `gh`（本機 2.97.0） | ⬜ 未實測 |
| 建 issue／留言／label | `gh issue create` ／ `gh issue comment` ／ `gh issue edit --add-label`（增量） | ⬜ 未實測 |
| 標準 label | `spec`、`process`、`bypass`、`blocked` | ✅ 實測 2026-09-09（`gh label list` 列出 spec／process／bypass／blocked） |
| 從 issue 開分支 | `gh issue develop <N> --base main`，分支名 `<N>-<slug>` | ⬜ 未實測 |
| 分支保護 | main：必經 PR、只允許 merge commit、禁 force push、dismiss stale approvals、required approvals 0 | ✅ 實測 2026-09-11（五項逐一讀回，第三者現在照跑即可重現；受測環境：`gh` 對 `AugustusHsu/agent-devflow` 具 admin 權限——protection 端點對非 admin 回 404。第 1、3、4、5 項：`gh api repos/AugustusHsu/agent-devflow/branches/main/protection --jq '{pr: (.required_pull_request_reviews != null), force: .allow_force_pushes.enabled, dismiss: .required_pull_request_reviews.dismiss_stale_reviews, approvals: .required_pull_request_reviews.required_approving_review_count}'` 期望輸出 `{"approvals":0,"dismiss":true,"force":false,"pr":true}`，四鍵依序對應 required approvals 0／dismiss stale approvals／禁 force push／必經 PR。第 2 項：`gh api repos/AugustusHsu/agent-devflow --jq '{merge: .allow_merge_commit, squash: .allow_squash_merge, rebase: .allow_rebase_merge}'` 期望輸出 `{"merge":true,"rebase":false,"squash":false}`＝只允許 merge commit） |
| tag 保護 | rulesets；無法依角色限制建立者 | ⬜ 未實測 |
| 開 PR | `gh pr create --base main --body-file <templates/pr.md 填好>` | ⬜ 未實測 |
| 審查證據（`R3`／`R5`） | `gh pr review <N> --approve\|--request-changes --body`；review 原生綁 commit | ⬜ 未實測 |
| 合併（`I3`） | `gh pr merge <N> --merge --subject "🔀 merge(#N): …" --body "PR #N; reviewer …; head <sha>"`；repo 層：`allow_squash_merge=false`、`allow_rebase_merge=false`、`delete_branch_on_merge=true` | ⬜ 未實測 |
| 已合併訊號（`C1`） | `gh pr view <N> --json state,mergedAt,mergeCommit` ＋ `git merge-base --is-ancestor` | ⬜ 未實測 |
| 合併後刪分支（`C1`） | `gh pr merge --delete-branch` 或 `git push origin --delete <branch>`；`git ls-remote --heads` 驗 | ⬜ 未實測 |
| CI 位置 | `.github/workflows/` | ⬜ 未實測 |
| 人類站（`D3`） | GitHub Pages：`gh-pages` 分支或 Actions 部署 | ⬜ 未實測 |
| 故障退路（`F3`） | — | ⬜ 未實測 |

## 已知限制（文件推導，待實測）

- 同一帳號不能核可自己的 PR；單人 repo 的 required approvals 必須是 0，審查證據靠 review 內容與 head sha，不靠 approval 計數。
- REST `/issues` 會混入 PR，列 issue 時要過濾。
- 公開 repo 預設任何人可送 review；必要時開 code review limits。
