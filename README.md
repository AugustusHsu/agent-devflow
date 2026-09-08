# agent-devflow

給 AI coding agent 用的開發流程套件：把「規格建版 → 拆任務 → 平行開發 → 彙整 → 退版」
做成可安裝到任何專案的一組規則、模板與最少量腳本。本 repo 用自己的流程開發自己。

> 現況：`stage: 0`（bootstrap，尚無流程）。設計決策已定案（見下），流程本體 `devflow/WORKFLOW.md` 尚未寫。

## 為什麼再做一個

三個前身各留下教訓：

| 前身 | 教訓 |
|---|---|
| agent-team-kit | 工具比流程先長大（逾四千行 Python、47 張流程工單）；`kit/` 與根目錄兩份拷貝靠測試硬撐；三路審查讓一張單審五輪；收尾（worktree、分支）沒機械化，所以一直殘留 |
| agent-foundry | 規則要「匯入」才生效，而匯入只有人能做；每次變更過三道人工閘門；一個事實抄在多處，再用戳記與 lint 追同步；反悔錄長到 269 行 |
| AI_Server_SuperOD | 真實專案，GitLab + MR + protected tag 跑得動，是唯一能實測 `gitlab` 欄的地方；但 kit 安裝物被 `.gitignore` 掉、CLAUDE.md 膨脹到 69 KB |

歸納成四條不變式：

1. **一個事實只住一處，其餘一律生成。** 入口檔（CLAUDE.md／AGENTS.md）、人類文檔站、平台對照表都是產物；不手抄、不設戳記。
2. **合併進 main 就是部署。** 規則是 repo 裡的檔案，coder 直接讀；沒有匯入步驟。
3. **工單只住在 forge。** repo 內不放工單檔、不放 BACKLOG；orchestrator 不得持有第二份。
4. **工具只做痛過兩次以上的。** 程式碼總量設紅線；超過就是流程設計有問題，不是要更多工具。

## 三層工具變數

| 變數 | 回答的問題 | 值 |
|---|---|---|
| `forge` | repo、PR/MR、issue、CI 住在哪 | `github` \| `gitlab` |
| `coder` | 誰動手改 code | `claude-code` \| `codex` |
| `orchestrator` | 誰派工、喚醒 coder、跟人對話 | `none` \| `hermes` \| `paperclip`（省略＝`none`，人自己派工） |

只有這三個是自變數。審查載體、CLI、CI 檔位置、入口檔名、skills 目錄、派工方式都是衍生值，
由 `devflow/` 下的對照表機械產生，每一格標「實測／未實測」。

兩條鐵律：orchestrator 不得持有工單的第二份拷貝；換 orchestrator 不得改變 forge 與 coder 的任何狀態——
三種 orchestrator 下 issue、分支、worktree、PR 的形狀完全相同，差別只在誰按按鈕、一次按幾個。

## 已定案的設計決策

- **規格建版**：規格文檔獨立 PR/MR 以 merge commit 合入 main（不 squash）。版本＝該 merge commit；
  任務從 `git diff <上一版>..<這版> -- docs/spec/<feature>/` 拆；退版＝`git revert -m 1` 同一顆。
  不打 spec tag；文檔內建版本欄。零任務的規格變更是合法且完整的變更。
- **審查閘門＝PR/MR 本身**。一個 fresh-context reviewer 對固定的 base..head 逐條 AC，至少嘗試一個反例。
- **平行**：每張 issue 宣告 write scope；重疊者不同時開工。一個 worktree 一個 coder。不做 DAG／wave／overlap zone。
- **衝突歸屬**：後合者適應（merge main 進自己的分支）。
- **失敗路徑**：文檔錯 → 回規格開新版、任務關閉；實作錯 → 退回同一任務，兩輪後升級到人；
  合併衝突 → 後合者適應；整合後壞 → 退版。
- **收尾清單**：測試綠 → PR/MR → 審查 → merge commit → 關 issue → `git worktree remove` ＋ 刪分支 →
  `git worktree list` 只剩主目錄。
- **兩級變更**：`normative`（改變 coder／orchestrator 被允許或被要求做的事、模板與對照表內容）走完整流程；
  `editorial`（措辭、範例、補坑）不開 issue、不建版。判準必須機械。
- **Stage**：repo 以 `stage` 宣告套用到哪一層——`0` bootstrap、`1` 單線、`2` 規格建版、`3` 平行。
  規則不得要求它自己尚未存在的機制；導入專案可從任一層起。
- **Bypass**：直推 main 是合法操作，不是漂移。commit 必須引用一張帶 `bypass` label 的 issue
  （沒有就開一張一行的），標題前綴 `⏭️`。`gh issue list -l bypass` 就是帳，不另設紀錄。
- **文檔**：一個來源、兩個投影，判準是「會不會進 agent 的 context」。`devflow/` 與 `docs/spec/` 給 agent
  （也渲染給人）；`docs/guide/` 只給人，入口檔永不指向它。現在只靠 forge 渲染；
  mkdocs＋mike 等 kit 第一個 release；wiki 不當投影目標（它是可手改的第二份真相）。
- **版本號一律四碼** `<a>.<b>.<c>.<d>`，進位歸零（動 a 則 b／c／d 歸零，依此類推）。兩個用途，
  位數判準都是「下游要付什麼代價」：
  - kit release tag `v<a>.<b>.<c>.<d>`（導入專案付的代價）：a 流程形狀變、b normative 變（要重生衍生檔）、
    c 相容新增（新的欄、模板、工具）、d editorial。
  - 規格文檔版本欄（實作付的代價）：a 目標或範圍改寫、b 既有 AC 改動（既有任務失效）、
    c 只新增 AC（只新增任務）、d 澄清（零任務）。orchestrator 看 bump 的是哪一位決定怎麼從 diff 推任務。
  - `stage` 不是版本號。

## 預定佈局

```
agent-devflow/
├─ devflow.yml            # 三層變數、stage、docs 政策；本 repo 自己也是第一個消費者
├─ devflow/               # 出貨內容，唯一一份；安裝＝複製此目錄＋生成衍生檔
│  ├─ WORKFLOW.md         # 狀態機、不變式、失敗路徑、退版（上限約 200 行）
│  ├─ forges/ coders/ orchestrators/   # 衍生值對照表，每格標實測狀態
│  ├─ templates/          # 規格文檔、issue、審查
│  └─ bin/                # 只有痛過才加：init / task-finish / doctor
├─ CLAUDE.md AGENTS.md    # 生成物
├─ docs/spec/             # 本 repo 自己的規格（dogfood）
└─ docs/guide/            # 人類專用
```

## 執行順序

| Stage | 要做的事 | 完成判準 |
|---|---|---|
| 0 | README、`devflow.yml`、`WORKFLOW.md` v1、三張對照表骨架 | 直推 main |
| 1 | 單線流程套自己：issue → worktree → PR → 審查 → merge。卡點開 `process` issue，不當場改。跑過 2–3 張後萃取 Hermes skill（住在 repo，symlink 進 `~/.hermes/skills/`） | Hermes 用 skill 跑完一張 |
| 2 | 規格建版套自己：把累積的 `process` issue 合成一次 `WORKFLOW.md` 版本，從 diff 推任務 | 這一步卡住＝設計錯；改規則，不加工具 |
| 3 | 平行：兩張 write scope 不重疊的 issue，Hermes 各起一個 Claude Code 與一個 Codex | 收尾後 `git worktree list` 只剩主目錄 |
| 導入 | AI_Server_SuperOD 從 stage 1 裝起：`gitlab` 欄實測、查 Pages 是否開放 | 一個真實小功能走完 |
| 之後 | kit `v0.0.0.1` → mkdocs＋mike；封存 agent-team-kit、清殘留 worktree | |

## 不做的事

DAG／wave 排程、三路審查 panel、wiki 投影、工單鏡像、預先寫好的工具、每張單一份審查報告檔。
