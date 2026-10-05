# channels/scripts/telegram — telegram 通道的參考實作

本目錄是 `telegram` 通道的參考實作腳本。「參考實作，非通用」的邊界、以及為什麼腳本住這層而非 repo 根 `scripts/`，見 `../../README.md` 「為什麼這層會有實作」。

## 目錄內容

| 檔 | 用途 |
|---|---|
| `_marker.py` | `CH3` 分區標記 grammar 的**單一實作**：`T`／`A` 兩式的正則、正向查找（issue body → thread id）、反向查找（thread id → 是否屬此 body）、upsert 寫入、`T>1`／`A>1` 的 INVALID 判定。下列兩支腳本的 marker 讀寫全部走它，不各寫一份近似邏輯 |
| `devflow_topic.py` | issue 與 forum topic 的對應：`ensure` 取得或建立分區、`close` 結案時關閉、`sync` 從 forge 重建本機 cache。權威一律在 issue body 的標記，本機 JSON 只是加速用的 cache |
| `devflow_archive.py` | 分區封存：匯出（MD 人讀 ＋ JSON 全量）、發到 archives 分區、刪除原分區、清 cache |
| `devflow_relay.py` | 把 agent 的事件流轉播到該單的分區（工具呼叫摘要與進度）。摘要邏輯 `tool_summary` 與 `devflow_archive.py` 共用 |

## `_marker.py` 的落點與上移觸發條件

`_marker.py` 現在與腳本**同層**，因為兩支使用者（`devflow_topic.py`、`devflow_archive.py`）都在本目錄，同層 import 不需要任何 `sys.path` 操作——放父層經實測為 `ModuleNotFoundError: No module named '_marker'`，必須補回一行 `sys.path.insert(parent)`，而那行正是 `#285` 拔掉的病根（`devflow_relay.py` 原 `:33` 把未 resolve 的 symlink 目錄插到 realpath 前面，使經 symlink 執行時 import 到舊檔）。

**上移觸發條件：下一個 channel 出現時，`_marker.py` 上移至 `channels/scripts/`。** 屆時 grammar 的使用者不再只有 telegram，留在本目錄會讓別的 channel 得跨目錄 import（又要 path 操作）或複製一份（grammar 再度分叉，正是本檔要防的事）。上移時兩支腳本的 `import _marker` 需改為當時目錄結構下可解析的形式，不預先設計。

⚠️ **這是記載的意圖，不是機械關卡**：沒有任何檢查會在第二個 channel 出現時強制上移，`devflow_checks.py` 與 `tests/` 都不驗這件事。它依賴當時的實作者讀到本節。

## grammar 的權威在條文，不在本目錄

`_marker.py` 的 `TOPIC_RE`／`ARCHIVED_RE` 兩個常數**須與 `../../README.md`「分區三態」判定式（`:59`）的字面逐字相同**，`tests/channels/test_marker.py`（`AC-6`）以字串相等比對把關，並對「改一個字元」有鑑別力。要改判準得走 `G2` 開新單改條文，不是改這裡的常數。

兩式都只錨行首行尾（`^…$`），**不解析 markdown**：表格列內（行首 `|`）、縮排、散文旁註的同形字串一律不算標記（`../../README.md:63`「標記必須是獨立一行才算」）。**不得**在實作裡加上「排除 fenced code block」「跳過表格」之類的寬鬆化——那會使實作偏離條文，正是 `#285` 修掉的病。

## 驗證

```bash
/usr/bin/python3 tests/channels/test_marker.py     # AC-1～AC-7，純字串 fixture、零 Telegram API
```

本目錄的 `.py` 全檔**零 `sys.path` 操作**（受檢集合是 glob，不是列舉檔名，故新增腳本自動納入）：

```bash
grep -nE 'sys\.path' devflow/channels/scripts/telegram/*.py    # 期望無命中
```

## 已知未修的缺陷

`devflow_archive.py` 的 `scan`／`publish`／cache 三處缺陷屬 `#287`，`#285` 只修 `issue_meta` 的反向查找這一處。
