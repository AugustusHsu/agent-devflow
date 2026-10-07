---
name: devflow-orchestrator
description: "Use when devflow.yml binds seats.coordinator.filler to hermes"
version: 0.1.0
metadata:
  hermes:
    tags: [devflow, orchestrator, git-worktree, github, code-review, systemd]
---

# devflow orchestrator（Hermes）

本 skill 是 `devflow/WORKFLOW.md` 的流程實作：只寫「做什麼 → 依哪條規則」，條件內容不複述（`I5`）——要知道條件就翻 `WORKFLOW.md`。
語意以 issue 上寫的 G 為準，skill 與 G 衝突時 G 勝（`G1`、`G5`）。

對照表：`devflow/forges/<forge>.md`、`devflow/coders/<coder>.md`、`devflow/orchestrators/hermes.md`。引用任一格前先看狀態欄（第 0 節、`R9`、`R10`）。

## 一、觸發

- 專案根目錄有 `devflow.yml` 且 `seats.coordinator.filler` 為 `hermes`。
- 開工前讀 `stage`，只套用生效的節（`ST0`～`ST3`）；保護節依 `ST5`；stage 與權限的關係依 `ST4`。
- 每個任務兩個基準 G／T（第 0 節），以 issue 上寫的為準。
- 本檔改動的啟用邊界依 `G3`（`hermes.md` 「skill 啟用邊界（`G3`）」格；「session 開始載入」屬該表「已知事實」，待實測）。

## 二、單一任務生命週期（stage ≥ 1）

固定序 1→10，不跳步；`ST0` 直推 main，不走此流程。任一步失敗依第 7 節（F）處置，不自行 bypass（`F3`）。

**投影**：`launch: agent` 的填充者（`devflow.yml` 的 `seats.<位>.launch`）每一個工具呼叫，由協調平台的轉播機制即時投影到該單的對話通道——這是 runtime 行為，不依賴填充者自行播報，也不是誰要遵守的義務。派工者因此**不必**為進度另發訊息；需要人看見的只有里程碑：PR 開出、每輪 verdict、合併、收尾。投影的載體與格式（通道、訊息形狀、節奏）屬通道層 `channels/`（K4／`#258` 建），不在本檔規定。`launch: cli` 無投影——進度只落在 stdout 與 issue 留言，派工者要讓人看見什麼就得自己寫。

### 1. 開 issue（`L1`、`I4`）

- 用 `templates/issue.md`，欄位依 `L1`；G 填 commit sha，T 填規格 commit sha 或（治理／流程類）T 留言 id。
- 平行前提四欄 stage < 3 時依 `L1` 填；`P1`／`P4` 的判定 `ST3` 起。
- 命中 `L3` 停判準的政策問題先在 issue 留言裁決，再派工。

### 2. 建 worktree（`I1`、`I2`、`L2`）

主 checkout 執行，coder 只收路徑（`hermes.md` 「建 worktree（`I2`）」格、`coders/claude-code.md` 「worktree（`I2`）」格）：

```bash
git fetch origin && git branch <N>-<slug> origin/main
git worktree add ../<repo>.worktrees/<N> <N>-<slug>
git worktree list                                   # 含該路徑與分支
git -C ../<repo>.worktrees/<N> rev-parse HEAD       # 等於 base sha
```

### 3. 派 coder（`L2`；`hermes.md` 「派工（`L2`）」格）

以 Hermes `terminal(command="…", background=true)` 啟動，記下回傳的 pid。**不用 `delegate_task`**，不用 `setsid`（第六節）。

```bash
cd ../<repo>.worktrees/<N> && systemd-run --user --scope --unit=coder-<N> --collect -q \
  timeout <秒> claude -p "<prompt>" --output-format json --max-turns <turns> --allowedTools '<白名單>' \
  > <stdout 檔> 2> <stderr 檔> < /dev/null
```

- `--unit` 名稱是中斷把手；白名單以 `hermes.md` 「中斷交接」格所載為底，**不含** `systemd-run`／`systemctl`／`busctl`、`gh api`、`git push`（push 由 orchestrator 代行，步驟 6）。
- 啟動後依「派工」格讀回三項（`pstree -p`、`/proc/<pid>/cmdline`、`/proc/<pid>/cwd`）；**不用 `ps | grep 'claude -p'`**。headless 旗標對照 `coders/claude-code.md` 「headless 執行（`L2`）」格、「權限」格。
- prompt 必含（`L2`）：worktree 路徑、base sha、write scope、G／T、驗證指令、紀律（不 push、不開 PR、工具生成物依 `L3` 末段）、交付格式（含 `L3` 留言）；大檔明寫 `D4`。
- 派工後在 issue 留言記派工紀錄三項（鏡射 `L1`，不加該條沒有的義務）：coder／reviewer 的**完整啟動指令**（含版本旗標與工具版本）、`session_id` 或同等識別、**驗證指令的輸出原文**（首行 JSON、`-o` 全文、review id 與比對結果等；只寫「正常」「通過」等結論不構成紀錄）。輸出原文只證明驗證方式曾實跑並供核對，對照表狀態仍須另滿足 `R8`（第四節）。

### 4. coder 撞 `--max-turns`（`coders/claude-code.md` 「交接（`--resume`）」格）

1. 看工作區：`git -C <worktree> status --porcelain`、`git -C <worktree> log --oneline <base>..HEAD`。
2. 取 `session_id`：stdout JSON；被 SIGTERM 則依 `hermes.md` 「中斷交接」格從 `~/.claude/projects/<cwd 路徑編碼>/` 取。
3. 確認舊 coder 已停：`systemctl --user is-active coder-<N>.scope`，判定依 `hermes.md` 「中斷交接」格。
4. 同一套 `systemd-run` 包裝、同一 OS 使用者：`claude -p "<剩餘步驟＋turn 上限>" --resume <session_id> …`；prompt 明寫「你被中斷過，先讀工作區狀態」。

### 5. 複驗（`R6`、`G5`）

- 跑 issue 的驗證指令，貼原始輸出；證據可定位性依 `R6`。
- `git -C <worktree> diff --name-only <base>..HEAD` 對 write scope；夾帶物依 `G5` 標出。
- coder 的 `L3` 留言逐項判：停 → 問人、答案寫回同一 issue、重派；續 → 接受，或在 PR 留言記處置。
- 動到對照表的格 → 第四節。

### 6. push ＋ 開 PR（`L4`、`G1`、`R3`）

```bash
git -C ../<repo>.worktrees/<N> push -u origin <N>-<slug>
gh pr create --base main --head <N>-<slug> --title "<gitmoji> <type>(<scope>): <標題>" --body-file <填好的 templates/pr.md>
```

- coder 白名單不含 `git push`，`L4` 的 push 與開 PR 由 orchestrator 代行（`forges/github.md` 「開 PR」格）。
- body 用 `templates/pr.md`；head sha 每次 push 後更新（`R3`）；coder 回報的缺口寫進 body 並附 orchestrator 判定。

### 7. 派審（`R1`、`R2`、`R4`、`R6`）

**派審者依綁定**：`devflow.yml` 的 `seats.manager` 已綁定時由 manager 派（`seats/manager.md`），未綁定時該職責歸協調位，由協調位自派——不寫死為協調位。

兩種 `launch` 共通的前置：fresh context、與實作位異廠——`R2` 的異廠是**建議**不是必需：只有一家可用時用同廠的全新 context，同廠時另建議所用模型與實作位（`seats.implementer.model`）不同、同廠只有一個堪用模型時全新 context 即滿足（`seats/reviewer.md` 的例外分支同此）、丟棄式 checkout（`R12`；`coders/codex.md` 「審查用法（`R1`）」格，引用前查狀態 `R9`）。**單級暫存目錄、本輪專用暫存目錄與丟棄式 checkout 一律由派工者建立**，建好後把三個路徑寫進 prompt 的材料段；**審查位不自建**，收到的就是派工者建好的路徑（第 10 步守衛即以此為前提）。

三個暫存目錄的尺度不同，建立與回收的時點也不同——混用就是 `#251`／`#258` 兩輪「驗收腳本放第 1 輪的輪級目錄、第 2 輪沒得用」的來由：

| 變數 | 尺度 | 目錄名 | 建於 | 回收於 |
|---|---|---|---|---|
| `$W` | 單級（整張 issue，跨輪復用） | `devflow-task.$ISSUE.??????` | 第 1 輪的第 7 步，其後各輪沿用 | 第 10 步守衛 |
| `$T` | 輪級（本輪） | `devflow-rev.$TOKEN.??????` | 每輪的第 7 步 | 該輪的第 8 步 |
| `$D` | 輪級（本輪，丟棄式 checkout） | `devflow-co.$TOKEN.??????` | 每輪的第 7 步 | 該輪的第 8 步 |

以下依被派那一位的 `launch` 分支（`devflow.yml` 的 `seats.reviewer.launch`，省略時為 `cli`）。

#### launch: cli

```bash
mkdir -p -m 700 -- "${TMPDIR:-$HOME/.cache}"
ISSUE=<issue>                  # 本單 issue 號，例：255；僅 [0-9]，由派工者填；嵌進 $W 的目錄名，第 10 步守衛以它核對「這個目錄屬本單」
TOKEN=<issue>r<round>          # 本輪 token，例：255r1；僅 [A-Za-z0-9]，由派工者填；嵌進下兩行的目錄名，第 8 步與第 10 步守衛以它核對「這兩個目錄屬本輪」
W=$(mktemp -d "${TMPDIR:-$HOME/.cache}/devflow-task.$ISSUE.XXXXXX")  # 單級暫存目錄；整張單共用、跨輪沿用（第 2 輪起沿用第 1 輪建的那個，不重建）；第 8 步不回收，第 10 步守衛刪
T=$(mktemp -d "${TMPDIR:-$HOME/.cache}/devflow-rev.$TOKEN.XXXXXX")   # 本輪專用暫存目錄；`TMPDIR` 未設時落在 `$HOME/.cache`，不落 /tmp 本身（`TMPDIR` 指向 /tmp 時須先改設）；第 8 步刪
D=$(mktemp -d "${TMPDIR:-$HOME/.cache}/devflow-co.$TOKEN.XXXXXX")    # 丟棄式 checkout，同上不落 /tmp 本身；第 8 步刪
git clone --shared <repo> "$D" && git -C "$D" checkout <head sha>
env TMPDIR="$T" codex exec -C "$D" --sandbox workspace-write -m <model> -c model_reasoning_effort=<level> \
  -c approval_policy="never" -c sandbox_workspace_write.exclude_slash_tmp=true \
  -c sandbox_workspace_write.network_access=false \
  -c 'sandbox_workspace_write.writable_roots=["'"$D"'","'"$T"'","'"$W"'"]' \
  -o "$T/verdict.md" - < "$T/prompt.txt"
```

#### launch: agent

派給協調平台上的具名實例（`devflow.yml` 的 `seats.reviewer.instance`），由轉播器喚醒；三個暫存目錄與 checkout 由派工者照下方 block 建好，審查稿寫進 `$T`，三個路徑寫進審查稿的材料段。

```bash
mkdir -p -m 700 -- "${TMPDIR:-$HOME/.cache}"
ISSUE=<issue>                  # 同 cli：僅 [0-9]，由派工者填；第 10 步守衛以它核對 $W 屬本單
TOKEN=<issue>r<round>          # 同 cli：僅 [A-Za-z0-9]，由派工者填；第 8 步與第 10 步守衛以它核對兩個輪級目錄屬本輪
W=$(mktemp -d "${TMPDIR:-$HOME/.cache}/devflow-task.$ISSUE.XXXXXX")  # 單級暫存目錄；跨輪沿用，第 2 輪起沿用既有那個；第 10 步守衛刪
T=$(mktemp -d "${TMPDIR:-$HOME/.cache}/devflow-rev.$TOKEN.XXXXXX")   # 本輪專用暫存目錄；第 8 步刪
D=$(mktemp -d "${TMPDIR:-$HOME/.cache}/devflow-co.$TOKEN.XXXXXX")    # 丟棄式 checkout；第 8 步刪
git clone --shared <repo> "$D" && git -C "$D" checkout <head sha>
env TMPDIR="$T" ~/.hermes/scripts/devflow_relay.py <thread> --file "$T/prompt.md" \
  -p <instance> --issue <N> --fresh --pace quiet --then-wake <派工者自己的 instance> \
  [-m <model> --provider <name>]
```

- `--fresh` **不可省**：`R1` 要求每輪 fresh context。具名實例的 session 會累積，省掉即延續前一輪審查位的 context——前輪的判斷與取捨跟著進本輪，`R1` 要的「每輪全新」就不成立。
- `--then-wake` **不可省**：帶 `--issue` 即表示這一輪屬某張單的執行流程，轉播器會**拒絕**未帶者（`#298` `AC-3`：rc 非 0、一個子程序都不派）。其值是**派工者自己**的 instance 名，**不是** `<instance>`——那是審查位。理由：子程序退出後要喚醒的是派工者，以續接 verdict 處理（第 8 步）；填成審查位即喚醒剛結束的那一位，續接的那一步沒有人做。該值與 `ISSUE`／`TOKEN`／`-p <instance>` 同為「由派工者填」的占位符（`SKILL.md` 的讀者是 orchestrator，它不知道自己的 profile 名，故此處不寫死）。
- `--pace quiet`：避免審查位的投影與派工者自己的投影在同一通道交錯（第二節「投影」）。
- 沙箱依 `R12`：可寫根收斂到該 checkout ＋本輪暫存目錄；平台設不起可寫根收斂時，該輪改**唯讀**執行，並於派工 prompt 與 verdict 留言**雙方註明**（`R12`）——「不得自行升權」不因此豁免。
- `-m`／`--provider` 只在換模型時帶。verdict 的受測環境依 `R10` 寫**當次實際使用的**模型與 provider，不得照抄 `devflow.yml` 的預設綁定。
- 配額撞到時的形狀與判定依第七節（依 `launch` 分支）。
- `env TMPDIR="$T"` **不可省**：被喚醒的實例預設把暫存寫進自己 profile 的 scratch，不符第 10 步守衛的命名約定，守衛刪不到。`TMPDIR` 經 `env` 傳給 `hermes … chat --oneshot`（含經轉播器）被遵從——受測環境依 `R10` 記在 #251 AC-4，**引用前自行複驗**。
- `R12` 第 3 項的 `git diff` 另存位置是 `$T`，不是派工者自己的 scratch。`$D` 與 `$T` 同在第 8 步被 `rm -rf`——verdict 之後 checkout 已不在是 `R12`「隨暫存目錄丟棄」要的行為，不是缺陷。

#### 產物落點（反向規則）

本次執行期間產生的**任何**檔案，一律寫在 `$W`（單級）或 `$T`（輪級）之下。這兩個目錄就是 `C5` 第一項所稱**該單的專屬子目錄**：`$W` 是單級那一層（目錄名嵌 `$ISSUE`）、`$T` 是該單本輪的輪級那一層（目錄名嵌 `$TOKEN`，而 `$TOKEN` 的形狀是 `<issue>r<round>`），兩者皆專屬本單、皆在 `C5` 第一項的判準射程內（`$D` 同此，見上表）。**射程與例外由 `C5` 第一項定義，本節複述不另立**；本節定義的是這些變數的目錄名、尺度與回收時點。只有三類例外，與 `C5` 第一項的 (1)(2)(3) 逐項對應：
(1) 被審 checkout `$D` 與任務 worktree 內的工作樹改動；
(2) 寫進 forge 的留言與 PR 內容；
(3) `.hermes/plans/` 下的提案檔（本 repo 慣例，不 commit）。
判斷方式：不問「這是什麼類型的產物」，只問「這是我這次執行產生的嗎」。是，就在上述兩個目錄裡；在上述目錄外且不屬三類例外的，即違規。反過來，收尾時 `C5` 第一項的判準即「該單的專屬子目錄不存在」——逐一斷言 `$W`／`$T`／`$D` 不存在（第 8 步與第 10 步守衛即此），**不列舉、不清理暫存根下的其他內容**：那裡有他單的目錄與 runtime 的活體資源（`C3`）。

尺度的選法只看「下一輪還要不要用」：整張單共用的（驗收腳本、交接稿、工作 clone、突變對照）寫 `$W`，只有本輪意義的（prompt、verdict、本輪 diff patch）寫 `$T`。

本規則是**反向**的，取代舊的正向列舉（原措辭只逐字列了審查稿與 diff patch 兩項）。理由：`#251`／`#258` 兩輪實測下來，派工者把條文列出的那兩項放進輪級目錄、其餘全落自己 profile 的 scratch（兩輪共清出 28 項，含完整 repo clone `devflow-probe.258.*`），而把列舉從兩項擴成七項只是把邊界推到第七項之後。規則因此規定「什麼不必寫進去」，而非「什麼要寫進去」——例外是封閉集合，可逐項機械檢查；落點的判定是二元問題，不需派工者推論產物的類型。

#### prompt（兩段共用）

prompt 以 `templates/review-prompt.md` 為底，另加：
- 「已判通過不重審」清單（前輪 PASS 且該處 diff 未變）與「逐條要判」清單。
- verdict 開頭 `APPROVE`／`REQUEST_CHANGES`、寫明 head sha（`R3`）；一格不通過不阻擋其他格的判定。
- 功能 PR：審查者自構輸入逐條 AC 找反例，不以 coder 的 harness 輸出為證據（`R4`、`R6`）。
- `-m` 是萃取當時的模型名，依當下可用者換。
- **模板的每一項都要進 prompt**：`R4` 寫「用 `templates/review-prompt.md`」，「以它為底」指全文納入後再加上列各項，不是取其要旨自行改寫。自寫 prompt 會靜默漏掉模板的條目——#229 所記的三張單即因四輪審查全自寫，模板當時的留痕核對項從未進入審查位視野。

### 8. verdict 處理（`R3`、`R5`、`F1`、`F2`）

- 完整 verdict 貼成 PR 留言（`R5`；`forges/github.md` 「審查證據（`R3`／`R5`）」格），另一則留處置表：每條阻擋項標 `FIX`／`DEFER`／`REJECT` 並附 `R11` 要求的依據，並在同一則記 `R13` 的續審判定行與「續審」(a)(b)(c) 三項依據；該留言 URL 記入 issue「審查處置」段。
- `REQUEST_CHANGES` 分兩類：
  - 實作阻擋 → coder `--resume` 修（步驟 4；`F1`）。
  - T 的漏洞 → 依 `F2`。Hermes 側：問人、答案寫回原 issue（`L3` 通道）→ T 修訂作為新任務走步驟 1～10（新 issue／分支／worktree；原分支已承載開啟中的 PR，不再開第二張；原任務 coder 已停、worktree 依 `C3` 保留）→ 合入後把原 issue 的 T 更新為新 commit、影響分析留言 → 重派原任務。
- head 變更後重審（`R3`）；下一輪 prompt 縮窄到變更處＋未通過的 AC。
- `APPROVE` → 步驟 9。
- **回收本輪的輪級暫存目錄**：verdict 處理完畢（上列各項都已做完、下一輪尚未派出）即刪第 7 步建的 `$T`（`devflow-rev.$TOKEN.??????`）與 `$D`（`devflow-co.$TOKEN.??????`），`R12` 的「隨暫存目錄丟棄」在此生效。下方區塊可直接照抄實跑，它是第 10 步守衛本體的可執行副本（程式碼逐行相同，只有呼叫參數不同），**不是另寫一支 `rm -rf`**——那會是第二條、且較弱的刪除路徑，而守衛存在的理由就是占位填錯＝`rm -rf` 打在別處。**`$W` 不在本步回收**——它是單級的，下一輪要沿用（驗收腳本、交接稿、工作 clone 都在裡面），其回收在第 10 步守衛。回收與否不影響續審：下一輪 prompt 的「已判通過不重審」清單是 prompt 的一部分、由派工者派審時寫進去，不是 `$T` 裡的檔案（`R3`）。需留存的 verdict 原文此時已貼成 PR 留言（`R5`），forge 是權威。

```bash
# 本輪的輪級回收。下面是第 10 步 (0) 守衛本體的**可執行副本**：程式碼逐行相同，
#   唯一的差異是末行的呼叫參數——占位 1、2 填本輪的 $T／$D，占位 3 填 `-`（$W 跨輪沿用、
#   不在本步回收，其回收在第 10 步）。每一項判準的理由、符號與反例原文見第 10 步，此處不重述。
# 為何整段複製而非在本步只留一行指引：第 8 步要能照抄實跑（前一版只有兩個 ls 後置檢查，照它執行不刪任何東西，
#   PR #284 第 1 輪 BLOCK 1），而 kit 不帶可 source 的腳本檔（SKILL.md 是條文，不是套件），故副本是唯一能
#   同時滿足「本步自身可執行」與「不另立第二條較弱的刪除路徑」的形狀。代價是兩份要同步，以機械核對綁住：
#   兩份的非註解行必須逐行相同、差異只許出現在呼叫行（' _ 那行）。核對指令：
#   /usr/bin/python3 - devflow/orchestrators/hermes/SKILL.md <<'PY'
#   import re,sys
#   d=open(sys.argv[1]).read()
#   def g(n):
#       s=re.search(r"^### %d\..*?(?=^### \d+\.|\Z)"%n, d, re.S|re.M).group(0)
#       b=[x for x in re.findall(r"```bash\n(.*?)\n```", s, re.S) if "/usr/bin/env -i" in x][0]
#       v=[l for l in b.split(chr(10)) if not l.lstrip().startswith("#")]
#       return v[:v.index(")")+1]   # 只比守衛本體，不含其後的後置檢查
#   a,b=g(8),g(10)
#   diff=[(x,y) for x,y in zip(a,b) if x!=y]
#   ok = len(a)==len(b) and len(diff)==1 and diff[0][0].startswith("' _ ")
#   print("一致（差異僅呼叫行）" if ok else "已漂移：%r"%(diff or (len(a),len(b))))
#   PY
(
  /usr/bin/env -i \
    HOME="$HOME" TMPDIR="${TMPDIR:-}" PATH=/usr/bin:/bin \
    /bin/bash --noprofile --norc -c '
  set -u
  [ $# -eq 4 ] || { echo "須恰三個占位路徑＋本輪 token，停" >&2; exit 1; }
  TOKEN=$4
  case "$TOKEN" in
    "" | *[!A-Za-z0-9]*) echo "本輪 token 須非空且僅含 A-Za-z0-9，停：$TOKEN" >&2; exit 1 ;;
  esac
  ISSUE=${TOKEN%%r*}
  case "$ISSUE" in
    "" | *[!0-9]*) echo "由 token 推導的 issue 號須非空且僅含 0-9，停：$ISSUE（token=$TOKEN）" >&2; exit 1 ;;
  esac
  NL=$(printf "\nx"); NL=${NL%x}
  strip() {
    SS=$1
    while :; do
      case "$SS" in ?*/) SS=${SS%/} ;; *) break ;; esac
    done
  }
  ROOT="${TMPDIR:-$HOME/.cache}"
  strip "$ROOT"; RA=$SS
  [ -n "$RA" ] || { echo "暫存根為空，停" >&2; exit 1; }
  inum() {
    IN=$(ls -dLi -- "$1" 2>/dev/null) || { IN=; return 1; }
    while :; do case "$IN" in " "*|"	"*) IN=${IN#?} ;; *) break ;; esac; done
    IN=${IN%% *}
    case "$IN" in "" | *[!0-9]*) IN=; return 1 ;; esac
    return 0
  }
  case "$ROOT" in
    /*) RABS=$ROOT ;;
    *)
      CWD0=$(pwd -P && printf x) && CWD0=${CWD0%x} || CWD0=
      [ -n "$CWD0" ] || { echo "無法取得目前工作目錄，停" >&2; exit 1; }
      CWD0=${CWD0%"$NL"}
      RABS=$CWD0/$ROOT
      ;;
  esac
  CDPATH= cd -P -- "$ROOT" || { echo "無法進入暫存根：$ROOT" >&2; exit 1; }
  inum /proc/self/cwd/. || { echo "無法取得暫存根 inode（cwd）：$ROOT" >&2; exit 1; }
  IPIN=$IN
  inum . || { echo "無法取得釘住後的 inode，停" >&2; exit 1; }
  ICWD=$IN
  if [ "$IPIN" != "$ICWD" ]; then
    echo "釘住的目錄與 /proc/self/cwd 不一致（$IPIN vs $ICWD），零刪除中止" >&2; exit 1
  fi
  inum "$RABS" || { echo "暫存根在守衛執行期間消失，零刪除中止：$ROOT" >&2; exit 1; }
  IPATH=$IN
  if [ "$IPIN" != "$IPATH" ]; then
    echo "暫存根在守衛執行期間被換掉（釘住 inode $IPIN、路徑此刻指向 inode $IPATH），零刪除中止" >&2; exit 1
  fi
  RB=$(pwd -P && printf x) && RB=${RB%x} || RB=
  [ -n "$RB" ] || { echo "無法取得暫存根的真實路徑，停" >&2; exit 1; }
  RB=${RB%"$NL"}
  case "$RB" in
    /*) : ;;
    *) echo "暫存根真實路徑非絕對路徑，停：$RB" >&2; exit 1 ;;
  esac
  case "$RB" in *"$NL"*) echo "暫存根真實路徑含換行，停" >&2; exit 1 ;; esac
  strip "$RB"; RB=$SS
  chk() {
    CP=$1; ROLE=$2; IDX=$3; CRP=
    if [ -z "$CP" ]; then echo "占位 $IDX 為空路徑，停" >&2; return 1; fi
    case "$CP" in *"$NL"*) echo "占位 $IDX 路徑含換行，停" >&2; return 1 ;; esac
    strip "$CP"; CPS=$SS
    CPN=${CPS##*/}
    case "$ROLE" in
      rev) case "$CPN" in devflow-rev."$TOKEN".??????) : ;;
             *) echo "占位 $IDX 末段非該位合法名（須 devflow-rev.$TOKEN.??????），停：$CP" >&2; return 1 ;; esac ;;
      co)  case "$CPN" in devflow-co."$TOKEN".??????) : ;;
             *) echo "占位 $IDX 末段非該位合法名（須 devflow-co.$TOKEN.??????），停：$CP" >&2; return 1 ;; esac ;;
      task) case "$CPN" in devflow-task."$ISSUE".??????) : ;;
             *) echo "占位 $IDX 末段非該位合法名（須 devflow-task.$ISSUE.??????），停：$CP" >&2; return 1 ;; esac ;;
      *) echo "占位 $IDX 角色代號有誤（只收 rev／co／task），停" >&2; return 1 ;;
    esac
    strip "${CPS%/*}"; CPP=$SS
    if [ "$CPP" != "$RA" ] && [ "$CPP" != "$RB" ]; then
      echo "占位 $IDX 前綴非暫存根字面（須 $RA），停：$CP" >&2; return 1
    fi
    if [ -L "$CPN" ]; then echo "占位 $IDX 是 symlink，停：$CP" >&2; return 1; fi
    if [ ! -d "$CPN" ]; then echo "占位 $IDX 不是現存目錄，停：$CP" >&2; return 1; fi
    CRP=$CPN
    return 0
  }
  BAD=; RP1=; RP2=; RP3=; SKIP1=; SKIP2=; SKIP3=
  if [ "$1" = "-" ]; then SKIP1=1; else if chk "$1" rev 1; then RP1=$CRP; else BAD=1; fi; fi
  if [ "$2" = "-" ]; then SKIP2=1; else if chk "$2" co 2; then RP2=$CRP; else BAD=1; fi; fi
  if [ "$3" = "-" ]; then SKIP3=1; else if chk "$3" task 3; then RP3=$CRP; else BAD=1; fi; fi
  if [ -n "$SKIP1" ] && [ -n "$SKIP2" ] && [ -n "$SKIP3" ]; then
    echo "三個占位都填 -，沒有要回收的對象，停" >&2; BAD=1
  fi
  if [ -n "$RP1" ] && [ "$RP1" = "$RP2" ]; then echo "占位 1 與 2 指向同一目錄，停：$RP1" >&2; BAD=1; fi
  if [ -n "$RP1" ] && [ "$RP1" = "$RP3" ]; then echo "占位 1 與 3 指向同一目錄，停：$RP1" >&2; BAD=1; fi
  if [ -n "$RP2" ] && [ "$RP2" = "$RP3" ]; then echo "占位 2 與 3 指向同一目錄，停：$RP2" >&2; BAD=1; fi
  [ -z "$BAD" ] || { echo "有占位未通過驗證，零刪除中止" >&2; exit 1; }
  RC=0
  [ -n "$SKIP1" ] || rm -rf -- "$RP1" || { echo "刪除失敗：$RP1" >&2; RC=1; }
  [ -n "$SKIP2" ] || rm -rf -- "$RP2" || { echo "刪除失敗：$RP2" >&2; RC=1; }
  [ -n "$SKIP3" ] || rm -rf -- "$RP3" || { echo "刪除失敗：$RP3" >&2; RC=1; }
  exit $RC
' _ "<第 7 步的 $T>" "<第 7 步的 $D>" "-" "<本輪的 $TOKEN>"
)
RC8=$?
# 後置檢查：守衛的 rc 與三項「正面斷言」以 && 串接，整段最終 exit 即本步的機械判定
#   （與第 10 步 `C1` 段同一慣例：判定鏈以 && 串接，整段貼入與逐行執行結果相同）。
# RC8 必須先接進判定鏈：守衛失敗時是「零刪除、rc 非 0」，若只看目錄存留，
#   裸 ls 會讓整段最後回 0，把零刪除的失敗讀成成功（PR #284 第 2 輪 BLOCK 1）。
# 三項各自斷言、不混在一個 ls 裡：一個混合 ls 的非 0 只代表「至少一個不存在」，
#   不足以證明 $T 與 $D 皆已刪——兩者都要逐一正面斷言不存在。
[ "$RC8" = 0 ] \
  && [ ! -e "<第 7 步的 $T>" ] \
  && [ ! -e "<第 7 步的 $D>" ] \
  && [ -d "<第 7 步的 $W>" ] \
  && echo "第 8 步輪級回收完成（\$T／\$D 已刪、\$W 仍在）" \
  || { echo "第 8 步輪級回收未完成（守衛 rc=$RC8），停：依 F4 補，不重跑合併" >&2; false; }
```

### 9. 合併（`M1`～`M4`、`I3`、`R5`）

前提依 `M1` 逐項驗；main 前進依 `M3`、`M4`；合併者依 `M2`。

```bash
gh pr merge <PR-N> --merge --subject "<gitmoji> merge(#<N>): <一句話>" \
  --body "PR #<PR-N>; reviewer <審查者與模型>; head <head sha>
M2: <誰按、依據什麼授權>"
```

gitmoji 依變更性質選。對照 `forges/github.md` 「合併（`I3`）」格（`--match-head-commit <head sha>` 不在該格實測範圍）。

### 10. 收尾（`C1`～`C4`、`F4`）

`C1` 七步之前先執行 (0) 刪本單與本輪的暫存目錄——第 7 步建的 `$W`、`$T`、`$D` 在此回收（`R12` 「隨暫存目錄丟棄」）。**正常路徑下 `$T`／`$D` 已在第 8 步回收，本步占位 1、2 填 `-`、只收 `$W`**；若某輪的第 8 步漏做（`$T`／`$D` 仍在，多輪時尤易，依 `F4` 補），該輪的兩位改填真實路徑並帶**該輪**的 `$TOKEN`，與 `$W` 一併回收。兩種寫法見下方呼叫行。

占位 1、2 填 `-` 時 `$TOKEN` **仍必填**：占位 3 的 `$ISSUE` 由它推導（`${TOKEN%%r*}`），少了它就無從核對 `$W` 屬本單。填的是哪一輪的 token 不影響本步——同一張單各輪的 token 推出同一個 issue 號。

三者皆不跨段保留，占位與 `$TOKEN` 由執行者填入，**填錯就是 `rm -rf` 打在別處**，故刪除前逐一驗證（token 嵌在輪級目錄名裡，故另一輪的目錄會因 token 不符被擋；`$W` 的 issue 號由 token 推導，故他單的 `$W` 一律不命中）：

本守衛的前提是**第 7 步**共用前置的「暫存與 checkout 由派工者建立」——三個占位的值即該步 `mktemp -d` 的輸出，名稱因此必然帶 `devflow-task.$ISSUE.`／`devflow-rev.$TOKEN.`／`devflow-co.$TOKEN.` 前綴並落在同一個暫存根下。`launch` 不改變這個前提：`launch: agent` 的填充者在被喚醒時收到的是派工者建好的路徑，**不自建暫存根**（它自己的快取路徑不符本守衛的命名約定，若讓它自建，這整段檢查就無從套用）。

```bash
# (0) 刪本單與本輪的暫存目錄。第 7 步建的 $W（devflow-task.$ISSUE.??????）、
#     $T（devflow-rev.$TOKEN.??????）與 $D（devflow-co.$TOKEN.??????）在此回收。
# 三個占位的角色綁位：占位 1 只收 rev、占位 2 只收 co、占位 3 只收 task；任兩者對調即失敗。
# 占位 3 的 issue 號不另傳參數，由本輪 token 推導（ISSUE=${TOKEN%%r*}）：另傳一個 issue 號會讓
#   「占位 3 屬於哪張單」變成可獨立填錯的一項——填成別單時刪掉的是他單仍在用的 $W（跨輪復用，無從重建）。
#   由 token 推導使「$W 與 $T／$D 同屬一張單」成為結構保證，不靠執行者填對兩個相容的值。
# 占位可整位略去：**任一占位填 `-` 即「本次不收該位」**，對它不驗、不刪；三位不得同時為 `-`。
#   兩種用法：第 10 步的正常路徑填 "-" "-" "<$W>"（$T／$D 已在第 8 步回收）；第 8 步的輪級回收
#   填 "<$T>" "<$D>" "-"（$W 跨輪沿用、不在該步回收）。某輪第 8 步漏做時，第 10 步三位全填真實路徑補收。
#   `-` 不可能是合法占位（末段須命中角色樣式），故不與正常值混淆。這是明示的「本步不收這一位」，
#   不是「已不存在就算成功」（後者是 #251 判定的缺陷：占位填成不存在的合法名時照刪其餘位再回 0）。
#   兩者的差別是誰說的：填 `-` 是呼叫者明示不收；填一個不存在的合法名是呼叫者說要收、而它不在——
#   後者必須 rc 非 0 零刪除（可能填錯了輪或填錯了單），不能靜默當成功。
# 輸入格式白名單（不逐元件追查 symlink）：占位剝盡尾斜線後須恰為 <暫存根>/<該位的合法名>——最後一段命中該位角色樣式、去掉最後一段的前綴字面等於暫存根、該路徑本身非 symlink。三項全中才算合法，對三個占位一律套用。
# 先以 cd -P 釘住暫存根（cwd 由核心持有該目錄的 inode 參照，#272），之後碰檔案系統的動作（-L、-d、rm）全用相對名：$ROOT 可以是 symlink，若拿完整路徑去刪，symlink 可在驗證與 rm 之間被重新指向，rm 就打到另一個 root 底下同名而「從未驗證」的目錄（實測 bash 與 dash 皆可重現）。cd 綁的是當時那個目錄的 inode，事後改 symlink 不影響相對名解析——窗口是關掉，不是縮小。
# 為何走白名單不逐元件追查：readlink -f 會把 <symlink>/.、<symlink>/./、<中間 symlink>/<合法名> 都解析成同根下一個「合規的」目錄並刪掉它，而逐元件檢查須區分 <symlink>/. 與 <普通目錄>/.（兩者解析結果都合法），成本高且易誤擋合法邊界。占位本應由第 7 步原樣填入，迂迴寫法不是正常用法。
# 行為收窄（刻意）：<合法名>/. 與 <合法名>/./ 即使是普通目錄也一律擋，因為最後一段是 . 不是合法名。<合法名>／<合法名>/／<合法名>/// 三種寫法仍可用——差一個 . 而已，別用會連尾斜線一起擋的粗判準。
# 暫存根有兩個可接受的字面值：$ROOT 原值與「釘住後 pwd -P 給的真實路徑」（TMPDIR 指向 symlink 時兩者不同，都得接受，否則正常路徑會被誤擋）。兩者都要剝盡尾斜線：TMPDIR=/foo/ 時第 7 步產生的占位是 /foo//devflow-rev.$TOKEN.xxxxxx，前綴為 /foo/，不剝就比不等。
# 後者務必在 cd 之後以 pwd -P 取，不可在 cd 之前用 readlink -f -- "$ROOT"：$ROOT 若在 readlink 與 cd 之間被改指（A→B），該值留著舊 root A 而 cwd 已是 B，指向 A 的占位會比對舊值通過驗證，-L／-d／rm 卻全打在 B，刪掉 B 底下從未驗證的目錄（實測 bash 與 dash 皆可重現）。pwd -P 問的是已釘住的 inode，不重走 $ROOT。
# 「暫存根是否被換掉」用「釘住的 cwd」與「此刻重新解析 $ROOT」兩個 inode 比對，不用 pathname 字串、也不用 cd 前後兩次路徑解析的 inode：同一性判定前後被推翻三次（canonical pathname 在 cd 前取→cd 前改指；pathname 字串→同名重建 inode 不同；inode 編號→rmdir 後核心立即重用同一 inode，ext4 實測三次皆重用），共通根因是每次 ls／readlink 都重新解析路徑、每次解析都是新的 TOCTOU 窗口，比對哪個屬性都只是把窗口推到下一個屬性。cwd 在 cd 當下綁定 inode 且行程結束前不放掉參照，新建目錄拿不到同一個 inode，這條路是結構性堵住的（#272 受控對照：不持有 重用=Y ×3、持 cwd 重用=N ×3）。#253 原以 exec 9< 持有目錄 fd 達成同一效果，#272 改為 cwd：open(O_RDONLY) 需讀權限，mode 0311 的暫存根會被誤擋（N3），而 cd 只需 x 權限；且 cd 到 FIFO 立即失敗，不像 open 會掛住（N2）。/proc/self/cwd 為 Linux 特有（守衛已依賴 GNU readlink -f、ls -di 等非 POSIX 行為，此依賴不新增負擔，但只保證在 Linux 成立）。
# 兩段式，先驗完再刪：三個占位全部通過（非空、不含換行、合白名單、非 symlink、須為現存目錄、兩兩相異；填 `-` 的那位略過驗證與刪除）才進刪除；任一不合法 → 零刪除、rc 非 0。
# 「零刪除」的範圍限於驗證階段：驗證未全過就一個都不刪。進入刪除階段後各 rm 都會執行，其一失敗（例如權限）只使 rc 非 0，不會回滾另一個已刪的——刪除本身不是交易。
# 角色樣式寫死在 case 的 pattern 位置、不經參數傳遞：樣式若當參數傳，呼叫點會做 pathname expansion，cwd 內有字面同形目錄（devflow-rev.******）時樣式會被換成該目錄名，不合法的短名就會被放行。本輪 token 與由它推導的 issue 號是唯二來自參數的樣式片段，故它們在 pattern 位置必須加引號（devflow-rev."$TOKEN".??????、devflow-task."$ISSUE".??????）：加引號時其內容只當字面比對，不加引號時 TOKEN=* 會變成萬用樣式、同根下任何一輪的目錄全部放行——與上述同類的錯誤。
# 尾斜線先剝盡才測 -L：[ -L "<link>/" ] 回假（尾斜線要求解析到目標），symlink 帶尾斜線會漏過 symlink 閘門。
# 「已不存在就算成功」是缺陷不是寬容（#251）：占位 2 填成不存在的合法名時，舊版會照刪占位 1 再回 0，看起來成功、實際漏刪。
# 角色綁位：占位 1 只收 devflow-rev.$TOKEN.??????、占位 2 只收 devflow-co.$TOKEN.??????、占位 3 只收 devflow-task.$ISSUE.??????，任兩者對調即失敗。
# 守衛本體在 /usr/bin/env -i 造的空環境裡由 /bin/bash 執行，內層 PATH 固定；三個占位與本輪 token 以位置參數 $1／$2／$3／$4 傳入，不再內插進指令字串。
# 不加 command 前綴：BASH_FUNC_command%% 注入會穿透 command 前綴（實測），直接寫 /usr/bin/env 才擋得住。
# 跨輪核對靠目錄名裡的 token（#255）：第 7 步把本輪 token 嵌進兩個輪級目錄名，守衛以第四個位置參數收到同一個 token 並當成角色樣式的一部分，故同根下另一輪的 devflow-rev.<別的 token>.??????／devflow-co.<別的 token>.?????? 不命中樣式、一律被擋。正面核對，不需任何持久記錄。
# 跨單核對靠目錄名裡的 issue 號：占位 3 的樣式用 ISSUE=${TOKEN%%r*}，故他單的 devflow-task.<別的 issue>.?????? 不命中樣式、一律被擋（`C3` 「只清本次任務擁有的資源」在本步的落實）。
# token 先驗字元集（非空且僅 [A-Za-z0-9]）再當 pattern 用，順序不可反：未驗就用時 TOKEN=* 會變萬用樣式（見上一條角色樣式的註解），而限死 [A-Za-z0-9] 也使 token 不可能夾帶斜線、點或 glob 字元去撐出額外的路徑層級。
# token 填錯的假陽性（刻意接受）：填成別輪或打錯字時，本輪的合法目錄不命中樣式 → rc 非 0、兩個目錄都存活、清不掉，須改對 token 再跑。方向安全（不誤刪），代價是漏刪要人回頭處理。
# 占位務必加引號（未加時含 glob 的路徑會展開，實測會多刪同根下別輪的目錄）。
# 占位在雙引號內：路徑含 $、反引號、雙引號、反斜線時須先跳脫——指令替換會在任何判定之前執行（實測含 $(…) 的路徑會執行該指令，守衛擋得住刪除、擋不住執行）。
# 反測本守衛時勿用 busybox sh：它以內建 applet 執行 rm，PATH 前置的 rm 攔截器完全不生效（實測 shim 零呼叫、目標真的被刪）；bash 與 dash 才會走 PATH。
# $RP 不得帶尾斜線：rm -rf -- "<link>/" 會跟隨 symlink 刪掉目標（占位已剝盡尾斜線，且刪的是相對名）。
# 外層仍包一層子 shell：本體的 exit 只結束內層 bash，外層括號讓人工貼進互動 shell 時不會被關掉，rc 照樣傳出。
# 已知限制（#248／#249，2026-09-27 裁定不防，範圍見下）：
# 本守衛不防「同一 shell 內」的 function／alias／變數屬性污染。已實測可繞過的三項：
#   declare -n RP=OK    → OK=1 連帶把 RP 設成 1，rm 打在相對路徑 ./1
#   declare -l RP       → 暫存根全小寫時，解析結果被轉小寫，刪到同名小寫目錄
#   export -f '['       → 父目錄比對回假相等，根外目錄被刪
# 未逐項實測、僅屬同類機制者：-u／-i／-a／-A、alias。單獨 declare -x 實測無影響。
# 不防的理由：植入它們需要先能在本 shell 內執行 code，而有該權限者可直接 rm -rf。
# 環境變數注入（BASH_FUNC_*）不在此列——它不需執行 code，已由 /usr/bin/env -i 阻斷。
# 本守衛也不防占位貼入時的 shell 求值（指令替換、glob 展開）——見上方既有註解。
# 本守衛不逐元件追查 symlink，改以輸入格式白名單：占位須恰為 <暫存根>/<合法名>（可帶尾斜線）；含 . 或 .. 或多層或經中間 symlink 的寫法一律拒絕，不論解析結果是否合規。
# 本守衛不防「暫存根在守衛執行期間被換掉」以外的 TOCTOU：占位本身在驗證與 rm 之間被替換不在防護範圍（占位由第 7 步產生，其父目錄即暫存根，已由 inode 比對與釘住 cwd 覆蓋）。
(
  /usr/bin/env -i \
    HOME="$HOME" TMPDIR="${TMPDIR:-}" PATH=/usr/bin:/bin \
    /bin/bash --noprofile --norc -c '
  set -u
  [ $# -eq 4 ] || { echo "須恰三個占位路徑＋本輪 token，停" >&2; exit 1; }
  # 本輪 token（第 7 步嵌進兩個輪級目錄名的那一個）。字元集先驗、後用：它接著要進 case 的 pattern 位置，
  # 未驗就用時 TOKEN=* 會被當成萬用樣式、同根下每一輪的目錄都命中（放行一切）；限死非空且僅 [A-Za-z0-9]
  # 也使它不可能夾帶 /、. 或 glob 字元去改變樣式的結構。這道檢查在任何刪除之前，故不合格即零刪除。
  TOKEN=$4
  case "$TOKEN" in
    "" | *[!A-Za-z0-9]*) echo "本輪 token 須非空且僅含 A-Za-z0-9，停：$TOKEN" >&2; exit 1 ;;
  esac
  # 占位 3（$W）的 issue 號由 token 推導，不另收參數：token 的形狀是 <issue>r<round>，剝掉第一個 r 起的
  # 尾段即 issue 號。另收一個參數會讓「$W 屬於哪張單」變成可獨立填錯的一項，填錯就刪掉他單仍在用的 $W。
  # 同樣先驗字元集後用（它也要進 pattern 位置）：須非空且僅 [0-9]。token 不含 r 時 ${TOKEN%%r*} 回 token 原值：
  # 它若全數字（例如 TOKEN=283），這道檢查放行，推出的 issue 號就是 283——缺輪次不在此擋，而是由占位 1、2 的
  # 樣式比對擋下（devflow-rev."$TOKEN".?????? 要求目錄名嵌的是完整 token，第 7 步建的名字帶輪次故不命中）；
  # 它若含非數字（例如 TOKEN=abc），在此擋下。
  ISSUE=${TOKEN%%r*}
  case "$ISSUE" in
    "" | *[!0-9]*) echo "由 token 推導的 issue 號須非空且僅含 0-9，停：$ISSUE（token=$TOKEN）" >&2; exit 1 ;;
  esac
  NL=$(printf "\nx"); NL=${NL%x}
  # 剝盡尾斜線。?*/ 要求「至少一字元＋斜線」才剝，故 "/" 剝不成空字串、"///" 剝到剩 "/" 就停。
  # 用迴圈不用單次 ${x%/}：三重尾斜線單次剝完仍以 / 收尾，後續 -L 與前綴比對都會走偏。
  strip() {
    SS=$1
    while :; do
      case "$SS" in ?*/) SS=${SS%/} ;; *) break ;; esac
    done
  }
  ROOT="${TMPDIR:-$HOME/.cache}"
  # 暫存根有兩個可接受的字面值：RA＝環境給的 $ROOT 原值（可能本身是 symlink），RB＝釘住後那個 inode 的真實路徑。
  # 兩者都剝盡尾斜線後才拿來比對：TMPDIR=/foo/ 時第 7 步的占位是 /foo//devflow-rev.$TOKEN.xxxxxx，其前綴為 /foo/。
  # RA 在 cd 之前取沒有問題：它是字面值，不經任何解析，外部改指不會改變它。
  strip "$ROOT"; RA=$SS
  [ -n "$RA" ] || { echo "暫存根為空，停" >&2; exit 1; }
  # 取一個路徑的 inode 編號到 IN。ls -i 是 POSIX 取 inode 的可攜辦法（stat 非 POSIX 必備）。
  # -L 不可省：ls -di <symlink> 取的是 symlink 自身的 inode，cd -P 後 ls -di . 取的是目標的，
  # 兩者本來就不等，漏 -L 會把「暫存根為 symlink 且未被換掉」這個合法用法全部誤擋（實測 20859917 vs 20859911）。
  # 解析不用 awk：守衛本體整段在 bash -c 的單引號字串內，本體裡再出現單引號會切斷該字串。改用參數展開。
  # （這條註解本身也因此不寫單引號——切出來的片段若含空白或 metachar，整個守衛的參數就被打亂。）
  # 先剝前導空白再取第一欄：某些 ls 會為對齊補空白，不剝的話 ${IN%% *} 會取到空字串。
  inum() {
    IN=$(ls -dLi -- "$1" 2>/dev/null) || { IN=; return 1; }
    while :; do case "$IN" in " "*|"	"*) IN=${IN#?} ;; *) break ;; esac; done
    IN=${IN%% *}
    case "$IN" in "" | *[!0-9]*) IN=; return 1 ;; esac
    return 0
  }
  # $ROOT 可以是相對名（TMPDIR=rootlink）。同一性檢查要在釘住之後重新解析 $ROOT，那時 cwd 已經換掉，
  # 相對名會對著新的 cwd 解析而指到別處（或不存在），合法用法會被誤擋。故先在原 cwd 下補成絕對路徑。
  # 用 pwd -P 而不是 $PWD：$PWD 由外層環境帶進來時可能與實際 cwd 不符。物理路徑加上相對名仍指同一個目錄。
  # RA 維持 $ROOT 原字面不變——它是白名單的可接受前綴之一，補絕對路徑會改掉占位的比對語意。
  case "$ROOT" in
    /*) RABS=$ROOT ;;
    *)
      CWD0=$(pwd -P && printf x) && CWD0=${CWD0%x} || CWD0=
      [ -n "$CWD0" ] || { echo "無法取得目前工作目錄，停" >&2; exit 1; }
      CWD0=${CWD0%"$NL"}
      RABS=$CWD0/$ROOT
      ;;
  esac
  # 以 cd -P 釘住暫存根，之後「同一性比對」與所有碰檔案系統的動作都以這個 cwd 為準。
  # 為什麼是 cwd 而不是再比對一個屬性：本守衛的同一性判定前後被推翻三次，每次都是「換一個屬性比對」——
  #   canonical pathname（cd 前取）→ cd 前改指即用舊值比對通過；
  #   pathname 字串 → $ROOT 被 mv 走後同名重建，pathname 相同而目錄已換；
  #   inode 編號 → rmdir 後重建，核心立即重用剛釋放的 inode，編號相同而目錄已換（ext4 實測三次皆重用）。
  # 共通根因是 ls／readlink／test 每次都「重新解析路徑」，每次解析都是一個新的 TOCTOU 窗口，
  # 所以比對哪個屬性都只是把窗口推到下一個屬性上。cwd 不同：cd 當下就綁定了那個 inode，
  # 之後不再經過路徑解析，且行程存活期間核心持有 cwd 的參照、不會釋放該 inode——
  # inode 重用這條路是被「結構性」堵住的，不是靠比對某個易變屬性（#272 受控對照：不持有 重用=Y ×3、持 cwd 重用=N ×3）。
  # #253 原以 exec 9< "$ROOT" 持有目錄 fd 達成同一效果（受控對照：持 fd 重用=N ×3），#272 改為 cwd，理由有二：
  #   open(O_RDONLY) 需要讀權限，mode 0311（只可穿越）的暫存根會被誤擋（N3，實測 main rc=1 殘留=2）；cd 只需 x 權限。
  #   $ROOT 為 FIFO 時 open 會阻塞到有寫端為止、守衛掛住（N2，實測 timeout 3 → rc=124）；cd 到非目錄立即失敗。
  # cwd 只在本行程有效，故 cd 必須在這個內層 shell 執行（守衛本體整段就是內層 shell），且之後不再 cd 到別處。
  # 釘住的對象是 cd 當下 $ROOT 解析到的那個 inode；這是整段守衛唯一一次解析 $ROOT 來「落腳」，
  # 之後的同一性檢查再解析一次 $ROOT 只是拿來與釘住的 inode 比對，不據以落腳。
  # 釘住之後所有碰檔案系統的動作（-L、-d、rm）都用「相對名」對這個 cwd 做：
  #   $ROOT 可以是 symlink（T 明文允許），事後改指不會改變相對名的解析——窗口是關掉而不是縮小。
  # 判定「格式」仍只看占位字面（見 chk），故迂迴寫法照樣擋得住：釘住只換掉「碰檔案系統的路徑」，不換判定依據。
  # CDPATH= 顯式清零：cd 在 CDPATH 非空時可能跳到別處並把落腳路徑印到 stdout，不倚賴外層環境已清乾淨。
  # -- 使 $ROOT 以 - 開頭時不被當成選項。
  CDPATH= cd -P -- "$ROOT" || { echo "無法進入暫存根：$ROOT" >&2; exit 1; }
  # 兩個 inode：IPIN＝釘住的 cwd（經 /proc/self/cwd 取，不經任何路徑解析）、IPATH＝此刻重新解析 $ROOT 得到的。
  # /proc/self/cwd 是 Linux 特有。本守衛已依賴 GNU readlink -f 與 ls -di 等非 POSIX 行為，
  # 這不是新增的可攜性負擔，但明載於此：本守衛只保證在 Linux 上成立。
  inum /proc/self/cwd/. || { echo "無法取得暫存根 inode（cwd）：$ROOT" >&2; exit 1; }
  IPIN=$IN
  inum . || { echo "無法取得釘住後的 inode，停" >&2; exit 1; }
  ICWD=$IN
  # 自我檢查：/proc/self/cwd 與相對名 . 必須是同一個 inode。由核心保證，不等表示 /proc 不可信或前提已經不成立。
  if [ "$IPIN" != "$ICWD" ]; then
    echo "釘住的目錄與 /proc/self/cwd 不一致（$IPIN vs $ICWD），零刪除中止" >&2; exit 1
  fi
  # 同一性檢查：$ROOT 這個路徑此刻仍須指向釘住的那個目錄。
  # 被換掉的三種形式都在這裡落網，且都不依賴 inode 編號沒被重用：
  #   rmdir／mv 後同名重建 → 路徑指向新目錄，cwd 仍握著舊的，兩者必不同（持 cwd 使新目錄拿不到舊 inode）；
  #   symlink 改指 → 路徑解析到新目標，cwd 仍是舊目標；
  #   根被刪除且未重建 → ls 取不到 inode，inum 失敗，同樣中止（readlink /proc/self/cwd 會帶 (deleted) 尾綴）。
  # 反過來，未被換掉時 IPATH 必等於 IPIN，$ROOT 為 symlink 時 ls -dLi 取的是目標 inode，故不誤擋。
  inum "$RABS" || { echo "暫存根在守衛執行期間消失，零刪除中止：$ROOT" >&2; exit 1; }
  IPATH=$IN
  if [ "$IPIN" != "$IPATH" ]; then
    echo "暫存根在守衛執行期間被換掉（釘住 inode $IPIN、路徑此刻指向 inode $IPATH），零刪除中止" >&2; exit 1
  fi
  # RB 必須在 cd 之後才取，而且要問「已釘住的 cwd」而不是再解析一次 $ROOT。
  # pwd -P 回的是當前 cwd 那個 inode 的真實路徑，不重走 $ROOT，故與 RA 同樣不受事後改指影響。
  # 若像舊版在 cd 之前用 readlink -f -- "$ROOT" 當可接受前綴：$ROOT 可在 readlink 與 cd 之間被改指（A→B），
  # 該值留著舊 root A 而 cwd 已經是 B，指向 A 的 canonical 占位會比對舊值通過驗證，
  # 但 -L／-d／rm 全打在 B——占位逐字指向 A 卻刪掉 B 底下從未驗證的目錄（實測 bash 與 dash 皆可重現）。
  RB=$(pwd -P && printf x) && RB=${RB%x} || RB=
  [ -n "$RB" ] || { echo "無法取得暫存根的真實路徑，停" >&2; exit 1; }
  RB=${RB%"$NL"}
  case "$RB" in
    /*) : ;;
    *) echo "暫存根真實路徑非絕對路徑，停：$RB" >&2; exit 1 ;;
  esac
  case "$RB" in *"$NL"*) echo "暫存根真實路徑含換行，停" >&2; exit 1 ;; esac
  strip "$RB"; RB=$SS
  # 驗一個占位：$1 路徑、$2 角色代號（rev／co／task）、$3 占位序號（僅供訊息）。通過回 0 並把「相對名」留在 CRP。
  # 白名單：剝盡尾斜線後須恰為 <暫存根>/<該位合法名>。格式判定全走占位字面，不靠 readlink -f 的解析結果——
  # readlink -f 會把 <symlink>/.、<中間 symlink>/<合法名> 正規化成同根合規目錄，拿它當判定依據就是 BLOCK 3 的成因。
  # 角色樣式寫死在 case 的 pattern 位置、不經參數傳遞：pattern 位置不做 pathname expansion，cwd 內容與判定無關。
  # 唯二的例外是本輪 token 與由它推導的 issue 號，它們必須來自參數（第 7 步才知道值）；在 pattern 位置加引號使其只當字面比對，
  # 不加引號時 TOKEN=* 會變萬用樣式、把同根下每一輪的目錄都放行，且兩者的字元集已在上面先驗過。
  chk() {
    CP=$1; ROLE=$2; IDX=$3; CRP=
    if [ -z "$CP" ]; then echo "占位 $IDX 為空路徑，停" >&2; return 1; fi
    case "$CP" in *"$NL"*) echo "占位 $IDX 路徑含換行，停" >&2; return 1 ;; esac
    strip "$CP"; CPS=$SS
    # 最後一段須命中該位角色樣式。"."、".."、空字串都不命中，迂迴寫法在此一併被擋。
    CPN=${CPS##*/}
    case "$ROLE" in
      rev) case "$CPN" in devflow-rev."$TOKEN".??????) : ;;
             *) echo "占位 $IDX 末段非該位合法名（須 devflow-rev.$TOKEN.??????），停：$CP" >&2; return 1 ;; esac ;;
      co)  case "$CPN" in devflow-co."$TOKEN".??????) : ;;
             *) echo "占位 $IDX 末段非該位合法名（須 devflow-co.$TOKEN.??????），停：$CP" >&2; return 1 ;; esac ;;
      task) case "$CPN" in devflow-task."$ISSUE".??????) : ;;
             *) echo "占位 $IDX 末段非該位合法名（須 devflow-task.$ISSUE.??????），停：$CP" >&2; return 1 ;; esac ;;
      *) echo "占位 $IDX 角色代號有誤（只收 rev／co／task），停" >&2; return 1 ;;
    esac
    # 去掉最後一段的前綴須字面等於暫存根。CPS 已剝盡尾斜線且末段非空，故 ${CPS%/*} 就是前綴；
    # 前綴也要剝盡尾斜線：TMPDIR=/foo/ 時第 7 步的 mktemp -d "${TMPDIR:-…}/devflow-rev.$TOKEN.XXXXXX"
    # 產生的占位是 /foo//devflow-rev.$TOKEN.xxxxxx，其 ${CPS%/*} 為 /foo/，不剝就與 /foo 比不等（實測會誤擋正常路徑）。
    # 沒有斜線時（相對路徑如 devflow-rev.$TOKEN.xxxxxx）${CPS%/*} 回原字串，與暫存根不等，一併被擋。
    strip "${CPS%/*}"; CPP=$SS
    if [ "$CPP" != "$RA" ] && [ "$CPP" != "$RB" ]; then
      echo "占位 $IDX 前綴非暫存根字面（須 $RA），停：$CP" >&2; return 1
    fi
    # 以下改用相對名對已釘住的 cwd 判定，不再走 $CP／$CPS 那條會經 root symlink 重新解析的路徑。
    # 最終路徑本身仍須非 symlink（白名單擋的是迂迴寫法，直接填 symlink 名要靠這道）。
    if [ -L "$CPN" ]; then echo "占位 $IDX 是 symlink，停：$CP" >&2; return 1; fi
    if [ ! -d "$CPN" ]; then echo "占位 $IDX 不是現存目錄，停：$CP" >&2; return 1; fi
    CRP=$CPN
    return 0
  }
  # 第一段：只驗證，不刪。三個都驗（不短路）好讓人一次看到全部問題。
  # 填 `-` 的那位整位略去：SKIPn 記下該位被略去，刪除階段跳過它。三位皆可填 `-`——
  #   第 10 步正常路徑傳 "-" "-" "<$W>"，第 8 步的輪級回收傳 "<$T>" "<$D>" "-"。
  # `-` 不可能是合法占位（末段須命中角色樣式），故不與正常值混淆；
  # 三位同時為 `-` 時沒有任何要回收的對象，視為呼叫錯誤而非 no-op。
  BAD=; RP1=; RP2=; RP3=; SKIP1=; SKIP2=; SKIP3=
  if [ "$1" = "-" ]; then SKIP1=1; else if chk "$1" rev 1; then RP1=$CRP; else BAD=1; fi; fi
  if [ "$2" = "-" ]; then SKIP2=1; else if chk "$2" co 2; then RP2=$CRP; else BAD=1; fi; fi
  if [ "$3" = "-" ]; then SKIP3=1; else if chk "$3" task 3; then RP3=$CRP; else BAD=1; fi; fi
  if [ -n "$SKIP1" ] && [ -n "$SKIP2" ] && [ -n "$SKIP3" ]; then
    echo "三個占位都填 -，沒有要回收的對象，停" >&2; BAD=1
  fi
  # 相異性：角色樣式已使三位不可能收到同一路徑，此檢查是第二道（樣式若日後放寬仍守得住），且明確拒絕而非靜默略過。
  if [ -n "$RP1" ] && [ "$RP1" = "$RP2" ]; then echo "占位 1 與 2 指向同一目錄，停：$RP1" >&2; BAD=1; fi
  if [ -n "$RP1" ] && [ "$RP1" = "$RP3" ]; then echo "占位 1 與 3 指向同一目錄，停：$RP1" >&2; BAD=1; fi
  if [ -n "$RP2" ] && [ "$RP2" = "$RP3" ]; then echo "占位 2 與 3 指向同一目錄，停：$RP2" >&2; BAD=1; fi
  [ -z "$BAD" ] || { echo "有占位未通過驗證，零刪除中止" >&2; exit 1; }
  # 第二段：全數通過才刪。以相對名刪，對象即驗證時看到的那些目錄（cwd 已釘住），不受 root symlink 事後改指影響。
  RC=0
  [ -n "$SKIP1" ] || rm -rf -- "$RP1" || { echo "刪除失敗：$RP1" >&2; RC=1; }
  [ -n "$SKIP2" ] || rm -rf -- "$RP2" || { echo "刪除失敗：$RP2" >&2; RC=1; }
  [ -n "$SKIP3" ] || rm -rf -- "$RP3" || { echo "刪除失敗：$RP3" >&2; RC=1; }
  exit $RC
' _ "-" "-" "<第 7 步的 $W>" "<任一輪的 $TOKEN>"
)
# ↑ 正常路徑（$T／$D 已在第 8 步回收）：占位 1、2 填 "-"，只收 $W。$TOKEN 仍必填（占位 3 的 $ISSUE 由它推導）。
# ↓ 補收路徑（某輪第 8 步漏做，$T／$D 仍在；依 F4）：該輪的兩位填真實路徑、帶該輪的 $TOKEN，與 $W 一併回收。
#    漏做的輪不只一輪時，每輪各跑一次本守衛（token 不同），$W 只在其中一次收、其餘次占位 3 填 "-"。
#    末行改為：' _ "<該輪的 $T>" "<該輪的 $D>" "<第 7 步的 $W>" "<該輪的 $TOKEN>"
```

> **反測不得以真實工作目錄當靶**（#202 AC-4 第 23 條）：守衛若寫壞，反測本身就會刪掉靶目錄。一律用 `mktemp -d` 另建的誘餌 `HOME`。

`C1` 七步照序執行，判準見條文；每段的最終 exit 即該步的機械判定（判定鏈以 `&&` 串接，不作判定的指令已 `|| true`，整段貼入與逐行執行結果相同），非 0 或註解所列情況即停、不進下一步。Hermes 側指令（在主 checkout 執行）：

```bash
# (1) 兩項全驗：HEAD_OID 填 PR 的 <head sha>，(5) 填同一個值（段與段不保證同一 shell，不靠變數跨段）；fetch → 祖先檢查 → 讀回三欄；祖先檢查非 0 ＝ 未合入；state 非 MERGED → grep 非 0，結果未定（F3）
HEAD_OID=<head sha> && git fetch origin main && git merge-base --is-ancestor "$HEAD_OID" origin/main \
  && gh pr view <PR-N> --json state,mergedAt,mergeCommit --jq '"\(.state)\t\(.mergedAt)\t\(.mergeCommit.oid)"' | grep '^MERGED'

# (2) 仍 active 才 kill；kill 只送訊號、exit 不作判定（|| true）；等到讀回字串為 inactive（deactivating 不算；逾時 124 ＝ 未停）；判定依 hermes.md 「中斷交接」格
[ "$(systemctl --user is-active coder-<N>.scope)" != active ] || systemctl --user kill --signal=TERM coder-<N>.scope || true
timeout 30 sh -c 'until [ "$(systemctl --user is-active coder-<N>.scope)" = inactive ]; do sleep 1; done' \
  && [ "$(systemctl --user is-active coder-<N>.scope)" = inactive ] && echo inactive

# (3) 非空 → 逐項判是否須保留；有須保留者 → 停，依 F4
git -C ../<repo>.worktrees/<N> status --porcelain

# (4) 被拒不強制：回 (3) 重判，確認無需保留後加 --force
git worktree remove ../<repo>.worktrees/<N>

# (5) compare-and-delete。HEAD_OID 在此重填與 (1) 相同的 <head sha>（不得 rev-parse 分支現值）；空字串與全零會讓 update-ref 退化成無條件刪除，
#     故先驗「40 位十六進位且非全零」，不過即停；被拒（cannot lock ref … is at X but expected Y）＝ ref 已移動，停，不改用 branch -d／-D、不 merge main 重試
HEAD_OID=<head sha>
[[ $HEAD_OID =~ ^[0-9a-f]{40}$ && $HEAD_OID != 0000000000000000000000000000000000000000 ]] \
  && git update-ref -d refs/heads/<N>-<slug> "$HEAD_OID"

# (6) ls-remote 非 0 → 結果未定（F3），停；0 且空 → 跳過；0 且非空 → 取 OID，祖先檢查為 0 才刪
if OUT=$(git ls-remote --heads origin <N>-<slug>); then
  [ -z "$OUT" ] || { git merge-base --is-ancestor "${OUT%%[[:space:]]*}" origin/main && git push origin --delete <N>-<slug>; }
else echo "F3: ls-remote 失敗，停"; false; fi

# (7) 非 0 → 結果未定（F3）；0 且非空 → 未刪成，停；0 且空＝C1 完成
if OUT=$(git ls-remote --heads origin <N>-<slug>); then [ -z "$OUT" ] && echo "C1 完成" || { echo "遠端分支仍在，停"; false; }; else echo "F3: ls-remote 失敗，停"; false; fi

# C2：OPEN → gh issue close <N> 後再讀回
gh issue view <N> --json state --jq .state
```

- (1) 讀回 `MERGED`，依 `forges/github.md` 「已合併訊號（`C1`）」格；(2) 判定依 `hermes.md` 「中斷交接」格；(6)(7) 依 `forges/github.md` 「合併後刪分支（`C1`）」格；`C2` 讀回 `CLOSED`。
- 範圍依 `C3`、`C4`；收尾失敗依 `F4`。

## 三、輪次紀律（`F1`、`R3`、`R5`）

- 審查輪次不設上限；每輪處置後依 `R13` 判定續審、升人或擱置，並記該條要求的續審留痕。實作未達 AC 的兩輪無進展升級另依 `F1`。
- 審查 reasoning：首輪 `xhigh`／`high`；後續範圍縮窄可降 `medium`／`low`。
- 每輪 PR 留言兩則：verdict 摘要表＋完整 verdict（`R5`）。

## 四、對照表結帳（`R7`～`R10`）

格的成立條件依 `R7`、`R8`、`R9`、`R10`。Hermes 側證據鏈：啟動前留言（`git worktree list`、worktree HEAD、完整啟動指令）→ coder 產物（commit、驗證輸出）→ orchestrator 貼 stdout JSON 關鍵欄位（`session_id`、`num_turns`、`result` 摘要）→ 證據 URL 以 `gh api repos/<owner>/<repo>/issues/comments/<id>` 讀回。這條證據鏈的留言就是步驟 3 末條那則 `L1` 派工紀錄（同一則，不另開），`L1` 生效後的執行要當對照表證據時只能引它。

`R8` 一次性條件的已知例：`.comments[-1]`（用留言 id）；`createdAt == updatedAt` 在 close 後失效（看 `lastEditedAt: null`）；驗證用 PR 永久留在 `--state all`（改可丟棄 repo）；`pgrep -P` 不證無殘留（用 cgroup）。

## 五、規則改自己（`G2`）

- 流程依 `G2`。Hermes 側：提案 issue（問題／案例／候選／建議，人逐項裁）→ 實作單作為新任務走步驟 1～10。
- 審查 prompt 明寫 `git show <舊 G sha>:devflow/WORKFLOW.md` 為依據（`G2`）。
- 版本位數依 `V1`～`V3`，不相容標記依 `V6`（第 3 節，依 `ST1`）。
- 合併後啟用邊界依 `G3`；檢查器門檻依 `G4`（依 `ST2`）。
- 入口區塊同步依 `D2`、`I5`：`python3 devflow/install.py . --dry-run` 驗。

## 六、無人值守

- 事先授權由人寫進 issue 或授權檔。授權的範圍與不可下放的事項依 `I8`～`I11`（`autonomy` 三檔的差異、機械／方向類的判準、一律由人處置的四項），不在本檔另行列舉；授權檔只需逐項指明本單取哪一檔、停止條件，以及 Codex 額度撞到時 sleep 到恢復再派（日上限；週上限依第七節依 `launch` 分支的配額條文）。
- 每步邊界（派工、撞 turns、verdict、合併、收尾）在 issue 留狀態（`L3`）。
- forge 回錯或逾時依 `F3`。
- Codex 額度撞到（日上限）：一次性 cron 於恢復時間重派＋watchdog 每 3 分鐘看 verdict 檔；週上限依第七節依 `launch` 分支的配額條文。Claude 額度撞到：Hermes 自身靜默，人隔日看 issue 接手。
- 全用 Hermes 追蹤的 background 進程（`terminal(background=true)` ＋ `systemd-run --scope`）；不用 `setsid`——會無聲死亡且無法讀回。

## 七、已知陷阱

- 引用不生效的規則——先查 `ST` 表（例：`G3` 依 `ST5`、`G4` 依 `ST2`）。
- commit body 不能代替 issue 上的裁決（`L3`）。
- 計數用 `grep -c` 會算進圖例句；用相同方法互驗等於沒驗（`R6`、`R8`）。
- 改大檔（如 1500+ 行的 `scripts/devflow_checks.py`）的 coder 易撞 max-turns——prompt 明寫 `D4`。
  更根本的是**大檔要能直接執行與測試**：inline 在 YAML 裡的程式碼連跑一次都要先抽取，
  而抽取邏輯本身就會出錯（PR #81：協調者以「最大 `run: |` 區塊」抽取、多切結尾標記，
  跑出 `NameError` 一度誤判為內容問題）。issue #82 因此把檢查器搬進 `scripts/`。
- `ps | grep 'claude -p'` 對多行 prompt 不可靠——用 `pstree -p`／`/proc/<pid>/cmdline`（`hermes.md` 「派工（`L2`）」格）。
- `systemctl --user is-active <unit>.scope` 對從未存在的 unit 也回 `inactive`——先證 scope 曾 `active`（`hermes.md` 「中斷交接」格）。
- 對照表引用行號會漂移——引用格用「面向」名稱，不用 `file:line`。
- Codex 配額耗盡：形狀依派工時的 `launch` 分支（第 7 步），判定錯一邊就會把「配額擋住」誤讀成「審完了」。
  - `launch: cli`（`codex exec`）：以 `turn.failed` 收尾（稍早一則同句 `error`，其在事件流中的位置隨觀測而異）、exit 1、`-o` 不寫，恢復點只在訊息的 `try again at …`（觀測次數、`error` 的位置與受測環境以 `coders/codex.md` 「配額中斷」格為準，`📝`）。
  - `launch: agent`（具名實例經轉播器）`📝`：**本形狀僅一次觀測**（`coders/codex.md` 「配額中斷」格的第四次觀測，前三次皆為 `cli`），故以下寫的是**本次觀測為**何，不是所有 agent 配額中斷必然如此——引用前查該格狀態（`R9`）。本次觀測：事件流末則為 `{"type":"result","exit_code":1,…,"error":"HTTP 429: The usage limit has been reached"}`，**不是** `turn.failed`；恢復點載於 `Limit resets at 01:55 (in 33h 42m)`——**相對時距**（`in Nh Nm`），不是絕對時刻，換算基準是讀到該行的時間，隔夜再算就偏。⚠️ 轉播器把這個結束投影為「❌ 結束」而**非錯誤**，**派工者須讀事件流原文判定，不可只看投影**——只看投影會把配額耗盡當成正常收工，接著去等一個永遠不會出現的 verdict。來源：`#272`（2026-10-02，`hermes -p dfrev chat --oneshot --format stream-json`）https://github.com/AugustusHsu/agent-devflow/issues/272#issuecomment-5947986219 。
  - 兩者共同：配額綁**帳號**（訊息把恢復點與購買額度都指向 `chatgpt.com/codex/settings/usage`，非 thread 層級），換 context、換 thread、換具名實例都不會繞過。**日上限與週上限只有在訊息明示類型時才分類**，不以時距長短或恢復點落在哪一天推斷——時距與限制週期之間沒有觀測支持的對應關係：
    - `cli` 形狀（`try again at …`）：給**時刻**者為日上限（實例 `12:36 AM`）、給**日期**者為週上限（實例 `Sep 26th, 2026 8:02 PM`），依 `coders/codex.md` 「配額中斷」格既有觀測（`📝`）。
    - `agent` 形狀（`Limit resets at HH:MM (in Nh Nm)`）：只給相對時距，**不含**週期資訊 ⇒ 一律視為**不確定**，不先套日／週處置。處置：查帳號頁面 `chatgpt.com/codex/settings/usage` 確認是日上限還是週上限後再依下列分支；查不到或讀不準就停下交人（issue 留言寫明被擋的位、訊息原文與恢復點，依 `L3`）。
    - 確認為日上限：依第六節 sleep 到恢復再派。
    - 確認為週上限：不等。審查位依 `R2` 改派，分兩種情形——
      - `devflow.yml` 的 `seats.reviewer.fallback` **已宣告**：只用該組（`R2` 要求事先定下，不臨場選）。
      - `fallback` **省略**（它是選填）：**不得**臨場新增 `devflow.yml` 未宣告的綁定候選（`I7`）——停下交人裁示（在 issue 留言寫明被擋的位、恢復點與候選方案，依 `L3`），或依第六節等恢復；兩者都不是自己挑一個工具就派。
      - 被擋的是實作位時 `R2` 不適用（它只管審查位），改派異廠或依第六節等恢復。
