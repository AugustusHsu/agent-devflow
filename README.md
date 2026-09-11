# agent-devflow

給 AI coding agent 用的開發流程套件：規格建版 → 拆任務 → 開發 → 審查 → 合併 → 收尾，
以及失敗與退版路徑。做成可安裝到任何專案的一組規則、對照表與模板。本 repo 用自己的流程開發自己。

> 現況：`stage: 1`（單線）。規則本體 `devflow/WORKFLOW.md` 為 `0.0.2.0`；
> 對照表尚未遷移至 `R9` 三值，且絕大多數格子仍標未實測，
> 待 #17 的職位／分節結構落地後，再由 #15 依 `R9` 重做。下一步是 Phase 2（見下）。

## 設計要點

- **三個自變數**（`devflow.yml`）：`forge`（github｜gitlab）、`coder`（claude-code｜codex）、`orchestrator`（none｜hermes｜paperclip）。其餘都是衍生值，由 `devflow/forges/`、`coders/`、`orchestrators/` 對照表提供，每格標實測狀態。
- **工單只住 forge**；PR/MR 是審查與合併的載體；repo 內不放工單檔或審查報告副本。
- **規格先建版**：規格文檔獨立 PR 合入，版本＝merge commit，文內四碼版本欄，不打 spec tag。任務由 diff＋影響分析推導，不由版本位數推導。
- **兩個基準**：每個任務記錄治理基準 G（WORKFLOW.md 的 commit）與開發目標 T（規格的 commit）。規則變更依舊規則審查，合入後在下一個任務／session 邊界啟用——這是避免「改流程卡死自己」的核心機制。
- **四碼版本** `a.b.c.d`，進位歸零：a 不相容、b 相容新增、c 修正、d 內容修訂。從 `0.0.0.0` 起；`stage` 不是版本號。
- **coder 永遠在 worktree**（`../<repo>.worktrees/<N>`），主 checkout 只做協調。
- **合併預設由人按**（`merge: human`）；獨立審查建議異廠、不強制。
- **Bypass 是有範圍的例外**：需當次授權、引用 `bypass` issue、寫明跳過哪條與恢復方式。
- **文檔一個來源兩種投影**：`devflow/` 與 `docs/spec/` 給 agent（也給人看），`docs/guide/` 只給人。人類站等首個 release 再接 MkDocs＋mike；不做 wiki 投影。

規則的完整條文與 ID 見 [`devflow/WORKFLOW.md`](devflow/WORKFLOW.md)。

## 為什麼再做一個

三個前身的教訓：

| 前身 | 教訓 |
|---|---|
| agent-team-kit | 工具比流程先長大，`kit/` 與根目錄兩份拷貝靠測試硬撐。但它的 git 規則（merge commit、祖先驗證後才刪分支、單人 repo 的 approvals 設定）與平行前提（依賴／寫入範圍／契約／外部資源四項）是對的，本 repo 沿用 |
| agent-foundry | 規則要匯入才生效、每次變更過多道人工閘門、事實抄在多處再靠戳記追同步。本 repo 把「規則就是檔案」與「一個事實一處」當不變式 |
| AI_Server_SuperOD | 真實 GitLab 專案。它證明 MR＋merge commit＋protected tag 跑得動，也留下「API 回 500 但其實已合併」「正本與鏡像 remote 同名不同義」這類必須寫進失敗路徑與專案綁定的案例 |

## 佈局

```
devflow.yml               三個自變數、stage、merge、docs
devflow/
  WORKFLOW.md             規則本體（規則帶 ID）
  forges/ coders/ orchestrators/   衍生值對照表，每格標實測狀態
  templates/              spec / issue / pr / review-prompt / entry-block
CLAUDE.md AGENTS.md       只含 devflow:begin/end 區塊（由 templates/entry-block.md 產生）
docs/spec/                本 repo 自己的規格（dogfood）
docs/guide/               人類專用
.github/workflows/        devflow-checks.yml：九項檢查，`d2`／`i1` 為關卡（check 列入 branch protection），其餘七項建議只寫進 log
```

## 執行順序

各 Phase 的「出口」是**該階段的能力已驗證**，驗證與試跑一律發生在升 `stage` 之前：`stage` 只標示已驗證的能力，
不是權限開關（`ST4`）。因此「演練或驗證某項能力」與「把它設為 required check」是兩件事，
後者另有自己的條件（前提與三條件，見「Phase 1 第三出口的判定方式」）。

| Phase | 內容 | 出口 |
|---|---|---|
| 0 | 本 README、`devflow.yml`、WORKFLOW.md 草稿、對照表骨架、模板、入口區塊 | 使用者審過 WORKFLOW.md，直推 main |
| 1 | GitHub 設定（main 保護、labels）逐格實測；驗 coder headless 與 worktree 交接；CI workflow 在 PR 最終 head 的 run 成功且 log 產出 advisory；升 required 的判定方式見表下一節（Phase 1 內以 `i1` 走通） | `stage: 1`；自動合併保持關閉 |
| 2 | 第一個端到端任務：把入口區塊安全插入**其他專案**既有的 CLAUDE.md／AGENTS.md（含客製內容、重跑、碰撞測試）——本 repo 自己的入口區塊已存在，這裡開發的是可安裝到別處的能力；再跑 2–3 個有價值的任務；萃取 Hermes skill | 整條鏈跑通並可接手 |
| 3 | 用現行流程（W0）開發下一版流程（W1）：規格核准 → 實作 → 依 W0 審查 → 啟用；演練檢查器尚未就緒、執行中規格變更、回復 | `stage: 2`；能改流程、能停、能退 |
| 4 | 隔離專案測安裝／升級／回復；Claude Code 與 Codex 各跑一次；GitLab 唯讀盤點；發 `v0.0.0.1`＋MkDocs＋mike | 有可安全安裝的固定版本 |
| 5 | 導入 AI_Server_SuperOD：先確認正本與 GitLab 當前能力，選低風險模組增量導入，跑一個真實 MR | GitLab 上一條可查證的交付鏈 |
| 6 | 受控平行：兩個低耦合任務、兩個 worktree、合併序列化、單邊失敗與精準清理 | `stage: 3` |

### Phase 1 第三出口的判定方式

- **本階段要達成的**：導入 `.github/workflows/devflow-checks.yml` 的 PR，在其**最終 head commit**
  （`gh pr view <N> --json headRefOid`）上留下一筆同時滿足以下五項的 run——
  `path` ＝ `.github/workflows/devflow-checks.yml`、`event` ＝ `pull_request`、`head_sha` ＝ 該 commit、
  **最新 attempt** 的 `conclusion` ＝ `success`，且 log 實際印出 advisory。
  同一個 head 上可以有多個 workflow 的 run，同一筆 run 也可以有多個 attempt（`run_attempt`），
  所以判定時要把 **run ID 記進該 PR 或 issue**，只說「head 上有成功的 run」指認不了是哪一筆。
  這些條件在分支刪除、PR 合併後仍查得到：
  `gh api "repos/<owner>/<repo>/actions/runs?head_sha=<sha>" --jq '.workflow_runs[] | {id, path, event, head_sha, run_attempt, conclusion}'`。
  判定不看 Actions 實際 checkout 的 merge ref，也不看合併後 main 的 commit——
  三者可以是同一份 tree 但不同 commit SHA（例：`2daafca` 與 `d64d214` 的 tree 都是 `403faa5`）。
- **required 現況**（2026-09-11 起）：`devflow-checks` 已列入 main 的 branch protection
  `required_status_checks`。九項檢查中 `d2`（入口區塊）、`i1`（head branch 名稱）為關卡——
  `❌` 使檢查器 exit 1、check 變紅、擋合併；其餘七項 advisory，只寫進 log，不擋。
  分界是定義域封不封閉，見 `devflow-checks.yml` 檔頭。
- **升 required 的判定方式**（已於 `i1` 首次走通；日後其餘七項升級仍適用，各項的 required 目標記在 #22）：
  - **前提**：workflow 把「這次實際 checkout 的 commit SHA」（`checkout_sha`）與「該 commit 上
    `devflow-checks.yml` 的 blob id」（`checker_blob`）印進 log——PR #41 起印出。
    `pull_request` 事件跑的是 GitHub 生成的 merge commit，該 commit 在 PR 合併後就查不到
    （`refs/pull/<N>/merge` 隨之消失），沒有這兩行，事後無從回推當時執行的是哪一份檔案。
  - **條件一**：正、反兩個 run 的 log 印出的 blob 相同——同一份檢查器，才談得上正反驗證。
  - **條件二**：正向案例是**合法輸入**：無任何 `❌`，最新 attempt 的 `conclusion` ＝ `success`（檢查器 exit 0）。
  - **條件三**：負向案例相對正向案例**只新增目標項的違規**；其他項可以報 `📝` advisory，
    但不得出現 `❌`，`exit 1` 只能由目標項造成。證據：正負兩份輸入的 diff、目標項的 `❌`、
    其他項至多 `📝`，且 exit 為 1 不是 2（`exit 2` ＝檢查器本身無法執行）。
  - **證據**（`i1`；兩 run 皆 `event` ＝ `pull_request`、attempt 1；原始紀錄在 #22 留言）：

    | | 正向 | 負向 |
    |---|---|---|
    | PR | #41（head `4977b38`，已合併 `06ed4cc`） | #42（probe，空 commit `11d0fba`，分支 `probe-i1-negative`，已關不合併） |
    | run | `34549823621` | `34550078594` |
    | `checker_blob` | `0fb9116` | `0fb9116` |
    | `conclusion` | `success` | `failure` |
    | `❌` | 無 | 只有 `i1`（分支名不合 `<N>-<slug>`） |
    | 其他項 | 12 項 `📝` | 同一組 `📝` |
    | exit | 0 | 1 |

    `d2` 未取負向 run：要動 `AGENTS.md`，而本 repo 自己的入口區塊超 30 行不是「合法輸入的最小變動」。

## 不做的事

DAG／wave 排程器、多路審查 panel、每張單一份審查報告檔、工單鏡像、wiki 投影。
也不新增超出當前 stage 需要的工具。
封存舊 repo、清舊 worktree、改動 SuperOD 既有結構，都不在本計畫內。
