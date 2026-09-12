---
version: 1.3.2.0
---

# agent-devflow WORKFLOW

給 agent 讀的規範本體。引用規則一律用 ID（例：`I2`、`R3`），不用節號。
本檔不解釋理由；理由在對應規格與 README。人類導讀另見 `docs/guide/`（尚未建立）。

## 0. 變數與基準

- 自變數住 `devflow.yml`：`forge`，以及 `seats` 下各職位（`seats/`）的綁定——`filler`（填充者：工具名，或 `human`）與選填的 `model`、`reasoning`；`coordinator` 省略＝`human`。其餘皆衍生值，見 `forges/`、`coders/`、`orchestrators/` 對照表；對照表每格標狀態（`R9`），非 `✅` 不得當作可用；實測狀態的認定依 `R7`、`R8`，不因 `stage` 放寬。
- 每個任務固定兩個基準，寫在 issue 與 PR：
  - **治理基準 G**：本任務遵守的 `devflow/WORKFLOW.md` commit。
  - **開發目標 T**：本任務要實現的規格 commit 與 AC 清單。
- 第 0、1、13 節永遠生效；其餘各節依 `stage`（第 11 節）啟用。

## 1. 不變層（I）

- `I1` 同一時間：一張 issue ＝ 一條分支 ＝ 一個 worktree ＝ 一個實作者（職位，`seats/implementer.md`）。分支名 `<N>-<slug>`。
- `I2` 實作者（職位，`seats/implementer.md`）不在主 checkout 工作。worktree 由協調者（職位，`seats/coordinator.md`；由工具或人填）建在 `../<repo>.worktrees/<N>`；實作者只收路徑。主 checkout 只供協調用：forge 操作、建 worktree、收尾。
- `I3` 進 main 的每個變更都經 PR/MR，以 merge commit 合入；不 squash、不 rebase merge。唯一例外是直推 main；第 10 節生效時依該節。
- `I4` 工單只住 forge。repo 內不放工單檔、BACKLOG、審查報告副本；orchestrator 不得持有工單的第二份拷貝。
- `I5` 一個事實只住一處。入口檔區塊、對照表衍生物、人類站都是產物：不手抄、不設同步戳記。
- `I6` 換 orchestrator 工具（`devflow.yml` 的 `seats.coordinator.filler` 值）不改變 forge 與 coder 工具（`devflow.yml` 的 `seats.implementer.filler` 值）的任何狀態：issue、分支、worktree、PR 的形狀在 `seats.coordinator.filler` 的三種值下相同。

## 2. 規格（S）

- `S1` 規格住 `docs/spec/<feature>/spec.md`：frontmatter `version`（四碼），固定三個標題「目標與範圍」「驗收標準」「未決事項」；AC 一行一條、帶 `AC-n`。
- `S2` 規格變更經 PR 合入。版本＝該 merge commit；`0.0.0.0` 是草稿，首個核准版本是 `0.0.0.1`。
- `S3` 任務推導＝`git diff <上版>..<這版> -- docs/spec/<feature>/` ＋ 既有實作 ＋ 影響分析；每條受影響 AC 標 保留／修改／新增／取消。**不由版本位數推導**；首版也先辨識已完成的部分。
- `S4` 一次規格變更可對應零到多個任務；不為湊數發明任務。
- `S5` 規格 PR 由人審，依 `merge` 設定合併。
- `S6` 「未決事項」非空的規格不得核准。

## 3. 版本（V）

- `V1` 四碼 `a.b.c.d`，進位歸零；混合變更取影響最高的一位。這是本套件的自訂規則，不是 SemVer。
- `V2` 位數語意：`a` 不相容（既有契約或用法不再成立），只在人明確要求時進位；`a` 位不由語意判定，協調者與審查者不得自判，也不得以語意為由要求進或不進 `a` 位；`b` 相容新增：新增使用者須遵守的義務或新的流程能力（新步驟、新必填欄位、新關卡）；`c` 修正既有能力與判準補充，承諾不變，包含新增條文，若該條文只是把既有義務的判準寫清楚，或修正既有條文的缺陷；`d` 內容修訂，不改行為與契約。
- `V3` normative ＝ bump ≥ `c`，需 issue；editorial ＝ bump `d`，不需 issue，仍走 PR、仍 bump。判斷依語意，不依章節位置或字數。
- `V4` 適用對象：規格文檔（含本檔）與 kit release tag `v<a.b.c.d>`。`stage` 不是版本號；第三方版本、工具版本、issue 編號保持原值。
- `V5` kit tag 只打在 main 已含的 commit；已發版本不移動、不刪、不重打，修正走下一版。
- `V6` 變更若使既有契約或用法不再成立，不論位數為何，須在 issue 與 PR 說明中標明「不相容」，並列出受影響的契約與遷移方式。審查者可提報未標明者；不得據以要求改位數（`V2`）。

## 4. 任務生命週期（L）

- `L1` 派工前 issue 必須有：目標與對應 AC、G、T、write scope、阻塞依賴、共用契約、外部資源；「未決事項」為空。模板 `templates/issue.md`。
- `L2` 派工：從最新 main 建分支與 worktree；coder 收到 issue、G、T、worktree 路徑、驗證指令。
- `L3` coder 遇未決事項不猜，依判準分兩路徑。停（blocked），任一命中即停：(a) 處置會落在 write scope 外（repo 設定、branch protection、`WORKFLOW.md`、其他任務的 worktree）或會改變 issue 明列的 AC；(b) issue 本體、規格、issue 留言互相矛盾。命中：issue 留言 → 停；orchestrator 問人，答案寫回 issue，再重派。續：未命中者為工程判斷，issue 留言記錄情況、暫定處置、位置後繼續，不停。issue 留言是持久紀錄，提問通道只是通道。工作區內出現非本任務產生的檔案或工具生成物（MCP、編輯器、快取自動寫入者）同樣適用：回報，不自行 `add`、不自行刪除。
- `L4` 完成：測試綠 → push 分支 → 開 PR，引用 issue、G、T、head sha。模板 `templates/pr.md`。
- `L5` 之後依序：審查（第 5 節）→ 合併（第 6 節）→ 收尾（第 8 節）。
- `L6` 取消任務而分支已有 commit：先問人保留或丟棄，不得逕自刪除。

## 5. 審查（R）

- `R1` 實作 PR 由 fresh-context 審查者審：拿到 G、T、`base..head`、完整來源、測試指令；不接受作者摘要當證據。同一 session 不得對自己的工作簽正式 verdict。
- `R2` 建議審查者（職位，`seats/reviewer.md`）由與 coder 工具（`devflow.yml` 的 `seats.implementer.filler` 值）異廠的工具填；只有一家可用時，用同廠的全新 context。
- `R3` verdict 必須寫明 head sha；head 變更即失效，須重審。
- `R4` 逐條 AC 給證據，至少嘗試一個反例；反例須涵蓋「正確的值出現在錯誤的位置」這一類，不只是「值不存在」——把 AC 要求的字串設想成落在另一列、另一節、另一格，再看現有證據是否仍然成立；仍成立即證據不足。檢查 write scope 是否被超出、是否夾帶 `G5` 所列變更。用 `templates/review-prompt.md`。
- `R5` 審查證據住 forge（PR review／comment）。merge commit 訊息帶 PR 號、reviewer、head sha，作為離開 forge 時的可攜最小集合。
- `R6` 證據須能定位：AC 的驗證指令要指出具體位置與內容。計數式斷言（`grep -c`、`wc -l`、`--count`、比對總數）不得作為任一條 AC 的唯一證據——計數相符不表示內容落在正確位置；須另以 `grep -n` 定位或 `git diff` 逐行比對，並貼出該行。
- `R7` 對照表一格的值欄列出多個指令、選項或能力時，`✅ 實測` 必須對應全部皆已驗證。只驗證其中一部分：拆成獨立列各自標狀態，或在值欄逐項標明已驗證／未測，該格狀態取最保守者。實際生效的機制與值欄所列不同時（例如靠平台預設而非該指令），改寫值欄，不沿用原宣稱。值欄是包裝命令、腳本或別名時，先展開其涵蓋的能力再逐項適用本條；不得以「值欄只寫了一項」規避。
- `R8` 對照表的證據採前瞻讀法：`✅` 的判準是「第三者現在照著所附驗證方式做，能得到值欄宣稱的結果」，不是「當時那次執行留下了可核對的紀錄」。驗證方式須已實際執行過，且不依賴當時那次執行的一次性條件；文件推導、類推、未執行的推測不構成 `✅`。不得以 commit 訊息或對照表自身互證。不得由「行為符合規則」反推規則已生效——該行為若同時被派工 prompt 或其他來源要求，證據分不出來源，不構成 `✅`。
- `R9` 對照表狀態欄取三值之一。`✅ 可用`：第三者現在照著做能得到值欄宣稱的結果；須附第三者現在能執行的驗證方式與受測環境（`R8`、`R10`）。`📝 已宣稱`：有人做過並回報，來源具名；該格既有的驗證方式與受測環境記載不得刪去。依該格有無第三者現在能執行的驗證方式分兩種，須標明是哪一種。「無可執行的驗證方式」——該格沒有第三者現在能執行的驗證方式，不論先前是否驗證過。「驗證未達 `✅`」——該格附有第三者現在能執行的驗證方式，但不滿足 `✅` 的成立條件（例如未涵蓋當前宣稱、重跑結果不符、受測環境（`R10`）未附齊或與當前條件不符；不以此為限）。一格兼有兩者時，比照 `R7` 逐項標明是哪一種。`⬜ 未測`：沒做過，或做過的說法沒有具名來源。`📝` 只是資訊，不足以支持派工決策：不得據以宣告能力可用、不得當作任一條 AC 的證據、不得替代 `✅` 放行任何步驟。升為 `✅` 須使 `✅` 的成立條件全部成立；不得以回報次數、「沒有反例」或補齊部分條件代替。對照表得分為通用節與本機節。分節時先歸節、後判狀態。歸節只看值欄宣稱的對象，不看狀態欄：宣稱對象是具名的環境 instance——本機安裝的工具、帳號或組織、本 repo 的設定與資源——歸本機節；宣稱對象是可重用的工具能力或程序、repo 與環境只是可替換的參數者，歸通用節。值欄未表明宣稱對象時，先改寫值欄使其表明，不得直接歸節。一格兼含兩種宣稱時，拆成各自獨立的原子事實分別歸節，不把同一事實抄進兩節（`I5`、`R7`）。歸節後，各節的 `✅ 可用` 依下列定義，`📝`、`⬜` 及三值間的升降在兩節相同。通用節的 `✅ 可用`：第三者在任何專案照該格所附驗證方式做，能得到值欄宣稱的結果。本機節的 `✅ 可用`：第三者在本 repo 的當下環境照該格所附驗證方式做，能得到值欄宣稱的結果。兩節的 `✅` 皆須附第三者現在能執行的驗證方式與受測環境（`R8`、`R10`）；`R10` 的記載、比對與降級對兩節皆適用。未分節的表，`✅ 可用` 依本條前述定義。
- `R10` `✅` 須連同受測環境記載：驗證日期、所用工具與版本、執行身分或權限、目標 repo 或環境，以及其他會改變結果的條件。引用該格前先比對自己的環境與所記載者，有差異的項目重驗後再用，不沿用原狀態。記載的條件變更時（工具升版、權限或設定改變）該格依 `R9` 降為 `📝`。

## 6. 合併（M）

- `M1` 前提全部成立：測試綠；有效 verdict（`R3`）；候選的 base 是當下 main，或已 merge main 且重測、重審。
- `M2` 合併者依 `devflow.yml` 的 `merge`：`human` 由人按；`orchestrator` 只在有機械 guard 能驗 `M1` 時允許，否則視同 `human`。
- `M3` main 前進造成衝突：後合者 merge main 進自己的分支，重測、重審。
- `M4` 無文字衝突不等於無語意衝突；`M1` 的驗證對象是最終整合候選。

## 7. 失敗與退版（F）

- `F1` 實作未達 AC：同一 issue 修正；兩輪無進展升級到人。升級不等於放行。
- `F2` 規格錯或出現新依賴：暫停受影響任務，先修訂 T；無關任務繼續。不自動關單丟棄工作。T 的修訂由人在 issue 裁決方向，經 PR、依 G（舊版）審查後合入；第 2 節生效時額外走該節的規格程序，否則 T 可為 `docs/spec/` 下的草稿 commit（`version: 0.0.0.0`），以 issue 上寫的 commit 為準。
- `F3` forge 回錯或逾時：標「結果未定」，讀回 PR/MR 狀態、目標 sha、CI、分支後再決定；不盲目重送、不自行 bypass。
- `F4` 合併成功但收尾失敗：記 cleanup pending，只補收尾；不重做合併、不回滾已成功的實作。
- `F5` 撤回壞實作：revert PR（`git revert -m 1 <merge>` 產生 diff，仍走 `I3`）；規格仍正確就不撤規格。
- `F6` 已部署或涉及 migration：Git revert 不替代部署回復，另行處置相容的產物、配置與資料。

## 8. 收尾（C）

- `C1` 順序七步，每步判準成立才進下一步：(1) `git merge-base --is-ancestor <head> main` exit 0 → (2) 停止 coder 程序，已停與否依 `orchestrators/` 對照表判定 → (3) worktree 無需保留的未提交／未追蹤內容 → (4) `git worktree remove` → (5) 以步驟 (1) 所驗的同一 `<head>` 值（不重新讀取分支現值），`git update-ref -d refs/heads/<branch> <head>`：compare-and-delete，ref 已移動即拒絕；本步不驗合併狀態，與步驟 (1) 互補而非取代；不用 `git branch -d`／`-D` → (6) `git ls-remote --heads origin <branch>` 為空則跳過；非空則取其 OID，`git merge-base --is-ancestor <OID> main` exit 0 後 `git push origin --delete <branch>` → (7) `git ls-remote --heads origin <branch>` 為空＝成功。
- `C2` 關 issue；forge 自動關閉也要讀回驗證。
- `C3` 只清本次任務擁有的資源；其他活躍任務的 worktree、分支不動。blocked 或取消且成果未處置者保留並回報。
- `C4` 「`git worktree list` 只剩主目錄」是成功收尾的判準，不是強清命令。

## 9. 治理與規則變更（G）

- `G1` 每個任務記錄 G（本檔 commit）；PR 審查依 G 進行。
- `G2` 本檔的 normative 變更不依 `stage`，三項依序皆須：issue 記錄問題與人的裁決，裁決＝選定唯一處置 → 實作（本檔、模板、對照表、skill 都是實作）經 PR → 依 G（舊版，`G1`）由 fresh-context 審查（`R1`）通過後合入。第 2 節生效時額外要求規格前置核准，不取代前三項。候選版本不得放寬對自己的審查。
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
- `ST1` 單線：第 3～8、10 節生效；同時只有一個任務。
- `ST2` 規格建版：加上第 2、9 節；任務從規格推導。
- `ST3` 平行：加上第 12 節。
- `ST4` stage 只標示已驗證的能力，不是權限開關；降 stage 不放寬 main 保護、憑證或發布授權。
- `ST5` 保護節自 stage 0 起生效，不依 stage：第 5 節（R）、第 8 節（C）、第 9 節 `G1`～`G3`、`G5`。`G4` 例外，屬能力門檻，依 `ST2`。

## 12. 平行（P）

- `P1` 兩張任務同時活躍的前提（全部成立）：無阻塞依賴；write scope 不重疊；共用契約已在 main 且無人同時修改；外部資源可隔離。任一項不可判定 → 排序執行。
- `P2` 外部資源含 GPU、容器名、埠、資料目錄、image tag、部署環境。可平行編輯不等於可平行驗證或部署。
- `P3` 合併序列化；後合者適應（`M3`）。
- `P4` 不做 DAG／wave 排程器；`P1` 由 orchestrator 在派工時逐項確認並寫進 issue。

## 13. 文檔（D）

- `D1` 一個來源、兩種投影：`devflow/`（agent 讀，也渲染給人）、`docs/spec/`（agent 與人）、`docs/guide/`（只給人）。規範只有一份，指南引用它。
- `D2` 入口檔（CLAUDE.md／AGENTS.md）只擁有 `<!-- devflow:begin -->`…`<!-- devflow:end -->` 區塊，≤30 行；區塊須為入口檔的第一個 devflow 標記組，其前不得有任何 `<!-- devflow:begin -->` 或 `<!-- devflow:end -->` 行；區塊內容以 `devflow/templates/entry-block.md` 為準。區塊外是專案的內容，安裝與升級不得改動。
- `D3` 人類站依 `devflow.yml` 的 `docs.site`／`docs.versioning`；版本跟 kit release。wiki 不當投影目標。
- `D4` 超過 20 KB 的檔案不整份載入；先 `grep -n` 定位再局部讀。
