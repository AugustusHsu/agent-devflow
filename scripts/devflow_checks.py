#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 以下到 import 之前的註解，於 issue #82 由 .github/workflows/devflow-checks.yml 的檔頭
# 原樣搬來（逐行不改）。文中的「本檔」指搬家前的那個 workflow 檔——它當時同時裝著
# workflow 定義與這份檢查器；現在檢查器住這裡，workflow 只負責呼叫。
#
# 本 repo 的第一個 CI。規則本體是 devflow/WORKFLOW.md，檢查的對象也是它。
#
# 一項檢查何時可以從「建議」升為「必需關卡」，依據是 README「Phase 1 第三出口的判定方式」
# （正反兩個 run、同一份 blob、exit 1 只能由目標項造成）與 issue #26 的使用者裁決。
# 注意不是 `G4`：`G4` 住第 9 節，依第 0 節與 `ST2` 要 stage 2 才生效，現在是 stage 1，
# 不能引為依據。
# 本檔每一項檢查都有自己的開關（下面的 GATES）：True＝必需關卡，False＝建議（只報告不擋）。
# 十二項裡九項是 True（`encoding`、`d2`、`i1`、`i5`、`version`、`fence`、`tables`、`table`、`link`），
# 三項是 False（`dupid`、`refs`、`r9`）——分界不是「哪一項比較重要」，而是**定義域封不封閉**，
# 見下面各節。
#
# ── ⚠️ 這個 check 擋什麼、不擋什麼 ───────────────────────────────────────
# 會擋（exit 1）：`encoding` 受版控 .md 的內容是合法 UTF-8、
#                 `d2` 入口區塊（第一個 begin 到其後第一個 end 這一段：缺 end 或 >30 行；
#                 以及 begin 之前有落單的 end）、`i1` head branch 名稱、
#                 `i5` devflow.yml 的 `implementer_filler` 投影與 `seats.implementer.filler`
#                 及安裝器實際讀到的值三方一致、
#                 `version` 規則本體與規格文檔的 frontmatter `version` 是四碼（`V1`／`V4`）、
#                 `fence` 受版控 .md 的 fenced code block 都有關閉、
#                 `tables` devflow.yml 指名的對照表檔（`forge`、各職位的 `filler`）都受版控、
#                 `table` 對照表檔的表形狀合 `R9`（表頭欄位、狀態欄恰一、已分節時表要落在節內、
#                 資料列的狀態格非空、至少一張合格的表、不得有 raw HTML 表格）、
#                 `link` 相對連結指向 repo 內存在的路徑。
# 就這九項（`version`、`fence`、`table`、`link` 是 issue #80 開的，理由見下面「後四項為什麼現在
# 可以是關卡」；`tables` 是 issue #87 開的，見「tables 為什麼可以是關卡」；`encoding` 是
# issue #91 開的——它原本不是關卡而是 exit 2，理由見下面「exit code 的分類守則」與該項自己的註解）。
# 不擋（exit 0，只把發現印在 log）：`dupid`、`refs`、`r9` 三項，一律 advisory。
#
# 「GATES 是 True」只讓這個 check 自己變紅，**不等於它是 branch protection 的
# required status check**——後者是 repo 設定，要另外設，前提見下面「升 required 的前提」。
# 但「平台沒有機械阻擋」不等於「可以合併」：`M1` 要求測試綠，紅叉的 PR 依治理流程
# 不應合併。B 關卡的意思只是還沒有機器替人擋，不是放行。
#
# ── 那七項為什麼曾經全部停在 advisory（PR #20 六輪的停損）──────────────────
# 【歷史紀錄，寫於 stage 0。其中四項已於 issue #80 升為關卡，見下面專節；
#   `dupid`、`refs`、`r9` 三項仍停在 advisory，理由一、二對它們仍然成立。】
# 停損的理由，由輕到重：
#
#   一、六輪審查，每一輪都在當時的 required 項目上找到假陽性（誤擋合法內容）。
#       發現數 7、8、7、2、4、2，沒有收斂。一個會誤擋合法 PR 的 required 比沒有
#       required 更糟——它會讓人學會用 admin 權限繞過，那等於把保護整個拆掉。
#
#   二、判準本身錯過兩次。第三輪用「三輪都沒被找到假陽性」當理由把 refs 留在關卡，
#       第四輪一次就找到；第五輪改成「作者自己舉不出誤擋例子」才留 version，
#       第六輪審查者仍舉出一個（YAML document suffix 後接註解）。
#       結論：作者舉不出來，不代表不存在。
#
#   三、【最根本】devflow.yml 是 stage: 0，而 V1／V4 在第 3 節、S1 在第 2 節，
#       依 WORKFLOW.md 第 0 節「第 0、1、13 節永遠生效；其餘各節依 stage 啟用」
#       與 ST2「規格建版：加上第 2、3、9 節」——這三條規則在 stage: 0 下**還沒生效**。
#       我們花了六輪，把一條當前不在有效規則集內的規則做成 required gate。
#       把未生效的規則變成 gate，本身就是錯的，跟實作品質無關。
#       【已過期：devflow.yml 現在是 stage: 1，而 #63 把第 3 節的生效點併入 `ST1`
#       （「單線：第 3～8、10 節生效」），所以 V1／V4 現在是有效規則。S1 住第 2 節，
#       依 `ST2` 仍未生效——所以 `version` 這一關只引 V1／V4，不引 S1。】
#
# required 的目標移到 issue #22，而且**應該等 stage 進到 2 之後再談**——
# 在那之前，V1／V4／S1 都還不是有效規則，沒有東西可以拿來當 gate 的依據。
# 【已過期，同上：生效點改了，#22 也因此拆出 #80 把已解鎖的四項升關卡。】
#
# ── d2／i1 為什麼可以是關卡（issue #26）───────────────────────────────────
# 停損的診斷不是「CI gate 做不到」，是「選錯了檢查對象」。上面三個理由對照：
#
#   一、生效性：`D2` 在第 13 節、`I1` 在第 1 節。依 WORKFLOW.md 第 0 節
#       「第 0、1、13 節永遠生效」，這兩條在任何 stage 都是有效規則
#       （devflow.yml 現在是 stage: 1）。理由三不成立。
#
#   二、定義域封閉：失敗那七項的共同特徵是定義域含合法內容——`refs` 掃「任何檔案裡的
#       任何 code span」，`dupid` 掃「WORKFLOW.md 裡的任何清單項」，`version` 掃
#       「任意 YAML frontmatter」。這兩項不是：
#         `d2`：CLAUDE.md／AGENTS.md 兩個已知檔案，取檔案裡**第一個** begin 標記到
#               **其後第一個** end 標記，驗這一段 ≤30 行。字面比對（strip 後整行等於
#               標記），不看 markdown 結構、不看 nesting level、不看是否在 code block 內；
#               這段之後的標記一律忽略。這是 issue #26 的使用者裁決（B）。
#               這段之前若有 end 標記行也 ❌——D2 1.0.0.0 明寫區塊前不得有任何標記行
#               （issue #52）。定義域仍是「兩個已知檔案、兩個字面字串、第一次出現的位置」
#               ——沒有任何語法依賴，所以區塊**後面**的專案內容怎麼提到標記都不會誤擋。
#         `i1`：一個字串（GITHUB_HEAD_REF）符不符合 `<N>-<slug>`——
#               不打 API、不看 issue 是否存在、不猜 slug 的字元集（見下面「不發明規則」）。
#
#   三、判準：「作者舉不出誤擋例子就留在關卡」被推翻過兩次。`d2` 這裡也走過一遍——
#       前兩版用 markdown-it 找「真正的標記」，一版誤擋清單項裡的示例，修掉後下一版
#       又漏擋「整個真區塊縮在清單項內」。教訓是 D2 原文沒有規定區塊在頂層，任何
#       結構判準都是在發明規則。B 的字面判準把語法依賴歸零。原本還剩一種已知代價
#       （示例放在真區塊前面會驗錯段）——D2 1.0.0.0 把「區塊須為第一個標記組、其前無
#       標記行」寫進規則後，那不再是代價而是違規：begin 前的 end 由 `d2` ❌，完整的
#       示例組放在前面則依 D2 定義**它就是**區塊（安裝器會把它換成模板），見「擋不住什麼」。
#       要再降級，得由人裁決，不由本檔自己改。
#
# ── i5 為什麼可以是關卡（issue #75；規格是 docs/spec/install/spec.md AC-13）──────
# `I5` 住第 1 節，永遠生效。devflow.yml 把同一個事實寫了兩處：`seats.implementer.filler`
# （來源 S）與頂層 `implementer_filler`（投影 P）——安裝器 stdlib-only、不解析 YAML，只讀 P
# （AC-7）。投影靠人記得同步，正是 `I5` 要防的；AC-13 把一致性交給本檢查器機械保證。
#   一、定義域封閉：一個檔案（本 repo 根目錄的 devflow.yml）、兩條固定路徑、真 parser
#       （PyYAML compose 出的節點樹），沒有散文判讀。判定是 AC-13 逐條寫死的：
#         結構要求——恰一個 document；根、`seats` 的值、`seats.implementer` 的值都是 `!!map`；
#         這三個 mapping 的每個 key 都是 `!!str` 純量且鍵名不重複（引號鍵與裸鍵、alias 指向的
#         key 一視同仁，以 `.value` 比對）。任一不成立 → ❌。
#         三方比對——S、P 取值節點的 `.value`（須為 `!!str` 純量）；L＝直接載入
#         devflow/install.py 呼叫 read_implementer() 讀到的值（不另寫一份 AC-7 判定：兩份判定
#         就有第三個可漂移的東西）。通過 ⇔ 三者皆「無」，或三者皆為字串且逐字相等。
#       為什麼是 compose 不是 safe_load：construct 會把重複鍵 last-wins 合併、把引號鍵與裸鍵
#       合併、把 `<<` 展開——`"implementer_filler": codex` ＋ `implementer_filler: claude-code`
#       在 safe_load 後三者相等，卻正是過期投影。frontmatter 的 duplicate_version_key 同一機制。
#       為什麼要 L：S＝P 只保證 YAML 語意一致；`implementer_filler: *f`、`"claude-code"`、多行
#       plain scalar 續行在 compose 後 P 都取得到，安裝器卻讀不到或讀到別的東西。P＝L 保證
#       安裝器實際讀到的就是 YAML 語意。
#   二、生效性：`I5` 在第 1 節，任何 stage 都有效，不像 V1／V4／S1 要等 stage 2。
#   三、假陽性：合法輸入只有一種——投影寫成安裝器讀得到的裸字面值、與來源逐字相同。
#       其他寫法（alias、引號、顯式標籤）在 YAML 語意上等價，但安裝器讀不到，
#       AC-13 明文判 ❌：投影是給安裝器讀的，不是給 YAML parser 讀的。
#       「三者皆無」也通過——那表示這個 repo 沒用這個機制，不是違規。
#   正反 run 的紀錄在實作 PR（issue #75 AC-3）：正向＝本 repo 現行設定；反向＝把
#   `implementer_filler` 改成與 S 不同的值。其餘十個反向案例（規格「驗證」一節）在本地以
#   同一份檢查器逐案跑過，結果也記在 PR。
#
# ── 後四項為什麼現在可以是關卡（issue #80）────────────────────────────────
# `version`、`fence`、`table`、`link` 於 issue #80 升為關卡。逐項對照停損的三個理由：
#
#   * `version`（`V1` 四碼／`V4` 適用對象）
#       生效性：#63 把第 3 節的生效點併入 `ST1`，devflow.yml 是 stage: 1，V1／V4 已生效。
#               **不引 `S1`**（第 2 節，`ST2` 才生效）——那正是停損理由三記的錯。
#       定義域：兩類檔案——`devflow/WORKFLOW.md`，以及受版控且完全匹配
#               `docs/spec/<feature>/spec.md` 的檔。別的 .md 有 frontmatter version 也不管
#               （`V4`：第三方版本、工具版本保持原值）；`devflow/templates/spec.md` 是模板
#               不是規格文檔，同樣不在內。
#       假陽性：六輪找到的那個（YAML document suffix `... # 註解`）已修，本地以反例複驗
#               仍 exit 0。**不宣稱「不存在假陽性」**——那個宣稱被推翻過一次。
#
#   * `fence`（fenced code block 未關閉）
#       定義域：受版控 .md，判定用 markdown-it 自己切出來的 fence token，
#               收尾標記由 strip_containers() 剝掉 blockquote 標記與縮排後比對。
#       假陽性：#22 缺口 8（blockquote 內的合法 fence）由 strip_containers() 修掉；
#               本地以反例複驗（成對的 `> ```` 不報、清單項內縮排的 fence 不報、
#               `~~~` 包 ``` 不報；未關閉的、````↔``` 不對稱的仍報）。
#
#   * `table`（對照表形狀）
#       生效性：`R9` 住第 5 節，依 `ST5` 自 stage 0 起生效。
#       定義域：TABLE_DIRS 的**直屬** .md（七個檔）。原本的「一個檔案剛好一張表」
#               在 #66／PR #67 分節後會誤擋，已依 `R9` 的分節條文改寫，見該節的註解。
#       假陽性：本地以反例複驗——同一節兩張表、整檔未分節、節標題用 h3／粗體、
#               表被 blockquote 包住、code fence 裡的示範表，都不報。
#     issue #90 補兩類（#22 第三輪審查的假陰性 2、3；共同形狀是「parser 看到的」與
#     「讀者看到的」不一致）。併入 `table` 不另開 key：兩者和既有斷言一樣讀同一份
#     markdown AST、定義域同為上面七個檔、都是表形狀——#87 把 `tables` 分出去的理由
#     （資料來源與定義域不同）在這裡不成立。
#   * `table`：狀態格為空
#       生效性：同上（`R9`，`ST5`）。
#       定義域：合格表的資料列。markdown-it 把短列補成表頭欄數、補出的格為空字串，
#               只有空白的格也被 strip 成空字串（本地以 markdown-it-py 4.0.0 實測）；
#               兩者在 AST 上分不出來，讀者看到的同樣是空格，一併擋。
#       假陽性：看起來像誤擋但不是的——表格最後一列後面沒空行就接一段文字，那段文字會被
#               parser 收成一列、狀態格為空；GFM 規格的表格也是如此延伸（未在 GitHub 上實測），
#               讀者看到的是多了一列。本地以反例複驗：短列、`| x | y | z |   |`、
#               `| x | y | z ||`、tab／全形空白、表後緊接文字，都報。
#       仍擋不住：`&nbsp;`、`<!-- -->` 這類讀者看來是空、parser 看來非空的狀態格——那是值
#               不是形狀，交給 `r9`（建議）報「不是三值」。
#   * `table`：raw HTML 表格
#       生效性：同上。
#       定義域：對照表檔 AST 裡含 `<table` 的 html_block／html_inline（標籤名恰為 table、
#               大小寫不拘；blockquote、清單項、表格格內都算）。不解析 HTML 表的內容。
#       假陽性：判定用標準庫的 `html.parser.HTMLParser`，只認它判成 start tag 的
#               `<table>`——屬性名、屬性值、HTML 註解、未閉合引號裡的 `<table` 都不是
#               start tag，一律不報（前三輪的每個反例）。code fence／縮排 code block／
#               code span 的內容是 fence／code_block／code_inline token，根本不進 HTML
#               判定。`<tablefoo>`、`&lt;table&gt;`、`\<table>` 同樣不是 table start tag。
#               **不用正規式**：PR #92 三輪證明正規式在這裡不封閉（引號配對範圍、
#               屬性值含 `>`、畸形標籤），審查者第三輪判定應換 tokenizer。
#               對照表檔裡要示範 HTML 表格，放進 code fence。
#
#   * `link`（相對連結有效性）
#       定義域：受版控 .md 裡 AST 看得到的相對連結（行內連結、圖片、reference 定義）。
#               有 scheme 的、純 fragment 的不驗。
#       假陽性：#22 缺口 9（連結帶 query）已修（切 fragment 也切 query）；另修一個本地
#               找到的——`..probe.md` 這種合法檔名被 `startswith("..")` 判成逃出 repo，
#               改成比對路徑段。本地以反例複驗四種 query／fragment 組合皆不報。
#       仍擋不住：#22 缺口 6（指向 `.git/config` 之類受版控外但 runner 上存在的路徑），
#               本輪不處理，留在 #22；本輪也沒有讓它變得更糟。
#
# 這四項的正反案例是在本地以**同一份檢查器**逐案跑的（做法：把本檔的 inline python
# 原樣抽出來，在 `git archive HEAD` 造的臨時 repo 上套探針後執行，DEVFLOW_GATE_<KEY>=1
# 單獨打開目標項）。順序照上面「升 required 的前提」：本地正反 → 設 True → CI 正反。
# CI 上的正反 run 要另外取（負向輸入不落在本檔上），那是升 branch protection 的前提，
# 不是本檔自己變紅的前提。
#
# ── tables 為什麼可以是關卡（issue #87）──────────────────────────────────
# `table` 驗的是「已被選入的檔案」裡的表形狀，檔案集合本身只 sanity 檢查「至少找到一個」：
# `rm devflow/forges/github.md` 原本 exit 0，七張表刪掉六張也 exit 0（#22 第三輪審查的假陰性 1）。
#   為什麼是獨立的 key，不併入 `table`：兩者的資料來源、定義域、假陽性面都不同——`table` 讀
#       markdown AST、定義域是「目錄裡有什麼檔」；`tables` 讀 devflow.yml 的 YAML 節點、定義域是
#       「設定說要有什麼檔」。各自一個開關，其中一項日後被找到假陽性而降為建議時，另一項不跟著
#       失效；煙霧測試的「exit 1 只能由目標項造成」也才分得出是哪一半擋的。
#   生效性：依據是第 0 節「自變數住 `devflow.yml`：`forge`，以及 `seats` 下各職位的綁定——`filler`
#       ……其餘皆衍生值，見 `forges/`、`coders/`、`orchestrators/` 對照表」。第 0 節永遠生效。
#       那一條沒有 ID，所以引節號不引 ID。不引 `I5`：本項沒有第二處事實要比對，只是從既有的
#       自變數推導必須存在的檔案。
#   定義域：一個檔案（devflow.yml）裡的固定路徑——`forge`、`seats.implementer.filler`、
#       `seats.reviewer.filler`、`seats.coordinator.filler`——推導出至多四個檔名，逐字比對
#       table_files（受版控、TABLE_DIRS 直屬）。對應規則逐條寫在 TABLES_* 常數的註解。
#       不是「數量不得減少」：`forge` 改成 gitlab 之後 github.md 就可以刪，本項不擋。
#       fail closed：推導不出來（YAML 壞掉、缺 `forge`／`seats`、implementer／reviewer 省略、
#       職位不是 mapping、缺 `filler`、值不是字串、本項要讀的鍵重複）一律 ❌，不跳過也不 exit 2，
#       理由寫在該節開頭。`filler` 的值在該職位的目錄找不到 `<值>.md` 也是 ❌。
#       假陽性：合法設定裡會被擋的寫法——AC-13 明列的三個 mapping（根、`seats`、
#       `seats.implementer`）出現 merge key（`<<: *base`）時本項會判成「缺」。那是
#       **與 `i5` 一致**：AC-13 明文要求那三處不展開 `<<`，`i5` 本來就擋。
#       `seats.reviewer`／`seats.coordinator` 內層的 merge key **不在 AC-13 範圍**，
#       既有 `i5` 對它們是通過的，所以本項依 YAML merge 語意展開（tables_get），
#       不自行替 required gate 補規格沒有的禁令（審查者 PR #88 第二輪）。
#       alias（`reviewer: *x`、`filler: *f`）compose 後直接是被指向的節點，不受影響。
#       本地以反例複驗：`forge` 改 gitlab 後刪 github.md、`coordinator` 改 human 或整個省略後刪
#       hermes.md，都 exit 0。**不宣稱「不存在假陽性」**。
#
# ── 不發明規則：`i1` 的 slug 為什麼不限字元集 ─────────────────────────────
# `I1` 的原文只有「分支名 `<N>-<slug>`」，沒有規定 slug 的字元集。
# 收成 `^[0-9]+-[a-z0-9-]+$` 會擋掉 `26-封閉定義域`、`4-v0.0.2.0-bump`、`26-Fix-D2`——
# 那是檢查器發明的限制，正是 refs 誤擋 `M5` 的同一個錯。
# 所以只驗 WORKFLOW.md 真的寫了的部分：一個正整數、一個 `-`、非空的 slug。
# `<N>` 是 issue 號，issue 號從 1 起算，所以 `0-x` 不合——這不是發明，是 `<N>` 的定義。
#
# ── 升 required 的前提（README「Phase 1 第三出口的判定方式」）──────────────
# 把某一項升成 branch protection 的 required status check，README 要求三個條件：
#   條件一：正、反兩個 run 的 log 印出**相同的 blob id**——同一份檢查器才談得上正反驗證。
#   條件二：正向是合法輸入，無任何 ❌、conclusion＝success（檢查器 exit 0）。
#   條件三：負向相對正向**只新增目標項的違規**；其他項至多 📝，exit 1 只能由目標項造成
#           （exit 2 不算——那是檢查器自己壞了）。
# 前兩者的前提是 log 印得出「跑的是哪一份檔案」，所以本檔加了「記錄受測身分」那一步。
# 條件三要的負向輸入落在 AGENTS.md／CLAUDE.md（`d2`）、分支名（`i1`）、devflow.yml（`i5`）上，
# 都不是本檔的變更——換句話說，改本檔的 PR 只產得出正向 run，負向 run 要另外造。
# 條件一要求兩個 run 的 blob 相同，而 ❌／exit 1 只在 GATES 為 True 時出現：所以負向 run
# 跑的那份檢查器裡目標項已經是 True——本地先用同一份檢查器跑過全部反向案例，再上 CI 取
# 正反兩個 run，順序是「本地正反 → 設 True → CI 正反」，不是「CI 正反 → 設 True」。
# run 一律來自 pull_request 事件（README 的判定也只認 `event` ＝ `pull_request`）：本檔只有這一個
# 觸發，還沒開 PR 的分支跑不出 run，所以要升關卡的工單得**先開 PR（草稿即可）再取 run**——
# 負向輸入推一個探針 commit、取得 ❌ 後 revert（`i5` 的作法），或另開一條 probe 分支＋PR
# （`i1` 的作法，PR #42）。曾為此加過 workflow_dispatch，因它與 pull_request 共用 required
# context、較晚的 dispatch success 會蓋掉 PR 的 ❌ 而移除（PR #76 第一輪）；要再加得先換掉
# context 名稱並以實際 run 證明兩者不同。
#
# ── `version` 這一關在驗什麼（補充上面那節）──────────────────────────────
#   掃描對象是「devflow/WORKFLOW.md ＋ 受版控的 docs/spec/<feature>/spec.md」。
#   這不等於 V4 的適用對象：V4 還包含 kit release tag `v<a.b.c.d>`，而本檢查器
#   完全不讀 tag。spec 的數量也不是固定的一兩個，feature 增加就跟著增加。
#   值用原生 yaml.safe_load 取；重複 key 用 compose 看 node 偵測，不 construct，
#   才不會把合法的 merge key 弄成非法。
#   曾經宣稱「合法但會被擋的內容在定義上不存在」——**那是錯的，已被反例推翻**：
#   第六輪的 `... # frontmatter end` 是 YAML 1.2.2 §9.1.2 允許的 document suffix，
#   卻被判成 frontmatter 沒關閉。該 bug 已修，但這件事證明了這種宣稱不可靠。
#
# ── 擋不住什麼（已知不完備，不要假裝完備）──────────────────────────────
#   * 【八個關卡以外的全部。】以下各條說的是「連報告都報不到」，
#     或「報告了但沒有任何強制力」。
#   * 【`i5` 只看本 repo 的 devflow.yml。】消費者 repo 的投影一致性不在範圍（spec「未決事項」）：
#     它們只有安裝器 AC-7 的 advisory——「有 `seats:` 而無合規投影」會被提示，「兩處值不同」
#     無人攔。L 的定義是「devflow/install.py 現在讀到什麼」：改了讀取器，`i5` 跟著它走，
#     這是 AC-13 刻意的（唯一一份 AC-7 判定住在安裝器），不是漏洞。
#     `seats` 以外的職位（reviewer／coordinator／approver）的結構不驗——AC-13 只管兩條路徑
#     經過的三個 mapping。（reviewer／coordinator 的 `filler` 由 `tables` 讀，也只驗它讀的那幾個鍵。）
#   * 【`tables` 只驗「devflow.yml 指名的對照表受版控」。】表的內容對不對、是不是那個工具的表，
#     不驗（形狀歸 `table`；值與工具的對應要人讀）。沒被指名的表（現行的 gitlab.md、paperclip.md、
#     none.md）刪掉不擋——那是刻意的，它們不在當前設定的依賴裡。
#     `coordinator` 為 human 或整個省略時，不要求 orchestrators/none.md：issue #87 的判準是「human 不要求
#     對照表（人不是工具）」。但 none.md 開頭自稱是這個設定的對照表，所以本 repo 若把協調位改成 human，
#     none.md 被刪不會被擋——這個落差是判準的取捨，要改得由人裁決，不由本檔自己改。
#     `approver`、`seats` 下四個職位以外的鍵、`model`／`reasoning` 都不讀。
#   * 【`i5` 的 L 是在檢查器自己的行程裡執行 devflow/install.py 取得的——竄改該檔可繞過。】
#     攔得住的：import 期或 read_implementer() 內的例外、sys.exit（foreign() 攔 BaseException →
#     exit 2）、回傳非 str／str 子類（type() is str → exit 2）。攔不住的（PR #76 第二輪實測皆 exit 0）：
#     import 期 monkeypatch yaml.compose、atexit 註冊 os._exit(0)、read_implementer() 內 os._exit(0)
#     ——os._exit 繞過所有例外與 atexit，monkeypatch 發生在檢查器自己的行程內。
#     威脅模型不涵蓋這三者：都必須改 devflow/install.py 本身，而它在版控內、改動必經 PR ＋
#     required check ＋ 人工審查（PR #71 走了五輪）；能改它的人已經能直接改本檔關掉 GATES。
#     界線：**不需要惡意也會發生、且修法便宜**的才擋（sys.exit 早退、為了型別標註或包裝而回傳
#     str 子類）；只有蓄意竄改才會發生的，交給審查（G5 同一句話：本檢查器擋失誤，不擋蓄意規避）。
#   * 【`d2` 只驗第一段：第一個 begin 到其後第一個 end，≤30 行；有 begin 無 end 也擋；
#     第一個 begin 之前有 end 標記行也擋。】
#     區塊「內容」對不對、區塊外有沒有被安裝流程改到（D2 後半句），都要跟 base 比對
#     或跟 templates/entry-block.md 比對，本檢查器不做。第一段之後再出現的標記
#     一律忽略——第二個區塊、落單的標記，都不報。
#   * 【`d2` 不要求區塊存在。】D2 的原文是「入口檔只擁有這個區塊，≤30 行」，
#     沒有說「入口檔必須有這個區塊」——別的專案可能只裝了 CLAUDE.md 沒有 AGENTS.md。
#     所以檔案不在版控內、或檔案裡一個標記都沒有，都是 ⏭️ 略過，不是違規。
#     （只有 end 沒有 begin **不是**「一個標記都沒有」——那是 begin 前的落單 end，❌。）
#     代價：把整個區塊刪掉的 PR，`d2` 不會擋（會在 log 印出 ⏭️）。
#   * 【`i1` 只看 head branch 的形狀。】`<N>` 對不對應一個真實 issue 不驗（要打 API，
#     且 issue 可能已關閉）；`I1` 的另外三個「＝」（一個 worktree、一個 coder）
#     沒有任何機械來源可查。
#   * 【示例放在真區塊前面：D2 1.0.0.0 起是違規，不是判準 B 的代價。】D2 明寫「區塊須為
#     入口檔的第一個標記組，其前不得有任何 begin 或 end 行」。兩種形狀：
#       - 示例只含 end（或 end 先於 begin）：`d2` ❌「有落單的 devflow:end 在 begin 之前」
#         （issue #52 起），安裝器同判準 exit 1（install.py AC-5b）。
#       - 示例是完整的 begin…end 組：依 D2 的定義**它就是**區塊——`d2` 驗它 ≤30 行，
#         安裝器會把它換成模板、把後面「真正的」那份當專案內容留著。這裡沒有「驗錯段」，
#         是檔案本身不合 D2；但「第一組內容不是模板」要跟 templates/entry-block.md 比對
#         才看得出來，本檢查器不做（見本節第一條）。
#     本 repo 與安裝模板都把區塊放在檔案開頭，示例自然在後面。踩到時把示例移到區塊後面。
#     現況是 B 關卡：check 自己變紅、平台不機械阻擋；但依 `M1` 紅叉的 PR 不應合併，
#     所以踩到的人要改寫法或找人裁決，不是直接按合併。
#   * 【`i1` 只在 pull_request 事件有對象。】第 10 節的 bypass 是直推 main，不開 PR，
#     所以不需要在 `i1` 裡開例外——它根本不會跑到。反過來說，走 bypass 進 main 的
#     變更，`i1` 也擋不到。
#   * 【同一個規則 ID 被定義兩次 —— 沒有東西在擋。】
#     dupid 本來是關卡，第五輪被審查者找到一個假陽性（清單項只含 fence 時會吃到
#     清單外的段落）。那個 bug 已修，但作者接著自己又找到三個修不掉的：
#       - 附錄用清單解釋既有規則：「- `R3` 常被誤讀成…」
#       - 加一節「規則索引」把所有 ID 列一遍
#       - blockquote 引述既有條文
#     三者都是人會自然寫進 WORKFLOW.md 的東西，而 WORKFLOW.md 的定義寫法就是
#     「- `ID` 說明」，散文和定義在語法上分不出來。要分得出來就得知道「哪幾節裡的
#     清單項才是定義」——那是分節 schema，屬 issue #22（同樣要等 stage 2）。
#     它現在只報告：CI log 會列出來，但不會擋人。dupid 的 📝 需要人判斷是真重複
#     還是散文，不要當成一定有錯。
#   * 【改 ID 後別的檔案還指著舊號 —— 沒有東西在擋。】
#     refs 這一項本來就是為這個失效而存在的，但它會把 `M5`（Apple 晶片）、`C5`
#     （RFC 分類）這種合法的非規則代號判成懸空規則引用。WORKFLOW.md:7 只寫「引用規則
#     一律用 ID」，並沒有反向把所有這種形狀的 code span 保留給規則命名空間——所以那是
#     誤擋，不是使用者誤用。它現在是建議：CI log 會列出來，但**不會擋人，也沒有任何
#     機制保證有人讀**。實際擋這個失效的只剩人工審查（R4）。
#     升為關卡的條件（issue #22，且要等 stage 2）：建立保留命名空間，或把掃描範圍限定到可以宣告
#     「此處 ID 形狀的 code span 一律是規則引用」的檔案集合。在那之前，改動規則 ID 的
#     PR（#12／#17）建議手動跑一次 DEVFLOW_GATE_REFS=1。
#   * 另外四項：fenced code block 未關閉、對照表形狀、相對連結有效性、R9 狀態欄三值。
#     六輪審查的缺口幾乎都落在這些項目裡，因為它們驗的是「任意 markdown 內容」。
#     每項都能用 DEVFLOW_GATE_<KEY>=1 單獨打開，當成手動檢查工具跑。
#   * 【V1 的「進位歸零」沒驗】0.0.2.0 → 0.0.3.7 會通過。要驗它得跟 base 上的版本
#     比對（新的資料來源），而「該 bump 哪一位」依 V2／V3 是 normative／editorial 的
#     語意判斷，檢查器判不了。只驗「形式上有歸零」會擋掉合法的多位同時變更，
#     製造新的假陽性。留在 issue #22，本輪不做半套。
#   * 從未定義過的規則家族（例如 `Q3`）連建議都不會報：前綴集合＝基線 ∪ 現有定義的
#     前綴。放寬成「任何 ID 形狀」只會讓上面那個誤擋問題更嚴重。
#   * 權威檔案清單、raw HTML 內容（對照表檔內的 `<table` 除外，issue #90 起歸 `table`）、
#     對照表的分節 schema —— 都在 issue #22，本輪不做。
#   * frontmatter 的界定（首行 --- 到下一個 --- 或 ...，兩者後面都可以接註解）仍是
#     字面掃描；那是慣例不是 markdown 語法，沒有 parser 可問。界定出來的內容才交給
#     PyYAML。這一段的邊界寫法若還有沒想到的，仍可能誤判。
#   * GitHub 的算繪器不等於 markdown-it；兩者對極端輸入可能有差異。
#   * 只看受版控的 .md。非 markdown 檔、PR body、commit 訊息都不在範圍內。
#   * G5：required check 由 PR 分支上的 workflow 定義產生——想繞過的人可以直接改本檔。
#     本檢查器擋的是失誤，不是蓄意規避；後者由審查擋。
"""devflow 規則檢查。exit 0 通過／1 必需關卡失敗／2 檢查器本身無法執行。
（`--print-pins`／`--check-pins` 是不跑關卡的查詢模式，exit code 另有意思，見下面 PINS 那節。）"""
import importlib.util
import os
import re
import subprocess
from html.parser import HTMLParser
import sys
import traceback
from pathlib import Path
from urllib.parse import unquote


# ── exit code 的分類守則 ─────────────────────────────────────────
# exit 1 只有一個意思：某個必需關卡判了 ❌（內容違規）。exit 2 是「檢查器本身無法執行」——
# 缺相依、不在 repo 內、外來程式碼逸出、解析器受限、以及**任何沒被明確分類的例外**。
# Python 對未攔截的例外預設以 1 結束，會和關卡失敗撞號（PR #76 第三輪：深巢狀 devflow.yml
# 讓 yaml.compose 拋 RecursionError，投影明明一致卻被記成 i5 ❌）。這個 hook 把所有漏網的
# 例外統一收成 exit 2；SystemExit 不經 hook，所以 die() 與關卡的 sys.exit(1) 不受影響。
# traceback 照印（除錯要用），另補一行 💥 說明分類。
#
# 分界的判準是「壞掉的是誰」，不是「哪一步失敗」：
#   * 受版控 .md 的**內容**不是合法 UTF-8 ── exit 1（`encoding` 關卡，issue #91 缺口 11）。
#     檢查器執行得好好的，是被檢查的檔案有問題；判 2 會讓「有人 commit 了壞編碼的 md」
#     看起來像 CI 故障。改判之前實測 exit 2（read_text 的 UnicodeDecodeError 走 die()）。
#   * 同一個檔案**開不起來**（OSError）仍是 exit 2：`git ls-files` 說它在版控內、工作樹卻
#     讀不到，那是 repo 佈局／執行環境與本檔假設不符，不是檔案內容違規。
#   * 受版控的**檔名**不是 UTF-8 仍是 exit 2（tracked()）：本輪不動，它不在 issue #91
#     AC-1 的定義域（「非 UTF-8 的受版控 markdown」指內容）內，改它等於自行擴大 AC。
def _uncaught(exc_type, exc, tb):
    try:
        sys.stdout.flush()
        traceback.print_exception(exc_type, exc, tb)
        print("💥 檢查器無法執行：未預期的 %s: %s（未分類的例外一律 exit 2，不是關卡失敗）"
              % (exc_type.__name__, exc))
        sys.stdout.flush()
    finally:
        sys.exit(2)               # 連印出訊息都失敗（stdout 編碼之類）也要是 2，不能退回預設的 1
sys.excepthook = _uncaught


# ── 相依版本 pin 的單一來源（issue #91 AC-3）──────────────────────
# 版本號只寫在這裡一處（`I5`：一個事實一個來源）。workflow 的「準備檢查器相依」step
# 以 `--print-pins` 取值去驗版本與安裝，不複寫版本號。
#
# 為什麼單一來源放檢查器而不是 workflow：README「Phase 1 第三出口」的條件一要求
# 正反兩個 run 用同一份檢查器，而 workflow 的「記錄受測身分」step 印的是**本檔的 blob**。
# pin 住在本檔，blob 相同就保證「要求的 parser 版本」也相同；pin 若住 workflow，
# 只改 workflow 的 pin 不會動到 blob，條件一就只保證得了腳本、保證不了 parser。
# 另外本檔是唯一真的 import 這兩個模組的地方——相依是它的事實，不是 CI 的事實。
#
# 這不是執行期的版本斷言：本檔不因裝的版本不符 pin 而報錯（那會擋死本機開發，
# 也不在 AC 內）。實際跑的版本照樣印在下面的「檢查器：…」那一行，供人對照。
PINS = (("markdown-it-py", "3.0.0"), ("PyYAML", "6.0.1"))

# 兩個查詢模式。都在相依**安裝之前**跑，所以只能用標準庫——不得碰下面的 import。
#   --print-pins  印出 `<套件>==<版本>` 每行一筆，直接可以餵給 pip install
#   --check-pins  印出實際裝的版本；exit 0＝全部符合 pin，1＝有不符的（呼叫端該去裝）
#
# 查詢模式的 exit code **不是**檔頭那套守則：那套說的是「跑了關卡之後的結論」，
# 而查詢模式一個關卡都沒跑。這裡的 1 只是「答案是否」，呼叫端（workflow 的準備 step）
# 把它轉成安裝動作，不是轉成關卡失敗。2 仍然只有一個意思：檢查器本身無法執行。
#
# 為什麼版本比對寫在這裡而不是 workflow 的 shell：一來 pin 就住這裡，比對跟著它走才不會
# 各自漂移；二來 issue #91 明寫 workflow 的改動要盡量小（改 CI 有自我驗證問題），
# 邏輯留在腳本、workflow 只呼叫，改壞的面積最小；三來這段邏輯因此也被「記錄受測身分」
# 印出的 blob 蓋住，和 pin 本身享有同一份可追溯性。
_QUERY_MODES = ("--print-pins", "--check-pins")
_args = sys.argv[1:]
if [a for a in _args if a not in _QUERY_MODES]:
    # 不默默忽略：認不得的旗標若被當成「沒有旗標」，準備 step 的一個錯字就會在那裡
    # 跑起完整的規則檢查、以 exit 1 收場，看起來像關卡失敗。那正是本單要消滅的誤導。
    print("💥 檢查器無法執行：認不得的參數 %s（只接受 %s，或完全不帶參數）"
          % (" ".join(a for a in _args if a not in _QUERY_MODES), "／".join(_QUERY_MODES)))
    sys.exit(2)

if "--print-pins" in _args:
    for _dist, _ver in PINS:
        print("%s==%s" % (_dist, _ver))
    sys.exit(0)

if "--check-pins" in _args:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _installed_version
    _bad = []
    for _dist, _ver in PINS:
        try:
            _got = _installed_version(_dist)
        except PackageNotFoundError:
            _got = None
        print("%s：裝的是 %s，pin 是 %s%s"
              % (_dist, _got or "（未安裝）", _ver, "" if _got == _ver else "  ←不符"))
        if _got != _ver:
            _bad.append(_dist)
    # 只比 distribution 的版本，不 import：這條路徑的存在理由就是「裝之前也要能問」。
    sys.exit(1 if _bad else 0)

try:
    import yaml
    from markdown_it import MarkdownIt
    import markdown_it
except ImportError as e:
    print("💥 檢查器無法執行：缺少相依模組 %s" % e.name)
    sys.exit(2)

# ── 關卡開關 ──────────────────────────────────────────────────────
# True＝必需關卡（失敗就擋）；False＝建議（只報告）。
# 十二項裡九項是 True，三項是 False。分界是定義域封不封閉，理由見檔頭。
# 驗證用：DEVFLOW_GATE_<KEY>=1 可單獨打開一項，環境變數只能加嚴不能放寬。
# 順序＝執行順序：`encoding` 在讀檔當下就判，排在最前面。
GATES = {
    "encoding": True,   # 受版控 .md 的內容是合法 UTF-8（issue #91）
    "d2":      True,    # D2 入口區塊 ≤30 行（第 13 節，永遠生效）
    "i1":      True,    # I1 head branch 名為 <N>-<slug>（第 1 節，永遠生效）
    "i5":      True,    # I5 devflow.yml 投影 implementer_filler 三方一致（第 1 節，永遠生效；spec AC-13）
    "version": True,    # V1 frontmatter version 四碼（第 3 節，ST1 起生效；issue #80）
    "fence":   True,    # fenced code block 未關閉（issue #80）
    "tables":  True,    # devflow.yml 指名的對照表都受版控（第 0 節，永遠生效；issue #87）
    "table":   True,    # 對照表形狀，依 R9 分節（issue #80）
    "link":    True,    # 相對連結有效性（issue #80）
    "dupid":   False,   # 規則 ID 唯一定義（散文與定義分不出來，見檔頭）
    "refs":    False,   # 規則 ID 無懸空引用（會誤擋非規則代號，見檔頭）
    "r9":      False,   # R9 對照表狀態欄三值（值欄該記什麼未定案，見 issue #13／#22）
}
for _k in GATES:
    if os.environ.get("DEVFLOW_GATE_" + _k.upper()) == "1":
        GATES[_k] = True

# ── 設定 ──────────────────────────────────────────────────────────
RULES_FILE = "devflow/WORKFLOW.md"
# D2 的定義域：兩個已知檔案、兩個字面標記。標記字串以 WORKFLOW.md 的 D2 為準。
ENTRY_FILES = ("CLAUDE.md", "AGENTS.md")
D2_BEGIN = "<!-- devflow:begin -->"
D2_END = "<!-- devflow:end -->"
# 行數含頭尾兩行標記，和 D2 的推導方式一致
# （sed -n '/begin/,/end/p' | wc -l，現況兩檔皆 15）。
D2_MAX_LINES = 30
# I1 的定義域：一個字串。只驗 WORKFLOW.md 真的寫了的部分——
# 一個正整數（<N> 是 issue 號，從 1 起算，所以不收 0 開頭）、一個 `-`、非空的 slug。
# slug 的字元集 I1 沒有規定，收窄就是發明規則（見檔頭「不發明規則」）。一律 fullmatch。
BRANCH_RE = re.compile(r"[1-9][0-9]*-.+")
# I5（spec AC-13）的定義域：一個檔案、兩條固定路徑、一個讀取函式。
# S＝seats.implementer.filler、P＝根層 implementer_filler、L＝安裝器 read_implementer() 讀到的值。
I5_FILE = "devflow.yml"
I5_INSTALLER = "devflow/install.py"
I5_PROJECTION = "implementer_filler"
I5_SOURCE_PATH = ("seats", "implementer", "filler")
YAML_MAP = "tag:yaml.org,2002:map"
YAML_STR = "tag:yaml.org,2002:str"
# 對照表的定義域：這三個目錄的**直屬** .md（見下面 table_files 的取法）。
# 不遞迴子目錄——devflow/orchestrators/hermes/SKILL.md 是該 orchestrator 的流程指令
# （hermes.md 的「流程指令住哪」格就指向它），不是對照表；把它算進來會要求
# 一個流程指令檔長出 `面向／值／狀態` 表，那是檢查器發明規則。
FORGES_DIR = "devflow/forges/"
CODERS_DIR = "devflow/coders/"
ORCHESTRATORS_DIR = "devflow/orchestrators/"
TABLE_DIRS = (FORGES_DIR, CODERS_DIR, ORCHESTRATORS_DIR)
# tables（issue #87）的定義域：devflow.yml 的固定鍵 → 必須受版控的對照表檔。
# 依據是第 0 節「自變數住 devflow.yml：forge 與 seats 下各職位的 filler……其餘皆衍生值，
# 見 forges/、coders/、orchestrators/ 對照表」。對應規則：
#   `forge: <v>`                    → devflow/forges/<v>.md
#   `seats.implementer.filler: <v>` → devflow/coders/<v>.md          實作位填的是 coder
#   `seats.reviewer.filler: <v>`    → devflow/coders/<v>.md          審查位填的也是 coder
#   `seats.coordinator.filler: <v>` → devflow/orchestrators/<v>.md   協調位填的是 orchestrator
#   `seats.approver`                → 不讀（裁決位是人，seats/approver.md）
#   `filler: human`                 → 不要求（人不是工具）
#   省略整個 `coordinator`          → 等同 human，不要求（第 0 節「`coordinator` 省略＝`human`」）
# 第 0 節只給 `coordinator` 定了省略的意思；implementer／reviewer 省略、或職位在但缺 `filler`，
# 檢查器不替它發明預設值——推導不出來就 ❌（fail closed，見 tables 那一節）。
# 值在該職位的目錄找不到 `<v>.md` 就是 ❌，不管別的目錄有沒有同名檔：`implementer.filler: hermes`
# 要的是 coder 的表，orchestrators/hermes.md 補不了這個缺。兩個目錄都沒有＝設定指向一個
# 沒有衍生值的工具，同樣 ❌（那也可能就是表被刪了，檢查器分不出來，也不需要分）。
# 檔名是 `<目錄><值>.md` 這個**字串**，拿去比 table_files（受版控、直屬），不做路徑正規化：
# `hermes/SKILL`、`../WORKFLOW` 這種值湊不出直屬檔名，自然判成找不到。
TABLES_FORGE = ("forge", FORGES_DIR)
TABLES_SEATS = "seats"
TABLES_SEAT_DIRS = (("implementer", CODERS_DIR),
                    ("reviewer", CODERS_DIR),
                    ("coordinator", ORCHESTRATORS_DIR))
TABLES_OPTIONAL_SEAT = "coordinator"
TABLES_FILLER = "filler"
TABLES_HUMAN = "human"
TABLE_HEADER = ["面向", "值", "狀態"]
STATUS_COL = "狀態"
# R9 的分節：「對照表得分為通用節與本機節」。節名用詞以 R9 為準，
# 標題層級 R9 沒有規定，所以不看層級（現行七張表都寫成 `## 通用`／`## 本機`）。
TABLE_SECTIONS = ("通用", "本機")
# R9 的三值，用詞以 devflow/WORKFLOW.md 的 R9 為準。
R9_STATUSES = ("✅ 可用", "📝 已宣稱", "⬜ 未測")
# 三值後面可以接補充（R9 要求 ✅ 附驗證方式、📝 標明是哪一種），
# 但必須是「三值 ＋ 分隔符」，不能是「✅ 可用性佳」這種黏著詞。
R9_SEPS = " \t（(：:，,。、；;）)"
OLD_TOKENS = ("✅ 實測", "⬜ 未實測", "⬜ 未實作")
# 規則家族前綴的基線。實際集合是「基線 ∪ WORKFLOW.md 現有定義的前綴」：
# 加新家族自動納入，整個家族被刪掉時基線仍擋得住懸空引用。
BASELINE_PREFIXES = {"I", "S", "V", "L", "R", "M", "F", "C", "G", "B", "ST", "P", "D"}
# 一律用 fullmatch，不用 match：Python 的 $ 會匹配「字串最後一個換行之前」，
# 所以 ^…$ ＋ match() 會讓 "0.0.2.0\n" 這種含換行的值矇混過關。
ID_RE = re.compile(r"([A-Z]{1,4})[0-9]+")

MD = MarkdownIt("commonmark").enable("table")
errors = []
advisories = []


def die(msg):
    print("💥 檢查器無法執行：%s" % msg)
    sys.exit(2)


def report(gate, msg, detail=()):
    """依 GATES 決定這一項是擋還是只報告。兩條路都走同一個 detail。"""
    detail = list(detail)
    if GATES[gate]:
        errors.append(msg)
        print("  ❌ %s" % msg)
        for d in detail:
            print("      %s" % d)
        return
    advisories.append(msg)
    print("  📝 %s" % msg)
    for d in detail[:5]:
        print("       %s" % d)
    if len(detail) > 5:
        print("       …（另有 %d 筆同類，升為關卡後會全部列出）" % (len(detail) - 5))


def ok(msg):
    print("  ✅ %s" % msg)


def tag(gate):
    return "必需關卡" if GATES[gate] else "建議"


# ── 取得受版控的檔案（NUL 分隔，檔名含空白也不會被拆開）────────────
def tracked():
    p = subprocess.run(["git", "ls-files", "-z"], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
    if p.returncode != 0:
        die("git ls-files 失敗（exit %d）：%s"
            % (p.returncode, p.stderr.decode("utf-8", "replace").strip()))
    out = []
    for raw in p.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            out.append(raw.decode("utf-8"))
        except UnicodeDecodeError:
            die("受版控的檔名不是 UTF-8：%r" % raw)
    return out


def read_text(path):
    """回傳 (text, err, nbytes)：err 是 UnicodeDecodeError，解得開就是 None；
    nbytes 是檔案的位元組長度（算絕對位移要用，見 decode_error_detail）。

    utf-8-sig：BOM 對 GitHub 的算繪無影響，不該讓 frontmatter 偵測失效。

    解碼失敗**不 die()**（issue #91 缺口 11）：檔案內容不是合法 UTF-8 是內容違規
    （exit 1 的 `encoding` 關卡），不是檢查器無法執行。而且要 fail closed——這裡仍以
    errors="replace" 把文字交出去，讓該檔的其他關卡照跑，不因為「讀不乾淨」就把
    整個檔案從 d2／fence／version／table／link 的定義域裡摘掉。壞掉的位元組變成
    U+FFFD，其餘位元組原樣保留，行結構不變，所以行號仍然對得上。

    開不起來（OSError）仍是 die()／exit 2：git 說它在版控內、工作樹卻讀不到，
    那是執行環境與本檔假設不符，不是被檢查的內容有問題。
    """
    try:
        raw = Path(path).read_bytes()
    except OSError as e:
        die("讀不到 %s：%s" % (path, e))
    try:
        return raw.decode("utf-8-sig"), None, len(raw)
    except UnicodeDecodeError as e:
        return raw.decode("utf-8-sig", "replace"), e, len(raw)


def decode_error_detail(path, raw_len, e):
    """把 UnicodeDecodeError 講成「哪個檔、哪一行、哪個位元組」。

    utf-8-sig 會先剝掉 BOM 再解，所以 e.object 是剝完的緩衝區、e.start 相對於它——
    要換回檔案裡的絕對位移得補回被剝掉的長度，不然帶 BOM 的檔會報少 3。"""
    skipped = raw_len - len(e.object)
    line = e.object.count(b"\n", 0, e.start) + 1
    return ["%s:%d 位元組偏移 %d（0-based，自檔首算起）是 %s"
            % (path, line, e.start + skipped,
               " ".join("0x%02x" % b for b in e.object[e.start:e.end])),
            "codec 的說法：%s" % e.reason,
            "受版控的 markdown 必須是 UTF-8（BOM 可有可無）；"
            "多半是別的編碼（Big5／GBK／Latin-1）存進來的，用 iconv 轉回 UTF-8 即可"]


# ── 從 AST 取事實：不用正規式猜「這是不是表格／清單項／程式碼」──────
def locate(lines, tok, needle=None):
    """回傳 1-based 行號。有 needle 就在 token 涵蓋的行裡找它。"""
    if not tok.map:
        return None
    start, end = tok.map
    if needle:
        for n in range(start, min(end, len(lines))):
            if needle in lines[n]:
                return n + 1
    return start + 1


def rule_definitions(tokens, lines):
    """清單項開頭是 `ID` 的都算定義——縮排、巢狀、粗體、blockquote 一律算。
    寧可多認（誤報看得見）也不少認（漏報是沉默的）。"""
    out = []
    for i, t in enumerate(tokens):
        if t.type != "list_item_open":
            continue
        for j in range(i + 1, len(tokens)):
            tj = tokens[j]
            if tj.type in ("list_item_open", "list_item_close"):
                # list_item_open：已經進到子項。list_item_close：這個 item 結束了
                # ——少了它，清單項只含 fence（沒有 inline）時會一路吃到清單外面
                # 的段落，把那裡的引用當成本項的開頭。
                break
            if tj.type != "inline":
                continue
            first = None
            for c in tj.children or []:
                # 粗體／斜體／連結的開標記，以及它們前後產生的空 text token，
                # 都不算「開頭」——`R3` 被 ** 包起來仍然是定義。
                if c.type in ("strong_open", "em_open", "s_open", "link_open"):
                    continue
                if c.type == "text" and not c.content.strip():
                    continue
                first = c
                break
            if first is not None and first.type == "code_inline":
                content = first.content.strip()
                if ID_RE.fullmatch(content):
                    out.append((content, locate(lines, t, "`%s`" % content)
                                or locate(lines, t)))
            break
    return out


def code_spans(tokens, lines):
    """所有行內 code span。程式碼區塊裡的內容不會產生 inline token，天然排除。"""
    for t in tokens:
        if t.type != "inline":
            continue
        for c in t.children or []:
            if c.type == "code_inline":
                content = c.content.strip()
                yield content, (locate(lines, t, "`%s`" % content) or locate(lines, t))


def section_name(text):
    """標題文字是不是 R9 的節名。兩端的空白與粗體／斜體標記不計
    （`## **通用**` 和 `## 通用` 是同一個節）；其餘一律不是節標題。"""
    t = text.strip().strip("*_").strip()
    return t if t in TABLE_SECTIONS else None


def r9_sections(tokens):
    """檔案裡出現過的 R9 節標題，依出現順序。空清單＝整檔未分節。

    只認**文件層級**的標題：blockquote／list 等容器內的 `## 通用` 是引用或
    舉例，不是這份檔案的分節（審查者 PR #81 第一輪反例：`> ## 通用` 會讓
    節外的表被誤判為合格）。markdown-it 對容器內的 token 設 level > 0。"""
    out = []
    heading_level = None
    for t in tokens:
        if t.type == "heading_open":
            heading_level = t.level
        elif t.type == "heading_close":
            heading_level = None
        elif heading_level is not None and t.type == "inline":
            lv, heading_level = heading_level, None
            if lv != 0:
                continue
            name = section_name(t.content)
            if name:
                out.append(name)
    return out


def tables_of(tokens, lines):
    """每張表連同它所在的 R9 節（`section`；不在任何節下＝None）。

    節的範圍＝從該節標題到下一個**同層或更淺**的標題為止。更深的子標題
    （`## 通用` 下的 `### 細節`）仍在該節內——把子標題當成節結束會誤擋
    合法的結構（審查者 PR #81 第一輪反例）。R9 沒有規定節標題的層級，
    所以層級由該檔實際使用的節標題決定，不寫死 h2。

    用**堆疊**保存外層節，不是單一變數：`## 通用` 下的 `### 通用` 結束後
    仍應回到外層的「通用」，單一 `section_depth` 會把整個節清空（審查者
    PR #81 第二輪反例）。堆疊每層記 (層級, 節名或 None)。

    只認文件層級的標題：blockquote／list 等容器內的標題（token level > 0）
    是引用或舉例，既不開節也不關節。"""
    out = []
    cur = part = row = None
    stack = []          # [(depth, section_or_None), ...]，depth 遞增
    depth = None

    def current_section():
        for _, name in reversed(stack):
            if name:
                return name
        return None

    for t in tokens:
        if t.type == "heading_open":
            depth = int(t.tag[1:]) if t.tag[:1] == "h" and t.tag[1:].isdigit() else None
            if t.level != 0:
                depth = None          # 容器內的標題：不開節也不關節
            continue
        if t.type == "heading_close":
            continue
        if depth is not None and t.type == "inline":
            while stack and stack[-1][0] >= depth:
                stack.pop()
            stack.append((depth, section_name(t.content)))
            depth = None
            continue
        depth = None
        if t.type == "table_open":
            cur = {"line": locate(lines, t), "header": [], "header_line": None,
                   "body": [], "section": current_section()}
        elif t.type == "table_close":
            if cur is not None:
                out.append(cur)
            cur = part = row = None
        elif t.type == "thead_open":
            part = "head"
        elif t.type == "tbody_open":
            part = "body"
        elif t.type == "tr_open":
            row = {"line": locate(lines, t), "cells": []}
        elif t.type == "tr_close":
            if cur is not None and row is not None:
                if part == "head":
                    cur["header"] = row["cells"]
                    cur["header_line"] = row["line"]
                else:
                    cur["body"].append(row)
            row = None
        elif t.type == "inline" and row is not None:
            row["cells"].append(t.content.strip())
    return out


# raw HTML `<table>` 的判定：用標準庫的 HTMLParser，不用正規式。
#
# 正規式做過三輪都不封閉（PR #92）：對整個 token 配對引號會把文字內容裡的引號
# 當屬性引號、吃掉中間真正的表格；改切標籤後，`[^>]*?` 又在屬性值含 `>` 時提早
# 結束，畸形標籤也切不準。審查者第三輪的結論是「應改用 HTML tokenizer/parser，
# 而不是繼續擴充單一正規式」——用正規式解析 HTML 本來就不成立。
#
# HTMLParser 只回報**它判定為 start tag** 的東西：屬性名、屬性值、註解、未閉合
# 引號裡的 `<table` 都不會變成 handle_starttag 的呼叫，前三輪的每個反例自然消失。
# 它也給 (行, 欄)，行號直接可用，不必回頭在原文搜字串（那正是第三輪行號錯置的
# 根因）。容錯：HTMLParser 對畸形輸入不拋例外，照 HTML5 的錯誤復原規則繼續。
class _TableTagFinder(HTMLParser):
    """找出 raw HTML 裡的 `<table>` start tag，回報其相對行號（1-based）。

    `set_cdata_mode` 是 HTMLParser 的內部開關：碰到 `<script>`／`<style>` 後把後續
    內容當 raw text，裡面的標籤不再回報。但 **markdown 的 `<script>` 在 GitHub 上會
    被清掉、裡面的內容照樣渲染**——審查者 PR #92 第四輪實測 `<script>` 內的 table
    最終有渲染出來。對照表檔不該有 script/style，一律當成普通標籤繼續解析。"""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.hits = []

    def set_cdata_mode(self, *args, **kwargs):   # noqa: N802（覆寫內部方法）
        pass

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.hits.append(self.getpos()[0])

    handle_startendtag = handle_starttag


def html_table_lines(text):
    """text 裡 `<table>` start tag 的相對行號（1-based，相對於 text 的第一行）。"""
    p = _TableTagFinder()
    try:
        p.feed(text)
        p.close()
    except Exception:            # HTMLParser 幾乎不拋，真拋了就當作有問題
        return [1]
    return p.hits


def raw_html_tables(tokens, lines):
    """AST 裡的 raw HTML `<table>` 所在行號（issue #90 缺口 2）。

    只認 parser 判成 HTML 的 token：區塊層的 html_block、行內的 html_inline（在 inline 的
    children 裡，容器內、表格格內都算）。code fence／縮排 code block／code span 的內容是
    fence／code_block／code_inline token，天然排除——那是示範，不是資料。
    不解析 HTML 表的內容（表頭、欄位、狀態格都不看）：那會讓檢查器變成第二個 parser。"""
    out = []
    for t in tokens:
        if t.type == "html_block":
            for rel in html_table_lines(t.content):
                out.append((t.map[0] + rel) if t.map else None)
        elif t.type == "inline":
            # 同一個 inline token 的 html_inline children 是**同一段 HTML 被文字切開**
            # （`<div>` 文字 `</div>`），要串起來才解析得出跨 child 的標籤。
            #
            # 但**不能只串 HTML、丟掉中間的文字**：那些位置的換行也佔行數，丟掉後
            # parser 的相對行號就少算（審查者 PR #92 第五輪：真實第 22 行報成 20）。
            # 換行在 inline 裡是 `softbreak`／`hardbreak` token，**`content` 是空字串**
            # ——不能數 `content` 裡的 `\n`，要認 token 型別。
            kids = t.children or []
            if not any(c.type == "html_inline" for c in kids):
                continue
            parts = []
            for c in kids:
                if c.type == "html_inline":
                    parts.append(c.content)
                elif c.type in ("softbreak", "hardbreak"):
                    parts.append("\n")
                else:
                    parts.append("\n" * c.content.count("\n"))
            base = t.map[0] if t.map else None
            for rel in html_table_lines("".join(parts)):
                out.append((base + rel) if base is not None else None)
    return out


def link_targets(tokens, env, lines):
    """行內連結、圖片、以及未被使用的 reference 定義。跨行、成對括號、
    角括號形式都由 parser 處理，不是我在猜。"""
    out = []
    for t in tokens:
        if t.type != "inline":
            continue
        ln = locate(lines, t)
        for c in t.children or []:
            if c.type == "link_open":
                href = c.attrGet("href")
                if href:
                    out.append((href, ln))
            elif c.type == "image":
                src = c.attrGet("src")
                if src:
                    out.append((src, ln))
    for label, ref in (env.get("references") or {}).items():
        href = (ref or {}).get("href")
        if not href:
            continue
        ln = None
        for n, line in enumerate(lines):
            if line.lstrip().lower().startswith("[%s]:" % label.lower()):
                ln = n + 1
                break
        out.append((href, ln))
    return out


def strip_containers(s):
    """剝掉 blockquote 標記與縮排，只留這一行真正的內容。
    引言區塊裡的 fence 收尾寫成「> ```」，不剝就會被誤判成沒關閉。"""
    prev = None
    while prev != s:
        prev = s
        s = s.lstrip()
        if s.startswith(">"):
            s = s[1:]
    return s.strip()


def unclosed_fence(tokens, lines):
    """fence token 的最後一行不是合格的收尾標記，就是沒關閉。用 parser 自己的切分。
    收尾標記必須同字元、且不短於開頭——```` 開就不能用 ``` 關。"""
    for t in tokens:
        if t.type != "fence" or not t.map:
            continue
        end = t.map[1]
        if end < 1 or end > len(lines):
            return t.map[0] + 1
        cand = strip_containers(lines[end - 1])
        mark = t.markup or "```"
        if not cand or set(cand) != {mark[0]} or len(cand) < len(mark):
            return t.map[0] + 1
    return None


# ── frontmatter：界定是字面掃描（慣例，非 markdown 語法），值交給 PyYAML ──
def duplicate_version_key(fm):
    """頂層是不是寫了不只一個 version key。
    只 compose 不 construct：一旦 construct 就會攔截到 merge key（<<: *d）
    而讓合法的 YAML 變成非法——偵測重複和解析值必須分開做。
    看 node.value 而不是解析後的 dict，"version" 這種加引號的寫法才抓得到。"""
    try:
        node = yaml.compose(fm)
    except yaml.YAMLError:
        return False          # 真的壞掉的話由 safe_load 去報
    if not isinstance(node, yaml.MappingNode):
        return False
    n = 0
    for k, _v in node.value:
        if (isinstance(k, yaml.ScalarNode)
                and k.tag != "tag:yaml.org,2002:merge"
                and k.value == "version"):
            n += 1
    return n > 1


# 開頭與結束標記後面都可以接註解：YAML 1.2.2 §9.1.2 的 document suffix 允許
# 「... # 註解」。只比對「rstrip 後完全等於 --- 或 ...」會把合法寫法誤判成
# 沒關閉——這一項是規則沒有規定的限制，不該由檢查器發明。
FM_OPEN_RE = re.compile(r"---[ \t]*(?:#.*)?")
FM_TERM_RE = re.compile(r"(?:---|\.\.\.)[ \t]*(?:#.*)?")


def frontmatter(lines):
    """回傳 ('none'|'unclosed'|'ok', 內容字串)。
    結尾要補回換行：YAML 區塊純量（version: | ）的收尾語意取決於最後一行有沒有
    換行，少了它檢查器看到的值就和真正讀這個檔案的 parser 不一樣。"""
    if not lines or not FM_OPEN_RE.fullmatch(lines[0].rstrip()):
        return "none", ""
    for j in range(1, len(lines)):
        if FM_TERM_RE.fullmatch(lines[j].rstrip()):
            return "ok", "\n".join(lines[1:j]) + "\n"
    return "unclosed", ""


# ── 前置 sanity：不在 repo 內或抓不到檔案時要炸掉，不能靜默跳過 ────
files = tracked()
md_files = [f for f in files if f.endswith(".md")]
# 直屬：去掉目錄前綴後不得再含 `/`（見 TABLE_DIRS 的註解）。
table_files = sorted(f for f in md_files
                     if any(f.startswith(d) and "/" not in f[len(d):]
                            for d in TABLE_DIRS))
if not files:
    die("git ls-files 沒有回傳任何受版控的檔案（不在 git work tree 內？）")
if RULES_FILE not in files:
    die("找不到受版控的 %s，repo 佈局與檢查器假設不符" % RULES_FILE)
if not table_files:
    die("在 %s 下找不到任何對照表" % "／".join(TABLE_DIRS))
print("檢查器：python %s／markdown-it-py %s／PyYAML %s／受版控 md %d 個／對照表 %d 個"
      % (sys.version.split()[0], markdown_it.__version__, yaml.__version__,
         len(md_files), len(table_files)))
print("必需關卡：%s ／ 建議：%s"
      % ("、".join(k for k in GATES if GATES[k]) or "（無）",
         "、".join(k for k in GATES if not GATES[k]) or "（無）"))

print()
print("── 編碼：受版控 .md 的內容是合法 UTF-8（%s）" % tag("encoding"))
# 定義域封閉到不能再封閉：一個檔案的位元組序列是不是合法 UTF-8，由 codec 判，沒有啟發式、
# 沒有「GitHub 算繪可能不一樣」的空間。合法 UTF-8 永遠解得開＝不可能有假陽性；
# 解不開的檔案 GitHub 也算繪不出正確文字＝不可能有假陰性。所以直接是關卡（issue #91 AC-1）。
#
# 為什麼開新的 key 而不是併進既有項：既有八項每一項都對應一條規則或一個結構斷言
# （`d2`→D2、`version`→V1／V4、`fence`／`table`／`link`→各自的形狀），而「檔案是 UTF-8」
# 是**讀得到內容**的前提，先於所有那些判定發生，不屬於其中任何一條的定義域。
# 併進去會讓那一項的失敗訊息同時代表兩種完全不同的問題，也讓它的假陽性紀錄不再可比。
#
# fail closed：解不開的檔案不從後面的關卡裡摘掉——read_text 以 errors="replace" 照樣
# 交出文字，壞位元組變 U+FFFD，行結構不變，d2／fence／version／table／link 照跑。
# 「讀不到就跳過」會讓一個壞編碼的檔案順帶豁免掉其餘所有檢查。
docs = {}
bad_encoding = []
for f in md_files:
    text, enc_err, nbytes = read_text(f)
    if enc_err is not None:
        bad_encoding.append(f)
        report("encoding", "%s 的內容不是合法 UTF-8" % f,
               decode_error_detail(f, nbytes, enc_err))
    lines = text.split("\n")
    env = {}
    try:
        tokens = MD.parse(text, env)
    except Exception as e:
        die("markdown-it 解析 %s 失敗：%s" % (f, e))
    docs[f] = {"lines": lines, "tokens": tokens, "env": env}
if bad_encoding:
    print("      —— 以上 %d 個檔仍以 U+FFFD 代替壞位元組往下檢查（fail closed），"
          "後面各項若對它報錯，先修編碼再看" % len(bad_encoding))
else:
    ok("%d 個受版控 .md 都解得開（utf-8，BOM 可有可無）" % len(md_files))

print()
print("── D2：入口區塊 ≤%d 行（%s）" % (D2_MAX_LINES, tag("d2")))
# 兩個已知檔案，入口區塊＝檔案裡**第一個** begin 標記到**其後第一個** end 標記，
# 只驗這一段的行數。判準是字面比對（strip 後整行等於標記），不看 markdown 結構、
# 不看 nesting level、不看是不是在 code block 裡——這是 issue #26 的使用者裁決（B）。
#
# 為什麼不用 AST：前兩版用 markdown-it 找「真正的標記」，一版誤擋清單項裡的示例，
# 修掉後下一版又漏擋「整個真區塊縮在清單項內」。D2 原文（WORKFLOW.md:122）沒有
# 規定區塊必須在頂層，任何結構判準都是在發明規則。字面比對的定義域最窄：
# 兩個已知檔案、兩個字面字串、第一次出現的位置。
#
# 這段之後的所有標記一律忽略：不計數、不報錯。專案自己的內容可以在區塊後面
# 用任何寫法示範標記（清單項、blockquote、<details>、code fence），都不受影響。
# 這段之**前**則相反：D2（1.0.0.0 起）明寫「區塊須為第一個標記組，其前不得有任何
# begin 或 end 行」，所以第一個 begin 之前出現 end 標記行是違規，❌ 而不是略過；
# 沒有 begin 卻有 end 也一樣（安裝器同判準拒絕：install.py 的 AC-5b）。

def entry_block(lines):
    """回傳 (stray_end, begin_line, end_line)，1-based；不存在的那一項是 None。
    stray_end＝第一個 begin 之前（沒有 begin 則全檔）最早的 end 標記行。"""
    begin = next((n + 1 for n, s in enumerate(lines)
                  if s.strip() == D2_BEGIN), None)
    head = lines if begin is None else lines[:begin - 1]
    stray = next((n + 1 for n, s in enumerate(head)
                  if s.strip() == D2_END), None)
    if begin is None:
        return stray, None, None
    end = next((n + 1 for n, s in enumerate(lines[begin:], start=begin)
                if s.strip() == D2_END), None)
    return stray, begin, end

for f in ENTRY_FILES:
    # 不在版控內＝這個專案沒裝這個入口檔。D2 不要求它存在（見檔頭）。
    if f not in files:
        print("  ⏭️ %s 不在版控內，略過" % f)
        continue
    stray, begin, end = entry_block(docs[f]["lines"])
    # 以下都是「檔案讀得到、內容形狀不對」——那是內容違規（exit 1），
    # 不是檢查器無法執行（exit 2）。exit 2 留給缺相依、不在 repo 內這類情況。
    #
    # 第一個 begin 之前有 end 標記行（含「只有 end 沒有 begin」）：D2 說區塊前不得有
    # 任何標記行。只報最早的一行；不替人清理——區塊外是專案的內容。
    if stray is not None:
        report("d2", "%s:%d 有落單的 devflow:end 在 begin 之前" % (f, stray),
               ["D2：區塊須為入口檔的第一個標記組，其前不得有任何 begin／end 行",
                "把那一行移到區塊後面（或刪掉）即可；區塊後的標記一律不驗"])
        continue
    # 一個標記都沒有＝這個檔案沒有 devflow 區塊，同上，不是違規。
    if begin is None:
        print("  ⏭️ %s 沒有 devflow 區塊，略過" % f)
        continue
    if end is None:
        report("d2", "%s 的 devflow 區塊沒有關閉（%s:%d 有 begin，其後沒有 end）"
               % (f, f, begin))
        continue
    n_lines = end - begin + 1
    if n_lines > D2_MAX_LINES:
        report("d2", "%s 的入口區塊 %d 行，超過 D2 的 %d 行"
               % (f, n_lines, D2_MAX_LINES),
               ["%s:%d-%d（含頭尾兩行標記）" % (f, begin, end)])
    else:
        ok("%s 的入口區塊 %d 行（%s:%d-%d）" % (f, n_lines, f, begin, end))

print()
print("── I1：head branch 名為 <N>-<slug>（%s）" % tag("i1"))
# 定義域封閉：一個字串比對一個 pattern。不打 API、不看 issue 是否存在。
# 檢查對象是 head branch，不是 base。同 repo 內 head 不會是 main；但 fork 的
# main 可以當 head 開 PR 進來，那時 GITHUB_HEAD_REF 就是 `main`，會被判 ❌——
# 這是預期行為：I1 要求一張 issue 對一條 `<N>-<slug>` 分支，fork 的 main 也不例外。
head_ref = os.environ.get("GITHUB_HEAD_REF", "").strip()
event_name = os.environ.get("GITHUB_EVENT_NAME", "")
if not head_ref:
    if event_name == "pull_request":
        # pull_request 事件一定有 GITHUB_HEAD_REF。沒有＝執行環境和假設不符，
        # 這時「略過」會讓關卡靜默失效，所以炸掉（exit 2）而不是放行。
        die("pull_request 事件卻取不到 GITHUB_HEAD_REF，I1 沒有檢查對象")
    print("  ⏭️ 非 pull_request 執行（event=%s），取不到 head branch，略過"
          % (event_name or "本機"))
elif BRANCH_RE.fullmatch(head_ref):
    ok("head branch `%s` 合 <N>-<slug>" % head_ref)
else:
    report("i1", "head branch `%s` 不合 I1 的 `<N>-<slug>`" % head_ref,
           ["`<N>` 是 issue 號（正整數，不以 0 開頭），接一個 `-`，再接非空的 slug",
            "例：`26-closed-domain-checks`",
            "slug 的字元集 I1 沒有規定，這裡不限"])

print()
print("── I5：%s 的 %s 投影與 %s 及安裝器讀到的值三方一致（%s）"
      % (I5_FILE, I5_PROJECTION, ".".join(I5_SOURCE_PATH), tag("i5")))
# 判定逐條照 docs/spec/install/spec.md AC-13，理由見檔頭「i5 為什麼可以是關卡」。
# 只 compose 不 construct（同 duplicate_version_key）：要抓的重複鍵、引號鍵、merge 鍵
# 都是 construct 會吞掉的東西。壞 YAML、多 document 是內容違規（❌），不是檢查器壞掉；
# 檔案不在版控內、安裝器載不進來才是 exit 2——那是 repo 佈局與本檔假設不符。

def node_desc(node):
    """log 用：節點種類、tag、（純量的）值、所在行。alias 解析後指向錨定節點，行號是錨的位置。"""
    line = node.start_mark.line + 1 if node.start_mark else "?"
    if isinstance(node, yaml.ScalarNode):
        return "%s tag=%s value=%r（第 %s 行）" % (type(node).__name__, node.tag, node.value, line)
    return "%s tag=%s（第 %s 行）" % (type(node).__name__, node.tag, line)


def is_plain_map(node):
    return isinstance(node, yaml.MappingNode) and node.tag == YAML_MAP


def mapping_entries(node, where):
    """AC-13 對一個路徑上 mapping 的鍵要求：每個 key 都是 !!str 的 ScalarNode，鍵名（.value）
    不重複——引號鍵與裸鍵、Unicode escape、!!str 顯式標籤、alias 指向的 key，compose 後
    .value 都是同一個 canonical 字串，所以一律抓得到；非字串 tag 的鍵（bool／int／null／
    merge）與複合鍵（key 是 Sequence／Mapping）直接是違規，不做 tag 正規化。
    回傳 (違規清單, {鍵名: 值節點})；重複鍵只保留第一個，反正結構已經 ❌。"""
    problems = []
    seen = {}
    values = {}
    for k, v in node.value:
        if not (isinstance(k, yaml.ScalarNode) and k.tag == YAML_STR):
            problems.append("%s 有非 !!str 純量的鍵：%s" % (where, node_desc(k)))
            continue
        if k.value in seen:
            problems.append("%s 的鍵 `%s` 重複：%s 與 %s"
                            % (where, k.value, node_desc(seen[k.value]), node_desc(k)))
            continue
        seen[k.value] = k
        values[k.value] = v
    return problems, values


def i5_structure(root):
    """結構要求 ＋ 取 S、P 節點。回傳 (違規清單, S 節點或 None, P 節點或 None)。
    路徑上的 mapping：根一定看；seats 的值、seats.implementer 的值存在才看。"""
    if not is_plain_map(root):
        return ["根不是 !!map 的 MappingNode：%s" % node_desc(root)], None, None
    problems, root_values = mapping_entries(root, "根")
    projection = root_values.get(I5_PROJECTION)
    source = None
    seats = root_values.get(I5_SOURCE_PATH[0])
    if seats is not None:
        if not is_plain_map(seats):
            problems.append("`%s` 的值不是 !!map 的 MappingNode：%s"
                            % (I5_SOURCE_PATH[0], node_desc(seats)))
        else:
            more, seats_values = mapping_entries(seats, "`%s`" % I5_SOURCE_PATH[0])
            problems += more
            implementer = seats_values.get(I5_SOURCE_PATH[1])
            if implementer is not None:
                where = "`%s`" % ".".join(I5_SOURCE_PATH[:2])
                if not is_plain_map(implementer):
                    problems.append("%s 的值不是 !!map 的 MappingNode：%s"
                                    % (where, node_desc(implementer)))
                else:
                    more, impl_values = mapping_entries(implementer, where)
                    problems += more
                    source = impl_values.get(I5_SOURCE_PATH[2])
    return problems, source, projection


def i5_scalar(node, name):
    """S／P 存在時須為 !!str 的 ScalarNode，取 .value；不存在＝None。
    yes／1／~ 之類被隱式解析成 bool／int／null 的都不是。回傳 (值或 None, 違規或 None)。"""
    if node is None:
        return None, None
    if not (isinstance(node, yaml.ScalarNode) and node.tag == YAML_STR):
        return None, "%s 不是 !!str 的 ScalarNode：%s" % (name, node_desc(node))
    return node.value, None


def foreign(what, fn):
    """執行外來程式碼（載入 installer、呼叫 read_implementer），任何逸出都轉成 exit 2。
    攔 BaseException 不是 Exception：SystemExit 繼承 BaseException，installer 在 import 期或
    read_implementer() 內一句 sys.exit(0) 若穿透到頂層，Python 就以 0 結束——整個檢查器判 success、
    三個關卡靜默失效（PR #76 第一輪）。KeyboardInterrupt 同理。die() 自己的 SystemExit(2) 是
    在 except 區塊裡才拋的，不會被同一個 except 攔回。只包這兩段，檢查器本身的 sys.exit 不受影響。"""
    try:
        return fn()
    except BaseException as e:
        die("%s：%s: %s" % (what, type(e).__name__, e))


def load_installer():
    """直接載入 devflow/install.py 取 L。AC-13：不得另寫一份 AC-7 判定——
    兩份判定就有第三個可漂移的東西。載不進來是佈局問題（exit 2），不是內容違規。"""
    if I5_INSTALLER not in files:
        die("找不到受版控的 %s，AC-13 的 L 沒有來源" % I5_INSTALLER)
    sys.dont_write_bytecode = True        # 別在 devflow/ 留 __pycache__
    spec = importlib.util.spec_from_file_location("devflow_install", I5_INSTALLER)
    module = importlib.util.module_from_spec(spec)
    # 語法錯、import 錯、import 期的 sys.exit 都算載不進來
    foreign("載入 %s 失敗" % I5_INSTALLER, lambda: spec.loader.exec_module(module))
    if not callable(getattr(module, "read_implementer", None)):
        die("%s 沒有 read_implementer()，AC-13 的 L 沒有來源" % I5_INSTALLER)
    return module


def show(value):
    return "（無）" if value is None else repr(value)


if I5_FILE not in files:
    die("找不到受版控的 %s，repo 佈局與檢查器假設不符" % I5_FILE)
# 從輸入到判定，每一步的例外分類（守則見檔首 _uncaught）：
#   讀檔 OSError ── exit 2：CI 剛 checkout 的受版控檔讀不到是環境問題，不是內容
#   yaml.YAMLError（ScannerError／ParserError／ComposerError／ReaderError）── ❌ exit 1：
#     這是 parser 在說「你的輸入不對」——語法錯、多 document、alias 未定義、非 UTF-8／
#     不可列印字元——都是使用者寫錯，屬「不是恰一個合法 document」的結構違規
#   RecursionError／MemoryError ── exit 2：Python 在說「我的資源不夠」，不是 parser 在說輸入錯。
#     深巢狀（約 500 層起）PyYAML 的遞迴 composer 會撞 recursionlimit；投影可能完全一致，
#     檢查器只是判不了。不提高 recursionlimit——那只是推高門檻，分類仍錯，且可能真的 segfault
#   節點樹走訪、比對、印出時任何未預期例外 ── exit 2（_uncaught 兜底；那是檢查器的 bug）
# bytes 交給 PyYAML：BOM／編碼由它依 YAML 規則判，和「真正讀這個檔案的 parser」一致。
# 安裝器那邊是 bytes 嚴格 UTF-8、BOM 不剝——兩邊看法不同時 P≠L，正是 i5 要報的。
try:
    with open(I5_FILE, "rb") as fh:
        i5_bytes = fh.read()
except OSError as e:
    die("讀不到 %s：%s" % (I5_FILE, e))
i5_problems = []
try:
    i5_root = yaml.compose(i5_bytes)
except yaml.YAMLError as e:
    i5_root = None
    i5_problems.append("不是恰一個合法的 YAML document：%s"
                       % str(e).strip().replace("\n", " "))
except (RecursionError, MemoryError) as e:
    die("解析 %s 時 %s：檔案巢狀太深或太大，超出檢查器（PyYAML 遞迴 composer）的能力；"
        "這不是投影不一致，i5 無法判定" % (I5_FILE, type(e).__name__))
if i5_root is None and not i5_problems:
    i5_problems.append("沒有任何 document（空檔或只有註解）")
yml_parse_problems = list(i5_problems)    # 解析層的違規；tables 那一節共用同一份節點樹與訊息
s_val = p_val = None
if not i5_problems:
    i5_problems, s_node, p_node = i5_structure(i5_root)
    s_val, bad = i5_scalar(s_node, "S＝`%s` 的值" % ".".join(I5_SOURCE_PATH))
    if bad:
        i5_problems.append(bad)
    p_val, bad = i5_scalar(p_node, "P＝`%s` 的值" % I5_PROJECTION)
    if bad:
        i5_problems.append(bad)
installer = load_installer()
# read_implementer() 依 AC-7 承諾永不報錯；真的逸出（含 sys.exit）是安裝器壞了＝檢查器無法執行，
# 不是 devflow.yml 違規，所以是 exit 2 不是 exit 1，也不能讓它以自己的 exit code 收場。
l_val = foreign("%s 的 read_implementer() 逸出" % I5_INSTALLER,
                lambda: installer.read_implementer(Path(".")))
# 契約：回 None 或**恰好是 str**。用 type() is 不用 isinstance：str 子類可以覆寫 __eq__
# （`class PretendEqual(str): __eq__ = lambda *_: True`），isinstance 放行後 s == p == l 恆真、
# 關卡失效（PR #76 第二輪）。不正規化成 str(l)：那會把「回傳型別不合契約」誤報成「投影不一致」。
# 這是檢查器的輸入不合契約＝exit 2，不是 devflow.yml 違規。
if l_val is not None and type(l_val) is not str:
    die("%s 的 read_implementer() 回傳 %r（型別 %s），契約是 None 或恰好 str"
        % (I5_INSTALLER, l_val, type(l_val).__name__))
if i5_problems:
    report("i5", "%s 不符 AC-13 的結構要求（%d 項）" % (I5_FILE, len(i5_problems)),
           i5_problems
           + ["AC-13：恰一個 document；根、`seats` 的值、`seats.implementer` 的值都是 !!map；"
              "這三個 mapping 的每個 key 都是 !!str 純量且鍵名不重複；S、P 存在時是 !!str 純量"])
elif s_val is None and p_val is None and l_val is None:
    ok("%s 沒有 `%s`、沒有 `%s`、安裝器也讀不到值：三者皆無，本 repo 未用此機制"
       % (I5_FILE, ".".join(I5_SOURCE_PATH), I5_PROJECTION))
elif s_val == p_val == l_val:
    ok("%s：`%s` ＝ `%s` ＝ 安裝器讀到的值 ＝ %r"
       % (I5_FILE, ".".join(I5_SOURCE_PATH), I5_PROJECTION, s_val))
else:
    report("i5", "%s 的 `%s` 投影與來源不一致（I5／AC-13）" % (I5_FILE, I5_PROJECTION),
           ["S＝`%s`：%s" % (".".join(I5_SOURCE_PATH), show(s_val)),
            "P＝`%s`：%s" % (I5_PROJECTION, show(p_val)),
            "L＝安裝器 %s read_implementer() 讀到：%s" % (I5_INSTALLER, show(l_val)),
            "通過 ⇔ 三者皆無，或三者皆為字串且逐字相等。投影要寫成安裝器讀得到的裸字面值"
            "（不是 alias、引號、顯式標籤、多行），並與來源逐字相同"])

print()
print("── V1：frontmatter version 為四碼 a.b.c.d（%s）" % tag("version"))
VER_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+")
SPEC_RE = re.compile(r"docs/spec/[^/]+/spec\.md")
# 掃描範圍：規則本體與規格文檔。注意這不等於 V4 的適用對象——
# V4 還包含 kit release tag v<a.b.c.d>，本檢查器完全不讀 tag（見檔頭）。
# V4 明寫「第三方版本、工具版本、issue 編號保持原值」，所以別的 .md 就算有
# frontmatter version 也一律不管——那是它自己的版號，不是四碼制的。
# devflow/templates/spec.md 是「模板」不是「規格文檔」，同樣不在適用對象內：
# 它的 version 是給人複製的佔位值，拿四碼制去擋它是把規則套到範圍外。
# 引的規則是 `V1`（四碼）＋`V4`（適用對象），兩條都住第 3 節，依 `ST1` 在
# 現行 stage 1 生效。**不引 `S1`**：它住第 2 節，依 `ST2` 要 stage 2 才生效，
# 拿休眠條文當關卡的依據正是檔頭「停損理由三」記的那個錯。`S1` 另外規定了
# 規格的三個標題與 AC 形狀，那些本檢查器一概不驗。
version_targets = [f for f in md_files
                   if f == RULES_FILE or SPEC_RE.fullmatch(f)]
if not version_targets:
    die("找不到任何 V4 適用對象，repo 佈局與檢查器假設不符")
for f in version_targets:
    state, fm = frontmatter(docs[f]["lines"])
    if state != "ok":
        report("version", "%s 的 frontmatter %s（V1／V4）"
               % (f, "沒有關閉" if state == "unclosed" else "不存在"))
        continue
    # 取值一律用原生 safe_load，才會和真正讀這個檔案的 parser 一致
    # （merge key、anchor／alias、各種 scalar 樣式都由它處理）。
    try:
        data = yaml.safe_load(fm)
    except yaml.YAMLError as e:
        report("version", "%s 的 frontmatter 不是合法 YAML：%s"
               % (f, str(e).strip().replace("\n", " ")))
        continue
    # 重複 key 的偵測獨立做：只看 mapping node 的 key 清單，不 construct，
    # 才不會把合法的 merge key（<<: *d）連帶弄成非法。
    if duplicate_version_key(fm):
        report("version", "%s 的 frontmatter 有多個 version key"
                          "（YAML 實際生效的是最後一個）" % f)
    if not isinstance(data, dict) or "version" not in data:
        report("version", "%s 的 frontmatter 缺 version（V1／V4）" % f)
        continue
    value = data["version"]
    if not isinstance(value, str):
        report("version", "%s version=%r 不是字串（四碼要寫成 a.b.c.d 或加引號）"
               % (f, value))
    elif VER_RE.fullmatch(value):
        ok("%s version=%s" % (f, value))
    else:
        # 用 %r：值可能含換行（version: | 的區塊純量），裸印會把輸出撐破，
        # 也看不出來問題正是那個看不見的換行。
        report("version", "%s version=%r 不是四碼 a.b.c.d（V1）" % (f, value))

print()
print("── 規則 ID 無重複定義（%s，%s）" % (RULES_FILE, tag("dupid")))
rd = docs[RULES_FILE]
defined = {}
for rid, line in rule_definitions(rd["tokens"], rd["lines"]):
    defined.setdefault(rid, []).append(line)
dups = {k: v for k, v in defined.items() if len(v) > 1}
if dups:
    for rid in sorted(dups):
        report("dupid", "規則 ID `%s` 被定義 %d 次" % (rid, len(dups[rid])),
               ["%s:%s:%s" % (RULES_FILE, n, rd["lines"][n - 1].strip())
                for n in dups[rid] if n])
elif not defined:
    report("dupid", "在 %s 找不到任何規則定義，檢查器的假設可能已與檔案脫節"
           % RULES_FILE)
else:
    ok("%d 條規則 ID，無重複定義" % len(defined))

print()
print("── 規則 ID 無懸空引用（md 內的 `ID` 都要有定義，%s）" % tag("refs"))
prefixes = set(BASELINE_PREFIXES)
for rid in defined:
    prefixes.add(ID_RE.fullmatch(rid).group(1))
refs = {}
nref = 0
for f in md_files:
    for content, line in code_spans(docs[f]["tokens"], docs[f]["lines"]):
        m = ID_RE.fullmatch(content)
        if not m or m.group(1) not in prefixes:
            continue
        nref += 1
        refs.setdefault(content, []).append((f, line))
dangling = sorted(r for r in refs if r not in defined)
if dangling:
    for rid in dangling:
        report("refs", "引用了未定義的規則 ID `%s`" % rid,
               ["%s:%s:%s" % (f, n, docs[f]["lines"][n - 1].strip() if n else "?")
                for f, n in refs[rid]])
else:
    ok("%d 處引用、%d 個相異 ID（含 %s 的定義行本身），全部有定義"
       % (nref, len(refs), RULES_FILE))

print()
print("── markdown 的 fenced code block 都有關閉（%s）" % tag("fence"))
bad_fence = [(f, unclosed_fence(docs[f]["tokens"], docs[f]["lines"]))
             for f in sorted(docs)]
bad_fence = [(f, n) for f, n in bad_fence if n]
if bad_fence:
    for f, n in bad_fence:
        report("fence", "%s:%d 的 fenced code block 沒有關閉" % (f, n))
else:
    ok("%d 個 md 檔的 code fence 都成對" % len(md_files))

print()
print("── 對照表集合：%s 指名的對照表都受版控（%s）" % (I5_FILE, tag("tables")))
# 對應規則見上面 TABLES_* 常數的註解；為什麼是獨立關卡見檔頭「tables 為什麼可以是關卡」。
# 節點樹沿用 i5 那一節 compose 出來的 i5_root（同一份 bytes、同一個 parser，不解析第二次）。
# devflow.yml 不在版控內、讀不到、巢狀太深：i5 那一節已經 die()（exit 2），走不到這裡——
# 那是 repo 佈局或環境與本檔假設不符，分類沿用 i5。
#
# 推導不出來一律 ❌（exit 1），不 die()、不跳過：
#   * 跳過正是本項要消除的失敗模式——把 devflow.yml 寫壞的同一個 PR 再刪一張表，會整個放行。
#   * 不 die()：壞 YAML、缺鍵、型別不符是**內容違規**，不是檢查器無法執行（檔首的 exit code 守則；
#     i5 對同一份檔案的壞 YAML 也判 ❌）。die() 還會中斷整輪，後面各關卡的結果都看不到。
#   * 不靠 i5 代擋：GATES 各自獨立，i5 被降為建議時本項仍要擋，所以自己報。
#     同一份壞 YAML 因此 i5、tables 各一個 ❌——兩項都依賴它，各自如實回報。
# 只對本項要讀的鍵負責（tables_get）：同名鍵重複＝推導有歧義 → ❌；同一個 mapping 裡
# 別的鍵有什麼毛病不是本項的事（根、seats、seats.implementer 的鍵由 i5 依 AC-13 管）。

YAML_MERGE = "tag:yaml.org,2002:merge"


def tables_merge_sources(parent, where):
    """parent 裡 `<<` 帶進來的 mapping，依 YAML merge 語意由先到後。
    回傳 (mapping 清單, 違規或 None)。

    AC-13 只禁止**它明列的三個 mapping**（根、`seats`、`seats.implementer`）出現
    merge key；`seats.reviewer`／`seats.coordinator` 不在該範圍，既有 `i5` 對它們
    的 merge key 實際是通過的（審查者 PR #88 第二輪實測）。本項若一律不展開，
    就等於自行替 required gate 補上規格沒有的禁令——那是擴張規格，不是沿用。

    仍不改用 `safe_load`：重複鍵、非字串鍵的檢查要靠 compose 的節點樹。

    **同一個 mapping 只允許一個 `<<`**：PyYAML 對兩個 `<<` 是後者覆蓋先者，
    與本函式「先出現者優先」相反（審查者 PR #88 第四輪第 11 案：`safe_load`
    得 `nosuchtool`、checker 得 `codex`）。語意分歧的輸入一律擋，不挑一邊。

    `<<` 的值不是 mapping、也不是「全是 mapping 的 sequence」時 fail closed：
    那是 PyYAML `safe_load` 自己會拋 ConstructorError 的輸入。"""
    out = []
    seen_merge = False
    for k, v in parent.value:
        if not (isinstance(k, yaml.ScalarNode) and k.tag == YAML_MERGE):
            continue
        if seen_merge:
            return None, ("%s 有多個 `<<`：PyYAML 是後者覆蓋先者，本檢查是先者"
                          "優先，語意分歧" % where)
        seen_merge = True
        # `<<: *a` 是單一 mapping；`<<: [*a, *b]` 是序列，前者優先。
        items = v.value if isinstance(v, yaml.SequenceNode) else [v]
        for it in items:
            if not (isinstance(it, yaml.MappingNode) and it.tag == YAML_MAP):
                return None, ("%s 的 `<<` 來源不是 !!map 的 MappingNode：%s"
                              % (where, node_desc(it)))
            out.append(it)
    return out, None


def tables_validate_merge(parent, where, _seen=None):
    """遍歷 parent 可達的整個 merge graph，驗證結構。回傳違規或 None。

    **與值查找拆開**（審查者 PR #88 第四輪）：查找會在直接鍵命中或第一個來源
    有值時短路，壞掉的深層來源就永遠驗不到。結構是有限且可遍歷的，先整個驗完
    再查值。"""
    seen = _seen if _seen is not None else set()
    if id(parent) in seen:
        return None
    seen.add(id(parent))
    sources, bad = tables_merge_sources(parent, where)
    if bad:
        return bad
    for src in sources:
        bad = tables_validate_merge(src, where, seen)
        if bad:
            return bad
    return None


def tables_get(parent, key, where, _seen=None):
    """parent（已確認是 !!map）裡 !!str 鍵 key 的值節點。回傳 (節點或 None, 違規或 None)。
    鍵以 compose 後的 .value 比對（引號鍵、alias 指向的鍵一視同仁，同 mapping_entries）。
    出現不只一次是歧義：construct 是 last-wins，別的 parser 可能 first-wins 或直接報錯。

    直接鍵找不到時，依 YAML merge 語意往 `<<` 的來源找（直接鍵優先於 merge 來源，
    單一 `<<` 的 sequence 內先出現者優先）。呼叫端須先跑 tables_validate_merge。"""
    hits = [v for k, v in parent.value
            if isinstance(k, yaml.ScalarNode) and k.tag == YAML_STR and k.value == key]
    if len(hits) > 1:
        return None, "%s 的鍵 `%s` 出現 %d 次，推導有歧義" % (where, key, len(hits))
    if _seen is None:               # 進入點：先驗整個 merge graph 的結構
        bad = tables_validate_merge(parent, where)
        if bad:
            return None, bad
    if hits:
        return hits[0], None
    sources, bad = tables_merge_sources(parent, where)
    if bad:
        return None, bad
    seen = _seen if _seen is not None else set()
    if id(parent) in seen:          # anchor 互指造成的環，停住
        return None, None
    seen.add(id(parent))
    for src in sources:
        node, bad = tables_get(src, key, where, seen)
        if bad:
            return None, bad
        if node is not None:
            return node, None
    return None, None


tables_problems = []
tables_required = []          # [(來源鍵, 值, 目錄)]
if i5_root is None:
    tables_problems += yml_parse_problems
elif not is_plain_map(i5_root):
    tables_problems.append("根不是 !!map 的 MappingNode：%s" % node_desc(i5_root))
else:
    key, directory = TABLES_FORGE
    node, bad = tables_get(i5_root, key, "根")
    if not bad and node is None:
        bad = "缺 `%s`（第 0 節的自變數）" % key
    if not bad:
        value, bad = i5_scalar(node, "`%s` 的值" % key)
    if bad:
        tables_problems.append(bad)
    else:
        tables_required.append((key, value, directory))

    seats, bad = tables_get(i5_root, TABLES_SEATS, "根")
    if not bad and seats is None:
        bad = "缺 `%s`（第 0 節的自變數）" % TABLES_SEATS
    if not bad and not is_plain_map(seats):
        bad = "`%s` 的值不是 !!map 的 MappingNode：%s" % (TABLES_SEATS, node_desc(seats))
    if bad:
        tables_problems.append(bad)
    else:
        for seat, directory in TABLES_SEAT_DIRS:
            where = "`%s.%s`" % (TABLES_SEATS, seat)
            key = "%s.%s.%s" % (TABLES_SEATS, seat, TABLES_FILLER)
            node, bad = tables_get(seats, seat, "`%s`" % TABLES_SEATS)
            if not bad and node is None:
                if seat == TABLES_OPTIONAL_SEAT:
                    continue                      # 第 0 節：省略＝human，不要求
                bad = ("缺 %s（第 0 節只定義 `%s` 省略＝%s，這個職位沒有省略的預設）"
                       % (where, TABLES_OPTIONAL_SEAT, TABLES_HUMAN))
            if not bad and not is_plain_map(node):
                bad = "%s 的值不是 !!map 的 MappingNode：%s" % (where, node_desc(node))
            if not bad:
                node, bad = tables_get(node, TABLES_FILLER, where)
            if not bad and node is None:
                bad = "%s 缺 `%s`" % (where, TABLES_FILLER)
            if not bad:
                value, bad = i5_scalar(node, "`%s` 的值" % key)
            if bad:
                tables_problems.append(bad)
            elif value != TABLES_HUMAN:
                tables_required.append((key, value, directory))

if tables_problems:
    report("tables", "%s 推導不出必需的對照表（%d 項）" % (I5_FILE, len(tables_problems)),
           tables_problems
           + ["推導需要：根是 !!map；`forge` 是 !!str 純量；`seats` 是 !!map；"
              "`seats.implementer`、`seats.reviewer` 是含 !!str `filler` 的 !!map；"
              "`seats.coordinator` 同上或整個省略（＝human）；以上各鍵不重複"])
table_file_set = set(table_files)
tables_missing = []
for key, value, directory in tables_required:
    path = "%s%s.md" % (directory, value)
    if path in table_file_set:
        continue
    have = sorted(f[len(directory):-len(".md")] for f in table_files if f.startswith(directory))
    elsewhere = [d for d in TABLE_DIRS
                 if d != directory and "%s%s.md" % (d, value) in table_file_set]
    tables_missing.append(
        "`%s` ＝ %r → %s 不在版控內（%s 現有：%s；%s）"
        % (key, value, path, directory, "、".join(have) or "（無）",
           "%s 有同名檔，但這個鍵要的是 %s 的表" % ("、".join(elsewhere), directory)
           if elsewhere else
           "%s 都沒有 %s.md：設定指向沒有對照表的值，或表被刪了"
           % ("、".join(TABLE_DIRS), value)))
if tables_missing:
    report("tables", "%s 指名的對照表不在版控內（%d 項）" % (I5_FILE, len(tables_missing)),
           tables_missing)
if not tables_problems and not tables_missing:
    ok("%s 指名的 %d 張對照表都受版控：%s（`human` 與省略的 coordinator 不要求，approver 不讀）"
       % (I5_FILE, len(tables_required),
          "、".join("`%s`→%s%s.md" % (k, d, v) for k, v, d in tables_required)))

print()
print("── 對照表的形狀（%s）" % tag("table"))
# 定義域：TABLE_DIRS 的直屬 .md（見上面 table_files）。每條斷言都是
# 「檢查器沒看懂這個檔案」的絆線，所以 fail closed——沒看懂就報，不靜默放行。
#
# 判準逐條對著 R9 的分節條文（issue #80 AC-1）：
#   (1) 每張表的表頭要含 `面向`／`值`／`狀態`，且「狀態」恰一欄（多一欄就判不出
#       哪欄是狀態，R9 的三值無從檢查；這是狀態欄檢查的前提，不是額外的規定）。
#   (2) 表數不限。R9 說「對照表得分為通用節與本機節」，但**沒有規定一個節內
#       可以有幾張表**——現行分布是 forges／coders 各 2 張、orchestrators 各 1 張，
#       「剛好一張」「剛好兩張」都是在發明規則。條文未規定的不假設（issue #80 已提報）。
#   (3) 分節：R9 的「得分為」是「可以」，而且明文有「未分節的表」的判準，所以
#       整檔不分節**不是**違規。但同一條也寫「分節時先歸節、後判狀態」——
#       檔案一旦出現節標題，節外的表就沒有歸節可言。所以只在**已分節的檔案**裡
#       要求每張表落在某一節下；未分節的檔案不要求。
#   (4) fail closed：對照表檔至少要有一張合格的表。整檔沒有表、或每張表都不合格，
#       都是「這個檔案的對照資料不在任何格式契約之下」，要擋。
#   (5) 資料列的狀態格 strip 後不得為空（issue #90 缺口 3）。markdown-it 會把短列補成
#       表頭的欄數，補出來的格是空字串（本地以 markdown-it-py 4.0.0 實測）；只有空白的格
#       parser 也 strip 成空字串，兩者在 AST 上分不出來，讀者看到的也同樣是空格，所以一併擋。
#       「格數 ≤ 狀態欄索引」那條留著：parser 補格是它現在的行為，不是這裡能依賴的契約。
#   (6) raw HTML 的 `<table` 出現在對照表檔內一律擋（issue #90 缺口 2）。對照表的格式契約
#       是 markdown 表格；raw HTML 表格繞過上面每一條狀態欄檢查，在 GitHub 上卻照常渲染，
#       讀者看到的對照資料就不在任何契約之下。不解析 HTML 表的內容，見 raw_html_tables()。
status_tables = {}          # f -> [(table, 狀態欄索引), ...]，供 R9 用
for f in table_files:
    d = docs[f]
    tables = tables_of(d["tokens"], d["lines"])
    sections = r9_sections(d["tokens"])
    usable = []
    problems = []
    for t in tables:
        where = "%s:%s" % (f, t["header_line"] or t["line"])
        missing = [h for h in TABLE_HEADER if h not in t["header"]]
        if missing:
            problems.append("%s 表頭缺 %s（實際表頭：%s）"
                            % (where, "／".join(missing), " | ".join(t["header"])))
            continue
        if t["header"].count(STATUS_COL) != 1:
            problems.append("%s 有 %d 個「%s」欄，無法判定哪一欄才是狀態"
                            % (where, t["header"].count(STATUS_COL), STATUS_COL))
            continue
        if sections and t["section"] is None:
            problems.append("%s 這張表不在「%s」任一節之下（本檔已分節：%s）"
                            % (where, "」「".join(TABLE_SECTIONS),
                               "、".join(sections)))
            continue
        col = t["header"].index(STATUS_COL)
        short = [r for r in t["body"]
                 if len(r["cells"]) <= col or not r["cells"][col].strip()]
        if short:
            problems.append("%s 有 %d 列的狀態格為空（缺格或只有空白；最早在第 %s 行）"
                            % (where, len(short), short[0]["line"]))
            continue
        usable.append((t, col))
    for n in raw_html_tables(d["tokens"], d["lines"]):
        problems.append("%s:%s 有 raw HTML 的 <table>：對照表只能用 markdown 表格，"
                        "HTML 表格不受狀態欄檢查" % (f, n))
    status_tables[f] = usable
    if not usable:
        problems.append("整個檔案沒有一張合格的對照表（至少要有一張：表頭含 %s、"
                        "「%s」欄恰一個、有資料列；已分節時還要落在節內）"
                        % ("／".join(TABLE_HEADER), STATUS_COL))
    if problems:
        report("table", "%s 的對照表形狀不合 R9（%d 項）" % (f, len(problems)),
               problems)
    else:
        ok("%s：%d 張合格的表、%d 個資料列（%s）"
           % (f, len(usable), sum(len(t["body"]) for t, _ in usable),
              "／".join(sorted({t["section"] for t, _ in usable}))
              if sections else "整檔未分節，R9 允許"))

print()
print("── markdown 相對連結指向存在的路徑（%s）" % tag("link"))
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
# 存在性的 oracle 是 **git 的檔案清單**，不是 runner 的檔案系統。
# `os.path.exists` 會跟隨 symlink，使判定取決於 runner 上有沒有那個
# 目標：tracked 的 `outside-link -> /etc/passwd` 會放行（假陰性），
# 指向不存在目標的同型 symlink 會被擋（假陽性）——兩者在 git 裡都是
# mode 120000 的 repo entry，判定卻相反（審查者 PR #81 第五輪反例）。
# 這也是 #22 已知的 `.git/config` 漏放的同一個根因。
tracked_set = set(files)
# repo 根一定存在，但它不是任何 tracked path 的前綴推導結果
# （`a/b.md` 只推得出 `a`）——`[x](.)`、`[x](./)`、`[x](devflow/..)`
# 都 normpath 成 `.`，不預置就會誤擋（審查者 PR #81 第六輪反例）。
tracked_dirs = {"."}
for _t in files:
    _p = _t
    while "/" in _p:
        _p = _p.rsplit("/", 1)[0]
        tracked_dirs.add(_p)

def in_repo(p):
    """p 是不是 git 認得的 repo entry（檔案或目錄）。"""
    return p in tracked_set or p in tracked_dirs
broken = []
nlink = 0
for f in md_files:
    d = docs[f]
    base = os.path.dirname(f)
    for target, line in link_targets(d["tokens"], d["env"], d["lines"]):
        # fragment 與有 scheme 的 URL 不是 repo 路徑；`//host/path` 是
        # network-path URL（無 scheme 但指向外部主機），也不是。
        # 但單一 `/` 開頭的 target 在 GitHub 上是 **repo-root 相對連結**
        # （`/devflow/WORKFLOW.md` 指向 repo 根），要檢查（審查者 PR #81
        # 第三輪：一律排除會漏放）。
        if (target.startswith("#") or target.startswith("//")
                or SCHEME.match(target)):
            continue
        # URL 的順序是 path?query#fragment；兩者都不是路徑的一部分。
        # 先切再 percent-decode，且**分類（repo-root vs 相對）在 decode 前
        # 就定案**——decode 後才看首斜線的話，`/%2Fetc/passwd` 會變成
        # `//etc/passwd`、去首斜線成 runner 的絕對路徑 `/etc/passwd`
        # 而漏放（審查者 PR #81 第四輪反例）。
        raw = target.split("#", 1)[0].split("?", 1)[0]
        from_repo_root = raw.startswith("/")
        path = unquote(raw[1:] if from_repo_root else raw)
        if not path:
            continue
        nlink += 1
        # decode 後仍可能生出前導斜線（`%2F…`）：那不是 repo 路徑，
        # 交給下面的 repo 邊界判定擋掉，不再剝一次。
        full = path if from_repo_root else os.path.join(base, path)
        full = os.path.normpath(full)
        # 比對的是**路徑段**，不是字首：`..probe.md` 是一個合法的檔名，
        # 用 startswith("..") 會把它判成逃出 repo（本機實測 exit 1）。
        # 絕對路徑一律逃出：percent-decode 後可能生出前導斜線
        # （`/%2Fetc/passwd` → `/etc/passwd`），那是 runner 的檔案系統，
        # 不是 repo；只擋 `..` 會讓它因 os.path.exists 為真而漏放
        # （審查者 PR #81 第四輪反例）。
        if os.path.isabs(full) or full == ".." or full.startswith("../"):
            broken.append("%s:%s -> %s（逃出 repo 之外）" % (f, line, target))
        elif not in_repo(full):
            broken.append("%s:%s -> %s" % (f, line, target))
if broken:
    report("link", "有相對連結指向不存在或 repo 之外的路徑", broken)
else:
    ok("%d 條相對連結（含 reference 定義、圖片）都指得到" % nlink)

print()
print("── R9：對照表狀態欄取三值之一（%s）" % tag("r9"))
# 對照表的狀態欄還沒依 R9 遷移到三值，而 devflow/ 不在本工單的 write scope 內：
# 現在設成關卡會擋死每個 PR。遷移完成後把 GATES["r9"] 改成 True，但那還有
# 前置：`✅` 的驗證方式與受測環境該記成什麼，尚未定案（issue #13、#22）。
# 判讀對象是上面那一節認定為「合格」的表（status_tables），所以 R9 的三值
# 只在已經有格式契約的表上檢查——形狀不合的那些，形狀那一節已經擋了。
def status_ok(cell):
    for tok in R9_STATUSES:
        if cell == tok:
            return True
        if cell.startswith(tok) and cell[len(tok)] in R9_SEPS:
            return True
    return False

r9_clean = True
for f in table_files:
    usable = status_tables.get(f) or []
    if not usable:
        r9_clean = False
        report("r9", "%s 找不到可判讀狀態欄的表（形狀那一節已報）" % f)
        continue
    body_lines = set()
    for t, col in usable:
        body_lines |= {r["line"] for r in t["body"]} | {t["header_line"]}
        bad = [r for r in t["body"] if not status_ok(r["cells"][col])]
        if bad:
            r9_clean = False
            report("r9", "%s:%s 有 %d 列的狀態欄不是 %s"
                   % (f, t["header_line"], len(bad), "／".join(R9_STATUSES)),
                   ["%s:%s 狀態欄=「%s」" % (f, r["line"], r["cells"][col])
                    for r in bad])
    # 表格以外的敘述句也會宣告舊的二值制度，一併報。
    prose = ["%s:%d:%s" % (f, n + 1, line.strip())
             for n, line in enumerate(docs[f]["lines"])
             if (n + 1) not in body_lines and any(o in line for o in OLD_TOKENS)]
    if prose:
        r9_clean = False
        report("r9", "%s 的敘述句仍用二值用語" % f, prose)
if r9_clean:
    ok("對照表狀態欄全部合 R9"
       + ("" if GATES["r9"] else
          " —— 可把 GATES[\"r9\"] 改成 True 升為必需關卡（前提見 README 第三出口的判定方式）"))

print()
if errors:
    print("===== 必需關卡失敗（%d 項）=====" % len(errors))
    for m in errors:
        print("  ❌ %s" % m)
    if advisories:
        print("（另有 %d 項建議，不影響本次結果）" % len(advisories))
    sys.exit(1)
if not [k for k in GATES if GATES[k]]:
    print("===== 沒有任何必需關卡：本次檢查不擋任何 PR =====")
    print("（%d 項建議；要讓某一項擋人，把 GATES 裡它的 False 改成 True）"
          % len(advisories))
else:
    print("===== 必需關卡全部通過 =====")
    if advisories:
        print("（另有 %d 項建議，未達升關卡前提，本輪不阻擋）" % len(advisories))
