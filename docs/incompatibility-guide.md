# PHP 5.3→8.5 / MySQL 5.1→8.4 LTS 非互換整理

Nov 9, 2026 · @Yo Suzuki

## 0. この文書の読み方・前提

PHP 5.3.x → 8.5.x、MySQL 5.1.x → 8.4.x LTS の間に入る非互換を、中間バージョンごとに累積で列挙する。最終的に 8.5 / 8.4 で直面するものは、それを導入したバージョンの節に記載している（例: PHP 7.2 で非推奨・8.0 で削除、は 7.2 の節）。

| 列 | 意味 |
| --- | --- |
| 対象 | 何が変わるか。該当するコード・SQL・設定の具体例 |
| 影響 | どう壊れるか。エラー種別（Fatal / Error 例外 / Warning / Deprecated / 起動不能）と、エラーにならずに結果が変わる「サイレント」な変化を区別 |
| 修正方針 | 恒久対応。移行期のみ使える暫定策は「暫定:」と明記 |
| 重要度 | 高: 起動不能・致命的エラー・データ破損・サイレントな挙動変化。中: 警告や一部機能の停止。低: 非推奨で当面は動く |

前提と用語:

- 旧環境は PHP 5.3 + ext/mysql（`mysql_*`）+ libmysqlclient、MySQL 5.1 は MyISAM 既定・latin1 既定の時代の構成を想定。日本語環境（SJIS/EUC-JP/UTF-8、機種依存文字）に固有の項目を各節に含める。
- PHP の「非推奨」は E\_DEPRECATED を出して動作する。PHP 8.x で非推奨になったものは PHP 9.0 で削除予定。MySQL の「非推奨」は警告付きで動作し、次の LTS 以降で削除される。
- 基準日: 2026-11-09。PHP 8.5.0 は 2025-11-20 リリース（[php.net](https://www.php.net/releases/8.5/en.php)）、MySQL 8.4.0 LTS は 2024-04-30 リリース（[リリースノート](https://dev.mysql.com/doc/relnotes/mysql/8.4/en/news-8-4-0.html)）。MySQL 8.0 は 2026-04 でサポート終了済み。
- PHP–MySQL 連携（ドライバ、認証、文字コード、型、エラー処理）は 14 節にまとめ、各バージョン節からは要点のみ参照する。

## 1. 全体移行戦略

結論: **PHP を先に 7.4（mysqlnd）へ上げ、次に MySQL を 8.0 → 8.4 へ、最後に PHP を 8.x → 8.5 へ**上げる三段構えが最も安全。PHP 5.3 の libmysqlclient は MySQL 8.x に接続できず（照合 ID 255・caching\_sha2\_password）、逆に PHP 8.5 は MySQL 5.1 に接続できるが utf8mb4 が使えないため、どちらか一方だけを先に最終形にすることはできない（組合せの詳細は 15 節）。

### 推奨経路

| 系 | 実機で踏む段 | 理由 |
| --- | --- | --- |
| PHP | 5.3 → 5.6 → 7.4 → 8.0 → 8.5（8.1〜8.4 は静的解析とテストで通過） | 5.6 で非推奨警告を全部拾う。7.4 は mysqlnd で caching\_sha2\_password が安定し MySQL 8 と接続できる最初の実用版。8.0 が最大の非互換の壁。8.1 以降は非推奨中心で、8.5 で一括確認できる |
| MySQL（インプレース） | 5.1 → 5.5 → 5.6 → 5.7（最新 GA）→ 8.0（最新 8.0.x）→ 8.4 | インプレースは 1 メジャーずつしか公式サポートされない。5.7→8.0、8.0→8.4 は直接可。ダウングレード不可 |
| MySQL（論理移行） | 5.1 から mysqldump → 補正 → 8.0 または 8.4 へ import | 5.1 由来データ（旧 TIMESTAMP 既定、ゼロ日付、`TYPE=`、旧時刻フォーマット、latin1 誤宣言）が多い場合はこちらが現実的。ダンプの補正項目は 9〜13 節 |

### 実施順序（推奨）

1. 棚卸し: アプリの SQL を general\_log で 1 営業日分採取、PHP は PHPCompatibility（`testVersion 8.5-`）と Rector のドライランで件数を把握。my.cnf / php.ini は新規に作り直す前提で差分だけ抽出。
2. DB スキーマ正規化（旧 MySQL 上で実施可）: ENGINE 明示と InnoDB 化、ゼロ日付の NULL 化、TIMESTAMP 既定の明示、旧時刻フォーマット列の `ALTER TABLE … FORCE`、ROW\_FORMAT=DYNAMIC、文字コードの実態調査（13 節）。
3. PHP 5.6 化: E\_DEPRECATED を全ログ収集し、ext/mysql → mysqli/PDO 置換（14 節）を DB アクセス層に集約。
4. PHP 7.4 化: Error 例外・統一変数構文・mcrypt・each 等を解消。ここで MySQL 8 と接続できる状態になる。
5. MySQL 8.0 化（ステージングで `util.checkForServerUpgrade()` 合格後）: sql\_mode は一旦旧互換値で起動し、アプリ修正後に既定値へ戻す。照合順序・認証プラグインを決める。
6. MySQL 8.4 化: `default_authentication_plugin` 等の削除変数を my.cnf から除去、全ユーザを caching\_sha2\_password へ。
7. PHP 8.0 → 8.5 化: 比較・型・エラー既定の変更に対応。mysqli 例外既定（8.1）と PDO ネイティブ型（8.1）はここで顕在化する。

### ツール

| 用途 | ツール |
| --- | --- |
| PHP 構文・非互換検出 | `php -l` 全ファイル、PHPCompatibility（phpcs）、Rector（`LevelSetList::UP_TO_PHP_85`）、PHPStan / Psalm、`error_reporting=E_ALL` でのログ収集 |
| MySQL アップグレード前検査 | MySQL Shell `util.checkForServerUpgrade()`（5.7→8.0、8.0→8.4 に対応）、`mysqlcheck --check-upgrade`、`mysqld --validate-config`（8.0.16+、my.cnf の無効変数検出） |
| SQL 回帰 | general\_log を新 DB で再生し `SHOW WARNINGS` と結果を旧 DB と diff（Percona Toolkit `pt-upgrade` が使える） |
| 文字コード | 機種依存文字・絵文字・末尾空白・ゼロ日付を含むテストデータの往復テスト |

### テストで必ず確認する観点

- 文字化け（① ㈱ 〜 － ∥ ￠ ￡ ￢ 髙 﨑 𠮷、絵文字）の入出力往復。
- JSON API の数値型（`"1"` → `1`）の差分。PHP 8.1 の PDO ネイティブ型で変わる。
- GROUP BY / ORDER BY なしの一覧の並び順、派生テーブル内 ORDER BY に依存するクエリ。
- 日時: タイムゾーン（PHP `date.timezone`、MySQL `log_timestamps`）、TIMESTAMP の自動更新、ゼロ日付。
- エラー時の挙動: DB エラーが例外になる前提で、未捕捉例外が 500 にならないか。

## 2. PHP 5.4 / 5.5 / 5.6 の非互換

5.3 → 5.6 の段階で致命的なのは、register\_globals・magic\_quotes の消滅と、`htmlspecialchars` の既定文字コードが UTF-8 になる点（SJIS/EUC-JP サイトは出力が空になる）。5.5/5.6 で非推奨になったものは 7.0 で削除されるので、この段階で E\_DEPRECATED をゼロにしておく。

### PHP 5.4

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 1 | `register_globals`、`register_long_arrays`（`$HTTP_GET_VARS`/`$HTTP_POST_VARS`/`$HTTP_SESSION_VARS` 等）の削除 | 未定義変数として null になり、認証分岐などが無警告で変わる | `$_GET`/`$_POST`/`$_SESSION` へ置換。`extract($_REQUEST)` での代替は脆弱なので不可 | 高 |
| 2 | `magic_quotes_gpc` / `magic_quotes_runtime` / `magic_quotes_sybase` 削除。`get_magic_quotes_gpc()` は常に false（7.4 非推奨、8.0 削除）、`set_magic_quotes_runtime()` は 5.4 で E\_CORE\_ERROR（7.0 削除） | magic quotes によるエスケープを前提にしていた SQL が **SQL インジェクション可能** になる。`stripslashes` 分岐は無害化 | 全入力をプリペアドステートメントまたは `mysqli_real_escape_string` へ。`if (get_magic_quotes_gpc())` 分岐を削除 | 高 |
| 3 | 呼び出し時参照渡し `foo(&$a)` の削除（`allow_call_time_pass_reference`） | Fatal error（コンパイル時） | 関数定義側を `function foo(&$a)` に変更 | 高 |
| 4 | `htmlspecialchars()` / `htmlentities()` / `html_entity_decode()` の既定 charset が ISO-8859-1 → UTF-8。無効な UTF-8 バイト列は空文字を返す | SJIS/EUC-JP で運用しているサイトの出力が **空文字になる（サイレント）** | 第 3 引数で `'SJIS'`（実体は CP932 推奨）/`'EUC-JP'` を明示するか、5.6 以降は `default_charset` を実際の内部エンコードに設定 | 高 |
| 5 | `break 0;`、`break $n;`、`continue 0;` の削除 | Fatal error | 定数リテラルに書き換え | 中 |
| 6 | `session_register()` / `session_unregister()` / `session_is_registered()` と `session.bug_compat_42` / `session.bug_compat_warn` の削除 | Fatal error | `$_SESSION` を直接操作 | 中 |
| 7 | mysqli の旧別名削除: `mysqli_bind_param`、`mysqli_bind_result`、`mysqli_client_encoding`、`mysqli_fetch`、`mysqli_param_count`、`mysqli_get_metadata`、`mysqli_send_long_data`、`mysqli_master_query` / `mysqli_slave_query` / `mysqli_rpl_*` / `mysqli_disable_reads_from_master` 等 | Fatal error | `mysqli_stmt_*` の正式名へ。レプリケーション分散関数は削除してアプリ側で接続先を選ぶ | 中 |
| 8 | `safe_mode`、`register_globals`、`define_syslog_variables`、`y2k_compliance`、`highlight.bg`、`zend.ze1_compatibility_mode` 等の ini 削除、`import_request_variables()` 削除 | 起動時に未知ディレクティブの警告、関数は Fatal | php.ini から除去（8 節） | 低 |
| 9 | 配列→文字列変換が E\_NOTICE、非数値文字列オフセット `$str['abc']` が「Illegal string offset」警告、`isset($str['x'])` が false に | ログ増加、`isset` 判定の反転 | 型を確認して修正 | 低 |
| 10 | `E_ALL` に E\_STRICT を含むように | 非 static メソッドの static 呼び出し等で E\_STRICT が大量に出る | 7.0 で再分類されるので、ここでは `error_reporting` で抑制しつつ件数把握 | 低 |
| 11 | `mbstring.script_encoding` 削除 → `zend.multibyte=On` + `zend.script_encoding` | SJIS で書かれたソースの 5C 問題（「表」「ソ」「能」等を含む文字列リテラル）が Parse error | ソースを UTF-8（BOM なし）へ一括変換するのが最善。暫定: `zend.multibyte=On`、`zend.script_encoding=SJIS` | 高（SJIS ソースの場合） |
| 12 | `date.timezone` 未設定が E\_WARNING（7.0 で警告廃止、UTC 既定） | 7.0 以降は無警告で UTC 時刻になる | php.ini に `date.timezone=Asia/Tokyo` を必ず設定 | 高 |
| 13 | スーパーグローバル名を引数名に使えない（`function f($_GET)`） | Fatal error | リネーム | 低 |

### PHP 5.5

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 14 | ext/mysql（`mysql_*` 全関数）が非推奨。接続時に E\_DEPRECATED（7.0 で削除） | 7.0 で Fatal error | 14 節の対応表で mysqli または PDO へ。DB アクセス層に集約してから置換 | 高 |
| 15 | `preg_replace()` の `/e` 修飾子が非推奨（7.0 で削除） | 7.0 では Warning を出して null を返すため、置換結果が **無言で消える** | `preg_replace_callback()` へ | 高 |
| 16 | `mcrypt_ecb()` / `mcrypt_cbc()` / `mcrypt_cfb()` / `mcrypt_ofb()` 非推奨（7.0 削除）。ext/mcrypt 全体は 7.1 非推奨、7.2 削除 | 7.2 で Fatal error | OpenSSL へ（4 節 #9） | 高 |
| 17 | APC（オペコードキャッシュ）が Zend OPcache に置き換わる。`apc_store()` 等のユーザキャッシュ API は APCu へ分離 | `apc_*` が Fatal error（Smarty 等のキャッシュ設定も） | APCu を導入し `apcu_*` へ（互換レイヤ apcu\_bc は 8.x では保守されていないので書き換え） | 中 |
| 18 | `pack()` / `unpack()` の `a` / `A` / `Z` 指定の NUL・空白処理変更 | バイナリ解析結果の差 | `Z` へ見直し、テスト | 低 |
| 19 | `php_logo_guid()` 等のロゴ関数削除 | Fatal error | 削除 | 低 |

### PHP 5.6

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 20 | `$HTTP_RAW_POST_DATA` と `always_populate_raw_post_data` が非推奨（7.0 で削除） | XML-RPC/JSON API で入力が取れない | `file_get_contents('php://input')` へ（複数回読める） | 高 |
| 21 | `json_decode()` が RFC 7159 準拠に: `TRUE` / `False` / `Null` などの大文字リテラルを拒否、空文字は構文エラー | 旧クライアントや手書き JSON が null になる | 送信側の修正、受信側で `json_last_error()` を必ず確認 | 中 |
| 22 | `default_charset` が UTF-8 既定になり、`htmlspecialchars`・mbstring・iconv の既定値に使われる。`mbstring.internal_encoding` / `mbstring.http_input` / `mbstring.http_output` / `iconv.*_encoding` が非推奨 | 起動時 Deprecated。SJIS/EUC-JP 既定を期待していた処理が UTF-8 扱いになり文字化け | `default_charset` を実際の内部エンコードに設定し、コード側で `mb_internal_encoding()` を明示。長期的には内部 UTF-8 へ統一 | 高（SJIS/EUC-JP 環境） |
| 23 | OpenSSL ストリーム（`https://`、`ssl://`、`fsockopen`）がピア証明書を既定で検証 | 自己署名・期限切れ CA への `file_get_contents`、SOAP、`fsockopen` が失敗 | 正しい CA を配置。暫定: stream context の `verify_peer=false` | 中 |
| 24 | `mcrypt_*` が不正な長さの key/iv を受け付けなくなる（旧版は NUL パディング） | 既存暗号文を復号できない、Warning | 鍵・IV を明示的にパディングして渡す（移行期）。最終的に OpenSSL 化 | 高（mcrypt 利用時） |
| 25 | GMP がリソースからオブジェクトへ | `is_resource()` 判定が false | `instanceof GMP` | 低 |
| 26 | `crypt()` の salt 省略が E\_NOTICE（8.0 で ArgumentCountError） | 8.0 で Fatal | salt を必ず渡す、または `password_hash()` へ | 中 |
| 27 | cURL の `CURLOPT_SAFE_UPLOAD` 既定 true: `'@/path/to/file'` 形式のアップロードが無効（7.0 でオプション自体削除、`@` 形式は完全に不可） | アップロード API がファイルでなく文字列を送る（サイレント） | `CURLFile` へ | 中 |
| 28 | 非互換コンテキストからの非 static メソッド呼び出し（`Foo::bar()` 内で `$this` を使う）が E\_DEPRECATED（7.0 で `$this` 未定義 → Error） | 7.0 以降 Error | インスタンス化して呼ぶ、または static 宣言 | 中 |
| 29 | `mbstring.func_overload` との併用で `default_charset` の解釈が変わる | 文字化け | 7.2 で非推奨・8.0 削除になるので、この時点で func\_overload をやめる（4 節 #19） | 中 |

## 3. PHP 7.0 の非互換

7.0 は削除（ext/mysql、ereg、`/e`）と、エラーにならずに意味が変わる変更（統一変数構文、`date.timezone`、PHP4 コンストラクタの廃止予告）が重なる最初の大きな壁。静的解析で検出できないもの（#5、#22）はテストで拾う。

### 削除

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 1 | ext/mysql 削除（`mysql_connect`、`mysql_query`、`mysql_escape_string`、`mysql_real_escape_string` 等全て） | Fatal error: Call to undefined function | 14 節の対応表に従い mysqli / PDO へ | 高 |
| 2 | ext/ereg 削除: `ereg`、`eregi`、`ereg_replace`、`eregi_replace`、`split`、`spliti`、`sql_regcase` | Fatal error。`split(',', $s)` は旧コードで頻出 | `explode` / `preg_split` / `preg_match` / `preg_replace` へ。デリミタ付与、`i` フラグ、POSIX クラス（`[[:alpha:]]` は PCRE でも可）、エスケープ差を確認 | 高 |
| 3 | `$HTTP_RAW_POST_DATA` 削除、`always_populate_raw_post_data` ini 削除 | 入力取得不可、ini に残すと警告 | `php://input` | 高 |
| 4 | `preg_replace` の `/e` 削除 | Warning + null（置換結果が消える） | `preg_replace_callback` | 高 |
| 5 | 代替開始タグ `<%`、`<%=`、`<script language="php">` と `asp_tags` ini の削除 | タグが HTML としてそのまま出力（コード露出） | `<?php` へ | 中 |
| 6 | 削除関数: `call_user_method()` / `call_user_method_array()`、`set_magic_quotes_runtime()`、`magic_quotes_runtime()`、`set_socket_blocking()`、`mcrypt_generic_end()`、`mcrypt_ecb/cbc/cfb/ofb()`、`datefmt_set_timezone_id()`、`IntlDateFormatter::setTimeZoneID()`、fpm での `dl()`、`mktime()`/`gmmktime()` の `is_dst` 引数 | Fatal / ArgumentCountError | `call_user_func([$obj, $m])`、`setTimeZone()`、引数削除 | 中 |
| 7 | ext/mssql、ext/sybase\_ct 削除、ini の `#` コメント削除、`xsl.security_prefs` ini 削除 | Fatal / ini 警告 | pdo\_sqlsrv 等、`;` コメント | 低 |
| 8 | `date.timezone` 未設定時の警告廃止、既定 UTC | 無警告で日時が 9 時間ずれる（サイレント） | `date.timezone=Asia/Tokyo` を必須に。コード側でも `date_default_timezone_set()` | 高 |

### エラーにならず意味が変わるもの

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 9 | 統一変数構文（左から右へ評価）: `$$foo['bar']` は `${$foo['bar']}` だったものが `($$foo)['bar']` に、`$obj->$arr['k']` は `$obj->{$arr['k']}` だったものが `($obj->$arr)['k']` に、`$obj->$name['k']()`、`Foo::$bar['baz']()` も同様 | エラーにならず別の変数・プロパティを参照する（サイレント）。動的プロパティ・可変変数を多用する旧フレームワークで発生 | 旧の意味を保つには `{}` で明示（`${$foo['bar']}`、`$obj->{$arr['k']}`）。`global $$foo->bar` は `global ${$foo->bar}` | 高 |
| 10 | エンジン例外: 多くの Fatal が `Error` 階層（TypeError、ParseError、ArithmeticError、DivisionByZeroError、AssertionError）に | `catch (Exception $e)` で捕捉されず、`set_error_handler` も呼ばれない。`set_exception_handler` のハンドラが `Exception $e` と型宣言していると TypeError | `Throwable` を catch / 型宣言。フレームワークのエラーハンドラを見直す | 高 |
| 11 | `%` のゼロ除算 → DivisionByZeroError（`/` は 7.x では Warning + INF/NAN、8.0 で例外）、負のビットシフト → ArithmeticError、ビット幅以上のシフトは 0 | 例外で停止 | 除数チェック、`intdiv()` | 中 |
| 12 | 16 進文字列 `"0x1A"` が数値文字列でなくなる（`is_numeric` false、`"0x10" == 16` false） | 判定・計算の差 | `hexdec()` を明示 | 中 |
| 13 | 予約語追加: `bool`、`int`、`float`、`string`、`null`、`true`、`false`、`resource`、`object`、`mixed`、`numeric` をクラス・インターフェイス・トレイト名に使用不可 | `class String`、`class Object`、`class Resource` が Fatal | リネーム（名前空間を使っていても不可） | 高 |
| 14 | `list()`: 文字列の分解不可（全て null）、空の `list()` 不可、代入順が左から右に | `list($a, $b) = 'ab'` が null（サイレント） | `str_split` / `explode` を経由 | 中 |
| 15 | `foreach`: 内部ポインタを動かさない（ループ内の `current()`/`next()`/`each()` の結果が変わる）、値渡しはコピーを反復、参照渡しはループ中の追加要素も反復 | ロジック差（サイレント） | ループ内でポインタ関数を使わない | 中 |
| 16 | 非 static メソッドの static 呼び出しが E\_DEPRECATED（8.0 で Error）。PHP4 形式コンストラクタ（クラス名と同名のメソッド）が E\_DEPRECATED（8.0 でただのメソッド扱い） | 8.0 でコンストラクタが呼ばれず初期化が走らない（サイレント） | `__construct()` へリネーム。`static` を明示 | 高 |
| 17 | `$a = &new Foo` 削除、`switch` の複数 `default` が Fatal、同名引数の重複 `function f($a, $a)` が Fatal、不正な 8 進リテラル `0128` が Parse error | コンパイルエラー | 修正 | 低 |
| 18 | 二重引用符内の `\u{` が Unicode エスケープに | `\u{` を含む文字列（JS コード生成等）が Parse error | `\\u{` または単一引用符 | 低 |
| 19 | `func_get_args()` / `func_get_arg()` が引数変更後の値を返す | ロジック差 | 先に複製 | 低 |
| 20 | E\_STRICT の再分類（大半が E\_DEPRECATED / E\_NOTICE / E\_WARNING へ） | ログ種別が変わり、`~E_STRICT` で抑制していたものが表示される | `error_reporting` を整理。根本修正 | 低 |
| 21 | `substr('abc', 3)` が `""`（旧 false） | `=== false` 判定の差 | 条件修正 | 低 |
| 22 | JSON 拡張が jsond に置換 | 数値・空文字扱いの微差 | テスト | 低 |
| 23 | `yield` が右結合の式に、`setlocale()` のカテゴリ文字列指定が非推奨（8.0 削除）、`password_hash()` の salt オプション非推奨、`capture_session_meta` SSL オプション非推奨 | Deprecated | `LC_ALL` 定数へ | 低 |

### 環境要因（同時に起こりやすい）

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 24 | 32bit → 64bit への移行（旧サーバが 32bit の場合）: `PHP_INT_MAX`、`crc32()` や `ip2long()` が負にならない、`mt_rand()` の範囲、`pack('N')`、`intval()` の飽和値 | DB に保存済みの符号付き値（`INT` に入れた crc32 や IP）と新しい計算値が一致しない | 保存形式を確認し、`sprintf('%u')` などで正規化 | 中（該当時） |
| 25 | 整数オーバーフロー、NaN / Inf の `(int)` キャストが 0 に | 計算結果差 | 検証 | 低 |

## 4. PHP 7.1〜7.4 の非互換

7.x 後半は「8.0 で削除されるものの非推奨化」が中心。`each()`、`create_function()`、`__autoload()`、`mbstring.func_overload`、`$str{0}`、mcrypt は旧コードでの出現頻度が高く、7.4 の時点で全て置換しておくと 8.0 の作業量が半減する。

### PHP 7.1

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 1 | ユーザ定義関数への引数不足が ArgumentCountError | 旧: Warning を出し null で続行。新: Fatal | 既定値を付ける、呼び出し側を修正 | 高 |
| 2 | 非数値文字列との算術演算: `"abc" + 1` → Warning「A non-numeric value」、`"1abc" + 1` → Notice「A non well formed numeric value」（8.0: 前者 TypeError、後者 Warning） | 8.0 で Fatal 化 | `(int)` キャストや `is_numeric()` で前処理 | 高 |
| 3 | 数値文字列の指数表記を尊重: `(int)"1e3"` が 1000（旧 1）、`intval("1e3")` 同様 | 計算結果の差（サイレント） | 入力検証を正規表現で | 中 |
| 4 | `rand()`/`srand()` が `mt_rand()`/`mt_srand()` の別名に、`mt_rand()` の剰余バイアス修正。`shuffle()`、`array_rand()`、`str_shuffle()` も MT ベースに | 同一シードの乱数列が変わる（抽選の再現、シード固定テスト） | 再現性が必要な結果は DB に保存。暫定: `mt_srand($seed, MT_RAND_PHP)`（8.3 で非推奨） | 中 |
| 5 | `$this` の制限（引数名、static 変数、`global $this`、`unset($this)`、static クロージャ内）、`void`/`iterable` が予約語 | Fatal | リネーム | 低 |
| 6 | `DateTime` がマイクロ秒を保持 | `new DateTime() == new DateTime()` が false に、`format('u')` が非ゼロ、シリアライズ結果が変わる | 秒精度で比較する（`format('Y-m-d H:i:s')` 同士） | 中 |
| 7 | `json_encode()` / `var_export()` が `serialize_precision=-1`（最短往復表現） | `0.1` が `0.10000000000000001` でなく `0.1` で出力（改善だがスナップショット差） | テスト期待値更新 | 低 |
| 8 | ext/mcrypt 非推奨（7.2 削除） | 7.2 で Fatal | `openssl_encrypt()` / `openssl_decrypt()` へ。MCRYPT\_RIJNDAEL\_128 ↔ AES-128/256-CBC は互換（mcrypt のゼロパディングは `OPENSSL_ZERO_PADDING` + 手動パディングで再現）。MCRYPT\_RIJNDAEL\_256（ブロック長 256）は OpenSSL に存在しないため phpseclib で復号して再暗号化。Blowfish/DES は OpenSSL 3 でレガシープロバイダが必要 | 高 |
| 9 | `session.hash_function` / `session.hash_bits_per_character` / `session.entropy_file` / `session.entropy_length` 削除 → `session.sid_length` / `session.sid_bits_per_character`（8.4 で非推奨） | ini 警告、セッション ID 長が変わり DB の session\_id 列幅を超える可能性 | 列幅を 128 以上に | 低 |
| 10 | `(unset)` キャスト、`ldap_sort()`、`png2wbmp()` / `jpeg2wbmp()`、`mb_ereg_replace()` の `e` オプションが非推奨（8.0 削除） | 8.0 で Fatal | `mb_ereg_replace_callback()` 等 | 中 |
| 11 | `compact()` / `extract()` / `func_get_args()` / `get_defined_vars()` / `parse_str()` 等の動的呼び出し（`$f = 'extract'; $f()`）禁止 | Error | 直接呼び出し | 低 |
| 12 | 負の文字列オフセット `$s[-1]` が有効（旧は Notice + 空） | 挙動差（改善） | — | 低 |

### PHP 7.2

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 13 | `count()` に Countable でない値（null、false、文字列、数値）を渡すと Warning（8.0 で TypeError） | 8.0 で Fatal。`count($row)` で $row が false/null のケースが頻出 | `count((array)$x)`、`$x ? count($x) : 0`、`is_countable()` | 高 |
| 14 | `__autoload()` 非推奨（8.0 削除） | 8.0 でクラスが読み込まれず Fatal | `spl_autoload_register()` | 高 |
| 15 | `create_function()` 非推奨（8.0 削除） | Fatal | クロージャ `function () use (...) {}` | 高 |
| 16 | `each()` 非推奨（8.0 削除）: `while (list($k, $v) = each($arr))` | Fatal | `foreach` | 高 |
| 17 | `mbstring.func_overload` 非推奨（8.0 削除） | `strlen` / `substr` / `strpos` / `str_split` 等がマルチバイトを意識しなくなり、文字数・切り出し・検索がバイト単位に（サイレント） | 該当全関数を `mb_*` へ置換（func\_overload=2 なら strlen/strpos/strrpos/substr/strtolower/strtoupper/stripos/strripos/strstr/stristr/strrchr/substr\_count/ucfirst/ucwords/mail） | 高（日本語サイト） |
| 18 | `$php_errormsg` / `track_errors` 非推奨（8.0 削除） | 未定義変数 | `error_get_last()` | 中 |
| 19 | `parse_str()` の第 2 引数省略、`assert()` の文字列引数、エラーハンドラの `$errcontext`、`gmp_random()`、`read_exif_data()`、`(unset)` が非推奨（8.0 削除） | 8.0 で Fatal / ハンドラシグネチャ不一致 | `parse_str($s, $out)`、`exif_read_data()` | 中 |
| 20 | `object` が予約語 | `class Object` が Fatal | リネーム | 低 |
| 21 | `get_class(null)` が Warning（8.0 TypeError）、`is_object()` が `__PHP_Incomplete_Class` に true | 判定差 | 修正 | 低 |
| 22 | `json_decode()` で空キー `""` が `_empty_` でなく `""` プロパティに | オブジェクトアクセス差 | 配列モード `json_decode($s, true)` | 低 |
| 23 | `hash_hmac()` / `hash_init(HASH_HMAC)` / `hash_pbkdf2()` で非暗号学ハッシュ（crc32、adler32、fnv、joaat）不可 | Warning + false | sha256 等へ | 低 |
| 24 | セッション開始後の `session_set_cookie_params()` / `session_name()` / `session_save_path()` / `session_cache_limiter()` 等が Warning で無効 | 設定が効かない（Cookie 属性など） | `session_start()` より前に移動 | 中 |
| 25 | 配列↔オブジェクトのキャストで数値文字列キーと整数キーが相互変換される | 到達不能だったキーが見えるようになる | 確認 | 低 |
| 26 | TLS ストリームの既定が TLS 1.0、1.1、1.2 の交渉に（`STREAM_CRYPTO_METHOD_TLS_CLIENT`） | 古いサーバとの接続差 | 明示指定 | 低 |

### PHP 7.3

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 27 | PCRE → PCRE2: 不正なエスケープや文字クラス内の範囲（`[\w-.]` のようなハイフン）がコンパイルエラー、`x` 修飾子の解釈差、`preg_quote()` が `#` もエスケープ | `preg_*` が Warning + false を返し、バリデーションが「常に失敗」あるいは「常に通過」する（サイレント） | 全正規表現を抽出して新版でコンパイルテスト、`preg_last_error()` をチェック | 高 |
| 28 | ヒアドキュメント / Nowdoc の終端識別子が柔軟化（インデント可、行末以外でも終端） | 本文中に終端識別子と同じ語で始まる行があるとそこで終わり Parse error / 本文欠落 | 識別子を一意な名前（`EOT_SQL_1` 等）に | 中 |
| 29 | `switch` 内の `continue` が Warning（`continue 2` の意図かと警告） | 挙動は `break` と同じで変わらないがログが出る | `break` または `continue 2` に書き換え | 低 |
| 30 | `define('X', 1, true)`（大文字小文字非依存定数）、`FILTER_FLAG_SCHEME_REQUIRED` / `HOST_REQUIRED`、`fgetss()` / `string.strip_tags` フィルタ、`image2wbmp()`、mbstring の非公開別名 `mbereg*` / `mbsplit` / `mbregex_encoding` が非推奨（8.0 削除） | 8.0 で Fatal | `mb_ereg*` 正式名、`strip_tags(fgets())` | 中 |
| 31 | mbstring の大文字小文字変換が完全ケースマッピング（`mb_strtoupper('ß')` → `'SS'`）、`MB_CASE_TITLE` の変更 | 欧文で差（日本語は影響なし） | テスト | 低 |
| 32 | `compact()` が未定義変数で Notice、`bcmul()` / `bcpow()` の末尾ゼロの扱い、`array_key_first()` 等の新関数名衝突 | ログ増 / Cannot redeclare | 変数初期化、`function_exists()` ガード | 低 |

### PHP 7.4

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 33 | 波括弧オフセット `$str{0}` / `$arr{'k'}` 非推奨（8.0 で Parse error） | 8.0 でファイル全体がコンパイル不能 | `[0]` へ（Rector / 正規表現で一括） | 高 |
| 34 | 括弧なしのネスト三項演算子 `$a ? $b : $c ? $d : $e` 非推奨（8.0 で Fatal） | コンパイルエラー | 括弧で明示 | 高 |
| 35 | `+` / `-` と `.` の優先順位変更の予告（8.0 で `.` が低くなる）: `"合計: " . $a + $b` は 8.0 で `"合計: " . ($a + $b)` | 7.4 で Deprecated、8.0 で結果が変わる（サイレント） | 括弧で明示 | 高 |
| 36 | `get_magic_quotes_gpc()` / `get_magic_quotes_runtime()` 非推奨（8.0 削除） | 8.0 で Fatal。旧コードの入力処理冒頭に頻出 | 分岐ごと削除 | 高 |
| 37 | `implode($arr, $glue)`（引数逆順）非推奨（8.0 で TypeError） | Fatal | 引数順修正 | 中 |
| 38 | `array_key_exists()` のオブジェクト適用非推奨（8.0 で TypeError） | Fatal | `property_exists()` / `isset()` | 中 |
| 39 | `(real)` キャスト、`is_real()` 非推奨（8.0 削除） | Parse error / Fatal | `(float)` / `is_float()` | 中 |
| 40 | `money_format()`、`hebrevc()`、`convert_cyr_string()`、`ezmlm_hash()`、`restore_include_path()` 非推奨（8.0 削除） | `money_format('%n', $v)` + `setlocale(LC_MONETARY, 'ja_JP')` の金額表示が Fatal | `NumberFormatter::formatCurrency()`（intl）または `number_format()` | 中 |
| 41 | `allow_url_include` ini 非推奨、`ReflectionType::__toString()` 非推奨、`base_convert()` の不正文字非推奨 | Deprecated | Off / `getName()` | 低 |
| 42 | null / bool / int / float / resource への配列アクセス `$null['k']` が Notice（8.0 で Warning） | ログ増 | `??` でガード | 低 |
| 43 | `fn` が予約語、`__serialize()` / `__unserialize()` が `Serializable` より優先 | `function fn()` が Parse error、シリアライズ形式の変化（新形式は旧 PHP で読めない） | リネーム。ローリング中のセッション共有に注意 | 低 |
| 44 | `password_hash()` のアルゴリズム定数が文字列（`PASSWORD_BCRYPT` = `'2y'`）、`openssl_random_pseudo_bytes()` が失敗時に例外 | `password_get_info()['algo'] === 1` が false | 定数で比較 | 低 |
| 45 | ファイル末尾の `<?php`（改行なし）が開始タグとして解釈 | Parse error | 削除 | 低 |
| 46 | 削除拡張: ext/wddx、ext/recode、ext/interbase、mysqli の組込みサーバ関数（`mysqli_embedded_server_*`）。PEAR が既定で同梱されない | Fatal、`require 'PEAR.php'` 失敗 | Composer へ移行 | 中 |

## 5. PHP 8.0 の非互換

8.0 は「旧コードが曖昧に許されていたもの」を一斉にエラー化する。最も危険なのはエラーにならない #1（文字列と数値の比較）と #13（優先順位）、次に件数が多い #8～#10（内部関数の TypeError / ValueError）。DB 周りは PDO の既定エラーモードが例外に変わる（14 節）。

### 比較・数値・ソート

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 1 | 数値と非数値文字列の緩い比較: `0 == "abc"` が false（旧 true）、`0 == ""` が false、`"1" == "01"` は true のまま。`in_array(0, ['a', 'b'])`、`switch (0)` の文字列 case、`$row['status'] == 0`（status が `''` や `'x'`） | 条件分岐が **無警告で反転** | `===` へ。`switch` の対象と case の型を揃える。`in_array(..., true)` | 高 |
| 2 | 数値文字列の再定義: 先頭数値 `"123abc"` は算術で Warning、非数値 `"abc" * 1` は TypeError、末尾空白 `"123 "` は数値扱い（`is_numeric` true） | Fatal / 判定差 | キャスト・検証を前段に | 高 |
| 3 | 配列・リソース・オブジェクトへの算術 / ビット演算（`[] + 1`、`$obj * 2`）が TypeError。null は 0 扱いのまま | Fatal | 型検証 | 中 |
| 4 | `/` と `%` のゼロ除算が DivisionByZeroError（旧: Warning + INF / false） | Fatal。平均値・割合計算で分母 0 のケース | 事前チェック、`fdiv()` | 高 |
| 5 | `sort()` / `usort()` 等が安定ソートに。比較コールバックが bool を返す（`return $a > $b;`）と Deprecated | 同値要素の順序が変わる、ログ | `<=>` を返す | 中 |
| 6 | 浮動小数の文字列化がロケール非依存 | ja\_JP では影響なし | — | 低 |
| 7 | `str*` 関数の needle に int を渡すと ASCII コードではなく文字列 `"65"` として検索。`substr()` / `mb_substr()` / `iconv_substr()` が範囲外で `""`（false ではない）、空 needle が有効 | 判定差（サイレント） | `chr()`、`=== false` 判定の見直し | 中 |

### エラー・例外・型検査

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 8 | 内部関数の引数型検査: 不正型で TypeError（strict\_types 無関係）。`strlen([])`、`count(null)`、`array_merge(null, $a)`、`in_array($x, null)`、`htmlspecialchars([])`、**`mysqli_fetch_assoc(false)`**、`array_key_exists($k, null)`、`strtotime([])` | Fatal。「失敗したクエリの false を fetch に渡す」パターンが即死 | 戻り値チェック、`(array)` / `(string)` キャスト、null 合体 | 高 |
| 9 | 内部関数が Warning + false の代わりに ValueError: `explode('', $s)`、`str_repeat($s, -1)`、`array_combine()` 長さ不一致、`range(1, 10, 0)`、`array_chunk($a, 0)`、`str_split($s, 0)`、`strpos()` の範囲外 offset、`mb_strlen($s, 'bad')`、`array_fill(0, -1, ..)`、`json_decode($s, false, 0)`、`array_rand([])`、`substr_count($s, '')`、**`mysqli_query($c, '')`**、`str_pad()` の空 pad、`random_int($max, $min)` | Fatal | 引数検証 | 高 |
| 10 | 未定義へのアクセス: 定数 → Error、変数 → Warning（旧 Notice）、配列キー → Warning、プロパティ → Warning、null / bool / int への配列読み出し → Warning、スカラへの配列書き込み `$int['k'] = 1` → Error、未定義関数 / メソッド → Error | 未定義定数（クォート忘れの文字列 `$a[key]`）が Fatal。Warning 増加でログ溢れ | 定数定義、`$a['key']`、`??` | 高 |
| 11 | 既定 `error_reporting = E_ALL`、`display_startup_errors = On`（php.ini 未設定時） | 旧コードの Warning / Deprecated が画面とログに大量出力。出力が先行して `header()` が失敗 | php.ini で明示（本番: `display_errors=Off`、`log_errors=On`、`error_reporting=E_ALL & ~E_DEPRECATED` を移行完了までの暫定） | 高 |
| 12 | `@` 演算子が Fatal 系（E\_ERROR、E\_PARSE、E\_CORE\_*、E\_COMPILE\_*、E\_USER\_ERROR、E\_RECOVERABLE\_ERROR）を抑止しなくなる。`@` 中の `error_reporting()` が 0 でなく 4437 を返す | `if (error_reporting() === 0) return;` 型のエラーハンドラが `@` を識別できず、抑止されていた警告で例外を投げる | `if (!(error_reporting() & $errno)) return false;` | 中 |
| 13 | 優先順位変更の実施: `.` が `+`/`-` より低く、`"合計: " . $a + $b` は `"合計: " . ($a + $b)`。括弧なしネスト三項演算子が Fatal | 前者は結果が変わる（サイレント）、後者はコンパイルエラー | 7.4 で Deprecated を潰しておく | 高 |
| 14 | 非 static メソッドの static 呼び出し → Error。PHP4 コンストラクタはただのメソッドに | Fatal / 初期化が走らない（サイレント） | `__construct()`、`static` | 高 |
| 15 | 継承時のシグネチャ非互換が Fatal（旧 Warning「Declaration of ... should be compatible」）。子クラスで引数数・型・既定値が親と合わない、マジックメソッドに型を書いた場合のシグネチャ検査（`__toString(): string` 等） | コンパイルエラー。旧 ORM / フレームワークのサブクラスで多発 | 親に合わせる（引数は広く、戻り値は狭く）。private は検査対象外 | 高 |
| 16 | `#[` が属性構文に。`#[コメント]` で始まる行がパースされる。新予約語 `match`、`mixed`。名前空間名が単一トークン（`Foo \ Bar` のような空白不可） | Parse error | `//` コメントへ、リネーム | 中 |
| 17 | `assert.exception=1` 既定: `assert()` 失敗が AssertionError | 本番で assert を残していると停止 | `zend.assertions=-1`（本番） | 低 |
| 18 | `mktime()` / `gmmktime()` は引数 1 つ以上必須、`crypt()` の salt 必須 | ArgumentCountError | `time()`、`password_hash()` | 中 |

### 削除

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 19 | 7.x で非推奨だったものの削除: `each()`、`create_function()`、`__autoload()`、`$php_errormsg` / `track_errors`、`money_format()`、`hebrevc()`、`convert_cyr_string()`、`ezmlm_hash()`、`restore_include_path()`、`get_magic_quotes_gpc()` / `get_magic_quotes_runtime()`、`fgetss()` / `string.strip_tags`、`is_real()` / `(real)`、`(unset)`、`$str{0}`、`implode()` 逆順、`array_key_exists()` のオブジェクト、`define(..., true)`、`mbereg*` 別名、`mb_ereg_replace()` の `e`、`mb_parse_str()` 1 引数、`read_exif_data()`、`ldap_sort()`、`ldap_control_paged_result*()`、`assert()` 文字列、`$errcontext`、`FILTER_SANITIZE_MAGIC_QUOTES`、`setlocale()` カテゴリ文字列、`mbstring.func_overload`、`image2wbmp()`、`png2wbmp()` / `jpeg2wbmp()`、`gmp_random()`、ext/xmlrpc（PECL へ） | Fatal（未定義関数 / Parse error） | 4 節の各項目の代替へ | 高 |
| 20 | 非推奨化: `zip_open()` 等の手続き型 ZIP API、`pg_*` の旧別名、`libxml_disable_entity_loader()`、`enchant_broker_*` 一部 | Deprecated | `ZipArchive` | 低 |
| 21 | 削除 ini: `track_errors`、`mbstring.func_overload`、`assert.quiet_eval`、`pdo_odbc.db2_instance_name`、`xmlrpc.*`、`allow_url_include`（非推奨継続） | 起動時警告 | 削除 | 低 |

### リソース → オブジェクト

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 22 | cURL → `CurlHandle` / `CurlMultiHandle` / `CurlShareHandle`（`curl_close()` は no-op）、GD → `GdImage`（`imagedestroy()` は no-op）、XML パーサ → `XMLParser`、`XMLWriter`、`Socket`、OpenSSL の鍵 / 証明書 / CSR、zlib の `InflateContext` / `DeflateContext`、`Shmop`、`SysvMessageQueue` / `SysvSemaphore` / `SysvSharedMemory`、`EnchantBroker`、`WeakReference` | `is_resource($ch)` が false を返し、接続・画像の有効判定が常に失敗（サイレント）。`gettype()` が `object` | `instanceof CurlHandle` / `$ch !== false` | 高（cURL / GD 利用時） |

### 名前衝突・その他

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 23 | 新グローバル関数 / クラス: `str_contains()`、`str_starts_with()`、`str_ends_with()`、`get_debug_type()`、`fdiv()`、`get_resource_id()`、`preg_last_error_msg()`、クラス `Attribute`、`Stringable`、`WeakMap`、`ValueError`、`UnhandledMatchError`、`PhpToken`、`InternalIterator` | 自前ポリフィルや同名クラスで Fatal「Cannot redeclare」/「Cannot declare class」 | `function_exists()` ガード、名前空間化 | 中 |
| 24 | libxml: 外部エンティティ読み込みが既定無効（XXE 対策） | DTD 外部参照を使う XML が読めない | 必要な場合のみ `LIBXML_NOENT` を意識的に | 低 |
| 25 | `mail()` / `mb_send_mail()` のヘッダ CRLF インジェクション対策強化（複数ヘッダは配列で） | 送信失敗 | 配列ヘッダ | 低 |
| 26 | `__PHP_Incomplete_Class` 、`Serializable` は 8.1 で非推奨。ローリング中に旧 PHP が書いたセッション / キャッシュを新 PHP が読む | クラス定義変更と組み合わさると復元失敗 | 切替時にセッション破棄を許容 | 低 |

### PHP–MySQL 連携（8.0 で顕在化、詳細は 14 節）

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 27 | `PDO::ATTR_ERRMODE` の既定が `ERRMODE_SILENT` → `ERRMODE_EXCEPTION` | `$stmt === false` や `errorInfo()` で判定していたコードが PDOException で停止 | 例外前提に書き換え。暫定: コンストラクタで `ERRMODE_SILENT` を明示 | 高 |
| 28 | `mysqli_fetch_*(false)` が TypeError、`mysqli_query($c, '')` が ValueError、`mysqli_num_rows()` / `insert_id` / `affected_rows` が PHP\_INT\_MAX 超で string | Fatal / 型差 | クエリ結果の判定を徹底 | 高 |
| 29 | `PDOStatement::fetchAll()` が常に配列（false を返さない） | `=== false` 判定が死ぬ（無害） | — | 低 |

## 6. PHP 8.1 / 8.2 の非互換

8.1 は DB 層に直撃する変更が 2 つある: mysqli の既定が例外モードになり、PDO（mysqlnd）が数値をネイティブ型で返す。件数で最大なのは「内部関数への null 渡し」の Deprecated（9.0 で TypeError）。8.2 は動的プロパティが旧 OOP コードに広く当たる。

### PHP 8.1

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 1 | 内部関数の非 nullable 引数に null を渡すと Deprecated（9.0 で TypeError）: `strlen(null)`、`trim(null)`、`htmlspecialchars(null)`、`str_replace($a, $b, null)`、`strtotime(null)`、`mb_strlen(null)`、`urlencode(null)`、`preg_match($p, null)`、`json_decode(null)`、`mysqli_real_escape_string($c, null)`、`strpos(null, 'x')` | `$_GET['x'] ?? null` や DB の NULL 列由来で大量の Deprecated。ログが溢れる | `(string)` キャスト、`?? ''`、関数の型宣言。Rector の `NullToStrictStringFuncCallArgRector` | 高 |
| 2 | mysqli の既定エラーモードが `MYSQLI_REPORT_ERROR｜MYSQLI_REPORT_STRICT`（旧 `MYSQLI_REPORT_OFF`） | 接続失敗・SQL エラー・プリペア失敗が `mysqli_sql_exception` を投げ、false 判定コードは未捕捉例外で Fatal | 例外前提で書き換え。暫定: 起動時に `mysqli_report(MYSQLI_REPORT_OFF)` | 高 |
| 3 | PDO（mysqlnd）がエミュレートプリペア・通常クエリでも INT / FLOAT を int / float で返す（`PDO::ATTR_STRINGIFY_FETCHES=false` 既定）。DECIMAL、DATE 等は string のまま | `$row['id'] === '1'` が false、`json_encode` の出力が `"id":"1"` → `"id":1`（API 契約変更）、`is_string()` 判定差、`switch` での型不一致 | 互換維持なら `PDO::ATTR_STRINGIFY_FETCHES => true`。新仕様にするなら API スキーマを更新 | 高 |
| 4 | 内部インターフェイス実装の暂定戻り値型: `ArrayAccess::offsetGet()` 等、`Iterator`、`IteratorAggregate`、`Countable::count()`、`JsonSerializable::jsonSerialize()`、`SessionHandlerInterface`、`DateTime` 継承クラス | Deprecated「Return type of X::offsetGet($o) should either be compatible with ...」 | 戻り値型を付与、旧 PHP もサポートするなら `#[\ReturnTypeWillChange]` | 中 |
| 5 | `htmlspecialchars()` / `htmlentities()` / `htmlspecialchars_decode()` / `html_entity_decode()` / `get_html_translation_table()` の既定フラグが `ENT_QUOTES｜ENT_SUBSTITUTE｜ENT_HTML401`（旧 `ENT_COMPAT`） | `'` が `&#039;` にエスケープされる（属性値や JS 埋め込み、二重エスケープ、テスト期待値）。無効バイトは空文字でなく U+FFFD に置換 | 旧挙動が必要な箇所は `ENT_COMPAT` を明示。本来は新既定の方が安全 | 中 |
| 6 | `strftime()` / `gmstrftime()` 非推奨（`setlocale(LC_TIME, 'ja_JP')` + `%a` で曜日を日本語化する定番） | Deprecated（9.0 で削除） | `date()` + 曜日配列、または `IntlDateFormatter`（intl） | 中 |
| 7 | `FILTER_SANITIZE_STRING` / `FILTER_SANITIZE_STRIPPED` 非推奨（XSS 対策として多用） | Deprecated | 出力時に `htmlspecialchars()`、入力検証は別途 | 中 |
| 8 | その他の非推奨: `date_sunrise()` / `date_sunset()`、`mhash*()`、`odbc_result_all()`、`FILE_BINARY` / `FILE_TEXT`、`PDO::FETCH_SERIALIZE`、`ctype_*()` への非文字列（`ctype_digit(123)`）、`key()` / `current()` / `next()` / `reset()` / `end()` / `prev()` へのオブジェクト、`mb_check_encoding()` 引数なし、`strptime()`、`IntlCalendar::roll(bool)`、ini `auto_detect_line_endings`、ini `filter.default` / `filter.default_flags` | Deprecated。`filter.default=magic_quotes` で magic quotes を擬似していた環境は要注意 | `ctype_digit((string)$id)`、`get_object_vars()` 経由、`filter.default` は廃止しコード側でエスケープ | 中 |
| 9 | 暗黙の float → int 変換で精度が落ちる場合 Deprecated（`$arr[1.5]`、`$x % 2` の float、ビット演算、文字列オフセット） | 金額・割合計算でログ | `intdiv()`、`(int) round()` を明示 | 中 |
| 10 | `$GLOBALS` の全体書き換え・参照取得不可（`$GLOBALS = []`、`$g = &$GLOBALS`、`array_pop($GLOBALS)`）。`$GLOBALS['x'] = 1` は可 | コンパイルエラー | 個別キー操作 | 低 |
| 11 | false からの配列自動生成 `$x = false; $x[] = 1;` が Deprecated（null からは可） | `$result = false;` を既定にして追加していくパターン | `[]` で初期化 | 中 |
| 12 | 継承されたメソッド内の static 変数が親子で共有される | クラスごとのキャッシュを static 変数で持っていた場合に混ざる（サイレント） | static プロパティ + `static::class` キー | 低 |
| 13 | `Serializable` のみ実装（`__serialize` なし）が Deprecated | Deprecated | `__serialize()` / `__unserialize()` 追加 | 低 |
| 14 | mysqli: `mysqli::init()` 非推奨（`parent::init()` → `parent::__construct()`）、`mysqli_driver::$driver_version` 非推奨、`mysqli_get_client_info($link)` の引数非推奨、`MYSQLI_REFRESH_SLAVE` → `MYSQLI_REFRESH_REPLICA`、`mysqli_result::fetch_all()` / `mysqli_stmt::next_result()` が libmysqlclient でも利用可、`mysqli_stmt::execute($params)` 追加、`mysqli::connect()` が true を返す | Deprecated | 置換（[mysqli changelog](https://www.php.net/manual/en/changelog.mysqli.php)） | 低 |
| 15 | リソース → オブジェクト: `finfo`、`FTP\Connection`、`IMAP\Connection`、`LDAP\Connection` / `Result` / `ResultEntry`、`PgSql\Connection` / `Result` / `Lob`、`PSpell\Dictionary` / `Config` | `is_resource()` 判定が false | `instanceof` | 低 |
| 16 | 新予約語 / クラス: `enum`（`enum Foo` 文脈）、`readonly`、`never`、`Fiber`、`ReturnTypeWillChange`、`array_is_list()`、`fsync()`、`enum_exists()` | `function readonly()` が 8.1 で Parse error（8.2 で緩和）、名前衝突 | リネーム、ガード | 低 |
| 17 | mbstring の内部刷新（8.1〜8.3）: `mb_detect_encoding()` の非 strict モードが候補の「適合度」で判定、SJIS 系 / EUC-JP 系 / ISO-2022-JP の変換テーブル修正 | 検出結果が旧版と変わる（SJIS と EUC-JP の曖昧なバイト列）、機種依存文字の往復結果が変わる場合がある | 入力エンコードを明示し自動検出をやめる。機種依存文字の回帰テスト（13 節） | 中 |
| 18 | OpenSSL 3.0 環境（8.1 以降を同梱するディストリビューション）: DES / Blowfish / RC4 / MD4 がレガシープロバイダ必須 | `openssl_encrypt($s, 'bf-cbc', ...)` が false（Unknown cipher） | openssl.cnf で legacy provider を有効化（暫定）、AES で再暗号化 | 中 |
| 19 | ファイル系関数で NUL バイトを含むパスは false を返す（8.0 の例外から変更）、`$_FILES['full_path']` 追加、引数アンパックで文字列キー可 | — | — | 低 |

### PHP 8.2

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 20 | 動的プロパティの非推奨: 宣言していないプロパティへの代入 `$obj->foo = 1`（`stdClass`、`__get`/`__set` を持つクラス、`#[\AllowDynamicProperties]` 付きクラスは対象外）。9.0 で Error | 旧 OOP コード（プロパティ未宣言のモデル、テンプレートへの値渡し）で大量の Deprecated | プロパティを宣言。暫定: クラスに `#[\AllowDynamicProperties]` | 高 |
| 21 | `"${var}"` / `"${expr}"` の文字列補間が非推奨 | Deprecated | `"{$var}"` | 中 |
| 22 | mysqli を libmysqlclient でビルド不可（mysqlnd のみ、[RFC](https://wiki.php.net/rfc/mysqli_support_for_libmysql)）。`mysqli.reconnect` ini と自動再接続機能が削除 | libmysqlclient の `[client]` 設定読み込みや自動再接続に依存した長時間バッチが「MySQL server has gone away」(2006) で停止 | 接続ラッパで 2006 / 2013 を捕捉して再接続。`mysqli_ping()` は 8.4 で非推奨なので使わない | 中 |
| 23 | `mb_convert_encoding()` の変換先・元に `HTML-ENTITIES`、`BASE64`、`UUENCODE`、`QPrint` を指定するのが非推奨（`DOMDocument::loadHTML()` 前の UTF-8 対策として定番） | Deprecated | `mb_encode_numericentity()`、`htmlentities()`、`base64_encode()`。DOM は `<?xml encoding="UTF-8">` を前置、または 8.4 の `Dom\HTMLDocument::createFromString()` | 中 |
| 24 | `utf8_encode()` / `utf8_decode()` 非推奨 | Deprecated | `mb_convert_encoding($s, 'UTF-8', 'ISO-8859-1')` | 低 |
| 25 | `strtolower()` / `strtoupper()` / `stristr()` / `stripos()` / `strripos()` / `lcfirst()` / `ucfirst()` / `ucwords()` / `str_ireplace()` がロケール非依存（ASCII のみ） | `setlocale(LC_CTYPE)` に依存した 1 バイト文字の変換差（日本語では実質なし） | `mb_strtolower()` | 低 |
| 26 | 部分的にサポートされていた callable の非推奨: `"self::m"`、`"parent::m"`、`"static::m"`、`[$obj, "parent::m"]` | `call_user_func('parent::foo')` が Deprecated | `parent::foo(...)`（第一級 callable） | 低 |
| 27 | `str_split("")` が `[]`（旧 `[""]`）、`ksort()` / `krsort()` の `SORT_REGULAR` が PHP 8 比較規則に、`var_export()` のクラス名が完全修飾、`date_default_timezone_get()` が ini 未設定時に UTC | ループ回数・並び順・スナップショットの差 | テスト、`SORT_STRING` 明示 | 低 |
| 28 | 新機能由来の衝突: `Random\` 名前空間、`#[\SensitiveParameter]`、`#[\AllowDynamicProperties]`、`readonly class`、独立型 `true` / `false` / `null` | 名前衝突 | リネーム | 低 |
| 29 | `SplFileObject::getCsvControl()` 等 SPL のシグネチャ強制、`DateTime::createFromImmutable()` の戻り値型 `static` | サブクラスで Fatal | シグネチャ修正 | 低 |

## 7. PHP 8.3 / 8.4 / 8.5 の非互換

8.3 以降は致命的な削除がなく、非推奨の蓄積が中心。件数が多いのは 8.4 の「暗黙 nullable 引数」と 8.5 の「非標準キャスト名」で、どちらも機械的に置換できる。8.5 の内容は [php.net の非推奨一覧](https://www.php.net/manual/de/migration85.deprecated.php)、[非互換変更](https://php.net/migration85.incompatible.php)、[RFC](https://wiki.php.net/rfc/deprecations_php_8_5) に基づく。

### PHP 8.3

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 1 | `get_class()` / `get_parent_class()` の引数なし呼び出し、`MT_RAND_PHP`、`assert_options()` と `assert.*` ini、`ldap_connect($host, $port)`、`NumberFormatter::TYPE_CURRENCY`、`U_MULTIPLE_DECIMAL_SEPERATORS` が非推奨 | Deprecated | `static::class`、`zend.assertions` | 低 |
| 2 | `unserialize()` のエラーが E\_WARNING（旧 E\_NOTICE） | ログ種別、`~E_NOTICE` で抑止していたものが表示 | データ修復 | 低 |
| 3 | `array_sum()` / `array_product()` が非数値要素（配列、オブジェクト）で Warning | ログ | 事前フィルタ | 低 |
| 4 | `range()` の引数検証強化（step 0 で ValueError、非数値文字列の扱い変更）、負のインデックスから始まる配列への `[]` 追加キーが `n+1`（旧 0） | 例外 / キー差（稀） | 修正 | 低 |
| 5 | `zend.max_allowed_stack_size`: 深い再帰がセグフォールトでなく Error「Maximum call stack size reached」 | テンプレート・ツリー処理の無限再帰が可視化される | 再帰見直し | 低 |
| 6 | 新関数 / クラス: `json_validate()`、`mb_str_pad()`、`str_increment()` / `str_decrement()`、`#[\Override]`、`DateMalformedStringException` 等（`Exception` のサブクラス） | Cannot redeclare | `function_exists()` ガード | 低 |
| 7 | 型付きクラス定数、動的クラス定数参照 `C::{$name}`、static 変数の初期化式、`readonly` の `__clone` 内再初期化 | 非互換なし | — | — |

### PHP 8.4

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 8 | 暗黙の nullable 引数 `function f(Foo $x = null)` が非推奨（9.0 でエラー） | 型宣言を使うコード全般で大量の Deprecated | `?Foo $x = null` へ（Rector で自動置換可） | 高 |
| 9 | `E_STRICT` 定数非推奨、E\_STRICT レベル削除 | `error_reporting(E_ALL & ~E_STRICT)` で Deprecated | `E_STRICT` を削除 | 中 |
| 10 | `session_set_save_handler()` の 6～8 個のコールバックを渡す旧形式が非推奨 | DB セッションハンドラのレガシー実装で Deprecated | `SessionHandlerInterface` を実装してオブジェクトを渡す | 中 |
| 11 | `xml_set_object()` と、`xml_set_*_handler()` への文字列メソッド名コールバックが非推奨 | 旧 XML パーサラッパで Deprecated | `[$this, 'method']` / クロージャ | 中 |
| 12 | `trigger_error($msg, E_USER_ERROR)` 非推奨 | Deprecated | 例外を throw | 中 |
| 13 | `exit()` / `die()` が関数扱い: 非 int / string 引数で TypeError、`strict_types` の影響を受ける | `exit(null)`、`exit(1.5)` が Fatal | 修正 | 低 |
| 14 | `round()` の内部実装変更（事前丸めの廃止）で境界値の結果が変わりうる | 金額・税計算の最小桁が変わる（サイレント） | 金額は整数（錢単位）または BCMath で計算、回帰テスト | 中 |
| 15 | `password_hash()` の bcrypt 既定コスト 10 → 12 | ハッシュ計算が約 4 倍、`password_needs_rehash()` が true | ログイン時再ハッシュの運用、負荷計測 | 低 |
| 16 | mysqli の非推奨: `mysqli_ping()` / `mysqli::ping()`、`mysqli_kill()`、`mysqli_refresh()`、`MYSQLI_REFRESH_*`、`mysqli::store_result()` の mode 引数（`MYSQLI_STORE_RESULT_COPY_DATA`）、`MYSQLI_SET_CHARSET_DIR`、`MYSQLI_STMT_ATTR_PREFETCH_ROWS`、`MYSQLI_CURSOR_TYPE_FOR_UPDATE` / `SCROLLABLE`、`MYSQLI_TYPE_INTERVAL` | Deprecated | ping → `SELECT 1`、kill → SQL `KILL`、refresh → SQL `FLUSH` | 中 |
| 17 | PDO: `Pdo\Mysql` サブクラスと `PDO::connect()` 追加、`PDO::MYSQL_ATTR_DIRECT_QUERY` が bool 型に | 非互換はほぼなし | — | 低 |
| 18 | その他の非推奨: `_` をクラス名に、`lcg_value()`、`stream_context_set_options()`、`session.sid_length` / `session.sid_bits_per_character` ini、`DOMImplementation::getFeature()`、`DOM_PHP_ERR`、`SplFixedArray::__wakeup()`、`ReflectionMethod::__construct(string)`、`IntlDateFormatter::setTimeZoneId()` 等 | Deprecated | 置換 | 低 |
| 19 | 例外化: `str_getcsv()` の不正な区切り文字、`php_uname()` の不正 mode、`unserialize()` の `allowed_classes` 非配列、`imagejpeg()` 等の不正 quality、`curl_multi_select()` の範囲外 timeout、DOM の一部メソッドが false でなく DOMException、比較中の再帰が Error | Fatal / 例外 | 引数検証 | 低 |
| 20 | `SimpleXMLElement` のメソッド呼び出しや文字列化がイテレータを暗黙リセットしない | foreach 中の挙動差（旧: 無限ループの原因） | テスト | 低 |
| 21 | リソース → オブジェクト（dba、odbc、soap、pgsql の一部）、新クラス `Dom\*`、`Pdo\Mysql`、`BcMath\Number`、`#[\Deprecated]`、新関数 `array_find()` / `array_any()` / `array_all()` / `mb_trim()` / `mb_ucfirst()` / `http_get_last_response_headers()` / `request_parse_body()` | `is_resource()` 判定、名前衝突 | `instanceof`、ガード | 低 |
| 22 | `PHP_DEBUG` / `PHP_ZTS` が bool、一時ファイル名が 13 バイト、JIT 初期化失敗で起動停止 | パス長依存コード | — | 低 |

### PHP 8.5

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 23 | 非標準キャスト名 `(integer)` / `(boolean)` / `(double)` / `(binary)` が非推奨 | 旧コードで頻出。Deprecated | `(int)` / `(bool)` / `(float)` / `(string)` へ一括置換 | 中 |
| 24 | バッククォート演算子 `` `cmd` `` が非推奨 | Deprecated | `shell_exec()`（`escapeshellarg()` を併用） | 低 |
| 25 | `__sleep()` / `__wakeup()` がソフト非推奨 | セッション・キャッシュにシリアライズされるクラスで Deprecated | `__serialize()` / `__unserialize()` を追加（PHP 7 互換が必要なら併記） | 中 |
| 26 | `case 1;`（セミコロン終端）が非推奨 | Deprecated | `case 1:` | 低 |
| 27 | null を配列オフセットや `array_key_exists()` のキーに使うのが非推奨 | `$arr[$undefined]` で Deprecated（未定義変数 Warning と重なる） | `?? ''` | 中 |
| 28 | 非数値文字列のインクリメント `$s = 'a'; $s++;` が非推奨 | Deprecated（連番生成ロジック） | `str_increment()` | 低 |
| 29 | `register_argc_argv` で非 CLI SAPI の `$_SERVER['argv']` をクエリ文字列から導出するのが非推奨、`$http_response_header` 変数が非推奨 | Deprecated | `$_GET`、`http_get_last_response_headers()`（8.4+） | 低 |
| 30 | no-op の解放関数が非推奨: `curl_close()`、`curl_share_close()`、`imagedestroy()`、`finfo_close()`、`xml_parser_free()` | Deprecated（8.0 以降 no-op だった） | 呼び出し削除（旧 PHP も対象なら `PHP_VERSION_ID` 分岐） | 低 |
| 31 | `chr()` に 0～255 範囲外、`ord()` に複数バイト文字列 | Deprecated | 検証 | 低 |
| 32 | PDO: `PDO::MYSQL_ATTR_*` 定数が非推奨 → `Pdo\Mysql::ATTR_*`（8.4 で導入）、`uri:` DSN が非推奨 | Deprecated | 8.4 以上のみ対応なら定数置換 | 中 |
| 33 | mysqli: `mysqli_execute()`（`mysqli_stmt_execute()` の別名）が非推奨 | Deprecated | `mysqli_stmt_execute()` | 低 |
| 34 | `MHASH_*` 定数非推奨（`mhash()` 自体は 8.1 で非推奨） | Deprecated | `hash()` | 低 |
| 35 | SPL: `spl_autoload_unregister('spl_autoload_call')` による全解除、`SplObjectStorage::contains()` / `attach()` / `detach()`、`ArrayObject` / `ArrayIterator` にオブジェクトを渡す | Deprecated | `offsetExists()` 等、配列へ変換 | 低 |
| 36 | Reflection: `setAccessible()`（8.1 以降 no-op）、存在しない定数の `ReflectionClass::getConstant()`、既定値のないプロパティの `getDefaultValue()` | Deprecated | 削除 | 低 |
| 37 | クロージャの不正な bind（static クロージャへのインスタンス束縛、別クラスのメソッドへの束縛、`$this` の解除、内部クラススコープへの束縛）が Warning → Deprecated、定数の再宣言 Deprecated、出力ハンドラ内の echo Deprecated、`__debugInfo()` の null 返却 Deprecated、ini `report_memleaks` / `intl.error_level` 非推奨、`socket_set_timeout()` 非推奨、`DATE_RFC7231` 非推奨、`openssl_pkey_derive()` の `key_length`、`finfo_buffer()` の `context` | Deprecated | 置換 | 低 |
| 38 | 非互換変更: `class_alias()` で `array` / `callable` 不可、比較不能オブジェクトと bool の緩い比較が `(bool)$obj` に統一、トレイトが親クラスより先にバインド、コンパイル / リンク時エラーがユーザエラーハンドラを経由せず即時処理、NAN のキャストで Warning、非配列の分割代入 `[$a] = 1` で Warning、`gc_collect_cycles()` の戻り値変更、`disable_classes` ini の挙動変更、`pcntl_exec()` / `bzcompress()` の ValueError、`DOMNodeList` 等の clone が例外、intl は ICU 57.1 以上 | 稀な挙動差。エラーハンドラでコンパイルエラーを握りつぶしていたコードは停止 | テスト | 低 |
| 39 | OPcache が常時組込み: `zend_extension=opcache.so` を ini に残すと Warning。`--enable-opcache` configure フラグ削除 | 起動時警告 | ini から `zend_extension=opcache` 行を削除（`opcache.enable` は引き続き有効） | 中 |
| 40 | `#[\NoDiscard]`: `DateTimeImmutable::modify()` / `setDate()` / `add()` 等の戻り値を捨てると Warning | 旧来のバグ（immutable を mutable と誤認）が可視化 | 戻り値を使う、意図的なら `(void)` キャスト | 低 |
| 41 | `fatal_error_backtraces=On` 既定: Fatal にスタックトレースが付く | ログ量増、`display_errors=On` の本番で情報露出 | 本番は `display_errors=Off` を徹底 | 低 |
| 42 | 新関数 / クラス: `array_first()` / `array_last()`、`get_error_handler()` / `get_exception_handler()`、`Uri\Rfc3986\Uri` / `Uri\WhatWg\Url`（新 URI 拡張）、`IntlListFormatter`、`locale_is_right_to_left()`、`grapheme_levenshtein()`、`curl_multi_get_handles()`、`PHP_BUILD_DATE` | Cannot redeclare（特に `array_first` / `array_last` は自前実装が多い） | `function_exists()` ガード、`Uri` 名前空間の衝突確認 | 中 |

## 8. php.ini・SAPI・日本語環境

php.ini は 5.3 のものを流用せず、`php.ini-production` をベースに必要な差分だけを移植する。削除済みディレクティブは起動を止めないが警告を出し続け、`short_open_tag` と `date.timezone` と文字コードの 3 点は設定を落とすとサイレントに壊れる。

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 1 | 削除・非推奨 ini ディレクティブ: `register_globals`、`magic_quotes_*`、`safe_mode*`、`register_long_arrays`、`allow_call_time_pass_reference`、`always_populate_raw_post_data`、`asp_tags`、`track_errors`、`mbstring.func_overload`、`mbstring.script_encoding`、`session.hash_*`、`session.entropy_*`、`session.bug_compat_*`、`y2k_compliance`、`define_syslog_variables`、`highlight.bg`、`zend.ze1_compatibility_mode`、`xsl.security_prefs`、`sql.safe_mode`、`assert.quiet_eval`、`iconv.*_encoding`（非推奨）、`mbstring.http_input` / `http_output` / `internal_encoding`（非推奨）、`filter.default`（非推奨）、`auto_detect_line_endings`（非推奨）、`session.sid_*`（非推奨）、`assert.*`（非推奨）、`report_memleaks`（非推奨）、`zend_extension=opcache.so`（8.5 で警告） | 起動時に「Unknown directive」や Deprecated が毎リクエスト出力される（FPM ログが埋まる） | php.ini を新規作成 | 中 |
| 2 | `short_open_tag`: `php.ini-production` は Off。`<?` 開始タグの旧コードが HTML としてそのまま出力される | ソースコード露出（DB 接続情報含む） | 全ファイルを `<?php` に置換（`<?=` は 5.4 以降常時有効）。暫定: `short_open_tag=On` | 高 |
| 3 | `date.timezone` | 未設定で UTC | `Asia/Tokyo` | 高 |
| 4 | 文字コード: `default_charset=UTF-8` 既定。SJIS / EUC-JP で内部処理する場合は `default_charset` をそのエンコードに、`mbstring.language=Japanese`。`mbstring.encoding_translation=On` + `mbstring.http_input=auto` による入力自動変換は非推奨 ini に依存 | 文字化け、`htmlspecialchars` の空文字返却 | 内部エンコードを UTF-8 に統一し、入出力変換はコード側で `mb_convert_encoding()`。ブラウザ向け SJIS 出力が必要なら `ob_start('mb_output_handler')` + `mb_http_output('SJIS-win')` | 高 |
| 5 | SJIS ソースファイル: `zend.multibyte=On` + `zend.script_encoding=SJIS`（旧 `mbstring.script_encoding`） | 5C 問題で Parse error | ソースを UTF-8（BOM なし）へ一括変換（`nkf -w --overwrite` 等）。BOM 付きは `header()` 前の出力になるので禁止 | 高（該当時） |
| 6 | エラー表示: 8.0 既定 `error_reporting=E_ALL`、`display_startup_errors=On` | 本番画面に警告が出る、ヘッダ送信失敗 | 本番: `display_errors=Off`、`log_errors=On`、`error_log` を明示。移行期は Deprecated をログに落として件数管理 | 高 |
| 7 | mod\_php → php-fpm（Apache event MPM / nginx）: `.htaccess` の `php_value` / `php_flag` が無効、`apache_setenv()` / `apache_note()` / `apache_get_modules()` 不可、`$_SERVER['PHP_AUTH_USER']` は Apache 側 `CGIPassAuth On`（2.4.13+）が必要、`$_SERVER['SCRIPT_NAME']` / `PATH_INFO` の差、実行ユーザが pool ユーザに | Basic 認証が通らない、ディレクトリ単位の ini が効かない、ファイル書き込み権限エラー | `.user.ini` または pool の `php_admin_value`、`getallheaders()`（7.3+ で FPM 対応）、nginx は `fastcgi_split_path_info` | 中 |
| 8 | OPcache: `opcache.validate_timestamps=1` / `revalidate_freq=2` でデプロイ直後数秒は旧コードが動く。APC のオペコードキャッシュ設定（`apc.*`）は無効 | デプロイ直後の不整合 | デプロイ時に FPM reload または `opcache_reset()` | 低 |
| 9 | `max_input_vars=1000`（5.3.9 以降） | 1000 を超える input を持つフォーム（一括編集画面）で後半が欠落（サイレント、Warning のみ） | 値を上げる、フォーム分割 | 中 |
| 10 | `variables_order=GPCS`（production）: `$_ENV` が空 | `$_ENV['DB_HOST']` 依存が壊れる | `getenv()` または `EGPCS` | 低 |
| 11 | session: `session.serialize_handler=php_serialize` 推奨（既定 `php` はキーに \` | `  や数字があると壊れる）、 `session.use\_strict\_mode=1`、`session.cookie\_samesite`（7.3+）、`session.cookie\_secure\` | ローリング中に新旧 PHP が同じセッションストアを共有するとシリアライズ形式差で復元失敗 | 切替時にセッション破棄を許容、または handler を揃える |
| 12 | `include_path`: PEAR が既定で入らない（7.4+）、`.`/`/usr/share/pear` の前提が崩れる | `require 'PEAR.php'`、`require 'DB.php'`（PEAR::DB！）が失敗 | Composer へ。PEAR::DB / MDB2 は PHP 8 非対応なので PDO へ書き換え | 中 |
| 13 | `pcre.jit=1` 既定（7.0+）: SELinux 等で JIT メモリ確保が失敗すると `preg_*` がエラー | 正規表現が全て失敗 | `pcre.jit=0` または SELinux ブール設定 | 低 |
| 14 | `memory_limit=128M` 既定、`post_max_size=8M`、`upload_max_filesize=2M`（新しい php.ini の既定） | 旧設定の大きな値が失われる | 差分移植 | 中 |
| 15 | `sendmail_path`、`mail.add_x_header`、`mb_send_mail()` の ISO-2022-JP エンコード（`mb_language('Japanese')`） | メール件名の文字化け | `mb_language()` をコードで明示 | 低 |

## 9. MySQL 5.1 → 5.5 → 5.6 の非互換

5.1 由来の DB で後々まで尾を引くのは、MyISAM 前提のスキーマ設計、TIMESTAMP の暗黙既定、旧パスワードハッシュ、旧時刻フォーマットの 4 点。これらは 8.0 へのアップグレード可否を直接左右するので、旧バージョン上にいるうちに片付ける。

### MySQL 5.5

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 1 | 既定ストレージエンジンが MyISAM → InnoDB。`ENGINE` 省略の `CREATE TABLE`（旧ダンプやアプリの DDL）が InnoDB になる | FULLTEXT インデックス作成がエラー（5.5 の InnoDB は非対応。5.6+ で対応だが挙動差）、複合キー 2 列目の AUTO\_INCREMENT（MyISAM 固有のグループ別連番）が「there can be only one auto column and it must be defined as a key」、`COUNT(*)` が遅くなる、テーブルロック → 行ロックでデッドロックが新たに発生、書き込みがトランザクション前提に | `ENGINE` を明示し、意図的に InnoDB へ。グループ別連番はアプリ側で採番。件数表示はキャッシュ化 | 高 |
| 2 | `TYPE=MyISAM` 構文削除（`ENGINE=` のみ） | 5.1 以前のダンプの import が構文エラー | `sed 's/TYPE=/ENGINE=/'` | 高 |
| 3 | 削除オプション（my.cnf にあると起動失敗）: `--skip-locking` / `--enable-locking`（→ `skip-external-locking`）、`[mysqld]` 節の `default-character-set`（→ `character-set-server`）、`default-collation`、`log-long-format`、`log-update`、`master-host` / `master-user` / `master-password` / `master-port` 等（→ `CHANGE MASTER TO`）、`skip-safemalloc`、`innodb_file_io_threads`（→ `innodb_read_io_threads` / `innodb_write_io_threads`）、`table_cache`（→ `table_open_cache`）、`language`（→ `lc_messages_dir` / `lc_messages`）、`myisam-recover`（→ `myisam-recover-options`） | mysqld が起動しない「unknown variable」 | my.cnf を新規作成して差分移植 | 高 |
| 4 | 削除 SQL: `SHOW INNODB STATUS`（→ `SHOW ENGINE INNODB STATUS`）、`SHOW TABLE TYPES`（→ `SHOW ENGINES`）、`SHOW PLUGIN`（→ `SHOW PLUGINS`）、`LOAD TABLE ... FROM MASTER`、`BACKUP TABLE`、`RESTORE TABLE`、`SHOW COLUMN TYPES`、`SET sql_log_update` | 構文エラー（監視スクリプト） | 置換 | 中 |
| 5 | InnoDB プラグイン 1.1 内蔵: `innodb_use_native_aio=ON` 既定（`fs.aio-max-nr` 不足で起動失敗）、`innodb_file_format=Barracuda` が選択可（既定は Antelope）、`innodb_buffer_pool_instances`、`innodb_strict_mode` | 起動・性能 | sysctl 調整 | 低 |
| 6 | `utf8mb4` 追加（4 バイト文字: 絵文字、𠮷 等）。この時点では任意だが 8.0 で既定になる | — | 13 節の計画をここで始める | 低 |
| 7 | `PARTITION BY KEY` / `LINEAR KEY` のハッシュアルゴリズム変更。5.1 で作成したテーブルは `ALGORITHM=1` 扱いで、8.0 ではサポートされない | 8.0 アップグレード前チェックで要対応 | 5.5.31+ で `ALTER TABLE t PARTITION BY ALGORITHM=2 KEY (...)` で再パーティション | 中（該当時） |
| 8 | pre-4.1 形式の 16 桁パスワードハッシュ（`old_passwords=1`）: 5.5 は動作、5.6 で `secure_auth=ON` 既定、5.7.5 で `mysql_old_password` プラグイン削除 | 該当アカウントが認証不能 | `SELECT user, host, LENGTH(password) FROM mysql.user` で 16 桁を検出し、全てパスワード再設定 | 高 |

### MySQL 5.6

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 9 | TIMESTAMP の暗黙既定（最初の TIMESTAMP 列が自動で `NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP`、`NULL` 代入で現在時刻）が非推奨。`explicit_defaults_for_timestamp` 導入（5.6 / 5.7 既定 OFF、**8.0 既定 ON**） | 8.0 で ON になると: TIMESTAMP 列が NULL 許容に、自動更新が付かない、`NOT NULL` 列への `NULL` 挿入がエラー（旧: 現在時刻）。`updated_at` が更新されなくなる（サイレント） | DDL に `DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` を明示（ダンプも補正）。`NULL` 挿入で現在時刻を期待する SQL を修正。暫定: `explicit_defaults_for_timestamp=OFF`（非推奨） | 高 |
| 10 | 時刻型の新内部フォーマット（5.6.4+、小数秒対応）。5.6.4 より前に作られた DATETIME / TIMESTAMP / TIME 列は旧フォーマットのまま残る | **8.0 へのアップグレードが拒否される**（チェッカーが「temporal columns in old format」を報告）。`avoid_temporal_upgrade` / `show_old_temporals` は 8.4 で削除 | 5.6 / 5.7 上で `mysqlcheck --check-upgrade` で検出し、全該当テーブルに `ALTER TABLE t FORCE`（または dump / reload） | 高 |
| 11 | `innodb_file_per_table=ON` 既定 | 新規テーブルが個別 .ibd に（既存は ibdata1 のまま）。バックアップ手順への影響 | — | 低 |
| 12 | `sql_mode` 既定が `NO_ENGINE_SUBSTITUTION`（5.6.6） | 無効な `ENGINE=`（FEDERATED 無効時等）が警告でなくエラー | 修正 | 低 |
| 13 | 既定値変更: `performance_schema=ON`（メモリ増）、`innodb_buffer_pool_size=128M``=48M`（サイズ変更時は旧 ib\_logfile の削除手順が必要。不一致だと起動失敗）、`max_allowed_packet=4M`、`table_open_cache=2000`、`binlog_checksum=CRC32`（5.5 レプリカが読めない）、`innodb_stats_persistent=ON`、`innodb_old_blocks_time=1000` | 起動失敗・メモリ不足・レプリケーション停止 | 手順化、明示設定 | 中 |
| 14 | オプティマイザ変更（semijoin、materialization、MRR、BKA、ICP、`optimizer_switch`）。`ORDER BY ... LIMIT` の優先度キューソートで同順位行の順序が非決定に | `IN (サブクエリ)` の実行計画変化。ページングで同じ行が重複 / 欠落（サイレント） | `ORDER BY ソート列, 主キー` のようにタイブレークを追加。スロークエリ比較 | 高 |
| 15 | `GRANT` による暗黙ユーザ作成が非推奨（5.7 で `NO_AUTO_CREATE_USER` 既定、8.0 で不可） | `GRANT ALL ON db.* TO 'u'@'%' IDENTIFIED BY 'p'` が 8.0 でエラー | `CREATE USER` → `GRANT` の 2 文に | 高 |
| 16 | 非推奨（5.7 で削除）: `YEAR(2)`（要 ALTER）、`INSERT DELAYED`（5.7 で通常 INSERT 扱い）、`SHOW AUTHORS` / `SHOW CONTRIBUTORS`、`--safe-mode`、`thread_concurrency`（5.7.2 削除）、`innodb_additional_mem_pool_size` / `innodb_use_sys_malloc`（5.7.4 削除）、`storage_engine`（→ `default_storage_engine`、5.7.5 削除）、`timed_mutexes`、`innodb_mirrored_log_groups`、`engine_condition_pushdown`、`have_*` 系変数 | my.cnf で起動失敗 / 構文エラー | 削除 | 中 |
| 17 | `log_slow_queries`（→ `slow_query_log`）、`log`（→ `general_log`）、`--one-thread`、`--skip-thread-priority` が 5.6 で削除 | 起動失敗 | 変更 | 高 |
| 18 | `mysql.user` の `password` 列は 5.7 で `authentication_string` に、`PASSWORD()` は 5.7 非推奨 / 8.0 削除 | `UPDATE mysql.user SET password=PASSWORD('x')` 型のスクリプトが失敗 | `ALTER USER ... IDENTIFIED BY` | 中 |
| 19 | フルテキスト: InnoDB FULLTEXT 追加。MyISAM とは最小トークン長（`innodb_ft_min_token_size=3` vs `ft_min_word_len=4`）、ストップワード、スコア計算が異なる。日本語はどちらも分かち書きしない | 検索結果差 | 5.7.6+ の `WITH PARSER ngram` へ移行（10 節 #22） | 中（該当時） |

## 10. MySQL 5.7 の非互換

5.7 の本質は `sql_mode` 既定の厳格化と、オプティマイザの `derived_merge`。前者はエラーで止まるが、後者は「グループ内の最新行を取る」定番イディオムをサイレントに壊す。`sql_mode` は my.cnf で旧互換値に下げられるが、その文字列に `NO_AUTO_CREATE_USER` を含めると 8.0 で起動できなくなる。

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 1 | `sql_mode` 既定: `ONLY_FULL_GROUP_BY, STRICT_TRANS_TABLES, NO_ZERO_IN_DATE, NO_ZERO_DATE, ERROR_FOR_DIVISION_BY_ZERO, NO_AUTO_CREATE_USER, NO_ENGINE_SUBSTITUTION` | 以下 #2～#5 が一斉に発生 | 暫定: my.cnf で `sql_mode=NO_ENGINE_SUBSTITUTION` 等に下げ、アプリ修正後に既定へ。**`NO_AUTO_CREATE_USER` は 8.0 で無効値（起動失敗 / `SET sql_mode` が 1231 エラー）** | 高 |
| 2 | `ONLY_FULL_GROUP_BY`: `SELECT a, b FROM t GROUP BY a`（1055）、`GROUP BY` にない列での `ORDER BY`（3065）、`SELECT DISTINCT a FROM t ORDER BY b`（3065） | レガシー PHP の集計 SQL が軒並みエラー | 主キーで GROUP BY（関数従属は許可）、`ANY_VALUE()`、サブクエリ化 | 高 |
| 3 | `STRICT_TRANS_TABLES`: 型不正・範囲外・桁あふれが Warning でなくエラー。1366 Incorrect integer value `''`、1406 Data too long、1264 Out of range、1265 Data truncated、1364 Field doesn't have a default value | INSERT / UPDATE が失敗。特に「NOT NULL 列を INSERT で省略」「数値列に空文字」「VARCHAR(10) に 11 文字」 | PHP 側で型変換と既定値付与、DDL に DEFAULT を明示。`INSERT IGNORE` での回避はデータ欠損を隠すので非推奨 | 高 |
| 4 | `NO_ZERO_DATE` / `NO_ZERO_IN_DATE`: `'0000-00-00'`、`'2024-02-00'` が 1292、DDL の `DEFAULT '0000-00-00 00:00:00'` が 1067 Invalid default value | 旧ダンプが import 不可、「未設定日付 = ゼロ日付」設計が破綻 | 列を NULL 許容にして `DEFAULT NULL`、既存データを `UPDATE ... SET d = NULL WHERE d = '0000-00-00'`（非 strict モードで実行）、PHP 側の `'0000-00-00'` 判定を `NULL` 判定に | 高 |
| 5 | `ERROR_FOR_DIVISION_BY_ZERO`: INSERT / UPDATE 内の 0 除算が 1365（SELECT は NULL + 警告） | 更新失敗 | `NULLIF(x, 0)` | 中 |
| 6 | `optimizer_switch` の `derived_merge=on`: FROM 句サブクエリが外側にマージされる。(a) `UPDATE t ... WHERE id IN (SELECT id FROM (SELECT ... FROM t) d)` が 1093「You can't specify target table for update in FROM clause」 (b) `SELECT * FROM (SELECT ... ORDER BY created DESC) x GROUP BY user_id` の ORDER BY が無視され、グループ内の任意行が返る | (a) エラー (b) **結果が間違うがエラーは出ない**。「ユーザごとの最新レコード」「最新価格」等で頻出 | 8.0 のウィンドウ関数 `ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created DESC)` へ書き換え、または相関サブクエリ。暫定: `NO_MERGE()` ヒント、派生テーブルに `LIMIT` | 高 |
| 7 | `GROUP BY` の暗黙ソートが非推奨（8.0 で削除）、`GROUP BY col ASC/DESC` 構文が非推奨（8.0 で構文エラー） | 8.0 で順序不定 / 構文エラー | `ORDER BY` を明示 | 高 |
| 8 | `secure_file_priv` 既定がディレクトリ限定（RPM: `/var/lib/mysql-files`） | `SELECT ... INTO OUTFILE '/tmp/x.csv'`、`LOAD DATA INFILE` が 1290 | 出力先をそのディレクトリに、または `LOAD DATA LOCAL`（PHP: `MYSQLI_OPT_LOCAL_INFILE` / `PDO::MYSQL_ATTR_LOCAL_INFILE`、サーバ `local_infile=ON`） | 中 |
| 9 | 認証関連の非推奨（8.0 削除）: `PASSWORD()`、`SET PASSWORD FOR u = PASSWORD('x')`、`GRANT ... IDENTIFIED BY`、`CREATE USER ... IDENTIFIED BY PASSWORD 'hash'`、`mysql_old_password`、`old_passwords`、`secure_auth` | 運用スクリプト・管理画面のユーザ作成 SQL が 8.0 で失敗 | `CREATE USER u IDENTIFIED BY 'x'`、`ALTER USER u IDENTIFIED BY 'x'`。ハッシュ指定は `IDENTIFIED WITH caching_sha2_password AS '...'` | 高 |
| 10 | 暗号関数の非推奨（8.0 削除）: `ENCODE()` / `DECODE()`、`ENCRYPT()`、`DES_ENCRYPT()` / `DES_DECRYPT()`、`OLD_PASSWORD()` | 「簡易隠蔽」に `ENCODE` を使った列が 8.0 で復号不能 | 8.0 移行前に `DECODE()` で平文化し `AES_ENCRYPT()`（またはアプリ側暗号化）で再暗号化 | 高（該当時） |
| 11 | 空間関数の旧名非推奨（8.0 削除）: `GeomFromText` → `ST_GeomFromText`、`AsText` → `ST_AsText`、`X()` / `Y()` → `ST_X` / `ST_Y`、`Contains()` → `MBRContains()` / `ST_Contains()`、`GLength` → `ST_Length`、`Distance` → `ST_Distance` | 8.0 で「FUNCTION does not exist」 | `ST_` 接頭辞へ（MBR 系と ST 系は意味が異なるので要確認） | 中（該当時） |
| 12 | `innodb_strict_mode=ON` 既定（5.7.7）: 行サイズ超過（1118 Row size too large > 8126）、不正な `KEY_BLOCK_SIZE` / `ROW_FORMAT` がエラー | VARCHAR(255) を多数持つテーブルの CREATE / ALTER（utf8mb4 変換時に顕在化） | 列を TEXT 化、`ROW_FORMAT=DYNAMIC` | 中 |
| 13 | `innodb_default_row_format=DYNAMIC`、`innodb_large_prefix=ON`、`innodb_file_format=Barracuda` 既定（5.7.7 / 5.7.9）。既存の COMPACT テーブルは 767 バイト制限のまま | utf8mb4 の `VARCHAR(255)` へのユニークキーで 1071 Specified key was too long | 変換前に `ALTER TABLE t ROW_FORMAT=DYNAMIC` | 高 |
| 14 | `show_compatibility_56=OFF` 既定: `information_schema.GLOBAL_STATUS` / `SESSION_STATUS` / `GLOBAL_VARIABLES` / `SESSION_VARIABLES` が 3167 エラー（8.0 でテーブル自体削除） | 監視・管理画面の SQL が失敗 | `performance_schema.global_status` / `global_variables`、`SHOW GLOBAL STATUS` | 中 |
| 15 | systemd 環境で `mysqld_safe` 不使用: `[mysqld_safe]` 節（`log-error`、`pid-file`、`open-files-limit`、`malloc-lib`）が無視 | ログ出力先が変わる、FD 上限不足 | `[mysqld]` 節へ移動、systemd `LimitNOFILE` | 中 |
| 16 | `log_timestamps=UTC` 既定（5.7.2） | エラーログ・スロークエリログの時刻が UTC（JST と 9 時間ずれる） | `log_timestamps=SYSTEM` | 中 |
| 17 | `mysql_install_db` → `mysqld --initialize`（root の一時パスワード、`password_expired`）、RPM では `validate_password` が有効 | 初期化スクリプト、弱いパスワードの拒否 | 手順更新、`validate_password` ポリシー調整 | 中 |
| 18 | 既定値変更: `binlog_format=ROW`、`sync_binlog=1`、`innodb_buffer_pool_dump_at_shutdown` / `load_at_startup=ON`、`innodb_page_cleaners=4`、`innodb_purge_threads=4`、`table_open_cache_instances=16`、`innodb_checksum_algorithm=crc32`（5.6 へのダウングレード不可）、`eq_range_index_dive_limit=200`、`binlog_error_action=ABORT_SERVER` | 性能特性変化、ロールバック不可 | ベンチマーク、バックアップ | 中 |
| 19 | 削除 / 非推奨: `ALTER IGNORE TABLE`、`INSERT DELAYED`（通常 INSERT に）、`YEAR(2)`、`--skip-innodb`（InnoDB 必須）、`EXPLAIN EXTENDED` / `EXPLAIN PARTITIONS`（8.0 削除）、`PROCEDURE ANALYSE()`（8.0 削除）、クエリキャッシュと `SQL_CACHE`（5.7.20 非推奨、8.0 削除）、`tx_isolation`（5.7.20 非推奨、8.0 削除） | 構文エラー | 置換 | 中 |
| 20 | `GET_LOCK()` が複数ロックを同時保持（2 回目の `GET_LOCK` が 1 回目を解放しない） | ロック設計の挙動差 | `RELEASE_LOCK()` を明示 | 低 |
| 21 | 新予約語: 5.5 `GENERAL`、`IGNORE_SERVER_IDS`、`MASTER_HEARTBEAT_PERIOD`、`MAXVALUE`、`RESIGNAL`、`SIGNAL`、`SLOW`；5.6 `GET`、`IO_AFTER_GTIDS`、`IO_BEFORE_GTIDS`、`MASTER_BIND`、`ONE_SHOT`、`PARTITION`、`SQL_AFTER_GTIDS`、`SQL_BEFORE_GTIDS`；5.7 `GENERATED`、`OPTIMIZER_COSTS`、`STORED`、`VIRTUAL` | 列名 `partition`、`signal`、`stored`、`get` 等で構文エラー | バッククォート、リネーム | 中 |
| 22 | 日本語全文検索: ngram パーサ（5.7.6、`ngram_token_size=2`）と MeCab プラグイン。MyISAM FULLTEXT + アプリ側 bigram 前処理や Tritonn / Senna からの移行先 | 検索結果・スコアが変わる | `FULLTEXT (col) WITH PARSER ngram` で再インデックス、`innodb_ft_min_token_size` 調整 | 中（該当時） |
| 23 | `mysql.user` の構造変更（`Password` 列削除、`plugin` 列必須）、権限テーブルへの直接 DML は非推奨 | ユーザ管理スクリプトの失敗 | アカウント管理文（`CREATE USER` / `ALTER USER` / `GRANT`）のみ使う | 中 |

## 11. MySQL 8.0 の非互換

8.0 は認証（caching\_sha2\_password）と文字コード（utf8mb4\_0900\_ai\_ci）の既定変更で旧 PHP から接続できなくなり、データディクショナリ化でアップグレード前のスキーマ正規化が必須になる。my.cnf の削除変数（特に `query_cache_*`）は起動自体を止める。非推奨・削除の全体像は [Percona の整理](https://www.percona.com/blog/mysql-8-0-deprecated-features-what-you-need-to-know/) と公式の [What Is New](https://dev.mysql.com/doc/en/mysql-nutshell.html) を参照。

### 認証・アカウント

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 1 | 既定認証プラグインが `caching_sha2_password`。非 TLS の TCP 接続では初回に RSA 公開鍵交換が走る | 旧クライアント（libmysqlclient < 8.0、PHP 7.4 未満の mysqlnd）が「The server requested authentication method unknown to the client \[caching\_sha2\_password\]」 | PHP を 7.4+（mysqlnd）へ先に更新。暫定: 該当ユーザを `IDENTIFIED WITH mysql_native_password`（8.4 で既定無効になるので恒久策にしない） | 高 |
| 2 | `character_set_server=utf8mb4`、`collation_server=utf8mb4_0900_ai_ci` 既定（旧 latin1 / latin1\_swedish\_ci）。照合 ID 255 | PHP 5.x 系ドライバが「Server sent charset (255) unknown to the client」で接続不能（[Red Hat Bugzilla](https://bugzilla.redhat.com/show_bug.cgi?id=1646158)）。`CREATE DATABASE` 省略時の既定が 0900\_ai\_ci になり既存 general\_ci と混在 | 移行期は my.cnf で `collation_server=utf8mb4_general_ci` を明示。PHP 側で接続 charset を必ず指定。照合の方針は 13 節 | 高 |
| 3 | `GRANT` でのユーザ作成不可、`GRANT ... IDENTIFIED BY` 削除、`PASSWORD()` 削除、`SET PASSWORD ... = PASSWORD()` 削除、`IDENTIFIED BY PASSWORD 'hash'` 削除。権限テーブルはデータディクショナリ管理（InnoDB） | セットアップスクリプトが構文エラー。**5.x の `mysql` スキーマのダンプを 8.0 に import してはいけない** | `CREATE USER` → `GRANT`。ユーザ移行は `SHOW GRANTS` の出力を元に DDL で再作成 | 高 |
| 4 | `SUPER` 非推奨 → 動的権限。mysqldump は 8.0.21+ で `PROCESS` 権限が必要（なければ `--no-tablespaces`）。`DEFINER=` 付きのビュー / トリガ / ルーチンの import には `SET_USER_ID`（8.4 では `SET_ANY_DEFINER`） | 非 root ユーザでの dump / restore が 1227 Access denied | `sed` で `DEFINER=` を除去するか権限付与。`SET GLOBAL` には `SYSTEM_VARIABLES_ADMIN`、他セッションの `KILL` には `CONNECTION_ADMIN` | 高 |
| 5 | `validate_password` コンポーネント（RPM / `mysql_secure_installation`）、`password_history`、`--skip-grant-tables` 時の `skip-networking` 強制 | 弱いパスワードの拒否、リモートからのリセット不可 | ポリシー調整 | 低 |

### SQL の意味・構文

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 6 | `GROUP BY` の暗黙ソート削除、`GROUP BY col ASC/DESC` 構文削除 | 集計一覧の並びが崩れる（サイレント）、構文エラー | `ORDER BY` 明示 | 高 |
| 7 | 派生テーブル・UNION 各要素の `ORDER BY` は `LIMIT` がないと無視される | 10 節 #6 のイディオムが確定的に壊れる | ウィンドウ関数へ書き換え | 高 |
| 8 | `sql_mode` の削除値: `NO_AUTO_CREATE_USER`、`DB2`、`MAXDB`、`MSSQL`、`MYSQL323`、`MYSQL40`、`ORACLE`、`POSTGRESQL`、`NO_FIELD_OPTIONS`、`NO_KEY_OPTIONS`、`NO_TABLE_OPTIONS` | my.cnf や `SET sql_mode` / `PDO::MYSQL_ATTR_INIT_COMMAND` の文字列に含むと起動失敗 / 1231 エラー | 文字列から除去 | 高 |
| 9 | 削除構文・機能: クエリキャッシュ（`SELECT SQL_CACHE` が構文エラー、`SQL_NO_CACHE` は無視、`FLUSH QUERY CACHE` / `RESET QUERY CACHE` 削除）、`EXPLAIN EXTENDED` / `PARTITIONS`、`PROCEDURE ANALYSE()`、`ALTER TABLE ... UPGRADE PARTITIONING`、`\N` を NULL として書く構文、`information_schema.GLOBAL_*`、旧空間関数、`ENCODE` / `DECODE` / `ENCRYPT` / `DES_*` / `PASSWORD` / `OLD_PASSWORD`、`tx_isolation` / `tx_read_only`（→ `transaction_isolation` / `transaction_read_only`；`SET SESSION tx_isolation = ...` が 1193） | 構文エラー、関数不存在 | 置換（PHP 側の `SET tx_isolation` も検索） | 高 |
| 10 | 削除変数（my.cnf にあると起動失敗）: `query_cache_type` / `query_cache_size` / `query_cache_limit` 等、`innodb_file_format` / `innodb_file_format_check` / `innodb_file_format_max`、`innodb_large_prefix`、`innodb_support_xa`、`innodb_checksums`、`innodb_locks_unsafe_for_binlog`、`innodb_stats_sample_pages`、`innodb_undo_logs`、`secure_auth`、`old_passwords`、`sync_frm`、`multi_range_count`、`log_warnings`（→ `log_error_verbosity`）、`have_crypt`、`ignore_builtin_innodb`、`ignore_db_dirs`、`date_format` / `datetime_format` / `time_format`、`max_tmp_tables`、`metadata_locks_cache_size` / `metadata_locks_hash_instances`、`show_compatibility_56`、`log_builtin_as_identified_by_password`、`--bootstrap`、`--des-key-file`、`--partition` / `--skip-partition`、`--temp-pool` | mysqld 起動不能 | `mysqld --validate-config`（8.0.16+）で事前検証 | 高 |
| 11 | 非推奨（8.4 でも動作、将来削除）: `SQL_CALC_FOUND_ROWS` / `FOUND_ROWS()`（8.0.17、ページングの定番）、`INSERT ... ON DUPLICATE KEY UPDATE c = VALUES(c)`（8.0.20 → 行エイリアス `INSERT ... AS new ON DUPLICATE KEY UPDATE c = new.c`）、`BINARY` 演算子（8.0.27 → `CAST(... AS BINARY)`）、整数表示幅 `INT(11)` と `ZEROFILL`（8.0.17、`SHOW CREATE TABLE` から消える）、`FLOAT(M,D)` / \`UNSIGNED FLOAT | DECIMAL`、`utf8`=`utf8mb3`  の名称（将来 utf8mb4 に切替予定）、 `JSON\_MERGE`、`PAD\_CHAR\_TO\_FULL\_LENGTH`、`SHOW PROFILES`、`mysql\_native\_password`（8.0.34）、`binlog\_format`（8.0.34）、`expire\_logs\_days`、`innodb\_log\_file\_size` （8.0.30 →  `innodb\_redo\_log\_capacity`）、`slave\_*`/`master\_*`  名の変数（8.0.26）、 `SET\_USER\_ID`（8.2）、`--character-set-client-handshake\`（8.2） | Warning。PHP 側では `SQL_CALC_FOUND_ROWS` と `VALUES()` が多い | 件数は別 `COUNT(*)`、行エイリアス構文（8.0.20+ 限定なので DB 更新完了後に） |
| 12 | 新予約語（8.0.x 累積）: `CUME_DIST`、`DENSE_RANK`、`EMPTY`、`EXCEPT`（8.0.31）、`FIRST_VALUE`、`FUNCTION`、`GROUPING`、`GROUPS`、`INTERSECT`（8.0.31）、`JSON_TABLE`、`LAG`、`LAST_VALUE`、`LATERAL`（8.0.14）、`LEAD`、`NTH_VALUE`、`NTILE`、`OF`、`OVER`、`PERCENT_RANK`、`RANK`、`RECURSIVE`、`ROW`、`ROWS`、`ROW_NUMBER`、`SYSTEM`、`WINDOW`、`ARRAY` / `MEMBER`（8.0.17） | 列名 `rank`、`system`、`groups`、`lead`、`function`、`window`、`row_number` 等で構文エラー。ビュー定義に含まれているとアップグレード失敗 | バッククォート。ORM / クエリビルダが自動クォートするか確認 | 高 |
| 13 | `REGEXP` / `RLIKE` が Henry Spencer → ICU（8.0.4）: UTF-8 列で文字単位マッチ（旧はバイト単位）、`[[:<:]]` / `[[:>:]]` 不可（→ `\\b`）、バックスラッシュは文字列リテラル内で二重化、`regexp_time_limit` / `regexp_stack_limit` 超過で 3699 / 3698。`REGEXP_REPLACE()` / `REGEXP_SUBSTR()` / `REGEXP_INSTR()` 追加 | 日本語列への `REGEXP '^.{5}$'` 等の結果が変わる（サイレント）、エラー | 正規表現の棚卸しとテスト | 中 |
| 14 | `information_schema` のビュー化: 列名が大文字で返る（`SELECT table_name FROM information_schema.tables` の結果キーが `TABLE_NAME`）、`TABLES.TABLE_ROWS` / `AUTO_INCREMENT` / `UPDATE_TIME` / `DATA_LENGTH` はキャッシュ（`information_schema_stats_expiry=86400`）、`COLUMNS.COLUMN_TYPE` に表示幅なし | PHP の `$row['table_name']` が undefined、AUTO\_INCREMENT 値や行数が最大 1 日古い、`int(11)` をパースするコードが壊れる | 列名を大文字か `AS` 別名、`information_schema_stats_expiry=0` または `ANALYZE TABLE` | 中 |
| 15 | `lower_case_table_names` は初期化時にのみ設定可（データディレクトリと異なると起動失敗）。Linux 既定 0 | Windows 由来（=1）や旧設定の移行で起動不能、テーブル名の大文字小文字混在で「Table doesn't exist」 | `mysqld --initialize --lower-case-table-names=1` で初期化してから dump / reload | 高 |
| 16 | データディクショナリ: .frm 廃止、アトミック DDL、MyISAM パーティションテーブル不可、ストアドルーチン / ビュー / トリガに無効な構文（削除関数、`GROUP BY ... DESC`、予約語）があるとアップグレード失敗、`FTS_` で始まるテーブル名、64 文字超の外部キー名、データディクショナリ予約テーブル名との衝突 | アップグレードが途中で失敗（ロールバックはバックアップから） | MySQL Shell `util.checkForServerUpgrade()` で全項目クリアしてから実施 | 高 |
| 17 | 旧時刻フォーマット列（5.6.4 以前作成）が残っているとアップグレード不可 | 5.1 由来 DB で必ず発生 | 5.7 上で `ALTER TABLE ... FORCE`（9 節 #10） | 高 |
| 18 | `explicit_defaults_for_timestamp=ON` 既定 | TIMESTAMP 列の挙動変化（9 節 #9） | DDL 明示 | 高 |
| 19 | 文字列比較の PAD 属性: `utf8mb4_0900_*` は NO PAD（`'a' = 'a '` が false、ユニークキーで `'a'` と `'a '` が別行） | 末尾空白を含む既存データが一致しない / 重複判定が変わる（サイレント） | 13 節 #5 | 高 |
| 20 | `innodb_autoinc_lock_mode=2`（interleaved）既定 | 複数行 `INSERT` の AUTO\_INCREMENT が連番にならず、`LAST_INSERT_ID() + n` で ID を推定するコードが破綻 | 1 行ずつ INSERT するか再 SELECT。暫定: `innodb_autoinc_lock_mode=1` | 中 |
| 21 | AUTO\_INCREMENT カウンタの永続化（再起動で max+1 に戻らない） | 削除済み最大 ID の再利用がなくなる（改善） | — | 低 |
| 22 | オプティマイザ: ハッシュジョイン（8.0.18）、`prefer_ordering_index`（8.0.21、`ORDER BY ... LIMIT` で索引選択が変わり遅延）、skip scan、派生条件プッシュダウン、ヒストグラム | 実行計画の退行 | スロークエリ比較、`optimizer_switch='prefer_ordering_index=off'`、ヒント | 中 |

### 運用・既定値

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 23 | `log_bin=ON` 既定（`server_id=1`）、`binlog_expire_logs_seconds` = 30 日 | ディスク消費増 | 不要なら `disable_log_bin`、必要なら保持期間設定 | 中 |
| 24 | `event_scheduler=ON` 既定 | 5.x で定義されたまま眠っていた EVENT が動き出す | 事前に `SHOW EVENTS` で棚卸し | 中 |
| 25 | X Plugin（ポート 33060）既定有効 | ファイアウォール / 監査 | `mysqlx=OFF` | 低 |
| 26 | TLS: 8.0.28 で TLSv1.0 / 1.1 削除、自己署名証明書の自動生成、`require_secure_transport` | 古い OpenSSL の PHP から TLS 接続不可、証明書検証失敗 | PHP 側設定は 14 節 #11 | 中 |
| 27 | 既定値: `max_allowed_packet=64M`（5.x: 1～4M）、`innodb_undo_tablespaces=2`、`innodb_flush_neighbors=0`、`innodb_max_dirty_pages_pct=90`、`log_error_verbosity=2`、`max_error_count=1024`、`table_open_cache=4000`、`innodb_dedicated_server`、`sql_require_primary_key`（OFF）、`cte_max_recursion_depth=1000`、内部一時テーブルが TempTable（`temptable_max_ram=1G`） | 挙動・メモリプロファイルの変化 | 明示設定と監視 | 低 |
| 28 | クライアントツール: 8.0 の mysqldump で 5.7 以下をダンプするときは `--column-statistics=0`、`--set-gtid-purged=OFF`。8.0 のダンプ（`utf8mb4_0900_ai_ci`、`/*!80016 DEFAULT ENCRYPTION='N' */`）は 5.7 に戻せない。mysql CLI は対話時 `--binary-as-hex` 既定 | dump 失敗、BINARY 列が 0x 表示 | オプション指定 | 中 |
| 29 | `mysql_upgrade` は不要（8.0.16+ でサーバが自動実行、`--upgrade=` オプション）。アップグレード経路は 5.7 最新 GA → 8.0 のみ（5.6 以下から直接不可）、ダウングレード不可 | 手順変更、ロールバック計画 | 事前フルバックアップとリハーサル | 高 |

## 12. MySQL 8.4 LTS の非互換

8.4 は 8.0 で非推奨だったものを実際に削除した最初のリリース。起動を止めるのは my.cnf の `default_authentication_plugin`、`expire_logs_days`、`skip-character-set-client-handshake`。接続を止めるのは `mysql_native_password` の既定無効化。根拠は [8.4.0 リリースノート](https://dev.mysql.com/doc/relnotes/mysql/8.4/en/news-8-4-0.html)、[8.3.0 リリースノート](https://dev.mysql.com/doc/relnotes/mysql/8.4/en/news-8-3-0.html)、[What Is New in MySQL 8.4](https://docs.oracle.com/cd/E17952_01/mysql-8.4-en/mysql-nutshell.html)。

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 1 | `mysql_native_password` プラグインが既定で無効（`mysql_native_password=OFF`）。9.x で完全削除 | 該当アカウント（アプリ、レプリケーション、監視、バックアップ用）が 1524「Plugin 'mysql\_native\_password' is not loaded」で認証失敗 | 事前に `SELECT user, host, plugin FROM mysql.user WHERE plugin = 'mysql_native_password'` で洗い出し、`ALTER USER ... IDENTIFIED WITH caching_sha2_password BY '...'`（PHP 7.4+ 必須）。暫定: my.cnf に `mysql_native_password=ON` | 高 |
| 2 | `default_authentication_plugin` 変数削除 → `authentication_policy`（8.0.27+） | my.cnf に残っていると起動失敗 | `authentication_policy='caching_sha2_password,,'`。旧プラグインを許すなら `'*,,'` | 高 |
| 3 | 削除変数 / オプション（my.cnf にあると起動失敗）: `expire_logs_days`（→ `binlog_expire_logs_seconds`）、`master_info_repository` / `relay_log_info_repository`、`binlog_transaction_dependency_tracking`（WRITESET 固定）、`transaction_write_set_extraction`、`log_bin_use_v1_row_events`、`avoid_temporal_upgrade` / `show_old_temporals`、`innodb_api_*`（memcached）、`group_replication_ip_whitelist` / `group_replication_recovery_complete_at`、`slave_rows_search_algorithms`、`old` / `new`、**`--character-set-client-handshake`**（`skip-character-set-client-handshake` も削除）、`--old-style-user-limits`、`--skip-host-cache`（→ `host_cache_size=0`）、`--abort-slave-event-count` / `--disconnect-slave-event-count`、`admin-ssl` / ssl / skip-ssl、language（innodb\_log\_file\_size・temptable\_use\_mmap・replica\_parallel\_type は非推奨であり削除ではない） | mysqld 起動不能。日本語運用で常套の `skip-character-set-client-handshake`（クライアントの charset を無視してサーバ側に強制）に代替はない | `mysqld --validate-config` で検証。charset は PHP 側で必ず明示（14 節 #3） | 高 |
| 4 | 削除 SQL: `SHOW MASTER STATUS`（→ `SHOW BINARY LOG STATUS`）、`SHOW SLAVE STATUS`（→ `SHOW REPLICA STATUS`）、`SHOW SLAVE HOSTS`（→ `SHOW REPLICAS`）、`START SLAVE` / `STOP SLAVE` / `RESET SLAVE`（→ `REPLICA`）、`CHANGE MASTER TO`（→ `CHANGE REPLICATION SOURCE TO`）、`RESET MASTER`（→ `RESET BINARY LOGS AND GTIDS`）、`PURGE MASTER LOGS`（→ `PURGE BINARY LOGS`）、`SHOW MASTER LOGS`（→ `SHOW BINARY LOGS`）、`FLUSH HOSTS`（→ `TRUNCATE TABLE performance_schema.host_cache`）、`WAIT_UNTIL_SQL_THREAD_AFTER_GTIDS()`（→ `WAIT_FOR_EXECUTED_GTID_SET()`）、ステータス変数 `Com_slave_*`（→ `Com_replica_*`） | 監視（旧版 mysqld\_exporter 等）・フェイルオーバ・バックアップスクリプトが構文エラー。`REPLICATION SLAVE` 権限名と `slave_*` 系の一部変数は残存 | 置換 | 高 |
| 5 | 削除ツール: `mysqlpump`、`mysql_upgrade`、`mysql_ssl_rsa_setup` | バックアップ / アップグレードスクリプト失敗 | `mysqldump`、MySQL Shell `util.dumpInstance()`。アップグレードはサーバが自動実行 | 中 |
| 6 | 削除権限: `SET_USER_ID` → `SET_ANY_DEFINER` / `ALLOW_NONEXISTENT_DEFINER` | `DEFINER=` 付きダンプの import 権限が変わる | 権限付与を更新 | 中 |
| 7 | InnoDB 既定値変更（my.cnf で未設定の場合のみ）: `innodb_adaptive_hash_index=OFF`、`innodb_change_buffering=NONE`、`innodb_flush_method=O_DIRECT`、`innodb_io_capacity=10000` / `innodb_io_capacity_max=20000`、`innodb_log_buffer_size=64M`、`innodb_doublewrite_pages=128`、`innodb_numa_interleave=ON`、`innodb_page_cleaners=4`、`innodb_purge_threads=1`（16 vCPU 以下）、`innodb_read_io_threads` / `innodb_parallel_read_threads` が CPU 数依存、`innodb_use_fdatasync=ON`、`innodb_buffer_pool_in_core_file=OFF` | I/O 負荷パターンと性能特性が変わる（小規模ディスクで `io_capacity=10000` は過大） | 主要値を my.cnf に明示し、ベンチマーク | 中 |
| 8 | レプリケーション既定: `replica_parallel_workers=4`、`replica_preserve_commit_order=ON`、依存追跡は WRITESET 固定、`binlog_format` 非推奨（ROW 以外は将来削除） | 構成変更 | — | 低 |
| 9 | TLS: PFS なし / 非 SHA2 の弱い暗号スイートを拒否、`tls_version` 既定 TLSv1.2,TLSv1.3 | 古いクライアントの TLS 接続失敗 | PHP 側が OpenSSL 1.1.1+ なら問題なし | 低 |
| 10 | 認証・プラグイン: `authentication_fido` → `authentication_webauthn`、`keyring_file` / `keyring_encrypted_file` プラグイン → コンポーネント、`mysql_native_password` クライアント側プラグインの警告 | Enterprise 機能中心 | — | 低 |
| 11 | `$` で始まる引用符なし識別子が非推奨 | `$col` のような列名で警告 | バッククォート | 低 |
| 12 | アップグレード経路: 8.0.x → 8.4.x はインプレース可（8.0 の最新パッチ推奨）。5.7 → 8.4 直接は不可（8.0 経由）。8.4 → 8.0 ダウングレード不可 | 計画 | MySQL Shell `util.checkForServerUpgrade()` は 8.0 → 8.4 に対応 | 高 |
| 13 | サポート期限: 8.0 は 2026-04 で終了済み。8.4 LTS はプレミアサポート 2029-04、延長サポート 2032-04 | 8.0 に留まる選択肢はない | — | — |

## 13. 文字コード・照合順序（日本語）

日本語 DB の移行で最もデータを壊すのは、(1) latin1 列に別エンコードのバイト列が入っている「誤宣言 DB」をそのまま `CONVERT TO` すること、(2) 8.0 既定の `utf8mb4_0900_ai_ci` が濁点・かなの区別をしないこと、(3) `_0900_` 照合の NO PAD。接続文字コードは PHP の API で明示する（[php.net 文字セットの説明](https://php.net/manual/ja/mysqlinfo.concepts.charset.php)）。

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 1 | latin1 誤宣言 DB: 5.1 時代の既定 `character_set_server=latin1` で、`SET NAMES` なしに SJIS / UTF-8 のバイト列を latin1 列に格納していた（読み書きとも無変換なので動いていた） | `ALTER TABLE ... CONVERT TO CHARACTER SET utf8mb4` すると latin1 → utf8mb4 の「正しい」変換が走り全データが化ける。`SET NAMES utf8mb4` を付けただけでも既存データは化ける | 列ごとに 2 段階: `ALTER TABLE t MODIFY c VARBINARY(n)` → `ALTER TABLE t MODIFY c VARCHAR(n) CHARACTER SET cp932`（実バイト列の本来のエンコード）→ `CONVERT TO utf8mb4`。mysqldump なら `--default-character-set=latin1 --skip-set-charset` でバイトを保全し、ダンプの `CHARSET=latin1` を書き換えてインポート | 高 |
| 2 | `sjis` vs `cp932`、`ujis` vs `eucjpms`: `～` (0x8160) は sjis で U+301C、cp932 で U+FF5E。同様に `－` `∥` `￠` `￡` `￢`。NEC 特殊文字（① ㈱ №）、IBM 拡張漢字（髙 﨑 稄）は sjis / ujis に存在しない | utf8mb4 変換時に `?` 化、strict モードではエラー、往復で別のコードポイントになる | Windows 由来データは `cp932` / `eucjpms` を元エンコードに指定。PHP 側も `mb_convert_encoding($s, 'UTF-8', 'SJIS-win')`（`'SJIS'` ではなく）、接続 charset は `cp932` | 高 |
| 3 | `utf8`（utf8mb3）→ `utf8mb4`: 4 バイト文字（絵文字、𠮷 𩼸 など JIS X 0213 の一部、CJK 拡張 B）は utf8mb3 列に入らない（strict: 1366 エラー、非 strict: その文字以降が切り捨て） | 人名漢字・絵文字の欠落。変換時は `VARCHAR(N)` のバイト上限（utf8mb4 は最大 16383 文字）で `VARCHAR(20000)` がエラー、多列テーブルで 1118 Row size too large、インデックスプレフィックス 767 バイト超過（1071） | 全列 utf8mb4 へ。先に `ROW_FORMAT=DYNAMIC`、長い VARCHAR は TEXT へ、TEXT はバイト上限が同じなので文字数上限が 1/4 になる点に注意（MEDIUMTEXT へ） | 高 |
| 4 | 8.0 既定照合 `utf8mb4_0900_ai_ci`（UCA 9.0、アクセント・大文字小文字非区別）: 日本語では濁点・半濁点を無視（は ＝ ば ＝ ぱ）、ひらがな ＝ カタカナ、小書き文字を同一視 | `WHERE name = 'はし'` が「バシ」「パシ」にもヒット、`UNIQUE` 列を変換すると 1062 重複、`ORDER BY` の並び順変化（すべてサイレント） | 日本語列は `utf8mb4_ja_0900_as_cs`（濁点・大小区別、かな同一視）、`utf8mb4_ja_0900_as_cs_ks`（かなも区別）、または `utf8mb4_bin`。旧挙動維持なら `utf8mb4_general_ci`（濁炳は区別、かなも区別、英字のみ大小非区別）を `collation_server` に明示 | 高 |
| 5 | PAD 属性: `_0900_` 照合は NO PAD、`utf8mb4_general_ci` / `utf8mb4_bin` / `utf8_*` / `cp932_*` は PAD SPACE | `'A' = 'A '` の結果が true → false、CHAR 列や固定長コードで末尾空白を含むデータの照合・重複判定が変わる（サイレント） | 照合を統一し、変換前に `UPDATE t SET c = TRIM(TRAILING ' ' FROM c)`。`utf8mb4_0900_bin` と `utf8mb4_bin` は PAD が異なる点に注意 | 高 |
| 6 | 照合の混在: 旧テーブル（`utf8_general_ci` / `utf8mb4_general_ci`）と新テーブル（`utf8mb4_0900_ai_ci`）の JOIN / UNION / `CASE` / `IF()` / `CONCAT` の比較 | 1267 / 1271 Illegal mix of collations。新規テーブルを追加した瞬間に既存クエリが失敗 | DB 全体で照合を統一（`ALTER DATABASE ... COLLATE`、`ALTER TABLE ... CONVERT TO CHARACTER SET utf8mb4 COLLATE ...`）、`collation_server` を明示 | 高 |
| 7 | 接続文字コード: PHP は `mysqli_set_charset($c, 'utf8mb4')` / DSN `charset=utf8mb4` で指定。`SET NAMES` をクエリで発行しても `mysqli_real_escape_string()` / `PDO::quote()` のエスケープは追従しない。mysqlnd は `[client] default-character-set` を読まない。`skip-character-set-client-handshake` は 8.4 で削除 | 文字化け。SJIS 接続で `SET NAMES sjis` + エスケープ関数の組合せは 5C 問題による **SQL インジェクション** | API で設定し、プリペアドステートメントへ。SJIS 運用を続けるなら `cp932` を指定（`sjis` は不可） | 高 |
| 8 | ソート順: `general_ci` は CJK ではコードポイント順、`0900_ai_ci` は UCA 順、`ja_0900_as_cs` は JIS X 4061（五十音）順 | 一覧の並びが変わる | 要件に応じて列単位の `COLLATE` 指定 | 中 |
| 9 | `LENGTH()` はバイト長（utf8mb4 で最大 4 / 文字）、`CHAR_LENGTH()` は文字数 | 桁チェック SQL（`WHERE LENGTH(code) <= 10`）が utf8mb3 → utf8mb4 で変わる。`LEFT()` / `SUBSTRING()` は文字単位で安全 | `CHAR_LENGTH()` | 中 |
| 10 | mysqldump の文字コード: 8.0 の既定 `--default-character-set=utf8mb4`、5.x は `utf8`。バイナリ列は `--hex-blob` | ダンプ経由での化け | 明示指定 | 中 |
| 11 | `utf8` の名称: 8.0 以降 `utf8` は `utf8mb3` の別名で警告 3719。将来 `utf8` = `utf8mb4` に切替予定 | DDL / `SET NAMES utf8` / `mb_convert_encoding` との混同 | DDL と PHP の指定を `utf8mb4` に一括置換 | 低 |
| 12 | PHP mbstring 側のエンコード名: `SJIS` / `SJIS-win`（= `CP932`）/ `SJIS-2004`、`EUC-JP` / `eucJP-win`（= `CP51932`）、`JIS` / `ISO-2022-JP` / `ISO-2022-JP-MS`。8.1～8.3 で変換テーブルが修正され機種依存文字の結果が変わる場合がある | 往復差 | MySQL 側と対応を固定（cp932 ↔ SJIS-win、eucjpms ↔ eucJP-win）し、`① ② ㈱ № ～ － ∥ ￠ ￡ ￢ 髙 﨑 稄 𠮷 😀` を含む回帰テスト | 中 |
| 13 | 全文検索と文字コード: ngram パーサは utf8mb4 前提。`innodb_ft_min_token_size` は ngram には適用されず `ngram_token_size` で制御 | トークン化の差 | 再インデックス | 低 |

変換手順の推奨順序: 実データのバイト列調査（`SELECT HEX(c)` でサンプリング）→ 末尾空白・ゼロ日付の掃除 → `ROW_FORMAT=DYNAMIC` → VARBINARY 経由の実エンコード宣言 → `CONVERT TO utf8mb4 COLLATE <統一照合>` → UNIQUE 重複の解消 → PHP 側の接続 charset を `utf8mb4` へ。

## 14. PHP–MySQL 連携の非互換

PHP 5.3 の ext/mysql + libmysqlclient から PHP 8.5 の mysqlnd（mysqli / PDO）への移行で変わるのは、API 名だけではなく「接続が暗黙か明示か」「エラーが戻り値か例外か」「数値が文字列かネイティブか」「文字コードが設定ファイル由来かコード由来か」の 4 点。DB アクセスをラッパに集約してから置換するのが現実的。

### ext/mysql → mysqli / PDO 対応表

| mysql\_\*（5.3） | mysqli（手続き型） | PDO | 注意点 |
| --- | --- | --- | --- |
| `mysql_connect($h, $u, $p)` | `mysqli_connect($h, $u, $p, $db, $port, $sock)` | `new PDO("mysql:host=$h;dbname=$db;charset=utf8mb4", $u, $p, $opts)` | mysql\_connect は同一引数なら既存接続を再利用、mysqli は毎回新規（接続数が増える）。失敗時: mysqli は 8.1 以降例外、PDO は常に PDOException |
| `mysql_pconnect()` | `mysqli_connect('p:' . $h, ...)` | `PDO::ATTR_PERSISTENT => true` | 永続接続はセッション状態（`SET NAMES`、`sql_mode`、一時テーブル、トランザクション）が残留する |
| `mysql_select_db($db)` | `mysqli_select_db($link, $db)` | DSN の `dbname` / `USE` | 引数順が逆（link が先頭） |
| `mysql_query($sql [, $link])` | `mysqli_query($link, $sql)` | `$pdo->query()` / `prepare()` + `execute()` | 引数順が逆、link 必須（「最後に開いた接続」の暗黙使用がない）。8.0: 空クエリは ValueError |
| `mysql_unbuffered_query()` | `mysqli_query($link, $sql, MYSQLI_USE_RESULT)` | `PDO::MYSQL_ATTR_USE_BUFFERED_QUERY => false` | 非バッファ中は同一接続で他クエリ不可 |
| `mysql_fetch_array($r, MYSQL_ASSOC)` | `mysqli_fetch_array($r, MYSQLI_ASSOC)` | `fetch(PDO::FETCH_ASSOC)` | 定数名変更。8.0: `$r` が false だと TypeError |
| `mysql_fetch_assoc` / `_row` / `_object` | `mysqli_fetch_assoc` / `_row` / `_object` | `fetch(PDO::FETCH_ASSOC / NUM / OBJ)` | — |
| `mysql_result($r, $i, $col)` | なし → `mysqli_data_seek($r, $i)` + `mysqli_fetch_array()` | `fetchColumn()` | ヘルパ関数を用意 |
| `mysql_num_rows($r)` | `mysqli_num_rows($r)` | `rowCount()`（SELECT では MySQL は返すが移植性なし）/ `COUNT(*)` | 8.0+: PHP\_INT\_MAX 超は string |
| `mysql_affected_rows([$link])` | `mysqli_affected_rows($link)` | `rowCount()` | PDO は `PDO::MYSQL_ATTR_FOUND_ROWS` で「一致行数」に切替可（mysql\_\* 既定は「変更行数」） |
| `mysql_insert_id([$link])` | `mysqli_insert_id($link)` | `lastInsertId()`（string） | BIGINT UNSIGNED 上限超は string |
| `mysql_error()` / `mysql_errno()` | `mysqli_error($link)` / `mysqli_errno($link)`、接続失敗は `mysqli_connect_error()` / `mysqli_connect_errno()` | `errorInfo()[2]` / `[1]`、`PDOException::$errorInfo` | PDOException `getCode()` は SQLSTATE 文字列（`'23000'`）。重複キー 1062 の判定は `errorInfo[1]` |
| `mysql_real_escape_string($s [, $link])` / `mysql_escape_string($s)` | `mysqli_real_escape_string($link, $s)` | `quote()`（引用符込み） | 本来はプリペアドへ。`mysql_escape_string` は charset 非対応で 7.0 削除 |
| `mysql_set_charset($cs)` / `mysql_client_encoding()` | `mysqli_set_charset($link, $cs)` / `mysqli_character_set_name($link)` | DSN `charset=` | `SET NAMES` 直発行はエスケープに反映されない |
| `mysql_free_result()` / `mysql_close()` | `mysqli_free_result()` / `mysqli_close()` | `$stmt = null` / `$pdo = null` | — |
| `mysql_ping()` | `mysqli_ping()`（8.4 非推奨） | なし | `SELECT 1` を発行して例外を捕捉 |
| `mysql_list_tables()` / `_dbs()` / `_fields()`、`mysql_db_name()`、`mysql_tablename()` | `SHOW TABLES` / `SHOW DATABASES` / `mysqli_fetch_fields()` | `SHOW` 文 | — |
| `mysql_field_name()` / `_type()` / `_len()` / `_flags()` / `_table()` | `mysqli_fetch_field_direct($r, $i)` の `name` / `type` / `length` / `flags` / `table` | `getColumnMeta($i)` | `mysql_field_type()` は `"int"` / `"string"` / `"blob"` 等の文字列、mysqli は `MYSQLI_TYPE_*` の整数 → 対応表が必要 |
| `mysql_db_query($db, $sql)` | `mysqli_select_db()` + `mysqli_query()` | — | — |
| `mysql_create_db()` / `mysql_drop_db()` | `mysqli_query($link, 'CREATE DATABASE ...')` | `exec()` | — |
| `mysql_stat()` / `_thread_id()` / `_info()` / `_get_server_info()` / `_get_client_info()` | `mysqli_stat()` / `_thread_id()` / `_info()` / `_get_server_info()` / `_get_client_info()` | `getAttribute(PDO::ATTR_SERVER_INFO / ATTR_SERVER_VERSION)` | `mysqli_get_client_info($link)` の引数は 8.1 非推奨 |
| `mysql_fetch_lengths()` | `mysqli_fetch_lengths()` | なし | — |
| ini: `mysql.default_host` / `_user` / `_password` / `_port` / `_socket`、`mysql.connect_timeout`、`mysql.allow_persistent`、`mysql.max_links`、`mysql.trace_mode` | `mysqli.default_*`、`mysqli.allow_persistent`、`mysqli.max_links`、`mysqli.max_persistent`（`mysqli.reconnect` は 8.2 削除） | `pdo_mysql.default_socket` | タイムアウトは `mysqli_options(MYSQLI_OPT_CONNECT_TIMEOUT)` / `PDO::ATTR_TIMEOUT` |

`dshafik/php7-mysql-shim` のような mysqli 上の `mysql_*` 互換レイヤは移行期の暫定策としては使えるが、8.1 以降は `mysqli_report(MYSQLI_REPORT_OFF)` が必要で、保守も停滞している。最終的には撤去する。

### ドライバ・挙動の非互換

| # | 対象 | 影響 | 修正方針 | 重要度 |
| --- | --- | --- | --- | --- |
| 1 | 暗黙接続の廃止: `mysql_query($sql)` は「最後に開いた接続」や ini 既定で自動接続していた。mysqli / PDO は接続オブジェクト必須 | 全呼び出し箇所に接続を渡す大規模改修 | DB アクセス層（クラス / 関数群）に集約し、接続はシングルトンで保持 | 高 |
| 2 | ドライバが mysqlnd のみ（mysqli は 8.2 で libmysqlclient ビルド削除。pdo\_mysql も mysqlnd 推奨）。mysqlnd は my.cnf の `[client]` 節（`default-character-set`、`socket`）を読まない | 設定ファイル由来の文字コードが消えて文字化け、ソケットパス不一致で「No such file or directory」（既定 `pdo_mysql.default_socket=/tmp/mysql.sock` vs サーバ `/var/lib/mysql/mysql.sock`） | コードで charset 指定、php.ini で `mysqli.default_socket` / `pdo_mysql.default_socket` | 高 |
| 3 | 接続文字コードの既定はサーバの `character_set_server` に従う（mysqlnd）。MySQL 5.1 は latin1、8.0 は utf8mb4。旧 PHP（5.x 系）は照合 ID 255 を知らず接続不能 | サーバ更新で暗黙の接続文字コードが変わる（サイレントな文字化け） | 常に `mysqli_set_charset()` / DSN `charset=`。移行期はサーバ `collation_server=utf8mb4_general_ci` | 高 |
| 4 | 認証: `caching_sha2_password`（8.0 既定、8.4 で native 無効）。mysqlnd は PHP 7.4+ で安定対応（7.2.8 / 7.3 で初期対応）。非 TLS の TCP では RSA 公開鍵交換（PHP に openssl 拡張が必要、`MYSQLI_SERVER_PUBLIC_KEY` / `PDO::MYSQL_ATTR_SERVER_PUBLIC_KEY` で鍵ファイル指定可）、UNIX ソケットは平文で可 | PHP < 7.4 は「authentication method unknown to the client」、openssl なしでは「Authentication requires secure connection」 | PHP を先に 7.4+ へ。`sha256_password` は非推奨なので使わない | 高 |
| 5 | 数値の返却型: ext/mysql と mysqli（テキストプロトコル）は全て string。mysqli プリペアド（`mysqli_stmt`）は int / float をネイティブ返却。PDO は 8.1 以降ネイティブ返却（`ATTR_STRINGIFY_FETCHES=false` 既定）。`MYSQLI_OPT_INT_AND_FLOAT_NATIVE` で mysqli テキストもネイティブ化可 | `===` 比較、`json_encode()` の出力、`is_string()` 判定、PHP 8 の比較規則との組合せで分岐が変わる | 方針を 1 つに統一し、API 境界でキャストして型を固定 | 高 |
| 6 | エラーモード: PDO は 8.0 で既定 `ERRMODE_EXCEPTION`、mysqli は 8.1 で既定 `MYSQLI_REPORT_ERROR｜MYSQLI_REPORT_STRICT`（接続失敗も `mysqli_sql_exception`） | 戻り値 false を判定するコードが未捕捉例外で停止。「接続できなければメンテ画面を出す」等のフローが変わる | 全 DB 呼び出しを例外前提に。暫定: 旧モードを明示設定 | 高 |
| 7 | 失敗クエリの結果扱い: `mysqli_fetch_*(false)` が TypeError（8.0）、`mysqli_query($c, '')` が ValueError（8.0）、`mysqli_real_escape_string($c, null)` が Deprecated（8.1） | Fatal | クエリ結果の判定を徹底（例外モードなら自然に解消） | 高 |
| 8 | 自動再接続の消滅: `mysqli.reconnect` は libmysqlclient 専用で 8.2 削除、mysqlnd は元々非対応、`mysqli_ping()` は 8.4 非推奨 | `wait_timeout`（既定 8 時間）を超えるバッチが「MySQL server has gone away」(2006) / 「Lost connection」(2013) で停止 | 接続ラッパで 2006 / 2013 を捕捉して再接続、長い処理の前後で接続を張り直す | 中 |
| 9 | プリペアドの型: PDO は既定でエミュレート（`ATTR_EMULATE_PREPARES=true`）で全パラメータを文字列化（`LIMIT ?` は `PDO::PARAM_INT` 必須）。ネイティブにすると `max_prepared_stmt_count` と 1 文 1 ステートメント制限。mysqli\_stmt の `bind_param('i')` は 64bit | SQL エラー、型不一致 | `bindValue($k, $v, PDO::PARAM_INT)` を明示 | 中 |
| 10 | 複数ステートメント: `PDO::MYSQL_ATTR_MULTI_STATEMENTS` は既定 true（5.5.21+）、`mysqli_multi_query()` | インジェクション時の被害拡大 | false にする | 中 |
| 11 | TLS: `mysqli_ssl_set()` + `MYSQLI_CLIENT_SSL`、検証無効は `MYSQLI_CLIENT_SSL_DONT_VERIFY_SERVER_CERT`、PDO は `PDO::MYSQL_ATTR_SSL_CA` / `SSL_VERIFY_SERVER_CERT`（7.1.4+）。MySQL 8.0 が自動生成する自己署名証明書は検証に失敗。`require_secure_transport=ON` なら平文接続自体が拒否 | 接続失敗 | CA を配布して検証、または UNIX ソケット | 中 |
| 12 | 接続時のセッション設定: `PDO::MYSQL_ATTR_INIT_COMMAND` / `mysqli_options(MYSQLI_INIT_COMMAND)` で `SET sql_mode='...'`、`SET tx_isolation=...` を発行している場合 | `NO_AUTO_CREATE_USER` を含む sql\_mode や `tx_isolation` は 8.0 でエラーになり、接続自体が失敗 | 文字列を修正（`transaction_isolation`） | 高 |
| 13 | `LOAD DATA LOCAL INFILE`: サーバ `local_infile=OFF` 既定（8.0）、PHP 側は `MYSQLI_OPT_LOCAL_INFILE` / `PDO::MYSQL_ATTR_LOCAL_INFILE`、8.1+ の `PDO::MYSQL_ATTR_LOCAL_INFILE_DIRECTORY` | 1148「The used command is not allowed」 / 3948 | 双方で許可、ディレクトリ限定 | 中 |
| 14 | 大きなパケット: サーバ `max_allowed_packet`（8.0 既定 64M）と mysqlnd の `mysqlnd.net_cmd_buffer_size` / `mysqlnd.net_read_buffer_size` | BLOB 送受信で 2006 | 設定調整 | 低 |
| 15 | AUTO\_INCREMENT と複数行 INSERT: `innodb_autoinc_lock_mode=2`（8.0）で連番が保証されない | `mysqli_insert_id() + $i` で各行の ID を推定するコードが誤った ID を使う（サイレント） | 1 行ずつ INSERT、またはユニークキーで再 SELECT | 中 |
| 16 | mysqli の非推奨 API（8.1～8.5）: `mysqli::init()`、`$driver_version`、`mysqli_get_client_info($link)`、`mysqli_ping()` / `kill()` / `refresh()`、`store_result($mode)`、`MYSQLI_SET_CHARSET_DIR`、`MYSQLI_REFRESH_SLAVE`、`mysqli_execute()` 別名 | Deprecated | 置換 | 低 |
| 17 | PDO の非推奨（8.5）: `PDO::MYSQL_ATTR_*` → `Pdo\Mysql::ATTR_*`（8.4 で `Pdo\Mysql` と `PDO::connect()` 導入）、`uri:` DSN、`PDO::FETCH_SERIALIZE`（8.1） | Deprecated | 8.4 以上のみ対象なら定数置換（[pdo\_mysql](https://www.php.net/pdo_mysql)） | 低 |
| 18 | mysqlnd 専用だった API（`mysqli_stmt::get_result()`、`mysqli_result::fetch_all()`、非同期 `MYSQLI_ASYNC` / `mysqli_poll()`）が 8.2 以降常に利用可 | 旧環境（libmysqlclient ビルド）で避けていた API が使える | — | 低 |
| 19 | PHP 5.3 の libmysqlclient 5.1 は `utf8mb4` を知らない（`mysql_set_charset('utf8mb4')` が失敗、`SET NAMES utf8mb4` は通るがエスケープが追従しない） | PHP を上げる前に DB を utf8mb4 化するとエスケープ不整合 | 順序: PHP（mysqlnd）→ utf8mb4 化 | 中 |

## 15. 段階移行中のバージョン組合せ互換マトリクス

「◎」は制約なし、「△」は条件付きで接続可、「×」は実用不可。PHP 側は mysqlnd 前提（PHP 5.3 のみ libmysqlclient 5.1 ビルドも想定）。Oracle の公式サポート対象外の組合せを含むが、プロトコル上は接続できる。

| PHP ↓ / MySQL → | 5.1 | 5.5 / 5.6 | 5.7 | 8.0 | 8.4 |
| --- | --- | --- | --- | --- | --- |
| 5.3（libmysqlclient 5.1） | ◎ | △ utf8mb4 不可（`mysql_set_charset('utf8mb4')` 失敗） | △ utf8mb4 不可 | × 照合 255 エラー、caching\_sha2 非対応（`collation_server` 変更 + native ユーザで辛うじて可） | × |
| 5.3～5.6（mysqlnd） | ◎ | ◎ | ◎ | △ `collation_server` を general\_ci 等に変更、`mysql_native_password` ユーザ限定 | × native が既定無効（`mysql_native_password=ON` で暫定可） |
| 7.0～7.3 | ◎ | ◎ | ◎ | △ `mysql_native_password` ユーザ限定（7.2.8 / 7.3 は caching\_sha2 初期対応ありだが非推奨）。7.0 は照合 255 要注意 | △ 同左 + `mysql_native_password=ON` |
| 7.4 | ◎（utf8mb4 はサーバ非対応） | ◎ | ◎ | ◎ | ◎ |
| 8.0～8.3 | ◎（utf8mb4 はサーバ非対応、mysqli は 8.1 から例外既定） | ◎ | ◎ | ◎ | ◎ |
| 8.4 / 8.5 | ◎（同上） | ◎ | ◎ | ◎ | ◎ |

補足:

- TLS 接続を使う場合、MySQL 8.0.28+ / 8.4 は TLSv1.2 以上のみ。PHP 5.3 時代の OpenSSL 0.9.8 / 1.0.0 は TLSv1.2 非対応なので、旧 PHP からは平文（または UNIX ソケット）に限られる。
- PHP 8.x から MySQL 5.1 へは接続できるが、`SET NAMES utf8mb4` が失敗するので接続 charset は `utf8` のまま。utf8mb4 への切替は DB 側が 5.5 以上になってから。
- 8.0 列の「△」は、サーバ側で `collation_server=utf8mb4_general_ci`（または `utf8`）と `default_authentication_plugin=mysql_native_password`（8.0 のみ。`authentication_policy` は 8.0.27+）を設定すれば接続できるという意味。この設定で運用を続けると 8.4 への移行時に同じ問題が再発するので、PHP 7.4 以上を先にする。
- 推奨する中間状態は「PHP 7.4 × MySQL 5.7」と「PHP 7.4 × MySQL 8.4」。どちらも制約なしで、PHP 8 固有の変更と DB 固有の変更を切り分けて検証できる。

## 16. 事前チェックリストと機械的検出

静的解析で拾えるものは全てツールに任せ、grep はツールが見落とす文字列・設定・SQL に使う。サイレントな変更（比較、優先順位、GROUP BY 順序、照合）はこれらでは検出できないので、旧新環境での結果比較テストが必須。

### PHP コード

| 検出対象 | コマンド / パターン |
| --- | --- |
| 全体の非互換（最優先） | `phpcs -p --standard=PHPCompatibility --runtime-set testVersion 8.5- --extensions=php,inc src/` |
| 自動修正 | Rector: `LevelSetList::UP_TO_PHP_85` + `SetList::DEAD_CODE`を `--dry-run` で確認してから適用 |
| 構文エラー | `find . -name '*.php' -print0 \| xargs -0 -n1 -P8 php -l \| grep -v 'No syntax errors'`（対象バージョンの php で実行） |
| ext/mysql | `grep -rEn '\bmysql_[a-z_]+\s*\(' --include='*.php' --include='*.inc'` |
| ereg / split | `grep -rEn '\b(ereg\|eregi\|ereg_replace\|eregi_replace\|split\|spliti\|sql_regcase)\s*\('` |
| `/e` 修飾子 | `grep -rEn "preg_replace\s*\(\s*['\"][^'\"]*['\"]?[a-zA-Z]*e[a-zA-Z]*['\"]"`（誤検出あり、目視確認） |
| 旧スーパーグローバル | `grep -rEn '\$HTTP_(GET\|POST\|COOKIE\|SERVER\|ENV\|SESSION\|POST_FILES)_VARS\|\$HTTP_RAW_POST_DATA'` |
| magic quotes / register\_globals | `grep -rEn 'magic_quotes\|register_globals\|session_register\|session_is_registered\|import_request_variables'` |
| mcrypt | `grep -rEn '\bmcrypt_\|MCRYPT_'` |
| 8.0 削除関数 | `grep -rEn '\b(each\|create_function\|__autoload\|money_format\|is_real\|hebrevc\|convert_cyr_string\|ezmlm_hash\|restore_include_path\|fgetss\|read_exif_data\|ldap_sort\|gmp_random)\s*\(\|\$php_errormsg\|\(real\)\|\(unset\)'` |
| 波括弧オフセット | `grep -rEn '\$[A-Za-z_][A-Za-z0-9_]*(\[[^]]*\])*\{[^}]+\}'`（ヒアドキュメント内の `{$var}` と区別が必要） |
| ネスト三項・連結優先順位 | PHPCompatibility / Rector に任せる（grep は困難） |
| 非標準キャスト（8.5） | `grep -rEn '\((integer\|boolean\|double\|binary)\)'` |
| バッククォート（8.5） | ``grep -rEn '`[^`]+`'`` を文字列リテラル外に限定して目視 |
| `__sleep` / `__wakeup`（8.5） | `grep -rEn 'function\s+__(sleep\|wakeup)\b'` |
| 暗黙 nullable（8.4） | `grep -rEn 'function\s+\w+\s*\([^)]*[A-Za-z_\\]+\s+\$\w+\s*=\s*null'` |
| `${var}` 補間（8.2） | `grep -rEn '"[^"]*\$\{[A-Za-z_]'` |
| 8.1～8.2 非推奨 | `grep -rEn 'utf8_encode\|utf8_decode\|strftime\s*\(\|FILTER_SANITIZE_STRING\|HTML-ENTITIES\|date_sunrise\|date_sunset\|mhash'` |
| 短縮タグ | `grep -rEn '<\?(?!php\|=\|xml)' -P` |
| `is_resource` | `grep -rEn 'is_resource\s*\('`（curl / GD / xml / ftp / ldap を確認） |
| `@` 前提のエラーハンドラ | `grep -rEn 'error_reporting\s*\(\s*\)\s*===?\s*0'` |
| mysqli / PDO 非推奨 | `grep -rEn 'mysqli_ping\|mysqli_kill\|mysqli_refresh\|mysqli_execute\s*\(\|->ping\(\|PDO::MYSQL_ATTR_\|mysqli\.reconnect'` |
| `E_STRICT` / `E_USER_ERROR` | `grep -rEn 'E_STRICT\|trigger_error\([^,]+,\s*E_USER_ERROR'` |
| 旧形式セッションハンドラ | `grep -rEn 'session_set_save_handler\s*\(\s*[^$\[n]'` |
| ポリフィル衝突 | `grep -rEn 'function\s+(str_contains\|str_starts_with\|str_ends_with\|array_is_list\|array_find\|array_any\|array_all\|array_first\|array_last\|json_validate\|mb_trim\|mb_str_pad)\s*\('` |
| SQL 側の危険パターン（PHP 内の SQL 文字列） | `grep -rEin 'SQL_CALC_FOUND_ROWS\|FOUND_ROWS\|GROUP BY[^;]*(ASC\|DESC)\b\|VALUES\s*\(\s*[a-z_]+\s*\)\|SQL_CACHE\|tx_isolation\|NO_AUTO_CREATE_USER\|ENCODE\s*\(\|DECODE\s*\(\|PASSWORD\s*\(\|0000-00-00\|GeomFromText\|AsText\s*\('` |
| 実行時の非推奨収集 | `php -d error_reporting=E_ALL -d display_errors=0 -d log_errors=1 -d error_log=/tmp/php-deprecated.log` でテストを回し、`sort \| uniq -c \| sort -rn` |

### my.cnf

`mysqld --validate-config`（8.0.16+）を移行先バージョンのバイナリで実行するのが確実。事前の grep:

```
grep -En '^(query_cache|innodb_file_format|innodb_large_prefix|innodb_support_xa|innodb_checksums|innodb_locks_unsafe|tx_isolation|log_warnings|default_authentication_plugin|expire_logs_days|master_info_repository|relay_log_info_repository|binlog_transaction_dependency|skip-character-set-client-handshake|character-set-client-handshake|default-character-set|old_passwords|secure_auth|skip-locking|table_cache|log_slow_queries|log\s*=|innodb_additional_mem_pool|thread_concurrency|innodb_file_io_threads|master-|slave-|skip-host-cache|show_compatibility_56|sql_mode.*NO_AUTO_CREATE_USER|avoid_temporal_upgrade|storage_engine\s*=|language\s*=)' /etc/my.cnf /etc/my.cnf.d/*.cnf /etc/mysql/*.cnf /etc/mysql/conf.d/*.cnf
```

### DB の事前調査 SQL（旧サーバ上で実行）

| 目的 | SQL |
| --- | --- |
| 認証プラグイン・旧ハッシュ | 5.7+: `SELECT user, host, plugin FROM mysql.user;` / 5.6 以前: `SELECT user, host, LENGTH(password) FROM mysql.user;`（16 = 旧ハッシュ） |
| エンジン・照合・行フォーマット | `SELECT TABLE_SCHEMA, TABLE_NAME, ENGINE, TABLE_COLLATION, ROW_FORMAT FROM information_schema.TABLES WHERE TABLE_SCHEMA NOT IN ('mysql','information_schema','performance_schema','sys');` |
| 列単位の文字セット | `SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, CHARACTER_SET_NAME, COLLATION_NAME FROM information_schema.COLUMNS WHERE CHARACTER_SET_NAME IS NOT NULL AND CHARACTER_SET_NAME <> 'utf8mb4';` |
| ゼロ日付既定値 | `SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, COLUMN_DEFAULT FROM information_schema.COLUMNS WHERE COLUMN_DEFAULT LIKE '0000-00-00%';` |
| TIMESTAMP 列（暗黙既定の影響先） | `SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, IS_NULLABLE, COLUMN_DEFAULT, EXTRA FROM information_schema.COLUMNS WHERE DATA_TYPE = 'timestamp';` |
| 旧時刻フォーマット | `mysqlcheck --check-upgrade --all-databases`（「needs upgrade」を検出）→ `ALTER TABLE ... FORCE` |
| 予約語になる列名 | `SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS WHERE UPPER(COLUMN_NAME) IN ('RANK','ROW_NUMBER','GROUPS','SYSTEM','LEAD','LAG','OVER','WINDOW','FUNCTION','OF','ROW','ROWS','CUBE','EMPTY','FIRST_VALUE','LAST_VALUE','NTILE','PERCENT_RANK','CUME_DIST','DENSE_RANK','JSON_TABLE','LATERAL','RECURSIVE','GROUPING','EXCEPT','INTERSECT','ARRAY','MEMBER','GENERATED','STORED','VIRTUAL','PARTITION','SIGNAL','RESIGNAL','MAXVALUE','GET','SLOW','GENERAL');` |
| ルーチン・ビュー・トリガ・イベント | `SELECT ROUTINE_SCHEMA, ROUTINE_NAME, DEFINER FROM information_schema.ROUTINES;` / `SELECT TABLE_SCHEMA, TABLE_NAME, DEFINER FROM information_schema.VIEWS;` / `SHOW TRIGGERS;` / `SHOW EVENTS;`（8.0 で `event_scheduler=ON` になる） |
| 末尾空白を含む値（NO PAD 対策） | 対象列ごとに `SELECT COUNT(*) FROM t WHERE c <> TRIM(TRAILING ' ' FROM c);` |
| 4 バイト文字の有無（utf8mb3 列では入っていないはずだがバイナリ列・latin1 誤宣言列ではありうる） | `SELECT COUNT(*) FROM t WHERE HEX(c) REGEXP '^(..)*F[0-4]';` |
| MyISAM パーティション | `SELECT DISTINCT TABLE_SCHEMA, TABLE_NAME FROM information_schema.PARTITIONS p JOIN information_schema.TABLES t USING (TABLE_SCHEMA, TABLE_NAME) WHERE p.PARTITION_NAME IS NOT NULL AND t.ENGINE <> 'InnoDB';` |
| アプリ発行 SQL の採取 | `SET GLOBAL general_log = ON;`（1 営業日）→ 新 DB で再生し `SHOW WARNINGS` と結果を比較（`pt-upgrade`） |
| アップグレードチェッカー | `mysqlsh -- util check-for-server-upgrade root@host --target-version=8.0.40 --config-path=/etc/my.cnf`（5.7 → 8.0）、`--target-version=8.4.0`（8.0 → 8.4） |

### テストデータに必ず含めるもの

- 機種依存文字: `① ② ㈱ № ℡ ～ － ∥ ￠ ￡ ￢ 髙 﨑 稄 德`、4 バイト: `𠮷 𩼸 😀`、半角カナ、全角空白、`\`（円記号 / バックスラッシュ）。
- 濁点・半濁点・かなの組（は / ば / ぱ / ハ / バ / パ）を持つ行での等価検索と UNIQUE。
- 末尾空白あり / なしのコード値。
- ゼロ日付、`NULL` 日付、2038-01-19 以降の TIMESTAMP（TIMESTAMP 型の上限は 8.4 でも変わらない。長期運用なら DATETIME へ）。
- 数値列の `0`、`''`、`NULL`、`'0.0'`、`'1e3'`、`'123abc'`。
- 金額の丸め境界（`round(0.285, 2)` 等）。

## 17. 参考資料

本文書で直接参照したページ:

- [PHP 8.5 非推奨機能一覧（php.net）](https://www.php.net/manual/de/migration85.deprecated.php)
- [PHP 8.5 下位互換性のない変更（php.net）](https://php.net/migration85.incompatible.php)
- [PHP RFC: Deprecations for PHP 8.5](https://wiki.php.net/rfc/deprecations_php_8_5)
- [PHP 8.5 リリースページ](https://www.php.net/releases/8.5/en.php)
- [PHP 8.4 下位互換性のない変更](https://www.php.net/manual/zh/migration84.incompatible.php)
- [PHP 8.2 下位互換性のない変更（日本語）](https://php.he.net/manual/ja/migration82.incompatible.php)
- [PHP 7.4 下位互換性のない変更](https://php.net/migration74.incompatible)
- [mysqli 変更履歴（php.net）](https://www.php.net/manual/en/changelog.mysqli.php)
- [PDO\_MYSQL（php.net）](https://www.php.net/pdo_mysql)
- [PHP RFC: Remove support for libmysql from mysqli](https://wiki.php.net/rfc/mysqli_support_for_libmysql)
- [MySQL 文字セットの考え方（php.net 日本語）](https://php.net/manual/ja/mysqlinfo.concepts.charset.php)
- [mysqli::set\_charset（php.net）](https://www.php.net/manual/en/mysqli.set-charset.php)
- [Red Hat Bugzilla 1646158: Server sent charset (255) unknown to the client](https://bugzilla.redhat.com/show_bug.cgi?id=1646158)
- [MySQL 8.4.0 リリースノート](https://dev.mysql.com/doc/relnotes/mysql/8.4/en/news-8-4-0.html)
- [MySQL 8.3.0 リリースノート（削除オプション）](https://dev.mysql.com/doc/relnotes/mysql/8.4/en/news-8-3-0.html)
- [MySQL 8.2.0 リリースノート（--character-set-client-handshake 非推奨）](https://dev.mysql.com/doc/relnotes/mysql/8.4/en/news-8-2-0.html)
- [What Is New in MySQL 8.4 since MySQL 8.0](https://docs.oracle.com/cd/E17952_01/mysql-8.4-en/mysql-nutshell.html)
- [What Is New in MySQL（最新）](https://dev.mysql.com/doc/en/mysql-nutshell.html)
- [MySQL 8.4 Upgrade Paths](https://dev.mysql.com/doc/refman/8.4/en/upgrade-paths.html)
- [Percona: MySQL 8.0 Deprecated Features](https://www.percona.com/blog/mysql-8-0-deprecated-features-what-you-need-to-know/)

各 PHP バージョンの移行ガイドは `https://www.php.net/manual/ja/migrationNN.php`（NN = 54 / 55 / 56 / 70 / 71 / 72 / 73 / 74 / 80 / 81 / 82 / 83 / 84 / 85）にあり、本文書の各節はその「下位互換性のない変更」「非推奨」の章と対応する。MySQL は各バージョンのリファレンスマニュアル「What Is New」と「Upgrading MySQL」の章、および「Server and Status Variables and Options Added, Deprecated, or Removed」が一次資料。
