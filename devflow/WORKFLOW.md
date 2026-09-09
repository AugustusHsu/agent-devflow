---
version: 0.0.1.0
---

# agent-devflow WORKFLOW

給 agent 讀的規範本體。引用規則一律用 ID（例：`I2`、`R3`），不用節號。
本檔不解釋理由；理由在對應規格與 README。人類導讀另見 `docs/guide/`（尚未建立）。

## 0. 變數與基準

- 三個自變數住 `devflow.yml`：`forge`、`coder`、`orchestrator`（省略＝`none`）。其餘皆衍生值，見 `forges/`、`coders/`、`orchestrators/` 對照表；對照表每格標實測狀態，未實測不得當作可用；實測狀態的認定依 `R7`、`R8`，不因 `stage` 放寬。
- 每個任務固定兩個基準，寫在 issue 與 PR：
  - **治理基準 G**：本任務遵守的 `devflow/WORKFLOW.md` commit。
  - **開發目標 T**：本任務要實現的規格 commit 與 AC 清單。
- 第 0、1、13 節永遠生效；其餘各節依 `stage`（第 11 節）啟用。

## 1. 不變層（I）

- `I1` 同一時間：一張 issue ＝ 一條分支 ＝ 一個 worktree ＝ 一個 coder。分支名 `<N>-<slug>`。
- `I2` coder 不在主 checkout 工作。worktree 由 orchestrator（或人）建在 `../<repo>.worktrees/<N>`；coder 只收路徑。主 checkout 只供協調用：forge 操作、建 worktree、收尾。
- `I3` 進 main 的每個變更都經 PR/MR，以 merge commit 合入；不 squash、不 rebase merge。唯一例外見第 10 節。
- `I4` 工單只住 forge。repo 內不放工單檔、BACKLOG、審查報告副本；orchestrator 不得持有工單的第二份拷貝。
- `I5` 一個事實只住一處。入口檔區塊、對照表衍生物、人類站都是產物：不手抄、不設同步戳記。
- `I6` 換 orchestrator 不改變 forge 與 coder 的任何狀態：issue、分支、worktree、PR 的形狀在三種 orchestrator 下相同。

## 2. 規格（S）

- `S1` 規格住 `docs/spec/<feature>/spec.md`：frontmatter `version`（四碼），固定三個標題「目標與範圍」「驗收標準」「未決事項」；AC 一行一條、帶 `AC-n`。
- `S2` 規格變更經 PR 合入。版本＝該 merge commit；`0.0.0.0` 是草稿，首個核准版本是 `0.0.0.1`。
- `S3` 任務推導＝`git diff <上版>..<這版> -- docs/spec/<feature>/` ＋ 既有實作 ＋ 影響分析；每條受影響 AC 標 保留／修改／新增／取消。**不由版本位數推導**；首版也先辨識已完成的部分。
- `S4` 一次規格變更可對應零到多個任務；不為湊數發明任務。
- `S5` 規格 PR 由人審，依 `merge` 設定合併。
- `S6` 「未決事項」非空的規格不得核准。

## 3. 版本（V）

- `V1` 四碼 `a.b.c.d`，進位歸零；混合變更取影響最高的一位。這是本套件的自訂規則，不是 SemVer。
- `V2` 位數語意：`a` 不相容（既有契約或用法不再成立）；`b` 相容新增（新能力、新 AC）；`c` 修正既有能力，承諾不變；`d` 內容修訂，不改行為與契約。
- `V3` normative ＝ bump ≥ `c`，需 issue；editorial ＝ bump `d`，不需 issue，仍走 PR、仍 bump。判斷依語意，不依章節位置或字數。
- `V4` 適用對象：規格文檔（含本檔）與 kit release tag `v<a.b.c.d>`。`stage` 不是版本號；第三方版本、工具版本、issue 編號保持原值。
- `V5` kit tag 只打在 main 已含的 commit；已發版本不移動、不刪、不重打，修正走下一版。

## 4. 任務生命週期（L）

- `L1` 派工前 issue 必須有：目標與對應 AC、G、T、write scope、阻塞依賴、共用契約、外部資源；「未決事項」為空。模板 `templates/issue.md`。
- `L2` 派工：從最新 main 建分支與 worktree；coder 收到 issue、G、T、worktree 路徑、驗證指令。
- `L3` coder 遇未決事項：issue 留言 → 停（blocked），不猜。orchestrator 問人，答案寫回 issue，再重派。issue 留言是持久紀錄，提問通道只是通道。工作區內出現非本任務產生的檔案或工具生成物（MCP、編輯器、快取自動寫入者）同樣適用：回報，不自行 `add`、不自行刪除。
- `L4` 完成：測試綠 → push 分支 → 開 PR，引用 issue、G、T、head sha。模板 `templates/pr.md`。
- `L5` 之後依序：審查（第 5 節）→ 合併（第 6 節）→ 收尾（第 8 節）。
- `L6` 取消任務而分支已有 commit：先問人保留或丟棄，不得逕自刪除。

## 5. 審查（R）

- `R1` 實作 PR 由 fresh-context 審查者審：拿到 G、T、`base..head`、完整來源、測試指令；不接受作者摘要當證據。同一 session 不得對自己的工作簽正式 verdict。
- `R2` 建議審查者與 coder 異廠；只有一家可用時，用同廠的全新 context。
- `R3` verdict 必須寫明 head sha；head 變更即失效，須重審。
- `R4` 逐條 AC 給證據，至少嘗試一個反例；反例須涵蓋「正確的值出現在錯誤的位置」這一類，不只是「值不存在」——把 AC 要求的字串設想成落在另一列、另一節、另一格，再看現有證據是否仍然成立；仍成立即證據不足。檢查 write scope 是否被超出、是否夾帶 `G5` 所列變更。用 `templates/review-prompt.md`。
- `R5` 審查證據住 forge（PR review／comment）。merge commit 訊息帶 PR 號、reviewer、head sha，作為離開 forge 時的可攜最小集合。
- `R6` 證據須能定位：AC 的驗證指令要指出具體位置與內容。計數式斷言（`grep -c`、`wc -l`、`--count`、比對總數）不得作為任一條 AC 的唯一證據——計數相符不表示內容落在正確位置；須另以 `grep -n` 定位或 `git diff` 逐行比對，並貼出該行。
- `R7` 對照表一格的值欄列出多個指令、選項或能力時，`✅ 實測` 必須對應全部皆已驗證。只驗證其中一部分：拆成獨立列各自標狀態，或在值欄逐項標明已驗證／未測，該格狀態取最保守者。實際生效的機制與值欄所列不同時（例如靠平台預設而非該指令），改寫值欄，不沿用原宣稱。
- `R8` 對照表的證據須是可獨立核對的觀察：第三者能重跑、或在 repo／forge 內查得到的產物（指令輸出、PR／issue 的實際狀態、transcript）；不得以 commit 訊息或對照表自身互證。不得由「行為符合規則」反推規則已生效——該行為若同時被派工 prompt 或其他來源要求，證據分不出來源，視同未測。

## 6. 合併（M）

- `M1` 前提全部成立：測試綠；有效 verdict（`R3`）；候選的 base 是當下 main，或已 merge main 且重測、重審。
- `M2` 合併者依 `devflow.yml` 的 `merge`：`human` 由人按；`orchestrator` 只在有機械 guard 能驗 `M1` 時允許，否則視同 `human`。
- `M3` main 前進造成衝突：後合者 merge main 進自己的分支，重測、重審。
- `M4` 無文字衝突不等於無語意衝突；`M1` 的驗證對象是最終整合候選。

## 7. 失敗與退版（F）

- `F1` 實作未達 AC：同一 issue 修正；兩輪無進展升級到人。升級不等於放行。
- `F2` 規格錯或出現新依賴：暫停受影響任務，先走第 2 節修訂規格；無關任務繼續。不自動關單丟棄工作。
- `F3` forge 回錯或逾時：標「結果未定」，讀回 PR/MR 狀態、目標 sha、CI、分支後再決定；不盲目重送、不自行 bypass。
- `F4` 合併成功但收尾失敗：記 cleanup pending，只補收尾；不重做合併、不回滾已成功的實作。
- `F5` 撤回壞實作：revert PR（`git revert -m 1 <merge>` 產生 diff，仍走 `I3`）；規格仍正確就不撤規格。
- `F6` 已部署或涉及 migration：Git revert 不替代部署回復，另行處置相容的產物、配置與資料。

## 8. 收尾（C）

- `C1` 順序：確認來源 head 是 main 祖先（`git merge-base --is-ancestor`）→ 停止 coder 程序 → 檢查 worktree 無需保留的未提交／未追蹤內容 → `git worktree remove` → 本機目標分支快轉對齊遠端（`git checkout main && git merge --ff-only origin/main`）→ `git branch -d`（永不 `-D`）→ 刪遠端分支 → `git ls-remote --heads` 驗證。快轉這步不可省：`-d` 的保護判準是 HEAD，本機 main 落後時 `-d` 等同失去保護。
- `C2` 關 issue；forge 自動關閉也要讀回驗證。
- `C3` 只清本次任務擁有的資源；其他活躍任務的 worktree、分支不動。blocked 或取消且成果未處置者保留並回報。
- `C4` 「`git worktree list` 只剩主目錄」是成功收尾的判準，不是強清命令。

## 9. 治理與規則變更（G）

- `G1` 每個任務記錄 G（本檔 commit）；PR 審查依 G 進行。
- `G2` 本檔的 normative 變更走第 2 節：規格核准 → 實作（本檔、模板、對照表、skill 都是實作）→ 依 G（舊版）審查。候選版本不得放寬對自己的審查。
- `G3` 新版啟用點是合入後的下一個任務／session 邊界。進行中的任務預設續用舊 G；新版修補安全缺陷時，明確暫停受影響任務並遷移，不默默混用兩版。
- `G4` 新規則要求的檢查器尚不存在時，先列為「建議」；工具可執行且正反測試通過後才升為必需關卡。
- `G5` 候選分支中的 CLAUDE.md／AGENTS.md／skill／CI 變更是待審產品，不是本次的治理依據。

## 10. Bypass（B）

- `B1` 直推 main 需人當次授權；不是常設許可。
- `B2` commit 標題前綴 `⏭️`，引用一張帶 `bypass` label 的 issue，寫明：跳過哪條規則 ID、理由、影響範圍、恢復方式。
- `B3` forge 不可用時先留本機紀錄（commit 訊息），恢復後補 issue。
- `B4` `stage: 0` 期間直推 main 不需 bypass issue；離開 stage 0 後本節生效。

## 11. Stage（ST）

- `ST0` bootstrap：尚無流程，直推 main。
- `ST1` 單線：第 4～8、10 節生效；同時只有一個任務。
- `ST2` 規格建版：加上第 2、3、9 節；任務從規格推導。
- `ST3` 平行：加上第 12 節。
- `ST4` stage 只標示已驗證的能力，不是權限開關；降 stage 不放寬 main 保護、憑證或發布授權。

## 12. 平行（P）

- `P1` 兩張任務同時活躍的前提（全部成立）：無阻塞依賴；write scope 不重疊；共用契約已在 main 且無人同時修改；外部資源可隔離。任一項不可判定 → 排序執行。
- `P2` 外部資源含 GPU、容器名、埠、資料目錄、image tag、部署環境。可平行編輯不等於可平行驗證或部署。
- `P3` 合併序列化；後合者適應（`M3`）。
- `P4` 不做 DAG／wave 排程器；`P1` 由 orchestrator 在派工時逐項確認並寫進 issue。

## 13. 文檔（D）

- `D1` 一個來源、兩種投影：`devflow/`（agent 讀，也渲染給人）、`docs/spec/`（agent 與人）、`docs/guide/`（只給人）。規範只有一份，指南引用它。
- `D2` 入口檔（CLAUDE.md／AGENTS.md）只擁有 `<!-- devflow:begin -->`…`<!-- devflow:end -->` 區塊，≤30 行；區塊外是專案的內容，安裝與升級不得改動。
- `D3` 人類站依 `devflow.yml` 的 `docs.site`／`docs.versioning`；版本跟 kit release。wiki 不當投影目標。
- `D4` 超過 20 KB 的檔案不整份載入；先 `grep -n` 定位再局部讀。
