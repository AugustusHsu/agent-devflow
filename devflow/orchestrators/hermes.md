# orchestrator: hermes

Hermes Agent 當協調者：確認範圍、固定 G／T、建 worktree、啟動 coder、向人提問、驗證交付、收尾。

| 面向 | 值 | 狀態 |
|---|---|---|
| 派工（`L2`） | 用 `terminal` 直接啟動 coder CLI（見 `coders/`），保存程序或 session 識別。**不用 `delegate_task` 起 coder**——它起的是 Hermes 子代理，不是 Claude Code／Codex | ⬜ 未實測（forge／repo 內查不到派工方式的紀錄：orchestrator 側的 terminal transcript 未留存，而 `terminal` 與 `delegate_task` 兩種派工在 repo／forge 留下的產物相同，現有觀察無法區分。值欄另一項「保存程序或 session 識別」所依據的 session_id `c5014a9f-…` 與 `coders/claude-code.md` 交接格同源，該格已依 `R8` 判定不可獨立核對；依 `R7` 全格取最保守者） |
| 建 worktree（`I2`） | `git worktree add ../<repo>.worktrees/<N> <N>-<slug>` | ⬜ 未實測（PR #2 記錄的建法為 `git branch 1-forges-github-phase1 origin/main` ＋ `git worktree add ../agent-devflow.worktrees/1 1-forges-github-phase1`。但該路徑已於收尾移除，重跑只證明 Git 指令可用，不能證明當時確由 Hermes 建立。補測：建立當下把指令與 `git worktree list` 輸出貼進 issue） |
| HITL（`L3`） | `clarify` 問人；答案寫回 issue 留言；派工前先清完未決事項 | ⬜ 未實測 |
| 平行上限 | 人設；`P1` 逐項確認寫進 issue | ⬜ 未實測 |
| 流程指令住哪 | `devflow/orchestrators/hermes/SKILL.md`（尚未寫；依 Phase 2 實跑後萃取），接入方式待驗：symlink 進 `~/.hermes/skills/`、或 `skills.external_dirs`、或 trusted project-local skills | ⬜ 未實測 |
| skill 啟用邊界（`G3`） | skill 指向已核准版本，不指向編輯中的候選；驗證「載到正確內容與版本」，不只驗 symlink 存在 | ⬜ 未實測 |
| 中斷交接 | 保留 issue、分支、worktree、HEAD、未提交內容、最後可信驗證；確認舊 coder 已停才重派 | ⬜ 未實測 |

## 已知事實（文件推導，待實測）

- Hermes 的專案 context 在 session 開始載入；改磁碟檔不會替換已載入的規則（`G3` 的依據）。
- Hermes 子代理不能 `clarify`；提問只能由頂層 session 發出。
- Hermes 掃 skill 目錄用 `os.walk(followlinks=True)`，symlink 理論上可被發現；仍需實測。
