---
version: 0.0.0.0
---

# install：把入口區塊安全插入其他專案的 CLAUDE.md／AGENTS.md

<!-- 依 WORKFLOW.md S1。stage 1 下第 2 節不生效，本檔為 Phase 2 首單的 T 基準（草稿）。-->

## 目標與範圍

給 agent-devflow 一個安裝器，把 `devflow/templates/entry-block.md` 的入口區塊插入**目標專案**既有的 `CLAUDE.md`／`AGENTS.md`，遵守 `D2`：區塊外的專案內容逐 byte 不變；重跑冪等；碰撞情況報錯且**不寫任何檔**。

**形式**：`devflow/install.py`，Python 3 stdlib only，`python3 devflow/install.py <目標 repo 路徑> [--dry-run]`。

**只做入口區塊**：不複製 `devflow/` 目錄、不建 `devflow.yml`（既有者只讀 `seats.implementer.filler` 一條路徑，見 AC-7）、不碰 `.gitignore`、不 commit。完整安裝／升級／回復是 Phase 4，本檔不定義其範圍。

**名詞定義**（全文適用）：
- **模板**：`devflow/templates/entry-block.md` 的完整 bytes，以 `<!-- devflow:begin -->` 行起、`<!-- devflow:end -->` 行止，含兩標記行；正規化為 LF、無 BOM、尾端恰一個 `\n`
- **標記行**：檔案 bytes 以 `\n` 切行、每行以 UTF-8 解碼（`errors="replace"`）後 `line.strip() == "<!-- devflow:begin -->"`（或 `end`）的行。**檔首 UTF-8 BOM（`EF BB BF`）不剝除**，屬第一行內容，故「BOM＋begin」的首行不是標記行——此點與 CI `d2`（`entry_block()`，以 `utf-8-sig` 讀檔）**刻意不同**：安裝器以 bytes 為準、不解碼整檔；差異僅影響「BOM 開頭且首行為 begin」一種輸入，記 #22 待對齊。其餘（第一組選取、`strip()` 語意）與判準 B 一致
- **第一組**：檔案第一個 begin 標記行，到其後第一個 end 標記行（含兩行）。**begin 之前若有任何 end 標記行**（落單 end）→ 違反 `D2`（1.0.0.0：區塊須為第一個標記組、其前無標記行），依 AC-5b 拒絕；無 begin 但有 end 標記行亦同
- **檔首插入**：輸出 = 模板 bytes + `\n` + 原檔 bytes。原檔以 `---` frontmatter 開頭時**同樣插在 byte 0**——`D2` 說「區塊外是專案的內容」，frontmatter 也是專案內容，安裝器不解析它；原檔若以換行開頭，該換行保留（不去重）
- **兩檔**：目標 repo 根目錄的 `CLAUDE.md` 與 `AGENTS.md`
- **目標檔集合**：依 AC-7 先選定要處理的檔案集合（兩檔／其一／只 `AGENTS.md`），**再**對集合內每檔做決策；不在集合內的檔案不讀、不建。「存在」以 `os.path.lexists` 判：**symlink 一律視為存在**；dangling symlink（`lexists` 真、`exists` 假）→ exit 2，不寫任何檔，stderr 說明——安裝器不替使用者決定該建到哪裡；集合內路徑存在但**不是一般檔案**（目錄、或 symlink 指向目錄）→ 同樣 exit 2，stderr `<路徑>: not a regular file`
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
- AC-7: 兩檔皆存在 → 各自依 AC-1～AC-6 決策後依原子性寫入；只存在其一 → 只處理該檔，**不建**另一個；兩者皆無 → 由目標 repo 根目錄的 `devflow.yml` 決定建哪一檔：檔案符合下述**形狀契約**、且 `filler` 的 token 恰為 `claude-code` → 建 `CLAUDE.md`；**其他任何情況**（無 `devflow.yml`、無法讀取、無法以 UTF-8 解碼、不符形狀、token 為其他字串）→ 建 `AGENTS.md`（入口檔是實作位——`seats/implementer.md`——填充工具的衍生值；`devflow.yml` 的 `seats:` 結構由 #68 引入；無設定時 `AGENTS.md` 是多數 agent 的通用入口）。此讀取**永不報錯**、不驗檔案其他內容、不建檔、**不做 YAML 解析**（stdlib only）。形狀契約只規定**輸入長什麼樣**與**不符時的結果**，不規定實作如何判定；判定以**整個檔案**為準，違規出現在 `filler` 之前或之後結果相同。定義：
  - **行**：檔案 bytes 以 `\n` 切行、UTF-8 解碼（同標記行：檔首 BOM 不剝除，屬第一行內容）。**空白**＝空格（U+0020）、tab（U+0009）、`\r`（實務上只出現在 CRLF 檔的行尾）；其他字元（含全形空格）都不是空白。**縮排**＝行首連續空格（U+0020）的個數；tab 不是縮排，以 tab 起首的行縮排為 0
  - **忽略行**：去除首尾空白後為空、或第一個非空白字元是 `#` 的行。忽略行可出現在任何位置、任何縮排，不影響任何判定
  - **鍵行**：縮排 ＋ 裸鍵 ＋ `:` ＋〔一個以上空白 ＋ token〕（可省）＋〔一個以上空白 ＋ `#` 至行尾〕（可省）＋ 行尾空白（可省），此外不得有任何字元。裸鍵限 ASCII：首字元為英文字母或 `_`，其餘為英文字母、數字、`_`、`-`、`.`；token 是一段不含空白、`#`、`{`、`}`、`[`、`]` 的連續字元（故 `reviewer: {}`、`reviewer: [a]` 都不是鍵行）。有 token 者為**有值鍵行**，無者為**無值鍵行**。凡不合此形者都不是鍵行，例如：引號鍵（`"filler":`）、非 ASCII 鍵、`- ` 序列項、flow 寫法（`{`／`}`／`[`／`]` 起首或收尾的行）、`<<:` 合併鍵、tab 縮排、`:` 後未接空白（`filler:claude-code`）、token 後再接字元（`filler: claude-code extra`、`filler: claude-code#x`）、區塊純量（`|`／`>`）的內容行——不必窮舉，判準只有上面一條
  - **區塊**：鍵行 K 的區塊 ＝ 緊接 K 之後、連續的行，直到第一個「縮排 ≤ K 的縮排」的非忽略行為止（不含該行）；有值、無值鍵行都有區塊。**直屬行**：區塊 B 內、且不落在 B 內任何其他鍵行之區塊內的非忽略行
  - **形狀契約**（四項須全部成立）：
    1. 縮排為 0 且以 `seats:` 起始的非忽略行**恰一行**，且為無值鍵行；其區塊為 **seats 區塊**。兩行以上（含 `seats: x` 這種帶值的、含跨 YAML document 的重複）→ 不符
    2. seats 區塊的直屬行中，縮排之後以 `implementer:` 起始的**恰一行**，且為無值鍵行；其區塊為 **implementer 區塊**
    3. implementer 區塊的直屬行中，縮排之後以 `filler:` 起始的**恰一行**，且為有值鍵行；其 token 即 `filler` 的值
    4. seats 區塊與 implementer 區塊的**每一個直屬行都是鍵行**。其他鍵（`reviewer`、`coordinator`、`approver`、`model`、`reasoning`…）可以出現、順序不限；那些鍵的區塊內容不在路徑上，本規格不管
  - 帶值的路徑鍵不構成路徑：`seats: foo`、`implementer: &a`、`seats: {…}` 直接違反第 1／2 項；其下縮排較深的行即使長得像 `implementer:`／`filler:`，也不會成為路徑上的行
  - token 逐 byte 比對、不去引號、不改大小寫：`filler: "claude-code"`、`filler: Claude-Code` 都不等於 `claude-code` → `AGENTS.md`
- AC-8: 模板行數（含兩標記行）>30 → exit 2，不寫任何檔，stderr 說明模板行數與 `D2` 上限
- AC-9: 連續執行兩次，第二次每個目標檔皆走 AC-3；判定：第一次執行後對兩檔各取 bytes 快照，第二次執行後 bytes 與快照相同且 stdout 每檔 `unchanged`
- AC-10: `--dry-run` → 不寫任何檔；exit code 與 stderr 與實際執行相同。exit 0 時對集合內每檔 stdout 印 unified diff（**恰為** `difflib.diff_bytes(difflib.unified_diff, old_lines, new_lines, b"a/<檔>", b"b/<檔>")` 的輸出逐行 join，不增不減——無尾端換行時**不**加 `\ No newline at end of file`）或 `<路徑>: unchanged`；exit 1／2 時 **stdout 全部抑制**（原子性：既然不會寫，也不印「預計」diff）
- AC-11: 目標路徑不存在、或不是目錄 → exit 2，stderr 說明；不讀模板、不做任何決策
- AC-12: 測試 harness（位置與執行方式寫進 `install.py` 檔頭）在 `/tmp` 建假專案，**每條 AC 的每個分支**至少一案（AC-5：begin 無 end；AC-5b：落單 end 在 begin 前／只有 end／落單 end 在 begin 前且 begin 後也有 end；AC-7：兩檔／只 CLAUDE／只 AGENTS／皆無＋形狀合規且 `filler: claude-code`（路徑三行皆帶行內 `#` 註解、`implementer` 前後各有其他職位）／皆無＋`filler: codex`／皆無＋無 `devflow.yml`／皆無＋路徑外含非 YAML 內容（如第 0 欄的 `- ` 行、`---`）但路徑合規 → `CLAUDE.md`／皆無＋不符形狀者每類至少一案、皆須得 `AGENTS.md`：重複 `seats:`（第二段才有 `implementer`）、`seats:` 不在第 0 欄、`seats: foo` 帶值後縮排寫 `implementer`／`filler`、`implementer: claude-code` 帶值、路徑直屬行出現非鍵行（`- ` 項、引號鍵、tab 縮排、`filler: claude-code extra`、其他職位鍵用 flow 寫法如 `reviewer: {}`）、`filler:` 無值、`filler: "claude-code"`、違規行位於 `filler` 之後；AC-4：end 在 EOF 無換行；AC-11：不存在／是檔案），可寫性：唯讀既有檔（dry-run 與實跑 exit 皆 2）／目錄不可寫（非 root 前提）；dangling symlink；symlink 指向目錄；AC-10：無尾端換行的 diff 逐 byte 等於 difflib 輸出；含原子性案（一檔可寫、另一檔 exit 1 → 兩檔皆未寫）；可獨立重跑

## 未決事項
