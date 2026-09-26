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
# 十六項裡十二項是 True（`encoding`、`d2`、`i1`、`i5`、`version`、`fence`、`tables`、`table`、
# `link`、`r9`、`dupid`、`v7`），四項是 False（`refs`、`seatoblig`、`orphan`、`r2`）——分界不是
# 「哪一項比較重要」，而是**定義域封不封閉**，見下面各節。
# 四項建議停在建議的理由各不相同：`refs` 是定義域封不住（見下面「擋不住什麼」）；
# `seatoblig`／`orphan` 的定義域封閉，只是正反測試還沒補（issue #213；升關卡的前提同樣是
# 上面那條 README 的判定方式）；`r2` 的定義域也封閉，但它**依裁決永遠不升關卡**
# （issue #218 的使用者裁決，2026-09-25：條文寫明同廠 fallback 宜用不同模型、不強制，
# 「檢查器維持建議項不升關卡」）——所以它不走 report()，輸出改用 ℹ️（提示）／⚠️（警告）
# 兩級，DEVFLOW_GATE_R2=1 也不再能打開它（見下面 GATES_NO_UPGRADE）。
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
#                 `link` 相對連結（含 raw HTML 的 `<a href>`／`<img src>`）指向 repo 內存在的路徑、
#                 `r9` 對照表的狀態欄取 `R9` 三值之一（`✅ 可用`／`📝 已宣稱`／`⬜ 未測`；
#                 三值之後可接分隔符與補充，見 R9_SEPS）、
#                 `dupid` 規則本體沒有把同一個規則 ID 定義兩次（定義＝節前綴判準，
#                 見下面「dupid 為什麼可以是關卡」）、
#                 `v7` PR 動到 `devflow/**`（`devflow/VERSION` 自身除外）時 `devflow/VERSION`
#                 有進位（merge-base 與 HEAD 兩份四碼嚴格遞增；只判有沒有進、不判位數）。
# 就這十二項（`version`、`fence`、`table`、`link` 是 issue #80 開的，理由見下面「後四項為什麼現在
# 可以是關卡」；`tables` 是 issue #87 開的，見「tables 為什麼可以是關卡」；`encoding` 是
# issue #91 開的——它原本不是關卡而是 exit 2，理由見下面「exit code 的分類守則」與該項自己的註解；
# `r9` 是 issue #94 開的，見「r9 為什麼可以是關卡」；`dupid` 是 issue #96 開的，
# 見「dupid 為什麼可以是關卡」；`v7` 是 issue #150 開的，見「v7 為什麼可以是關卡」）。
# 不擋（exit 0，只把發現印在 log）：`refs`（issue #96 逐項評估過三個收斂方向，沒有一個
# 封得住定義域，見下面「擋不住什麼」的 refs 那條）、
# `seatoblig` 職位檔的 `## 規則義務` 段與該檔其餘段的規則 ID 引用雙向一致、
# `orphan` 規則本體定義的規則 ID 至少有一個職位檔認領（`devflow/seats/README.md`
# 明文豁免的除外）——後兩項是 issue #213 開的，定義域封閉（見各自那一節的註解），
# 停在建議是因為正反測試未補，不是因為判準收不住。
# 另有 `r2`（issue #218 開的）：devflow.yml 裡審查的兩個宣告位置——主 pin `seats.reviewer`
# 與選填的 `seats.reviewer.fallback`——各自與實作位比一次，同廠時比兩邊的 `model`：不同就
# 每次執行都印一行 ℹ️、相同印 ⚠️（`R2` 建議同廠時換一個模型，同模型只差 context）。
# 兩處獨立判定、各出一則。它依裁決是建議且不升關卡，兩級輸出都不進 errors 也不進 advisories，
# 不影響 exit code；未宣告 fallback（它是選填）或該位異廠都是「不適用」，印 ✅。
# 首版只判 fallback，於是協調者直接以同廠同模型的主 pin 審查時（PR #216 第一輪）一聲不吭；
# 射程於 issue #221 補上主 pin，條文（`R2`）同步寫明「同廠」看的是當次實際擔任審查的那一位。
#
# 「GATES 是 True」只讓這個 check 自己變紅，**不等於它是 branch protection 的
# required status check**——後者是 repo 設定，要另外設，前提見下面「升 required 的前提」。
# 但「平台沒有機械阻擋」不等於「可以合併」：`M1` 要求測試綠，紅叉的 PR 依治理流程
# 不應合併。B 關卡的意思只是還沒有機器替人擋，不是放行。
#
# ── 那七項為什麼曾經全部停在 advisory（PR #20 六輪的停損）──────────────────
# 【歷史紀錄，寫於 stage 0。其中四項已於 issue #80 升為關卡、`r9` 已於 issue #94 升為關卡、
#   `dupid` 已於 issue #96 升為關卡，各見下面專節；只剩 `refs` 停在 advisory，
#   理由一、二對它仍然成立。】
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
#       行號：issue #100 起改由 parser 記下的原文位移算，修掉 #92 反推法少算行的四種寫法
#               （與 `link` 共用同一套取出機制，見「link 的 raw HTML 連結」）。
#
#   * `link`（相對連結有效性）
#       定義域：受版控 .md 裡 AST 看得到的相對連結（行內連結、圖片、reference 定義）；
#               issue #100 起加上 raw HTML 裡承載連結的屬性（HTML_LINK_ATTRS：`<a href>`、
#               `<img src>`；issue #102 起加上 `<img srcset>`、`<source srcset>`，切成
#               候選 URL 逐一驗）。有 scheme 的、純 fragment 的不驗。
#       假陽性：#22 缺口 9（連結帶 query）已修（切 fragment 也切 query）；另修一個本地
#               找到的——`..probe.md` 這種合法檔名被 `startswith("..")` 判成逃出 repo，
#               改成比對路徑段。本地以反例複驗四種 query／fragment 組合皆不報。
#       #22 缺口 6（指向 `.git/config` 之類受版控外但 runner 上存在的路徑）：本節寫成時
#               記為「仍擋不住」，同一單後來由 PR #81 第五輪修掉——存在性的 oracle 換成
#               `git ls-files`，不再問 runner 的檔案系統（見 link 那一節的註解）。
#       #22 缺口 5（raw HTML 的連結完全不受檢查）：issue #100 修掉。定義域、取出方式、
#               仍擋不住什麼，見下面「link 的 raw HTML 連結」。
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
# ── r9 為什麼可以是關卡（issue #94）──────────────────────────────────────
# 原本停在 advisory 的理由寫在 GATES 那一行：「值欄該記什麼未定案（issue #13／#22）」，
# 加上更直接的一點——**內容從來沒用過條文的用詞**。條文的三值是 `✅ 可用`／`📝 已宣稱`／
# `⬜ 未測`，七個對照表檔寫的卻是 `✅ 實測 <日期>`／`⬜ 未實測`／`⬜ 未實作`，
# 當時打開 `DEVFLOW_GATE_R9=1` 是 11 條 ❌、涵蓋 64 格：設成關卡會擋死每個 PR。
# 使用者 2026-09-19 裁決採方向 A（改內容、條文不動），issue #94 把那 64 格的狀態欄
# 逐格換成條文原文（只換開頭的標記詞，補充內容一字未動），遷移完成，本項才升為關卡。
#   生效性：`R9` 住第 5 節，依 `ST5` 自 stage 0 起生效（和 `table` 同一條依據）。
#   定義域：**只有狀態欄**，且封閉——`table` 那一節判定為「合格」的表（status_tables）
#       的資料列狀態格。形狀不合的表不進來：它們已經被 `table` 擋，這裡不重複報，
#       也不在沒有格式契約的東西上判值。
#       **表格以外的敘述句不掃**：`R9` 管的是「狀態欄取三值之一」，沒有規定散文怎麼寫。
#       掃散文會擋掉討論用詞沿革、引用舊格式、寫給讀者的遷移說明（審查者 PR #95 反例）。
#       **值欄該記什麼也不在定義域內**：本項只判狀態格取不取三值之一，不判補充寫得對不對。
#       這是**刻意限縮**，不是因為那件事未定案——#13 已於 2026-09-15 關閉（`R8` 改前瞻
#       讀法後困境解消，`R9`／`R10` 的條件已夠具體）。完整的機械覆蓋留母單 #22。
#   假陽性：三值之後允許「分隔符 ＋ 補充」（R9_SEPS），所以 `⬜ 未測`、
#       `✅ 可用（實測 2026-09-11，驗證方式：…）`、`📝 已宣稱（驗證未達 `✅`：…）` 都不擋；
#       擋的是黏著詞（`✅ 可用性佳`）、少了分隔符（`✅可用`）、三值之外的詞（`✅ 完成`）
#       與舊詞（`✅ 實測`）。本地以 tests/smoke_devflow_checks.py 的四個 `r9:*` 應擋案例
#       ＋ `r9:separators` 正向案例複驗。**不宣稱「不存在假陽性」**——那個宣稱被推翻過一次。
#   仍擋不住：狀態欄的**值對不對**。`✅` 的驗證方式與受測環境（`R10`）齊不齊、`📝` 有沒有
#       依 `R9` 標明是哪一種、宣稱與證據符不符，都是語意，檢查器判不了，仍靠 `R4` 人工審查
#       （留在 issue #22）。本項只鎖住「用詞不會再漂走」。
#
# ── dupid 為什麼可以是關卡（issue #96）───────────────────────────────────
# 停在 advisory 的理由是三個假陽性（附錄的散文、規則索引、blockquote 引述），當時的診斷是
# 「散文和定義在語法上分不出來；要分得出來就得知道哪幾節裡的清單項才是定義——那是分節
# schema，屬 issue #22，同樣要等 stage 2」。**那個診斷不正確，本節取代它**：分節結構本來
# 就在 WORKFLOW.md 裡，`## <數字>. <名>（<家族>）` 的括號字母就是該節定義的 ID 家族，
# 不必新增任何 schema，也和 stage 無關。
#   一、生效性：本項不引任何依 `stage` 啟用的條文。它驗的是規則本體自己的內部一致性——
#       同一個 ID 指向兩條規則時，`WORKFLOW.md:7`「引用規則一律用 ID」就無法定位到唯一
#       一條規則（`I5`「一個事實只住一處」是同一個方向）；這兩處都在「永遠生效」的節裡
#       （第 0 節：第 0、1、13 節永遠生效）。停損理由三（拿休眠條文當 gate 依據）不成立。
#   二、定義域封閉：一個已知檔案（devflow/WORKFLOW.md），一個定義判準，三個條件同時成立
#       才算定義（見 RULE_SECTION_RE 與 rule_definitions 的 docstring）：
#         (1) 落在 `## <數字>. <名>（<家族>）` 這種節之下；
#         (2) ID 的字母前綴＝該節括號裡的家族；
#         (3) 本項的原始行（list_item_open 那一行）以 `- ` 開頭。
#       節標題**用正規式抓形狀，不硬編碼 13 個節名**：日後新增節自動納入，不含括號字母的
#       節（第 0 節「變數與基準」）不產生定義。節的範圍到下一個同層或更淺的標題為止，
#       更深的子標題仍在節內；容器（blockquote／清單）裡的 `## …` 不分節，同 r9_sections。
#   三、假陽性：三個都不再成立，本地以 tests/smoke_devflow_checks.py 的三個 `dupid:*`
#       正向案例逐案複驗（各對應一個條件）：
#         - 附錄「常見誤讀」用清單解釋既有規則（「- `R3` 常被誤讀成…」）——附錄的節標題
#           沒有家族標記，條件 (1) 不成立；
#         - 加一節「規則索引」把所有 ID 列一遍——同樣沒有家族標記，且列進來的 `I1`、`I2`
#           與該節家族不符，條件 (1)(2) 都不成立；
#         - blockquote 引述既有條文（「> - `D1` …」）——行首是 `>`，條件 (3) 不成立。
#       粗體開頭（「- **`R3`** …」）仍算定義：ID 是不是本項的開頭由 token 層判，
#       條件 (3) 只看行首那個 `- `，不看後面的標記。fenced code block 裡的示範不產生
#       list_item token，天然排除。判準在**現行內容**上的結果與舊判準相同——71 條定義、
#       零重複（升關卡前實跑，exit 0）。**不宣稱「不存在假陽性」**：那個宣稱在本檔被推翻過
#       兩次（停損理由二）。
#   假陽性（判準的必然代價）：ID 前面有**已關閉的裝飾**但那不是本項主題時，仍算定義——
#       「- **注意** `R3` 的例外」會被當成 R3 的定義。原因是 `**注意**` 的內文住在一個
#       **已經關閉的** strong 容器裡，容器路徑不是 ID 的前綴，不算同層裸文字（#98 原本
#       寫成「level=1 比 ID 深」，那個機制描述已隨 PR #99 改掉，結論不變）。這與
#       「- **`R3`** …」（粗體包住 ID，必須算定義）在 token 結構上無法區分：
#       兩者的差別只在人讀得出的語意。orchestrator 實測。
#       代價方向：多認一條定義 → 若該 ID 別處另有真定義，會報成重複（可見的誤擋），
#       不會反過來藏住重複。
#   仍擋不住（刻意的代價，不是漏洞）：寫在無家族標記的節裡、或家族與節不符的重複定義——
#       例如把「- `I1` …」又寫進第 13 節。依判準它根本不算定義，所以不報。要連那種也擋，
#       得先由人裁決「定義只能寫在帶家族標記的節裡」並寫進 WORKFLOW.md（`G2`），
#       不由本檔自己發明規則。
#
# ── dupid 的「ID 是本項的開頭」為什麼不再窮舉（issue #98）────────────────────
# #96 的實作是「逐個跳過開標記，取第一個實質 token」：
#     if c.type in ("strong_open", "em_open", "s_open", "link_open"): continue
# 這個跳過清單是**開放集合**，每多一種寫法就要補一次。orchestrator 實測五種寫法，四種漏認
# （issue #98 的表）：`[](#x)` 停在 link_close、`[看這裡](#x)` 停在連結文字、`![](img.png)`
# 停在 image、`~~舊~~` 根本連 token 都不是（commonmark preset 把它當字面文字）。
# **這是必需關卡上的繞過**：`- [](#invisible) `X1` …` 加一個看不見的空連結，重複定義就不報。
#
# 改法不是把清單補長，是換問題：**不問「前面那個 token 是不是某種標記」，問「ID 前面有沒有
# 裸文字」**（leading_code_span）。裸文字＝與 ID 的 code span 同層或更外層的文字 token。
# 「同層或更外層」用**容器祖先路徑**判，不用深度數字：前置文字 token 的容器堆疊快照必須是
# ID 的容器堆疊快照的**前綴**（container_stacks）——相等＝同層、較短＝更外層；不成前綴表示
# 它在另一個（已經關閉的）sibling 容器裡，那是裝飾。
#   為什麼不能用 `level`（PR #99 第一輪審查，本輪改掉）：`level` 只是巢狀深度，**不帶容器
#     身分**。容器關閉後深度會被重用，於是 `- [裝飾](#x) …` 裡已關閉的連結內文（lv1）與
#     `- **`D1`** …` 裡包住 ID 的粗體內文（也是 lv1）分不出來，前者被當成「與 ID 同層的
#     裸文字」而**漏認**真定義。實測兩種寫法：`- [裝飾](#x) **`D1`** …`、
#     `- ~~舊~~ *`D1`* …`。語法全屬目前 parser 已支援的範圍、不需要任何外掛——那等於把
#     「空連結＋裸 ID」換形狀成「連結＋粗體 ID」就能藏住重複定義，同一條必需關卡的繞過
#     只是換了個寫法。堆疊快照帶著容器身分，兩者才分得開。
#   為什麼不必窮舉標記型別，**以及這句話的適用範圍**：在**目前已啟用的 parser 規則**
#     （commonmark ＋ `table` ＋ `strikethrough`）下，承載字面 prose 的 token 型別就是
#     TEXT_TOKENS 那一小組，其餘型別一律不看。這些規則的行內語法分兩類，兩類都不必逐一補：
#       - **把 prose 包進容器的**（`em`、`strong`、`link`、`s`，autolink 也走 `link_*`）：
#         產生自己的開／關 token（不是文字）＋自己那一層的內文，內文算不算裸文字由前綴
#         判準決定。
#       - **leaf（`nesting=0`，不開容器）**：`image`、`code_inline`、`html_inline`、
#         `softbreak`、`hardbreak`。它們有些帶內容（image 的 alt、code_inline 的碼、
#         html_inline 的 markup），但型別不在 TEXT_TOKENS 裡，一律不算裸文字——也就是
#         當成裝飾放行（`code_inline` 另有例外：它就是候選 ID 本身，由主流程處理）。
#         這是**刻意的個別政策**，不是「行內語法都會產生開／關 token」的推論結果；
#         image alt 因此形成一個已知假陽性，記在下面。
#     **這不是對任意外掛自動成立的宣稱**（原本寫成「承載字面文字的 token 型別是封閉的
#     一小組」，過廣，本輪限縮）：`footnote_ref`、`math_inline` 這類外掛直接產生**帶內容的
#     leaf token**——型別既不在 TEXT_TOKENS 裡、也不是 `*_open`／`*_close`——於是整顆被當成
#     裝飾放行。啟用新外掛＝要重新看它產出什麼 token，並決定它該不該算裸文字，不能靠這一段
#     推論。（外掛這一項依官方原始碼核對，未實跑：本機沒有 mdit_py_plugins。）
#   新的誤認風險（誠實記下，不宣稱封閉）：
#     - 假陽性方向：ID 之前只要沒有裸文字就算定義，所以「- ![badge](x.svg) `D1` …」這種
#       有 alt 文字的圖片、「- [](#a)」換行後才寫 ID，都會被當成定義。它們的形狀確實是
#       「這一項在講這個 ID」，判成定義是刻意的；真正的散文（「- 見 `I2` 與 `L3`」）被
#       擋掉，因為 `見 ` 是裸文字。tests 的 `dupid:prose-*` 三案鎖住這一邊，其中
#       `prose-in-strong`（「- **注意 `D1` 在粗體裡**」）鎖的是「同層」那半句：只比
#       頂層有沒有裸文字的實作會把整句包在粗體裡的散文誤判成定義。
#     - 假陰性方向（三類，方向都是漏認＝藏得住重複定義。原本只寫了 (a) 一類，
#       且把「與 GitHub 算繪一致」說成通則，兩者本輪都限縮）：
#       (a) parser **不認得**、GitHub **也**當成普通文字的語法（`==標記== `D1` …`）：
#           那一段留成字面文字＝裸文字，本項就不算定義。這一類檢查器與讀者看到的一致，
#           所以只是代價不是落差。**「parser 不認得的語法與 GitHub 算繪一致」只對這一類
#           成立，不是通則**——(b) 就是反例。
#       (b) GitHub 認得、本檔的 parser **沒有啟用**的語法：兩邊**不一致**，讀者看到標記、
#           檢查器看到裸文字。GFM task-list（`- [x] `D1` …`——`[x] ` 在 parser 眼裡是
#           頂層字面文字，讀者眼裡是 checkbox，所以「這一項在講 `D1`」的形狀漏認）、
#           extended autolink（裸網址）都在這一類。`~~` 本來也在，已靠把解析器對齊 GFM
#           （MD 的 `strikethrough`）消掉——那是**一次一種語法**的補法，不是判準的通則，
#           仍可能有下一種。tests 的 `dupid:task-list` 把 (b) 的現況行為釘成絆線
#           （斷言的是現況＝漏認，啟用 task-list 後該案會失敗，逼人當場改判）。
#       (c) parser **完全認得**、判準自己看走眼的（PR #99 第一輪審查發現）：裝飾與 ID 各在
#           自己的 sibling 容器裡，深度數字碰巧相同而被當成同層裸文字
#           （`- [裝飾](#x) **`D1`** …`、`- ~~舊~~ *`D1`* …`）。這一類是**實作缺陷不是
#           代價**——已由上面的容器路徑判準修掉，tests 的 `dupid:link-strong`、
#           `dupid:strike-em` 鎖住它不回頭。
#   條件 (3) 的錨點同時改了：從「ID 所在的那一行」改成「list_item_open 自己那一行」。
#     ID 前面既然可以有裝飾，裝飾裡就可以有換行，那時 ID 落在縮排的續行上，拿它判行首
#     會把真定義判掉（又一個繞過）。本項的行首寫法只有一個來源，就是本項的第一行；
#     三個假陽性案例（附錄、索引、`> - …`）的第一行寫法不變，判定與 #96 相同。
#
# ── link 的 raw HTML 連結（issue #100）───────────────────────────────────
# `link` 原本只認 AST 裡的 `link_open`／`image` token 與 reference 定義。raw HTML 的連結不產生
# 那兩種 token（parser 給的是 html_block／html_inline），於是**完全不受檢查**——必需關卡上的
# 繞過（#22 第三輪審查的假陰性 5）。orchestrator 在 `894ab1e` 實測五種寫法全部 exit 0：
# 行首的 `<a href>`、前面有文字的 `<a href>`、`<img src>`、指向 `.git/config`、
# `../../etc/passwd`。（issue 把第一種記成 html_block，本地實測不是：`a` 不是 type 6 的區塊
# 標籤、標籤後又接了文字，整行是段落裡的 html_inline；html_block 那一路是 `<img>` 單獨一行
# 與 `<div>` 包住的寫法。兩條路徑 tests 都有案例。）
#   判準：**列舉什麼承載連結，不列舉要擋什麼**（#98 的教訓：繞過清單窮舉不完）。承載連結的
#     是 HTML_LINK_ATTRS 這一小組 (標籤, 屬性)，目前是 `<a href>`、`<img src>`、`<img srcset>`、
#     `<source srcset>` 四個，每一組附一個「從值切出 URL」的切法（href／src 整個值就是一個
#     URL；srcset 見下面 issue #102 那一段）；不在這一組的標籤與屬性一律不看。切出的每個
#     URL 交給 markdown 連結用的**同一個**判定迴圈（下面 link 那一節）：
#     有 scheme 的、純 fragment、`//host` 不驗；先切 fragment 再切 query（#22 缺口 9）；比對
#     路徑段而非 `startswith("..")`（`..probe.md`）；存在性問 `git ls-files` 而非
#     `os.path.exists`（#22 缺口 6）。**這四條只有一份實作**——raw HTML 那一路若另寫判定，
#     四個已修缺陷會在新路徑上全部復活。
#   取出：與 `table` 的 raw HTML 表格共用同一套（raw_html_chunks → html_start_tags）。只認
#     parser 判成 HTML 的 token，所以 code fence／縮排 code block／code span 裡的示範天然排除；
#     只認 HTMLParser 判成 start tag 的東西，所以 HTML 註解、屬性值裡的 `<a href` 不算。
#     **不解析 HTML 的內容語意**（界線同 raw_html_tables：那會讓檢查器變成第二個 parser）——
#     對屬性值只做 URL 標準本來就對它做的兩步（去掉前後的控制字元與空白、刪掉 tab／換行），
#     entity 由 HTMLParser 解開，其餘一概不動。
#   行號：行內 HTML 的行號改由 parser 記下的原文位移算（HTML_POS）。#92 從兄弟 token 反推換行，
#     本地實測四種寫法少算一行（多行 code span、連結目的地前換行、連結 title 前換行、跨行的
#     reference label）——那些換行不在任何 token 裡。`table` 的行號同樣受影響，一併修掉。
#     包裝有沒有生效，啟動時自檢（不等內容裡剛好有行內 HTML）。本地只在 markdown-it-py 4.0.0
#     實跑過；CI pin 的 3.0.0 本地沒有，依原始碼判斷規則介面相同、**未實跑**——CI 每次執行
#     都會跑到那個自檢。
#     **自檢與 tests 都不完備，兩者合起來也不完備**（PR #101 兩輪審查各以定點突變實測）。
#     能抓到的，只有這些：
#       - 規則完全沒註冊、或 HTML_POS 寫成探針值以外的東西 → 自檢 exit 2。
#       - HTML_POS 固定成探針那個值（4）→ 自檢通過，tests 三個非 4 位移案例抓到。
#     抓不到的（已知有，不是推測）：把字元位移誤當 UTF-8 byte 位移——自檢通過、PR #101
#     當時的 67 案與 issue #102 補完後的 75 案都全過（後者本地重跑該突變實測），某些 CJK ＋
#     跨行的組合行號會多算一行。要收掉這一類得補對應的 tests 案例；在那之前，**不要把這段
#     讀成「錯的位移都會被擋下」**。
#   srcset（issue #102）：值不是一個 URL，是「候選 URL ＋ descriptor」的串（`a.png 480w,
#     b.png 800w`、`a.png 1x, b.png 2x`、`a.png`）。切法照 HTML 規格的「parse a srcset
#     attribute」：跳過前導的空白與逗號 → 到下一個空白為止是 URL（URL 以逗號結尾就剝掉結尾
#     逗號、沒有 descriptor）→ 其後到括號外的下一個逗號為止是 descriptor → 重複。
#     **不是 split(",")**：URL 本身可以含逗號（`a.png?x=1,2 480w`、`data:` URI），而沒有空白的
#     `a.png,b.png` 在規格裡是**一個** URL（瀏覽器照原樣去抓）。空白指規格的 ASCII whitespace
#     （space、tab、LF、FF、CR），不含 NBSP、全形空白。
#     切出的每個 URL 各自做上面那兩步 URL 前處理、各自進同一個判定迴圈——壞的那一個單獨成一條
#     明細（`檔:行 -> 那個 URL`），不是整串。切法（srcset_urls）只切字串，不判定。
#     `<img>` 同時有 `src` 與 `srcset` 時兩者都驗。
#     行號：同一個標籤切出的 URL 都報該 start tag 的 `<` 所在行（HTMLParser 只給標籤的位置，
#     不給屬性值的位置）。srcset 的值自己跨行時（候選之間以換行分隔），第二行以後的候選報的
#     仍是 `<` 那一行，不是候選自己那一行。
#   擴充（新增一種承載連結的屬性）：在 HTML_LINK_ATTRS 加一組 (標籤, 屬性) 與它的切法，並在
#     tests/smoke_devflow_checks.py 補一個應擋案例。值就是一個 URL 的，切法用 `_one_url`；
#     值是別種微語法的，要先寫出它的切法——那是新政策，不是補清單（issue #102 為 srcset 定過
#     一次）。不論哪種，切法都只切字串，**不得**在取出的地方另做判定。
#   仍擋不住（不宣稱「所有 HTML 連結都擋得住」，也不宣稱「所有 srcset 都擋得住」）。分兩類：
#     刻意的政策（有意不做；要改，由人裁決）：
#     - HTML_LINK_ATTRS 以外的屬性：`<img longdesc>`、`cite`（blockquote／q／del／ins）、
#       `<video src>`／`poster`、`<object data>`、`<iframe src>`、`<area href>`、`<link href>`、
#       `<form action>`、`style` 屬性裡的 `url()`。除了 `style` 的 `url()`，這些 PR #101 第一輪
#       審查都以 GitHub renderer（`gh api markdown`）實測過：被移除、失效、escape 成文字，或保留
#       屬性但不呈現成可點連結（issue #102 的表）。`style` 的 `url()` 沒有實測。
#     - `<source src>`（issue #102 AC-3 的裁決）：**維持放行，是政策不是遺漏**。`<source src>`
#       只在 `<audio>`／`<video>` 裡作用，而 GitHub 算繪時移除媒體元素。orchestrator 於
#       `1d0e7f5` 以 `gh api markdown --raw-field mode=gfm --raw-field context=<repo>` 實測：
#       `<video><source src>` 整個被移除（算繪成空的 `<p>`）；`<audio><source src>` 的
#       `<audio>` 被移除、`<source>` 自己留下但 `src` 消失，沒有媒體父元素也不會載入任何
#       東西。讀者看不到的東西壞了，不是本項要擋的落差。
#       `<picture>` 裡的 `<source src>` 是同一個結論：renderer 一樣把 `src` 剝掉（PR #103
#       兩輪審查各自實測），而且它本來就不參與選圖（HTML 規格：`<picture>` 只看 `<source>`
#       的 srcset）。`<source>` 的合法父元素就是 `<picture>` 與 media element（`<audio>`／
#       `<video>`）兩類，所以 `<source src>` 放行涵蓋全部合法用法；放在別處（孤立、`<div>`
#       內）屬無效用法，renderer 同樣剝掉 `src`。本檔沒有為它另立 tests 案例。
#     - `<img srcset>` 照驗，**即使 GitHub 會把整個 srcset 屬性剝掉**（orchestrator 實測：
#       `<img srcset="a.png 1x, b.png 2x" src="c.png">` 算繪成 `<img src="c.png">`）。留著是
#       刻意的：方向是只會多擋、不會漏放，可擋住「打算給別處用、路徑就是錯的」srcset。
#     - `<source srcset>` 的**合法多候選**：GitHub 的 sanitizer 只留下第一個 URL（PR #103
#       第一輪審查實測：`<picture><source srcset="README.md 1x, does/not/exist.png 2x">` 算繪成
#       `<source srcset="README.md">`，第二候選與 descriptor 都消失）。本檔仍驗全部候選，所以
#       後續候選指到不存在的路徑時會擋下一個讀者其實看不到的連結——**這是刻意的假陽性**，
#       方向仍是只會多擋、不會漏放。
#       縮減與否的變因是**有沒有構成合法的 `<picture>`**，不是 renderer 的 repo `context`
#       （PR #103 第二輪審查以四格矩陣實測：合法 picture 帶或不帶 context 都縮成第一個
#       URL；孤立的 `<source srcset>` 帶或不帶 context 都原樣保留）。
#     - `<base href>`：瀏覽器會拿它改寫整份文件的相對連結；本檔一律相對於 md 檔所在目錄解析
#       （和 markdown 連結同一個規則），不讀 `<base>`。
#     - 圖片 alt 裡的 HTML（`![<a href="x">](y.png)`）：alt 是純文字屬性，讀者看不到連結，
#       不看（parser 把它放在 image 自己的 children，以另一個 src 解析）。
#     - 同一個標籤重複的屬性（`<a href="ok" href="bad">`）：瀏覽器只用第一個，本檔每個都驗——
#       只會更嚴，代價是可見的誤擋，不會漏放。
#     - srcset 的 descriptor 不解析：規格裡會被瀏覽器捨棄的候選（descriptor 不合法，例如
#       `a.png 1q`；密度與前面的候選重複），本檔照樣驗它的 URL——只會更嚴，不會漏放。
#     - `<source srcset>` 不看所在位置與條件：不在 `<picture>` 裡的、`media`／`type` 不符而瀏覽器
#       不會選到的，本檔照樣驗——只會更嚴，不會漏放。
#     推論或未實測（不是有意不做，是判不了或沒驗過）：
#     - GitHub 怎麼處理 srcset 的相對路徑，**沒有實測**。本檔把它和 `<img src>` 一樣相對於 md 檔
#       所在目錄解析、問 `git ls-files` 存不存在；PR #101 第一輪審查的 renderer 輸出只證明
#       `<picture><source srcset>` 被保留，沒有證明 GitHub 在頁面上會把 srcset 的相對路徑改寫成
#       載入得到的位址。若不改寫，指向存在檔案的相對 srcset 讀者端也可能載不出來——本項驗的只有
#       「指到 repo 裡存在的路徑」。
#     - srcset 切法照規格步驟寫、tests 有正反案例；沒有拿真的瀏覽器的選圖結果對照過。
#     - JS 產生的連結：不在檔案的靜態內容裡，本檔讀的是原始碼，看不到。
#     - HTMLParser 不是瀏覽器的 HTML5 tokenizer：對畸形標記的錯誤復原可能不一致（例如沒閉合的
#       標籤被後面的算繪結果補齊），兩邊看到的 start tag 就不同。本地實跑過 HTMLParser 對未閉合
#       引號、`<![CDATA[`、`<?…>`、`<!DOCTYPE` 的結果；瀏覽器那一邊是依 HTML 規格推論，
#       未在 GitHub 上實測。
#     - HTMLParser 真的拋例外時（本地沒找到會拋的輸入）：那段 HTML 當成一條判不了的連結擋下
#       （fail closed），不是放行；這條路徑因此沒有 tests 案例。
#     - markdown 連結的行號仍是段落的第一行（locate），不像 raw HTML 那樣精確；那一路本單沒動。
#   假陽性：正文裡直接寫 `<a href="路徑/示範.md">` 當例子、不包 code span 會被擋——要示範就放進
#     code span 或 code fence（同 `table` 的做法）。現行受版控 md 沒有任何 raw HTML 連結（issue
#     #100 orchestrator 確認；改動後完整檢查仍 exit 0、相對連結數不變），也沒有任何 `srcset`
#     （issue #102 orchestrator 確認；改動後同樣 exit 0、相對連結數不變），所以本項不改變現行
#     內容的判定。tests 的四個 `link:html-*` 正向案例（fence、code span、註解、合法連結）與兩個
#     `link:srcset-*` 正向案例（合法的 descriptor／URL 含逗號／data: URI／各種空白、fence 與
#     code span 裡的示範）鎖住這一邊。srcset 已知會誤擋的寫法見上面「刻意的政策」的後兩條。
#     **不宣稱「不存在假陽性」**。
#
# ── v7 為什麼可以是關卡（issue #150）────────────────────────────────────
# `V7`（WORKFLOW.md 1.5.0.0，#147）：PR 動到 `devflow/**`（`devflow/VERSION` 自身除外）時，
# 同一 PR 須使 `devflow/VERSION` 進位。安裝器只報 VERSION、kit tag 只打在 main 已含的
# commit（`V5`），所以 main 上「同版號不同內容」只能靠這一關擋。
#   生效性：`V7` 住第 3 節，依 `ST1`（「單線：第 3～8、10 節生效」）在 stage 1 已生效，
#       和 `version` 同一條依據。
#   定義域封閉：兩個 git 物件（merge-base 與 HEAD）、一個檔案（`devflow/VERSION`）、
#       一條 diff 路徑過濾（`-- devflow/`，Python 端再排除 VERSION 自己）。沒有散文判讀、
#       不打 API、不看 issue、不讀 tag。「版本」的判定**直接 import 安裝器的 VERSION_RE**，
#       不另寫一份——同 `i5` 不另寫一份 AC-7 判定的理由：兩份判定就有第三個可漂移的東西。
#   不判位數對不對：`a`／`b`／`c`／`d` 該進哪一位是 `V1`／`V2` 的語意判斷，`V2` 明文不許
#       機械自判，留給審查者。本項只判「有沒有進位」（四碼數值元組嚴格遞增）。
#   升關卡的順序（同 `i5`：本地正反 → 設 True → CI 正反）：本地正反在
#       tests/smoke_devflow_checks.py 的三個 `v7:*` 正向、四個 `v7:*` 應擋、兩個 `v7:*`
#       環境錯誤案例（PR #152）。設 True 之前另取了一個 advisory 期間的真實 CI 反向
#       run（PR #153 probe，run 35585351635，blob e067a13：`📝 動到 devflow/ 卻沒有進位`、
#       exit 0），證明 CI 上的 base 取得（`origin/<GITHUB_BASE_REF>`，需 `fetch-depth: 0`）
#       與 diff 路徑過濾在真實 `pull_request` 事件下行為與本地一致。
#       設 True 之後 README「升 required 的判定方式」要的同 blob 正反兩個真實 run
#       記在 issue #150（AC-3）。
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
#   * 【十個關卡以外的全部。】以下各條說的是「連報告都報不到」，
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
#   * 【同一個規則 ID 被定義兩次 —— 只擋「家族節內」的那種。】
#     dupid 自 issue #96 起是關卡（判準見上面「dupid 為什麼可以是關卡」）。它擋的是
#     兩條定義都落在自己家族的節裡；把「- `I1` …」又寫進第 13 節（家族不符），或寫進
#     附錄、索引這種沒有家族標記的節，依判準都不算定義，**不報**。那是判準的取捨：
#     要連那種也擋，得先由人把「定義只能寫在帶家族標記的節裡」寫進 WORKFLOW.md（`G2`）。
#     另一種漏放（issue #98）：ID 前面的那段東西被 parser 看成**字面文字**，於是成了
#     裸文字，本項就不算定義。兩種來源，只有前者與 GitHub 一致：
#       - parser 不認得、GitHub 也當文字的（`==x== `D1` …`）——檢查器與讀者看到的一樣，
#         是代價；
#       - GitHub 認得、本檔的 parser **沒有啟用**的（GFM task-list `- [x] `D1` …`、
#         extended autolink）——兩邊不一致，讀者看到的是標記。`~~` 曾屬於這一種，已靠
#         把解析器對齊 GFM 消掉；**那是一次一種語法的補法，不是判準的通則**，仍可能有
#         下一種。要收掉 task-list 得引入新相依（mdit_py_plugins），那要人裁決。
#     第三種（PR #99 第一輪審查）**不是**漏放而是實作缺陷，已修：裝飾與 ID 各在自己的
#     sibling 容器裡時，舊判準比 `level` 深度數字會把裝飾內文當成同層裸文字而漏認
#     （`- [裝飾](#x) **`D1`** …`）。現在比容器祖先路徑，見上面那一節。
#   * 【改 ID 後別的檔案還指著舊號 —— 沒有東西在擋。】
#     refs 這一項本來就是為這個失效而存在的，但它會把 `M5`（Apple 晶片）、`C5`
#     （RFC 分類）這種合法的非規則代號判成懸空規則引用。WORKFLOW.md:7 只寫「引用規則
#     一律用 ID」，並沒有反向把所有這種形狀的 code span 保留給規則命名空間——所以那是
#     誤擋，不是使用者誤用。它現在是建議：CI log 會列出來，但**不會擋人，也沒有任何
#     機制保證有人讀**。實際擋這個失效的只剩人工審查（R4）。
#     issue #96 把家族的來源從「基線 ∪ 現有定義的前綴」換成節標題宣告的家族（見
#     BASELINE_PREFIXES），但那只是第一層：`M5` 的前綴 `M` 本來就是家族，誤擋照舊。
#     同一單逐項評估過 issue 列的三個第二層方向，沒有一個封得住定義域，所以本項留在
#     advisory（分析與實測數據記在 issue #96，結論留給母單 #22）：
#       - 只掃 `devflow/` 下的檔案：治不了——`M5`／`C5` 這種受測環境記載（`R10`）正是
#         寫在 devflow/ 的對照表裡；反而把 CLAUDE.md／AGENTS.md／README.md／docs/
#         （「別的檔案還指著舊號」的主要現場）整批移出定義域，兩頭都更差。
#       - 排除特定上下文（受測環境、值欄）：對照表的值欄、面向欄、狀態欄補充裡本來就
#         有大量**合法**的規則引用（「依 `R9`」、「審查證據（`R3`／`R5`）」、「合併（`I3`）」），
#         而「受測環境記載」和它們住同一格、沒有任何語法邊界分得開。要分得開就得先給
#         對照表的格子訂格式契約——那要動條文，走 `G2`，不在檢查器這邊。
#       - 只檢查「家族 ＋ 該家族已定義的編號範圍」：能消掉 `M5`／`C5`（M 家族只定義到
#         M4、C 家族只到 C4），但代價是本項只剩「編號有洞」才報得出來。現行 13 個家族
#         的編號全部連號、零洞，等於裝一個永遠不會響的關卡；而最常見的懸空成因——刪掉
#         或改掉家族裡編號最大的那條（例如 `R10`）——正好不會留下洞，會被靜默放過。
#         判準本身也是循環的：「`X5` 沒有定義所以它不是規則引用」，而本項要找的就是
#         「指向未定義 ID 的引用」。
#     升為關卡的條件不變：建立保留命名空間，或把掃描範圍限定到可以宣告「此處 ID 形狀的
#     code span 一律是規則引用」的檔案集合。兩者都要人裁決、都要動 WORKFLOW.md（`G2`），
#     不由本檔自己發明。在那之前，改動規則 ID 的 PR（#12／#17）建議手動跑一次
#     DEVFLOW_GATE_REFS=1；refs 的 📝 需要人判斷是真懸空還是非規則代號。
#   * 另外三項：fenced code block 未關閉、對照表形狀、相對連結有效性。
#     六輪審查的缺口幾乎都落在這些項目裡，因為它們驗的是「任意 markdown 內容」。
#     每項都能用 DEVFLOW_GATE_<KEY>=1 單獨打開，當成手動檢查工具跑。
#   * 【V1 的「進位歸零」沒驗】0.0.2.0 → 0.0.3.7 會通過。要驗它得跟 base 上的版本
#     比對（新的資料來源），而「該 bump 哪一位」依 V2／V3 是 normative／editorial 的
#     語意判斷，檢查器判不了。只驗「形式上有歸零」會擋掉合法的多位同時變更，
#     製造新的假陽性。留在 issue #22，本輪不做半套。
#   * 從未定義過的規則家族（例如 `Q3`）連建議都不會報：前綴集合＝基線 ∪ 現有定義的
#     前綴。放寬成「任何 ID 形狀」只會讓上面那個誤擋問題更嚴重。
#   * 權威檔案清單、raw HTML 內容（兩個例外：對照表檔內的 `<table`，issue #90 起歸 `table`；
#     HTML_LINK_ATTRS 承載的連結，issue #100 起歸 `link`，其餘屬性見「link 的 raw HTML 連結」）、
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
# 印出的符號與 exit code 的對應：✅ 該項通過、❌ 必需關卡失敗（→ exit 1）、
# 📝 建議項的發現（report() 在 GATES 為 False 時，→ 不影響 exit code）、
# 💥 檢查器無法執行（→ exit 2）。另有 ℹ️（提示）與 ⚠️（警告）兩級，只有 `r2` 用，
# 依 issue #218 的裁決不進 errors、不影響 exit code，見該節與 info()／warn()。
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

# ── 本機設定檔（issue #222）───────────────────────────────────────
# 本機執行才需要的設定住 repo 根目錄的 `.devflow-local`（不受版控，見 .gitignore）。
#
# 它存在的理由是**指令形式**，不是新功能：`L4` 要實作位自己跑這支檢查器，而派工的
# `--allowedTools` 白名單以指令前綴比對，`Bash(python3 *)` 不匹配任何帶環境變數前綴的
# 形式。逐一列舉組合列不完——issue #217 的甲案加了 `Bash(DEVFLOW_ALLOW_PIN_DRIFT=1 *)`
# 之後，兩個變數連寫（`A=1 B=2 python3 …`）實測仍被拒，而每新增一個變數都要再改名單。
# 設定搬進檔案，`L4` 的指令就回到裸形式 `python3 scripts/devflow_checks.py`。
#
# CI 的嚴格性由「這個檔不受版控」保證，不靠檢查器判斷自己在不在 CI。而「不受版控」
# 這件事**由檢查器自己守**（`_local_tracked`），不是交給 `.gitignore`：`.gitignore` 擋不住
# `git add -f`，而這個檔一旦進了版控就會跟著 CI 的 checkout 走——repo 的內容就能決定
# `v7` 拿誰當 base，等於「改 PR 自己的內容就關掉一道必需關卡」。這是 PR #226 第一輪
# 審查的 BLOCK-1，實測把本檔 `git add -f` 進 PR 並寫 `v7_base = HEAD` 之後，動了
# `devflow/**` 卻不進位的分支在 CI 形狀下從 exit 1 變成 exit 0。舊機制的放寬點只在
# 環境變數、repo 內容碰不到，本檔是第一個讓 repo 內容有機會影響判定的東西，所以這道線
# 必須在檢查器裡。守住之後兩個既有原則才成立：base 那三個來源「只能指定比較對象，
# 不能放寬判定」，以及 `DEVFLOW_GATE_` 的「只能加嚴不能放寬」。
#
# 煙霧測試的沙箱同理不會有它：`tests/smoke_devflow_checks.py` 用
# `git ls-files --cached --others --exclude-standard` 列出要複製的檔，被 `.gitignore` 忽略的
# 不在名單內；沙箱自己也是 git repo，真被放進去了照樣撞上上面那道版控檢查。
#
# 格式是**手寫解析的 `key = value`**，不用 YAML，也因此排在下面的 import 之前：
# `allow_pin_drift` 的用途正是「import 到的 parser 不是 pin 的那一版時放行」，拿那個
# parser 去讀這個決定，等於用受質疑的工具判自己該不該被質疑。這段只碰標準庫。
#
# 定義域：一個檔案、兩個已知鍵、逐行 `key = value`、`#` 開頭與空白行略過。認不得的鍵、
# 收不了的值、重複的鍵、缺 `=` 的行一律 exit 2 而不是略過——這是開發者自己維護的檔，
# 打錯字若被靜默忽略，人會以為設定生效了（同 _QUERY_MODES 不默默忽略認不得的旗標的
# 理由）。唯一被靜默吃掉的是 UTF-8 BOM：那不是人打的字，是編輯器加的。
# 查詢模式（`--print-pins`／`--check-pins`）在上面就已結束，不讀本檔：它們只回報
# 「裝了什麼」，不做任何豁免。
LOCAL_FILE = ".devflow-local"
# 鍵 → 收的值域（None＝收任何非空字串）。`allow_pin_drift` 只收兩個字面布林，不收
# `1`／`yes`／`on`：多一種寫法就多一種要說明的事，而這個檔只有一個讀者。`v7_base` 的值
# 有效性交給 git 自己判（同 DEVFLOW_V7_BASE 現行的處置：解析不了就在 `v7` 那節 die）。
LOCAL_KEYS = {"allow_pin_drift": ("true", "false"), "v7_base": None}


def _local_bad(msg, *hints):
    """本機設定檔判不了＝檢查器無法執行。die() 這裡還沒定義，自己印。"""
    print("💥 檢查器無法執行：%s" % msg)
    for _h in hints:
        print("    %s" % _h)
    sys.exit(2)


def _local_tracked(path):
    """問 git 這個檔受不受版控，回傳 True／False；問不出答案就 _local_bad。

    答不出來時**不當成未追蹤**（PR #226 第一輪審查 BLOCK-1）：讀這個檔的效果一律是
    放寬（關掉 pin 守衛、改 `v7` 的 base），放寬不能建立在一個問不到答案的前提上。
    對本機開發者來說 exit 2 與「沒有這個檔」是同一個結果，只是會明講原因；而這支
    檢查器本來就每一節都在用 git，git 跑不動時它也走不完。
    """
    try:
        p = subprocess.run(["git", "ls-files", "--error-unmatch", "--", path],
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except OSError as e:
        _local_bad("%s 存在，但問不到它受不受版控（git 跑不動：%s）" % (path, e))
    if p.returncode == 0:      # 路徑規格符合 index 裡的某個檔＝受版控
        return True
    if p.returncode == 1:      # `--error-unmatch` 的「沒有符合的已知檔案」＝未追蹤
        return False
    _local_bad("%s 存在，但問不到它受不受版控（git ls-files exit %d）：%s"
               % (path, p.returncode, p.stderr.decode("utf-8", "replace").strip()))


def _read_local_conf(path):
    """讀 `.devflow-local`，回傳 {鍵: 值字串}。檔案不存在回傳 {}（CI 走的就是這條）。"""
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except FileNotFoundError:
        return {}
    except OSError as e:
        _local_bad("%s 存在卻讀不到：%s" % (path, e))
    # 檔案存在才問版控——CI 與煙霧測試沙箱在上面那個 return 就結束了，不多跑一個 git。
    if _local_tracked(path):
        _local_bad(
            "%s 受版控了，但它只能是本機未追蹤的檔" % path,
            "它決定的是 pin 守衛放不放行、`v7` 拿誰當 base。受版控之後這些就成了 PR",
            "內容改得動的東西，等於讓被檢查的人改判準（見本節開頭的註解）。",
            "解法：`git rm --cached %s`——檔案留在本機，只是退出版控。" % path)
    # `utf-8-sig`：編輯器自動加的 BOM 吃掉。不吃掉的話它會黏在第一行的鍵名前面，
    # 訊息就會指著一個開頭多了 U+FEFF 的鍵名說「認不得」，而人看到的是一個
    # 拼對了的鍵。
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        _local_bad("%s 的內容不是合法 UTF-8：%s" % (path, e))
    conf = {}
    for _no, _line in enumerate(text.splitlines(), 1):
        _s = _line.strip()
        if not _s or _s.startswith("#"):
            continue
        if "=" not in _s:
            _local_bad("%s 第 %d 行不是 `key = value`：%r" % (path, _no, _line))
        _k, _, _v = _s.partition("=")
        _k, _v = _k.strip(), _v.strip()
        if _k not in LOCAL_KEYS:
            _local_bad("%s 第 %d 行的鍵 %r 認不得（只收 %s）"
                       % (path, _no, _k, "／".join(sorted(LOCAL_KEYS))))
        if _k in conf:
            # 「後者勝」與「前者勝」都是猜，而兩者猜錯的方向不同：`allow_pin_drift = true`
            # 後面跟一行 `false`，靜默取後者會讓以為設好了的人撞 exit 2；反過來則是
            # 以為關掉了卻還在放行。同一個鍵寫兩次就是寫錯了，停在這裡。
            _local_bad("%s 第 %d 行的鍵 %s 重複了（前面已經設過）" % (path, _no, _k))
        _allowed = LOCAL_KEYS[_k]
        if _allowed is None:
            if not _v:
                _local_bad("%s 第 %d 行 %s 的值是空的" % (path, _no, _k))
        elif _v not in _allowed:
            _local_bad("%s 第 %d 行 %s 的值 %r 認不得（只收 %s）"
                       % (path, _no, _k, _v, "／".join(_allowed)))
        conf[_k] = _v
    return conf


LOCAL_CONF = _read_local_conf(LOCAL_FILE)

try:
    import yaml
    from markdown_it import MarkdownIt
    from markdown_it.rules_inline import html_inline as _md_html_inline
    import markdown_it
except ImportError as e:
    print("💥 檢查器無法執行：缺少相依模組 %s" % e.name)
    sys.exit(2)

# import 成功之後再驗一次**實際 import 到的**版本。
#
# `--check-pins` 讀的是 distribution metadata（`importlib.metadata.version`），那只說明
# 「裝了什麼」，不說明「import 到什麼」——兩者可以不一致（審查者 PR #93 第一輪實測：
# metadata 報 3.0.0／6.0.1、實際 import 4.0.0／6.0.3，`--check-pins` 與完整檢查器都 exit 0）。
# 路徑順序、同名套件、editable 安裝、殘留的舊 site-packages 都能造成這種落差。
#
# 這一段擋的是「CI 實際跑的 parser 不是 pin 的那一版」——README「Phase 1 第三出口」
# 條件一要的是正反兩個 run 跑同一份檢查器，parser 版本不同就只成立一半。
# exit 2 而非 1：檢查器是在**用一個沒被授權的 parser** 執行，那是無法執行，不是內容問題。
_RUNTIME = {"markdown-it-py": markdown_it.__version__, "PyYAML": yaml.__version__}
_drift = ["%s：import 到 %s，pin 是 %s" % (_d, _RUNTIME[_d], _v)
          for _d, _v in PINS if _RUNTIME.get(_d) != _v]
#
# 豁免的取得順序（issue #222）：環境變數 `DEVFLOW_ALLOW_PIN_DRIFT` ＞ `.devflow-local` 的
# `allow_pin_drift`。環境變數優先，因為它是「這一次執行的覆寫」、檔案是持久設定——
# 煙霧測試的沙箱靠的正是這個順序：它逐案設 `DEVFLOW_ALLOW_PIN_DRIFT=1`，沙箱裡沒有
# 設定檔也照樣放行（`git archive` 不含未追蹤的檔），所以 tests/ 不必跟著改。
# 設成 `1` 以外的非空值是明確的「不要放行」，覆寫檔案；**完全未設**才往下看檔案，
# CI 走的就是這條——檔案也讀不到時，判定與本段改動前逐字相同。
_pin_drift_env = os.environ.get("DEVFLOW_ALLOW_PIN_DRIFT", "")
if _pin_drift_env:
    _allow_drift = _pin_drift_env == "1"
else:
    _allow_drift = LOCAL_CONF.get("allow_pin_drift") == "true"
if _drift and not _allow_drift:
    print("💥 檢查器無法執行：實際 import 的相依版本不符 pin")
    for _line in _drift:
        print("    %s" % _line)
    # 這段話對著的是「剛從 main 新建 worktree 的實作位」：這個檔不受版控，`L2` 每開一個
    # worktree 就少一份，裸跑必撞這裡。訊息因此直接給可貼的內容，而不是只說「可以設」。
    # 印出來的兩行**不帶行末註解**：上面的 parser 只略過整行 `#`，行末的 `#` 會被當成
    # `v7_base` 的值的一部分，照抄下去等於給自己種一個解析不了的 ref。
    print("    本機開發：在 repo 根目錄放一個 %s，內容如下兩行" % LOCAL_FILE)
    print("    （第二行選填，放了本機的 `v7` 才是真的判定而不是略過）：")
    print("        allow_pin_drift = true")
    print("        v7_base = main")
    print("    這個檔不受版控（受版控會 exit 2），所以每個 worktree 都要自己放一份。")
    print("    （也可改設 DEVFLOW_ALLOW_PIN_DRIFT=1；CI 兩者都沒有）")
    sys.exit(2)

# ── 關卡開關 ──────────────────────────────────────────────────────
# True＝必需關卡（失敗就擋）；False＝建議（只報告）。
# 十六項裡十二項是 True，四項是 False。分界是定義域封不封閉，理由見檔頭。
# 驗證用：DEVFLOW_GATE_<KEY>=1 可單獨打開一項（GATES_NO_UPGRADE 列的例外除外），
# 環境變數只能加嚴不能放寬。
# 順序＝執行順序：`encoding` 在讀檔當下就判，排在最前面。
GATES = {
    "encoding": True,   # 受版控 .md 的內容是合法 UTF-8（issue #91）
    "d2":      True,    # D2 入口區塊 ≤30 行（第 13 節，永遠生效）
    "i1":      True,    # I1 head branch 名為 <N>-<slug>（第 1 節，永遠生效）
    "i5":      True,    # I5 devflow.yml 投影 implementer_filler 三方一致（第 1 節，永遠生效；spec AC-13）
    "version": True,    # V1 frontmatter version 四碼（第 3 節，ST1 起生效；issue #80）
    "fence":   True,    # fenced code block 未關閉（issue #80）
    "tables":  True,    # devflow.yml 指名的對照表都受版控（第 0 節，永遠生效；issue #87）
    "r2":      False,   # R2 同廠審查位的模型建議（issue #218；#221 補主 pin 的射程）
                        # 依裁決不升關卡：本項不走 report()，輸出是 ℹ️／⚠️ 兩級，
                        # 這個 False 只讓 tag() 印「建議」，見 GATES_NO_UPGRADE
    "table":   True,    # 對照表形狀，依 R9 分節（issue #80）
    "link":    True,    # 相對連結有效性（issue #80）
    "dupid":   True,    # 規則 ID 唯一定義（定義域＝節前綴判準；issue #96）
    "refs":    False,   # 規則 ID 無懸空引用（會誤擋非規則代號，見檔頭）
    "r9":      True,    # R9 對照表狀態欄三值（issue #94：64 格已換成條文原文）
    "v7":      True,    # V7 動到 devflow/** 須進位 devflow/VERSION（第 3 節，ST1 起生效；
                        # issue #150，定義域見檔頭「v7 為什麼可以是關卡」）
    "seatoblig": False,  # 職位檔的「規則義務」段 ↔ 該檔其餘段的引用雙向一致
                         # （issue #213；定義域封閉，首版為建議是因為正反測試未補）
    "orphan":  False,   # 規則本體的規則 ID 至少一個職位檔認領（issue #213；同上）
}
# 不接受環境變數升關卡的項目。`r2` 在這裡是因為 issue #218 的裁決逐字要求「檢查器維持
# 建議項不升關卡」——那是條文強度的決定（`R2` 的模型約束是建議），不是「正反測試還沒補」
# 的暫時狀態，所以不留 DEVFLOW_GATE_R2=1 這條升級路徑。本項的輸出另見該節。
GATES_NO_UPGRADE = ("r2",)
for _k in GATES:
    if _k in GATES_NO_UPGRADE:
        continue
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
# R2 的同廠模型建議（issue #218；射程於 issue #221 補上主審查位）的定義域：同一個檔案
# （devflow.yml）、六條固定路徑、兩次逐字比對——審查的兩個宣告位置（主 pin 與選填的
# fallback）各與實作位比一次。職位名與 `filler` 沿用上面那幾個常數，不另抄一份。
R2_IMPLEMENTER = "implementer"
R2_REVIEWER = "reviewer"
R2_FALLBACK = "fallback"
R2_MODEL = "model"
R2_IMPL_PATH = "%s.%s" % (TABLES_SEATS, R2_IMPLEMENTER)
R2_REVIEWER_PATH = "%s.%s" % (TABLES_SEATS, R2_REVIEWER)
R2_FALLBACK_PATH = "%s.%s" % (R2_REVIEWER_PATH, R2_FALLBACK)
# 兩個位置在輸出裡的稱呼。各則訊息都帶著它，兩則才分得出誰是誰。
R2_MAIN_LABEL = "審查位主 pin"
R2_FB_LABEL = "審查位 fallback"
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
# 規則家族前綴的基線。實際集合是「基線 ∪ WORKFLOW.md 的節標題宣告的家族」
# （issue #96 AC-2 的第一層；家族的來源見 RULE_SECTION_RE）：加新節自動納入，
# 整個家族被刪掉時基線仍擋得住懸空引用。
# 不另外併「現有定義的前綴」——依 AC-1 的判準，定義的前綴恆等於它所在節的家族，
# 那個集合是節家族的子集，併進來不會多出任何東西。
BASELINE_PREFIXES = {"I", "S", "V", "L", "R", "M", "F", "C", "G", "B", "ST", "P", "D"}
# 規則定義住哪一節：`## <數字>. <名>（<家族>）`，括號裡的字母就是該節定義的 ID 家族
# （issue #96 AC-1）。**抓形狀，不硬編碼 13 個節名**，日後新增節才不會漏。
# 不含括號字母的節（第 0 節「變數與基準」、附錄、索引）不產生任何定義。
# 半形括號一併收：同一個形狀換個寫法就讓整節的定義憑空消失，是沉默的漏認。
RULE_SECTION_RE = re.compile(r"[0-9]+\.\s+.+[（(]([A-Z]{1,4})[）)]")
# 只有這個層級的標題能開家族節：WORKFLOW.md 的 13 個規則節全是 `##`。
RULE_SECTION_DEPTH = 2
# 一律用 fullmatch，不用 match：Python 的 $ 會匹配「字串最後一個換行之前」，
# 所以 ^…$ ＋ match() 會讓 "0.0.2.0\n" 這種含換行的值矇混過關。
ID_RE = re.compile(r"([A-Z]{1,4})[0-9]+")
# 承載「字面文字」的 inline token 型別（issue #98）。dupid 的判準只問這一類 token
# ——「有沒有裸文字」——不問任何標記型別，所以**目前已啟用的 parser 規則**（下面 MD 的
# commonmark ＋ `table` ＋ `strikethrough`）底下，行內語法再多也不必補判準
# （見 leading_code_span 與 rule_definitions 的 docstring）。
# **這不是對任意外掛成立的封閉集合**：`footnote_ref`、`math_inline` 這類外掛直接產生
# 帶內容的 leaf token，型別不在這裡也不是 `*_open`／`*_close`，會被當成裝飾放行。
# 啟用新外掛時要重新核對它產出什麼 token，見檔頭 issue #98 那一節。
# `text_special`（跳脫與 HTML entity）實測在 3.0.0（CI pin）與 4.0.0（本機）都已被
# text_collapse 併回 `text`（`&#35211;` 到 children 裡是內容為「見」的 `text`，`\*` 是 `**`），
# 兩個都收是為了不依賴 parser 版本——沒併回時它一樣承載字面文字，不能當成標記放行。
TEXT_TOKENS = ("text", "text_special")

# V7 的定義域：一條 diff 路徑過濾、一個檔案、兩個 git 物件（merge-base 與 HEAD）。
# `V7` 原文排除的是 `devflow/VERSION` 自己——路徑過濾交給 git（`-- devflow/`），
# 排除交給 Python（逐字比對整條路徑），兩步都不做路徑正規化。
V7_DIR = "devflow/"
V7_VERSION_FILE = "devflow/VERSION"
# 本機／沙箱指定 base 的環境變數（issue #150 AC-2）。值是 sha 或任何 git 解析得了的 ref。
# 它**只能指定比較對象，不能放寬判定**：設了之後照樣算 merge-base、照樣比四碼。
# issue #222 起同一個事實多一個持久來源：`.devflow-local` 的 `v7_base`（見該節的順序）。
V7_BASE_ENV = "DEVFLOW_V7_BASE"

# seatoblig／orphan（issue #213）的定義域：四個已知檔、一個段落標題、一個正則，
# 加上一份**從 repo 讀出來**的豁免清單。四樣都是字面事實，沒有啟發式。
SEAT_DIR = "devflow/seats/"
SEAT_FILES = tuple(SEAT_DIR + n + ".md"
                   for n in ("coordinator", "implementer", "reviewer", "approver"))
SEAT_README = SEAT_DIR + "README.md"
# 段落標題逐字比對（四個職位檔都寫成這一行，`git grep -c '^## 規則義務' devflow/seats`
# 每檔恰一）。不套 section_name() 的寬鬆判讀：那是 R9 為了 `## **通用**` 開的口子，
# 這裡沒有那個需求，收緊反而讓定義域小一點。
SEAT_OBLIG_HEADING = "## 規則義務"
# 行內 `ID` 的字面形狀。**ID 的長相不另立第二份定義**——直接把 ID_RE 的 pattern
# 包一層反引號（同 v7 沿用安裝器 VERSION_RE 的理由）。group(1) 是完整 ID，
# group(2) 是家族前綴（來自 ID_RE 自己的括號）。
SEAT_ID_RE = re.compile("`(%s)`" % ID_RE.pattern)
# README 裡「刻意不分配」那句的辨識詞。豁免哪幾條是**規則決定**（現行那句寫的是
# 「`V1`、`V2`、`V3`、`V5`、`V6` 的行為人，四個職位檔都不分配」，其中前四條待 #63
# 裁定、`V6` 來源是 #214），機讀它而不是
# 把 ID 抄進本檔：抄進來等於檢查器自己發明豁免（見檔頭「不發明規則」）。
SEAT_EXEMPT_MARK = "不分配"

# 解析器：commonmark ＋ GitHub 也認得的兩個擴充。`table` 是對照表要用的；`strikethrough`
# 是 issue #98 補的——GitHub 算繪的是 GFM，`~~舊~~` 在讀者眼裡是刪除線**標記**，
# commonmark preset 卻把整段當字面文字，於是 `- ~~舊~~ `D1` …` 在 dupid 眼裡成了
# 「ID 前面有裸文字」而漏認。這是**解析器保真度**的落差，不是判準的窮舉問題：判準只問
# 「parser 看到的是文字還是標記」，parser 認得的語法愈接近 GitHub，兩邊看到的就愈一致。
# 現行受版控的 md 一個 `~~` 都沒有（`git grep -n '~~' -- '*.md'` 無輸出），所以這個改動
# 不改變任何一項在現行內容上的判定；升版後仍是 71 條定義、零重複。
# 另有一層**不改任何判定**的包裝：html_inline 規則多記一個原文位移（issue #100），
# 見 raw_html_chunks 前面那段。
MD = MarkdownIt("commonmark").enable(["table", "strikethrough"])
errors = []
advisories = []
# ⚠️ 警告：不建議的狀況；不取名 warnings 是為了不遮蔽同名的標準函式庫模組。
# ℹ️ 提示不收集——它每次執行都印（`r2` 的 INFO 依裁決如此），結尾再列一次沒有意義。
cautions = []


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


def info(msg, detail=()):
    """ℹ️ 提示：不是違規。不進 errors、不進 advisories，不影響 exit code。
    用在「條文是建議、而當下的狀態值得每次執行都說一聲」的項目——目前只有 `r2`
    （issue #218 的裁決：同廠不同模型「每次使用都 INFO 提示」）。"""
    print("  ℹ️ %s" % msg)
    for d in detail:
        print("       %s" % d)


def warn(msg, detail=()):
    """⚠️ 警告：不建議的狀況。同樣不進 errors、不影響 exit code，
    但收進 cautions，結尾再列一次，免得在長 log 裡被滑過去。"""
    cautions.append(msg)
    print("  ⚠️ %s" % msg)
    for d in detail:
        print("       %s" % d)


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


def section_families(tokens):
    """與 tokens 等長的清單：每個 token 所在的規則節家族（不在任何家族節下＝None）。

    節的範圍＝從帶家族標記的標題到下一個**同層或更淺**的標題為止；更深的子標題
    （`## 1. 不變層（I）` 下的 `### 細節`）仍在該節內——把子標題當成節結束會誤擋
    合法的結構（和 tables_of 取節範圍的道理相同）。

    只認**文件層級**的標題：blockquote／清單等容器裡的 `## 1. 不變層（I）` 是引用
    或舉例，不是這份檔案的分節（同 r9_sections；markdown-it 對容器內的 token
    設 level > 0）。

    **只有 h2 能開家族節**：`WORKFLOW.md` 的 13 個規則節全是 `##`，更深的同形標題
    （`### 3. 補充說明（R）`）是子節不是新家族——把它當家族節會讓子節裡的舉例被判
    成重複定義（審查者 PR #97 第一輪反例）。更深的標題照樣不關掉外層的節。
    """
    out = [None] * len(tokens)
    family = None
    family_depth = 0
    depth = None
    at_doc_level = False
    for i, t in enumerate(tokens):
        if t.type == "heading_open":
            # h1…h6；抓不出數字就當成最深，只會讓它不去關掉外層的節。
            depth = int(t.tag[1:]) if t.tag[1:].isdigit() else 99
            at_doc_level = (t.level == 0)
        elif t.type == "heading_close":
            depth = None
        elif depth is not None and t.type == "inline":
            lv, depth = depth, None
            if at_doc_level:
                m = RULE_SECTION_RE.fullmatch(t.content.strip())
                if m and lv == RULE_SECTION_DEPTH:
                    family, family_depth = m.group(1), lv
                elif family is not None and lv <= family_depth:
                    family = None
        out[i] = family
    return out


def container_stacks(children):
    """與 children 等長的清單：每個 token 當下的**容器堆疊快照**（tuple）。

    markdown-it 的 inline children 是扁平的 token 串，容器只以 `*_open`／`*_close`
    成對出現，沒有樹。這裡邊掃邊維護一個堆疊：遇 `*_open` 推入、遇 `*_close` 彈出，
    堆疊元素用**推入時的索引**當識別——所以兩個相鄰的 `strong` 是兩個不同的容器，
    不會因為深度相同就被當成同一個。開標記自己屬於外層（推入前記錄）、關標記也是
    （彈出後記錄），與 markdown-it 給 `level` 的規則一致。

    **為什麼不能用 `level`**（issue #98 第一輪審查，PR #99）：`level` 只是深度數字，
    **不帶容器身分**。容器關閉後深度會被重用，於是「已關閉的 sibling 容器內文」與
    「包住 ID 的另一個容器內文」碰巧同為 lv1，被誤判成「與 ID 同層的裸文字」——
    `- [裝飾](#x) **`D1`** …`、`- ~~舊~~ *`D1`* …` 兩種寫法因此**漏認**真定義，
    而 dupid 是必需關卡，那是可以拿來藏重複定義的繞過路徑。堆疊快照帶著身分，
    「同層或更外層」才問得準：見 leading_code_span 的前綴判準。

    不成對的 `*_close`（parser 正常不會產生）：每個 close 最多彈一格，且**不驗容器
    型別**；堆疊已空就是 no-op。不拋例外——判準不因畸形輸入而變成 exit 2。
    """
    out = []
    stack = []
    for i, c in enumerate(children):
        if c.type.endswith("_close"):
            if stack:
                stack.pop()
            out.append(tuple(stack))
        elif c.type.endswith("_open"):
            out.append(tuple(stack))
            stack.append(i)
        else:
            out.append(tuple(stack))
    return out


def leading_code_span(children):
    """一個 inline 開頭的 code span：第一個 `code_inline`，且它前面沒有裸文字。
    開頭不是 code span 就回 None（issue #98 AC-1）。

    **「裸文字」＝與這個 code span 同層或更外層的文字 token**（`TEXT_TOKENS`，內容
    非空白）。「同層或更外層」用 container_stacks() 的堆疊快照判，**不用深度數字**：
    前置文字 token 的容器路徑必須是 code span 容器路徑的**前綴**，才算同層（路徑相等）
    或更外層（路徑較短）。已關閉的 sibling 容器路徑的最後一格是別的容器實例，不成前綴，
    所以是裝飾不是裸文字。六個例子（實測見 issue #98 與 PR #99 第二輪）：

        - **`R3`** …              strong_open 前無文字                    → 是開頭
        - [看這裡](#x) `R3` …      「看這裡」(link) vs ID ()：不是前綴 → 裝飾 → 是開頭
        - [裝飾](#x) **`R3`** …    「裝飾」(link) vs ID (strong)：不是前綴 → 裝飾 → 是開頭
        - ~~舊~~ *`R3`* …          「舊」(s) vs ID (em)：不是前綴   → 裝飾    → 是開頭
        - **注意 `R3`** …          「注意 」(strong) vs ID (strong)：相等 → 裸文字 → 不是
        - 見 `I2` 與 `L3`          「見 」() vs ID ()：相等          → 裸文字 → 不是

    **為什麼不必窮舉標記型別**：舊寫法是「逐個跳過開標記」，跳過清單是開放集合——
    `link_close`、`image`、`~~` 都是這樣漏掉的（issue #98 的實測表，五種寫法四種漏認）。
    這裡改成問「有沒有文字」：在**目前已啟用的 parser 規則**（commonmark ＋ `table`
    ＋ `strikethrough`）下，承載字面 prose 的 token 型別就是 `TEXT_TOKENS` 那一小組，
    其餘型別一律不看，所以這些規則產生的行內語法不必逐一補判準。

    這個「不必窮舉」**只在上面那組規則之內成立**，不是對任意外掛自動成立：`footnote_ref`、
    `math_inline` 這類外掛直接產生**帶內容的 leaf token**，型別不在 `TEXT_TOKENS` 裡，
    於是被當成裝飾放行。啟用新外掛時要重新看它產出什麼 token，見檔頭「dupid 的
    『ID 是本項的開頭』為什麼不再窮舉」那一節。
    """
    stacks = container_stacks(children)
    for k, c in enumerate(children):
        if c.type != "code_inline":
            continue
        here = stacks[k]
        for j, prev in enumerate(children[:k]):
            # 前綴 ⇔ 同層（相等）或更外層（較短）；不成前綴＝在別的（已關閉的）容器裡。
            if (prev.type in TEXT_TOKENS and prev.content.strip()
                    and here[:len(stacks[j])] == stacks[j]):
                return None
        return c
    return None


def rule_definitions(tokens, lines):
    """規則 ID 的定義。三個條件同時成立才算（issue #96 AC-1，條件 3 的錨點由 #98 改寫）：

      1. 落在帶家族標記的節下（`## <數字>. <名>（<家族>）`，見 RULE_SECTION_RE）；
      2. ID 的字母前綴＝該節括號裡的家族；
      3. 本項的原始行以 `- ` 開頭——不縮排、不在 blockquote 裡、不是有序清單。

    三者擋掉的正是 dupid 以前「修不掉」的三個假陽性：附錄／索引那種節沒有家族標記
    （條件 1）、索引把別家族的 ID 列進來（條件 2）、「> - `I1` …」這種引述（條件 3）。

    再加上「ID 是本項的開頭」——由 leading_code_span() 判，**不窮舉要跳過哪些標記**：
    問的是「ID 前面有沒有裸文字」，不是「前面那個 token 是不是某種標記」；「同層或更外層」
    比的是**容器祖先路徑的前綴**，不是 `level` 深度數字（PR #99 第一輪：深度數字會讓
    已關閉的 sibling 容器內文冒充同層裸文字而漏認）。所以「- **`R3`** …」
    「- [](#a) `R3` …」「- [裝飾](#a) **`R3`** …」「- ~~舊~~ *`R3`* …」都算定義，而
    「- 見 `I2` 與 `L3`」「- 這條規則參考了 `R3` 的做法」不算（AC-3）。
    fenced code block 裡的示範不產生 list_item token，天然排除。

    「不必窮舉」的適用範圍限於**目前已啟用的 parser 規則**下的普通 prose token，不對任意
    外掛自動成立；已知的三類假陰性（含 GFM task-list）記在檔頭 issue #98 那一節。

    條件 3 看的是 **list_item_open 自己那一行**（`t.map[0]`），不是「ID 落在哪一行」：
    ID 前面既然可以有裝飾，裝飾裡就可以有換行（`- [](#a)` 換行後才寫 `` `D1` ``），
    那時 ID 所在的行是縮排的續行，拿它判行首會把一個真定義判掉——本項的行首寫法只有
    一個來源，就是本項的第一行。三個假陽性案例的第一行分別是附錄項、索引項、
    `> - …`，判定與 #96 相同。
    """
    families = section_families(tokens)
    out = []
    for i, t in enumerate(tokens):
        if t.type != "list_item_open" or families[i] is None or not t.map:
            continue
        if not lines[t.map[0]].startswith("- "):     # 條件 3
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
            first = leading_code_span(tj.children or [])
            if first is not None:
                content = first.content.strip()
                m = ID_RE.fullmatch(content)
                if m and m.group(1) == families[i]:
                    out.append((content,
                                locate(lines, t, "`%s`" % content) or t.map[0] + 1))
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


# ── raw HTML：`table`（issue #90）與 `link`（issue #100）共用的一套機制 ──────────
# 兩者問的是同一類問題——「parser 判成 HTML 的那些 token 裡，有沒有某種 start tag」——
# 只差在要哪種 tag、取它的什麼。所以「從 AST 取出 raw HTML」（raw_html_chunks）與
# 「在 raw HTML 裡找 start tag」（html_start_tags）各只有一份，兩個關卡各自只寫
# 自己的那一小段篩選。
#
# 找 start tag 用標準庫的 HTMLParser，不用正規式。
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
# 標籤名、屬性名它會轉成小寫，屬性值裡的 entity（`&amp;`）它會解開——三者都和瀏覽器
# 看到的一致，本檔不再另做。
class _StartTagFinder(HTMLParser):
    """raw HTML 裡每一個 start tag：(相對行號（1-based）, 標籤名, attrs)。

    `set_cdata_mode` 是 HTMLParser 的內部開關：碰到 `<script>`／`<style>` 後把後續
    內容當 raw text，裡面的標籤不再回報。但 **markdown 的 `<script>` 在 GitHub 上會
    被清掉、裡面的內容照樣渲染**——審查者 PR #92 第四輪實測 `<script>` 內的 table
    最終有渲染出來。受版控的 md 不該有 script/style，一律當成普通標籤繼續解析
    （連結同理：`<script>` 裡的 `<a href>` 也照樣會被找出來）。"""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.tags = []

    def set_cdata_mode(self, *args, **kwargs):   # noqa: N802（覆寫內部方法）
        pass

    def handle_starttag(self, tag, attrs):
        self.tags.append((self.getpos()[0], tag, attrs))

    handle_startendtag = handle_starttag


def html_start_tags(text):
    """text 裡的 start tag（見 _StartTagFinder）。解析拋例外就回 None——HTMLParser
    幾乎不拋，真拋了表示看不完這段 HTML，由呼叫端各自 fail closed。"""
    p = _StartTagFinder()
    try:
        p.feed(text)
        p.close()
    except Exception:
        return None
    return p.tags


def html_table_lines(text):
    """text 裡 `<table>` start tag 的相對行號（1-based，相對於 text 的第一行）。"""
    tags = html_start_tags(text)
    if tags is None:             # 看不完就當作有問題
        return [1]
    return [ln for ln, tag, _ in tags if tag == "table"]


# `srcset` 的值不是一個 URL，是「候選 URL ＋ descriptor」的串（issue #102）：
# `a.png 480w, b.png 800w`、`a.png 1x, b.png 2x`、`a.png`。切法照 HTML 規格的
# 「parse a srcset attribute」，**先按空白切出 URL、再處理其後的 descriptor**，不是
# split(",")——URL 本身可以含逗號（`a.png?x=1,2 480w`、`data:image/png;base64,…`），
# 按逗號切會把一個 URL 切成兩段、後一段根本不是 URL（兩個方向都錯：誤擋那一段，
# 也漏掉沒有空白的 `a.png,b.png`——規格裡那是**一個** URL，瀏覽器會照原樣去抓）。
#
# 只切，不判：descriptor 的內容不解析、不驗。規格裡 descriptor 不合法的候選會被瀏覽器
# 丟掉，本檔照樣驗它的 URL——只會更嚴，不會漏放（檔頭「link 的 raw HTML 連結」）。
# 空白是規格的 ASCII whitespace 五個字元，不是 str.isspace()：後者還含 NBSP、全形空白，
# 那些在 srcset 裡是 URL 的一部分。
_HTML_WS = "\t\n\f\r "


def srcset_urls(value):
    """srcset 屬性值裡每個候選的 URL 字串（原樣，不含 descriptor），依出現順序。"""
    out = []
    pos, n = 0, len(value)
    while True:
        # 規格的 splitting loop：跳過前導的空白與逗號。
        while pos < n and (value[pos] in _HTML_WS or value[pos] == ","):
            pos += 1
        if pos >= n:
            return out
        # 到下一個空白為止是 URL——逗號在這裡**不**斷開。
        start = pos
        while pos < n and value[pos] not in _HTML_WS:
            pos += 1
        url = value[start:pos]
        # URL 以逗號結尾（`a.png, b.png`）＝沒有 descriptor，剝掉結尾逗號就是 URL。
        if url.endswith(","):
            out.append(url.rstrip(","))
            continue
        out.append(url)
        # 否則其後到「括號外的下一個逗號」為止是 descriptor（規格的 descriptor
        # tokenizer；它的三個狀態裡，只有括號內的逗號不結束這個候選）。
        in_parens = False
        while pos < n:
            c = value[pos]
            pos += 1
            if in_parens:
                in_parens = c != ")"
            elif c == ",":
                break
            elif c == "(":
                in_parens = True


def _one_url(value):
    """值就是一個 URL 的屬性（href、src）。"""
    return [value]


# raw HTML 裡**承載連結**的東西（issue #100、#102）：(標籤名, 屬性名) → 怎麼從值切出 URL。
# 標籤名、屬性名都是 HTMLParser 轉過的小寫。判準是**列舉承載連結的屬性**，不是「遇到
# 某些標籤就特別處理」——不在這一組裡的 tag／屬性一律不看，在這一組裡的就依右邊的切法
# 取出一或多個 URL、交給 `link` 那一節的**同一個**判定迴圈（scheme／fragment、query、
# 路徑段、git ls-files 都只有那一份）。切法只切字串，不做任何判定。
#
# 這一組是**刻意的政策**，不是「所有 URL 型屬性」的推論結果。其餘的（`longdesc`、`cite`、
# `poster`、`<source src>`、`<object data>`、`style` 裡的 `url()`……）都不在，理由與擴充
# 方式見檔頭「link 的 raw HTML 連結」那一節。
HTML_LINK_ATTRS = {
    ("a", "href"): _one_url,
    ("img", "src"): _one_url,
    ("img", "srcset"): srcset_urls,
    ("source", "srcset"): srcset_urls,
}
# URL 的前處理，照 WHATWG URL 標準對屬性值做的那兩步：去掉前後的 C0 控制字元與空白、
# 刪掉所有 tab／換行。瀏覽器對 `href=" README.md "` 解析出的就是 `README.md`；不做的話
# 會把合法連結判成壞的（方向只有誤擋，不會漏放）。srcset 先切出候選、再對每個候選的
# URL 各做一次（規格就是這個順序）。除此之外不動值——percent-decode、切 query／fragment
# 都是那個共用迴圈的事，不在這裡做第二次。
_URL_EDGE = "".join(chr(c) for c in range(0x21))
_URL_TAB_NL = re.compile("[\t\n\r]")


def html_link_urls(text):
    """text 裡承載連結的屬性值：[(url, 相對行號)]。解析拋例外回 [(None, 1)]——
    看不完就不知道裡面有沒有壞連結，交給呼叫端當成一條判不了的連結擋下。
    行號是 start tag 的 `<` 所在行：同一個標籤切出的每個 URL 都報這一行。"""
    tags = html_start_tags(text)
    if tags is None:
        return [(None, 1)]
    out = []
    for ln, tag, attrs in tags:
        for name, value in attrs:
            split = HTML_LINK_ATTRS.get((tag, name))
            if split is None or value is None:
                continue
            for raw in split(value):
                url = _URL_TAB_NL.sub("", raw.strip(_URL_EDGE))
                if url:
                    out.append((url, ln))
    return out


# html_inline 的原文位移（issue #100）。inline 的 children 沒有 map，要知道一段行內
# HTML 落在第幾行，#92 的做法是把它前面兄弟 token 裡的換行加起來（softbreak／hardbreak
# 認型別、其餘數 content 裡的 `\n`）。但**有些換行不在任何 token 裡**，本地實測四種
# 寫法都少算一行：多行 code span（`code_inline` 的 content 已被 parser 把換行轉成空格）、
# 連結目的地前換行（`[a](⏎README.md)`）、連結 title 前換行、跨行的 reference label——
# 後三者的換行被 link token 吞掉，沒有任何 child 帶著它。`table` 的行號也因此錯過。
# 反推不回來，就問 parser 自己：html_inline 規則被呼叫時 `state.pos` 正指著那個 `<`，
# 而 state.src 就是這個 inline token 的 content（連結文字裡的 HTML 也在同一個 src 上
# 解析；圖片的 alt 另起一個 src，但 alt 是純文字屬性，不是 HTML，本來就不看）。
# 包一層把它記進 token.meta，規則本身的判定一字不改。
HTML_POS = "devflow_src_pos"


def _html_inline_with_pos(state, silent):
    pos = state.pos
    n = len(state.tokens)
    found = _md_html_inline(state, silent)
    if found and not silent:
        for tok in state.tokens[n:]:     # push 前可能先 flush 一個 pending 的 text
            if tok.type == "html_inline":
                tok.meta[HTML_POS] = pos
    return found


MD.inline.ruler.at("html_inline", _html_inline_with_pos)
# 包裝有沒有生效，啟動時就驗，不等內容裡剛好有行內 HTML：CI 跑的是 PINS 的
# markdown-it-py，本機常是別的版本，規則**完全沒註冊**（或 HTML_POS 寫成探針值以外的
# 東西）要在這裡以 exit 2 現形（壞掉的是檢查器自己），而不是讓行號悄悄錯掉。
#
# 這個探針**不是**完整的語意驗證，tests 也不是（PR #101 兩輪審查各以定點突變實測）：
# 固定寫成 4 → 探針通過、tests 抓到；把字元位移誤當 UTF-8 byte 位移 → **兩邊都沒抓到**，
# 行號在某些 CJK ＋跨行的組合上多算一行。已知的漏洞範圍寫在檔頭 issue #100 那一節，
# 不要把這裡讀成「錯的位移都會被擋下」。
_probe = [c for t in MD.parse("x\ny <b>") if t.type == "inline" for c in t.children]
if not any(c.type == "html_inline" and c.meta.get(HTML_POS) == 4 for c in _probe):
    die("markdown-it %s 的 html_inline 規則包裝沒有生效，raw HTML 的行號算不出來"
        % markdown_it.__version__)


def raw_html_chunks(tokens):
    """AST 裡 parser 判成 HTML 的每一段：(html, base)。html 的第 k 行（1-based）是原檔的
    第 base + k 行；token 沒帶 map 時 base 是 None。

    只認 parser 判成 HTML 的 token：區塊層的 html_block、行內的 html_inline（在 inline 的
    children 裡，容器內、表格格內、連結文字裡都算）。code fence／縮排 code block／code span
    的內容是 fence／code_block／code_inline token，天然排除——那是示範，不是資料。
    不解析 HTML 的內容語意：取出來交給 html_start_tags，其餘由呼叫端各自篩選。"""
    for t in tokens:
        if t.type == "html_block":
            yield t.content, (t.map[0] if t.map else None)
        elif t.type == "inline":
            # 同一個 inline token 的 html_inline children 是**同一段 HTML 被文字切開**
            # （`<div>` 文字 `</div>`），要串起來才解析得出跨 child 的標籤。
            #
            # 但**不能只串 HTML、把中間的換行丟掉**：丟掉後 parser 的相對行號就少算
            # （審查者 PR #92 第五輪：真實第 22 行報成 20）。每個 html_inline 之前補足
            # 換行，補到它在原文裡的那一行——行數由 parser 記下的位移（HTML_POS）算，
            # 不從兄弟 token 反推（反推漏掉的四種寫法見 HTML_POS 前面的註解）。
            kids = [c for c in t.children or [] if c.type == "html_inline"]
            if not kids:
                continue
            parts = []
            at = 0                        # parts 目前寫到第幾行（0-based）
            for c in kids:
                row = t.content.count("\n", 0, c.meta[HTML_POS])
                parts.append("\n" * (row - at))
                parts.append(c.content)
                at = row + c.content.count("\n")
            yield "".join(parts), (t.map[0] if t.map else None)


def raw_html_tables(tokens, lines):
    """AST 裡的 raw HTML `<table>` 所在行號（issue #90 缺口 2）。
    不解析 HTML 表的內容（表頭、欄位、狀態格都不看）：那會讓檢查器變成第二個 parser。"""
    out = []
    for html, base in raw_html_chunks(tokens):
        for rel in html_table_lines(html):
            out.append((base + rel) if base is not None else None)
    return out


def link_targets(tokens, env, lines):
    """行內連結、圖片、未被使用的 reference 定義，以及 raw HTML 裡承載連結的屬性
    （HTML_LINK_ATTRS，issue #100；srcset 切成候選 URL 各算一條，issue #102）。
    跨行、成對括號、角括號形式都由 parser 處理，不是我在猜。raw HTML 那一路的 target
    可能是 None：那段 HTML 解析不完。"""
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
    # raw HTML 的連結 AST 看不到（沒有 link_open／image token，issue #100 缺口 5）。
    # 這裡只負責**取出** URL，判定交給呼叫端那一個迴圈，不另寫一套。
    for html, base in raw_html_chunks(tokens):
        for url, rel in html_link_urls(html):
            out.append((url, (base + rel) if base is not None else None))
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
# 家族的來源是 WORKFLOW.md 的節標題（issue #96 AC-2 第一層），不是「現有定義的前綴」：
# 後者依 AC-1 的判準恆為前者的子集。基線仍保留——整個節被刪掉時還擋得住懸空引用。
prefixes = set(BASELINE_PREFIXES) | {f for f in section_families(rd["tokens"]) if f}
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
print("── R2：同廠審查位的模型（%s；主 pin 與 fallback 各判一次；依裁決不升關卡）" % tag("r2"))
# 定義域：一個檔案（devflow.yml）、六條固定路徑、兩次逐字比對——
#   `seats.implementer.filler`／`seats.implementer.model`（被審者，兩次比對共用）
#   `seats.reviewer.filler`／`seats.reviewer.model`（主 pin）
#   `seats.reviewer.fallback.filler`／`seats.reviewer.fallback.model`（選填的改派宣告）
# 節點樹沿用 i5 那一節 compose 出來的 i5_root（同一份 bytes、同一個 parser，不解析第三次）；
# 取鍵沿用 tables_get（同名鍵重複＝歧義、`<<` 依 YAML merge 語意展開），所以本項自己不碰 YAML，
# 也不會和 `i5`／`tables` 對同一份檔案給出兩套看法。
#
# 為什麼看兩個位置（issue #221）：`R2` 要防的是「審查者與被審者同廠同模型，只差 context」，
# 這個風險不分它來自主 pin 還是 fallback——直接把 `seats.reviewer` 設成與實作位同廠同模型，
# 風險完全相同。首版（issue #218）只判 fallback，於是 PR #216 那一輪協調者直接用與實作位
# 同廠同模型的工具審查（根本沒走 fallback 路徑）時，本項一聲不吭。條文的射程本來就涵蓋
# 「當次實際擔任審查的工具與模型」，改寫後寫明了（`R2`），本項跟著對兩個位置各判一次。
# 兩處**獨立判定**：主 pin 異廠、fallback 同廠同模型時，只對 fallback 出 ⚠️，不混成一條。
#
# 本項是**提示，不是關卡**。`R2` 的模型約束是建議（issue #218 的使用者裁決，2026-09-25：
# 「通用建議：條文寫明同廠 fallback 宜用不同模型，不強制；檢查器維持建議項不升關卡
# （配你已定的 INFO／WARNING 提示）」），所以它不走 report()、不進 errors、不吃
# DEVFLOW_GATE_R2=1（見 GATES_NO_UPGRADE），每個位置只印三種結果：
#   ℹ️ 該位同廠且兩邊的 `model` 不同 —— 合建議，仍**每次執行都印一行**。這是裁決的
#      字面要求：「如果使用同廠不同模型就簡單的 INFO 提示，每次使用都 INFO 提示」，
#      所以它不是「有問題才提」，訊息也就保持一行、不附 detail。
#   ⚠️ 該位同廠且兩邊的 `model` 相同 —— 裁決：「同廠同模型需要用 warning 提示，
#      要警告這個狀況是不建議的」。措辭到「不建議」為止，不說成違規。
#   ✅ 其餘都是「不適用」，不印成問題（檢查器不發明規則）。
#
# 幾個刻意不做的判定，逐條對著改寫後的 R2：
#   (1) `seats.reviewer.fallback` 不存在 → 該位不適用（主 pin 照判）。條文把它寫成「可寫在」
#       的選填宣告位置，要求它存在就是發明義務。
#   (2) 該位的 `filler` 與 `seats.implementer.filler` 不同 → 異廠，
#       條文的模型建議只在同廠時才給，不適用。
#   (3) 同廠但有一邊的 `model` 沒 pin → ℹ️「核不出來」，不是問題。改建議級後條文沒有
#       「兩位的 `model` 都須顯式 pin」這條義務；而未 pin 時實際用哪個模型取決於工具當次的
#       預設（devflow.yml 自己的註解就記著別名靜默漂移那次），機械上確實核不了——
#       核不了要說，但不能把「沒做非義務的事」報成問題。
#   (4) 結構或取值讀不出來（壞 YAML、鍵重複、值不是 !!str 純量）→ ℹ️「無從核對」並附原因。
#       同一份檔案的解析層與 `seats`／`seats.implementer` 的形狀另有 `i5`、`tables` 兩個
#       必需關卡把（見那兩節），本項不重複判，也不藉這條變成第三個把關的人。
#   (5) 條文明寫「同廠只有一個堪用模型時，全新 context 即滿足本條」，所以 ⚠️ 那一行的
#       處置文字照這句寫：換模型或換異廠是選項，沒有第二個堪用模型時不必勉強。
#   (6) 不判「主 pin 與 fallback 哪一個是那一輪實際生效的」——那是派工當下的事實，
#       檔案裡看不到。兩個位置各判各的，不互相遮蔽、也不合成一條結論。
#
# 本項看的是**pin 的形狀**，不是那一輪實際派了誰：派工發生在 repo 外，檢查器看不到。
# 條文（改寫後的 `R2`）說的是「當次實際擔任審查的工具與模型」，那個事實只有協調者知道；
# 本項能做的是把兩個宣告位置都攤開來，讓「照設定派工」的那條路上不會有同廠同模型沒人提醒。
# 設定之外臨場改派（PR #216 那次就是）仍然出了本項的定義域，是 `R2` 給人遵守的部分。


def r2_map(parent, where, key):
    """parent（已確認 !!map）裡 `key` 的值節點，要求是 !!map。
    缺鍵＝(None, None)，由呼叫端決定缺了算不算違規。"""
    node, bad = tables_get(parent, key, where)
    if bad or node is None:
        return None, bad
    if not is_plain_map(node):
        return None, ("%s 的 `%s` 的值不是 !!map 的 MappingNode：%s"
                      % (where, key, node_desc(node)))
    return node, None


def r2_str(parent, where, key):
    """parent 裡 `key` 的 !!str 純量值。缺鍵＝(None, None)。"""
    node, bad = tables_get(parent, key, where)
    if bad or node is None:
        return None, bad
    return i5_scalar(node, "%s 的 `%s`" % (where, key))


def r2_unreadable(what, why):
    """讀不出形狀時的 ℹ️。what 是這一則涵蓋的位置，why 是一或多條原因，照原文附在下面。"""
    return "info", ("%s 的%s讀不出形狀，本項無從核對（解析層與 `%s` 的形狀另由 `i5`、"
                    "`tables` 兩個必需關卡把守）"
                    % (I5_FILE, what, TABLES_SEATS)), why


def r2_one(label, path, node, impl_filler, impl_model, impl_model_bad):
    """判一個審查位置（主 pin 或 fallback）：與實作位同廠時才比 `model`。
    回傳 (級別, 訊息, detail)，級別是 `ok`／`info`／`warn` 三值之一。

    兩個位置各呼叫一次、各出一則：同廠與否、model 相不相同，都是該位置自己的事實，
    不互相遮蔽也不合成一條結論（issue #221）。被審者那一邊（impl_*）兩則共用。"""
    what = "%s（`%s`）" % (label, path)
    where = "`%s`" % path
    where_impl = "`%s`" % R2_IMPL_PATH
    unreadable = []
    filler, bad = r2_str(node, where, TABLES_FILLER)
    if bad:
        unreadable.append(bad)
    elif filler is None:
        unreadable.append("%s 缺 `%s`：分不出這一位是同廠還是異廠" % (where, TABLES_FILLER))
    if unreadable:
        return r2_unreadable(what, unreadable)
    if filler != impl_filler:
        return "ok", ("%s：%s 的 `%s` ＝ %r 與實作位的 %r 異廠，R2 的模型建議不適用"
                      % (I5_FILE, label, path + "." + TABLES_FILLER,
                         filler, impl_filler)), ()
    same = "同廠（`%s` 皆為 %r）" % (TABLES_FILLER, filler)
    # 沒寫（missing）與寫了但讀不出來（unreadable）分開收：兩者都讓本項核不出模型是否相同，
    # 但只有前者要附「選填、不 pin 不違反 R2」那句——鍵重複的情形 pin 是寫了的，兩次。
    missing = []
    model, bad = r2_str(node, where, R2_MODEL)
    if bad:
        unreadable.append(bad)
    elif model is None:
        missing.append("%s 沒有 `%s`" % (where, R2_MODEL))
    if impl_model_bad:
        unreadable.append(impl_model_bad)
    elif impl_model is None:
        missing.append("%s 沒有 `%s`" % (where_impl, R2_MODEL))
    if unreadable or missing:
        # 沒 pin 不是違規（條文沒有這條義務），但沒 pin 就核不出模型是否相同——說核不出來。
        return "info", ("%s：%s與實作位%s，但 `%s` 沒有兩邊都讀得出來，"
                        "核不出模型是否相同" % (I5_FILE, what, same, R2_MODEL)), (
            unreadable + missing
            + (["`%s` 是選填，不 pin 不違反 R2；要讓本項核得出來才需要兩邊都寫明" % R2_MODEL]
               if missing else []))
    if model == impl_model:
        return "warn", ("%s 的%s與實作位%s又同模型（`%s` 皆為 %r）："
                        "只差 context，這個狀況不建議"
                        % (I5_FILE, what, same, R2_MODEL, model)), [
            "`%s` 與 `%s` 都是 %r" % (path + "." + R2_MODEL,
                                      R2_IMPL_PATH + "." + R2_MODEL, model),
            "R2 建議同廠時所用模型與實作位不同：可換成同廠的另一個模型，或改派異廠的工具；"
            "同廠只有一個堪用模型時，依條文全新 context 即滿足 R2"]
    return "info", ("%s：%s與實作位%s，模型 %r ≠ %r，合 R2 的建議"
                    % (I5_FILE, what, same, model, impl_model)), ()


def r2_check():
    """回傳一或多則 (級別, 訊息, detail)：主 pin 與 fallback 各一則，順序固定。

    本項只有這三種級別，不走 report()——`R2` 的模型約束是建議，依裁決不升關卡。
    讀不出來的東西若是兩則共用的（YAML 根、`seats`、實作位），就只出一則合併的 ℹ️。"""
    both = "審查位（`%s` 與 `%s`）" % (R2_REVIEWER_PATH, R2_FALLBACK_PATH)
    if i5_root is None:
        return [r2_unreadable(both, list(yml_parse_problems))]
    if not is_plain_map(i5_root):
        return [r2_unreadable(both, ["根不是 !!map 的 MappingNode：%s" % node_desc(i5_root)])]
    seats, bad = r2_map(i5_root, "根", TABLES_SEATS)
    if not bad and seats is None:
        bad = "缺 `%s`（第 0 節的自變數）" % TABLES_SEATS
    if bad:
        return [r2_unreadable(both, [bad])]
    where_seats = "`%s`" % TABLES_SEATS
    reviewer, bad = r2_map(seats, where_seats, R2_REVIEWER)
    if bad:
        return [r2_unreadable(both, [bad])]
    if reviewer is None:
        return [("ok", "%s 沒有 `%s`：沒有審查位可判" % (I5_FILE, R2_REVIEWER_PATH), ())]
    # fallback 是選填（判定 (1)）：沒宣告就只出「不適用」那一則，主 pin 照判。
    fallback, bad = r2_map(reviewer, "`%s`" % R2_REVIEWER_PATH, R2_FALLBACK)
    if bad:
        fb_out = r2_unreadable("%s（`%s`）" % (R2_FB_LABEL, R2_FALLBACK_PATH), [bad])
    elif fallback is None:
        fb_out = ("ok", "%s 沒有 `%s`：未宣告 fallback（選填），R2 的模型建議不適用"
                  % (I5_FILE, R2_FALLBACK_PATH), ())
    else:
        fb_out = None           # 宣告了，下面和主 pin 走同一套判定
    # 被審者那一邊：兩則共用，讀不出來就兩則都判不了，合成一則。
    implementer, bad = r2_map(seats, where_seats, R2_IMPLEMENTER)
    if not bad and implementer is None:
        bad = "缺 `%s`：沒有實作位可比，判不出審查位是不是同廠" % R2_IMPL_PATH
    if bad:
        return [r2_unreadable(both, [bad])]
    where_impl = "`%s`" % R2_IMPL_PATH
    impl_filler, bad = r2_str(implementer, where_impl, TABLES_FILLER)
    if not bad and impl_filler is None:
        bad = "%s 缺 `%s`：沒有可比的實作位廠牌" % (where_impl, TABLES_FILLER)
    if bad:
        return [r2_unreadable(both, [bad])]
    # 實作位的 `model` 讀不讀得出來，只有同廠的位置才用得上，所以不在這裡就地判，
    # 原樣交給 r2_one——異廠的那一則不該因為被審者沒 pin model 就改口。
    impl_model, impl_model_bad = r2_str(implementer, where_impl, R2_MODEL)
    out = [r2_one(R2_MAIN_LABEL, R2_REVIEWER_PATH, reviewer,
                  impl_filler, impl_model, impl_model_bad)]
    out.append(fb_out if fb_out is not None
               else r2_one(R2_FB_LABEL, R2_FALLBACK_PATH, fallback,
                           impl_filler, impl_model, impl_model_bad))
    return out


for _r2_level, _r2_msg, _r2_detail in r2_check():
    if _r2_level == "warn":
        warn(_r2_msg, _r2_detail)
    elif _r2_level == "info":
        info(_r2_msg, _r2_detail)
    else:
        ok(_r2_msg)

print()
print("── 對照表的形狀（%s）" % tag("table"))
# 定義域：TABLE_DIRS 的直屬 .md（見上面 table_files）。每條斷言都是
# 「檢查器沒看懂這個檔案」的絆線，所以 fail closed——沒看懂就報，不靜默放行。
#
# 判準逐條對著 R9 的分節條文（issue #80 AC-1）：
#   (1) 每張表的表頭要含 `面向`／`值`／`狀態`，且「狀態」恰一欄（多一欄就判不出
#       哪欄是狀態，R9 的三值無從檢查；這是狀態欄檢查的前提，不是額外的規定）。
#   (2) 表數不限。R9 說「對照表得分為通用節與本機節」，但**沒有規定一個節內
#       可以有幾張表**——現行分布是八個對照表檔各 1 張（#135 之後；本節寫成時是
#       forges／coders 各 2 張），「剛好一張」「剛好兩張」都是在發明規則。判準不依賴
#       現行分布，條文未規定的不假設（issue #80 已提報；註解由 issue #150 AC-5 更新）。
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
        # raw HTML 解析不完（html_link_urls 的 None）：裡面有沒有壞連結無從判定，fail closed。
        if target is None:
            broken.append("%s:%s 的 raw HTML 解析不完，其中的連結無從判定" % (f, line))
            continue
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
    ok("%d 條相對連結（含 reference 定義、圖片、raw HTML 的 %s）都指得到"
       % (nlink, "／".join("<%s %s>" % p for p in sorted(HTML_LINK_ATTRS))))

print()
print("── R9：對照表狀態欄取三值之一（%s）" % tag("r9"))
# issue #94 把七個對照表檔 64 格的狀態欄換成 R9 的三值原文（使用者 2026-09-19 裁決
# 採方向 A：改內容、條文不動），遷移完成，GATES["r9"] 隨之升為 True，理由見檔頭
# 「r9 為什麼可以是關卡」。本項**刻意限縮定義域**：只判狀態格取不取三值之一，不驗
# `✅` 是否真的附了驗證方式與受測環境——後者由 `R9`／`R10` 條文要求，條件本身已夠
# 具體（#13 於 2026-09-15 關閉，結論是 `R8` 改前瞻讀法後困境已解消），但完整的機械
# 覆蓋留在母單 #22，不在本項。
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
# 定義域只有**狀態欄**：`R9` 管的是「狀態欄取三值之一」，沒有規定散文怎麼寫。
# 掃表格外的敘述句會擋掉合法內容——討論用詞沿革、引用舊格式、寫給讀者的遷移說明，
# 都會提到舊詞（審查者 PR #95 第一輪反例）。那是 required gate 的假陽性。
if r9_clean:
    ok("對照表狀態欄全部合 R9"
       + ("" if GATES["r9"] else
          " —— 可把 GATES[\"r9\"] 改成 True 升為必需關卡（前提見 README 第三出口的判定方式）"))

print()
print("── V7：devflow/** 改動須進位 kit VERSION（%s）" % tag("v7"))
# 判定逐條照 `V7` 第一句，理由見檔頭「v7 為什麼可以是關卡」。
#
# **「版本」的定義只有一份**：直接用安裝器的 VERSION_RE（kit-install 規格「名詞定義」：
# 四碼十進位非負整數、除單獨的 0 外無前導零、恰一個 `\n`、無 BOM，整檔 bytes fullmatch）。
# 不另寫一份——同 `i5` 不另寫一份 AC-7 判定的理由。installer 在 `i5` 那一節已經載好。
V7_VERSION_RE = getattr(installer, "VERSION_RE", None)
if V7_VERSION_RE is None:
    die("%s 沒有 VERSION_RE，V7 沒有「版本」定義的來源" % I5_INSTALLER)


def v7_git(args):
    """跑一個 git 指令，回傳 (returncode, stdout bytes, stderr 文字)。

    **不自己決定失敗是 die 還是 ❌**：兩者在本項都有——git 跑不動、base 解析不了
    （淺 clone 拿不到 base 分支的歷史）是檢查器無法執行（exit 2）；某一端讀不到
    `devflow/VERSION` 是被檢查的內容有問題（❌）。呼叫端各自分類。"""
    p = subprocess.run(["git"] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout, p.stderr.decode("utf-8", "replace").strip()


def v7_version(rev, side):
    """讀 `<rev>:devflow/VERSION` 的 bytes，回傳 (四碼元組, 顯示字串, 說明或 None)。

    物件不存在（那一端根本沒有這個檔）與內容不合「版本」定義，都是**輸入錯**——
    ❌ 而不是 exit 2。檢查器執行得好好的，是被比較的兩個 commit 裡有一個放了
    判不了的東西（同 `encoding` 的分類：內容壞不是檢查器壞）。"""
    where = side if rev == side else "%s（%s）" % (side, rev)
    rc, raw, err = v7_git(["show", "%s:%s" % (rev, V7_VERSION_FILE)])
    if rc != 0:
        return None, None, ("%s 讀不到 %s：%s" % (where, V7_VERSION_FILE, err))
    m = V7_VERSION_RE.fullmatch(raw)
    if m is None:
        return None, None, (
            "%s 的 %s 不合 kit-install 規格的「版本」定義"
            "（四碼 a.b.c.d、除單獨的 0 外無前導零、恰一個換行、無 BOM）：%r"
            % (where, V7_VERSION_FILE, raw))
    return tuple(int(g) for g in m.groups()), raw.decode("ascii").rstrip("\n"), None


# base 的取得順序：`DEVFLOW_V7_BASE`（一次性覆寫，煙霧測試沙箱走這條）＞ `.devflow-local`
# 的 `v7_base`（本機持久設定，issue #222）＞ CI 的 `origin/<GITHUB_BASE_REF>`。三者的值都是
# sha 或任何 git 解析得了的 ref，也都**只能指定比較對象，不能放寬判定**。
# 三個都沒有時與 `i1` 同款：`pull_request` 事件卻取不到就 die（略過會讓關卡靜默失效），
# 非 `pull_request` 就略過並印明。event_name 是 `i1` 那一節取的同一個事實，不重取。
#
# `v7_base` 可以是**持久設定**，是因為它在本機其實不是每次執行的參數：本機分支要合進哪裡
# 是固定的，寫 `v7_base = main` 就算 `merge-base main HEAD`，與 CI 對 PR base 做的事同型，
# 一次寫定之後每個任務都適用（`V7` 要的「這個 PR 有沒有進位」本來就是對著 merge-base 問，
# 見下面那段）。沙箱那條仍走環境變數：它比的是沙箱自己的 HEAD，那才是真的逐次不同。
v7_base_env = os.environ.get(V7_BASE_ENV, "").strip()
v7_base_conf = LOCAL_CONF.get("v7_base", "").strip()
v7_base_ref = os.environ.get("GITHUB_BASE_REF", "").strip()
if v7_base_env:
    v7_base, v7_base_from = v7_base_env, V7_BASE_ENV
elif v7_base_conf:
    v7_base, v7_base_from = v7_base_conf, "%s 的 v7_base" % LOCAL_FILE
elif v7_base_ref:
    v7_base, v7_base_from = "origin/%s" % v7_base_ref, "GITHUB_BASE_REF"
else:
    v7_base = v7_base_from = None

if v7_base is None:
    if event_name == "pull_request":
        die("pull_request 事件卻取不到 base（%s 與 GITHUB_BASE_REF 都沒有），V7 沒有比較對象"
            % V7_BASE_ENV)
    print("  ⏭️ 非 pull_request 執行（event=%s），取不到 base，略過"
          % (event_name or "本機"))
else:
    # 兩個 git 物件是 merge-base 與 HEAD，**不是 base tip 與 HEAD**：changed 由
    # `<merge-base>..HEAD` 算，版本就得和同一個起點比，否則「這個 PR 有沒有進位」會
    # 被 base 分支上別人的進位影響。`V7` 第二句（多張 PR 平行時以 main 當時的值重新進位）
    # 明文不在本項範圍（issue #150「不在範圍」），由合併衝突處理。
    # CI 上兩者其實重合：`pull_request` 跑的是 GitHub 生成的 merge commit，base tip 是它的
    # 父，merge-base 就等於 base tip；差別只在本機拿舊分支跑的時候看得到。
    rc, out, err = v7_git(["merge-base", v7_base, "HEAD"])
    if rc != 0:
        die("git merge-base %s HEAD 失敗（exit %d）：%s；"
            "CI 上多半是 checkout 深度不足（見 .github/workflows/devflow-checks.yml 的 fetch-depth）"
            % (v7_base, rc, err))
    v7_mb = out.decode("utf-8", "replace").strip()
    # `-z` 而不是預設輸出：git 對含空白／非 ASCII 的路徑會加引號並跳脫，那會讓
    # 「排除 devflow/VERSION」的逐字比對對不上（同 tracked() 用 -z 的理由）。
    rc, out, err = v7_git(["diff", "--name-only", "-z", "%s..HEAD" % v7_mb, "--", V7_DIR])
    if rc != 0:
        die("git diff %s..HEAD 失敗（exit %d）：%s" % (v7_mb, rc, err))
    v7_changed = [n for n in out.decode("utf-8", "replace").split("\0")
                  if n and n != V7_VERSION_FILE]
    if not v7_changed:
        ok("%s..HEAD 沒有動到 %s（%s 自己除外），V7 不觸發（base＝%s，取自 %s）"
           % (v7_mb[:12], V7_DIR, V7_VERSION_FILE, v7_base, v7_base_from))
    else:
        v7_base_ver, v7_base_str, v7_base_bad = v7_version(v7_mb, "base")
        v7_head_ver, v7_head_str, v7_head_bad = v7_version("HEAD", "HEAD")
        v7_detail = ["變更：%s" % n for n in v7_changed]
        v7_bad = [b for b in (v7_base_bad, v7_head_bad) if b]
        if v7_bad:
            # 一條 ❌ 不是兩條：兩端都壞掉時問題仍然只有一個——「判不出有沒有進位」。
            report("v7", "%s 動了 %d 個檔，但兩端的 %s 至少有一端判不了，無法判斷有沒有進位"
                   % (V7_DIR, len(v7_changed), V7_VERSION_FILE),
                   v7_bad + ["base＝%s（%s，取自 %s）" % (v7_mb, v7_base, v7_base_from)]
                   + v7_detail)
        elif v7_head_ver > v7_base_ver:
            ok("%s 動了 %d 個檔，%s 已進位 %s → %s"
               % (V7_DIR, len(v7_changed), V7_VERSION_FILE, v7_base_str, v7_head_str))
        else:
            report("v7", "動到 %s 卻沒有進位 %s：base %s → HEAD %s"
                   % (V7_DIR, V7_VERSION_FILE, v7_base_str, v7_head_str),
                   ["V7：PR 動到 devflow/**（devflow/VERSION 自身除外）時，"
                    "同一 PR 須使 devflow/VERSION 進位",
                    "位數（a／b／c／d）依 V1／V2 由人判，本項只判有沒有進位",
                    "base＝%s（%s，取自 %s）" % (v7_mb, v7_base, v7_base_from)]
                   + v7_detail)

print()
print("── seat 規則義務段 ↔ 同檔其餘段的引用雙向一致（%s）" % tag("seatoblig"))
# 定義域封閉在三個字面事實上：**四個已知檔**（SEAT_FILES）、**一個段落標題**
# （SEAT_OBLIG_HEADING，逐字比對）、**一個正則**（SEAT_ID_RE，由 ID_RE 包一層反引號
# 而成）。判定只有集合差，沒有啟發式、沒有門檻、沒有「意圖」的猜測。
#
# 逐行找標題而不走 markdown-it：本項要的是**段的行範圍**（要把該段從全文裡扣掉再比），
# 那是行的事實不是 token 的事實；四個職位檔一個 code fence 都沒有
# （`git grep -c '```' devflow/seats` 全零，且上面 `fence` 那一項在驗每個 md 的 fence 成對），
# 所以「行首是 `## `」不可能落在程式碼區塊裡。同 d2 逐行找標記的理由，見那一節。
#
# 兩個方向都是缺陷，各報各的：
#   * cited - listed：其餘段引了、義務段沒列 → 義務清單不完整。
#   * listed - cited：義務段列了、其餘段沒有對應條文 → 職責條文缺漏。
# 後者正是本項的來由（issue #213）：`29316c1`（#194 AC-11）只補了 coordinator 義務段的
# `R12`，職責段沒有對應條文，六輪讀審＋一輪審查都沒抓到。
#
# 首版是**建議**：定義域封閉，但升關卡的前提是 README「Phase 1 第三出口的判定方式」
# （正反兩個 run、同一份 blob、exit 1 只能由目標項造成），那組測試還沒補，由 #213 的後續單處理。
def seat_oblig_span(lines):
    """`## 規則義務` 的 (標題行索引, 段結束索引)：段內容是 lines[head + 1:end]，
    `end` 是其後第一個 `## ` 開頭的行索引，沒有就是檔尾。找不到標題回 None。

    標題行自己不屬於任何一側——它既不是義務清單的內容，也不該讓「規則義務」四個字
    出現在另一側。四個職位檔各恰一個這樣的標題，取第一個。"""
    head = None
    for i, line in enumerate(lines):
        if line.rstrip() == SEAT_OBLIG_HEADING:
            head = i
            break
    if head is None:
        return None
    for j in range(head + 1, len(lines)):
        if lines[j].startswith("## "):
            return head, j
    return head, len(lines)


def seat_ids(lines):
    """一段行文字裡出現的規則 ID 集合。"""
    return {m.group(1) for m in SEAT_ID_RE.finditer("\n".join(lines))}


def seat_id_line(lines, lo, hi, rid):
    """`rid` 在 lines[lo:hi] 裡第一次出現的行號（1-based）；找不到回 None。"""
    for i in range(lo, hi):
        if "`%s`" % rid in lines[i]:
            return i + 1
    return None


seat_claimed = {}
seatoblig_clean = True
for f in SEAT_FILES:
    if f not in docs:
        # 受版控的職位檔少一個＝定義域與 repo 佈局脫節。不 die()：這是被檢查的**內容**
        # 與假設不符，和 dupid「找不到任何規則定義」同一種分類。
        seatoblig_clean = False
        report("seatoblig", "%s 不在受版控的 md 裡，本項的定義域與 repo 佈局脫節" % f)
        continue
    seat_lines = docs[f]["lines"]
    span = seat_oblig_span(seat_lines)
    if span is None:
        seatoblig_clean = False
        report("seatoblig", "%s 沒有「%s」段，列不出它的規則義務"
               % (f, SEAT_OBLIG_HEADING))
        continue
    seat_head, seat_end = span
    listed = seat_ids(seat_lines[seat_head + 1:seat_end])
    cited = seat_ids(seat_lines[:seat_head] + seat_lines[seat_end:])
    seat_claimed[f] = listed
    if not listed:
        seatoblig_clean = False
        report("seatoblig", "%s 的「%s」段沒有任何規則 ID"
               % (f, SEAT_OBLIG_HEADING))
    missing = sorted(cited - listed)
    if missing:
        seatoblig_clean = False
        report("seatoblig",
               "%s：其餘段引用了 %d 個 ID，「%s」段漏列" % (f, len(missing), SEAT_OBLIG_HEADING),
               ["%s:%s 引用了 `%s`，義務段沒有它"
                % (f, seat_id_line(seat_lines, 0, seat_head, rid)
                   or seat_id_line(seat_lines, seat_end, len(seat_lines), rid), rid)
                for rid in missing])
    extra = sorted(listed - cited)
    if extra:
        seatoblig_clean = False
        report("seatoblig",
               "%s：「%s」段列了 %d 個 ID，職責／禁止／能力等其餘段沒有對應條文"
               % (f, SEAT_OBLIG_HEADING, len(extra)),
               ["%s:%s 義務段列了 `%s`，其餘段找不到它"
                % (f, seat_id_line(seat_lines, seat_head + 1, seat_end, rid), rid)
                for rid in extra])
if seatoblig_clean:
    ok("%d 個職位檔的「%s」段與同檔其餘段雙向一致（共 %d 個相異 ID）"
       % (len(SEAT_FILES), SEAT_OBLIG_HEADING,
          len(set().union(*seat_claimed.values()) if seat_claimed else set())))

print()
print("── 規則 ID 至少有一個 seat 認領（%s）" % tag("orphan"))
# 定義域的三段都是**已經在別處機讀出來的事實**，本項一個都不自己發明：
#   * 定義：上面 `dupid` 算好的 defined（rule_definitions 的三條件判準，issue #96／#98）。
#     不另寫一份「什麼算定義」——同 v7 沿用安裝器 VERSION_RE 的理由。
#   * 認領：上一項算好的 seat_claimed（四個職位檔「規則義務」段的聯集）。
#   * 豁免：**從 devflow/seats/README.md 機讀**——取含「不分配」的行裡的 `ID`。
#     豁免哪幾條是規則決定（現行那句是 `V1`／`V2`／`V3`／`V5`／`V6` 都不分配，
#     其中前四條待 #63 裁定、`V6` 來源是 #214），
#     把 ID 寫死在本檔等於檢查器發明規則（見檔頭「不發明規則」）。README 改了豁免範圍，
#     本項跟著改；改的人不必同時想到還要來動檢查器——那正是本項要消掉的那種漏改。
#
# 少了誰就報誰，不猜處置：報出來的 ID 可能該補進某個職位檔的義務段，也可能該併進
# README 的豁免句，兩條路都改的是**規則**，由人裁決（現況的 `V6`／`V7` 已開子單）。
#
# 首版是建議，理由同上一項：定義域封閉，正反測試未補。
orphan_exempt = set()
orphan_exempt_where = []
if SEAT_README not in docs:
    report("orphan", "%s 不在受版控的 md 裡，讀不到豁免清單（本項以「沒有豁免」往下判）"
           % SEAT_README)
else:
    for n, line in enumerate(docs[SEAT_README]["lines"], 1):
        if SEAT_EXEMPT_MARK not in line:
            continue
        ids = {m.group(1) for m in SEAT_ID_RE.finditer(line)}
        if ids:
            orphan_exempt |= ids
            orphan_exempt_where.append("%s:%d" % (SEAT_README, n))
orphan_claimed = set().union(*seat_claimed.values()) if seat_claimed else set()
orphans = sorted(set(defined) - orphan_claimed - orphan_exempt)
orphan_src = ("讀自 %s" % "、".join(orphan_exempt_where)) if orphan_exempt_where \
    else "%s 裡沒有含「%s」的豁免句" % (SEAT_README, SEAT_EXEMPT_MARK)
if orphans:
    report("orphan", "%d 個規則 ID 沒有任何職位檔認領，也不在 %s 的豁免句裡"
           % (len(orphans), SEAT_README),
           ["%s:%s 定義了 `%s`" % (RULES_FILE, defined[rid][0], rid) for rid in orphans]
           + ["豁免清單（%s）：%s"
              % (orphan_src, "、".join("`%s`" % r for r in sorted(orphan_exempt)) or "（空）")])
else:
    ok("%d 條規則 ID 都有職位檔認領或在豁免句裡（認領 %d、豁免 %d，%s）"
       % (len(defined), len(orphan_claimed & set(defined)), len(orphan_exempt), orphan_src))

print()
if cautions:
    print("===== 警告（%d 項）：不建議的狀況，不影響本次結果 =====" % len(cautions))
    for m in cautions:
        print("  ⚠️ %s" % m)
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
