---
version: 0.0.0.0
---

# install：把入口區塊安全插入其他專案的 CLAUDE.md／AGENTS.md

<!-- 依 WORKFLOW.md S1。stage 1 下第 2 節不生效，本檔為 Phase 2 首單的 T 基準（草稿）。-->

## 目標與範圍

給 agent-devflow 一個安裝器，把 `devflow/templates/entry-block.md` 的入口區塊插入**目標專案**既有的 `CLAUDE.md`／`AGENTS.md`，遵守 `D2`：區塊外的專案內容逐字元不變；重跑冪等；碰撞情況報錯不寫檔。

**形式**：`devflow/install.py`，Python 3 stdlib only，`python3 devflow/install.py <目標 repo 路徑> [--dry-run]`。

**只做入口區塊**：不複製 `devflow/` 目錄、不建 `devflow.yml`、不碰 `.gitignore`、不 commit。完整安裝／升級／回復是 Phase 4。

**入口區塊的辨識**與 `devflow-checks.yml` 的 `d2` 判準 B 一致：檔案第一個 `<!-- devflow:begin -->` 到其後第一個 `<!-- devflow:end -->`（`strip()` 後整行相等），其後標記一律忽略。

## 驗收標準

- AC-1: 目標檔不存在 → 建檔，內容恰為區塊（模板全文），檔尾一個換行
- AC-2: 目標檔存在、無區塊、有內容 → 區塊插於檔首，原內容緊接其後（區塊 end 與原內容之間一個空行），原內容逐字元不變
- AC-3: 已有區塊且內容與模板相同 → 不寫檔，exit 0，stdout 註明冪等
- AC-4: 已有區塊但內容與模板不同 → 只替換第一組 begin…end 之間（含兩標記行），區塊外逐字元不變
- AC-5: 有 begin 無 end、或有 end 在任何 begin 之前且無 begin → 報錯 exit 1，**不寫檔**，stderr 指出檔名與行號
- AC-6: 第一組區塊之後再出現標記 → 忽略，不報錯，不改動
- AC-7: 目標 repo 同時有 `CLAUDE.md` 與 `AGENTS.md` → 兩檔各自依 AC-1～AC-6 處理；只有其一 → 只處理該檔，**不建**另一個；兩者皆無 → 建 `AGENTS.md`（僅此一檔）
- AC-8: 模板本身（含兩標記行）>30 行 → 報錯 exit 2，不寫任何檔（安裝器不寫出違反 `D2` 的區塊）
- AC-9: 連續執行兩次，第二次對每個目標檔皆為 AC-3 的冪等路徑；`git diff` 為空
- AC-10: `--dry-run` → 印出每個目標檔的 unified diff（或「無改動」），不寫檔，exit code 與實際執行相同
- AC-11: 目標路徑不存在、或不是目錄 → exit 2，stderr 說明
- AC-12: 測試 harness 在 `/tmp` 建假專案覆蓋 AC-1～AC-11 每條至少一案，可獨立重跑；harness 位置與執行方式寫進 `install.py` 檔頭

## 未決事項

（空）
