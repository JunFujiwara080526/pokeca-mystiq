# Mystiq デプロイ手順書（GitHub ＋ Render ＋ Xserverドメイン）

この手順書に従えば、**完全無料で**あなたの謎解きアプリを世界中からアクセスできる状態（独自ドメイン `pokeca-j-league.info`）にできます。

---

## 準備（所要時間：約15〜30分）

必要なもの：
- [ ] [GitHub](https://github.com/) アカウント（未登録なら無料登録、1分）
- [ ] [Render](https://render.com/) アカウント（GitHub連携ログインで一瞬）
- [ ] [エックスサーバーの管理パネル](https://secure.xserver.ne.jp/xapanel/login/xdomain/) ログイン情報（ドメイン購入時のもの）

---

## パート1：GitHubにアプリを置く

ローカルのリポジトリ初期化・初回コミットは**すでに完了**しています。あとはGitHubにアップロード（push）するだけです。

### 1-1. GitHubで空のリポジトリを作る

1. [GitHub](https://github.com/) にログイン
2. 右上の **「＋」** → **「New repository」** をクリック
3. 以下を設定して一番下の **「Create repository」** をクリック：
   - **Repository name**: `pokeca-mystiq`（英数小文字なら何でもOK）
   - **Public / Private**: どちらでも構いません（Private推奨）
   - **「Add a README file」などのチェックはすべて外したまま**（空リポジトリにする必要があります）
4. 作成後に表示されるリポジトリのURL（例: `https://github.com/あなたのID/pokeca-mystiq`）をコピー

### 1-2. コードをアップロードする

**私にURL（`https://github.com/あなたのID/pokeca-mystiq`）を教えていただければ、push直前の設定とコマンド実行まで手元で進めます。**

ご自身でターミナルから行う場合は以下を実行します：

```bash
cd /Users/fujiwarajun/Documents/Manus/2026-11-11/sE4x7c/outputs/mystiq
git remote add origin https://github.com/あなたのユーザー名/pokeca-mystiq.git
git push -u origin main
```

> **パスワード入力を求められた場合**：GitHubでは2021年以降、通常のパスワードではなく **Personal Access Token（PAT）** を使います。[GitHubのトークン生成ページ](https://github.com/settings/tokens)（「Generate new token (classic)」）で `repo` にチェックを入れて作成し、そのトークンをパスワード欄に入力してください。または、無料の [GitHub Desktop](https://desktop.github.com/) を使えば画面操作だけで完了します。

---

## パート2：Renderにデプロイする（無料）

GitHubへのpushが完了したら、次はRenderでアプリを起動します。

1. [Render](https://render.com/) にアクセスし、**「Sign in with GitHub」** でログイン（連携を許可）
2. 画面右上の **「New +」** ボタン → **「Web Service」** をクリック
3. 「Git provider」から **「GitHub」** を選択し、さきほど作った `pokeca-mystiq` リポジトリの横にある **「Connect」** をクリック
   - 一覧に出ない場合は「Configure account」からリポジトリへのアクセスを許可してください
4. 以下の表のとおりに入力・選択します：

| 設定項目 | 入力値 | 備考 |
| --- | --- | --- |
| **Name** | `pokeca-mystiq` | URLの一部になります（英数小文字） |
| **Region** | `Singapore` または `Oregon` | 日本から近いSingaporeがおすすめ |
| **Branch** | `main` | 初期値のままでOK |
| **Root Directory** | （空欄） | このままでOK |
| **Runtime** | `Python` | 自動検出されます |
| **Build Command** | （空欄） | Python標準ライブラリのみ使用のためビルド不要 |
| **Start Command** | `python3 server.py` | これだけ入力 |
| **Instance Type** | **Free** | 必ず「Free」を選択（完全無料） |

5. 下にスクロールして **「Advanced」** を開き、**「Add Environment Variable」** で環境変数を2つ追加：

| Key | Value | 意味 |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | クラウドで全IPからのアクセスを受け入れる設定 |
| `ADMIN_PASSWORD` | あなたが考えたパスワード（英数8文字以上） | **管理画面のログインパスワード**になります。忘れないようにメモしてください |

6. 一番下の **「Create Web Service」** をクリック

7. ログが流れ始め、2〜5分で **「Your service is live」** と表示されたら成功です！
   - 画面上部に `https://pokeca-mystiq.onrender.com` のような専用URLが表示されます。これがあなたのアプリのクラウドURLです

### 動作確認チェックリスト

- [ ] `https://〇〇.onrender.com/` → 回答画面が表示され、スマホからも開ける
- [ ] `https://〇〇.onrender.com/screen.html` → 実況画面が表示される（これが別会場用）
- [ ] `https://〇〇.onrender.com/admin.html` → 設定した `ADMIN_PASSWORD` でログインできる
- [ ] `https://〇〇.onrender.com/api/healthz` → `{"ok": true, ...}` とJSONが返る

> **💡 Render無料枠の重要仕様**
> - **15分アクセスがないと一時休止**します。次回アクセス時に**約30〜50秒の起動待ち**が発生します
> - **大会当日の対策**：開始10分前に管理者がブラウザで一度アクセスしておけば、大会中に休止することはありません
> - **再起動時にDBがリセット**されるため、**大会終了後は管理画面右上の「💾 データバックアップ」ボタンで解答記録（JSON）をPCに保存**してください。問題データはGitHubで守られているため消えません

---

## パート3：エックスサーバー側でドメインを紐づける

`pokeca-j-league.info` でアクセスできるようにします。

1. **Render側でカスタムドメインを追加**
   - Renderの `pokeca-mystiq` サービス画面 → 左メニュー **「Custom Domains」**
   - **「Add Custom Domain」** → `pokeca-j-league.info` を入力して追加
   - 画面に「DNS設定情報（CNAME または A レコード）」が表示されます（コピーできるように画面を開いたままにしておく）

2. **Xserverドメイン側でDNSレコードを登録**
   - [Xserverドメイン会員パネル](https://secure.xserver.ne.jp/xapanel/login/xdomain/) にログイン
   - **「ドメイン管理」** → 対象ドメイン（`pokeca-j-league.info`）の **「DNSレコード設定」** を開く
   - **「DNSレコード追加」** を選択し、Renderの画面に表示された値を入力：
     - **種別（タイプ）**：Render指示どおり（通常は `CNAME` または `A`）
     - **ホスト名**：ルートドメインの場合は空欄または `@`、`www` 用なら `www`
     - **内容**：Render画面に表示された値（例: `pokeca-mystiq.onrender.com`）
     - **TTL**：3600のままでOK
   - **「確認画面へ進む」→「追加する」**

3. **反映確認**
   - DNS設定の反映には**数分〜数時間**かかります（気長にお待ちください）
   - Render側が自動的に無料SSL証明書を発行します
   - `https://pokeca-j-league.info` をブラウザで開いて回答画面が出れば完了！

---

## パート4：別会場での最終確認（大会本番前）

1. 別会場のプロジェクター/大型モニターに接続されたPCまたはタブレットを用意
2. ブラウザで **`https://pokeca-j-league.info/screen.html`** を開く
3. ブラウザを**全画面表示**（Mac: `Ctrl + Cmd + F`、Windows: `F11`）
4. スマホから `https://pokeca-j-league.info` を開いてテストで1問回答し、実況ボードの順位表に即座（約2.5秒以内）に反映されることを確認

---

## トラブルシューティング

| 現象 | 対処 |
| --- | --- |
| 最初のアクセスが30秒以上かかる | 無料枠のコールドスタート。一度動けば大会中は正常に戻ります |
| 管理画面に入れない | Renderの「Environment」で `ADMIN_PASSWORD` を再設定し保存すれば即反映 |
| ドメインで開けない | DNS設定の反映待ち（最大24時間）の可能性。まずは Render の専用URLで確認を進めてください |
| 大会の記録を残したい | 管理画面右上の「💾 データバックアップ」ボタンでJSONをDL保存 |

---

何か引っかかる点があれば、画面の様子を教えていただければすぐに対応できます。
