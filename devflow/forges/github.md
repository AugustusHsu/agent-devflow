# forge: github

衍生值對照表。每格狀態：`✅ 實測 <日期>` 並附驗證方式，或 `⬜ 未實測`。未實測的格子不得在流程中當作可用。

| 面向 | 值 | 狀態 |
|---|---|---|
| 審查載體 | Pull Request | ✅ 實測 2026-09-09（PR #2 承載 issue #1 的審查與合併全程。注意：以 `git clone --shared` 從本機建審查 checkout 時 `origin` 指向本機而非 GitHub，`refs/pull/<N>/head` 抓不到，須改 fetch 分支名） |
| CLI | `gh`（本機 2.97.0） | ✅ 實測 2026-09-09（issue #1／#3 建單、PR #2 開單與合併全程以 `gh` 2.97.0 完成） |
| 建 issue／留言／label | `gh issue create` ／ `gh issue comment` ／ `gh issue edit --add-label`（增量） | ✅ 實測 2026-09-09（issue #1、#3 以 `gh issue create --label` 建成，建單當下即帶上 label） |
| 標準 label | `spec`、`process`、`bypass`、`blocked` | ✅ 實測 2026-09-09（`gh label list` 列出 spec／process／bypass／blocked） |
| 從 issue 開分支 | `gh issue develop <N> --base main`，分支名 `<N>-<slug>`。註：PR #2 實際用 `git branch <N>-<slug> origin/main` ＋ `git worktree add` 建分支，`gh issue develop` 本身尚未跑過 | ⬜ 未實測 |
| 分支保護 | main：必經 PR、只允許 merge commit、禁 force push、dismiss stale approvals、required approvals 0 | ✅ 實測 2026-09-09（直推 main 收到 `GH006 Protected branch update failed`） |
| tag 保護 | rulesets；無法依角色限制建立者 | ⬜ 未實測 |
| 開 PR | `gh pr create --base main --body-file <templates/pr.md 填好>` | ✅ 實測 2026-09-09（PR #2 以 `gh pr create --body-file` 開成，正文即填好的 `templates/pr.md`） |
| 審查證據（`R3`／`R5`） | `gh pr review <N> --approve\|--request-changes --body`；review 原生綁 commit | ✅ 實測 2026-09-09（PR #2 兩則 review 原生綁在 `6eb62d4`；`gh pr view 2 --json reviews` 讀得回該 commit oid） |
| 合併（`I3`） | `gh pr merge <N> --merge --subject "🔀 merge(#N): …" --body "PR #N; reviewer …; head <sha>"`；repo 層：`allow_squash_merge=false`、`allow_rebase_merge=false`、`delete_branch_on_merge=true` | ✅ 實測 2026-09-09（`gh pr merge 2 --merge --subject --body` 產生 merge commit `a701527`：兩個父節點 `ce52cf7`／`6eb62d4`，訊息 `PR #2; reviewer codex; head 6eb62d4`。`gh api repos/AugustusHsu/agent-devflow` 讀回 `allow_squash_merge=false`、`allow_rebase_merge=false`、`allow_merge_commit=true`、`delete_branch_on_merge=true`） |
| 已合併訊號（`C1`） | `gh pr view <N> --json state,mergedAt,mergeCommit` ＋ `git merge-base --is-ancestor` | ✅ 實測 2026-09-09（`gh pr view 2 --json state,mergedAt,mergeCommit` 回 merged 與 mergeCommit `a701527`；`git merge-base --is-ancestor 6eb62d4 origin/main` 回 0） |
| 合併後刪分支（`C1`） | `gh pr merge --delete-branch` 或 `git push origin --delete <branch>`；`git ls-remote --heads` 驗 | ✅ 實測 2026-09-09（repo 設定 `delete_branch_on_merge=true` 生效，合併後遠端分支自動移除，未另下刪除指令；`git ls-remote --heads origin` 只剩 `refs/heads/main`） |
| CI 位置 | `.github/workflows/` | ⬜ 未實測 |
| 人類站（`D3`） | GitHub Pages：`gh-pages` 分支或 Actions 部署 | ⬜ 未實測 |
| 故障退路（`F3`） | 標「結果未定」後逐項讀回，再決定重送或收手：`gh pr view <N> --json state,mergedAt,mergeCommit,headRefOid`（PR 狀態與目標 sha）、`gh pr checks <N>`（CI）、`git ls-remote --heads origin`（遠端分支）、`git merge-base --is-ancestor <head> origin/main`（是否其實已合入）。以上單項都在正常流程跑過，但未在 forge 回錯／逾時情境下演練 | ⬜ 未實測 |

## 已知限制（文件推導，待實測）

- 同一帳號不能核可自己的 PR；單人 repo 的 required approvals 必須是 0，審查證據靠 review 內容與 head sha，不靠 approval 計數。
- REST `/issues` 會混入 PR，列 issue 時要過濾。
- 公開 repo 預設任何人可送 review；必要時開 code review limits。
