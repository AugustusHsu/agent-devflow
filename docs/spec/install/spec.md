---
version: 0.0.0.0
---

# install：把入口區塊安全插入其他專案的 CLAUDE.md／AGENTS.md

<!-- 依 WORKFLOW.md S1。stage 1 下第 2 節不生效，本檔為 Phase 2 首單的 T 基準（草稿）。-->

## 目標與範圍

給 agent-devflow 一個安裝器，把 `devflow/templates/entry-block.md` 的入口區塊插入**目標專案**既有的 `CLAUDE.md`／`AGENTS.md`，遵守 `D2`：區塊外的專案內容逐 byte 不變；重跑冪等；碰撞情況報錯且**不寫任何檔**。

**形式**：`devflow/install.py`，Python 3 stdlib only，`python3 devflow/install.py <目標 repo 路徑> [--dry-run]`。

**只做入口區塊**：不複製 `devflow/` 目錄、不建 `devflow.yml`（既有者只讀頂層 `implementer_filler` 鍵——`seats.implementer.filler` 的投影，見 AC-7、AC-13）、不碰 `.gitignore`、不 commit。完整安裝／升級／回復是 Phase 4，本檔不定義其範圍。

**名詞定義**（全文適用）：
- **模板**：`devflow/templates/entry-block.md` 的完整 bytes，以 `<!-- devflow:begin -->` 行起、`<!-- devflow:end -->` 行止，含兩標記行；正規化為 LF、無 BOM、尾端恰一個 `\n`
- **標記行**：檔案 bytes 以 `\n` 切行、每行以 UTF-8 解碼（`errors="replace"`）後 `line.strip() == "<!-- devflow:begin -->"`（或 `end`）的行。**檔首 UTF-8 BOM（`EF BB BF`）不剝除**，屬第一行內容，故「BOM＋begin」的首行不是標記行——此點與 CI `d2`（`entry_block()`，以 `utf-8-sig` 讀檔）**刻意不同**：安裝器以 bytes 為準、不解碼整檔；差異僅影響「BOM 開頭且首行為 begin」一種輸入，記 #22 待對齊。其餘（第一組選取、`strip()` 語意）與判準 B 一致
- **第一組**：檔案第一個 begin 標記行，到其後第一個 end 標記行（含兩行）。**begin 之前若有任何 end 標記行**（落單 end）→ 違反 `D2`（1.0.0.0：區塊須為第一個標記組、其前無標記行），依 AC-5b 拒絕；無 begin 但有 end 標記行亦同
- **檔首插入**：輸出 = 模板 bytes + `\n` + 原檔 bytes。原檔以 `---` frontmatter 開頭時**同樣插在 byte 0**——`D2` 說「區塊外是專案的內容」，frontmatter 也是專案內容，安裝器不解析它；原檔若以換行開頭，該換行保留（不去重）
- **兩檔**：目標 repo 根目錄的 `CLAUDE.md` 與 `AGENTS.md`
- **目標檔集合**：依 AC-7 先選定要處理的檔案集合（兩檔／其一／依 `devflow.yml` 二選一），**再**對集合內每檔做決策；不在集合內的檔案不讀、不建。「存在」以 `os.path.lexists` 判：**symlink 一律視為存在**；dangling symlink（`lexists` 真、`exists` 假）→ exit 2，不寫任何檔，stderr 說明——安裝器不替使用者決定該建到哪裡；集合內路徑存在但**不是一般檔案**（目錄、或 symlink 指向目錄）→ 同樣 exit 2，stderr `<路徑>: not a regular file`
- **可寫性**：決策階段對集合內每個「將被寫入」的既有檔案檢查 `os.access(path, os.W_OK)`、將被建立的檔案檢查其目錄 `os.access(dir, os.W_OK | os.X_OK)`（POSIX 建檔需 write＋search 兩權限；`0222` 目錄 `W_OK` 真但建檔失敗）；任一不可寫 → exit 2，不寫任何檔。此檢查在 `--dry-run` 與實際執行**皆執行**，使兩者 exit code 一致（AC-10）。**測試前提**：可寫性案例以非 root 身分執行；harness 偵測到 `os.geteuid() == 0` 時將該類案例標為 `SKIP`（不算 FAIL），並在總計列印 skip 數——root 對 `0444` 檔 `os.access(W_OK)` 恆真，chmod 無法構造反例。檢查後仍發生的 OSError 不在原子性承諾內（可寫性檢查與寫入之間的競態）
- **原子性**：先對集合內全部檔案做決策（AC-1～AC-6、AC-8 各歸哪一路），任一檔命中 exit 1／exit 2 路徑則**集合內皆不寫**；全部可寫才寫

## 驗收標準

- AC-1: 目標檔不存在 → 建檔，內容 bytes 恰等於模板
- AC-2: 目標檔存在、無任何標記行 → 檔首插入（定義見上）；原檔 bytes 逐 byte 出現在輸出的 `len(模板)+1` 位置起
- AC-3: 第一組存在且其 bytes（含兩標記行，行尾正規化為 LF 後）等於模板 → 不寫檔，exit 0，stdout 該檔一行 `<路徑>: unchanged`
- AC-4: 第一組存在但 bytes 不等於模板 → 輸出 = 原檔[第一組 begin 行首之前] + 模板 + 原檔[第一組 end 行的行尾序列之後]；end 行有行尾序列（`\n` 或 `\r\n`）時連同其一併取代，end 行位於 EOF 且無行尾序列時 span 止於 EOF（此時輸出因模板尾端 `\n` 而多一個尾端換行，屬預期）；第一組之外逐 byte 不變（含第一組之後的任何標記——AC-6）
- AC-5: 有 begin 標記行、其後**無** end 標記行 → exit 1，不寫任何檔，stderr 一行 `<路徑>:<begin 行號>: devflow:begin without end`
- AC-5b: 第一個 begin 標記行之前有 end 標記行、或無 begin 但有 end 標記行 → exit 1，不寫任何檔，stderr 一行 `<路徑>:<該 end 行號>: stray devflow:end before begin`（取最早的一行）
- AC-6: 第一組之後再出現任何標記行 → 忽略：不計數、不報錯、不改動那些行；第一組仍依 AC-3／AC-4 處理
- AC-7: 兩檔皆存在 → 各自依 AC-1～AC-6 決策後依原子性寫入；只存在其一 → 只處理該檔，**不建**另一個；兩者皆無 → 由目標 repo 根目錄 `devflow.yml` 的**頂層鍵 `implementer_filler`** 決定建哪一檔：檔案通過下述**信封**、候選行合規、且值恰為 `claude-code` → 建 `CLAUDE.md`；**其他任何情況**（無 `devflow.yml`、無法讀取、無法以 UTF-8 **嚴格**解碼、信封不成立、無候選行、候選行不合規或重複、值為其他字串）→ 建 `AGENTS.md`（無設定時 `AGENTS.md` 是多數 agent 的通用入口）。此讀取**永不報錯**、不驗檔案其他內容（信封只看每個頂層行的起首，不解析任何值）、不建檔、**不做 YAML 解析**（stdlib only）。`implementer_filler` 是 `seats.implementer.filler`（實作位——`seats/implementer.md`——的填充工具；`seats:` 結構由 #68 引入）的**衍生投影**，一致性見 AC-13；安裝器只讀投影，**不讀** `seats:` 巢狀路徑——不解析 YAML 卻要判斷巢狀路徑等於手寫 YAML 子集 parser，PR #74 三輪審查證明攻擊面不收斂（#69 裁決）
  - **行**：檔案 bytes 以 `\n` 切行；檔首 BOM 不剝除（同標記行），故 BOM 開頭的檔案其第一個頂層行必不是頂層鍵行、整檔不合規。**忽略行**＝只含空格／tab／`\r` 的行、或去掉行首空格／tab 後以 `#` 起始的行。**頂層行**＝首字元不是空格的非忽略行。**頂層鍵行**＝裸鍵 ＋ `:` ＋（行尾、或一個以上空格／tab 再接任意內容）；裸鍵首字元為英文字母或 `_`，其餘為英文字母、數字、`_`、`-`、`.`
  - **信封**：**每一個頂層行都必須是頂層鍵行**；唯一例外是**第一個**頂層行可以是 `---`（其後只能是空格／tab／`\r`，或空格／tab 再接 `#` 註解）。任何其他頂層行——以 `[`、`{`、`"`、`'`、`|`、`>`、`-`、`?`、`%`、`&`、`!`、`*`、`<`、tab、BOM 起始者；第二個 `---`、`...`；`--- [`／`--- |`／`--- !!str` 之類 `---` 後帶內容者；引號鍵、非 ASCII 鍵；flow 集合或引號 scalar 的第 0 欄續行（單獨的 `]`／`}`／`"`）——使整檔不合規 → `AGENTS.md`。信封不看頂層鍵行 `:` 之後的內容，也不看任何縮排的行
  - **候選行**：以 `implementer_filler:` 起始的頂層行（`implementer_filler_x:` 之類只是前綴相同者不算；縮排的行——含 tab 縮排——不是頂層行，故不是候選行）。須**恰一行**，且整行為：`implementer_filler:` ＋ 一個以上空格或 tab ＋ **值** ＋〔一個以上空格或 tab ＋ `#` 至行尾〕（可省）＋ 行尾的空格／tab／`\r`（可省），此外不得有任何字元；值＝一段不含空格、tab、`\r`、`#` 的連續字元，逐 byte 比對、不去引號、不改大小寫。不合規例：`:` 後無空白（`implementer_filler:claude-code`）、無值（含只有註解）、值後接其他字元（`claude-code extra`、`claude-code#x`）、零行或兩行以上（兩行值相同亦同——重複鍵在 YAML 1.2 是錯誤、寬鬆 parser 取後者，「取第一個」會與其分歧）、值帶引號（`"claude-code"`）——一律 `AGENTS.md`
  - **保證邊界**：信封的目的是——在**符合 YAML 1.2 的檔案**中——通過者的根節點必為 block mapping，且候選行必為該 mapping 的一個直接 entry。理由：（一）根節點若是其他種類——block sequence、flow sequence／mapping、引號／plain／block scalar、alias、帶 tag 或 anchor 者——其第一個內容行（或 `---` 之後的內容）不是頂層鍵行，信封擋下。根節點的縮排基準是 −1（YAML 1.2.2 §9.1.3 `l-bare-document ::= s-l+block-node(-1,block-in)`），所以根 flow node 的續行**合法地**落在第 0 欄（§7.4.2 Example 7.19：第 0 欄的 `[`、`foo: bar`、`]`）、根 block scalar 的內容也可在第 0 欄（§9.1.3 Example 9.3 的 `|` 與 `%!PS-Adobe-2.0`）——這些正是信封要擋的。（二）根 block mapping 內部，值節點的縮排基準是 0：flow 集合與引號 scalar 的續行需 ≥1 格（§8.2.3 `s-l+flow-in-block(0)` 把節點置於 n＝1，續行走 §6.1 `s-flow-line-prefix(1)`＝`s-indent(1)`）、block scalar 內容需 ≥1 格（§8.1.2 `c-l+literal(0)` 內容在 n＋m、m≥1）、plain 多行 scalar 續行同需 ≥1 格且不得含 `: `、implicit key 限單行（§8.2.2）——因此合法檔案的第 0 欄不會出現任何續行，每個頂層行都是 entry。多 document 檔案（第二個 `---`、`...`）被信封擋下。**不在保證內**：違反 1.2 縮排規則、但寬鬆 parser（PyYAML 在 flow 與引號 scalar 內不檢查縮排）接受的檔案——例如 `x: [` 之後把候選行放在第 0 欄、再以**縮排的** `]` 收尾（第 0 欄的 `]` 會被信封擋下）：PyYAML 把候選行讀成 list 元素，本規格判 `CLAUDE.md`。只有無效 YAML 才會踩到；這是「不做 YAML 解析」的代價，本 repo 自己的檔案另由 AC-13 用真 parser 兜底
  - **advisory**：存在以 `seats:` 起始的頂層行、而本條讀不到合規的值（信封不成立、候選行缺失、不合規或重複）時，仍建 `AGENTS.md`、exit code 不變，另在 stderr 印一行 `devflow.yml: seats: present but implementer_filler unreadable (missing, malformed, duplicated, or file is not a plain top-level mapping); defaulting to AGENTS.md`（`--dry-run` 同印，AC-10）。這是 AC-13 在無 parser 環境的弱化版：只能偵測「投影缺失或壞掉」，偵測不了「兩處值不同」。讀到合規值時、或無 `seats:` 頂層行時不印
- AC-8: 模板行數（含兩標記行）>30 → exit 2，不寫任何檔，stderr 說明模板行數與 `D2` 上限
- AC-9: 連續執行兩次，第二次每個目標檔皆走 AC-3；判定：第一次執行後對兩檔各取 bytes 快照，第二次執行後 bytes 與快照相同且 stdout 每檔 `unchanged`
- AC-10: `--dry-run` → 不寫任何檔；exit code 與 stderr 與實際執行相同。exit 0 時對集合內每檔 stdout 印 unified diff（**恰為** `difflib.diff_bytes(difflib.unified_diff, old_lines, new_lines, b"a/<檔>", b"b/<檔>")` 的輸出逐行 join，不增不減——無尾端換行時**不**加 `\ No newline at end of file`）或 `<路徑>: unchanged`；exit 1／2 時 **stdout 全部抑制**（原子性：既然不會寫，也不印「預計」diff）
- AC-11: 目標路徑不存在、或不是目錄 → exit 2，stderr 說明；不讀模板、不做任何決策
- AC-12: 測試 harness（位置與執行方式寫進 `install.py` 檔頭）在 `/tmp` 建假專案，**每條 AC 的每個分支**至少一案（AC-5：begin 無 end；AC-5b：落單 end 在 begin 前／只有 end／落單 end 在 begin 前且 begin 後也有 end；AC-7：兩檔／只 CLAUDE／只 AGENTS／皆無＋`implementer_filler: claude-code`（行尾 `# …` 註解、CRLF、首行 `---`、首行 `--- # 註解`、與完整 `seats:` 區塊並存各一）→ `CLAUDE.md`／皆無＋`implementer_filler: codex`／皆無＋無 `devflow.yml`／皆無＋信封成立但值層有非法 YAML（`x: [` 未閉合、`y: "` 未閉合、縮排行內任意雜訊）→ `CLAUDE.md`（信封不看值、不看縮排行）／皆無＋不合規者每類至少一案、皆須得 `AGENTS.md`——候選行：`implementer_filler:claude-code`、無值（`implementer_filler:`、`implementer_filler:  # c`）、值後多餘 token（`claude-code extra`、`claude-code#x`）、重複（兩值相同、兩值不同各一）、`"claude-code"` 帶引號、`Claude-Code` 大小寫、`implementer_filler_x: claude-code` 前綴相同、空格縮排、tab 縮排；信封：根 flow sequence（`[`＋第 0 欄候選行＋`]`，Example 7.19 形式）、根 flow mapping（`{`＋候選行＋`}`）、根多行雙引號 scalar（`"`＋候選行＋`"`）與單引號變體、根 block scalar（`|`＋候選行）、`--- [`＋候選行＋`]`、`--- |`、**BOM 緊接鍵名**（首行 BOM＋合規候選行——抓誤用 `utf-8-sig`）、BOM＋`# 註解` 首行、第二個 `---`（候選行在第二個 document）、`...` 收尾、`%YAML 1.2` 指令行、他行引號鍵 `"forge": github`、`? key` 複合鍵、第 0 欄 `- item`、`x: [`＋候選行＋第 0 欄 `]`（信封擋 `]`）；其他：無法 UTF-8 解碼、只有 `seats.implementer.filler: claude-code` 巢狀寫法而無頂層鍵（含 PR #74 第三輪的三個 flow 包裹反例）／advisory：`seats:` 頂層行存在且讀不到合規值（候選行缺失、信封不成立各一）→ `AGENTS.md` ＋ stderr 恰一行 advisory、exit 0（dry-run 同）；讀到合規值、或無 `seats:` 行 → 無 advisory；AC-4：end 在 EOF 無換行；AC-11：不存在／是檔案），可寫性：唯讀既有檔（dry-run 與實跑 exit 皆 2）／目錄不可寫（非 root 前提）；dangling symlink；symlink 指向目錄；AC-10：無尾端換行的 diff 逐 byte 等於 difflib 輸出；含原子性案（一檔可寫、另一檔 exit 1 → 兩檔皆未寫）；可獨立重跑。AC-13 不在本 harness 範圍（它的執行者是 CI，驗證方式見該條）
- AC-13（`I5` 投影一致性）: `implementer_filler` 是 `seats.implementer.filler` 的**衍生投影**——同一個事實住兩處，`I5` 要求投影是產物、不手抄、不靠人記得同步。兩者的一致性由**機械檢查**保證：
  - **執行者與對象**：本 repo 的 CI 檢查器（`.github/workflows/devflow-checks.yml` 內嵌的規則檢查，已載入 PyYAML）新增一項，key `i5`；對象是本 repo 根目錄的 `devflow.yml`；每個 PR 執行，與其他項同一個 job
  - **判定**：以 PyYAML `yaml.compose` 取**節點樹**，**不經 `safe_load`／construct**——construct 會把重複鍵 last-wins 合併、把引號鍵與裸鍵合併、把 `<<` 展開，被吞掉的正是本條要抓的東西；本檔 CI 檢查器對 frontmatter `version` 的重複偵測已用同一機制（`duplicate_version_key`），沿用。**結構要求**（任一不成立 → ❌）：恰一個 document（`compose` 對多 document 拋錯即 ❌）；根節點是 `MappingNode`；沿兩條路徑——根層的 `implementer_filler`，與 `seats` → `implementer` → `filler`——所經的每一個 mapping（根、`seats`、`seats.implementer`）內，**任何鍵名都不得重複**——不限路徑上的鍵（以 key `ScalarNode` 的 `.value` 比對：引號鍵與裸鍵、alias 指向的 key 一視同仁），且不得含 merge 鍵（tag `tag:yaml.org,2002:merge`）。取 **S**＝`seats.implementer.filler` 的值節點（任一層鍵不存在、或其值不是 `MappingNode` → 無）、**P**＝根層 `implementer_filler` 的值節點（不存在 → 無）；S、P 存在時須為 tag `tag:yaml.org,2002:str` 的 `ScalarNode`（`yes` 之類被解析為 bool 者 → ❌），取其 `.value`。**L**＝安裝器依 AC-7 讀到的值（讀不到 → 無）——CI 直接載入 `devflow/install.py` 呼叫其讀取函式取得，**不得**另寫一份 AC-7 判定（兩份判定就有第三個可漂移的東西）。**通過 ⇔ 結構要求成立，且 S、P、L 三者皆為「無」，或三者皆為字串且逐字相等**。❌ 時 log 印出違反的結構要求、或三者的值。三者缺一不可：S＝P 保證投影沒漂移，P＝L 保證安裝器實際讀到的就是 YAML 語意（AC-7 的信封不是 YAML parser）；結構要求保證「同一事實在檔內只住一處」——`"implementer_filler": codex` ＋ `implementer_filler: claude-code` 這種 `safe_load` 後三者相等的過期投影，正是 `I5` 違規
  - **嚴重度**：本項是**關卡**——`GATES["i5"]` 最終須為 True。`devflow-checks` 已是 main 的 required status check（README「required 現況」），advisory 只寫 log 不擋合併，等於「靠人記得看」，與「機械保證」矛盾。定義域封閉（單一檔案、兩條固定路徑、真 parser、無散文判讀），符合 README 升關卡的判準；正反兩個 run（見驗證）是上線前的必要程序，不是要不要關卡的裁量。實作單在 `devflow-checks.yml` 檔頭記錄理由
  - **為什麼不是 `install.py` 自檢**：安裝器受 stdlib-only 約束、無法讀巢狀路徑——那正是本條與 AC-7 現行寫法的成因；自檢只能做到 AC-7 的 advisory（偵測「有 `seats:` 而無合規投影」），偵測不了「兩處值不同」。安裝器也**不得**在 PyYAML 可用時改走解析路徑：兩套解析＝兩種行為，實際跑到的會是比較弱的那套
  - **為什麼不是 `devflow/` 下的獨立腳本**：沒有執行者的腳本不是機械檢查；若日後要給消費者 repo 用，可從 CI 檢查器抽出，本檔不定義
  - **驗證**：依 README 既有程序取正反兩個 run——正向 run 為本 repo 現行設定 ✅；反向 run 的 blob 至少涵蓋：`implementer_filler` 與 S 不同、`implementer_filler` 刪除、**`"implementer_filler": codex` ＋ `implementer_filler: claude-code`**（引號鍵＋裸鍵重複，`safe_load` 後三者相等）、`seats:` 下兩個 `implementer:`（巢狀來源重複）、`implementer:` 下兩個 `filler:`、根層 `<<: *x` merge 鍵、兩個 document——每一個都須 ❌；兩個 run 的 sha 記錄在實作 PR

## 未決事項

- **消費者 repo 的投影一致性**：AC-13 只涵蓋本 repo。在 Phase 4 安裝／升級工具（能帶 YAML parser、或直接生成投影）落地前，消費者 repo 只有 AC-7 的 advisory——「有 `seats:` 而無合規 `implementer_filler:`」會被提示，「兩處值不同」無人攔。
- **BOM 對齊**：安裝器與 CI `d2` 對「BOM 開頭且首行為 begin」判定不同，記 #22（見「標記行」）。
