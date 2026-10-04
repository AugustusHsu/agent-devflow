# channel: telegram

衍生值對照表，**只有通用節**（值欄宣稱可重用的工具能力、平台限制或程序，群組、bot 與 repo 只是可替換的參數）。本機節——具名的環境 instance（本 repo 用的群組 id、bot username、profile 名）——住 `devflow.local/channels/telegram.md`，不隨 kit 安裝。分節與狀態欄依 `R9`。規則本體在 `WORKFLOW.md` 第 13 節（`CH1`、`CH2`）；層定義在本目錄 `README.md`。

本表的三格證據全部引用既有 forge 紀錄（`#258` 2026-10-04 K4 材料留言 https://github.com/AugustusHsu/agent-devflow/issues/258#issuecomment-5976693497 ），本單（K4a）不重跑、不打 Telegram API；第三者依各格「驗證方式」自行重現。

## 通用

| 面向 | 職位 | 值 | 狀態 |
|---|---|---|---|
| seat 間喚醒 | coordinator／manager | Telegram Bot API 硬性禁止 bot 收到其他 bot 的訊息；協調平台的 `allow_bots: mentions` 在 Telegram 上永不觸發（該設定供 Slack／Discord 用）。seat 間的喚醒只能走子程序 ＋ 事件流轉播（`orchestrators/hermes/SKILL.md` 第 7 步 `launch: agent`），不能靠 @提及 | ✅ 可用（實測 2026-09-29，`#267` 派工時觀測：協調位 bot 以 `hermes -p dfcoord send --json -t telegram:<chat>:<thread>` 送出 @ 目標 bot 的訊息，回報 `success: true`、`message_id 443`，訊息確實落在 topic；目標 bot 的 `getUpdates` 從未收到該則、其 gateway 日誌零 inbound。驗證方式，第三者在自己有兩個 bot 的 forum group 照做：(1) 以 bot A 的 token `sendMessage` 一則含 `@<bot B username>` 的訊息到任一 topic，記下回傳的 `message_id`；(2) 以 bot B 的 token 跑 `getUpdates`（或讀其 gateway 的 inbound 日誌），期望**不含**該 `message_id`；(3) 對照組——以人類帳號在同一 topic 發一則 @ bot B 的訊息，期望 bot B 的 `getUpdates` 含它，證明 (2) 的空結果不是 B 本身收不到訊息。受測環境（`R10`）：首次驗證＝最近確認 2026-09-29；Hermes `v0.21.5+3584.g38e416d (2026.9.24)`；執行身分為兩個 bot 的 token 持有者（本 repo：`@devflow_coord_bot` 送、`@devflow_mgr_bot` 收），bot 皆為群組 administrator；目標環境 Telegram forum group `-1003546152597` thread `355`；證據：`#258` K4 材料留言（上方連結）、`#267` topic 封存檔 `267.md` 的 `23:50:22` 段） |
| 在 General 下指令的限制 | coordinator／approver | 協調平台（Hermes）的 Telegram adapter 以 `exclusive_bot_mentions`（預設開）先於 `free_response_topics` 白名單判定：訊息的 bot mention 集合非空且不含目標 bot 自己的 handle 時，在前者就被靜默丟棄（排除），後者的白名單來不及放行；同時 @ 到自己與其他 bot 時不排除。在 General 對多個 bot 下指令時，未被 @ 到的 bot 必然沉默；被 @ 到的 bot 是否回應由其各自的 mention 設定與 gateway 狀態決定，不在本格機制內 | ✅ 可用（實測 2026-09-30：裁決位在 General 發「實作由 `@devflow_impl_bot` 執行、審查由 `@devflow_rev_bot` 執行」，三個 bot 全部沉默、gateway 日誌零 inbound。其中 `@devflow_coord_bot` 未被 @ → 沉默，與本格機制一致；另兩 bot 被 @ 到卻沉默，其沉默原因本格不宣稱（它們的 `require_mention: true` 對人發的訊息已滿足，排除不來自本格機制）。機制定位：`plugins/platforms/telegram/adapter.py` 的 `_telegram_exclusive_bot_mentions() and _explicit_bot_mentions_exclude_self(message)` 判斷（`:6460`）早於 `_telegram_is_free_response_topic(message)`（`:6468`）8 行；`_explicit_bot_mentions_exclude_self` 回 `bool(mentioned_bot_usernames) and bot_username not in mentioned_bot_usernames`（`:6165`）。驗證方式，第三者在自己跑 Hermes gateway 的 forum group 照做：(1) 在 General 發一則只 @ bot B 的訊息，期望 bot A 不回；(2) 對照組——同一則改成同時 @ bot A 與 bot B，期望 bot A 回；(3) 讀 adapter 原始碼確認兩個判斷的先後（行號隨版本變，以函式名定位）。對照組 (2) 於本 repo 未實跑，由 Hermes 上游測試 `tests/gateway/test_telegram_group_gating.py::test_collectible_username_not_suppressed_by_other_bot_mention`（@jarvis ＋ @other_bot 同一則仍交給 jarvis）支撐；協調位 2026-10-04 以 `~/.hermes/hermes-agent/venv/bin/python -m pytest … -k collectible_username_not_suppressed_by_other_bot_mention -q` 實跑 → 1 passed。受測環境（`R10`）：首次驗證＝最近確認 2026-09-30（觀察）、2026-10-04（上游測試）；Hermes `v0.21.5+3584.g38e416d (2026.9.24)`，`exclusive_bot_mentions` 未設（預設 `true`）；執行身分為裁決位（群組 creator）發言、三個 seat bot（administrator）接收；目標環境 forum group `-1003546152597` General；證據：`#258` K4 材料留言（上方連結）「另三個已知的通道側操作知識」第一項、PR #282 核方向留言（協調位實查 `dfimpl/config.yaml:23,25`、`dfrev/config.yaml:47,49` 與上游測試）） |
| session 與 thread 的綁定 | coordinator | 協調平台的一個 gateway session 綁定建立它的 thread（topic），agent 無法自行遷移。在 topic 內提問，回覆落進該 topic 自己的獨立 session；在 General 開始的對話不會因為 @ 到別的 topic 而搬過去。現行分工（協調對話留 General、執行記錄投影進 topic）由此限制而定，不是偏好 | ✅ 可用（實測：`#228` 兩次嘗試在 topic 內以提問工具向人提問、回覆都落回 topic 的獨立 session 而非原對話；`#247` 258 則訊息全落在 General、topic（thread `669`）只收到投影。驗證方式，第三者在自己跑 Hermes gateway 的 forum group 照做：(1) 在 General 與 bot 開始一段對話，請它記住一個暫時值；(2) 到任一 topic 內問 bot 該值，期望它答不出（topic 是另一個 session）；(3) 對照組——回 General 問同一值，期望答得出。受測環境（`R10`）：首次驗證 2026-09-27（`#228`，thread `208`）、最近確認 2026-09-30（`#247`，thread `669`）；Hermes `v0.21.5`（`#228` 當時）～`v0.21.5+3584.g38e416d`（`#247`）；執行身分為裁決位（群組 creator）與協調位 bot；目標環境 forum group `-1003546152597`；證據：`#258` K4 材料留言（上方連結）第三項、`#228` 與 `#247` issue body 的 `<!-- devflow:topic thread=… -->` 標記） |

## 建議（非強制）

- **bot 命名**：`<project>_<seat>_bot`（本 repo：`devflow_coord_bot`、`devflow_mgr_bot`、`devflow_impl_bot`、`devflow_rev_bot`）。只是建議：Telegram username **全域唯一**，第二個採用同一 `<project>` 前綴的人會撞名，採用前須自行向 @BotFather 確認可用性；撞名時換前綴即可，不影響本表任何一格。

## 已知限制（文件推導，待實測）

- Bot API 無列出 forum topic 的方法；issue 與 topic 的對應須自行維護，forge 上的記載為權威（`README.md` 職能 4）。
- 單結束時 topic 的封存程序、通道四態狀態機：K4b 定義，本表不宣稱。
- 本表三格的驗證方式都需要第三者自備 Telegram forum group 與 ≥2 個 bot；無此環境者只能依 `R9` 當 `📝` 引用。
