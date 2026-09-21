# kit 發版程序

本檔只適用於 **agent-devflow kit 自己的發版**——把 main 上的某個 commit 標成 kit release tag
`v<a.b.c.d>` 並讓人類站建出對應版本；**消費者專案不跑這份程序**，它們消費的是已發的 tag。
兩條前提全程不放寬：tag 名就是 `devflow/VERSION` 的值前面加 `v`（`V4`），且 tag 只打在 main
已含的 commit、已發版本不移動、不刪、不重打（`V5`）。

五個步驟依序跑。每步一個可以整段貼進終端機的區塊，**步驟之間不共用 shell 變數**：每步各自
重算 `tag` 與 `sha`，所以隔一天再跑、中途換了終端機都不怕；但**重跑時一律從步驟 1 起**——步驟 2 的讀回只斷言 tag 指向 `$sha` 且為 annotated，分支、VERSION 與 tag 名相符這三項只在步驟 1 檢查。每個區塊第一行
就切到 repo 根，從 repo 內哪個目錄起跑都一樣。

`V5` 在 GitHub 端有機械保證：tag ruleset `23780350` 擋掉對 `refs/tags/v*` 的移動與刪除。
機制、驗證方式與受測環境見 `forges/github.md` 的「tag 保護」格，本檔不重述（`I5`）。

## 1. 前置檢查

四項任一不成立就停在原地，不要往下走。四項分別擋掉：發到一半的本機修改、發錯分支或發到還沒
進 main 的 commit、tag 名與 `devflow/VERSION` 對不上、以及重發一個已經存在的版本。

```bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

tag="v$(cat devflow/VERSION)"
fail() { echo "💥 $1"; exit 1; }

# (1) 工作樹乾淨：要發的是 main 上那份內容，不是本機還沒進 main 的東西
[ -z "$(git status --porcelain)" ] || fail "工作樹不乾淨（git status --porcelain 有輸出）"

# (2) 在 main，且與 origin/main 同 sha（V5：tag 只打在 main 已含的 commit）
git fetch --quiet origin main
branch="$(git rev-parse --abbrev-ref HEAD)"
[ "$branch" = "main" ] || fail "不在 main，目前在 $branch"
sha="$(git rev-parse origin/main)"
[ "$(git rev-parse HEAD)" = "$sha" ] \
  || fail "HEAD $(git rev-parse HEAD) 與 origin/main $sha 不同；先把該進 main 的都合進去再發"

# (3) devflow/VERSION 的值與將打的 tag 名一致（V4）
printf '%s' "${tag#v}" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' \
  || fail "devflow/VERSION 不是四碼 a.b.c.d：$(cat devflow/VERSION)"
[ "$tag" = "v$(git show "$sha:devflow/VERSION")" ] \
  || fail "工作樹的 devflow/VERSION 與 origin/main 上的不同，tag 名會標到錯的版本"

# (4) 該 tag 尚不存在於遠端（V5：已發版本不重打）
[ -z "$(git ls-remote origin "refs/tags/$tag")" ] \
  || fail "$tag 已存在於遠端；已發版本不移動、不刪、不重打，修正走下一版"

echo "✅ 前置檢查四項通過：要發 $tag，指向 origin/main $sha"
```

## 2. 建 annotated tag

`-a` 是 annotated：產生一個帶訊息、作者與時間的 tag 物件；lightweight tag 沒有這些，
`gh` 與人類站也讀不到訊息。打的位置固定是 `origin/main` 的 sha（`V5`）。

```bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

tag="v$(cat devflow/VERSION)"
git fetch --quiet origin main
sha="$(git rev-parse origin/main)"

# 訊息一行就夠：本版帶進來的變更逐條住 README 事實表與各 PR，tag 訊息不重述（I5）
git tag -a "$tag" "$sha" -m "kit $tag"

# 讀回：指到 origin/main 那個 commit，而且真的是 annotated（物件型別 tag）
[ "$(git rev-parse "$tag^{commit}")" = "$sha" ] \
  || { echo "💥 $tag 沒指向 origin/main $sha"; exit 1; }
[ "$(git cat-file -t "$tag")" = "tag" ] \
  || { echo "💥 $tag 不是 annotated tag"; exit 1; }
git log -1 --format='%H %s' "$tag"
```

## 3. push tag

只推這一個 tag，refspec 寫全名。推上去的瞬間 `docs.yml` 的 `push: tags: ["v*"]` 會被觸發，
所以推完直接接步驟 4。

```bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

tag="v$(cat devflow/VERSION)"

git push origin "refs/tags/$tag"

# 讀回：遠端那個 ref 指的就是本機剛建的 tag 物件
remote="$(git ls-remote origin "refs/tags/$tag" | cut -f1)"
[ "$remote" = "$(git rev-parse "$tag")" ] \
  || { echo "💥 遠端 $tag 是 $remote，與本機 $(git rev-parse "$tag") 不同"; exit 1; }
echo "✅ 已推 $tag → $remote；docs.yml 應已被 tag push 觸發，接步驟 4"
```

## 4. 確認 docs workflow

等該 tag 的 run 跑成功，再從**站上**讀回 `versions.json`——run 綠只代表 workflow 沒報錯，
站上真的多一個版本要自己讀。本 tag 是已建版本中最高版時，`latest` 必須掛在它身上；
回填舊 tag 時 `latest` 本來就不會動，所以只在最高版時檢查這一項。

```bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

tag="v$(cat devflow/VERSION)"
repo="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"

# tag push 觸發的 run，headBranch 就是 tag 名；用環境變數餵 jq，省掉引號層層轉義
run="$(TAG="$tag" gh run list --workflow=docs.yml --limit 20 \
         --json databaseId,headBranch \
         --jq '[.[] | select(.headBranch == env.TAG)] | first | .databaseId')"
[ -n "$run" ] && [ "$run" != "null" ] \
  || { echo "💥 找不到 $tag 的 docs run；見「失敗處置」"; exit 1; }
gh run watch "$run" --exit-status

# 站上讀回：versions.json 要含本 tag；本 tag 是最高版時 latest 要指向它
vj="$(mktemp)"
trap 'rm -f "$vj"' EXIT
curl -fsS "https://${repo%%/*}.github.io/${repo##*/}/versions.json" -o "$vj"
TAG="$tag" python3 - "$vj" <<'PY'
import json, os, re, sys
vs = json.load(open(sys.argv[1], encoding="utf-8"))
tag = os.environ["TAG"]
hit = [v for v in vs if v.get("version") == tag]
if not hit:
    sys.exit("💥 versions.json 沒有 %s，只有 %s" % (tag, [v.get("version") for v in vs]))
four = [v for v in vs if re.fullmatch(r"v\d+\.\d+\.\d+\.\d+", v.get("version", ""))]
top = max(four, key=lambda v: [int(x) for x in v["version"][1:].split(".")])
if top["version"] == tag and "latest" not in hit[0].get("aliases", []):
    sys.exit("💥 %s 是最高版本，latest 卻不在它身上" % tag)
print("✅ versions.json 含 %s；latest 指向 %s" % (tag, top["version"]))
PY
```

## 5. 從 tag 重裝驗證

發版的成品是「別人 clone 得到、裝得起來的那份 kit」，不是本機工作樹。所以從 tag 淺 clone
一份出來，對一個消費者 repo 跑 `--dry-run`：安裝器會走完整個決策階段、印出會寫什麼，
但不寫任何檔。`CONSUMER_REPO` 給已存在的消費者 repo 路徑；不給就現場 clone 一份 e2e repo。

```bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

tag="v$(cat devflow/VERSION)"
url="$(git remote get-url origin)"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# 拿到的必須是 tag 上那份 kit，不是本機工作樹
git clone --branch "$tag" --depth 1 "$url" "$work/kit"

consumer="${CONSUMER_REPO:-}"
if [ -z "$consumer" ]; then
  consumer="$work/consumer"
  gh repo clone AugustusHsu/devflow-e2e "$consumer" -- --depth 1
fi

python3 "$work/kit/devflow/install.py" "$consumer" --dry-run
echo "✅ $tag 可從 tag 重裝：install.py --dry-run 對 $consumer exit 0（未寫任何檔）"
```

## 禁止事項

`V5` 的內容是「已發版本不移動、不刪、不重打」，對應到四件**不做**的事：

- `git push --force`（或 `git push -f`）到任何 `refs/tags/v*`。
- `git tag -d` 掉已發的 tag 之後重打同名。
- `git push --tags`：它會把本機所有 tag 一起推上去，含還不該發的、含步驟 2 打壞留著的。
  發版一次只推一個 tag，指令見步驟 3。
- 對已發 tag 做任何移動——改指另一個 commit、或先刪再建，兩者都是移動。

需要修正時發**下一版**：改內容 → 進位 `devflow/VERSION`（`V7`）→ 走一次本程序。
tag ruleset `23780350` 只擋**移動與刪除**（第一、二、四條會在 GitHub 端得到 `GH013`，連 admin 也不能繞）；
**建立新 tag 不受 ruleset 管**，所以第三條 `git push --tags` 只能靠本程序擋——而且推錯的 tag 因同一個 ruleset 刪不掉，只能燒版號。
規則先於機械保證：不要為了繞過去而改 ruleset。

## 失敗處置

- **tag 已 push，但 docs run 失敗**：修 workflow（進 main 仍走 PR，`I3`），
  再用 `workflow_dispatch` 對同一個 tag 回填：`gh workflow run docs.yml --ref main -f tag=<tag>`。
  **不**刪 tag 重打——tag 指的內容沒有錯，錯的是建站工具鏈，而工具鏈本來就固定取 main，
  修好的 main 直接就是回填時會用的那份。
- **步驟 1 第 (4) 項發現 tag 已存在於遠端**：那一版已經發過了。確認 `devflow/VERSION`
  是不是忘了進位（`V7` 由 CI 的 `v7` 關卡擋在 PR 階段），補進位後走下一版，不重發同名。
- **步驟 2 打錯位置，但還沒跑步驟 3**：這個 tag 還沒推出去、還不是「已發版本」，
  移除本機那個同名 tag 之後重跑步驟 2 即可。一旦跑過步驟 3 就不適用，改走下一版。
- **步驟 5 裝不起來**：tag 已經發出去了，不回收。開 issue 修安裝器，走下一版；
  同時在 README 事實表記下該版的已知問題。
