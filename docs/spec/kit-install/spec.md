---
version: 0.0.0.1
---

# kit-install：把 agent-devflow 完整安裝到消費者專案；升級與回復皆為重裝

<!-- 依 WORKFLOW.md S1。stage 1 下第 2 節不生效；本檔為 Phase 4 首單（#131）的 T 基準。
     入口區塊行為由 docs/spec/install/spec.md（下稱「入口規格」）定義，本檔只引用不重述（I5）。-->

## 目標與範圍

**要解決什麼**：入口規格的安裝器只插入入口區塊；裝到消費者專案後，區塊指向的 `devflow/WORKFLOW.md` 並不存在。本檔把同一支安裝器擴充為**完整安裝**：把 kit 的 `devflow/` 鏡像到消費者專案、建立消費者自有的 `devflow.local/`、再依入口規格處理入口區塊。**升級與回復不是新功能**：換一個 kit checkout（另一個 tag）重跑同一支安裝。Phase 4 出口「有可安全安裝的固定版本」＝本檔＋`devflow/VERSION`＋tag（`V4`、`V5`）。

**形式**：`python3 <kit>/devflow/install.py <目標 repo 路徑> [--dry-run]`。Python 3 stdlib only，POSIX。**來源**＝執行中的 `install.py` 所在的 `devflow/` 目錄（`os.path.dirname(os.path.abspath(__file__))`），其上層為 kit 根；不依賴 git、不驗 git 狀態。**目標**＝命令列給的路徑。來源與目標可為同一 repo（kit 自檢，或消費者跑自己那份副本），此時鏡像為 no-op（AC-19）。

**擁有權**（全文核心，每條 AC 由此推導）：

| 目標內路徑 | 擁有者 | 安裝器行為 |
|---|---|---|
| `devflow/**` | kit | 鏡像：與來源不同即覆寫、來源沒有即刪除；排除路徑除外 |
| `devflow.yml` | 消費者 | 不建、不改；只依入口規格 AC-7 唯讀 |
| `devflow.local/**` | 消費者 | 不存在才建，且只放 `README.md`；存在（任何形態）則整棵不碰 |
| `CLAUDE.md`／`AGENTS.md` | 消費者（區塊除外） | 依入口規格 AC-1～AC-13 |
| 其他一切 | 消費者 | 不讀、不寫 |

**名詞定義**（全文適用）：
- **版本**：`devflow/VERSION` 檔，內容恰為一行 `a.b.c.d`（`V1` 四碼，每碼十進位非負整數、除單獨的 `0` 外無前導零）加恰一個 `\n`，無 BOM。比較依四碼數值元組。
- **排除路徑**：任何名為 `__pycache__` 的目錄（連同其下全部）、副檔名 `.pyc` 的檔。對來源與目標**雙邊**生效：來源的不複製、目標的不刪除、不列入報表。
- **鏡像集合**：來源 `devflow/` 下、排除路徑以外的所有一般檔案，以相對於 `devflow/` 的 POSIX 路徑識別。
- **動作**：對鏡像集合每個路徑 p——目標無 p → `created`；目標 p 存在但 bytes 不同、或 p 是 symlink（任何指向）→ `updated`（symlink 由一般檔取代）；bytes 相同 → `unchanged`。目標 `devflow/` 下、排除路徑以外、不在鏡像集合的一般檔或 symlink → `deleted`（symlink 只移除連結本身，不進入其指向）。刪除後留下的空目錄一併移除，`devflow/` 本身除外。
- **模式**：以目標**安裝前**的 `devflow/VERSION` 為舊版、來源的為新版——目標無 `devflow/` 或無該檔 → `fresh`；舊版可解析且新版＞舊版 → `upgrade`；新版＜舊版 → `downgrade`；相等 → `same`；舊版存在但不合「版本」定義 → `replace`。模式只用於報表，不改變行為。
- **單檔原子寫入**：寫 p ＝ 同目錄寫暫存檔後 `os.replace`。不保證多檔整體原子（AC-16）。

**不做**（決定，非未決）：
- 不建、不改 `devflow.yml`。`forge`／`seats` 是消費者的選擇，安裝器不替人選；kit 附 `devflow/templates/devflow.yml`（頂層鍵集合與 kit 根 `devflow.yml` 相同，值為註解過的預設）供複製，缺檔時只提示（AC-9）。
- 不加 `--uninstall`。README Phase 4 只列安裝／升級／回復；移除留後版。
- 不安裝 CI 檢查器（`scripts/devflow_checks.py`、`.github/workflows/`）與 `docs/`：它們不在 `devflow/` 下。v0.0.0.1 的消費者沒有 CI，另立 issue。
- 不建 `.hermes/skills/` symlink 等 orchestrator 接入；接入方式住 `devflow/orchestrators/<name>.md`。
- 不驗來源是否為 tag checkout。`V5` 保證已發 tag 不移動，故從 tag checkout 安裝時 VERSION 與內容一一對應；從其他 commit 安裝是使用者的選擇，安裝器只報 VERSION。
- 不合併內容。`devflow/**` 是 kit 的，消費者在其下的修改會被下一次鏡像覆寫或刪除——`--dry-run` 先列出（AC-10）。

**與入口規格的關係**：入口規格「目標與範圍」寫「不複製 `devflow/` 目錄」，本檔使該句不再成立——依 `V6` 標為**不相容**：受影響契約＝「`install.py` 只動入口檔」；遷移＝無（尚無消費者）；入口規格該句改為引用本檔（editorial，另單）。入口規格 AC-1～AC-13 全部保留，由本安裝器在鏡像之後執行；其 harness 案例保留、斷言前綴依 AC-20 調整。

**kit 內容前提**（本檔不實作、v0.0.0.1 前完成、另單）：kit 的 `devflow/{coders,forges,orchestrators}/*.md` 只保留「通用」節；「本機」節（含 kit 自身的）移到各消費者的 `devflow.local/`。AC-17 以此為 kit 義務，`R9` 措辭與 SKILL.md 路徑同步屬該單。

## 驗收標準

「集合」「原子性」「可寫性」「`--dry-run`」的既有語意依入口規格。exit code：0 成功；1 入口區塊碰撞（入口規格 AC-5／5b／5c）；2 環境或用法錯誤。exit 非 0 時**不寫任何檔、stdout 全部抑制**，stderr 恰一行 `<路徑或項目>: <原因>`。

- AC-1: 目標無 `devflow/` → 建立；鏡像集合每檔 bytes 等於來源；`devflow.local/README.md` 依 AC-7；入口區塊依入口規格；stdout 第一行模式 `fresh`；exit 0
- AC-2: 目標 `devflow/x` 存在但 bytes 與來源不同、或為 symlink → 覆寫為來源 bytes（symlink 由一般檔取代），stdout 一行 `devflow/x: updated`
- AC-3: 目標 `devflow/y` 為一般檔或 symlink、不在鏡像集合、不屬排除路徑 → 刪除（symlink 只移除連結），stdout 一行 `devflow/y: deleted`；刪後空目錄移除（`devflow/` 本身保留）
- AC-4: 動作為 `unchanged` 的路徑不印任何行；排除路徑雙邊不複製、不刪除、不印
- AC-5: 連續執行兩次 → 第二次 stdout 恰為摘要行（模式 `same`）＋入口規格 AC-3 的 `unchanged` 行；第二次執行後目標整棵樹的 bytes 與存在性等於第一次執行後的快照
- AC-6: 以 kit 副本 A（VERSION `0.0.0.1`）安裝，再以副本 B（VERSION `0.0.0.2`；相對 A 恰一檔改、一檔增、一檔刪）安裝 → 摘要模式 `upgrade`，動作行恰為 `updated`／`created`／`deleted` 各一；再以 A 安裝 → 摘要模式 `downgrade`，目標 `devflow/` 整棵樹 bytes 與第一次安裝後逐 byte 相同
- AC-7: 目標無 `devflow.local`（`os.path.lexists` 假）→ 建目錄與 `devflow.local/README.md`（bytes 等於 `devflow/templates/local-README.md`），stdout 一行 `devflow.local/README.md: created`；`lexists` 真（目錄、空目錄、缺 README、檔案、symlink 皆算）→ 不建、不改、不印
- AC-8: 目標有 `devflow.yml` → 安裝前後 bytes 相同；目標無 → 不建
- AC-9: exit 0 且目標無 `devflow.yml` → stderr 含恰一行 `devflow.yml: absent; copy devflow/templates/devflow.yml and edit (advisory)`，exit 不受影響；`--dry-run` 同樣印；exit 非 0 時不印（stderr 只有錯誤那一行）
- AC-10: `--dry-run` → 不寫任何檔（目標整棵樹 bytes 與存在性前後相同）；exit code、stderr、stdout 的摘要行與動作行與實際執行**逐字相同**；入口檔部分依入口規格 AC-10（unified diff 或 `unchanged`）
- AC-11: exit 0 時 stdout 第一行恰為 `kit-install: <舊版或 none> -> <新版> (<模式>)`，模式取 `fresh|upgrade|downgrade|same|replace` 之一，`replace` 時舊版印 `invalid`；其後為動作行（`devflow/...` 與 `devflow.local/README.md`），以路徑字串 `sorted()` 排序；再接入口檔輸出（入口規格 AC-3／AC-10 格式）
- AC-12: 來源無 `devflow/VERSION`、或內容不合「版本」定義 → exit 2，stderr `devflow/VERSION: <原因>`；不讀目標、不做任何決策
- AC-13: 來源 `devflow/` 下（排除路徑以外）任何 symlink，不論指向檔、目錄或 dangling → exit 2，stderr `<相對路徑>: symlink in source not supported`
- AC-14: 目標 `devflow` 以 `lexists` 存在但不是目錄（一般檔、任何 symlink 含指向目錄者、dangling）→ exit 2，stderr `devflow: <原因>`
- AC-15: 決策階段對每個將被 created／updated／deleted 的路徑檢查所在目錄 `W_OK | X_OK`、將被 updated／deleted 的既有檔另檢查本身 `W_OK`；任一不可寫 → exit 2、不寫任何檔；`--dry-run` 亦檢查（與入口規格「可寫性」同理）
- AC-16: 寫入順序＝鏡像 created／updated（每檔單檔原子）→ 鏡像 deleted → 空目錄移除 → `devflow.local/` → 入口檔（入口規格原子性）。中途 I/O 失敗 → exit 2，stderr 指出失敗路徑；已完成的步驟不回滾，重跑即為恢復（AC-5 保證收斂）
- AC-17: harness 對**執行中的 kit 本身**檢：`devflow/VERSION` 合「版本」定義；`devflow/templates/devflow.yml` 與 `devflow/templates/local-README.md` 存在；`devflow/` 下（排除路徑以外）無 symlink；`devflow/{coders,forges,orchestrators}/*.md` 無 `## 本機` 標題行。任一不成立即該案失敗
- AC-18: 目標中 `devflow/`、`devflow.local/`、入口檔集合以外的任何路徑，安裝前後 bytes 與存在性相同；harness 以整棵樹快照（含權限位以外的 stat 不比）比對
- AC-19: 目標路徑即 kit 根（來源＝目標）→ 鏡像全部 `unchanged`、無 `deleted`；`devflow.local/` 依 AC-7；入口檔依入口規格；摘要模式 `same`；exit 0
- AC-20: `tests/install/harness.py` 擴充：本檔每條 AC 每個分支至少一案；需變造來源的案例把 kit 複製到 `/tmp` 後變造、執行該副本的 `install.py`（AC-6 的 A／B 即兩份副本）；入口規格既有案例全部保留，其 stdout 斷言改為「摘要行＋動作行」前綴之後的部分逐字不變

## 未決事項

