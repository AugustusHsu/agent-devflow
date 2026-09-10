# orchestrator: hermes

Hermes Agent 當協調者：確認範圍、固定 G／T、建 worktree、啟動 coder、向人提問、驗證交付、收尾。

| 面向 | 值 | 狀態 |
|---|---|---|
| 派工（`L2`） | 用 `terminal` 直接啟動 coder CLI（見 `coders/`），保存程序或 session 識別。**不用 `delegate_task` 起 coder**——它起的是 Hermes 子代理，不是 Claude Code／Codex | ✅ 實測 2026-09-11（驗證方式：在 orchestrator 的頂層 session 以 `terminal(command="cd <worktree> && <coders/ 表上的 CLI 指令> > <stdout 檔> 2> <stderr 檔> < /dev/null", background=true)` 啟動 coder，記下該工具回傳的 pid；再於同一台機器讀回三項——(1) `pstree -p <該 pid> \| head -1` 的鏈上出現 `claude(<coder pid>)`；(2) `tr '\0' ' ' < /proc/<coder pid>/cmdline` 以 `claude -p` 開頭；(3) `readlink /proc/<coder pid>/cwd` 等於該 worktree 路徑。第 (1) 項同時判定「不用 `delegate_task`」：`delegate_task` 起的是 Hermes 自己的子代理，進程樹不會多出 `claude -p` 這個外部進程。值欄「保存程序或 session 識別」兩項分別由 `terminal(background=true)` 回傳、稍後仍可用來讀回該進程的 pid，與 stdout 檔內 JSON 的 `session_id`（見 `coders/claude-code.md` 的 headless 執行格）判定。**不要用 `ps -eo pid,args \| grep 'claude -p'`**：coder 的 prompt 為多行時 `ps` 的 args 顯示不可靠，會讀到空結果而誤判進程不存在。此程序不依賴本次的 prompt 或 repo，第三者現在可獨立重跑。受測環境：2026-09-11；orchestrator 為 Hermes Agent v0.21.1（2026.9.7），coder 為 Claude Code 2.1.267 headless；程序讀回依賴 Linux 的 `/proc` 與 `pstree`（無 `/proc` 的平台須另找讀回方式）；執行身分為本機 OS 使用者，且須與 coder 進程同一使用者（`/proc/<pid>/cwd` 只有該進程擁有者或 root 讀得到）；目標 repo `AugustusHsu/agent-devflow`；證據：issue #33 留言 https://github.com/AugustusHsu/agent-devflow/issues/33#issuecomment-5624350935（完整 `terminal` 呼叫）＋ https://github.com/AugustusHsu/agent-devflow/issues/33#issuecomment-5624355903（進程樹與 `/proc` 讀回）） |
| 建 worktree（`I2`） | `git worktree add ../<repo>.worktrees/<N> <N>-<slug>` | ✅ 實測 2026-09-11（驗證方式同 `coders/claude-code.md` 的 worktree 格，主體換成 orchestrator：orchestrator 在主 checkout 以 `terminal` 執行 `git branch <N>-<slug> origin/main`，再執行 `git worktree add ../<repo>.worktrees/<N> <N>-<slug>`；啟動 coder 前以 `git worktree list` 確認輸出含該路徑與分支名，並以 `git -C ../<repo>.worktrees/<N> rev-parse HEAD` 確認該 worktree 的 HEAD 等於 base commit。判定點：worktree 路徑落在 repo 目錄之外（`I2`），主 checkout 那一列仍停在原分支與原 commit，且 coder 只收到該路徑。此程序不依賴本次的 issue 或 repo，第三者現在可獨立重跑。受測環境：2026-09-11；orchestrator 為 Hermes Agent v0.21.1（2026.9.7），以 `terminal` 工具執行本機 `git version 2.43.0` 的 `branch`／`worktree` 子命令；執行身分為對該 repo 工作目錄具寫入權限的本機 OS 使用者（本步驟不需 forge 權限）；目標 repo `AugustusHsu/agent-devflow`，base `origin/main @ 333d087`；證據：issue #33 留言 https://github.com/AugustusHsu/agent-devflow/issues/33#issuecomment-5624350935） |
| HITL（`L3`） | `clarify` 問人；答案寫回 issue 留言；派工前先清完未決事項 | ⬜ 未實測 |
| 平行上限 | 人設；`P1` 逐項確認寫進 issue | ⬜ 未實測 |
| 流程指令住哪 | `devflow/orchestrators/hermes/SKILL.md`（尚未寫；依 Phase 2 實跑後萃取），接入方式待驗：symlink 進 `~/.hermes/skills/`、或 `skills.external_dirs`、或 trusted project-local skills | ⬜ 未實測 |
| skill 啟用邊界（`G3`） | skill 指向已核准版本，不指向編輯中的候選；驗證「載到正確內容與版本」，不只驗 symlink 存在 | ⬜ 未實測 |
| 中斷交接 | 保留 issue、分支、worktree、HEAD、未提交內容、最後可信驗證；確認舊 coder 已停才重派 | ⬜ 未實測 |

## 已知事實（文件推導，待實測）

- Hermes 的專案 context 在 session 開始載入；改磁碟檔不會替換已載入的規則（`G3` 的依據）。
- Hermes 子代理不能 `clarify`；提問只能由頂層 session 發出。
- Hermes 掃 skill 目錄用 `os.walk(followlinks=True)`，symlink 理論上可被發現；仍需實測。
