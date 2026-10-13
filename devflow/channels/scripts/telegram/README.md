# channels/scripts/telegram — telegram 通道的參考實作

本目錄是 `telegram` 通道的參考實作腳本。「參考實作，非通用」的邊界、以及為什麼腳本住這層而非 repo 根 `scripts/`，見 `../../README.md` 「為什麼這層會有實作」。

## 目錄內容

| 檔 | 用途 |
|---|---|
| `_marker.py` | `CH3` 分區標記 grammar 的**單一實作**：`T`／`A` 兩式的正則、正向查找（issue body → thread id）、反向查找（thread id → 是否屬此 body）、upsert 寫入、`T>1`／`A>1` 的 INVALID 判定，以及狀態層的 `preserve_state`（一般修訂保留現行標記）與 `compare_state_lines`（完整標記行的通用比較，唯讀）。下列兩支腳本的 marker 讀寫全部走它，不各寫一份近似邏輯 |
| `devflow_topic.py` | issue 與 forum topic 的對應：`ensure` 取得或建立分區、`close` 結案時關閉、`sync` 從 forge 重建本機 cache、`edit-body` 改 body 的一般內容（保留狀態標記並讀回驗證）。權威一律在 issue body 的標記，本機 JSON 只是加速用的 cache |
| `devflow_archive.py` | 分區封存：匯出（MD 人讀 ＋ JSON 全量）、發到 archives 分區、刪除原分區、清 cache |
| `devflow_relay.py` | 把 agent 的事件流轉播到該單的分區（工具呼叫摘要與進度）。摘要邏輯 `tool_summary` 與 `devflow_archive.py` 共用 |

## `_marker.py` 的落點與上移觸發條件

`_marker.py` 現在與腳本**同層**，因為兩支使用者（`devflow_topic.py`、`devflow_archive.py`）都在本目錄，同層 import 不需要任何 `sys.path` 操作——放父層經實測為 `ModuleNotFoundError: No module named '_marker'`，必須補回一行 `sys.path.insert(parent)`，而那行正是 `#285` 拔掉的病根（`devflow_relay.py` 原 `:33` 把未 resolve 的 symlink 目錄插到 realpath 前面，使經 symlink 執行時 import 到舊檔）。

**上移觸發條件：下一個 channel 出現時，`_marker.py` 上移至 `channels/scripts/`。** 屆時 grammar 的使用者不再只有 telegram，留在本目錄會讓別的 channel 得跨目錄 import（又要 path 操作）或複製一份（grammar 再度分叉，正是本檔要防的事）。上移時兩支腳本的 `import _marker` 需改為當時目錄結構下可解析的形式，不預先設計。

⚠️ **這是記載的意圖，不是機械關卡**：沒有任何檢查會在第二個 channel 出現時強制上移，`devflow_checks.py` 與 `tests/` 都不驗這件事。它依賴當時的實作者讀到本節。

## grammar 的權威在條文，不在本目錄

`_marker.py` 的 `TOPIC_RE`／`ARCHIVED_RE` 兩個常數**須與 `../../README.md`「分區三態」判定式（`:59`）的字面逐字相同**，`tests/channels/test_marker.py`（`AC-6`）以字串相等比對把關，並對「改一個字元」有鑑別力。要改判準得走 `G2` 開新單改條文，不是改這裡的常數。

兩式都只錨行首行尾（`^…$`），**不解析 markdown**：表格列內（行首 `|`）、縮排、散文旁註的同形字串一律不算標記（`../../README.md:63`「標記必須是獨立一行才算」）。**不得**在實作裡加上「排除 fenced code block」「跳過表格」之類的寬鬆化——那會使實作偏離條文，正是 `#285` 修掉的病。

## body 寫入保留狀態標記（`edit-body` 與完整標記行比較）

`CH3` 的狀態權威在 issue body 的兩行機器可讀標記，而 `gh issue edit --body`／`-F` 是**全量取代**不是合併：任何「重新產出一份 body」形式的一般修訂都會把標記抹掉，使該單落回 `T=0 A=0` ＝未開始，下一次執行就重建分區或重做封存並覆寫既有匯出檔。條文側的義務見 `WORKFLOW.md` 的 `CH3`（保存義務〔限定射程〕、適用範圍／例外、讀回義務、串行前提）。

本目錄提供兩個落點：

| 落點 | 用途 |
|---|---|
| `_marker.preserve_state(old_body, new_body, *, detail)` | **非狀態遷移的一般修訂**的寫側：把 old body 的合法狀態標記保存進 new body。**old 為權威**（`thread`、`file=` 皆取 old）；new 試圖**新增** old 沒有的狀態類別時 raise `StateIntroduced` 並拒絕寫入；old／new 的四類 INVALID（`T>1`、`A>1`、`T=0 A=1`、`NN` 不符）raise `InvalidMarker`。讀取順序固定：old 的 INVALID → new 的 INVALID → 偷渡。純字串、零 I/O、零 `gh`，且 `new_body` 一律是回傳值的**逐字前綴**（尾端空白行與 tab 不得被刪，故**不**沿用 `upsert_*` 的 `rstrip()` 追加寫法） |
| `_marker.compare_state_lines(before, after)` | **通用**的完整標記行比較 → `(相同?, 差異描述)`。比的是**整行**（`thread` 與 `file=` 都算），不是 `(T, A, NN)`——只改 `file=` 的那一支會讓計數與兩個 `NN` 全同 |
| `devflow_topic.py edit-body <issue> -F <檔>` | 端到端入口：讀 old body → `preserve_state` → 寫暫存檔（落 `$TMPDIR/devflow-editbody-<issue>/` 這個**該單專屬子目錄**，`C5`；成功／`gh` 失敗／讀回失配三條路徑都在 `finally` 只清本次產物）→ `gh issue edit -F` → **讀回**並以 `compare_state_lines` 逐字比對。不符即 exit 非 0、stderr 印「結果未定」＋單號＋寫入前快照與讀回值的兩組完整標記行，**停下交人**；**不自動重送**（會以同一份過期快照再覆蓋）、**不以舊 body 覆蓋**。讀回失配是**一次寫入的結果未定**，不是「合併成功而收尾失敗」 |

`preserve_state` 與 `upsert_topic`／`upsert_archived` 的界線**不可互換**：後者是**狀態遷移**的寫側（`ensure`／`archive` 已決定新的態，參數是新的 `thread`／`file`），依 `CH3` 的「適用範圍／例外」刻意不受保存義務約束，其正確性驗**預期的新狀態**而不是「標記不變」。故**不得**把 `preserve_state` 插進 `_to_forge`／`cmd_archive`——那等於禁止 `ensure`／`archive` 改標記。

### `compare_state_lines` 的用法與宣稱

⚠️ **工作檔的落點**（`C5`：本單執行期間產生的檔案一律落在該單的專屬子目錄之下）：下例的 before／after 兩份文字**不要**直接寫在暫存根（`/tmp`、`$TMPDIR`），請先開一個以單號命名的專屬子目錄，用畢自行移除——比較器本身唯讀、不會替你清檔。

```bash
N=<issue>; REPO=<owner/repo>
WORK="${TMPDIR:-/tmp}/devflow-statecheck-$N"      # 該單專屬子目錄，不在暫存根留散檔
mkdir -p "$WORK"
gh issue view "$N" -R "$REPO" --json body -q .body > "$WORK/before.md"
#  …（任何方式改 body：edit-body、裸 gh issue edit、gh api -X PATCH、Web UI）…
gh issue view "$N" -R "$REPO" --json body -q .body > "$WORK/after.md"
WORK="$WORK" /usr/bin/python3 - <<'PY'
import importlib.util, os, pathlib, sys
work = pathlib.Path(os.environ["WORK"])
spec = importlib.util.spec_from_file_location(
    "_marker", "devflow/channels/scripts/telegram/_marker.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
same, diff = m.compare_state_lines((work / "before.md").read_text(),
                                   (work / "after.md").read_text())
print("PASS" if same else "FAIL", diff)
sys.exit(0 if same else 1)
PY
rc=$?
rm -rf "$WORK"                                    # 清除步驟：只刪本次自己開的子目錄
exit $rc
```

- **唯讀、可重跑、不自動修復**：它只吃兩個字串並回報，不碰 forge、不打網路、零 I/O，也不會去把標記補回去——補不補、怎麼補由人或呼叫端決定。
- **不綁入口**：`before`／`after` 不必取自 `edit-body`。裸 `gh issue edit`、`gh api -X PATCH`、GitHub Web UI 改出來的兩份 body 一樣能套。
- 四種破壞各自回 `FAIL` 並指出差異：刪掉標記行、改 `thread` 的 `NN`、**只改 `file=`**、新增重複標記（`T>1`／`A>1`）。完全相同回 `PASS`。
- **已知限制（不得略）**：`gh api -X PATCH`、GitHub Web UI 與任何不經本入口的寫入無法攔截；本入口未採用條件更新，不是原子更新。
- 上一條的補充：`讀 → 保存 → 寫 → 讀回` 之間沒有互斥，讀回只核對「讀回值 vs 本入口讀到的舊快照」，**不保證偵測所有 lost update**（另一個寫者在讀取之後改了 body 時，以舊快照覆蓋的結果與舊快照仍可逐字相同）。故同一張 issue 的 body 寫入須**串行**。本目錄**未**實作事後掃描，上面那行聲明也不得被讀成「有掃描在兜底」——掃描不存在，它不是讀回或比較的前提。

### 各義務的檢查手段與 `G4` 位階

`G4` 逐字：「新規則要求的檢查器尚不存在時，先列為建議；工具可執行且正反測試通過後才升為必需關卡。」逐項如實評定：

| 義務 | 檢查手段 | 位階 | 升級條件 |
|---|---|---|---|
| 一般修訂須保留合法狀態標記——**本入口（`edit-body`）** | `preserve_state` ＋ `compare_state_lines` ＋ `tests/channels/test_marker.py` 的正反測試（突變實作與缺陷判準各自轉 FAIL） | **必需**：工具可執行（`/usr/bin/python3 tests/channels/test_marker.py`）且正反測試通過 | — |
| 一般修訂須保留合法狀態標記——**不經本入口的寫入**（裸 `gh issue edit`、`gh api -X PATCH`、Web UI） | 無自動觸發的檢查器；人或呼叫端把該次寫入的 before／after 餵進 `compare_state_lines`（工具本身已可執行且有正反測試） | **建議** | 出現能在寫入前後**自動**取得 before／after 並套用 `compare_state_lines` 的包裝或 CI 檢查，且其正反測試通過。⚠️ 升級**不以「實作事後掃描」為前提**——掃描只是其中一種可能手段 |
| 寫入後須讀回並逐字比對完整標記行 | `edit-body` 的讀回（與 `compare_state_lines` **同一處實作**）＋ 正反測試（讀回只比 `(T, A, NN)` 的缺陷判準會放行「只改 `file=`」，整行比對擋下） | **必需**（射程限於經本入口的寫入） | 其餘入口同上一列 |
| 同一 issue 的 body 寫入須串行 | 無機械檢查器：本目錄不加鎖、lease、重試或監控，串行靠程序安排 | **建議** | 出現可執行的互斥機制（鎖／lease／條件更新）且其正反測試通過 |
| 合法狀態遷移的新狀態正確（`ensure`／`archive`） | 既有通道判準（`../../telegram.md` 的對照表格） | **既有**，本節不改 | — |

三條禁止，引用本節者一併適用：不得把「未實作掃描」當成永久分界；不得預先宣稱尚未驗證的工具可用；不得以「降為建議」替代漏做的 `compare_state_lines`——它是交付物，不是位階問題。

## 驗證

```bash
/usr/bin/python3 tests/channels/test_marker.py     # grammar、upsert、狀態層（純字串 fixture、零 Telegram API）
```

本目錄的 `.py` 全檔**零 `sys.path` 操作**（受檢集合是 glob，不是列舉檔名，故新增腳本自動納入）：

```bash
grep -nE 'sys\.path' devflow/channels/scripts/telegram/*.py    # 期望無命中
```

## 已知未修的缺陷

`devflow_archive.py` 的 `scan`／`publish`／cache 三處缺陷屬 `#287`，`#285` 只修 `issue_meta` 的反向查找這一處。
