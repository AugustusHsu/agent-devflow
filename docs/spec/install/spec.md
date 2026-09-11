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
- AC-7: 兩檔皆存在 → 各自依 AC-1～AC-6 決策後依原子性寫入；只存在其一 → 只處理該檔，**不建**另一個；兩者皆無 → 由目標 repo 根目錄 `devflow.yml` 的**頂層鍵 `implementer_filler`** 決定建哪一檔：該鍵合規（形狀見下）且值恰為 `claude-code` → 建 `CLAUDE.md`；**其他任何情況**（無 `devflow.yml`、無法讀取、無法以 UTF-8 **嚴格**解碼、無該鍵、不符形狀、值為其他字串）→ 建 `AGENTS.md`（無設定時 `AGENTS.md` 是多數 agent 的通用入口）。此讀取**永不報錯**、不驗檔案其他內容、不建檔、**不做 YAML 解析**（stdlib only）。`implementer_filler` 是 `seats.implementer.filler`（實作位——`seats/implementer.md`——的填充工具；`seats:` 結構由 #68 引入）的**衍生投影**，一致性見 AC-13；安裝器只讀投影，**不讀** `seats:` 巢狀路徑——不解析 YAML 卻要判斷巢狀路徑等於手寫 YAML 子集 parser，PR #74 三輪審查證明攻擊面不收斂（#69 裁決）
  - **形狀**：檔案 bytes 以 `\n` 切行（檔首 BOM 不剝除，同標記行）。**候選行**＝以 `implementer_filler:` 起始的行（第 0 欄，前面沒有任何字元；`implementer_filler_x:` 之類只是前綴相同者不算）。候選行須**恰一行**，且整行為：`implementer_filler:` ＋ 一個以上空格或 tab ＋ **值** ＋〔一個以上空格或 tab ＋ `#` 至行尾〕（可省）＋ 行尾的空格／tab／`\r`（可省），此外不得有任何字元；值＝一段不含空格、tab、`\r`、`#` 的連續字元，逐 byte 比對、不去引號、不改大小寫。不符任一項——鍵不在第 0 欄（含空格或 tab 縮排、BOM 緊接鍵名）、`:` 後無空白（`implementer_filler:claude-code`）、無值（含只有註解）、值後接其他字元（`claude-code extra`、`claude-code#x`）、候選行零行或兩行以上（含跨 YAML document；兩行值相同亦同——重複鍵在 YAML 1.2 是錯誤、寬鬆 parser 取後者，「取第一個」會與其分歧）、值帶引號（`"claude-code"`）——一律 `AGENTS.md`。候選行以外的任何內容（`seats:` 區塊、其他頂層鍵、註解、非 YAML 雜訊）不影響結果
  - **保證邊界**：符合 YAML 1.2 的檔案中，第 0 欄的 `implementer_filler:` 行只能是頂層 mapping 的鍵——flow 集合與區塊純量的續行至少需一個空格縮排，無法把第 0 欄的行包進去；寬鬆 parser（如 PyYAML）接受、但違反此縮排規則的檔案，其解析結果可能與本規格不同，不在保證內。這是「不做 YAML 解析」的既有代價，與舊 `^coder:` 相同
  - **advisory**：存在以 `seats:` 起始的第 0 欄行、而候選行形狀檢查不成立時，仍建 `AGENTS.md`、exit code 不變，另在 stderr 印一行 `devflow.yml: seats: present but implementer_filler: missing or malformed; defaulting to AGENTS.md`（`--dry-run` 同印，AC-10）。這是 AC-13 在無 parser 環境的弱化版：只能偵測「投影缺失或壞掉」，偵測不了「兩處值不同」。候選行合規時、或無 `seats:` 行時不印
- AC-8: 模板行數（含兩標記行）>30 → exit 2，不寫任何檔，stderr 說明模板行數與 `D2` 上限
- AC-9: 連續執行兩次，第二次每個目標檔皆走 AC-3；判定：第一次執行後對兩檔各取 bytes 快照，第二次執行後 bytes 與快照相同且 stdout 每檔 `unchanged`
- AC-10: `--dry-run` → 不寫任何檔；exit code 與 stderr 與實際執行相同。exit 0 時對集合內每檔 stdout 印 unified diff（**恰為** `difflib.diff_bytes(difflib.unified_diff, old_lines, new_lines, b"a/<檔>", b"b/<檔>")` 的輸出逐行 join，不增不減——無尾端換行時**不**加 `\ No newline at end of file`）或 `<路徑>: unchanged`；exit 1／2 時 **stdout 全部抑制**（原子性：既然不會寫，也不印「預計」diff）
- AC-11: 目標路徑不存在、或不是目錄 → exit 2，stderr 說明；不讀模板、不做任何決策
- AC-12: 測試 harness（位置與執行方式寫進 `install.py` 檔頭）在 `/tmp` 建假專案，**每條 AC 的每個分支**至少一案（AC-5：begin 無 end；AC-5b：落單 end 在 begin 前／只有 end／落單 end 在 begin 前且 begin 後也有 end；AC-7：兩檔／只 CLAUDE／只 AGENTS／皆無＋`implementer_filler: claude-code`（行尾 `# …` 註解、CRLF、與完整 `seats:` 區塊並存各一）→ `CLAUDE.md`／皆無＋`implementer_filler: codex`／皆無＋無 `devflow.yml`／皆無＋候選行合規但檔案其餘部分不是合法 YAML（第 0 欄 `- ` 行、未閉合的 `[`）→ `CLAUDE.md`／皆無＋不符形狀者每類至少一案、皆須得 `AGENTS.md`：鍵不在第 0 欄（空格縮排、tab 縮排各一）、`implementer_filler:claude-code`、無值（`implementer_filler:`、`implementer_filler:  # c`）、值後多餘 token（`claude-code extra`、`claude-code#x`）、重複 `implementer_filler:`（兩值相同、兩值不同、跨 `---` 各一）、`"claude-code"` 帶引號、`Claude-Code` 大小寫、`implementer_filler_x: claude-code` 前綴相同、無法 UTF-8 解碼、只有 `seats.implementer.filler: claude-code` 巢狀寫法而無頂層鍵（含 PR #74 第三輪的三個 flow 包裹反例）／advisory：`seats:` 在第 0 欄且無合規候選行 → `AGENTS.md` ＋ stderr 恰一行 advisory、exit 0（dry-run 同）；有合規候選行、或無 `seats:` 行 → 無 advisory；AC-4：end 在 EOF 無換行；AC-11：不存在／是檔案），可寫性：唯讀既有檔（dry-run 與實跑 exit 皆 2）／目錄不可寫（非 root 前提）；dangling symlink；symlink 指向目錄；AC-10：無尾端換行的 diff 逐 byte 等於 difflib 輸出；含原子性案（一檔可寫、另一檔 exit 1 → 兩檔皆未寫）；可獨立重跑。AC-13 不在本 harness 範圍（它的執行者是 CI，驗證方式見該條）
- AC-13（`I5` 投影一致性）: `implementer_filler` 是 `seats.implementer.filler` 的**衍生投影**——同一個事實住兩處，`I5` 要求投影是產物、不手抄、不靠人記得同步。兩者的一致性由**機械檢查**保證：
  - **執行者與對象**：本 repo 的 CI 檢查器（`.github/workflows/devflow-checks.yml` 內嵌的規則檢查，已載入 PyYAML）新增一項，key `i5`；對象是本 repo 根目錄的 `devflow.yml`；每個 PR 執行，與其他項同一個 job
  - **判定**：以 PyYAML `safe_load` 解析全檔，取 **S**＝`seats.implementer.filler`（任一層不存在、或不是 mapping → 無）與 **P**＝頂層 `implementer_filler`（不存在 → 無）；**L**＝安裝器依 AC-7 讀到的值（不符形狀 → 無）——CI 直接載入 `devflow/install.py` 呼叫其讀取函式取得，**不得**另寫一份形狀判定（兩份判定就有第三個可漂移的東西）。**通過 ⇔ S、P、L 三者皆為「無」，或三者皆為字串且逐字相等**。解析失敗、多於一個 YAML document、任一為非字串（如 `yes` 被 YAML 1.1 解析為布林）、任一不相等 → 該項 ❌，log 印出三者的值。三者缺一不可：S＝P 保證投影沒漂移，P＝L 保證安裝器實際讀到的就是 YAML 語意（AC-7 的形狀不是 YAML parser）
  - **嚴重度**：定義域封閉（單一檔案、單一鍵、真 parser、無散文判讀），符合 README「升關卡」的判準；是否設為關卡（`GATES` True）與是否列入 required status check，依既有程序（正反兩個 run、同一份 blob）由實作單決定並在該檔檔頭記錄理由
  - **為什麼不是 `install.py` 自檢**：安裝器受 stdlib-only 約束、無法讀巢狀路徑——那正是本條與 AC-7 現行寫法的成因；自檢只能做到 AC-7 的 advisory（偵測「有 `seats:` 而無合規投影」），偵測不了「兩處值不同」。安裝器也**不得**在 PyYAML 可用時改走解析路徑：兩套解析＝兩種行為，實際跑到的會是比較弱的那套
  - **為什麼不是 `devflow/` 下的獨立腳本**：沒有執行者的腳本不是機械檢查；若日後要給消費者 repo 用，可從 CI 檢查器抽出，本檔不定義
  - **驗證**：依 README 既有程序取正反兩個 run——反向 run 以改壞 `implementer_filler`（與 S 不同、或刪除）的 blob 觸發 ❌，正向 run 為本 repo 現行設定 ✅；兩個 run 的 sha 記錄在實作 PR

## 未決事項

- **消費者 repo 的投影一致性**：AC-13 只涵蓋本 repo。在 Phase 4 安裝／升級工具（能帶 YAML parser、或直接生成投影）落地前，消費者 repo 只有 AC-7 的 advisory——「有 `seats:` 而無合規 `implementer_filler:`」會被提示，「兩處值不同」無人攔。
- **BOM 對齊**：安裝器與 CI `d2` 對「BOM 開頭且首行為 begin」判定不同，記 #22（見「標記行」）。
