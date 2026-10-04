# channel: none

沒有對話通道；人直接看 forge。這是 `devflow.yml` 頂層鍵 `channel` 的預設值（省略即為此），也是 kit 裝進新專案時的初始狀態。

本值下 `README.md` 的四職能全部由 forge 自己承擔：出站通知＝人自己讀 issue／PR；入站裁決＝人直接在 forge 留言（`CH1` 的「寫回 forge」一步不存在，因為回覆本來就在 forge）；seat 身分投影＝只有 forge 上的作者欄；對話分區＝issue／PR 本身。`CH2` 的故障分級不適用——沒有通道就沒有送達失敗。`launch: agent` 的投影（`orchestrators/hermes/SKILL.md` 第二節）在本值下無載體，派工者要讓人看見什麼就得寫進 issue 留言。

衍生值對照表，**只有通用節**。分節與狀態欄依 `R9`。

## 通用

| 面向 | 職位 | 值 | 狀態 |
|---|---|---|---|
| 出站通知 | coordinator | 不推播；人讀 forge | ✅ 可用（無通道即無需驗證：本格宣稱的是「不做任何事」，第三者在任何 `channel: none` 的專案照做（不設通道、只讀 forge）必然得到同一結果；受測環境：不適用——本格不依賴任何工具版本或環境） |
| 入站裁決 | approver／coordinator | 人直接在 issue／PR 留言，即為 forge 紀錄（`L3`、`R5`） | ✅ 可用（同 `forges/<forge>.md` 「留言／label」格，依該格的驗證方式與受測環境；本格不另宣稱能力） |
| seat 身分投影 | — | 無；只有 forge 作者欄 | ✅ 可用（同上：宣稱「不做」，無需驗證） |
| 對話分區 | — | 無；issue／PR 本身即分區 | ✅ 可用（同上） |
