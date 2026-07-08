# J-Net21 新着支援情報ウォッチ

J-Net21「支援情報ヘッドライン」の公式RSSから、**補助金・助成金・融資** の情報を毎日 **午前2時（日本時間）** に自動取得し、対象地域（**全国・愛知・岐阜・静岡・三重**）の「本日の新着」をWebページとして表示するシステムです。

- 取得元RSS: https://j-net21.smrj.go.jp/snavi/support/support.xml
- 自動実行: GitHub Actions（無料枠で動作、サーバー不要）
- 閲覧ページ: GitHub Pages（スマホ・PCどちらからでも閲覧可）

---

## セットアップ手順（初回のみ・約10分）

### 1. GitHubリポジトリを作成
1. https://github.com にログイン（アカウントがなければ無料登録）
2. 右上「＋」→「New repository」
3. Repository name: `jnet21-watch`（任意の名前でOK）
4. **Private** を選択しても動作します（Pagesを使う場合、無料プランではPublicが必要）
5. 「Create repository」をクリック

### 2. ファイルをアップロード
1. 作成したリポジトリで「uploading an existing file」をクリック
2. このフォルダの中身（`scripts/`、`.github/`、`README.md`）をドラッグ＆ドロップ
   - ※ `.github` フォルダは隠しフォルダです。Web画面でうまく上がらない場合は、「Add file → Create new file」でファイル名に `.github/workflows/update.yml` と入力し、中身を貼り付けてください
3. 「Commit changes」をクリック

### 3. GitHub Actions の権限を確認
1. リポジトリの Settings → Actions → General
2. 「Workflow permissions」で **Read and write permissions** を選択して Save

### 4. 初回実行（手動）
1. リポジトリの「Actions」タブ →「新着支援情報の自動更新」
2. 「Run workflow」→「Run workflow」で手動実行
3. 1〜2分で完了し、`docs/index.html` が生成されます
   - ※ 初回はRSSに載っている全件が「新着」として表示されます（基準日の作成）。2回目以降から本当の新着だけになります

### 5. GitHub Pages を有効化（閲覧ページの公開）
1. Settings → Pages
2. 「Source」: Deploy from a branch
3. 「Branch」: `main` ／ フォルダ: `/docs` → Save
4. 数分後、`https://（ユーザー名）.github.io/jnet21-watch/` でページが見られます
5. このURLをスマホのホーム画面に追加しておくと、アプリのように使えます

---

## スマホで「アプリ」として使う（PWA）

このシステムはPWA（プログレッシブWebアプリ）に対応しています。ホーム画面に追加すると、専用アイコンから起動でき、ブラウザの枠なしで全画面表示されます。App Store／Google Playは不要です。

**iPhone（Safari）**
1. 公開ページ（`https://（ユーザー名）.github.io/jnet21-watch/`）をSafariで開く
2. 画面下の共有ボタン（□に↑）→「ホーム画面に追加」
3. 「新着補助金」というアイコンが追加されます

**Android（Chrome）**
1. 公開ページをChromeで開く
2. メニュー（︙）→「ホーム画面に追加」または「アプリをインストール」

一度読み込んだページはオフラインでも表示できます（前回取得分のキャッシュ）。

---

## 毎日の動き

| 時刻（JST） | 動作 |
|---|---|
| 午前2:00 | GitHub Actionsが自動起動 → RSS取得 → 対象地域を抽出 → 前日までのデータと照合して新着判定 → ページ更新 |
| いつでも | ページを開くと「本日の新着」＋過去14日分の履歴が見られます |

※ GitHub Actionsのスケジュール実行は混雑状況により数分〜数十分遅れることがあります（GitHubの仕様）。

## カスタマイズ

`scripts/fetch_news.py` の冒頭で変更できます。

- `TARGET_REGIONS` … 対象地域の追加・削除（例: `"長野県"` を追加）
- `ARCHIVE_DAYS` … 履歴の表示日数（初期値14日）
- セミナー・イベント情報も見たい場合は、`RSS_URL` を `https://j-net21.smrj.go.jp/snavi/event/event.xml` にしたコピーを作れば同様に動きます

## 注意事項

- 本システムは J-Net21（中小機構）の公式RSSを1日1回取得するだけの軽量な仕組みです
- 掲載情報の正確性・最新性は、必ず各制度のリンク先（公式ページ）でご確認ください
