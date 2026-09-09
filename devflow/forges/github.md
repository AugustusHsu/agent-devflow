# forge: github

衍生值對照表。每格狀態：`✅ 實測 <日期>` 並附驗證方式，或 `⬜ 未實測`。未實測的格子不得在流程中當作可用。

| 面向 | 值 | 狀態 |
|---|---|---|
| 審查載體 | Pull Request | ✅ 實測 2026-09-09（PR #2 承載 issue #1 的審查與合併全程。注意：以 `git clone --shared` 從本機建審查 checkout 時 `origin` 指向本機而非 GitHub，`refs/pull/<N>/head` 抓不到，須改 fetch 分支名） |
| CLI | `gh`（本機 2.97.0） | ✅ 實測 2026-09-09（issue #1／#3 建單、PR #2 開單與合併全程以 `gh` 2.97.0 完成） |
| 建 issue／留言／label | `gh issue create --label`（已驗證）／`gh issue comment`（未測）／`gh issue edit --add-label` 增量（未測） | ⬜ 未實測（`gh issue create --label` 部分已於 2026-09-09 驗證：issue #1、#3 建單當下即帶上 label。另兩項在 PR #2 期間從未呼叫；它們於 issue #4 執行期間跑過——本 issue 的 AC 修訂留言、#3 轉 tracking 的 comment——但發生在本 PR 開出之後，不列為本次證據，待下一輪結帳。依 `R7` 全格取最保守者） |
| 標準 label | `spec`、`process`、`bypass`、`blocked` | ✅ 實測 2026-09-09（`gh label list` 列出 spec／process／bypass／blocked） |
| 從 issue 開分支 | `gh issue develop <N> --base main`，分支名 `<N>-<slug>`。註：PR #2 實際用 `git branch <N>-<slug> origin/main` ＋ `git worktree add` 建分支，`gh issue develop` 本身尚未跑過 | ⬜ 未實測 |
| 分支保護 | main：必經 PR、只允許 merge commit、禁 force push、dismiss stale approvals、required approvals 0 | ✅ 實測 2026-09-09（五項逐一讀回：`gh api repos/AugustusHsu/agent-devflow/branches/main/protection` 回 `pr_required=true`、`force_push_allowed=false`、`dismiss_stale=true`、`approvals=0`；`gh api repos/AugustusHsu/agent-devflow` 回 `squash=false`、`rebase=false`、`merge_commit=true`＝只允許 merge commit。另有行為證據：直推 main 收到 `GH006 Protected branch update failed`） |
| tag 保護 | rulesets；無法依角色限制建立者 | ⬜ 未實測 |
| 開 PR | `gh pr create --base main --head <branch> --title … --body-file <填好的 templates/pr.md>` | ✅ 實測 2026-09-09（PR #2 實際指令：`gh pr create --base main --head 1-forges-github-phase1 --title … --body-file /tmp/pr1.md`。限制：正文取自填好的 `templates/pr.md`，但此對應關係未經獨立讀回——`gh pr view 2 --body` 與模板的逐行比對尚未做） |
| 審查證據（`R3`／`R5`） | `gh pr review <N> --comment --body`（已驗證）／`--approve`（未測）／`--request-changes`（未測）；review 原生綁 commit（已驗證） | ⬜ 未實測（`gh pr view 2 --json reviews` 讀回 PR #2 兩則 review 的 state 皆為 `COMMENTED`＝`--comment`：chatgpt-codex-connector 一則、AugustusHsu 一則，兩則原生綁在 `6eb62d4`，commit oid 讀得回。「review 綁 commit」這個性質成立，但值欄所列的 `--approve`／`--request-changes` 一個都沒跑過，依 `R7` 全格取最保守者） |
| 合併（`I3`） | `gh pr merge <N> --merge --subject "🔀 merge(#N): …" --body "PR #N; reviewer …; head <sha>"`；repo 層：`allow_squash_merge=false`、`allow_rebase_merge=false`、`delete_branch_on_merge=true` | ✅ 實測 2026-09-09（`gh pr merge 2 --merge --subject --body` 產生 merge commit `a701527`：兩個父節點 `ce52cf7`／`6eb62d4`，訊息 `PR #2; reviewer codex; head 6eb62d4`。`gh api repos/AugustusHsu/agent-devflow` 讀回 `allow_squash_merge=false`、`allow_rebase_merge=false`、`allow_merge_commit=true`、`delete_branch_on_merge=true`） |
| 已合併訊號（`C1`） | `gh pr view <N> --json state,mergedAt,mergeCommit` ＋ `git merge-base --is-ancestor` | ✅ 實測 2026-09-09（`gh pr view 2 --json state,mergedAt,mergeCommit` 回 merged 與 mergeCommit `a701527`；`git merge-base --is-ancestor 6eb62d4 origin/main` 回 0） |
| 合併後刪分支（`C1`）——平台自動 | repo 層 `delete_branch_on_merge=true`，合併時自動刪除來源分支；`git ls-remote --heads origin` 驗證 | ⬜ 未實測（可核對：`gh api repos/AugustusHsu/agent-devflow` 回 `delete_branch_on_merge=true`；PR #2 合併後 timeline 於一秒內記到 `head_ref_deleted`；`git ls-remote --heads origin` 只剩 `refs/heads/main`。不可核對：設定為 true 是狀態，「PR #2 確由它自動刪除」是因果主張——`gh api repos/…/issues/2/timeline` 的 `head_ref_deleted` 事件無欄位可區分平台自動與合併後立即顯式刪除，兩者的 actor、時間差與遠端狀態完全相同。PR #2 事後無從補測；未來可用對照實驗收斂：先設 `delete_branch_on_merge=false` 合併一個 PR 觀察分支留存，再設回 true 合併另一個並全程不下刪除指令，兩個 PR 的 timeline 差異即為 forge 內可查的證據） |
| 合併後刪分支（`C1`）——顯式指令 | 同上目的的替代方法，改由指令刪除：`gh pr merge --delete-branch` ／ `git push origin --delete <branch>` | ⬜ 未實測（PR #2 靠平台自動刪除完成收尾，這兩個指令都沒跑過） |
| CI 位置 | `.github/workflows/` | ⬜ 未實測 |
| 人類站（`D3`） | GitHub Pages：`gh-pages` 分支或 Actions 部署 | ⬜ 未實測 |
| 故障退路（`F3`） | 標「結果未定」後逐項讀回，再決定重送或收手：`gh pr view <N> --json state,mergedAt,mergeCommit,headRefOid`（PR 狀態與目標 sha）、`gh pr checks <N>`（CI）、`git ls-remote --heads origin`（遠端分支）、`git merge-base --is-ancestor <head> origin/main`（是否其實已合入）。其中 `gh pr checks` 從未跑過；其餘三項曾在正常流程用過，但整套退路未在 forge 回錯／逾時情境下演練 | ⬜ 未實測 |

## 已知限制（文件推導，待實測）

- 同一帳號不能核可自己的 PR；單人 repo 的 required approvals 必須是 0，審查證據靠 review 內容與 head sha，不靠 approval 計數。
- REST `/issues` 會混入 PR，列 issue 時要過濾。
- 公開 repo 預設任何人可送 review；必要時開 code review limits。
