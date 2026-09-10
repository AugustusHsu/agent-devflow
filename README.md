# agent-devflow

給 AI coding agent 用的開發流程套件：規格建版 → 拆任務 → 開發 → 審查 → 合併 → 收尾，
以及失敗與退版路徑。做成可安裝到任何專案的一組規則、對照表與模板。本 repo 用自己的流程開發自己。

> 現況：`stage: 0`（bootstrap）。規則本體 `devflow/WORKFLOW.md` 為 `0.0.2.0`；
> 對照表待依 `R9` 三值重做（issue #15）。下一步是 Phase 1（見下）。

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
.github/workflows/        CI（目前七項檢查全為建議，不擋 PR；見該檔檔頭）
devflow/
  WORKFLOW.md             規則本體（規則帶 ID）
  forges/ coders/ orchestrators/   衍生值對照表，每格標實測狀態
  templates/              spec / issue / pr / review-prompt / entry-block
CLAUDE.md AGENTS.md       只含 devflow:begin/end 區塊（由 templates/entry-block.md 產生）
docs/spec/                本 repo 自己的規格（dogfood）
docs/guide/               人類專用
```

## 執行順序

| Phase | 內容 | 出口 |
|---|---|---|
| 0 | 本 README、`devflow.yml`、WORKFLOW.md 草稿、對照表骨架、模板、入口區塊 | 使用者審過 WORKFLOW.md，直推 main |
| 1 | GitHub 設定（main 保護、labels）逐格實測；驗 coder headless 與 worktree 交接；CI check 跑通並有正反 run 紀錄 | `stage: 1`；自動合併保持關閉 |
| 2 | 第一個端到端任務：把入口區塊安全插入既有 CLAUDE.md／AGENTS.md（含客製內容、重跑、碰撞測試）；再跑 2–3 個有價值的任務；萃取 Hermes skill | 整條鏈跑通並可接手 |
| 3 | 用 W0 開發 W1：規格核准 → 實作 → 依 W0 審查 → 啟用；演練檢查器尚未就緒、執行中規格變更、回復 | `stage: 2`；能改流程、能停、能退 |
| 4 | 隔離專案測安裝／升級／回復；Claude Code 與 Codex 各跑一次；GitLab 唯讀盤點；發 `v0.0.0.1`＋MkDocs＋mike | 有可安全安裝的固定版本 |
| 5 | 導入 AI_Server_SuperOD：先確認正本與 GitLab 當前能力，選低風險模組增量導入，跑一個真實 MR | GitLab 上一條可查證的交付鏈 |
| 6 | 受控平行：兩個低耦合任務、兩個 worktree、合併序列化、單邊失敗與精準清理 | `stage: 3` |

## 不做的事

DAG／wave 排程器、多路審查 panel、每張單一份審查報告檔、工單鏡像、wiki 投影、預先寫好的工具。
封存舊 repo、清舊 worktree、改動 SuperOD 既有結構，都不在本計畫內。
