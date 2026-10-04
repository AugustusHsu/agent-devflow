# channel: none

沒有對話通道；人直接看 forge。這是 `devflow.yml` 頂層鍵 `channel` 的預設值（省略即為此），也是 kit 裝進新專案時的初始狀態。

本值下 `README.md` 的四職能全部由 forge 自己承擔：出站通知＝人自己讀 issue／PR；入站裁決＝人直接在 forge 留言（`CH1` 的「寫回 forge」一步不存在，因為回覆本來就在 forge）；seat 身分投影＝只有 forge 上的作者欄；對話分區＝issue／PR 本身。`CH2` 的故障分級不適用——沒有通道就沒有送達失敗。`launch: agent` 的投影（`orchestrators/hermes/SKILL.md` 第二節）在本值下無載體，派工者要讓人看見什麼就得寫進 issue 留言。
