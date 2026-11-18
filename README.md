# php-mysql-incompat-scan

PHP 5.3→8.5 / MySQL 5.1→8.4 LTS のバージョンアップで問題になる非互換を、ソースコード・設定ファイル・設計書から機械抽出するオフラインスキャナ。

> **English summary** — A single-file, standard-library-only Python scanner that locates PHP 5.3→8.5 and MySQL 5.1→8.4 incompatibilities in
> PHP/SQL sources, `php.ini` / `my.cnf`, and design documents (xlsx / docx / pptx). It is built for air-gapped environments where
> Composer-based tools or AI assistants are not available. Rule descriptions and reports are in Japanese.

- Python 3.11 以上、**標準ライブラリのみ**（pip・ネットワーク不要）。`incompat_scan.py` 1 ファイルを持ち込めば動く
- パターンルール 205 本 + ファイル単位チェック 8 種。各検出に「対象・影響・修正方針」が付く（一覧: [docs/RULES.md](docs/RULES.md)）
- 日本語環境向け: SJIS / EUC-JP ソースの自動判定、SJIS の 5C 文字、全角英数字の設計書、`sjis`/`cp932`・照合順序まわりのルール
- Excel 設計書はセル・図形（テキストボックス）・コメント単位で位置を出力
- 対象フォルダは読み取りのみ

出力例: [docs/sample_report.html](docs/sample_report.html)

## 位置づけ

PHP の構文・API の検出は [PHPCompatibility](https://github.com/PHPCompatibility/PHPCompatibility) や [Rector](https://github.com/rectorphp/rector)、
MySQL のアップグレード可否は MySQL Shell の `util.checkForServerUpgrade()` の方が正確。それらが使えるならそちらを一次情報にすること。
本ツールが補うのは次の範囲。

- Composer や外部ツールを持ち込めない閉域環境での一次調査
- PHP コード中の SQL 文字列、`my.cnf` / `php.ini`、PHP–MySQL 連携（文字コード・認証・エラーモード）
- 設計書（Office 文書）に書かれた前提・関数名・設定値の洗い出し
- 影響調査の証跡（0 件のルールも含む一覧、判定記入欄付き CSV）

## インストール

`incompat_scan.py` をコピーするだけでよい。pip を使う場合:

```
pip install git+https://github.com/mytooyo/php-mysql-incompat-scan.git
incompat-scan <調査対象フォルダ> -o <出力フォルダ>
```

## 実行

```
python incompat_scan.py <調査対象フォルダ> -o <出力フォルダ>
```

| オプション | 内容 |
| --- | --- |
| `--audit` | 監査ルール（確度C）も有効化。`==` 比較・`count()`・`switch`・`LIMIT` など、サイレントな挙動変更の候補を広く拾う。件数が大きく増える |
| `--no-heuristic` | 確定（確度A）のみ |
| `--only PHP80,SQL` / `--skip DOC` | ルールID前方一致で限定 / 除外 |
| `--skip-comments` | コメント行と判定した行を除外（既定は「コメント行=Y」を付けて出力） |
| `--exclude-dir vendor` | ディレクトリ名で除外（複数指定可）。`.git` `.svn` `node_modules` 等は既定で除外 |
| `--all-text` | 未知の拡張子のテキストも設計書として走査 |
| `--csv-encoding cp932` | CSV を CP932 で出力（既定は UTF-8 BOM 付き。Excel でそのまま開ける） |
| `-j N` | 並列プロセス数（既定は CPU 数に合わせ自動。`-j 1` で並列なし） |
| `--list-rules` / `--dump-rules rules.json` | ルール一覧表示 / JSON 出力 |

推奨手順: まず既定（確度A・B）で実行して `summary.csv` で全体量を把握 → 重要度「高」から `findings.csv` を消化 →
最後に `--audit --only PHP80,PHP72-01,SQL56-05` などで監査ルールを範囲を絞って実行。

処理時間の目安: 単一プロセスで 100 万行あたり約 5 分（並列数に応じて短縮）。

## 出力

| ファイル | 内容 |
| --- | --- |
| `report.html` | 件数サマリ、ルール別件数、該当の多いファイル、ルール別明細（先頭 200 件）、限界の説明 |
| `findings.csv` | 全該当箇所。重要度・確度・ルールID・ファイル・位置・行抜粋・対象・影響・修正方針・整理書参照。末尾に「判定／担当／備考」の記入欄 |
| `summary.csv` | 全ルールの件数（0 件のルールも含む＝調査済みの証跡） |
| `files.csv` | 走査した全ファイルの種別・文字コード・件数・状態（未対応／読取不可を含む） |
| `manual_checklist.csv` | 静的に検出できない項目と確認方法（実行ログ収集、調査 SQL 等） |

「位置」はソースは `L行番号`、my.cnf は `L行番号 [節]`、Excel は `シート名!セル` / `シート名!図形#n`、
Word は `段落n`、PowerPoint は `スライドn-m`。

## 走査対象

| 種別 | 判定 | 適用ルール |
| --- | --- | --- |
| PHP ソース | `.php .inc .phtml .tpl .ctp .html .htm` ほか、拡張子不明で先頭に `<?` を含むもの | PHP・SQL・連携 |
| SQL / スクリプト / 設定 | `.sql .ddl .sh .bat .ps1 .pl .xml .yml .json .env .a5er` ほか | SQL・連携 |
| PHP 設定 | `php.ini` `.user.ini` `.htaccess` `httpd*.conf` `php-fpm*.conf` | php.ini |
| MySQL 設定 | `my.cnf` `my.ini` `*.cnf` | my.cnf（節を追跡） |
| 設計書（Office） | `.xlsx .xlsm .docx .pptx .vsdx`（セル・図形・コメント・段落・スライド・ノート） | 全ルール＋設計書キーワード |
| 設計書（テキスト） | `.txt .md .csv .tsv .rtf` | 同上 |
| 設計書（旧 Office） | `.xls .doc .ppt` — 文字列の簡易抽出。位置は概算、取りこぼしあり | 同上 |
| 未対応 | `.pdf .vsd .jtd` 等、パスワード付き Office、画像 | `files.csv` に「未対応／読取不可」として列挙 |

- 文字コードは UTF-8 / EUC-JP / SJIS(CP932) / ISO-2022-JP を自動判定。
- 設計書のテキストは NFKC 正規化して照合（全角英数字「ＰＨＰ５．３」「ｍｙｓｑｌ＿ｑｕｅｒｙ」も一致）。

## 確度と重要度

- 確度 A（確定）: 一致すれば原則対応が必要。
- 確度 B（要確認）: 該当の可能性あり。目視で要否を判定。
- 確度 C（監査）: 型に依存するサイレントな変更の候補。`--audit` 指定時のみ。
- 重要度 高: 起動不能・Fatal・データ破損・サイレントな挙動変化 ／ 中: 警告や一部機能停止 ／ 低: 非推奨。

## 限界（必ず読むこと）

- 行単位の正規表現照合。複数行にまたがる文、変数経由で組み立てる SQL・関数名、`eval` は検出できない。
- 型に依存する非互換（緩い比較、算術、null 渡し、動的プロパティ、static 呼び出し、シグネチャ非互換）は静的に判定できない。
  → `manual_checklist.csv` の方法（新環境での `error_reporting=E_ALL` ログ収集、`php -l`、general_log 再生）で補完する。
- 「0 件」は該当なしの証明ではない。特に設計書は表記ゆれ・図・画像内文字を拾えない。
- 対象環境に PHP 8.x が用意できるなら `php -l` 全ファイル実行、PHPCompatibility / Rector が使えるならそちらを一次情報とし、
  本ツールは SQL・設定・設計書・文字コード・連携部分の補完として使う。

## ガイド参照について

`findings.csv` の「ガイド参照」列（`§5-1` 等）は、ルールの元になった非互換整理ドキュメントの節・項番。
ドキュメントを `docs/incompatibility-guide.md` として同梱する場合の相互参照用で、無くてもツールの動作には影響しない。

## 開発・コントリビューション

```
python -m unittest discover -s tests -v
```

ルールの追加方法、誤検出・検出漏れの報告方法は [CONTRIBUTING.md](CONTRIBUTING.md) を参照。

## 免責

ルールは公式の移行ガイド・リリースノートを基に作成しているが、網羅性・正確性は保証しない。
検出結果は調査の起点であり、対応要否の最終判断は実環境でのテストによること。
スキャン結果には調査対象のファイル名とコード断片が含まれるため、取り扱いに注意すること。

## ライセンス

[MIT](LICENSE)
