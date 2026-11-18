# Changelog

形式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/)、バージョンは [Semantic Versioning](https://semver.org/lang/ja/) に従う。

## [1.0.0] - 2026-11-18

### Added

- パターンルール 205 本（PHP 5.4〜8.5、MySQL 5.5〜8.4、php.ini、my.cnf、PHP–MySQL 連携、設計書キーワード）
- ファイル単位の特殊チェック 8 種（文字コード、SJIS 5C 文字、PHP4 コンストラクタ、ヒアドキュメント終端、バッククォート、date.timezone、ENGINE 未指定）
- xlsx / docx / pptx / vsdx の本文抽出、旧 Office 形式の簡易抽出
- 出力: findings.csv / summary.csv / files.csv / manual_checklist.csv / report.html
- 並列実行（`-j`）、ルール一覧出力（`--list-rules` / `--dump-rules` / `--export-rules-md`）
