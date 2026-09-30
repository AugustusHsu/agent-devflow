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

fresh context、異廠、丟棄式 checkout（`coders/codex.md` 「審查用法（`R1`）」格，引用前查狀態 `R9`）：

```bash
mkdir -p -m 700 -- "${TMPDIR:-$HOME/.cache}"
T=$(mktemp -d "${TMPDIR:-$HOME/.cache}/devflow-rev.XXXXXX")   # 本輪專用暫存目錄；`TMPDIR` 未設時落在 `$HOME/.cache`，不落 /tmp 本身（`TMPDIR` 指向 /tmp 時須先改設）；第 10 步 (0) 刪
D=$(mktemp -d "${TMPDIR:-$HOME/.cache}/devflow-co.XXXXXX")    # 丟棄式 checkout，同上不落 /tmp 本身；第 10 步 (0) 刪
git clone --shared <repo> "$D" && git -C "$D" checkout <head sha>
env TMPDIR="$T" codex exec -C "$D" --sandbox workspace-write -m <model> -c model_reasoning_effort=<level> \
  -c approval_policy="never" -c sandbox_workspace_write.exclude_slash_tmp=true \
  -c sandbox_workspace_write.network_access=false \
  -c 'sandbox_workspace_write.writable_roots=["'"$D"'","'"$T"'"]' \
  -o "$T/verdict.md" - < "$T/prompt.txt"
```

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

### 9. 合併（`M1`～`M4`、`I3`、`R5`）

前提依 `M1` 逐項驗；main 前進依 `M3`、`M4`；合併者依 `M2`。

```bash
gh pr merge <PR-N> --merge --subject "<gitmoji> merge(#<N>): <一句話>" \
  --body "PR #<PR-N>; reviewer <審查者與模型>; head <head sha>
M2: <誰按、依據什麼授權>"
```

gitmoji 依變更性質選。對照 `forges/github.md` 「合併（`I3`）」格（`--match-head-commit <head sha>` 不在該格實測範圍）。

### 10. 收尾（`C1`～`C4`、`F4`）

`C1` 七步之前先執行 (0) 刪本輪暫存目錄——第 7 步建的 `$T`、`$D` 在此回收（`R12` 「隨暫存目錄丟棄」）。`$T`／`$D` 不跨段保留，路徑由執行者填入，**填錯就是 `rm -rf` 打在別處**，故刪除前逐一驗證：

```bash
# (0) 刪本輪暫存目錄。第 7 步建的 $T（devflow-rev.??????）與 $D（devflow-co.??????）在此回收。
# 輸入格式白名單（不逐元件追查 symlink）：占位剝盡尾斜線後須恰為 <暫存根>/<該位的合法名>——最後一段命中該位角色樣式、去掉最後一段的前綴字面等於暫存根、該路徑本身非 symlink。三項全中才算合法。
# 先 cd -P 釘住暫存根，之後碰檔案系統的動作（-L、-d、rm）全用相對名：$ROOT 可以是 symlink，若拿完整路徑去刪，symlink 可在驗證與 rm 之間被重新指向，rm 就打到另一個 root 底下同名而「從未驗證」的目錄（實測 bash 與 dash 皆可重現）。cd 綁的是當時那個目錄的 inode，事後改 symlink 不影響相對名解析——窗口是關掉，不是縮小。
# 為何走白名單不逐元件追查：readlink -f 會把 <symlink>/.、<symlink>/./、<中間 symlink>/<合法名> 都解析成同根下一個「合規的」目錄並刪掉它，而逐元件檢查須區分 <symlink>/. 與 <普通目錄>/.（兩者解析結果都合法），成本高且易誤擋合法邊界。占位本應由第 7 步原樣填入，迂迴寫法不是正常用法。
# 行為收窄（刻意）：<合法名>/. 與 <合法名>/./ 即使是普通目錄也一律擋，因為最後一段是 . 不是合法名。<合法名>／<合法名>/／<合法名>/// 三種寫法仍可用——差一個 . 而已，別用會連尾斜線一起擋的粗判準。
# 暫存根有兩個可接受的字面值：$ROOT 原值與「釘住後 pwd -P 給的真實路徑」（TMPDIR 指向 symlink 時兩者不同，都得接受，否則正常路徑會被誤擋）。兩者都要剝盡尾斜線：TMPDIR=/foo/ 時第 7 步產生的占位是 /foo//devflow-rev.xxxxxx，前綴為 /foo/，不剝就比不等。
# 後者務必在 cd 之後以 pwd -P 取，不可在 cd 之前用 readlink -f -- "$ROOT"：$ROOT 若在 readlink 與 cd 之間被改指（A→B），該值留著舊 root A 而 cwd 已是 B，指向 A 的占位會比對舊值通過驗證，-L／-d／rm 卻全打在 B，刪掉 B 底下從未驗證的目錄（實測 bash 與 dash 皆可重現）。pwd -P 問的是已釘住的 inode，不重走 $ROOT。
# 「暫存根是否被換掉」用 inode 比對（ls -dLi，cd 前後各一次），不用 pathname 字串比對：pathname 相同而 inode 不同的情形存在（$ROOT 被 mv 走後同名重建，字串比對誤認沒變，刪掉新 inode 下從未驗證的兩目錄）；inode 相同而 pathname 不同的情形也存在（TMPDIR=//foo 時 GNU readlink -f 正規化成 /foo、pwd -P 保留 //foo，字串比對必然不等，合法用法被誤擋）。兩者皆實測，inode 比對同時解掉這兩面。
# 兩段式，先驗完再刪：兩個占位全部通過（非空、不含換行、合白名單、非 symlink、須為現存目錄、兩者相異）才進刪除；任一不合法 → 零刪除、rc 非 0。
# 「零刪除」的範圍限於驗證階段：驗證未全過就一個都不刪。進入刪除階段後兩個 rm 都會執行，其一失敗（例如權限）只使 rc 非 0，不會回滾另一個已刪的——刪除本身不是交易。
# 角色樣式寫死在 case 的 pattern 位置、不經參數傳遞：樣式若當參數傳，呼叫點會做 pathname expansion，cwd 內有字面同形目錄（devflow-rev.******）時樣式會被換成該目錄名，不合法的短名就會被放行。
# 尾斜線先剝盡才測 -L：[ -L "<link>/" ] 回假（尾斜線要求解析到目標），symlink 帶尾斜線會漏過 symlink 閘門。
# 「已不存在就算成功」是缺陷不是寬容（#251）：占位 2 填成不存在的合法名時，舊版會照刪占位 1 再回 0，看起來成功、實際漏刪。
# 角色綁位：占位 1 只收 devflow-rev.??????、占位 2 只收 devflow-co.??????，兩者對調即失敗。
# 守衛本體在 /usr/bin/env -i 造的空環境裡由 /bin/bash 執行，內層 PATH 固定；占位以位置參數 $1／$2 傳入，不再內插進指令字串。
# 不加 command 前綴：BASH_FUNC_command%% 注入會穿透 command 前綴（實測），直接寫 /usr/bin/env 才擋得住。
# 只辨角色樣式不辨輪次：同根下若有另一輪的 devflow-rev.??????／devflow-co.??????，填錯照樣會刪（跨輪身分核對需第 7 步的持久記錄，由 #255 承接）。
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
  [ $# -eq 2 ] || { echo "須恰兩個占位路徑，停" >&2; exit 1; }
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
  # 兩者都剝盡尾斜線後才拿來比對：TMPDIR=/foo/ 時第 7 步的占位是 /foo//devflow-rev.xxxxxx，其前綴為 /foo/。
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
  # 釘住前先記下暫存根的 inode。判「暫存根是否被換掉」用 inode 而不是 pathname 字串：
  #   pathname 相同但 inode 不同的情形確實存在——$ROOT 被 mv 走後以同名新目錄重建，
  #   字串比對會誤認「沒變」而把新 inode 底下從未驗證的兩個目錄刪掉（實測 bash 與 dash 皆可重現）。
  #   反過來，inode 相同而 pathname 不同也存在——TMPDIR=//foo 時 GNU readlink -f 正規化成 /foo、
  #   pwd -P 保留 //foo，字串比對必然不等，合法用法被誤擋。inode 比對同時解掉這兩面。
  inum "$ROOT" || { echo "無法取得暫存根 inode：$ROOT" >&2; exit 1; }
  IPRE=$IN
  # 釘住暫存根目錄本身，之後所有碰檔案系統的動作（-L、-d、rm）都用「相對名」對這個已釘住的 cwd 做。
  # 為什麼要釘：$ROOT 可以是 symlink（T 明文允許），而 symlink 可在驗證與 rm 之間被外部重新指向，
  # 使 rm 打到另一個 root 底下同名但「從未驗證」的目錄。cd 之後 cwd 綁定的是當時那個目錄的 inode，
  # 事後改 symlink 不會改變相對名的解析——窗口是關掉而不是縮小（重跑驗證只能縮小，關不掉）。
  # 判定「格式」仍只看占位字面（見 chk），故迂迴寫法照樣擋得住：釘住只換掉「碰檔案系統的路徑」，不換判定依據。
  # CDPATH= 顯式清零：cd 在 CDPATH 非空時可能跳到別處並把落腳路徑印到 stdout，不倚賴外層環境已清乾淨。
  CDPATH= cd -P -- "$ROOT" || { echo "無法進入暫存根：$ROOT" >&2; exit 1; }
  # 釘住後再取一次 inode，這次問「已釘住的 cwd」（.）而不是再解析一次 $ROOT——
  # 對 $ROOT 重新求值等於把「可被外部改掉的觀測」重新引回判定，那正是前一版的缺陷成因。
  inum . || { echo "無法取得釘住後的 inode，停" >&2; exit 1; }
  IPOST=$IN
  # 同一性檢查：釘住的必須就是一開始看到的那個目錄。不是就零刪除中止。
  # 這道擋的是「$ROOT 在守衛執行期間被換掉」本身——symlink 改指與同名重建都在射程內，
  # 且與占位寫成 canonical 還是 symlink 字面無關（兩種形式都在檢查前就被擋下）。
  if [ "$IPRE" != "$IPOST" ]; then
    echo "暫存根在守衛執行期間被換掉（inode $IPRE -> $IPOST），零刪除中止" >&2; exit 1
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
  # 驗一個占位：$1 路徑、$2 角色代號（rev／co）、$3 占位序號（僅供訊息）。通過回 0 並把「相對名」留在 CRP。
  # 白名單：剝盡尾斜線後須恰為 <暫存根>/<該位合法名>。格式判定全走占位字面，不靠 readlink -f 的解析結果——
  # readlink -f 會把 <symlink>/.、<中間 symlink>/<合法名> 正規化成同根合規目錄，拿它當判定依據就是 BLOCK 3 的成因。
  # 角色樣式寫死在 case 的 pattern 位置、不經參數傳遞：pattern 位置不做 pathname expansion，cwd 內容與判定無關。
  chk() {
    CP=$1; ROLE=$2; IDX=$3; CRP=
    if [ -z "$CP" ]; then echo "占位 $IDX 為空路徑，停" >&2; return 1; fi
    case "$CP" in *"$NL"*) echo "占位 $IDX 路徑含換行，停" >&2; return 1 ;; esac
    strip "$CP"; CPS=$SS
    # 最後一段須命中該位角色樣式。"."、".."、空字串都不命中，迂迴寫法在此一併被擋。
    CPN=${CPS##*/}
    case "$ROLE" in
      rev) case "$CPN" in devflow-rev.??????) : ;;
             *) echo "占位 $IDX 末段非該位合法名（須 devflow-rev.??????），停：$CP" >&2; return 1 ;; esac ;;
      co)  case "$CPN" in devflow-co.??????) : ;;
             *) echo "占位 $IDX 末段非該位合法名（須 devflow-co.??????），停：$CP" >&2; return 1 ;; esac ;;
      *) echo "占位 $IDX 角色代號有誤（只收 rev／co），停" >&2; return 1 ;;
    esac
    # 去掉最後一段的前綴須字面等於暫存根。CPS 已剝盡尾斜線且末段非空，故 ${CPS%/*} 就是前綴；
    # 前綴也要剝盡尾斜線：TMPDIR=/foo/ 時第 7 步的 mktemp -d "${TMPDIR:-…}/devflow-rev.XXXXXX"
    # 產生的占位是 /foo//devflow-rev.xxxxxx，其 ${CPS%/*} 為 /foo/，不剝就與 /foo 比不等（實測會誤擋正常路徑）。
    # 沒有斜線時（相對路徑如 devflow-rev.xxxxxx）${CPS%/*} 回原字串，與暫存根不等，一併被擋。
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
  # 第一段：只驗證，不刪。兩個都驗（不短路）好讓人一次看到全部問題。
  BAD=; RP1=; RP2=
  if chk "$1" rev 1; then RP1=$CRP; else BAD=1; fi
  if chk "$2" co 2; then RP2=$CRP; else BAD=1; fi
  # 相異性：角色樣式已使兩位不可能收到同一路徑，此檢查是第二道（樣式若日後放寬仍守得住），且明確拒絕而非靜默略過。
  if [ -n "$RP1" ] && [ "$RP1" = "$RP2" ]; then echo "兩占位指向同一目錄，停：$RP1" >&2; BAD=1; fi
  [ -z "$BAD" ] || { echo "有占位未通過驗證，零刪除中止" >&2; exit 1; }
  # 第二段：全數通過才刪。以相對名刪，對象即驗證時看到的那兩個目錄（cwd 已釘住），不受 root symlink 事後改指影響。
  RC=0
  rm -rf -- "$RP1" || { echo "刪除失敗：$RP1" >&2; RC=1; }
  rm -rf -- "$RP2" || { echo "刪除失敗：$RP2" >&2; RC=1; }
  exit $RC
' _ "<第 7 步的 $T>" "<第 7 步的 $D>"
)
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

- 事先授權由人寫進 issue 或授權檔，逐項列：`APPROVE` 即按合併（仍依 `M1`、`M2`）、`R13` 升人與擱置的處置方式（第三節）、停止條件、Codex 額度撞到時 sleep 到恢復再派（日上限；週上限依第七節「Codex 配額耗盡」）。
- 每步邊界（派工、撞 turns、verdict、合併、收尾）在 issue 留狀態（`L3`）。
- forge 回錯或逾時依 `F3`。
- Codex 額度撞到（日上限）：一次性 cron 於恢復時間重派＋watchdog 每 3 分鐘看 verdict 檔；週上限依第七節「Codex 配額耗盡」。Claude 額度撞到：Hermes 自身靜默，人隔日看 issue 接手。
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
- Codex 配額耗盡：`codex exec` 以 `turn.failed` 收尾（稍早一則同句 `error`，其在事件流中的位置隨觀測而異）、exit 1、`-o` 不寫，恢復點只在訊息的 `try again at …`（觀測次數、`error` 的位置與受測環境以 `coders/codex.md` 「配額中斷」格為準，`📝`）。配額綁帳號（訊息把恢復點與購買額度都指向 `chatgpt.com/codex/settings/usage`，非 thread 層級），換 context 不會繞過。日上限（訊息給當日時刻）：依第六節 sleep 到恢復再派；週上限（訊息帶日期）：不等——審查位依 `R2` 處理；被擋的是 implementer 位時 `R2` 不適用，改派異廠或依第六節等恢復。
