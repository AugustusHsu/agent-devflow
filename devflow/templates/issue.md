<!-- issue body 模板（WORKFLOW.md L1）。派工前每一欄都要填；「未決事項」必須為空。-->

## 目標

<一句話。對應規格：`docs/spec/<feature>/spec.md` 的 AC-n, AC-m>

## 基準

- 治理基準 G：`devflow/WORKFLOW.md @ <commit sha>`
- 開發目標 T：`docs/spec/<feature>/spec.md @ <commit sha>`（version <a.b.c.d>）

## 平行前提（P1；stage < 3 時仍要填，供之後判斷）

- Write scope：`<path/**>`, `<file>`
- 阻塞依賴：— 或 #N
- 共用契約：— 或 `<path>`（已在 main）
- 外部資源：— 或 `<category:resource>`（例 `gpu:0`、`port:8020`、`deploy:staging`）

## 驗證指令

```
<測試或檢查指令；審查者也會跑>
```

## 派工紀錄（讀審結束與派工後補）

- 派工前讀審（`L7`）：讀審結束即填；進行中可記各輪 URL，派工當下必為三值之一：`READY <URL>`、`人裁決 <URL>`、`未觸發 a／b 皆否`
- 派工：<留言 URL；或「本單無派工」>

## 審查處置（每輪 `REQUEST_CHANGES` 後補；`R11`）

<每輪一行：`第 n 輪 @ <head sha> → <處置留言 URL>`；或「尚無審查」>

## 未決事項

<派工前必須為空。coder 執行中遇到的問題寫成留言，不改這裡。>
