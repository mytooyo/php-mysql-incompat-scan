# ルール一覧

`python incompat_scan.py --export-rules-md docs/RULES.md` で生成。手で編集しないこと。

- 適用種別: P=PHPソース / S=SQL・スクリプト・汎用設定 / I=php.ini系 / C=my.cnf系 / D=設計書
- 確度: 確定 / 要確認 / 監査（`--audit` 指定時のみ有効）

## パターンルール（205）

| ID | 導入Ver | 重要度 | 確度 | 種別 | 対象 | 影響 | 修正方針 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PHP54-01 | PHP5.4 | 高 | 確定 | PD | $HTTP_*_VARS（register_long_arrays） | 未定義変数(null)になり分岐が無警告で変わる | $_GET/$_POST/$_SESSION 等へ置換 |
| PHP54-02 | PHP5.4 | 高 | 確定 | PD | magic_quotes 関連関数 | 5.4で機能削除・7.0/8.0で関数削除(Fatal)。magic quotes前提のSQLはインジェクション可能になる | 分岐ごと削除し、SQLはプリペアドステートメントへ |
| PHP54-03 | PHP5.4 | 高 | 要確認 | P | 呼び出し時参照渡し foo(&$a) の可能性 | Fatal error（コンパイル時） | 関数定義側を function foo(&$a) にし、呼び出し側の & を削除 |
| PHP54-04 | PHP5.4/8.1 | 高 | 要確認 | PD | htmlspecialchars 系（charset/flags 既定値） | 既定charsetがUTF-8(5.4)。SJIS/EUC-JP文字列は空文字になる。既定flagsがENT_QUOTES\|ENT_SUBSTITUTE(8.1)で ' もエスケープ | 第2・第3引数(flags, encoding)の明示有無を確認。内部エンコードに合わせて明示 |
| PHP54-05 | PHP5.4 | 中 | 確定 | P | break 0 / break $n / continue $n | Fatal error | 定数リテラルに書き換え |
| PHP54-06 | PHP5.4 | 中 | 確定 | PD | session_register 系 | Fatal error（未定義関数） | $_SESSION を直接操作 |
| PHP54-07 | PHP5.4 | 中 | 確定 | PD | mysqli 旧別名・レプリケーション関数 | Fatal error | mysqli_stmt_* 正式名へ。rpl系は削除 |
| PHP54-08 | PHP5.4 | 中 | 確定 | PD | import_request_variables 等 | Fatal error | $_REQUEST 等を明示的に参照 |
| PHP54-13 | PHP5.4 | 低 | 確定 | P | スーパーグローバル名の引数 | Fatal error | 引数名を変更 |
| PHP55-01 | PHP5.5/7.0 | 高 | 確定 | PD | ext/mysql (mysql_*) | 7.0で削除。Fatal error: Call to undefined function | mysqli / PDO へ置換（ガイド14節の対応表）。引数順・暗黙接続・エラー処理が変わる |
| PHP55-02 | PHP5.5/7.0 | 高 | 確定 | P | preg_replace の /e 修飾子 | 7.0以降 Warning + null を返し置換結果が消える（サイレント） | preg_replace_callback へ |
| PHP55-02b | PHP5.5/7.0 | 高 | 要確認 | P | /e 修飾子付き正規表現リテラルの可能性（配列・変数経由） | 同上 | preg_replace で使われているか確認 |
| PHP55-03 | PHP5.5/7.2 | 高 | 確定 | PD | ext/mcrypt | 7.2で削除(Fatal)。既存暗号文の復号互換に注意（ゼロパディング、RIJNDAEL_256はOpenSSLに無い） | openssl_encrypt/decrypt へ。RIJNDAEL_256/Blowfish/DES は復号→AESで再暗号化 |
| PHP55-04 | PHP5.5 | 中 | 確定 | PD | APC ユーザキャッシュ API (apc_*) | Fatal error | APCu の apcu_* へ |
| PHP55-05 | PHP5.5 | 低 | 確定 | P | ロゴGUID関数 | Fatal error | 削除 |
| PHP56-01 | PHP5.6/7.0 | 高 | 確定 | PD | $HTTP_RAW_POST_DATA | 7.0で削除。入力が取得できない | file_get_contents('php://input') |
| PHP56-02 | PHP5.6/7.0 | 中 | 要確認 | P | cURL の '@ファイル' アップロード | ファイルでなく文字列が送信される（サイレント） | CURLFile へ |
| PHP56-03 | PHP5.6 | 中 | 要確認 | PD | mbstring/iconv のエンコーディング設定箇所 | default_charset(UTF-8既定)との整合。ini側 mbstring.* は非推奨 | 内部エンコード方針（UTF-8統一）に合わせて設定値を確認 |
| PHP56-05 | PHP5.6/8.0 | 中 | 確定 | P | crypt() の salt 省略 | 8.0で ArgumentCountError | password_hash() へ、または salt を明示 |
| PHP56-06 | PHP5.6 | 中 | 要確認 | P | SSL/TLS ストリーム接続 | ピア証明書検証が既定有効。自己署名・古いCAで接続失敗 | 接続先の証明書を確認。CAを配置 |
| PHP70-01 | PHP7.0 | 高 | 確定 | PD | ext/ereg (ereg/split 系) | Fatal error（未定義関数） | preg_match / preg_replace / preg_split / explode へ（デリミタ・エスケープ差に注意） |
| PHP70-02 | PHP7.0 | 中 | 確定 | P | ASPタグ <% / <script language="php"> | PHPとして解釈されずソースがそのまま出力される | <?php へ |
| PHP70-03 | PHP7.0 | 中 | 確定 | PD | 7.0 削除関数 | Fatal error | call_user_func / stream_set_blocking 等へ |
| PHP70-04 | PHP7.0 | 低 | 確定 | P | $a = &new Foo | Parse error | & を削除 |
| PHP70-05 | PHP7.0 | 高 | 要確認 | P | 可変変数/可変プロパティ + 添字（統一変数構文） | 評価順が左→右に変わり別の変数・プロパティを参照する（サイレント） | 旧の意味を保つには ${$a['b']} / $obj->{$a['b']} と {} で明示 |
| PHP70-06 | PHP7.0 | 中 | 要確認 | P | catch (Exception) / 例外ハンドラ | 旧Fatalの多くが Error 例外になり Exception では捕捉されない | 最上位の捕捉は Throwable に。ハンドラの型宣言も Throwable |
| PHP70-08 | PHP7.0+ | 高 | 確定 | P | 予約語と同名のクラス/インターフェイス | Fatal error | リネーム |
| PHP70-08b | PHP7.0+ | 高 | 確定 | P | 組込みクラスと同名のクラス定義 | Fatal error: Cannot declare class（名前空間なしの場合） | リネームまたは名前空間化 |
| PHP70-10 | PHP7.0 | 中 | 要確認 | P | 16進表記の文字列 "0x1A" | 数値文字列として扱われなくなる（is_numeric false、比較・計算結果が変わる） | hexdec() を明示 |
| PHP70-11 | PHP7.0 | 低 | 確定 | P | 二重引用符内の \u{ | Unicodeエスケープとして解釈され Parse error | \\u{ または単一引用符へ |
| PHP70-13 | PHP7.0/8.0 | 低 | 確定 | P | setlocale のカテゴリ文字列指定 | 8.0で削除(TypeError) | LC_ALL 等の定数へ |
| PHP70-14 | PHP7.0 | 低 | 確定 | P | global $$var | 可変変数の解釈変更 | global ${$foo->bar} と明示 |
| PHP70-19 | PHP7.0 | 低 | 確定 | P | password_hash の salt オプション | 非推奨→8.0で無視 | salt 指定を削除 |
| PHP71-01 | PHP7.1 | 中 | 要確認 | P | シード固定の乱数 (srand/mt_srand) | 同一シードの乱数列が変わる（抽選再現・テスト） | 再現が必要な結果はDB保存。暫定 MT_RAND_PHP（8.3非推奨） |
| PHP71-02 | PHP7.2/8.0 | 中 | 確定 | P | (unset) キャスト | 8.0で削除 | null 代入へ |
| PHP71-03 | PHP7.1/8.0 | 中 | 確定 | P | mb_ereg_replace の 'e' オプション | 8.0で削除 | mb_ereg_replace_callback へ |
| PHP71-05 | PHP7.1/8.0 | 中 | 確定 | PD | 7.x非推奨→8.0削除関数 | Fatal error | 代替実装へ |
| PHP72-01 | PHP7.2/8.0 | 高 | 監査 | P | count()/sizeof() | null/false/文字列を渡すと 8.0 で TypeError（クエリ失敗時の false 等） | 引数が必ず配列/Countableか確認。is_countable()、(array)キャスト |
| PHP72-02 | PHP7.2/8.0 | 高 | 確定 | PD | __autoload() | 8.0で削除。クラスが読み込まれず Fatal | spl_autoload_register() へ |
| PHP72-03 | PHP7.2/8.0 | 高 | 確定 | PD | create_function() | 8.0で削除(Fatal) | クロージャへ |
| PHP72-04 | PHP7.2/8.0 | 高 | 確定 | P | each() | 8.0で削除(Fatal) | foreach へ |
| PHP72-05 | PHP7.2/8.0 | 中 | 確定 | PD | $php_errormsg | 8.0で削除（未定義変数） | error_get_last() |
| PHP72-06 | PHP7.2/8.0 | 中 | 確定 | P | parse_str() の第2引数省略 | 8.0で ArgumentCountError | parse_str($s, $out) |
| PHP72-07 | PHP7.2/8.0 | 中 | 確定 | P | assert() の文字列引数 | 8.0で評価されなくなる | 式で記述 |
| PHP72-08 | PHP7.2/8.0 | 中 | 確定 | PD | 7.2非推奨→8.0削除関数 | Fatal error | gmp_random_bits / exif_read_data |
| PHP72-12 | PHP7.2 | 低 | 確定 | P | HMAC に非暗号学的ハッシュ | Warning + false | sha256 等へ |
| PHP73-01 | PHP7.3 | 高 | 要確認 | P | PCRE2: 文字クラス内の \w- 等のハイフン | 正規表現がコンパイルエラーになり preg_* が false（バリデーションが常に失敗/通過） | ハイフンを末尾へ移動またはエスケープ |
| PHP73-01b | PHP7.3 | 中 | 監査 | P | preg_* 全般（PCRE2 移行） | 不正エスケープ等の厳格化で既存パターンがエラーになりうる | 全パターンを新環境でコンパイルテスト |
| PHP73-04 | PHP7.3/8.0 | 中 | 確定 | P | 大文字小文字非依存の定数 define(..., true) | 8.0で第3引数無視（別表記での参照が未定義定数 Error） | 参照側の表記を統一 |
| PHP73-05 | PHP7.3/8.0 | 中 | 確定 | PD | 7.3非推奨→8.0削除（fgetss, mbereg別名 等） | Fatal error | mb_ereg* 正式名、strip_tags(fgets()) |
| PHP74-01 | PHP7.4/8.0 | 高 | 要確認 | P | 波括弧オフセット $str{0} | 8.0で Parse error（ファイル全体がコンパイル不能） | [ ] へ置換（文字列内の "{$a}" 補間は対象外） |
| PHP74-02 | PHP7.4/8.0 | 高 | 要確認 | P | 括弧なしのネスト三項演算子 | 8.0で Fatal（コンパイルエラー） | 括弧で結合を明示 |
| PHP74-03 | PHP7.4/8.0 | 高 | 要確認 | P | "." と "+"/"-" の混在 | 8.0で優先順位が変わり結果が変わる（サイレント） | 括弧で明示 |
| PHP74-04 | PHP7.4/8.0 | 中 | 確定 | P | implode() の引数逆順 | 8.0で TypeError | (glue, array) の順へ |
| PHP74-05 | PHP7.4/8.0 | 中 | 確定 | P | (real) / is_real() | 8.0で削除 | (float) / is_float() |
| PHP74-06 | PHP7.4/8.0 | 中 | 確定 | PD | money_format 等 | 8.0で削除(Fatal) | NumberFormatter / number_format 等 |
| PHP74-09 | PHP7.4 | 中 | 要確認 | PD | PEAR ライブラリ / 削除拡張 (wddx, recode, interbase) | PEARは既定で同梱されない。PEAR::DB/MDB2 は PHP 8 非対応 | Composer パッケージ / PDO へ移行 |
| PHP80-01 | PHP8.0 | 高 | 監査 | P | 数値/空文字との緩い比較 (==, !=) | 0 == "abc" が false になる等、数値と非数値文字列の比較結果が変わる（サイレント） | 比較対象の型を確認し === / 明示キャストへ |
| PHP80-02 | PHP8.0 | 高 | 監査 | P | in_array/array_search（strictなし） | 緩い比較の規則変更の影響を受ける | 第3引数 true を指定 |
| PHP80-03 | PHP8.0 | 中 | 監査 | P | switch 文 | case は緩い比較。数値と文字列 case の混在で分岐が変わる | 対象と case の型を揃える |
| PHP80-04 | PHP8.0+ | 高 | 要確認 | P | is_resource() 判定 | curl/GD/xml/socket/openssl 等がオブジェクト化され常に false（サイレント） | !== false / instanceof 判定へ |
| PHP80-05 | PHP8.0 | 中 | 確定 | P | @ 抑止判定 (error_reporting() == 0) | @ 中の error_reporting() が 0 でなく 4437 を返し、抑止していた警告で例外等が発生 | if (!(error_reporting() & $errno)) return false; |
| PHP80-06 | PHP8.0 | 中 | 確定 | P | #[ で始まるコメント | 属性構文として解釈され Parse error | // コメントへ |
| PHP80-07 | PHP8.0+ | 中 | 要確認 | P | 後発の組込み関数と同名のユーザ定義関数 | Fatal error: Cannot redeclare（function_exists ガードが無い場合） | function_exists() ガードの有無を確認、または削除 |
| PHP80-08 | PHP8.0 | 中 | 確定 | P | 引数なしの mktime() | ArgumentCountError | time() |
| PHP80-09 | PHP8.0 | 中 | 確定 | PD | xmlrpc 拡張削除 / 手続き型ZIP API 非推奨 | xmlrpc_* は Fatal（PECLへ移動） | 代替ライブラリ / ZipArchive |
| PHP80-10 | PHP8.0 | 中 | 確定 | P | 削除された filter 定数 | Error（未定義定数） | FILTER_SANITIZE_ADD_SLASHES 等 |
| PHP80-14 | PHP8.0 | 高 | 要確認 | PD | PDO 接続・エラーモード | 既定が ERRMODE_EXCEPTION。戻り値false判定のコードが PDOException で停止。8.1 で数値がネイティブ型で返る | 例外前提に書き換え。型は ATTR_STRINGIFY_FETCHES で互換維持可 |
| PHP80-14b | PHP8.0 | 中 | 要確認 | P | PDO errorInfo()/errorCode() による判定 | 例外が先に飛ぶため到達しない | try/catch へ |
| PHP80-15 | PHP8.0 | 中 | 監査 | P | usort 系コールバック | bool を返すコールバックは非推奨。安定ソート化で同値要素の順序が変わる | <=> で -1/0/1 を返す |
| PHP80-16 | PHP8.0 | 中 | 監査 | P | @ エラー抑止演算子 | Fatal系は抑止されなくなる。抑止に依存した処理の確認 | 事前チェックへ置換 |
| PHP80-20 | PHP8.0 | 高 | 監査 | P | mysqli 結果取得（false 渡し） | 失敗したクエリの false を渡すと TypeError | クエリ結果の判定/例外モード前提へ |
| PHP81-01 | PHP8.1 | 高 | 要確認 | P | 組込み関数へスーパーグローバルを直接渡している | 未定義キー→null→「null を渡すのは非推奨」(9.0で TypeError)。Warning も発生 | ?? '' で既定値を与える |
| PHP81-02 | PHP8.1 | 高 | 要確認 | PD | mysqli 接続・レポートモード | 既定が例外モード(MYSQLI_REPORT_ERROR\|STRICT)。接続失敗・SQLエラーが mysqli_sql_exception | 例外前提へ。暫定 mysqli_report(MYSQLI_REPORT_OFF) |
| PHP81-02b | PHP8.1 | 中 | 要確認 | P | mysqli のエラー戻り値判定 | 例外が先に飛ぶため到達しない。エラー時フロー（メンテ画面等）が変わる | try/catch へ |
| PHP81-03 | PHP8.1 | 中 | 要確認 | P | 数字文字列との厳密比較 (=== "1") | PDO がネイティブ型(int)を返すと不一致になる | 型方針を統一（STRINGIFY_FETCHES または int 比較） |
| PHP81-04 | PHP8.1 | 中 | 要確認 | P | 組込みインターフェイスの実装 | 戻り値型未宣言で Deprecated。Serializable 単独実装も非推奨 | 戻り値型を付与（旧PHP併用時は #[\ReturnTypeWillChange]） |
| PHP81-06 | PHP8.1 | 中 | 確定 | PD | 8.1 非推奨（strftime, FILTER_SANITIZE_STRING 等） | Deprecated（9.0で削除） | date()/IntlDateFormatter、htmlspecialchars() 等 |
| PHP81-07 | PHP8.1 | 低 | 確定 | P | $GLOBALS 全体の書き換え/参照 | コンパイルエラー | 個別キー操作へ |
| PHP81-09 | PHP8.1 | 低 | 確定 | P | mysqli 8.1 非推奨API | Deprecated | 置換 |
| PHP81-12 | PHP8.1+ | 中 | 要確認 | PD | 文字コード自動判定 | 判定アルゴリズム変更で検出結果が旧版と変わる | 入力エンコードを明示し自動判定をやめる |
| PHP81-12b | PHP8.1+ | 中 | 要確認 | P | エンコード名 'SJIS'/'EUC-JP' 指定 | 機種依存文字(①㈱髙 等)は SJIS-win/eucJP-win でないと化ける。変換テーブル修正で結果が変わる場合あり | Windows由来データは SJIS-win(CP932)/eucJP-win を指定し回帰テスト |
| PHP81-13 | PHP8.1 | 中 | 確定 | P | OpenSSL レガシー暗号 (BF/DES/RC4) | OpenSSL 3 環境で false（Unknown cipher） | AES で再暗号化。暫定 legacy provider |
| PHP82-02 | PHP8.2 | 中 | 確定 | P | "${var}" 形式の文字列補間 | Deprecated | "{$var}" へ |
| PHP82-03 | PHP8.2/8.4 | 中 | 確定 | PD | mysqli 自動再接続 / ping | mysqli.reconnect 削除(8.2)、mysqli_ping 非推奨(8.4)。長時間バッチが 2006 gone away で停止 | 接続ラッパで 2006/2013 を捕捉して再接続 |
| PHP82-04 | PHP8.2 | 中 | 確定 | P | mbstring の 'HTML-ENTITIES'/'BASE64' 等 | Deprecated | htmlentities / mb_encode_numericentity / base64_encode |
| PHP82-05 | PHP8.2 | 低 | 確定 | PD | utf8_encode/utf8_decode | Deprecated | mb_convert_encoding |
| PHP82-06 | PHP8.2 | 低 | 確定 | P | "self::m" 形式の callable | Deprecated | 第一級callable / 配列形式 |
| PHP82-07 | PHP8.2 | 低 | 要確認 | P | setlocale() | strtolower 等がロケール非依存化。strftime 非推奨とも関連 | ロケール依存処理の有無を確認 |
| PHP83-01 | PHP8.3 | 低 | 確定 | P | 8.3 非推奨（引数なし get_class 等） | Deprecated | static::class / self::class 等 |
| PHP84-01 | PHP8.4 | 高 | 確定 | P | 暗黙の nullable 引数 (Type $x = null) | Deprecated（9.0でエラー） | ?Type $x = null へ（Rector で自動置換可） |
| PHP84-02 | PHP8.4 | 中 | 確定 | PID | E_STRICT 定数 | Deprecated（定数非推奨・レベル削除） | E_STRICT を削除 |
| PHP84-03 | PHP8.4 | 中 | 要確認 | PD | session_set_save_handler() | コールバック6〜8個を渡す形式が非推奨 | SessionHandlerInterface 実装オブジェクトを渡す |
| PHP84-04 | PHP8.4 | 中 | 確定 | P | xml_set_object() | Deprecated | [$this, "method"] / クロージャ |
| PHP84-05 | PHP8.4 | 中 | 確定 | P | trigger_error(..., E_USER_ERROR) | Deprecated | 例外を throw |
| PHP84-06 | PHP8.4 | 中 | 確定 | P | mysqli 8.4 非推奨API | Deprecated | SQL の KILL / FLUSH へ |
| PHP84-07 | PHP8.4 | 中 | 監査 | P | round() | 内部実装変更で境界値の結果が変わりうる（金額・税計算） | 整数演算/BCMath。回帰テスト |
| PHP84-08 | PHP8.4 | 低 | 確定 | P | 8.4 非推奨関数/定数 | Deprecated | 置換 |
| PHP85-01 | PHP8.5 | 中 | 確定 | P | 非標準キャスト名 (integer)/(boolean)/(double)/(binary) | Deprecated | (int)/(bool)/(float)/(string) へ一括置換 |
| PHP85-03 | PHP8.5 | 中 | 確定 | P | __sleep()/__wakeup() | ソフト非推奨 | __serialize()/__unserialize() を追加 |
| PHP85-04 | PHP8.5 | 低 | 確定 | P | case のセミコロン終端 (case 1;) | Deprecated | コロンへ |
| PHP85-05 | PHP8.5 | 低 | 確定 | P | no-op 解放関数 | Deprecated（8.0以降何もしない） | 呼び出し削除 |
| PHP85-06 | PHP8.5 | 低 | 確定 | P | PDO::MYSQL_ATTR_* 定数 / uri: DSN | Deprecated | Pdo\Mysql::ATTR_*（8.4+） |
| PHP85-07 | PHP8.5 | 低 | 確定 | P | mysqli_execute() 別名 | Deprecated | mysqli_stmt_execute() |
| PHP85-08 | PHP8.5 | 低 | 確定 | P | 8.5 非推奨（$http_response_header 等） | Deprecated | http_get_last_response_headers() / stream_set_timeout() 等 |
| PHP85-09 | PHP8.5 | 低 | 要確認 | P | attach()/detach()（SplObjectStorage の場合） | Deprecated | offsetSet()/offsetUnset() |
| PHPX-01 | 環境 | 高 | 確定 | P | 短縮開始タグ <? | short_open_tag=Off で PHP として解釈されずソースが露出 | <?php へ置換（暫定 short_open_tag=On） |
| PHPX-03 | 環境 | 低 | 要確認 | P | $_ENV 参照 | variables_order=GPCS（production既定）で空 | getenv() へ |
| PHPX-04 | 環境 | 中 | 要確認 | PD | mod_php 依存 (apache_*, PHP_AUTH_*, PATH_INFO) | php-fpm 構成で使えない/値が変わる | Webサーバ設定で引き渡し、代替実装 |
| PHPX-06 | 環境 | 低 | 要確認 | P | 32bit/64bit 依存 (crc32, ip2long) | 64bit では負にならない。DB保存済みの符号付き値と不一致 | sprintf('%u') 等で正規化 |
| PHPX-08 | 環境 | 低 | 要確認 | P | eval() | eval されるコードは本ツールで検査できない | 評価対象コードを別途確認 |
| PHPX-10 | 環境 | 中 | 要確認 | PD | 外部ライブラリ/フレームワーク利用 | 旧版は PHP 8 非対応の可能性が高い（ライブラリ自体が本表の非互換を含む） | バージョンを特定し PHP 8.5 対応版の有無を確認 |
| INI-01 | PHP5.4-8.x | 中 | 確定 | ID | 削除済み php.ini ディレクティブ | 起動時に警告/無視。機能が無くなっている（register_globals, magic_quotes, func_overload 等は挙動に直結） | php.ini-production をベースに新規作成し、当該行は移植しない。依存コードを修正 |
| INI-01p | PHP5.4-8.x | 中 | 確定 | P | ini_set/ini_get で削除済みディレクティブを操作 | 効果なし/false を返す | 依存処理を修正 |
| INI-02 | PHP5.6-8.5 | 低 | 確定 | ID | 非推奨 php.ini ディレクティブ | 起動時 Deprecated | default_charset 等の代替へ |
| INI-02p | PHP5.6-8.5 | 低 | 確定 | P | ini_set/ini_get で非推奨ディレクティブを操作 | Deprecated | 代替設定へ |
| INI-03 | 環境 | 中 | 要確認 | ID | 値の再確認が必要な php.ini 設定 | 既定値・推奨値が変わっている（文字コード、TZ、エラー表示、短縮タグ等） | 新 php.ini へ意図した値を明示的に移植 |
| INI-03p | 環境 | 中 | 要確認 | P | 実行時の ini_set による重要設定 | 設定の一元管理・既定値変更の影響確認 | 値を確認 |
| INI-04 | 環境 | 中 | 確定 | ID | .htaccess / httpd.conf の php_value/php_flag | php-fpm では無効（mod_php 専用） | .user.ini または FPM pool の php_admin_value へ |
| INI-05 | PHP8.5 | 中 | 確定 | I | zend_extension=opcache | 8.5 で OPcache 常時組込み。行が残ると Warning | 行を削除 |
| INI-06 | PHP7.0+ | 高 | 確定 | I | 削除/PECL移動済み拡張のロード | 起動時エラー。当該拡張の関数が使えない | 代替拡張へ移行 |
| LNK-01 | 連携 | 高 | 確定 | PSD | SET NAMES / SET CHARACTER SET の直接発行 | エスケープ関数に反映されない（SJIS系では5C問題によるSQLインジェクション）。utf8指定のままだと4バイト文字欠落 | mysqli_set_charset() / DSN charset= で指定 |
| LNK-02 | 連携 | 高 | 確定 | PSCD | 接続文字コードが utf8mb4 以外 | sjis/ujis は機種依存文字が化ける。utf8(mb3) は絵文字・一部漢字が欠落。latin1 は誤宣言DBの疑い | DB変換後に utf8mb4 へ統一。SJIS運用継続なら cp932 |
| LNK-03 | 連携 | 高 | 要確認 | PD | addslashes() によるエスケープ | magic quotes 代替としてSQLに使用している場合、マルチバイトで不完全 | プリペアドステートメントへ |
| LNK-04 | 連携 | 低 | 要確認 | P | 永続接続 | セッション状態（SET NAMES, sql_mode, 一時表）が残留 | 必要性を再評価 |
| LNK-05 | 連携 | 中 | 監査 | P | insert_id / affected_rows | 複数行INSERTのID連番前提は innodb_autoinc_lock_mode=2 で崩れる。affected_rows の意味（変更行/一致行） | ID推定をやめ再SELECT。FOUND_ROWS フラグを確認 |
| LNK-06 | 連携 | 中 | 確定 | PSD | LOAD DATA / INTO OUTFILE | secure_file_priv 既定で 1290、local_infile=OFF 既定で 1148/3948 | 出力先ディレクトリ・許可設定を見直し |
| LNK-07 | 連携 | 低 | 要確認 | P | 複数ステートメント実行 | インジェクション時の被害拡大 | 無効化を検討 |
| LNK-08 | 連携 | 高 | 要確認 | PSD | 接続時初期化コマンド / sql_mode 設定 | NO_AUTO_CREATE_USER 等を含むと 8.0 で接続自体が失敗。既定 sql_mode の厳格化 | 設定値を確認・修正 |
| LNK-09 | 連携 | 高 | 確定 | P | mysqli に単純対応が無い/挙動差の大きい mysql_* 関数 | 機械置換不可。ヘルパ実装が必要（mysql_result, mysql_field_type の型名文字列 等） | ガイド14節の対応表に従い個別実装 |
| LNK-10 | 連携 | 中 | 要確認 | PSD | DSN 文字列 | charset 指定の有無、ソケットパス、ドライバ種別を確認 | DSN に charset=utf8mb4 を明示 |
| LNK-11 | 連携 | 低 | 要確認 | P | MySQL TLS 接続設定 | TLSv1.2以上必須、証明書検証 | CA配布・検証設定 |
| LNK-12 | 連携 | 中 | 要確認 | P | エスケープ関数による SQL 組み立て | 接続charsetを API で設定していないと不完全。null 渡しは 8.1 で Deprecated | プリペアドステートメントへ |
| SQL55-01 | MySQL5.5 | 高 | 確定 | PSD | TYPE=エンジン 構文 | 構文エラー | ENGINE= へ |
| SQL55-02 | MySQL5.5 | 中 | 要確認 | PSD | MyISAM テーブル | 既定エンジンは InnoDB。FULLTEXT/グループ別AUTO_INCREMENT/テーブルロック前提の挙動差。8.0 でパーティション不可 | InnoDB 化の可否を検討（COUNT(*) 性能、ロック、トランザクション） |
| SQL55-03 | MySQL5.5 | 中 | 確定 | PSD | 5.5 削除 SQL | 構文エラー | SHOW ENGINE INNODB STATUS 等へ |
| SQL55-05 | MySQL5.6+ | 中 | 要確認 | PSD | 全文検索 (FULLTEXT / MATCH AGAINST) | InnoDB FTS は最小トークン長・ストップワード・スコアが MyISAM と異なる。日本語は ngram パーサが必要 | WITH PARSER ngram で再インデックス、結果比較 |
| SQL56-01 | MySQL5.6/8.0 | 高 | 要確認 | SD | TIMESTAMP 列定義 | explicit_defaults_for_timestamp=ON(8.0既定)で暗黙の DEFAULT/ON UPDATE CURRENT_TIMESTAMP が付かない。NULL代入で現在時刻にならない（サイレント） | DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP を明示 |
| SQL56-02 | MySQL5.6/5.7 | 中 | 確定 | PSD | INSERT DELAYED | 通常INSERT扱い→将来削除 | DELAYED を削除 |
| SQL56-03 | MySQL5.6 | 中 | 確定 | SD | YEAR(2) 型 | 削除 | YEAR(4) へ ALTER |
| SQL56-04 | MySQL5.6/8.0 | 高 | 確定 | PSD | GRANT ... IDENTIFIED BY / IDENTIFIED BY PASSWORD | 8.0 で構文エラー（GRANT によるユーザ作成不可） | CREATE USER → GRANT の2文へ |
| SQL56-05 | MySQL5.6+ | 高 | 監査 | PSD | LIMIT（ページング） | 同順位行の並びが非決定。ページ間で行が重複/欠落（サイレント） | ORDER BY に主キー等のタイブレークを追加 |
| SQL57-01 | MySQL5.7/8.0 | 高 | 確定 | PSD | GROUP BY col ASC/DESC | 8.0 で構文エラー | ORDER BY を明示 |
| SQL57-01b | MySQL5.7/8.0 | 高 | 要確認 | PSD | GROUP BY | ONLY_FULL_GROUP_BY(5.7既定)で非集約列の SELECT が 1055 エラー。暗黙ソート削除(8.0)で並び順が変わる（サイレント） | SELECT 列を集約/ANY_VALUE()、ORDER BY を明示 |
| SQL57-02 | MySQL5.7 | 高 | 確定 | PSD | ゼロ日付 '0000-00-00' | NO_ZERO_DATE(strict)で INSERT/DDL がエラー(1292/1067)。旧ダンプが import 不可 | 列を NULL 許容にし NULL へ移行。PHP側の判定も修正 |
| SQL57-03 | MySQL5.7/8.0 | 高 | 要確認 | PSD | 派生テーブル (FROM (SELECT ...)) | derived_merge で内側 ORDER BY が無視され「グループ内最新行」イディオムが壊れる（サイレント）。UPDATE 対象表の参照は 1093 | ウィンドウ関数 ROW_NUMBER() / 相関サブクエリへ |
| SQL57-04 | MySQL5.7/8.0 | 高 | 要確認 | PSD | PASSWORD() / SET PASSWORD | 8.0 で関数削除 | ALTER USER ... IDENTIFIED BY。アプリ独自認証に使用している場合は password_hash 等へ移行 |
| SQL57-05 | MySQL5.7/8.0 | 高 | 要確認 | PSD | ENCODE/DECODE/ENCRYPT/DES_* 関数 | 8.0 で削除。暗号化済み列が復号不能になる | 8.0 移行前に平文化し AES_ENCRYPT / アプリ側暗号へ |
| SQL57-06 | MySQL5.7/8.0 | 中 | 確定 | PSD | 旧名の空間関数 | 8.0 で FUNCTION does not exist | ST_ 接頭辞の関数へ |
| SQL57-08 | MySQL5.7/8.0 | 中 | 確定 | PSD | information_schema.GLOBAL_STATUS 等 | 5.7 でエラー、8.0 で削除 | performance_schema.global_status / SHOW STATUS |
| SQL57-09 | MySQL5.7 | 中 | 確定 | PSD | ALTER IGNORE TABLE | 構文削除 | 重複を事前に解消 |
| SQL57-10 | MySQL5.7 | 中 | 要確認 | PSD | INSERT IGNORE / UPDATE IGNORE | strict モードのエラーが警告に降格され、切り捨て・型変換が黙って起きる | データ欠損を許容する意図か確認 |
| SQL57-11 | MySQL5.7 | 低 | 要確認 | PSD | GET_LOCK() | 複数ロック同時保持になり、2回目の GET_LOCK で1回目が解放されない | RELEASE_LOCK を明示 |
| SQL57-12 | MySQL5.7 | 中 | 監査 | SD | NOT NULL（DEFAULT なし）列 | strict モードで INSERT 時に列省略すると 1364 エラー | DEFAULT を明示、または INSERT 側で値を指定 |
| SQL80-01 | MySQL8.0 | 中 | 確定 | PSD | SQL_CALC_FOUND_ROWS / FOUND_ROWS() | 非推奨（8.0.17）。将来削除 | 別途 COUNT(*) を発行 |
| SQL80-02 | MySQL8.0 | 低 | 確定 | PSD | ON DUPLICATE KEY UPDATE ... VALUES() | 非推奨（8.0.20） | 行エイリアス構文へ（DB更新完了後） |
| SQL80-03 | MySQL8.0 | 高 | 確定 | PSD | クエリキャッシュ構文 (SQL_CACHE 等) | 構文エラー（クエリキャッシュ削除） | 削除 |
| SQL80-03b | MySQL8.0 | 低 | 確定 | PSD | SQL_NO_CACHE | 無視される（非推奨） | 削除 |
| SQL80-04 | MySQL8.0 | 中 | 確定 | PSD | EXPLAIN EXTENDED / PROCEDURE ANALYSE | 構文エラー | 削除 |
| SQL80-05 | MySQL8.0 | 高 | 確定 | PSCD | tx_isolation / tx_read_only | 変数削除（1193 エラー / 起動失敗） | transaction_isolation / transaction_read_only |
| SQL80-06 | MySQL8.0 | 高 | 確定 | PSCD | sql_mode の削除値 (NO_AUTO_CREATE_USER 等) | 起動失敗 / SET sql_mode が 1231 エラー | 文字列から除去 |
| SQL80-07 | MySQL8.0 | 中 | 要確認 | PSD | REGEXP / RLIKE | ICU 化。マルチバイトが文字単位マッチに変わり結果が変わる（サイレント） | 正規表現を棚卸ししテスト |
| SQL80-07b | MySQL8.0 | 高 | 確定 | PSD | 単語境界 [[:<:]] [[:>:]] | ICU では不可（エラー） | \\b へ |
| SQL80-08 | MySQL8.0 | 中 | 要確認 | PSD | information_schema 参照 | 列名が大文字で返る（$row["table_name"] が未定義）。統計値はキャッシュ（最大1日古い） | 列に AS 別名、information_schema_stats_expiry=0 |
| SQL80-09 | MySQL5.5-8.0 | 高 | 要確認 | SD | 予約語と同名の列定義 | クォートなしで参照する SQL が構文エラー。ビュー/ルーチンに含むとアップグレード失敗 | アプリ側 SQL のバッククォート有無を確認、またはリネーム |
| SQL80-09b | MySQL5.5-8.0 | 高 | 要確認 | PSD | 予約語がクォートなしで識別子として使われている可能性 | 構文エラー（rank, groups, system, lead, window 等） | バッククォートで囲む/リネーム |
| SQL80-10 | MySQL8.0 | 中 | 要確認 | PSCD | utf8 (utf8mb3) の宣言 | 4バイト文字（絵文字・一部漢字）が入らない。8.0 で非推奨警告 | utf8mb4 へ変換（行サイズ・索引長・照合順序に注意） |
| SQL80-10b | MySQL8.0 | 高 | 要確認 | PSCD | latin1 の宣言 | 日本語DBでは「誤宣言」（実体は SJIS/UTF-8 バイト列）の疑い。そのまま CONVERT TO すると全データが化ける | HEX() で実バイト列を確認し、VARBINARY 経由で実エンコードを宣言してから変換 |
| SQL80-10c | MySQL8.0 | 高 | 要確認 | PSCD | sjis / ujis の宣言 | 機種依存文字(①㈱髙 等)が sjis/ujis に無く、変換時に ? 化/エラー。～－∥ の対応コードポイント差 | Windows由来データは cp932 / eucjpms として扱い変換 |
| SQL80-10d | MySQL8.0 | 高 | 要確認 | PSCD | 照合順序の指定 | 8.0 既定 utf8mb4_0900_ai_ci は濁点・かな・大小を区別せず NO PAD。既存 general_ci と混在すると 1267 | DB全体で照合順序を統一（日本語は utf8mb4_ja_0900_as_cs / utf8mb4_bin / general_ci 維持） |
| SQL80-11 | MySQL8.0 | 中 | 確定 | SD | ZEROFILL | 非推奨。表示幅に依存したゼロ埋め | LPAD() / アプリ側で整形 |
| SQL80-11b | MySQL8.0 | 低 | 監査 | S | 整数表示幅 INT(n) / FLOAT(M,D) | 非推奨。SHOW CREATE TABLE から消え、int(11) を解析するコードが壊れる | 表示幅を削除 |
| SQL80-12 | MySQL8.0 | 低 | 要確認 | PSD | BINARY 演算子 | 非推奨（8.0.27） | CAST(... AS BINARY) / COLLATE utf8mb4_bin |
| SQL80-14 | MySQL8.0/8.4 | 中 | 確定 | SD | DEFINER= 付きオブジェクト | import に SET_USER_ID(8.0)/SET_ANY_DEFINER(8.4) 権限が必要。定義者ユーザ不在で実行時エラー | DEFINER を除去または権限付与 |
| SQL80-15 | MySQL8.0 | 中 | 確定 | S | SQL 文中の \N（NULL の別表記） | 8.0 で構文エラー | NULL へ |
| SQL80-16 | MySQL5.5/8.0 | 中 | 要確認 | PSD | パーティション定義 | MyISAM パーティション不可(8.0)。5.1 作成の KEY パーティションはハッシュ方式が旧式 | InnoDB 化、ALGORITHM=2 で再パーティション |
| SQL80-17 | MySQL5.7/8.0 | 中 | 要確認 | PSD | ユーザ管理 SQL / mysql.user 直接操作 | Password 列削除、権限テーブルへの直接DMLは不可/非推奨。既定認証プラグイン変更 | CREATE USER / ALTER USER / GRANT のみ使用 |
| SQL80-18 | MySQL8.0 | 低 | 確定 | PSD | JSON_MERGE() | 非推奨 | JSON_MERGE_PRESERVE() |
| SQL80-19 | MySQL8.0 | 中 | 要確認 | PSD | UNION | 各 SELECT 内の ORDER BY は LIMIT が無いと無視される | 外側で ORDER BY |
| SQL80-20 | MySQL8.0 | 低 | 要確認 | PSD | インデックスヒント / STRAIGHT_JOIN | オプティマイザ変更で旧ヒントが逆効果になりうる | 実行計画を新環境で再確認 |
| SQL80-21 | MySQL8.0 | 低 | 要確認 | PSD | LOCK TABLES | MyISAM 前提の排他制御。InnoDB ではトランザクションとの併用に注意 | トランザクション / SELECT ... FOR UPDATE へ |
| SQL80-22 | MySQL8.0 | 低 | 要確認 | PSD | LENGTH()（バイト長） | utf8mb4 化で1文字最大4バイト。桁チェックの結果が変わる | CHAR_LENGTH() へ |
| SQL84-01 | MySQL8.4 | 高 | 確定 | PSD | MASTER/SLAVE 系レプリケーション構文・FLUSH HOSTS | 8.4 で構文エラー（監視・フェイルオーバ・バックアップスクリプト） | SOURCE/REPLICA 系構文へ（SHOW BINARY LOG STATUS, SHOW REPLICA STATUS 等） |
| SQL84-02 | MySQL8.0/8.4 | 高 | 確定 | PSCD | 認証プラグイン指定 | mysql_native_password は 8.4 で既定無効（1524）。9.x で削除 | caching_sha2_password へ（PHP 7.4+ 必須） |
| SQL84-03 | MySQL8.0/8.4 | 中 | 確定 | PSD | 削除済みクライアントツール | コマンドが存在しない | mysqldump / MySQL Shell / mysqld --initialize |
| SQL84-04 | MySQL8.0 | 低 | 要確認 | PSD | MySQL クライアントツール呼び出し | オプション既定値の変更（--column-statistics, --set-gtid-purged, 文字コード既定 utf8mb4, PROCESS 権限） | オプションを明示し新旧組合せで動作確認 |
| SQL84-05 | MySQL8.0 | 低 | 要確認 | PSD | SUPER / SET_USER_ID 権限 | SUPER 非推奨（動的権限へ）、SET_USER_ID は 8.4 で削除 | 動的権限 / SET_ANY_DEFINER |
| CNF-55 | MySQL5.5/5.6 | 高 | 確定 | CD | 5.5/5.6 で削除された my.cnf オプション | mysqld が起動しない（unknown variable） | my.cnf を新規作成し代替オプションへ（skip-external-locking, table_open_cache, slow_query_log 等） |
| CNF-55b | MySQL5.5 | 高 | 確定 | C | [mysqld] 節の default-character-set | mysqld が起動しない | character-set-server へ（[client]/[mysql] 節では有効だが mysqlnd は読まない） |
| CNF-55c | MySQL5.5 | 高 | 確定 | C | log= / language= | 起動失敗（general_log / lc_messages_dir へ変更。language は 8.4 で削除） | general_log, general_log_file / lc_messages_dir |
| CNF-57 | MySQL5.7 | 高 | 確定 | CD | 5.7 で削除された my.cnf オプション | mysqld が起動しない | 行を削除 |
| CNF-57b | MySQL5.7 | 高 | 確定 | C | オプション名の前方一致省略 (key_buffer= 等) | 5.7 以降は省略形を受け付けず起動失敗 | 正式名 (key_buffer_size 等) へ |
| CNF-57c | MySQL5.7 | 中 | 確定 | C | [mysqld_safe] 節 | systemd 環境では mysqld_safe を使わず、この節は無視される | log-error, pid-file, open-files-limit 等を [mysqld] / systemd へ移動 |
| CNF-80 | MySQL8.0 | 高 | 確定 | CD | 8.0 で削除された my.cnf 変数 | mysqld が起動しない（query_cache_*, innodb_file_format, log_warnings 等） | 行を削除/代替へ。mysqld --validate-config で検証 |
| CNF-84 | MySQL8.4 | 高 | 確定 | CD | 8.4 で削除された my.cnf 変数 | mysqld が起動しない（default_authentication_plugin, expire_logs_days, skip-character-set-client-handshake 等） | authentication_policy / binlog_expire_logs_seconds 等へ。charset は接続側で明示 |
| CNF-84b | MySQL8.4 | 高 | 確定 | C | 8.4 で削除されたオプション (old/new/ssl/innodb) | mysqld が起動しない | 行を削除 |
| CNF-DEP | MySQL8.0-8.4 | 低 | 確定 | CD | 非推奨の my.cnf 変数 | 警告。将来削除（innodb_log_file_size → innodb_redo_log_capacity、slave_* → replica_* 等） | 代替変数へ |
| CNF-CHK | 環境 | 中 | 要確認 | CD | 値の再確認が必要な my.cnf 設定 | 既定値が大きく変わっている/移行方針の決定が必要（sql_mode, 文字コード, 照合, TIMESTAMP, 認証 等） | 新 my.cnf に意図した値を明示 |
| DOC-01 | 設計書 | 低 | 要確認 | D | 旧バージョン・旧環境の記載 | 前提バージョンの記述箇所。設計書の改訂対象 | 移行後バージョンへ改訂し、前提に依存する記述を確認 |
| DOC-02 | 設計書 | 中 | 要確認 | D | 文字コード・照合順序に関する記載 | 文字コード変換（utf8mb4化）、照合順序（濁点/かな/末尾空白）、バイト長前提の仕様に影響 | ガイド13節に照らして仕様を確認 |
| DOC-03 | 設計書 | 中 | 要確認 | D | DB 物理設計・運用方式に関する記載 | エンジン既定変更、レプリケーション構文、クエリキャッシュ削除、採番方式等に影響 | ガイド9〜12節に照らして確認 |
| DOC-04 | 設計書 | 中 | 要確認 | D | 認証・暗号・バックアップに関する記載 | mcrypt 削除、MySQL ENCODE/PASSWORD 削除、認証プラグイン変更、TLS バージョン、ダンプ手順に影響 | ガイドの該当節に照らして確認 |
| DOC-05 | 設計書 | 中 | 要確認 | D | ミドルウェア・ライブラリ・実行方式に関する記載 | PHP 8.5 対応版の有無、APC→OPcache/APCu、mod_php→FPM の影響 | バージョンと対応状況を確認 |
| DOC-06 | 設計書 | 低 | 要確認 | D | 日時・端数処理に関する記載 | date.timezone 既定 UTC、TIMESTAMP 暗黙既定、ゼロ日付、round() 実装変更に影響 | 仕様と実装の対応を確認 |
| DOC-07 | 設計書 | 低 | 要確認 | D | エラー処理・バッチに関する記載 | エラー既定レベル、DB例外化、長時間バッチの再接続に影響 | 方針を確認 |

## ファイル単位の特殊チェック（8）

| ID | 導入Ver | 重要度 | 確度 | 種別 | 対象 | 影響 | 修正方針 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ENC-01 | PHP5.4+ | 高 | 確定 | P | ソースファイルが非 UTF-8 | zend.multibyte 未設定では SJIS の 5C 問題で Parse error。default_charset と不整合で文字化け | ソースを UTF-8(BOMなし) へ一括変換 |
| ENC-02 | 環境 | 中 | 確定 | P | UTF-8 BOM 付きソース | BOM が出力され header()/session_start() が失敗 | BOM を除去 |
| ENC-03 | PHP5.4+ | 高 | 要確認 | P | SJIS の 5C 文字（ソ・表・能 等）を含む行 | zend.multibyte なしでは文字列リテラルが壊れる | ソースを UTF-8 化 |
| PHP70-07 | PHP7.0/8.0 | 高 | 確定 | P | PHP4 形式コンストラクタ | 8.0 でコンストラクタとして呼ばれない（サイレント） | __construct() へ |
| PHP73-02 | PHP7.3 | 中 | 確定 | P | ヒアドキュメント本文に終端識別子と同じ語で始まる行 | Parse error / 本文欠落 | 識別子を変更 |
| PHP85-02 | PHP8.5 | 低 | 要確認 | P | バッククォート演算子 | Deprecated | shell_exec() へ |
| INI-TZ | PHP7.0 | 高 | 確定 | I | php.ini に date.timezone 未設定 | 無警告で UTC になる（サイレント） | Asia/Tokyo を設定 |
| SQL55-04 | MySQL5.5 | 高 | 確定 | S | ENGINE 指定のない CREATE TABLE（.sql） | InnoDB で作成される | ENGINE を明示 |

## 機械検出できない確認項目（28）

| ID | 導入Ver | 重要度 | 確認対象 | 確認方法 |
| --- | --- | --- | --- | --- |
| M-01 | PHP8.0 | 高 | 非数値文字列/配列/null への算術・比較（型は静的に判定不能） | 新環境で error_reporting=E_ALL のログを収集（TypeError / Warning: A non-numeric value） |
| M-02 | PHP8.0 | 高 | ゼロ除算（/ と %）が DivisionByZeroError | 除算箇所の分母が 0 になるケースのテスト |
| M-03 | PHP8.0 | 高 | 非 static メソッドの static 呼び出し（Error） | PHPCompatibility / PHPStan、または実行ログ |
| M-04 | PHP8.0 | 高 | 継承時のメソッドシグネチャ非互換（Fatal） | 対象バージョンの php -l / 全クラスのロードテスト |
| M-05 | PHP8.0 | 高 | 未定義定数（クォート忘れ $a[key]）が Error、未定義変数/キーが Warning | 実行ログ収集 |
| M-06 | PHP8.0 | 高 | 内部関数の引数型不正が TypeError / ValueError（strlen([]) explode("",..) 等） | 実行ログ収集、PHPStan |
| M-07 | PHP8.1 | 高 | 内部関数への null 渡し（Deprecated、9.0 で TypeError） | 実行ログの「Passing null to parameter」を集計 |
| M-08 | PHP8.2 | 高 | 動的プロパティ（未宣言プロパティへの代入） | 実行ログの「Creation of dynamic property」を集計 |
| M-09 | PHP8.1 | 中 | float→int の暗黙変換、false からの配列自動生成 | 実行ログ収集 |
| M-10 | PHP7.0 | 中 | foreach 内での current()/next()、list() の代入順、func_get_args() の変更後値 | 該当イディオムの目視、テスト |
| M-11 | PHP7.3 | 中 | switch 内の continue（Warning） | 対象バージョンの php -l |
| M-12 | PHP7.2 | 高 | mbstring.func_overload 有効環境での strlen/substr/strpos 等（バイト単位に変わる） | php.ini の func_overload 値を確認し、有効なら全該当関数を mb_* へ |
| M-13 | PHP8.5 | 中 | null の配列オフセット、非数値文字列の ++、#[NoDiscard] 戻り値破棄 | 実行ログ収集 |
| M-14 | 環境 | 高 | 全 PHP ファイルの構文エラー | 対象バージョンで find . -name "*.php" \| xargs -n1 php -l |
| M-15 | MySQL5.7 | 高 | strict モード違反（型不正・桁あふれ・NOT NULL 省略・空文字の数値列挿入） | general_log を新DBで再生し SHOW WARNINGS / エラーを収集 |
| M-16 | MySQL5.7 | 高 | ONLY_FULL_GROUP_BY 違反（SELECT 列と GROUP BY の不整合） | 全 GROUP BY クエリを新DBで実行（1055/3065） |
| M-17 | MySQL8.0 | 高 | GROUP BY の暗黙ソート依存、ORDER BY なし一覧の並び順 | 旧新DBで結果比較（pt-upgrade 等） |
| M-18 | MySQL8.0 | 高 | 照合順序の意味変更（濁点/かな同一視、NO PAD、UNIQUE 重複） | ガイド16節の調査SQL、テストデータ（は/ば/ぱ、末尾空白） |
| M-19 | MySQL8.0 | 高 | latin1 誤宣言・機種依存文字・4バイト文字の実データ | SELECT HEX(col) によるサンプリング |
| M-20 | MySQL5.6 | 高 | 旧時刻フォーマット列（5.6.4 以前作成の DATETIME/TIMESTAMP/TIME） | mysqlcheck --check-upgrade → ALTER TABLE ... FORCE |
| M-21 | MySQL8.0 | 高 | データディクショナリ移行の阻害要因（予約語、旧構文を含むビュー/ルーチン、MyISAMパーティション） | MySQL Shell util.checkForServerUpgrade() |
| M-22 | MySQL8.4 | 高 | mysql_native_password ユーザ / 旧16桁ハッシュ | SELECT user,host,plugin FROM mysql.user |
| M-23 | MySQL8.0 | 中 | 実行計画の退行（オプティマイザ変更） | スロークエリログ比較、EXPLAIN |
| M-24 | MySQL8.0 | 中 | 眠っている EVENT（event_scheduler=ON 既定で動き出す） | SHOW EVENTS |
| M-25 | 連携 | 高 | DB エラー時のフロー（戻り値判定→例外）、数値型（文字列→int/float） | 異常系テスト、JSON API のスナップショット比較 |
| M-26 | 連携 | 中 | mysqlnd が my.cnf [client] を読まないことによる charset/socket の欠落 | 接続コードで charset・socket を明示しているか確認 |
| M-27 | 環境 | 中 | 32bit→64bit 移行（整数幅、crc32/ip2long の符号） | 旧サーバのアーキテクチャ確認、保存値の形式確認 |
| M-28 | 設計書 | 中 | PDF・画像・パスワード付き Office・旧形式(xls/doc)の設計書 | 本ツールは未対応/簡易抽出。目視または xlsx/docx へ変換して再走査 |
