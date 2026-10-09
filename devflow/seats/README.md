# devflow/seats — 職位定義

五個職位各一檔：`implementer.md`（實作位）、`reviewer.md`（審查位）、`manager.md`（執行位）、`coordinator.md`（協調位）、`approver.md`（裁決位）。每檔只寫職責、產出物、禁止、context 語意、規則義務、填充者能力；不指定填哪個工具，也不記工具的指令——前者是綁定、後者住對照表。

本目錄是**職位本體、不綁工具**；填充者的人格檔範本（**通道側操作規範**）住 `devflow/channels/templates/`，兩者的分工見該目錄的 `README.md`。

版本規則 `V1`、`V2`、`V3`、`V5`、`V6` 的行為人，五個職位檔都不分配——這五條不是遺漏，是刻意保留：G 未指定其行為人，分配即等於新增 G 中不存在的義務。其中 `V1`、`V2`、`V3`、`V5` 待 #63 裁定；`V6` 是 #214 裁決當下就納入的，理由與前四條同（純敘述義務、無機械判準），來源不是 #63。這句是說明，不是義務。

## `filler` 與 `launch` 的分工

`filler` 只指**模型與能力的來源**（對照表在 `devflow/coders/`），不指啟動機制；啟動機制是 `launch`（見 `devflow.yml`）。同一個 `filler` 可由不同 `launch` 啟動，能力證據依 `R9` 綁該 `filler` 的對照表格，不因 `launch` 改變而失效。**`launch: agent` 時 `filler` 指能力對照表的歸屬，不表示實際執行的是該 CLI**——例如 Hermes 平台上跑 Anthropic 模型的具名實例，其 `filler` 為 `claude-code`，能力對照看 `coders/claude-code.md`。
