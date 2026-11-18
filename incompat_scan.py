#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
incompat_scan.py
PHP 5.3 -> 8.5 / MySQL 5.1 -> 8.4 LTS 非互換 該当箇所スキャナ

  * Python 3.11 以上、標準ライブラリのみ（pip 不要・ネットワーク不要）
  * ソース（PHP / SQL / 設定 / シェル）と設計書（xlsx / docx / pptx / テキスト、
    旧形式 xls / doc / ppt は簡易抽出）を走査し、非互換ルールに該当する箇所を出力
  * 出力: findings.csv（該当箇所）, summary.csv（ルール別件数）, files.csv（ファイル別）,
          manual_checklist.csv（機械検出できない確認項目）, report.html

使い方:
  python incompat_scan.py <調査対象フォルダ> [-o 出力フォルダ] [--audit] ...
  python incompat_scan.py --list-rules
  python incompat_scan.py --help

「ガイド参照」列の節番号は docs/incompatibility-guide.md（非互換整理）の節・項番を指す。

確度:
  A = 確定    パターンに一致すれば原則対応が必要
  B = 要確認  該当の可能性あり。目視で要否を判定
  C = 監査    サイレントな挙動変更の候補を広く拾う（件数大。--audit 指定時のみ）
"""
from __future__ import print_function

import argparse
import csv
import html
import io
import json
import os
import re
import sys
import time
import unicodedata
import zipfile
import xml.etree.ElementTree as ET

VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# ルール定義
# ---------------------------------------------------------------------------
# targets: P=PHPソース S=SQL/スクリプト/汎用設定 I=php.ini系 C=my.cnf系 D=設計書
RULES = []
FLAGS = re.I | re.A   # re.A: \w \b を ASCII 基準に（日本語隣接でも単語境界になる）


def R(rid, ver, sev, conf, targets, pattern, title, impact, fix, ref="", **opt):
    RULES.append(dict(id=rid, ver=ver, sev=sev, conf=conf, targets=targets,
                      pattern=pattern, title=title, impact=impact, fix=fix,
                      ref=ref, doc=opt.get("doc"), ex=opt.get("ex"),
                      cs=opt.get("cs", False), sect=opt.get("sect")))


def FN(names):
    """関数呼び出しパターン（メソッド呼び出し ->x( / ::x( / $x( は除外）"""
    return r'(?<![\w>:$])(?:%s)\s*\(' % names


def BARE(names):
    return r'(?<![\w$])(?:%s)(?![\w])' % names


def CNF(names):
    """my.cnf のオプション行（- と _ を同一視）"""
    n = names.replace('_', '[-_]')
    return r'^\s*(?:--)?(?:loose[-_])?(?:%s)(?=\s*(?:=|$|#|;))' % n


def CNFDOC(names):
    n = names.replace('_', '[-_]')
    return r'(?<![\w-])(?:%s)(?![\w-])' % n


def INI(names):
    return r'^\s*(?:php_(?:admin_)?(?:value|flag)\s+)?(?:%s)(?![\w.])' % names


def INISET(names):
    return r'''ini_(?:set|get|alter|restore)\s*\(\s*['"](?:%s)['"]''' % names


# ============================ PHP 5.4 ======================================
R('PHP54-01', 'PHP5.4', '高', 'A', 'PD',
  r'\$HTTP_(?:GET|POST|COOKIE|SERVER|ENV|SESSION)_VARS\b|\$HTTP_POST_FILES\b',
  '$HTTP_*_VARS（register_long_arrays）', '未定義変数(null)になり分岐が無警告で変わる',
  '$_GET/$_POST/$_SESSION 等へ置換', '§2-1')
R('PHP54-02', 'PHP5.4', '高', 'A', 'PD',
  FN('get_magic_quotes_gpc|get_magic_quotes_runtime|set_magic_quotes_runtime|magic_quotes_runtime'),
  'magic_quotes 関連関数', '5.4で機能削除・7.0/8.0で関数削除(Fatal)。magic quotes前提のSQLはインジェクション可能になる',
  '分岐ごと削除し、SQLはプリペアドステートメントへ', '§2-2 §4-36',
  doc=BARE('magic_quotes_gpc|magic_quotes_runtime|get_magic_quotes_gpc|set_magic_quotes_runtime|magic_quotes'))
R('PHP54-03', 'PHP5.4', '高', 'B', 'P',
  r'(?<![\w$])[a-z_]\w*\s*\((?:[^()]*,)?\s*&\s*\$\w',
  '呼び出し時参照渡し foo(&$a) の可能性', 'Fatal error（コンパイル時）',
  '関数定義側を function foo(&$a) にし、呼び出し側の & を削除', '§2-3',
  ex=r'\bfunction\b|\bforeach\b|\barray\s*\(|\buse\s*\(|\bfn\s*\(|&&')
R('PHP54-04', 'PHP5.4/8.1', '高', 'B', 'PD',
  FN('htmlspecialchars|htmlentities|html_entity_decode|htmlspecialchars_decode|get_html_translation_table'),
  'htmlspecialchars 系（charset/flags 既定値）',
  '既定charsetがUTF-8(5.4)。SJIS/EUC-JP文字列は空文字になる。既定flagsがENT_QUOTES|ENT_SUBSTITUTE(8.1)で \' もエスケープ',
  '第2・第3引数(flags, encoding)の明示有無を確認。内部エンコードに合わせて明示', '§2-4 §6-5')
R('PHP54-05', 'PHP5.4', '中', 'A', 'P',
  r'\b(?:break|continue)\s+(?:0|\$\w+)\s*;',
  'break 0 / break $n / continue $n', 'Fatal error', '定数リテラルに書き換え', '§2-5')
R('PHP54-06', 'PHP5.4', '中', 'A', 'PD',
  FN('session_register|session_unregister|session_is_registered'),
  'session_register 系', 'Fatal error（未定義関数）', '$_SESSION を直接操作', '§2-6',
  doc=BARE('session_register|session_unregister|session_is_registered'))
R('PHP54-07', 'PHP5.4', '中', 'A', 'PD',
  FN('mysqli_bind_param|mysqli_bind_result|mysqli_client_encoding|mysqli_fetch|mysqli_param_count|'
     r'mysqli_get_metadata|mysqli_send_long_data|mysqli_master_query|mysqli_slave_query|mysqli_rpl_\w+|'
     'mysqli_(?:disable|enable)_reads_from_master|mysqli_(?:disable|enable)_rpl_parse|mysqli_send_query'),
  'mysqli 旧別名・レプリケーション関数', 'Fatal error', 'mysqli_stmt_* 正式名へ。rpl系は削除', '§2-7')
R('PHP54-08', 'PHP5.4', '中', 'A', 'PD',
  FN('import_request_variables|define_syslog_variables'),
  'import_request_variables 等', 'Fatal error', '$_REQUEST 等を明示的に参照', '§2-8')
R('PHP54-13', 'PHP5.4', '低', 'A', 'P',
  r'function\s+\w*\s*\([^)]*\$(?:_GET|_POST|_SESSION|_COOKIE|_SERVER|_REQUEST|_FILES|_ENV|GLOBALS)\b',
  'スーパーグローバル名の引数', 'Fatal error', '引数名を変更', '§2-13')

# ============================ PHP 5.5 ======================================
R('PHP55-01', 'PHP5.5/7.0', '高', 'A', 'PD',
  FN(r'mysql_[a-z_]+'),
  'ext/mysql (mysql_*)', '7.0で削除。Fatal error: Call to undefined function',
  'mysqli / PDO へ置換（ガイド14節の対応表）。引数順・暗黙接続・エラー処理が変わる', '§2-14 §3-1 §14',
  doc=r'(?<![\w$])mysql_[a-z_]+(?![\w])')
R('PHP55-02', 'PHP5.5/7.0', '高', 'A', 'P',
  r'''preg_replace\s*\(\s*['"].*?[/#~|!@%}\])][imsxuADSUXJ]*e[imsxuADSUXJ]*['"]\s*,''',
  'preg_replace の /e 修飾子', '7.0以降 Warning + null を返し置換結果が消える（サイレント）',
  'preg_replace_callback へ', '§2-15 §3-4', cs=True)
R('PHP55-02b', 'PHP5.5/7.0', '高', 'B', 'P',
  r'''['"][/#~|!@%][^'"]*[/#~|!@%][imsxuADSUX]*e[imsxuADSUX]*['"]''',
  '/e 修飾子付き正規表現リテラルの可能性（配列・変数経由）', '同上',
  'preg_replace で使われているか確認', '§2-15', cs=True,
  ex=r'preg_replace\s*\(\s*[\'"]')
R('PHP55-03', 'PHP5.5/7.2', '高', 'A', 'PD',
  r'(?<![\w$])(?:mcrypt_\w+|mdecrypt_generic)\s*\(|\bMCRYPT_\w+',
  'ext/mcrypt', '7.2で削除(Fatal)。既存暗号文の復号互換に注意（ゼロパディング、RIJNDAEL_256はOpenSSLに無い）',
  'openssl_encrypt/decrypt へ。RIJNDAEL_256/Blowfish/DES は復号→AESで再暗号化', '§2-16 §4-8',
  doc=r'(?<![\w$])(?:mcrypt_\w+|MCRYPT_\w+|mcrypt)(?![\w])')
R('PHP55-04', 'PHP5.5', '中', 'A', 'PD',
  FN(r'apc_\w+'),
  'APC ユーザキャッシュ API (apc_*)', 'Fatal error', 'APCu の apcu_* へ', '§2-17',
  doc=r'(?<![\w$])apc_\w+')
R('PHP55-05', 'PHP5.5', '低', 'A', 'P',
  FN('php_logo_guid|php_egg_logo_guid|php_real_logo_guid|zend_logo_guid'),
  'ロゴGUID関数', 'Fatal error', '削除', '§2-19')

# ============================ PHP 5.6 ======================================
R('PHP56-01', 'PHP5.6/7.0', '高', 'A', 'PD',
  r'\$HTTP_RAW_POST_DATA\b', '$HTTP_RAW_POST_DATA', '7.0で削除。入力が取得できない',
  "file_get_contents('php://input')", '§2-20 §3-3')
R('PHP56-02', 'PHP5.6/7.0', '中', 'B', 'P',
  r'''=>\s*['"]@|CURLOPT_SAFE_UPLOAD|CURLOPT_POSTFIELDS[^;]*['"]@''',
  "cURL の '@ファイル' アップロード", 'ファイルでなく文字列が送信される（サイレント）', 'CURLFile へ', '§2-27')
R('PHP56-03', 'PHP5.6', '中', 'B', 'PD',
  FN('mb_internal_encoding|mb_http_output|mb_http_input|mb_regex_encoding|mb_language|mb_detect_order|iconv_set_encoding'),
  'mbstring/iconv のエンコーディング設定箇所', 'default_charset(UTF-8既定)との整合。ini側 mbstring.* は非推奨',
  '内部エンコード方針（UTF-8統一）に合わせて設定値を確認', '§2-22 §8-4')
R('PHP56-05', 'PHP5.6/8.0', '中', 'A', 'P',
  r'(?<![\w>:$])crypt\s*\(\s*[^,()]+(?:\([^()]*\))?\s*\)',
  'crypt() の salt 省略', '8.0で ArgumentCountError', 'password_hash() へ、または salt を明示', '§2-26')
R('PHP56-06', 'PHP5.6', '中', 'B', 'P',
  r'''fsockopen\s*\(\s*['"](?:ssl|tls)://|file_get_contents\s*\(\s*['"]https://|new\s+SoapClient|stream_socket_client\s*\(\s*['"](?:ssl|tls)''',
  'SSL/TLS ストリーム接続', 'ピア証明書検証が既定有効。自己署名・古いCAで接続失敗',
  '接続先の証明書を確認。CAを配置', '§2-23')

# ============================ PHP 7.0 ======================================
R('PHP70-01', 'PHP7.0', '高', 'A', 'PD',
  FN('ereg|eregi|ereg_replace|eregi_replace|split|spliti|sql_regcase'),
  'ext/ereg (ereg/split 系)', 'Fatal error（未定義関数）',
  'preg_match / preg_replace / preg_split / explode へ（デリミタ・エスケープ差に注意）', '§3-2',
  doc=r'(?<![\w$>:])(?:ereg|eregi|ereg_replace|eregi_replace|spliti|sql_regcase)(?![\w])|(?<![\w$>:.])split\s*\(')
R('PHP70-02', 'PHP7.0', '中', 'A', 'P',
  r'<%(?!@)|<script\s+language\s*=\s*["\']?php', 'ASPタグ <% / <script language="php">',
  'PHPとして解釈されずソースがそのまま出力される', '<?php へ', '§3-5')
R('PHP70-03', 'PHP7.0', '中', 'A', 'PD',
  FN('call_user_method|call_user_method_array|set_socket_blocking|mcrypt_generic_end|datefmt_set_timezone_id'),
  '7.0 削除関数', 'Fatal error', 'call_user_func / stream_set_blocking 等へ', '§3-6')
R('PHP70-04', 'PHP7.0', '低', 'A', 'P',
  r'=\s*&\s*new\b', '$a = &new Foo', 'Parse error', '& を削除', '§3-17')
R('PHP70-05', 'PHP7.0', '高', 'B', 'P',
  r'\$\$\w+\s*\[|\$\$\w+\s*->|->\s*\$\w+\s*\[|::\s*\$\w+\s*\[[^\]]*\]\s*\(',
  '可変変数/可変プロパティ + 添字（統一変数構文）',
  '評価順が左→右に変わり別の変数・プロパティを参照する（サイレント）',
  '旧の意味を保つには ${$a[\'b\']} / $obj->{$a[\'b\']} と {} で明示', '§3-9')
R('PHP70-06', 'PHP7.0', '中', 'B', 'P',
  r'catch\s*\(\s*\\?Exception\s+\$|set_exception_handler\s*\(',
  'catch (Exception) / 例外ハンドラ', '旧Fatalの多くが Error 例外になり Exception では捕捉されない',
  '最上位の捕捉は Throwable に。ハンドラの型宣言も Throwable', '§3-10')
R('PHP70-08', 'PHP7.0+', '高', 'A', 'P',
  r'\b(?:class|interface|trait)\s+(?:bool|int|float|string|null|true|false|resource|object|mixed|numeric|void|iterable|never|enum|match|fn|readonly)\b',
  '予約語と同名のクラス/インターフェイス', 'Fatal error', 'リネーム', '§3-13 §4-20')
R('PHP70-08b', 'PHP7.0+', '高', 'A', 'P',
  r'^\s*(?:abstract\s+|final\s+)*class\s+(?:Error|TypeError|ParseError|ArgumentCountError|ArithmeticError|AssertionError|'
  r'DivisionByZeroError|Throwable|Stringable|Attribute|WeakMap|WeakReference|ValueError|UnhandledMatchError|PhpToken|'
  r'Fiber|ReturnTypeWillChange|JsonException|Generator|SessionHandler|Transliterator|DateTimeImmutable|DateTimeInterface|'
  r'CURLFile|JsonSerializable|CallbackFilterIterator|Random|Override|Deprecated|NoDiscard|SensitiveParameter|IntlChar)\b',
  '組込みクラスと同名のクラス定義', 'Fatal error: Cannot declare class（名前空間なしの場合）', 'リネームまたは名前空間化', '§5-23')
R('PHP70-10', 'PHP7.0', '中', 'B', 'P',
  r'''['"]0x[0-9a-f]+['"]''', '16進表記の文字列 "0x1A"', '数値文字列として扱われなくなる（is_numeric false、比較・計算結果が変わる）',
  'hexdec() を明示', '§3-12')
R('PHP70-11', 'PHP7.0', '低', 'A', 'P',
  r'"[^"]*\\u\{', '二重引用符内の \\u{', 'Unicodeエスケープとして解釈され Parse error', '\\\\u{ または単一引用符へ', '§3-18', cs=True)
R('PHP70-13', 'PHP7.0/8.0', '低', 'A', 'P',
  r'''setlocale\s*\(\s*['"]LC_''', 'setlocale のカテゴリ文字列指定', '8.0で削除(TypeError)', "LC_ALL 等の定数へ", '§3-23')
R('PHP70-14', 'PHP7.0', '低', 'A', 'P', r'\bglobal\s+\$\$', 'global $$var', '可変変数の解釈変更', 'global ${$foo->bar} と明示', '§3-9')
R('PHP70-19', 'PHP7.0', '低', 'A', 'P',
  r'''password_hash\s*\([^;]*['"]salt['"]''', 'password_hash の salt オプション', '非推奨→8.0で無視', 'salt 指定を削除', '§3-23')

# ============================ PHP 7.1 ======================================
R('PHP71-01', 'PHP7.1', '中', 'B', 'P',
  r'(?<![\w>:$])(?:mt_srand|srand)\s*\(\s*[^)\s]', 'シード固定の乱数 (srand/mt_srand)',
  '同一シードの乱数列が変わる（抽選再現・テスト）', '再現が必要な結果はDB保存。暫定 MT_RAND_PHP（8.3非推奨）', '§4-4')
R('PHP71-02', 'PHP7.2/8.0', '中', 'A', 'P', r'\(\s*unset\s*\)\s*\$', '(unset) キャスト', '8.0で削除', 'null 代入へ', '§4-10')
R('PHP71-03', 'PHP7.1/8.0', '中', 'A', 'P',
  r'''mb_eregi?_replace\s*\([^;]*,\s*['"][a-z]*e[a-z]*['"]\s*\)''', "mb_ereg_replace の 'e' オプション", '8.0で削除',
  'mb_ereg_replace_callback へ', '§4-10')
R('PHP71-05', 'PHP7.1/8.0', '中', 'A', 'PD', FN('png2wbmp|jpeg2wbmp|ldap_sort'), '7.x非推奨→8.0削除関数', 'Fatal error', '代替実装へ', '§4-10')

# ============================ PHP 7.2 ======================================
R('PHP72-01', 'PHP7.2/8.0', '高', 'C', 'P',
  FN('count|sizeof'), 'count()/sizeof()', 'null/false/文字列を渡すと 8.0 で TypeError（クエリ失敗時の false 等）',
  '引数が必ず配列/Countableか確認。is_countable()、(array)キャスト', '§4-13')
R('PHP72-02', 'PHP7.2/8.0', '高', 'A', 'PD', r'function\s+__autoload\s*\(', '__autoload()', '8.0で削除。クラスが読み込まれず Fatal',
  'spl_autoload_register() へ', '§4-14', doc=BARE('__autoload'))
R('PHP72-03', 'PHP7.2/8.0', '高', 'A', 'PD', FN('create_function'), 'create_function()', '8.0で削除(Fatal)', 'クロージャへ', '§4-15',
  doc=BARE('create_function'))
R('PHP72-04', 'PHP7.2/8.0', '高', 'A', 'P', FN('each'), 'each()', '8.0で削除(Fatal)', 'foreach へ', '§4-16')
R('PHP72-05', 'PHP7.2/8.0', '中', 'A', 'PD', r'\$php_errormsg\b', '$php_errormsg', '8.0で削除（未定義変数）', 'error_get_last()', '§4-18')
R('PHP72-06', 'PHP7.2/8.0', '中', 'A', 'P',
  r'(?<![\w>:$])(?:mb_)?parse_str\s*\(\s*[^,()]+(?:\([^()]*\))?[^,()]*\)\s*;',
  'parse_str() の第2引数省略', '8.0で ArgumentCountError', 'parse_str($s, $out)', '§4-19')
R('PHP72-07', 'PHP7.2/8.0', '中', 'A', 'P', r'''(?<![\w>:$])assert\s*\(\s*['"]''', 'assert() の文字列引数', '8.0で評価されなくなる', '式で記述', '§4-19')
R('PHP72-08', 'PHP7.2/8.0', '中', 'A', 'PD', FN('gmp_random|read_exif_data'), '7.2非推奨→8.0削除関数', 'Fatal error', 'gmp_random_bits / exif_read_data', '§4-19')
R('PHP72-12', 'PHP7.2', '低', 'A', 'P',
  r'''hash_(?:hmac|init|pbkdf2)\s*\(\s*[r'"](?:crc32b?|adler32|fnv\w*|joaat)['"]''', 'HMAC に非暗号学的ハッシュ', 'Warning + false', 'sha256 等へ', '§4-23')

# ============================ PHP 7.3 ======================================
R('PHP73-01', 'PHP7.3', '高', 'B', 'P',
  r'preg_\w+\s*\(.*\[[^\]]*\\[wdsWDS]-[^\]\\]', 'PCRE2: 文字クラス内の \\w- 等のハイフン',
  '正規表現がコンパイルエラーになり preg_* が false（バリデーションが常に失敗/通過）',
  'ハイフンを末尾へ移動またはエスケープ', '§4-27', cs=True)
R('PHP73-01b', 'PHP7.3', '中', 'C', 'P', r'(?<![\w>:$])preg_\w+\s*\(', 'preg_* 全般（PCRE2 移行）',
  '不正エスケープ等の厳格化で既存パターンがエラーになりうる', '全パターンを新環境でコンパイルテスト', '§4-27')
R('PHP73-04', 'PHP7.3/8.0', '中', 'A', 'P', r'\bdefine\s*\([^;]*,\s*true\s*\)\s*;', '大文字小文字非依存の定数 define(..., true)',
  '8.0で第3引数無視（別表記での参照が未定義定数 Error）', '参照側の表記を統一', '§4-30')
R('PHP73-05', 'PHP7.3/8.0', '中', 'A', 'PD',
  r'FILTER_FLAG_(?:SCHEME|HOST)_REQUIRED|' + FN(r'fgetss|image2wbmp|mbereg\w*|mbsplit|mbregex_encoding') + r'|string\.strip_tags',
  '7.3非推奨→8.0削除（fgetss, mbereg別名 等）', 'Fatal error', 'mb_ereg* 正式名、strip_tags(fgets())', '§4-30')

# ============================ PHP 7.4 ======================================
R('PHP74-01', 'PHP7.4/8.0', '高', 'B', 'P',
  r'''\$\w+(?:\[[^\]]*\]|->\w+)*\{\s*(?:-?\d+|\$\w+(?:\s*[-+]\s*\d+)?|['"][\w-]+[r'"]|\w+\([^)]*\)\s*-\s*\d+)\s*\}''',
  '波括弧オフセット $str{0}', '8.0で Parse error（ファイル全体がコンパイル不能）', '[ ] へ置換（文字列内の "{$a}" 補間は対象外）', '§4-33')
R('PHP74-02', 'PHP7.4/8.0', '高', 'B', 'P',
  r'\?[^?:;]+:[^?:;(]+\?[^?:;]+:', '括弧なしのネスト三項演算子', '8.0で Fatal（コンパイルエラー）', '括弧で結合を明示', '§4-34',
  ex=r'\bcase\b')
R('PHP74-03', 'PHP7.4/8.0', '高', 'B', 'P',
  r'''(?<![\d.])\.\s*(?:\$[\w>\[\]'"-]+|\d+)\s*[-+]\s*(?:\$\w|\d)''', '"." と "+"/"-" の混在',
  '8.0で優先順位が変わり結果が変わる（サイレント）', '括弧で明示', '§4-35 §5-13')
R('PHP74-04', 'PHP7.4/8.0', '中', 'A', 'P', r'''(?<![\w>:$])(?:implode|join)\s*\(\s*\$\w+\s*,\s*['"]''', 'implode() の引数逆順', '8.0で TypeError', '(glue, array) の順へ', '§4-37')
R('PHP74-05', 'PHP7.4/8.0', '中', 'A', 'P', r'\(\s*real\s*\)\s*[\$\w(]|' + FN('is_real'), '(real) / is_real()', '8.0で削除', '(float) / is_float()', '§4-39')
R('PHP74-06', 'PHP7.4/8.0', '中', 'A', 'PD', FN('money_format|hebrevc|convert_cyr_string|ezmlm_hash|restore_include_path'),
  'money_format 等', '8.0で削除(Fatal)', 'NumberFormatter / number_format 等', '§4-40',
  doc=BARE('money_format|hebrevc|convert_cyr_string|ezmlm_hash|restore_include_path'))
R('PHP74-09', 'PHP7.4', '中', 'B', 'PD',
  r'''(?:require|include)(?:_once)?\s*\(?\s*[r'"](?:PEAR|DB|MDB2|Mail|Auth|Log|Pager|Cache/Lite|HTTP/Request2?|Net/\w+|HTML/\w+|XML/\w+|Services/\w+|Spreadsheet/\w+|File/\w+|Date|Var_Dump)(?:/[\w/]+)?\.php|'''
  r'(?<![\w$])(?:PEAR|DB|MDB2)::(?:isError|connect|factory|singleton)|' + FN(r'wddx_\w+|recode_\w+|ibase_\w+'),
  'PEAR ライブラリ / 削除拡張 (wddx, recode, interbase)', 'PEARは既定で同梱されない。PEAR::DB/MDB2 は PHP 8 非対応',
  'Composer パッケージ / PDO へ移行', '§4-46 §8-12')

# ============================ PHP 8.0 ======================================
R('PHP80-01', 'PHP8.0', '高', 'C', 'P',
  r'''(?<![=!<>])[!=]=(?!=)\s*(?:-?\d+\b|''|"")|(?:\b\d+|''|"")\s*[!=]=(?!=)''',
  '数値/空文字との緩い比較 (==, !=)', '0 == "abc" が false になる等、数値と非数値文字列の比較結果が変わる（サイレント）',
  '比較対象の型を確認し === / 明示キャストへ', '§5-1')
R('PHP80-02', 'PHP8.0', '高', 'C', 'P',
  r'(?<![\w>:$])(?:in_array|array_search)\s*\((?![^;]*,\s*true\s*\))', 'in_array/array_search（strictなし）',
  '緩い比較の規則変更の影響を受ける', '第3引数 true を指定', '§5-1')
R('PHP80-03', 'PHP8.0', '中', 'C', 'P', r'\bswitch\s*\(', 'switch 文', 'case は緩い比較。数値と文字列 case の混在で分岐が変わる', '対象と case の型を揃える', '§5-1')
R('PHP80-04', 'PHP8.0+', '高', 'B', 'P', FN('is_resource|get_resource_type'), 'is_resource() 判定',
  'curl/GD/xml/socket/openssl 等がオブジェクト化され常に false（サイレント）', '!== false / instanceof 判定へ', '§5-22 §6-15')
R('PHP80-05', 'PHP8.0', '中', 'A', 'P',
  r'error_reporting\s*\(\s*\)\s*(?:===?|!==?)\s*0|\b0\s*(?:===?|!==?)\s*error_reporting\s*\(\s*\)|!\s*error_reporting\s*\(\s*\)',
  '@ 抑止判定 (error_reporting() == 0)', '@ 中の error_reporting() が 0 でなく 4437 を返し、抑止していた警告で例外等が発生',
  'if (!(error_reporting() & $errno)) return false;', '§5-12')
R('PHP80-06', 'PHP8.0', '中', 'A', 'P', r'^\s*#\[|;\s*#\[', '#[ で始まるコメント', '属性構文として解釈され Parse error', '// コメントへ', '§5-16')
R('PHP80-07', 'PHP8.0+', '中', 'B', 'P',
  r'function\s+&?\s*(?:str_contains|str_starts_with|str_ends_with|get_debug_type|fdiv|get_resource_id|array_is_list|'
  r'array_key_first|array_key_last|is_countable|is_iterable|array_find|array_find_key|array_any|array_all|array_first|'
  r'array_last|json_validate|mb_trim|mb_ltrim|mb_rtrim|mb_str_pad|mb_ucfirst|mb_lcfirst|mb_str_split|mb_chr|mb_ord|mb_scrub|'
  r'str_increment|str_decrement|random_int|random_bytes|intdiv|password_hash|password_verify|password_needs_rehash|'
  r'hash_equals|array_column|boolval|json_last_error_msg|hex2bin|http_response_code|getallheaders|array_walk_recursive|'
  r'get_error_handler|get_exception_handler|iterator_apply|lcfirst|hrtime|net_get_interfaces|sodium_\w+)\s*\(',
  '後発の組込み関数と同名のユーザ定義関数', 'Fatal error: Cannot redeclare（function_exists ガードが無い場合）',
  'function_exists() ガードの有無を確認、または削除', '§5-23 §7-6 §7-42')
R('PHP80-08', 'PHP8.0', '中', 'A', 'P', r'(?<![\w>:$])(?:gm)?mktime\s*\(\s*\)', '引数なしの mktime()', 'ArgumentCountError', 'time()', '§5-18')
R('PHP80-09', 'PHP8.0', '中', 'A', 'PD', FN(r'xmlrpc_\w+|zip_open|zip_read|zip_entry_\w+|libxml_disable_entity_loader'),
  'xmlrpc 拡張削除 / 手続き型ZIP API 非推奨', 'xmlrpc_* は Fatal（PECLへ移動）', '代替ライブラリ / ZipArchive', '§5-19 §5-20')
R('PHP80-10', 'PHP8.0', '中', 'A', 'P', r'\bFILTER_SANITIZE_MAGIC_QUOTES\b|\bINPUT_(?:SESSION|REQUEST)\b', '削除された filter 定数', 'Error（未定義定数）', 'FILTER_SANITIZE_ADD_SLASHES 等', '§5-19')
R('PHP80-14', 'PHP8.0', '高', 'B', 'PD', r'\bnew\s+\\?PDO\s*\(|PDO::ERRMODE_(?:SILENT|WARNING)|PDO::ATTR_ERRMODE',
  'PDO 接続・エラーモード', '既定が ERRMODE_EXCEPTION。戻り値false判定のコードが PDOException で停止。8.1 で数値がネイティブ型で返る',
  '例外前提に書き換え。型は ATTR_STRINGIFY_FETCHES で互換維持可', '§5-27 §6-3 §14')
R('PHP80-14b', 'PHP8.0', '中', 'B', 'P', r'->\s*(?:errorInfo|errorCode)\s*\(', 'PDO errorInfo()/errorCode() による判定', '例外が先に飛ぶため到達しない', 'try/catch へ', '§5-27')
R('PHP80-15', 'PHP8.0', '中', 'C', 'P', r'(?<![\w>:$])u[ak]?sort\s*\(', 'usort 系コールバック', 'bool を返すコールバックは非推奨。安定ソート化で同値要素の順序が変わる', '<=> で -1/0/1 を返す', '§5-5')
R('PHP80-16', 'PHP8.0', '中', 'C', 'P', r'@\s*(?:\$\w|\\?[a-z_]\w*\s*\(|new\b|include|require)', '@ エラー抑止演算子', 'Fatal系は抑止されなくなる。抑止に依存した処理の確認', '事前チェックへ置換', '§5-12')
R('PHP80-20', 'PHP8.0', '高', 'C', 'P', r'(?<![\w>:$])(?:mysqli_fetch_\w+|mysqli_num_rows|mysqli_free_result|mysqli_data_seek)\s*\(',
  'mysqli 結果取得（false 渡し）', '失敗したクエリの false を渡すと TypeError', 'クエリ結果の判定/例外モード前提へ', '§5-28 §14')

# ============================ PHP 8.1 ======================================
R('PHP81-01', 'PHP8.1', '高', 'B', 'P',
  r'(?<![\w>:$])(?:strlen|trim|ltrim|rtrim|htmlspecialchars|htmlentities|str_replace|strpos|stripos|substr|strtolower|strtoupper|'
  r'urlencode|rawurlencode|urldecode|addslashes|stripslashes|strip_tags|nl2br|explode|preg_match|preg_replace|strtotime|'
  r'mb_strlen|mb_substr|mb_convert_encoding|mb_convert_kana|mb_strimwidth|strcmp|md5|sha1|json_decode|base64_decode|'
  r'mysqli_real_escape_string|ctype_\w+|is_numeric|intval)\s*\((?:[^;]*,)?\s*\$_(?:GET|POST|REQUEST|COOKIE|SERVER|SESSION|FILES)\[[^\]]+\]\s*[,)]',
  '組込み関数へスーパーグローバルを直接渡している', '未定義キー→null→「null を渡すのは非推奨」(9.0で TypeError)。Warning も発生',
  "?? '' で既定値を与える", '§6-1')
R('PHP81-02', 'PHP8.1', '高', 'B', 'PD', r'(?<![\w>:$])(?:mysqli_connect|mysqli_real_connect|mysqli_init|mysqli_report)\s*\(|\bnew\s+\\?mysqli\s*\(',
  'mysqli 接続・レポートモード', '既定が例外モード(MYSQLI_REPORT_ERROR|STRICT)。接続失敗・SQLエラーが mysqli_sql_exception',
  '例外前提へ。暫定 mysqli_report(MYSQLI_REPORT_OFF)', '§6-2 §14')
R('PHP81-02b', 'PHP8.1', '中', 'B', 'P',
  r'(?<![\w>:$])(?:mysqli_error|mysqli_errno|mysqli_connect_error|mysqli_connect_errno)\s*\(|->\s*(?:connect_error|connect_errno)\b',
  'mysqli のエラー戻り値判定', '例外が先に飛ぶため到達しない。エラー時フロー（メンテ画面等）が変わる', 'try/catch へ', '§6-2')
R('PHP81-03', 'PHP8.1', '中', 'B', 'P', r'''[!=]==\s*['"]-?\d+['"]|['"]-?\d+['"]\s*[!=]==''', '数字文字列との厳密比較 (=== "1")',
  'PDO がネイティブ型(int)を返すと不一致になる', '型方針を統一（STRINGIFY_FETCHES または int 比較）', '§6-3 §14')
R('PHP81-04', 'PHP8.1', '中', 'B', 'P',
  r'\bimplements\s+[^{]*\b(?:ArrayAccess|Iterator|IteratorAggregate|Countable|JsonSerializable|SessionHandlerInterface|Serializable)\b',
  '組込みインターフェイスの実装', '戻り値型未宣言で Deprecated。Serializable 単独実装も非推奨',
  '戻り値型を付与（旧PHP併用時は #[\\ReturnTypeWillChange]）', '§6-4 §6-13')
R('PHP81-06', 'PHP8.1', '中', 'A', 'PD',
  FN(r'strftime|gmstrftime|strptime|date_sunrise|date_sunset|mhash\w*|odbc_result_all') +
  r'|\bFILE_(?:BINARY|TEXT)\b|\bFILTER_SANITIZE_(?:STRING|STRIPPED)\b|PDO::FETCH_SERIALIZE',
  '8.1 非推奨（strftime, FILTER_SANITIZE_STRING 等）', 'Deprecated（9.0で削除）',
  'date()/IntlDateFormatter、htmlspecialchars() 等', '§6-6 §6-7 §6-8',
  doc=BARE('strftime|gmstrftime|FILTER_SANITIZE_STRING'))
R('PHP81-07', 'PHP8.1', '低', 'A', 'P', r'\$GLOBALS\s*=[^=]|=\s*&\s*\$GLOBALS\s*;|array_\w+\s*\(\s*\$GLOBALS\s*[,)]', '$GLOBALS 全体の書き換え/参照', 'コンパイルエラー', '個別キー操作へ', '§6-10')
R('PHP81-09', 'PHP8.1', '低', 'A', 'P', r'\bMYSQLI_REFRESH_SLAVE\b|\bdriver_version\b|mysqli_get_client_info\s*\(\s*\$|parent::init\s*\(', 'mysqli 8.1 非推奨API', 'Deprecated', '置換', '§6-14')
R('PHP81-12', 'PHP8.1+', '中', 'B', 'PD',
  r'''(?<![\w>:$])(?:mb_detect_encoding|mb_convert_variables)\s*\(|mb_convert_encoding\s*\([^;]*['"](?:auto|[^'"]*,[^'"]*)['"]''',
  '文字コード自動判定', '判定アルゴリズム変更で検出結果が旧版と変わる', '入力エンコードを明示し自動判定をやめる', '§6-17')
R('PHP81-12b', 'PHP8.1+', '中', 'B', 'P',
  r'''['"](?:SJIS|Shift_JIS|sjis|EUC-JP|eucjp|EUCJP|JIS|ISO-2022-JP)['"]''', "エンコード名 'SJIS'/'EUC-JP' 指定",
  '機種依存文字(①㈱髙 等)は SJIS-win/eucJP-win でないと化ける。変換テーブル修正で結果が変わる場合あり',
  'Windows由来データは SJIS-win(CP932)/eucJP-win を指定し回帰テスト', '§13-2 §13-12')
R('PHP81-13', 'PHP8.1', '中', 'A', 'P',
  r'''openssl_(?:en|de)crypt\s*\([^;]*[r'"](?:bf|blowfish|des|rc4|rc2|cast5|idea)[-\w]*['"]''', 'OpenSSL レガシー暗号 (BF/DES/RC4)',
  'OpenSSL 3 環境で false（Unknown cipher）', 'AES で再暗号化。暫定 legacy provider', '§6-18')

# ============================ PHP 8.2 ======================================
R('PHP82-02', 'PHP8.2', '中', 'A', 'P', r'"[^"]*\$\{[a-z_(]', '"${var}" 形式の文字列補間', 'Deprecated', '"{$var}" へ', '§6-21')
R('PHP82-03', 'PHP8.2/8.4', '中', 'A', 'PD', r'\bMYSQLI_OPT_RECONNECT\b|(?<![\w>:$])mysqli_ping\s*\(|->\s*ping\s*\(\s*\)|mysqli\.reconnect',
  'mysqli 自動再接続 / ping', 'mysqli.reconnect 削除(8.2)、mysqli_ping 非推奨(8.4)。長時間バッチが 2006 gone away で停止',
  '接続ラッパで 2006/2013 を捕捉して再接続', '§6-22 §7-16 §14')
R('PHP82-04', 'PHP8.2', '中', 'A', 'P',
  r'''mb_\w+\s*\([^;]*['"](?:HTML-ENTITIES|BASE64|UUENCODE|QPrint|Quoted-Printable|HTML)['"]''', "mbstring の 'HTML-ENTITIES'/'BASE64' 等",
  'Deprecated', 'htmlentities / mb_encode_numericentity / base64_encode', '§6-23')
R('PHP82-05', 'PHP8.2', '低', 'A', 'PD', FN('utf8_encode|utf8_decode'), 'utf8_encode/utf8_decode', 'Deprecated', 'mb_convert_encoding', '§6-24')
R('PHP82-06', 'PHP8.2', '低', 'A', 'P', r'''[r'"](?:self|parent|static)::\w+['"]''', '"self::m" 形式の callable', 'Deprecated', '第一級callable / 配列形式', '§6-26')
R('PHP82-07', 'PHP8.2', '低', 'B', 'P', r'(?<![\w>:$])setlocale\s*\(', 'setlocale()', 'strtolower 等がロケール非依存化。strftime 非推奨とも関連', 'ロケール依存処理の有無を確認', '§6-25')

# ============================ PHP 8.3 ======================================
R('PHP83-01', 'PHP8.3', '低', 'A', 'P',
  r'(?<![\w>:$])get_(?:parent_)?class\s*\(\s*\)|\bMT_RAND_PHP\b|' + FN('assert_options') + r'|ldap_connect\s*\([^,()]+,',
  '8.3 非推奨（引数なし get_class 等）', 'Deprecated', 'static::class / self::class 等', '§7-1')

# ============================ PHP 8.4 ======================================
R('PHP84-01', 'PHP8.4', '高', 'A', 'P',
  r'\bfunction\b[^;{]*?(?<![?|$\w\\])(?!(?:mixed|null)\b)[a-z_\\][\w\\]*\s+&?\$\w+\s*=\s*null\b|'
  r'^\s*(?!(?:mixed|null|return|static|public|private|protected|var|global|const|echo|new|case|print|else|and|or)\b)[a-z_\\][\w\\]*\s+&?\$\w+\s*=\s*null\s*[,)]',
  '暗黙の nullable 引数 (Type $x = null)', 'Deprecated（9.0でエラー）', '?Type $x = null へ（Rector で自動置換可）', '§7-8')
R('PHP84-02', 'PHP8.4', '中', 'A', 'PID', r'\bE_STRICT\b', 'E_STRICT 定数', 'Deprecated（定数非推奨・レベル削除）', 'E_STRICT を削除', '§7-9', cs=True)
R('PHP84-03', 'PHP8.4', '中', 'B', 'PD', FN('session_set_save_handler'), 'session_set_save_handler()', 'コールバック6〜8個を渡す形式が非推奨',
  'SessionHandlerInterface 実装オブジェクトを渡す', '§7-10', doc=BARE('session_set_save_handler'))
R('PHP84-04', 'PHP8.4', '中', 'A', 'P', FN('xml_set_object'), 'xml_set_object()', 'Deprecated', '[$this, "method"] / クロージャ', '§7-11')
R('PHP84-05', 'PHP8.4', '中', 'A', 'P', r'(?:trigger_error|user_error)\s*\([^;]*\bE_USER_ERROR\b', 'trigger_error(..., E_USER_ERROR)', 'Deprecated', '例外を throw', '§7-12')
R('PHP84-06', 'PHP8.4', '中', 'A', 'P',
  r'(?<![\w>:$])(?:mysqli_kill|mysqli_refresh)\s*\(|\bMYSQLI_(?:REFRESH_\w+|STORE_RESULT_COPY_DATA|SET_CHARSET_DIR|STMT_ATTR_PREFETCH_ROWS|CURSOR_TYPE_FOR_UPDATE|CURSOR_TYPE_SCROLLABLE|TYPE_INTERVAL)\b',
  'mysqli 8.4 非推奨API', 'Deprecated', 'SQL の KILL / FLUSH へ', '§7-16')
R('PHP84-07', 'PHP8.4', '中', 'C', 'P', r'(?<![\w>:$])round\s*\(', 'round()', '内部実装変更で境界値の結果が変わりうる（金額・税計算）', '整数演算/BCMath。回帰テスト', '§7-14')
R('PHP84-08', 'PHP8.4', '低', 'A', 'P', FN('lcg_value|stream_context_set_options') + r'|\bSUNFUNCS_RET_\w+|\bDOM_PHP_ERR\b', '8.4 非推奨関数/定数', 'Deprecated', '置換', '§7-18')

# ============================ PHP 8.5 ======================================
R('PHP85-01', 'PHP8.5', '中', 'A', 'P', r'\(\s*(?:integer|boolean|double|binary)\s*\)\s*[\$\w(\'"\\-]', '非標準キャスト名 (integer)/(boolean)/(double)/(binary)',
  'Deprecated', '(int)/(bool)/(float)/(string) へ一括置換', '§7-23')
R('PHP85-03', 'PHP8.5', '中', 'A', 'P', r'function\s+__(?:sleep|wakeup)\s*\(', '__sleep()/__wakeup()', 'ソフト非推奨', '__serialize()/__unserialize() を追加', '§7-25')
R('PHP85-04', 'PHP8.5', '低', 'A', 'P', r'\bcase\s+[^:;?]+;|(?<![\w$>])default\s*;\s*$', 'case のセミコロン終端 (case 1;)', 'Deprecated', 'コロンへ', '§7-26', ex=r'\bwhen\b|\bend\b')
R('PHP85-05', 'PHP8.5', '低', 'A', 'P', FN('curl_close|curl_share_close|imagedestroy|finfo_close|xml_parser_free'), 'no-op 解放関数', 'Deprecated（8.0以降何もしない）', '呼び出し削除', '§7-30')
R('PHP85-06', 'PHP8.5', '低', 'A', 'P', r'''PDO::MYSQL_ATTR_\w+|['"]uri:''', 'PDO::MYSQL_ATTR_* 定数 / uri: DSN', 'Deprecated', 'Pdo\\Mysql::ATTR_*（8.4+）', '§7-32 §14')
R('PHP85-07', 'PHP8.5', '低', 'A', 'P', FN('mysqli_execute'), 'mysqli_execute() 別名', 'Deprecated', 'mysqli_stmt_execute()', '§7-33')
R('PHP85-08', 'PHP8.5', '低', 'A', 'P',
  r'\$http_response_header\b|' + FN('socket_set_timeout') + r'|\bMHASH_\w+|\bDATE_RFC7231\b|DateTimeInterface::RFC7231|->\s*setAccessible\s*\(',
  '8.5 非推奨（$http_response_header 等）', 'Deprecated', 'http_get_last_response_headers() / stream_set_timeout() 等', '§7-29 §7-34 §7-36')
R('PHP85-09', 'PHP8.5', '低', 'B', 'P', r'->\s*(?:attach|detach)\s*\(', 'attach()/detach()（SplObjectStorage の場合）', 'Deprecated', 'offsetSet()/offsetUnset()', '§7-35')

# ============================ PHP 環境・その他 ==============================
R('PHPX-01', '環境', '高', 'A', 'P', r'<\?(?!php\b|=|xml\b)', '短縮開始タグ <?', 'short_open_tag=Off で PHP として解釈されずソースが露出',
  '<?php へ置換（暫定 short_open_tag=On）', '§8-2')
R('PHPX-03', '環境', '低', 'B', 'P', r'\$_ENV\s*\[', '$_ENV 参照', 'variables_order=GPCS（production既定）で空', 'getenv() へ', '§8-10')
R('PHPX-04', '環境', '中', 'B', 'PD',
  FN(r'apache_(?:note|setenv|getenv|get_modules|get_version|request_headers|response_headers|lookup_uri|child_terminate)|virtual') +
  r'''|\$_SERVER\s*\[\s*['"](?:PHP_AUTH_USER|PHP_AUTH_PW|PATH_INFO|ORIG_PATH_INFO|PATH_TRANSLATED)['"]\s*\]''',
  'mod_php 依存 (apache_*, PHP_AUTH_*, PATH_INFO)', 'php-fpm 構成で使えない/値が変わる', 'Webサーバ設定で引き渡し、代替実装', '§8-7',
  doc=BARE('mod_php|apache_note|apache_setenv|PHP_AUTH_USER'))
R('PHPX-06', '環境', '低', 'B', 'P', FN('crc32|ip2long') + r'|\bPHP_INT_(?:MAX|SIZE)\b', '32bit/64bit 依存 (crc32, ip2long)',
  '64bit では負にならない。DB保存済みの符号付き値と不一致', "sprintf('%u') 等で正規化", '§3-24')
R('PHPX-08', '環境', '低', 'B', 'P', r'(?<![\w>:$])eval\s*\(', 'eval()', 'eval されるコードは本ツールで検査できない', '評価対象コードを別途確認', '')
R('PHPX-10', '環境', '中', 'B', 'PD',
  r'(?<![\w$\\])(?:Smarty|PHPExcel|PHPMailer|ADODB|ADONewConnection|NewADOConnection|TCPDF|FPDF|Zend_\w+|sfContext|CakePHP|AppController|CI_Controller|'
  r'Ethna_\w+|SC_[A-Z]\w+|Propel|Doctrine_\w+|PHPUnit_Framework\w*|Mail_mime|HTTP_Request2?|DB_DataObject|MDB2|HTML_QuickForm\w*|'
  r'Services_JSON|PclZip|phpThumb|Securimage|Qdmail|JpGraph|Net_\w+|Auth_\w+|Spreadsheet_Excel_\w+|simple_html_dom|Snoopy|nusoap\w*|xajax)(?![\w])',
  '外部ライブラリ/フレームワーク利用', '旧版は PHP 8 非対応の可能性が高い（ライブラリ自体が本表の非互換を含む）',
  'バージョンを特定し PHP 8.5 対応版の有無を確認', '§8-12')

_REMOVED_INI = (r'register_globals|register_long_arrays|magic_quotes_gpc|magic_quotes_runtime|magic_quotes_sybase|safe_mode\w*|'
                r'allow_call_time_pass_reference|always_populate_raw_post_data|asp_tags|track_errors|mbstring\.func_overload|'
                r'mbstring\.script_encoding|session\.hash_function|session\.hash_bits_per_character|session\.entropy_file|'
                r'session\.entropy_length|session\.bug_compat_42|session\.bug_compat_warn|y2k_compliance|define_syslog_variables|'
                r'highlight\.bg|zend\.ze1_compatibility_mode|xsl\.security_prefs|sql\.safe_mode|assert\.quiet_eval|detect_unicode|'
                r'mysql\.\w+|apc\.\w+|mssql\.\w+|sybct\.\w+|mcrypt\.\w+|mysqli\.reconnect|opcache\.fast_shutdown|xmlrpc_errors|'
                r'xmlrpc_error_number|gpc_order|mime_magic\.\w+')
_DEPR_INI = (r'mbstring\.internal_encoding|mbstring\.http_input|mbstring\.http_output|iconv\.input_encoding|iconv\.output_encoding|'
             r'iconv\.internal_encoding|filter\.default|filter\.default_flags|auto_detect_line_endings|session\.sid_length|'
             r'session\.sid_bits_per_character|assert\.\w+|report_memleaks|intl\.error_level|allow_url_include|'
             r'session\.use_trans_sid|session\.use_only_cookies|session\.trans_sid_tags|session\.trans_sid_hosts|session\.referer_check|'
             r'date\.default_latitude|date\.default_longitude|date\.sunrise_zenith|date\.sunset_zenith|register_argc_argv')
_CHECK_INI = (r'short_open_tag|default_charset|date\.timezone|error_reporting|display_errors|display_startup_errors|log_errors|'
              r'mbstring\.language|mbstring\.encoding_translation|mbstring\.detect_order|mbstring\.substitute_character|'
              r'zend\.multibyte|zend\.script_encoding|variables_order|request_order|max_input_vars|memory_limit|post_max_size|'
              r'upload_max_filesize|include_path|session\.save_handler|session\.save_path|session\.serialize_handler|'
              r'auto_prepend_file|auto_append_file|output_handler|output_buffering|disable_functions|open_basedir|sendmail_path|'
              r'precision|serialize_precision|pcre\.jit|mysqli\.default_socket|pdo_mysql\.default_socket|mysqli\.default_\w+')

R('INI-01', 'PHP5.4-8.x', '中', 'A', 'ID', INI(_REMOVED_INI), '削除済み php.ini ディレクティブ',
  '起動時に警告/無視。機能が無くなっている（register_globals, magic_quotes, func_overload 等は挙動に直結）',
  'php.ini-production をベースに新規作成し、当該行は移植しない。依存コードを修正', '§8-1',
  doc=r'(?<![\w.$])(?:' + _REMOVED_INI.replace(r'|mysql\.\w+', '').replace(r'|apc\.\w+', '') + r')(?![\w.])')
R('INI-01p', 'PHP5.4-8.x', '中', 'A', 'P', INISET(_REMOVED_INI), 'ini_set/ini_get で削除済みディレクティブを操作', '効果なし/false を返す', '依存処理を修正', '§8-1')
R('INI-02', 'PHP5.6-8.5', '低', 'A', 'ID', INI(_DEPR_INI), '非推奨 php.ini ディレクティブ', '起動時 Deprecated', 'default_charset 等の代替へ', '§8-1 §2-22',
  doc=r'(?<![\w.$])(?:' + _DEPR_INI + r')(?![\w.])')
R('INI-02p', 'PHP5.6-8.5', '低', 'A', 'P', INISET(_DEPR_INI), 'ini_set/ini_get で非推奨ディレクティブを操作', 'Deprecated', '代替設定へ', '§8-1')
R('INI-03', '環境', '中', 'B', 'ID', INI(_CHECK_INI), '値の再確認が必要な php.ini 設定', '既定値・推奨値が変わっている（文字コード、TZ、エラー表示、短縮タグ等）',
  '新 php.ini へ意図した値を明示的に移植', '§8-2〜§8-15', doc=r'(?<![\w.$])(?:' + _CHECK_INI + r')(?![\w.])')
R('INI-03p', '環境', '中', 'B', 'P', INISET(_CHECK_INI), '実行時の ini_set による重要設定', '設定の一元管理・既定値変更の影響確認', '値を確認', '§8')
R('INI-04', '環境', '中', 'A', 'ID', r'^\s*php_(?:admin_)?(?:value|flag)\b', '.htaccess / httpd.conf の php_value/php_flag', 'php-fpm では無効（mod_php 専用）',
  '.user.ini または FPM pool の php_admin_value へ', '§8-7', doc=BARE('php_value|php_flag|php_admin_value|php_admin_flag'))
R('INI-05', 'PHP8.5', '中', 'A', 'I', r'^\s*zend_extension\s*=\s*"?[\w./\\-]*opcache', 'zend_extension=opcache', '8.5 で OPcache 常時組込み。行が残ると Warning', '行を削除', '§7-39')
R('INI-06', 'PHP7.0+', '高', 'A', 'I',
  r'^\s*extension\s*=\s*"?(?:php_)?(?:mysql|ereg|mcrypt|apc|mssql|sybase_ct|wddx|recode|interbase|xmlrpc|imap|pspell|oci8|pdo_oci)(?:\.so|\.dll)?"?\s*(?:;.*)?$',
  '削除/PECL移動済み拡張のロード', '起動時エラー。当該拡張の関数が使えない', '代替拡張へ移行', '§3 §4-46')

# ============================ PHP-MySQL 連携 ================================
R('LNK-01', '連携', '高', 'A', 'PSD', r'\bSET\s+NAMES\b|\bSET\s+CHARACTER\s+SET\b', 'SET NAMES / SET CHARACTER SET の直接発行',
  'エスケープ関数に反映されない（SJIS系では5C問題によるSQLインジェクション）。utf8指定のままだと4バイト文字欠落',
  'mysqli_set_charset() / DSN charset= で指定', '§13-7 §14')
R('LNK-02', '連携', '高', 'A', 'PSCD',
  r'''(?:mysqli?_set_charset\s*\([^)]*|->\s*set_charset\s*\(\s*|charset\s*[=:]\s*|SET\s+NAMES\s+|default[-_]character[-_]set\s*=\s*)[r'"]?(?:sjis|ujis|utf8|utf8mb3|latin1|cp932|eucjpms|binary)(?![\w])''',
  '接続文字コードが utf8mb4 以外', 'sjis/ujis は機種依存文字が化ける。utf8(mb3) は絵文字・一部漢字が欠落。latin1 は誤宣言DBの疑い',
  'DB変換後に utf8mb4 へ統一。SJIS運用継続なら cp932', '§13-1〜§13-3 §13-7')
R('LNK-03', '連携', '高', 'B', 'PD', FN('addslashes'), 'addslashes() によるエスケープ', 'magic quotes 代替としてSQLに使用している場合、マルチバイトで不完全',
  'プリペアドステートメントへ', '§2-2 §13-7')
R('LNK-04', '連携', '低', 'B', 'P', r'''(?<![\w>:$])mysql_pconnect\s*\(|['"]p:|PDO::ATTR_PERSISTENT''', '永続接続', 'セッション状態（SET NAMES, sql_mode, 一時表）が残留', '必要性を再評価', '§14')
R('LNK-05', '連携', '中', 'C', 'P', r'(?<![\w>:$])(?:mysqli?_insert_id|mysqli?_affected_rows)\s*\(|->\s*(?:lastInsertId|insert_id|affected_rows|rowCount)\b|LAST_INSERT_ID\s*\(',
  'insert_id / affected_rows', '複数行INSERTのID連番前提は innodb_autoinc_lock_mode=2 で崩れる。affected_rows の意味（変更行/一致行）',
  'ID推定をやめ再SELECT。FOUND_ROWS フラグを確認', '§11-20 §14-15')
R('LNK-06', '連携', '中', 'A', 'PSD', r'\bLOAD\s+DATA\b|\bINTO\s+(?:OUTFILE|DUMPFILE)\b|\bMYSQLI_OPT_LOCAL_INFILE\b|MYSQL_ATTR_LOCAL_INFILE|\blocal[-_]infile\b',
  'LOAD DATA / INTO OUTFILE', 'secure_file_priv 既定で 1290、local_infile=OFF 既定で 1148/3948', '出力先ディレクトリ・許可設定を見直し', '§10-8 §14-13')
R('LNK-07', '連携', '低', 'B', 'P', r'(?<![\w>:$])mysqli_multi_query\s*\(|->\s*multi_query\s*\(|MYSQL_ATTR_MULTI_STATEMENTS', '複数ステートメント実行', 'インジェクション時の被害拡大', '無効化を検討', '§14-10')
R('LNK-08', '連携', '高', 'B', 'PSD', r'MYSQL_ATTR_INIT_COMMAND|\bMYSQLI_INIT_COMMAND\b|\bSET\s+(?:SESSION\s+|GLOBAL\s+|@@\w*\.?)?sql_mode\b|\bsql[-_]mode\s*=',
  '接続時初期化コマンド / sql_mode 設定', 'NO_AUTO_CREATE_USER 等を含むと 8.0 で接続自体が失敗。既定 sql_mode の厳格化',
  '設定値を確認・修正', '§10-1 §11-8 §14-12')
R('LNK-09', '連携', '高', 'A', 'P',
  FN(r'mysql_result|mysql_field_type|mysql_field_name|mysql_field_len|mysql_field_flags|mysql_field_table|mysql_list_\w+|mysql_db_query|'
     'mysql_unbuffered_query|mysql_tablename|mysql_db_name|mysql_create_db|mysql_drop_db|mysql_escape_string|mysql_client_encoding|mysql_fetch_field|mysql_data_seek'),
  'mysqli に単純対応が無い/挙動差の大きい mysql_* 関数', '機械置換不可。ヘルパ実装が必要（mysql_result, mysql_field_type の型名文字列 等）',
  'ガイド14節の対応表に従い個別実装', '§14')
R('LNK-10', '連携', '中', 'B', 'PSD', r'''['"]mysqli?://|\bmysql:host=|\bmysql:unix_socket=|\bmysql:dbname=''', 'DSN 文字列', 'charset 指定の有無、ソケットパス、ドライバ種別を確認',
  'DSN に charset=utf8mb4 を明示', '§14-2 §14-3')
R('LNK-11', '連携', '低', 'B', 'P', r'(?<![\w>:$])mysqli_ssl_set\s*\(|\bMYSQLI_CLIENT_SSL\b|MYSQL_ATTR_SSL_\w+', 'MySQL TLS 接続設定', 'TLSv1.2以上必須、証明書検証', 'CA配布・検証設定', '§14-11')
R('LNK-12', '連携', '中', 'B', 'P', r'(?<![\w>:$])mysqli?_(?:real_)?escape_string\s*\(|->\s*(?:real_escape_string|escape_string|quote)\s*\(',
  'エスケープ関数による SQL 組み立て', '接続charsetを API で設定していないと不完全。null 渡しは 8.1 で Deprecated', 'プリペアドステートメントへ', '§13-7 §14-7')

# ============================ MySQL: SQL ====================================
R('SQL55-01', 'MySQL5.5', '高', 'A', 'PSD', r'\bTYPE\s*=\s*(?:MyISAM|InnoDB|HEAP|MEMORY|ISAM|BDB|MERGE|MRG_MyISAM)\b', 'TYPE=エンジン 構文', '構文エラー', 'ENGINE= へ', '§9-2')
R('SQL55-02', 'MySQL5.5', '中', 'B', 'PSD', r'(?<![\w$])MyISAM(?![\w])', 'MyISAM テーブル', '既定エンジンは InnoDB。FULLTEXT/グループ別AUTO_INCREMENT/テーブルロック前提の挙動差。8.0 でパーティション不可',
  'InnoDB 化の可否を検討（COUNT(*) 性能、ロック、トランザクション）', '§9-1 §11-16')
R('SQL55-03', 'MySQL5.5', '中', 'A', 'PSD',
  r'\bSHOW\s+INNODB\s+STATUS\b|\bSHOW\s+TABLE\s+TYPES\b|\bSHOW\s+PLUGIN\b|\bLOAD\s+TABLE\b.*\bFROM\s+MASTER\b|\bBACKUP\s+TABLE\b|\bRESTORE\s+TABLE\b|\bSHOW\s+MUTEX\s+STATUS\b|\bSHOW\s+COLUMN\s+TYPES\b',
  '5.5 削除 SQL', '構文エラー', 'SHOW ENGINE INNODB STATUS 等へ', '§9-4')
R('SQL55-05', 'MySQL5.6+', '中', 'B', 'PSD', r'\bFULLTEXT\b|\bMATCH\s*\([^)]*\)\s*AGAINST\b', '全文検索 (FULLTEXT / MATCH AGAINST)',
  'InnoDB FTS は最小トークン長・ストップワード・スコアが MyISAM と異なる。日本語は ngram パーサが必要', 'WITH PARSER ngram で再インデックス、結果比較', '§9-19 §10-22')
R('SQL56-01', 'MySQL5.6/8.0', '高', 'B', 'SD', r'\btimestamp\b(?:\s*\(\d\))?\s*(?:NOT\s+NULL|NULL|DEFAULT|ON\s+UPDATE|COMMENT|,|$)', 'TIMESTAMP 列定義',
  'explicit_defaults_for_timestamp=ON(8.0既定)で暗黙の DEFAULT/ON UPDATE CURRENT_TIMESTAMP が付かない。NULL代入で現在時刻にならない（サイレント）',
  'DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP を明示', '§9-9 §11-18')
R('SQL56-02', 'MySQL5.6/5.7', '中', 'A', 'PSD', r'\b(?:INSERT|REPLACE)\s+DELAYED\b', 'INSERT DELAYED', '通常INSERT扱い→将来削除', 'DELAYED を削除', '§9-16')
R('SQL56-03', 'MySQL5.6', '中', 'A', 'SD', r'\bYEAR\s*\(\s*2\s*\)', 'YEAR(2) 型', '削除', 'YEAR(4) へ ALTER', '§9-16')
R('SQL56-04', 'MySQL5.6/8.0', '高', 'A', 'PSD', r'\bGRANT\b.*\bIDENTIFIED\s+BY\b|\bIDENTIFIED\s+BY\s+PASSWORD\b', 'GRANT ... IDENTIFIED BY / IDENTIFIED BY PASSWORD',
  '8.0 で構文エラー（GRANT によるユーザ作成不可）', 'CREATE USER → GRANT の2文へ', '§9-15 §10-9 §11-3')
R('SQL56-05', 'MySQL5.6+', '高', 'C', 'PSD', r'\bLIMIT\s+(?:\d+|\?|:\w+|\$|\{|%)', 'LIMIT（ページング）', '同順位行の並びが非決定。ページ間で行が重複/欠落（サイレント）',
  'ORDER BY に主キー等のタイブレークを追加', '§9-14')
R('SQL57-01', 'MySQL5.7/8.0', '高', 'A', 'PSD', r'\bGROUP\s+BY\s+(?:(?!\bORDER\s+BY\b|\bHAVING\b|\bLIMIT\b)[^;])*?\b(?:ASC|DESC)\b', 'GROUP BY col ASC/DESC', '8.0 で構文エラー',
  'ORDER BY を明示', '§10-7 §11-6')
R('SQL57-01b', 'MySQL5.7/8.0', '高', 'B', 'PSD', r'\bGROUP\s+BY\b', 'GROUP BY',
  'ONLY_FULL_GROUP_BY(5.7既定)で非集約列の SELECT が 1055 エラー。暗黙ソート削除(8.0)で並び順が変わる（サイレント）',
  'SELECT 列を集約/ANY_VALUE()、ORDER BY を明示', '§10-2 §10-7 §11-6')
R('SQL57-02', 'MySQL5.7', '高', 'A', 'PSD', r'0000-00-00', "ゼロ日付 '0000-00-00'", 'NO_ZERO_DATE(strict)で INSERT/DDL がエラー(1292/1067)。旧ダンプが import 不可',
  '列を NULL 許容にし NULL へ移行。PHP側の判定も修正', '§10-4')
R('SQL57-03', 'MySQL5.7/8.0', '高', 'B', 'PSD', r'\bFROM\s*\(\s*SELECT\b|\bJOIN\s*\(\s*SELECT\b', '派生テーブル (FROM (SELECT ...))',
  'derived_merge で内側 ORDER BY が無視され「グループ内最新行」イディオムが壊れる（サイレント）。UPDATE 対象表の参照は 1093',
  'ウィンドウ関数 ROW_NUMBER() / 相関サブクエリへ', '§10-6 §11-7')
R('SQL57-04', 'MySQL5.7/8.0', '高', 'B', 'PSD', r'(?<![\w$>:])(?:OLD_)?PASSWORD\s*\(|\bSET\s+PASSWORD\b', 'PASSWORD() / SET PASSWORD', '8.0 で関数削除',
  'ALTER USER ... IDENTIFIED BY。アプリ独自認証に使用している場合は password_hash 等へ移行', '§10-9 §11-9',
  ex=r'function\s+password|->\s*password\s*\(')
R('SQL57-05', 'MySQL5.7/8.0', '高', 'B', 'PSD', r'(?<![\w$>:])(?:ENCODE|DECODE|ENCRYPT|DES_ENCRYPT|DES_DECRYPT)\s*\(', 'ENCODE/DECODE/ENCRYPT/DES_* 関数',
  '8.0 で削除。暗号化済み列が復号不能になる', '8.0 移行前に平文化し AES_ENCRYPT / アプリ側暗号へ', '§10-10 §11-9',
  ex=r'function\s+(?:encode|decode|encrypt)\b|json_|base64_|url|html')
R('SQL57-06', 'MySQL5.7/8.0', '中', 'A', 'PSD',
  r'(?<![\w$>:.])(?:GeomFromText|GeomFromWKB|GeometryFromText|PointFromText|LineFromText|PolyFromText|AsText|AsBinary|AsWKT|AsWKB|GLength|MBREqual|'
  r'ExteriorRing|InteriorRingN|NumInteriorRings|NumGeometries|GeometryN|StartPoint|EndPoint|NumPoints|PointN|ConvexHull)\s*\(',
  '旧名の空間関数', '8.0 で FUNCTION does not exist', 'ST_ 接頭辞の関数へ', '§10-11')
R('SQL57-08', 'MySQL5.7/8.0', '中', 'A', 'PSD', r'information_schema\s*\.\s*`?(?:GLOBAL|SESSION)_(?:STATUS|VARIABLES)\b', 'information_schema.GLOBAL_STATUS 等', '5.7 でエラー、8.0 で削除',
  'performance_schema.global_status / SHOW STATUS', '§10-14')
R('SQL57-09', 'MySQL5.7', '中', 'A', 'PSD', r'\bALTER\s+IGNORE\s+TABLE\b', 'ALTER IGNORE TABLE', '構文削除', '重複を事前に解消', '§10-19')
R('SQL57-10', 'MySQL5.7', '中', 'B', 'PSD', r'\b(?:INSERT|UPDATE)\s+IGNORE\b', 'INSERT IGNORE / UPDATE IGNORE', 'strict モードのエラーが警告に降格され、切り捨て・型変換が黙って起きる',
  'データ欠損を許容する意図か確認', '§10-3')
R('SQL57-11', 'MySQL5.7', '低', 'B', 'PSD', r'(?<![\w$>:])(?:GET_LOCK|RELEASE_LOCK|IS_FREE_LOCK)\s*\(', 'GET_LOCK()', '複数ロック同時保持になり、2回目の GET_LOCK で1回目が解放されない', 'RELEASE_LOCK を明示', '§10-20')
R('SQL57-12', 'MySQL5.7', '中', 'C', 'SD', r'\bNOT\s+NULL\b(?!\s+(?:DEFAULT|AUTO_INCREMENT|PRIMARY))', 'NOT NULL（DEFAULT なし）列', 'strict モードで INSERT 時に列省略すると 1364 エラー',
  'DEFAULT を明示、または INSERT 側で値を指定', '§10-3')
R('SQL80-01', 'MySQL8.0', '中', 'A', 'PSD', r'\bSQL_CALC_FOUND_ROWS\b|(?<![\w$>:])FOUND_ROWS\s*\(', 'SQL_CALC_FOUND_ROWS / FOUND_ROWS()', '非推奨（8.0.17）。将来削除', '別途 COUNT(*) を発行', '§11-11')
R('SQL80-02', 'MySQL8.0', '低', 'A', 'PSD', r'\bON\s+DUPLICATE\s+KEY\s+UPDATE\b.*\bVALUES\s*\(|=\s*VALUES\s*\(\s*`?\w+`?\s*\)', 'ON DUPLICATE KEY UPDATE ... VALUES()', '非推奨（8.0.20）',
  '行エイリアス構文へ（DB更新完了後）', '§11-11')
R('SQL80-03', 'MySQL8.0', '高', 'A', 'PSD', r'\bSQL_CACHE\b|\b(?:FLUSH|RESET)\s+QUERY\s+CACHE\b', 'クエリキャッシュ構文 (SQL_CACHE 等)', '構文エラー（クエリキャッシュ削除）', '削除', '§11-9')
R('SQL80-03b', 'MySQL8.0', '低', 'A', 'PSD', r'\bSQL_NO_CACHE\b', 'SQL_NO_CACHE', '無視される（非推奨）', '削除', '§11-9')
R('SQL80-04', 'MySQL8.0', '中', 'A', 'PSD', r'\bEXPLAIN\s+(?:EXTENDED|PARTITIONS)\b|\bPROCEDURE\s+ANALYSE\b', 'EXPLAIN EXTENDED / PROCEDURE ANALYSE', '構文エラー', '削除', '§11-9')
R('SQL80-05', 'MySQL8.0', '高', 'A', 'PSCD', r'\btx_isolation\b|\btx_read_only\b', 'tx_isolation / tx_read_only', '変数削除（1193 エラー / 起動失敗）', 'transaction_isolation / transaction_read_only', '§11-9')
R('SQL80-06', 'MySQL8.0', '高', 'A', 'PSCD',
  r'\bNO_AUTO_CREATE_USER\b|sql[-_]mode[^;\n]*\b(?:MYSQL323|MYSQL40|MAXDB|MSSQL|ORACLE|POSTGRESQL|DB2|NO_FIELD_OPTIONS|NO_KEY_OPTIONS|NO_TABLE_OPTIONS)\b',
  'sql_mode の削除値 (NO_AUTO_CREATE_USER 等)', '起動失敗 / SET sql_mode が 1231 エラー', '文字列から除去', '§10-1 §11-8')
R('SQL80-07', 'MySQL8.0', '中', 'B', 'PSD', r'(?<![\w$>:])(?:REGEXP|RLIKE)(?![\w])', 'REGEXP / RLIKE', 'ICU 化。マルチバイトが文字単位マッチに変わり結果が変わる（サイレント）', '正規表現を棚卸ししテスト', '§11-13')
R('SQL80-07b', 'MySQL8.0', '高', 'A', 'PSD', r'\[\[:[<>]:\]\]', '単語境界 [[:<:]] [[:>:]]', 'ICU では不可（エラー）', '\\\\b へ', '§11-13')
R('SQL80-08', 'MySQL8.0', '中', 'B', 'PSD', r'\binformation_schema\b', 'information_schema 参照', '列名が大文字で返る（$row["table_name"] が未定義）。統計値はキャッシュ（最大1日古い）',
  '列に AS 別名、information_schema_stats_expiry=0', '§11-14')
_RW_DDL = (r'rank|dense_rank|row_number|ntile|cume_dist|percent_rank|first_value|last_value|nth_value|lead|lag|groups|grouping|system|window|over|'
           r'rows|row|function|lateral|recursive|json_table|empty|except|intersect|member|array|of|cube|generated|stored|virtual|'
           r'optimizer_costs|partition|signal|resignal|maxvalue|get|slow|general|master_bind|io_after_gtids|io_before_gtids')
_RW_SQL = (r'rank|dense_rank|row_number|ntile|cume_dist|percent_rank|first_value|last_value|nth_value|lead|lag|groups|grouping|system|window|'
           r'lateral|recursive|json_table|except|intersect|cube|generated|stored|virtual|partition|signal|resignal|maxvalue')
R('SQL80-09', 'MySQL5.5-8.0', '高', 'B', 'SD',
  r'^\s*\(?\s*`?(?:' + _RW_DDL + r')`?\s+(?:tiny|small|medium|big|long)?(?:int|integer|varchar|char|text|blob|date|datetime|timestamp|time|year|'
  r'decimal|numeric|float|double|real|enum|set|bit|bool|boolean|json|binary|varbinary)\b',
  '予約語と同名の列定義', 'クォートなしで参照する SQL が構文エラー。ビュー/ルーチンに含むとアップグレード失敗',
  'アプリ側 SQL のバッククォート有無を確認、またはリネーム', '§10-21 §11-12')
R('SQL80-09b', 'MySQL5.5-8.0', '高', 'B', 'PSD',
  r'(?:\b(?:SELECT|WHERE|AND|OR|ON|BY|SET|FROM|JOIN|INTO|UPDATE|TABLE|HAVING|DISTINCT)\s+|[,(.]\s*)(?:' + _RW_SQL + r')\b(?!\s*\()(?=\s*(?:[,=<>!)]|FROM\b|ASC\b|DESC\b|IS\b|IN\b|LIKE\b|BETWEEN\b|AS\b|SET\b|WHERE\b|$))',
  '予約語がクォートなしで識別子として使われている可能性', '構文エラー（rank, groups, system, lead, window 等）', 'バッククォートで囲む/リネーム', '§10-21 §11-12',
  ex=r'^\s*(?://|\*|#)')
R('SQL80-10', 'MySQL8.0', '中', 'B', 'PSCD',
  r'\b(?:CHARACTER\s+SET|CHARSET)\s*=?\s*`?utf8\b(?!mb4)|\butf8_(?:general|unicode|bin|unicode_520|japanese)\w*|\butf8mb3\b',
  'utf8 (utf8mb3) の宣言', '4バイト文字（絵文字・一部漢字）が入らない。8.0 で非推奨警告', 'utf8mb4 へ変換（行サイズ・索引長・照合順序に注意）', '§13-3 §13-11')
R('SQL80-10b', 'MySQL8.0', '高', 'B', 'PSCD',
  r'\b(?:CHARACTER\s+SET|CHARSET)\s*=?\s*`?latin1\b|\blatin1_\w+_(?:ci|cs)\b|\blatin1_bin\b|character[-_]set[-_]server\s*=\s*latin1',
  'latin1 の宣言', '日本語DBでは「誤宣言」（実体は SJIS/UTF-8 バイト列）の疑い。そのまま CONVERT TO すると全データが化ける',
  'HEX() で実バイト列を確認し、VARBINARY 経由で実エンコードを宣言してから変換', '§13-1')
R('SQL80-10c', 'MySQL8.0', '高', 'B', 'PSCD',
  r'\b(?:CHARACTER\s+SET|CHARSET)\s*=?\s*`?(?:sjis|ujis)\b|\b(?:sjis|ujis)_(?:japanese_ci|bin)\b|character[-_]set[-_]server\s*=\s*(?:sjis|ujis)\b',
  'sjis / ujis の宣言', '機種依存文字(①㈱髙 等)が sjis/ujis に無く、変換時に ? 化/エラー。～－∥ の対応コードポイント差',
  'Windows由来データは cp932 / eucjpms として扱い変換', '§13-2')
R('SQL80-10d', 'MySQL8.0', '高', 'B', 'PSCD', r'\butf8mb4_0900_\w+|\b\w+_general_ci\b|\b\w+_unicode_ci\b|\bCOLLATE\s*=?\s*`?\w+|\bcollation[-_]server\b',
  '照合順序の指定', '8.0 既定 utf8mb4_0900_ai_ci は濁点・かな・大小を区別せず NO PAD。既存 general_ci と混在すると 1267',
  'DB全体で照合順序を統一（日本語は utf8mb4_ja_0900_as_cs / utf8mb4_bin / general_ci 維持）', '§13-4〜§13-6')
R('SQL80-11', 'MySQL8.0', '中', 'A', 'SD', r'\bZEROFILL\b', 'ZEROFILL', '非推奨。表示幅に依存したゼロ埋め', 'LPAD() / アプリ側で整形', '§11-11')
R('SQL80-11b', 'MySQL8.0', '低', 'C', 'S', r'\b(?:tiny|small|medium|big)?int\s*\(\s*\d+\s*\)|\b(?:float|double)\s*\(\s*\d+\s*,\s*\d+\s*\)', '整数表示幅 INT(n) / FLOAT(M,D)',
  '非推奨。SHOW CREATE TABLE から消え、int(11) を解析するコードが壊れる', '表示幅を削除', '§11-11 §11-14')
R('SQL80-12', 'MySQL8.0', '低', 'B', 'PSD', r'''(?:\b(?:WHERE|AND|OR|ON|BY|SELECT)\s+|[=(,]\s*)BINARY\s+[`'"\w$?:]''', 'BINARY 演算子', '非推奨（8.0.27）', 'CAST(... AS BINARY) / COLLATE utf8mb4_bin', '§11-11')
R('SQL80-14', 'MySQL8.0/8.4', '中', 'A', 'SD', r'\bDEFINER\s*=', 'DEFINER= 付きオブジェクト', 'import に SET_USER_ID(8.0)/SET_ANY_DEFINER(8.4) 権限が必要。定義者ユーザ不在で実行時エラー',
  'DEFINER を除去または権限付与', '§11-4 §12-6')
R('SQL80-15', 'MySQL8.0', '中', 'A', 'S', r'(?:,|\(|VALUES\s*\()\s*\\N\s*(?=,|\))', 'SQL 文中の \\N（NULL の別表記）', '8.0 で構文エラー', 'NULL へ', '§11-9', cs=True)
R('SQL80-16', 'MySQL5.5/8.0', '中', 'B', 'PSD', r'\bPARTITION\s+BY\b', 'パーティション定義', 'MyISAM パーティション不可(8.0)。5.1 作成の KEY パーティションはハッシュ方式が旧式',
  'InnoDB 化、ALGORITHM=2 で再パーティション', '§9-7 §11-16')
R('SQL80-17', 'MySQL5.7/8.0', '中', 'B', 'PSD', r'\bCREATE\s+USER\b|\bmysql\s*\.\s*`?user\b|\bFLUSH\s+PRIVILEGES\b|\bUPDATE\s+mysql\s*\.', 'ユーザ管理 SQL / mysql.user 直接操作',
  'Password 列削除、権限テーブルへの直接DMLは不可/非推奨。既定認証プラグイン変更', 'CREATE USER / ALTER USER / GRANT のみ使用', '§9-18 §10-23 §11-3')
R('SQL80-18', 'MySQL8.0', '低', 'A', 'PSD', r'(?<![\w$>:])JSON_MERGE\s*\(', 'JSON_MERGE()', '非推奨', 'JSON_MERGE_PRESERVE()', '§11-11')
R('SQL80-19', 'MySQL8.0', '中', 'B', 'PSD', r'\bUNION\b', 'UNION', '各 SELECT 内の ORDER BY は LIMIT が無いと無視される', '外側で ORDER BY', '§11-7')
R('SQL80-20', 'MySQL8.0', '低', 'B', 'PSD', r'\b(?:STRAIGHT_JOIN|USE\s+INDEX|FORCE\s+INDEX|IGNORE\s+INDEX)\b', 'インデックスヒント / STRAIGHT_JOIN', 'オプティマイザ変更で旧ヒントが逆効果になりうる',
  '実行計画を新環境で再確認', '§9-14 §11-22')
R('SQL80-21', 'MySQL8.0', '低', 'B', 'PSD', r'\bLOCK\s+TABLES?\b', 'LOCK TABLES', 'MyISAM 前提の排他制御。InnoDB ではトランザクションとの併用に注意', 'トランザクション / SELECT ... FOR UPDATE へ', '§9-1')
R('SQL80-22', 'MySQL8.0', '低', 'B', 'PSD', r'(?<![\w$>:._])LENGTH\s*\(', 'LENGTH()（バイト長）', 'utf8mb4 化で1文字最大4バイト。桁チェックの結果が変わる', 'CHAR_LENGTH() へ', '§13-9')
R('SQL84-01', 'MySQL8.4', '高', 'A', 'PSD',
  r'\bSHOW\s+(?:MASTER|SLAVE)\s+(?:STATUS|HOSTS|LOGS)\b|\b(?:START|STOP|RESET)\s+SLAVE\b|\bCHANGE\s+MASTER\s+TO\b|\bRESET\s+MASTER\b|'
  r'\bPURGE\s+MASTER\s+LOGS\b|\bFLUSH\s+HOSTS\b|WAIT_UNTIL_SQL_THREAD_AFTER_GTIDS',
  'MASTER/SLAVE 系レプリケーション構文・FLUSH HOSTS', '8.4 で構文エラー（監視・フェイルオーバ・バックアップスクリプト）',
  'SOURCE/REPLICA 系構文へ（SHOW BINARY LOG STATUS, SHOW REPLICA STATUS 等）', '§12-4')
R('SQL84-02', 'MySQL8.0/8.4', '高', 'A', 'PSCD', r'\bmysql_native_password\b|\bsha256_password\b|\bIDENTIFIED\s+WITH\b|\bmysql_old_password\b',
  '認証プラグイン指定', 'mysql_native_password は 8.4 で既定無効（1524）。9.x で削除', 'caching_sha2_password へ（PHP 7.4+ 必須）', '§11-1 §12-1')
R('SQL84-03', 'MySQL8.0/8.4', '中', 'A', 'PSD', r'(?<![\w$])(?:mysqlpump|mysql_upgrade|mysql_install_db|mysql_ssl_rsa_setup|mysqlhotcopy|mysql_convert_table_format|mysql_setpermission|mysql_zap)(?![\w])',
  '削除済みクライアントツール', 'コマンドが存在しない', 'mysqldump / MySQL Shell / mysqld --initialize', '§10-17 §12-5')
R('SQL84-04', 'MySQL8.0', '低', 'B', 'PSD', r'(?<![\w$])(?:mysqldump|mysqlimport|mysqlbinlog|mysqladmin|mysqlcheck)(?![\w])', 'MySQL クライアントツール呼び出し',
  'オプション既定値の変更（--column-statistics, --set-gtid-purged, 文字コード既定 utf8mb4, PROCESS 権限）', 'オプションを明示し新旧組合せで動作確認', '§11-28 §13-10')
R('SQL84-05', 'MySQL8.0', '低', 'B', 'PSD', r'\bGRANT\b[^;]*\bSUPER\b|\bSET_USER_ID\b', 'SUPER / SET_USER_ID 権限', 'SUPER 非推奨（動的権限へ）、SET_USER_ID は 8.4 で削除', '動的権限 / SET_ANY_DEFINER', '§11-4 §12-6')

# ============================ MySQL: my.cnf =================================
_C55 = (r'skip_locking|enable_locking|default_collation|log_long_format|log_update|master_host|master_user|master_password|master_port|'
        r'master_connect_retry|master_ssl\w*|skip_safemalloc|innodb_file_io_threads|table_cache|myisam_recover|skip_bdb|bdb_\w+|'
        r'log_bin_trust_routine_creators|one_thread|skip_thread_priority|safe_show_database|delay_key_write_for_all_tables|'
        r'sql_bin_update_same|log_slow_queries|record_buffer')
_C57 = (r'thread_concurrency|innodb_additional_mem_pool_size|innodb_use_sys_malloc|storage_engine|timed_mutexes|innodb_mirrored_log_groups|'
        r'engine_condition_pushdown|safe_mode|skip_innodb|max_long_data_size|have_\w+')
_C80 = (r'query_cache_\w+|innodb_file_format\w*|innodb_large_prefix|innodb_support_xa|innodb_checksums|innodb_locks_unsafe_for_binlog|'
        r'innodb_stats_sample_pages|innodb_undo_logs|secure_auth|old_passwords|sync_frm|multi_range_count|log_warnings|'
        r'ignore_builtin_innodb|ignore_db_dirs|max_tmp_tables|metadata_locks_cache_size|metadata_locks_hash_instances|'
        r'show_compatibility_56|log_builtin_as_identified_by_password|des_key_file|skip_partition|temp_pool|tx_isolation|tx_read_only|'
        r'log_syslog\w*|bootstrap')
_C84 = (r'default_authentication_plugin|expire_logs_days|master_info_repository|relay_log_info_repository|master_info_file|relay_log_info_file|'
        r'binlog_transaction_dependency_tracking|transaction_write_set_extraction|log_bin_use_v1_row_events|avoid_temporal_upgrade|'
        r'show_old_temporals|innodb_api_\w+|daemon_memcached_\w+|group_replication_ip_whitelist|group_replication_primary_member|'
        r'group_replication_recovery_complete_at|slave_rows_search_algorithms|character_set_client_handshake|'
        r'skip_character_set_client_handshake|old_style_user_limits|skip_host_cache|abort_slave_event_count|disconnect_slave_event_count|'
        r'admin_ssl|skip_ssl|keyring_file_data|keyring_encrypted_file_\w+|no_dd_upgrade|have_ssl|have_openssl|authentication_fido_rp_id')
_CDEP = (r'innodb_log_file_size|innodb_log_files_in_group|binlog_format|replica_parallel_type|slave_parallel_type|temptable_use_mmap|'
         r'sync_relay_log_info|mysql_native_password|sha256_password_\w+|'
         r'slave_\w+|master_verify_checksum|sync_master_info|log_slave_updates|skip_slave_start|innodb_undo_tablespaces|'
         r'symbolic_links|skip_symbolic_links|myisam_repair_threads|log_slow_slave_statements')
_CCHK = (r'sql_mode|character_set_server|collation_server|default_storage_engine|lower_case_table_names|explicit_defaults_for_timestamp|'
         r'innodb_strict_mode|innodb_file_per_table|innodb_default_row_format|innodb_autoinc_lock_mode|max_allowed_packet|'
         r'secure_file_priv|local_infile|log_timestamps|default_time_zone|event_scheduler|log_bin|server_id|skip_log_bin|disable_log_bin|'
         r'innodb_buffer_pool_size|innodb_flush_method|innodb_io_capacity\w*|innodb_adaptive_hash_index|innodb_change_buffering|'
         r'authentication_policy|require_secure_transport|tls_version|skip_name_resolve|skip_networking|bind_address|ft_min_word_len|'
         r'innodb_ft_min_token_size|ngram_token_size|group_concat_max_len|wait_timeout|interactive_timeout|max_connections|'
         r'optimizer_switch|transaction_isolation|performance_schema|open_files_limit|init_connect|init_file|skip_grant_tables|'
         r'validate_password\w*|default_password_lifetime|information_schema_stats_expiry|mysqlx\w*|binlog_expire_logs_seconds|'
         r'innodb_redo_log_capacity|datadir|socket|port|pid_file|log_error|slow_query_log\w*|long_query_time|general_log\w*')

R('CNF-55', 'MySQL5.5/5.6', '高', 'A', 'CD', CNF(_C55), '5.5/5.6 で削除された my.cnf オプション', 'mysqld が起動しない（unknown variable）',
  'my.cnf を新規作成し代替オプションへ（skip-external-locking, table_open_cache, slow_query_log 等）', '§9-3 §9-17', doc=CNFDOC(_C55))
R('CNF-55b', 'MySQL5.5', '高', 'A', 'C', CNF('default_character_set'), '[mysqld] 節の default-character-set', 'mysqld が起動しない',
  'character-set-server へ（[client]/[mysql] 節では有効だが mysqlnd は読まない）', '§9-3 §14-2', sect=r'^(?:mysqld|mysqld_safe|server|mysqld-\d\.\d)$')
R('CNF-55c', 'MySQL5.5', '高', 'A', 'C', r'^\s*(?:log|language)\s*=', 'log= / language=', '起動失敗（general_log / lc_messages_dir へ変更。language は 8.4 で削除）',
  'general_log, general_log_file / lc_messages_dir', '§9-17 §12-3', sect=r'^(?:mysqld|mysqld_safe|server)')
R('CNF-57', 'MySQL5.7', '高', 'A', 'CD', CNF(_C57), '5.7 で削除された my.cnf オプション', 'mysqld が起動しない', '行を削除', '§9-16', doc=CNFDOC(_C57.replace(r'|safe_mode', '').replace(r'|have_\w+', '')))
R('CNF-57b', 'MySQL5.7', '高', 'A', 'C', r'^\s*(?:key[-_]buffer|sort[-_]buffer|read[-_]buffer|thread[-_]cache|myisam[-_]sort[-_]buffer|net[-_]buffer|max[-_]allowed|table[-_]open)\s*=',
  'オプション名の前方一致省略 (key_buffer= 等)', '5.7 以降は省略形を受け付けず起動失敗', '正式名 (key_buffer_size 等) へ', '§9-3')
R('CNF-57c', 'MySQL5.7', '中', 'A', 'C', r'^\s*\[mysqld_safe\]', '[mysqld_safe] 節', 'systemd 環境では mysqld_safe を使わず、この節は無視される',
  'log-error, pid-file, open-files-limit 等を [mysqld] / systemd へ移動', '§10-15')
R('CNF-80', 'MySQL8.0', '高', 'A', 'CD', CNF(_C80), '8.0 で削除された my.cnf 変数', 'mysqld が起動しない（query_cache_*, innodb_file_format, log_warnings 等）',
  '行を削除/代替へ。mysqld --validate-config で検証', '§11-10', doc=CNFDOC(_C80.replace(r'|bootstrap', '')))
R('CNF-84', 'MySQL8.4', '高', 'A', 'CD', CNF(_C84), '8.4 で削除された my.cnf 変数', 'mysqld が起動しない（default_authentication_plugin, expire_logs_days, skip-character-set-client-handshake 等）',
  'authentication_policy / binlog_expire_logs_seconds 等へ。charset は接続側で明示', '§12-2 §12-3', doc=CNFDOC(_C84))
R('CNF-84b', 'MySQL8.4', '高', 'A', 'C', r'^\s*(?:--)?(?:old|new|ssl|innodb|skip[-_]new)(?=\s*(?:=|$|#))', '8.4 で削除されたオプション (old/new/ssl/innodb)', 'mysqld が起動しない', '行を削除', '§12-3',
  sect=r'^(?:mysqld|mysqld_safe|server)')
R('CNF-DEP', 'MySQL8.0-8.4', '低', 'A', 'CD', CNF(_CDEP), '非推奨の my.cnf 変数', '警告。将来削除（innodb_log_file_size → innodb_redo_log_capacity、slave_* → replica_* 等）',
  '代替変数へ', '§11-11 §12', doc=CNFDOC(_CDEP.replace(r'|slave_\w+', '')))
R('CNF-CHK', '環境', '中', 'B', 'CD', CNF(_CCHK), '値の再確認が必要な my.cnf 設定', '既定値が大きく変わっている/移行方針の決定が必要（sql_mode, 文字コード, 照合, TIMESTAMP, 認証 等）',
  '新 my.cnf に意図した値を明示', '§9〜§13', doc=CNFDOC(
      r'sql_mode|character_set_server|collation_server|default_storage_engine|lower_case_table_names|explicit_defaults_for_timestamp|'
      r'innodb_strict_mode|innodb_file_per_table|innodb_autoinc_lock_mode|max_allowed_packet|secure_file_priv|local_infile|log_timestamps|'
      r'event_scheduler|authentication_policy|ft_min_word_len|group_concat_max_len|wait_timeout|optimizer_switch|skip_grant_tables'))

# ============================ 設計書向けキーワード ==========================
R('DOC-01', '設計書', '低', 'B', 'D',
  r'PHP\s*[45]\.\d+(?:\.\d+)?|PHP\s*[45](?![\w.])|MySQL\s*[345]\.\d+(?:\.\d+)?|MySQL\s*5(?![\w.])|Apache\s*(?:1\.3|2\.[0-2])|CentOS\s*[4-7]|RHEL\s*[4-7]|'
  r'Red\s*Hat\s+Enterprise\s+Linux\s*[4-7]|Windows\s+Server\s+20(?:03|08|12)',
  '旧バージョン・旧環境の記載', '前提バージョンの記述箇所。設計書の改訂対象', '移行後バージョンへ改訂し、前提に依存する記述を確認', '')
R('DOC-02', '設計書', '中', 'B', 'D',
  r'Shift[_-]?JIS|(?<![\w])S-?JIS(?![\w])|EUC[-_]?JP|MS932|CP932|Windows-31J|ISO-2022-JP|eucJP-ms|utf8mb[34]|文字コード|文字化け|機種依存文字|外字|絵文字|'
  r'照合順序|collation|サロゲート|半角カナ|全角.{0,4}半角|バイト数|桁数チェック',
  '文字コード・照合順序に関する記載', '文字コード変換（utf8mb4化）、照合順序（濁点/かな/末尾空白）、バイト長前提の仕様に影響', 'ガイド13節に照らして仕様を確認', '§13')
R('DOC-03', '設計書', '中', 'B', 'D',
  r'MyISAM|InnoDB|全文検索|フルテキスト|パーティション|レプリケーション|マスタ[ー]?\s*[/／・]?\s*スレーブ|(?<![\w])(?:master|slave)(?![\w])|バイナリログ|'
  r'ストアド|トリガ[ー]?|ビュー定義|イベントスケジューラ|クエリキャッシュ|トランザクション分離|テーブルロック|排他制御|デッドロック|採番|AUTO_INCREMENT|シーケンス',
  'DB 物理設計・運用方式に関する記載', 'エンジン既定変更、レプリケーション構文、クエリキャッシュ削除、採番方式等に影響', 'ガイド9〜12節に照らして確認', '§9〜§12')
R('DOC-04', '設計書', '中', 'B', 'D',
  r'パスワード.{0,12}(?:ハッシュ|暗号|保存|照合)|MD5|SHA-?1(?![\w])|暗号化|復号|共通鍵|認証方式|認証プラグイン|SSL|TLS\s*1\.[01]|証明書|バックアップ|リストア|ダンプ|'
  r'DB\s*ユーザ|権限設計|GRANT',
  '認証・暗号・バックアップに関する記載', 'mcrypt 削除、MySQL ENCODE/PASSWORD 削除、認証プラグイン変更、TLS バージョン、ダンプ手順に影響', 'ガイドの該当節に照らして確認', '§4-8 §10-9 §10-10 §11-1 §12-1')
R('DOC-05', '設計書', '中', 'B', 'D',
  r'eAccelerator|XCache|Zend\s*(?:Optimizer|Guard|Framework)|ionCube|Smarty|PEAR|CakePHP|symfony|CodeIgniter|FuelPHP|Laravel|EC-?CUBE|Ethna|ADOdb|Propel|'
  r'Doctrine|PHPExcel|PHPMailer|TCPDF|FPDF|PHPUnit|Composer|(?<![\w])APC(?![\w])|memcached?|セッション管理|セッションハンドラ|php-?fpm|FastCGI|suEXEC|suPHP',
  'ミドルウェア・ライブラリ・実行方式に関する記載', 'PHP 8.5 対応版の有無、APC→OPcache/APCu、mod_php→FPM の影響', 'バージョンと対応状況を確認', '§2-17 §8')
R('DOC-06', '設計書', '低', 'B', 'D',
  r'タイムゾーン|2038年|ゼロ日付|日付.{0,6}(?:未設定|初期値|デフォルト)|更新日時.{0,10}自動|登録日時.{0,10}自動|自動更新|四捨五入|切り捨て|切り上げ|端数処理|丸め',
  '日時・端数処理に関する記載', 'date.timezone 既定 UTC、TIMESTAMP 暗黙既定、ゼロ日付、round() 実装変更に影響', '仕様と実装の対応を確認', '§3-8 §7-14 §9-9 §10-4')
R('DOC-07', '設計書', '低', 'B', 'D',
  r'エラーハンドリング|エラー処理方針|例外処理|エラーログ|ログ出力レベル|error_log|メール送信|mb_send_mail|sendmail|バッチ処理|cron|常駐',
  'エラー処理・バッチに関する記載', 'エラー既定レベル、DB例外化、長時間バッチの再接続に影響', '方針を確認', '§5-11 §14-6 §14-8')


# ---------------------------------------------------------------------------
# 機械検出できない確認項目
# ---------------------------------------------------------------------------
MANUAL = [
    ('M-01', 'PHP8.0', '高', '非数値文字列/配列/null への算術・比較（型は静的に判定不能）', '新環境で error_reporting=E_ALL のログを収集（TypeError / Warning: A non-numeric value）', '§5-1〜§5-3'),
    ('M-02', 'PHP8.0', '高', 'ゼロ除算（/ と %）が DivisionByZeroError', '除算箇所の分母が 0 になるケースのテスト', '§5-4'),
    ('M-03', 'PHP8.0', '高', '非 static メソッドの static 呼び出し（Error）', 'PHPCompatibility / PHPStan、または実行ログ', '§3-16 §5-14'),
    ('M-04', 'PHP8.0', '高', '継承時のメソッドシグネチャ非互換（Fatal）', '対象バージョンの php -l / 全クラスのロードテスト', '§5-15'),
    ('M-05', 'PHP8.0', '高', '未定義定数（クォート忘れ $a[key]）が Error、未定義変数/キーが Warning', '実行ログ収集', '§5-10'),
    ('M-06', 'PHP8.0', '高', '内部関数の引数型不正が TypeError / ValueError（strlen([]) explode("",..) 等）', '実行ログ収集、PHPStan', '§5-8 §5-9'),
    ('M-07', 'PHP8.1', '高', '内部関数への null 渡し（Deprecated、9.0 で TypeError）', '実行ログの「Passing null to parameter」を集計', '§6-1'),
    ('M-08', 'PHP8.2', '高', '動的プロパティ（未宣言プロパティへの代入）', '実行ログの「Creation of dynamic property」を集計', '§6-20'),
    ('M-09', 'PHP8.1', '中', 'float→int の暗黙変換、false からの配列自動生成', '実行ログ収集', '§6-9 §6-11'),
    ('M-10', 'PHP7.0', '中', 'foreach 内での current()/next()、list() の代入順、func_get_args() の変更後値', '該当イディオムの目視、テスト', '§3-14 §3-15 §3-19'),
    ('M-11', 'PHP7.3', '中', 'switch 内の continue（Warning）', '対象バージョンの php -l', '§4-29'),
    ('M-12', 'PHP7.2', '高', 'mbstring.func_overload 有効環境での strlen/substr/strpos 等（バイト単位に変わる）', 'php.ini の func_overload 値を確認し、有効なら全該当関数を mb_* へ', '§4-17'),
    ('M-13', 'PHP8.5', '中', 'null の配列オフセット、非数値文字列の ++、#[NoDiscard] 戻り値破棄', '実行ログ収集', '§7-27 §7-28 §7-40'),
    ('M-14', '環境', '高', '全 PHP ファイルの構文エラー', '対象バージョンで find . -name "*.php" | xargs -n1 php -l', '§16'),
    ('M-15', 'MySQL5.7', '高', 'strict モード違反（型不正・桁あふれ・NOT NULL 省略・空文字の数値列挿入）', 'general_log を新DBで再生し SHOW WARNINGS / エラーを収集', '§10-3'),
    ('M-16', 'MySQL5.7', '高', 'ONLY_FULL_GROUP_BY 違反（SELECT 列と GROUP BY の不整合）', '全 GROUP BY クエリを新DBで実行（1055/3065）', '§10-2'),
    ('M-17', 'MySQL8.0', '高', 'GROUP BY の暗黙ソート依存、ORDER BY なし一覧の並び順', '旧新DBで結果比較（pt-upgrade 等）', '§11-6'),
    ('M-18', 'MySQL8.0', '高', '照合順序の意味変更（濁点/かな同一視、NO PAD、UNIQUE 重複）', 'ガイド16節の調査SQL、テストデータ（は/ば/ぱ、末尾空白）', '§13-4 §13-5'),
    ('M-19', 'MySQL8.0', '高', 'latin1 誤宣言・機種依存文字・4バイト文字の実データ', 'SELECT HEX(col) によるサンプリング', '§13-1〜§13-3'),
    ('M-20', 'MySQL5.6', '高', '旧時刻フォーマット列（5.6.4 以前作成の DATETIME/TIMESTAMP/TIME）', 'mysqlcheck --check-upgrade → ALTER TABLE ... FORCE', '§9-10'),
    ('M-21', 'MySQL8.0', '高', 'データディクショナリ移行の阻害要因（予約語、旧構文を含むビュー/ルーチン、MyISAMパーティション）', 'MySQL Shell util.checkForServerUpgrade()', '§11-16'),
    ('M-22', 'MySQL8.4', '高', 'mysql_native_password ユーザ / 旧16桁ハッシュ', 'SELECT user,host,plugin FROM mysql.user', '§9-8 §12-1'),
    ('M-23', 'MySQL8.0', '中', '実行計画の退行（オプティマイザ変更）', 'スロークエリログ比較、EXPLAIN', '§9-14 §11-22'),
    ('M-24', 'MySQL8.0', '中', '眠っている EVENT（event_scheduler=ON 既定で動き出す）', 'SHOW EVENTS', '§11-24'),
    ('M-25', '連携', '高', 'DB エラー時のフロー（戻り値判定→例外）、数値型（文字列→int/float）', '異常系テスト、JSON API のスナップショット比較', '§14-5 §14-6'),
    ('M-26', '連携', '中', 'mysqlnd が my.cnf [client] を読まないことによる charset/socket の欠落', '接続コードで charset・socket を明示しているか確認', '§14-2'),
    ('M-27', '環境', '中', '32bit→64bit 移行（整数幅、crc32/ip2long の符号）', '旧サーバのアーキテクチャ確認、保存値の形式確認', '§3-24'),
    ('M-28', '設計書', '中', 'PDF・画像・パスワード付き Office・旧形式(xls/doc)の設計書', '本ツールは未対応/簡易抽出。目視または xlsx/docx へ変換して再走査', ''),
]

# ファイル単位の特殊チェック（summary 用の定義。検出ロジックは Scanner 内）
SPECIAL = [
    ('ENC-01', 'PHP5.4+', '高', 'A', 'ソースファイルが非 UTF-8', 'zend.multibyte 未設定では SJIS の 5C 問題で Parse error。default_charset と不整合で文字化け', 'ソースを UTF-8(BOMなし) へ一括変換', '§2-11 §8-5', 'P'),
    ('ENC-02', '環境', '中', 'A', 'UTF-8 BOM 付きソース', 'BOM が出力され header()/session_start() が失敗', 'BOM を除去', '§8-5', 'P'),
    ('ENC-03', 'PHP5.4+', '高', 'B', 'SJIS の 5C 文字（ソ・表・能 等）を含む行', 'zend.multibyte なしでは文字列リテラルが壊れる', 'ソースを UTF-8 化', '§2-11 §8-5', 'P'),
    ('PHP70-07', 'PHP7.0/8.0', '高', 'A', 'PHP4 形式コンストラクタ', '8.0 でコンストラクタとして呼ばれない（サイレント）', '__construct() へ', '§3-16 §5-14', 'P'),
    ('PHP73-02', 'PHP7.3', '中', 'A', 'ヒアドキュメント本文に終端識別子と同じ語で始まる行', 'Parse error / 本文欠落', '識別子を変更', '§4-28', 'P'),
    ('PHP85-02', 'PHP8.5', '低', 'B', 'バッククォート演算子', 'Deprecated', 'shell_exec() へ', '§7-24', 'P'),
    ('INI-TZ', 'PHP7.0', '高', 'A', 'php.ini に date.timezone 未設定', '無警告で UTC になる（サイレント）', 'Asia/Tokyo を設定', '§2-12 §3-8', 'I'),
    ('SQL55-04', 'MySQL5.5', '高', 'A', 'ENGINE 指定のない CREATE TABLE（.sql）', 'InnoDB で作成される', 'ENGINE を明示', '§9-1', 'S'),
]

# ---------------------------------------------------------------------------
# ファイル種別
# ---------------------------------------------------------------------------
PHP_EXT = {'.php', '.php3', '.php4', '.php5', '.phtml', '.inc', '.tpl', '.ctp', '.module', '.class', '.lib', '.html', '.htm', '.thtml', '.phps'}
SQL_EXT = {'.sql', '.ddl', '.dump', '.sh', '.bash', '.csh', '.ksh', '.bat', '.cmd', '.ps1', '.pl', '.pm', '.py', '.rb', '.cron',
           '.xml', '.yml', '.yaml', '.json', '.properties', '.env', '.a5er', '.edm'}
DOCTXT_EXT = {'.txt', '.md', '.csv', '.tsv', '.rst', '.adoc', '.tex', '.rtf', '.log', '.text', '.memo', '.doc.txt'}
OOXML_EXT = {'.xlsx', '.xlsm', '.xltx', '.xltm', '.docx', '.docm', '.dotx', '.pptx', '.pptm', '.ppsx', '.vsdx'}
LEGACY_EXT = {'.xls', '.doc', '.ppt', '.xlt', '.dot', '.pps'}
UNSUPPORTED_DOC = {'.pdf', '.vsd', '.jtd', '.odt', '.ods', '.odp', '.one', '.mpp'}
SKIP_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.svg', '.tif', '.tiff', '.zip', '.gz', '.tgz', '.bz2', '.7z', '.lzh', '.rar',
            '.tar', '.jar', '.war', '.exe', '.dll', '.so', '.o', '.a', '.class_', '.swf', '.fla', '.mp3', '.mp4', '.avi', '.mov', '.wav',
            '.ttf', '.otf', '.woff', '.woff2', '.eot', '.psd', '.ai', '.css', '.js', '.map', '.min.js', '.scss', '.less', '.ts',
            '.mo', '.po', '.pyc', '.db', '.sqlite', '.mdb', '.accdb', '.frm', '.myd', '.myi', '.ibd', '.lock', '.pem', '.crt', '.key'}
DEFAULT_EXCLUDE_DIRS = {'.git', '.svn', '.hg', 'CVS', 'node_modules', '.idea', '.vscode', '__pycache__'}

TYPE_LABEL = {'P': 'PHPソース', 'S': 'SQL/スクリプト/設定', 'I': 'PHP設定', 'C': 'MySQL設定', 'IC': '設定(汎用)',
              'D': '設計書(テキスト)', 'DX': '設計書(Office)', 'DL': '設計書(旧Office簡易抽出)'}


def classify(path):
    name = os.path.basename(path).lower()
    ext = os.path.splitext(name)[1]
    if name in ('.htaccess', '.user.ini') or name.startswith('php.ini') or re.match(r'php[\w.-]*\.ini$', name) \
            or re.match(r'(?:httpd|apache2?|php-fpm|www|vhosts?)[\w.-]*\.conf$', name):
        return 'I'
    if name in ('my.cnf', 'my.ini', 'mysqld.cnf', 'mysql.cnf') or ext == '.cnf' or re.match(r'my[\w.-]*\.(?:cnf|ini)$', name):
        return 'C'
    if ext in ('.ini', '.conf', '.cfg'):
        return 'IC'
    if ext in OOXML_EXT:
        return 'DX'
    if ext in LEGACY_EXT:
        return 'DL'
    if ext in UNSUPPORTED_DOC:
        return 'UNSUP'
    if ext in PHP_EXT:
        return 'P'
    if ext in SQL_EXT or name in ('crontab', 'makefile', 'dockerfile'):
        return 'S'
    if ext in DOCTXT_EXT:
        return 'D'
    if ext in SKIP_EXT:
        return 'SKIP'
    return 'SNIFF'


# ---------------------------------------------------------------------------
# 文字コード判定
# ---------------------------------------------------------------------------
def decode_bytes(b):
    if b.startswith(b'\xef\xbb\xbf'):
        return b[3:].decode('utf-8', 'replace'), 'UTF-8(BOM)'
    if b.startswith(b'\xff\xfe') or b.startswith(b'\xfe\xff'):
        return b.decode('utf-16', 'replace'), 'UTF-16'
    try:
        return b.decode('ascii'), 'ASCII'
    except UnicodeDecodeError:
        pass
    if b'\x1b$' in b or b'\x1b(' in b:
        try:
            return b.decode('iso2022_jp'), 'ISO-2022-JP'
        except UnicodeDecodeError:
            pass
    for enc, label in (('utf-8', 'UTF-8'), ('euc_jp', 'EUC-JP'), ('euc_jisx0213', 'EUC-JP(拡張)'),
                       ('cp932', 'SJIS(CP932)'), ('shift_jisx0213', 'SJIS(拡張)')):
        try:
            return b.decode(enc), label
        except (UnicodeDecodeError, LookupError):
            continue
    return b.decode('cp932', 'replace'), '不明(CP932で代替)'


def looks_binary(b):
    head = b[:8192]
    if head.startswith((b'\xff\xfe', b'\xfe\xff')):
        return False
    return b'\x00' in head


# ---------------------------------------------------------------------------
# Office 文書の抽出
# ---------------------------------------------------------------------------
def _ln(tag):
    return tag.rsplit('}', 1)[-1]


def _xlsx_shared(z):
    out = []
    try:
        f = z.open('xl/sharedStrings.xml')
    except KeyError:
        return out
    with f:
        for ev, el in ET.iterparse(f, events=('end',)):
            if _ln(el.tag) == 'si':
                parts = []
                for ch in el:
                    n = _ln(ch.tag)
                    if n == 't':
                        parts.append(ch.text or '')
                    elif n == 'r':
                        for t in ch:
                            if _ln(t.tag) == 't':
                                parts.append(t.text or '')
                out.append(''.join(parts))
                el.clear()
    return out


def _rels(z, path):
    d = {}
    try:
        root = ET.fromstring(z.read(path))
    except Exception:
        return d
    for r in root:
        d[r.attrib.get('Id')] = r.attrib.get('Target', '')
    return d


def _norm_target(base_dir, target):
    if target.startswith('/'):
        return target.lstrip('/')
    parts = (base_dir + '/' + target).split('/')
    st = []
    for p in parts:
        if p == '..':
            if st:
                st.pop()
        elif p and p != '.':
            st.append(p)
    return '/'.join(st)


def _a_paragraphs(xmlbytes):
    """DrawingML / WordprocessingML の段落テキスト列"""
    out = []
    try:
        root = ET.fromstring(xmlbytes)
    except Exception:
        return out
    for p in root.iter():
        if _ln(p.tag) == 'p':
            s = ''.join((t.text or '') for t in p.iter() if _ln(t.tag) == 't')
            if s.strip():
                out.append(s)
    return out


def extract_xlsx(z):
    shared = _xlsx_shared(z)
    names = z.namelist()
    sheets = []
    try:
        wb = ET.fromstring(z.read('xl/workbook.xml'))
        rels = _rels(z, 'xl/_rels/workbook.xml.rels')
        for el in wb.iter():
            if _ln(el.tag) == 'sheet':
                rid = None
                for k, v in el.attrib.items():
                    if _ln(k) == 'id':
                        rid = v
                tgt = rels.get(rid)
                if tgt:
                    sheets.append((el.attrib.get('name', '?'), _norm_target('xl', tgt)))
    except Exception:
        pass
    if not sheets:
        sheets = [(os.path.basename(n), n) for n in names if re.match(r'xl/worksheets/[^/]+\.xml$', n)]
    for sname, spath in sheets:
        if spath not in names:
            continue
        with z.open(spath) as f:
            for ev, el in ET.iterparse(f, events=('end',)):
                if _ln(el.tag) != 'c':
                    continue
                t = el.attrib.get('t')
                ref = el.attrib.get('r', '')
                val = None
                if t == 's':
                    for ch in el:
                        if _ln(ch.tag) == 'v' and ch.text:
                            try:
                                val = shared[int(ch.text)]
                            except (ValueError, IndexError):
                                val = None
                elif t == 'inlineStr':
                    val = ''.join((x.text or '') for x in el.iter() if _ln(x.tag) == 't')
                elif t == 'str':
                    for ch in el:
                        if _ln(ch.tag) == 'v':
                            val = ch.text
                if val and val.strip():
                    yield ('%s!%s' % (sname, ref), val)
                el.clear()
        # シート上の図形（テキストボックス）
        sdir = os.path.dirname(spath)
        rels = _rels(z, '%s/_rels/%s.rels' % (sdir, os.path.basename(spath)))
        for tgt in rels.values():
            if 'drawing' in tgt and tgt.endswith('.xml'):
                dp = _norm_target(sdir, tgt)
                if dp in names:
                    for i, s in enumerate(_a_paragraphs(z.read(dp)), 1):
                        yield ('%s!図形#%d' % (sname, i), s)
    for n in names:
        if re.match(r'xl/comments\d*\.xml$', n):
            try:
                root = ET.fromstring(z.read(n))
            except Exception:
                continue
            for c in root.iter():
                if _ln(c.tag) == 'comment':
                    s = ''.join((t.text or '') for t in c.iter() if _ln(t.tag) == 't')
                    if s.strip():
                        yield ('コメント!%s' % c.attrib.get('ref', ''), s)


def extract_docx(z):
    names = z.namelist()
    for part in ['word/document.xml'] + sorted(n for n in names if re.match(r'word/(?:header|footer|footnotes|endnotes|comments)\d*\.xml$', n)):
        if part not in names:
            continue
        label = '' if part == 'word/document.xml' else os.path.basename(part).replace('.xml', '') + ':'
        for i, s in enumerate(_a_paragraphs(z.read(part)), 1):
            yield ('%s段落%d' % (label, i), s)


def extract_pptx(z):
    names = z.namelist()

    def num(n):
        m = re.search(r'(\d+)\.xml$', n)
        return int(m.group(1)) if m else 0
    for n in sorted((x for x in names if re.match(r'ppt/slides/slide\d+\.xml$', x)), key=num):
        for i, s in enumerate(_a_paragraphs(z.read(n)), 1):
            yield ('スライド%d-%d' % (num(n), i), s)
    for n in sorted((x for x in names if re.match(r'ppt/notesSlides/notesSlide\d+\.xml$', x)), key=num):
        for i, s in enumerate(_a_paragraphs(z.read(n)), 1):
            yield ('ノート%d-%d' % (num(n), i), s)


def extract_vsdx(z):
    for n in sorted(x for x in z.namelist() if re.match(r'visio/pages/page\d+\.xml$', x)):
        try:
            root = ET.fromstring(z.read(n))
        except Exception:
            continue
        i = 0
        for el in root.iter():
            if _ln(el.tag) == 'Text':
                s = ''.join(el.itertext())
                if s.strip():
                    i += 1
                    yield ('%s-%d' % (os.path.basename(n).replace('.xml', ''), i), s)


def extract_ooxml(path):
    ext = os.path.splitext(path)[1].lower()
    with zipfile.ZipFile(path) as z:
        if ext.startswith('.xl'):
            gen = extract_xlsx(z)
        elif ext.startswith('.do'):
            gen = extract_docx(z)
        elif ext.startswith('.pp'):
            gen = extract_pptx(z)
        else:
            gen = extract_vsdx(z)
        for item in gen:
            yield item


_RE_ASCII_RUN = re.compile(rb'[\x20-\x7e]{5,}')
_RE_U16_RUN = re.compile(rb'(?:[\x20-\x7e]\x00|[\x00-\xff][\x30\x4e-\x9f\xff]){4,}')
_RE_HAS_ASCII3 = re.compile(r'[A-Za-z0-9_]{3}|[\u3040-\u30ff]{2}')


def extract_legacy(data):
    """旧形式 Office バイナリからの簡易文字列抽出（位置情報なし・取りこぼしあり）"""
    seen = set()
    n = 0
    for m in _RE_U16_RUN.finditer(data):
        try:
            s = m.group(0).decode('utf-16-le')
        except UnicodeDecodeError:
            continue
        if _RE_HAS_ASCII3.search(s) and s not in seen:
            seen.add(s)
            n += 1
            yield ('抽出#%d(概算位置 0x%X)' % (n, m.start()), s)
    for m in _RE_ASCII_RUN.finditer(data):
        s = m.group(0).decode('ascii')
        if s not in seen and re.search(r'[A-Za-z]{3}', s):
            seen.add(s)
            n += 1
            yield ('抽出#%d(概算位置 0x%X)' % (n, m.start()), s)


# ---------------------------------------------------------------------------
# スキャナ本体
# ---------------------------------------------------------------------------
class Scanner(object):
    def __init__(self, args):
        self.args = args
        self.findings = []
        self.files = []
        self.rule_by_id = {}
        self.by_target = {}
        confs = {'A', 'B'} | ({'C'} if args.audit else set())
        if args.no_heuristic:
            confs = {'A'}
        only = set(x.strip() for x in args.only.split(',')) if args.only else None
        skip = set(x.strip() for x in args.skip.split(',')) if args.skip else set()
        for r in RULES:
            fl = re.A if r['cs'] else FLAGS
            try:
                r['rx'] = re.compile(r['pattern'], fl)
                r['rx_doc'] = re.compile(r['doc'], fl) if r['doc'] else r['rx']
                r['rx_ex'] = re.compile(r['ex'], FLAGS) if r['ex'] else None
                r['rx_sect'] = re.compile(r['sect'], FLAGS) if r['sect'] else None
            except re.error as e:
                raise SystemExit('ルール %s の正規表現が不正: %s' % (r['id'], e))
            self.rule_by_id[r['id']] = r
            r['active'] = (r['conf'] in confs and (only is None or any(r['id'].startswith(o) for o in only))
                           and not any(r['id'].startswith(s) for s in skip))
        for t in 'PSICD':
            self.by_target[t] = [r for r in RULES if r['active'] and t in r['targets']]
        self.special_on = lambda rid: (only is None or any(rid.startswith(o) for o in only)) and not any(rid.startswith(s) for s in skip)

    # -- 結果登録 ----------------------------------------------------------
    def add(self, rid, sev, conf, ver, title, impact, fix, ref, finfo, loc, matched, excerpt, comment=''):
        self.findings.append(dict(sev=sev, conf=conf, id=rid, ver=ver, title=title, impact=impact, fix=fix, ref=ref,
                                  file=finfo['rel'], ftype=finfo['type'], enc=finfo['enc'], loc=loc,
                                  matched=_clip(matched, 80), excerpt=_clip(excerpt, self.args.excerpt), comment=comment))
        finfo['hits'] += 1

    def add_rule(self, r, finfo, loc, matched, excerpt, comment=''):
        self.add(r['id'], r['sev'], r['conf'], r['ver'], r['title'], r['impact'], r['fix'], r['ref'], finfo, loc, matched, excerpt, comment)

    def match_line(self, rules, text, finfo, loc, comment='', doc=False, section=None):
        if len(text) > 4000:
            text = text[:4000]
        for r in rules:
            m = (r['rx_doc'] if doc else r['rx']).search(text)
            if not m:
                continue
            if r['rx_ex'] is not None and r['rx_ex'].search(text):
                continue
            if r['rx_sect'] is not None and section is not None and not r['rx_sect'].search(section):
                continue
            self.add_rule(r, finfo, loc, m.group(0), text, comment)

    # -- ファイル走査 ------------------------------------------------------
    def scan_tree(self, root):
        root = os.path.abspath(root)
        excl = set(DEFAULT_EXCLUDE_DIRS) | set(x for x in (self.args.exclude_dir or []))
        items = []
        for dp, dns, fns in os.walk(root):
            dns[:] = sorted(d for d in dns if d not in excl)
            for fn in sorted(fns):
                path = os.path.join(dp, fn)
                items.append((path, os.path.relpath(path, root)))
        total = len(items)
        jobs = self.args.jobs
        if jobs <= 0:
            jobs = min(os.cpu_count() or 1, 8)
        t0 = time.time()
        print('  対象 %d ファイル / 並列数 %d' % (total, jobs if total >= 100 else 1), file=sys.stderr)
        if jobs > 1 and total >= 100:
            pool = None
            try:
                import multiprocessing
                pool = multiprocessing.Pool(jobs, _w_init, (self.args,))
            except Exception as e:
                print('  並列実行を開始できないため単一プロセスで続行: %s' % e, file=sys.stderr)
            if pool is not None:
                try:
                    for n, (fl, fd) in enumerate(pool.imap(_w_scan, items, 20), 1):
                        self.files.extend(fl)
                        self.findings.extend(fd)
                        if n % 500 == 0:
                            print('  ... %d/%d ファイル (%d 件検出, %.0f 秒)' % (n, total, len(self.findings), time.time() - t0), file=sys.stderr)
                finally:
                    pool.terminate()
                return
        for n, (path, rel) in enumerate(items, 1):
            if n % 200 == 0:
                print('  ... %d/%d ファイル (%d 件検出, %.0f 秒)' % (n, total, len(self.findings), time.time() - t0), file=sys.stderr)
            self.scan_one(path, rel)

    def scan_one(self, path, rel):
        try:
            self.scan_file(path, rel)
        except Exception as e:  # 1ファイルの失敗で全体を止めない
            self.files.append(dict(rel=rel, type='ERROR', enc='', hits=0, lines=0, status='読取エラー: %s' % e))

    def scan_file(self, path, rel):
        kind = classify(path)
        finfo = dict(rel=rel, type='', enc='', hits=0, lines=0, status='OK')
        try:
            size = os.path.getsize(path)
        except OSError as e:
            finfo.update(type='ERROR', status='読取エラー: %s' % e)
            self.files.append(finfo)
            return
        if kind == 'SKIP':
            if self.args.list_skipped:
                finfo.update(type='対象外', status='対象外(拡張子)')
                self.files.append(finfo)
            return
        if kind == 'UNSUP':
            finfo.update(type='設計書(未対応形式)', status='未対応形式: 目視確認が必要')
            self.files.append(finfo)
            return
        if size > self.args.max_size * 1024 * 1024:
            finfo.update(type=TYPE_LABEL.get(kind, kind), status='サイズ超過のためスキップ (%.1f MB)' % (size / 1048576.0))
            self.files.append(finfo)
            return
        if kind == 'DX':
            finfo['type'] = TYPE_LABEL['DX']
            self.files.append(finfo)
            try:
                n = 0
                for loc, text in extract_ooxml(path):
                    n += 1
                    self.scan_doc_text(text, finfo, loc)
                finfo['lines'] = n
            except zipfile.BadZipFile:
                finfo['status'] = '読取不可: ZIP として開けない（パスワード保護/破損の可能性）'
            except Exception as e:
                finfo['status'] = '読取エラー（一部のみ走査）: %s' % e
            return
        with open(path, 'rb') as f:
            data = f.read()
        if kind == 'DL':
            finfo['type'] = TYPE_LABEL['DL']
            finfo['status'] = '簡易抽出（位置は概算・取りこぼしあり。xlsx/docx へ変換して再走査を推奨）'
            self.files.append(finfo)
            n = 0
            for loc, text in extract_legacy(data):
                n += 1
                self.scan_doc_text(text, finfo, loc)
            finfo['lines'] = n
            return
        if kind == 'SNIFF':
            if looks_binary(data):
                if self.args.list_skipped:
                    finfo.update(type='対象外', status='対象外(バイナリ)')
                    self.files.append(finfo)
                return
            head = data[:4096]
            if b'<?' in head:
                kind = 'P'
            elif self.args.all_text:
                kind = 'D'
            else:
                if self.args.list_skipped:
                    finfo.update(type='対象外', status='対象外(未知の拡張子。--all-text で設計書扱い)')
                    self.files.append(finfo)
                return
        if looks_binary(data):
            finfo.update(type=TYPE_LABEL.get(kind, kind), status='バイナリのためスキップ')
            self.files.append(finfo)
            return
        text, enc = decode_bytes(data)
        finfo['type'] = TYPE_LABEL.get(kind, kind)
        finfo['enc'] = enc
        self.files.append(finfo)
        lines = [x.rstrip('\r') for x in text.split('\n')]
        finfo['lines'] = len(lines)
        if kind == 'P':
            self.scan_php(lines, finfo, enc)
        elif kind == 'S':
            self.scan_plain(lines, finfo, self.by_target['S'])
            if os.path.splitext(path)[1].lower() in ('.sql', '.ddl', '.dump'):
                self.check_create_table(lines, finfo)
        elif kind in ('I', 'C', 'IC'):
            self.scan_conf(lines, finfo, kind, os.path.basename(path).lower())
        elif kind == 'D':
            for i, ln in enumerate(lines, 1):
                if ln.strip():
                    self.scan_doc_text(ln, finfo, 'L%d' % i)

    # -- 設計書 ------------------------------------------------------------
    def scan_doc_text(self, text, finfo, loc):
        text = unicodedata.normalize('NFKC', text)
        rules = self.by_target['D']
        for part in text.splitlines():
            if part.strip():
                self.match_line(rules, part, finfo, loc, doc=True)

    # -- 汎用テキスト ------------------------------------------------------
    def scan_plain(self, lines, finfo, rules):
        for i, ln in enumerate(lines, 1):
            if ln.strip():
                s = ln.lstrip()
                cm = 'Y' if s.startswith(('--', '#', '//', 'REM ', 'rem ', '::')) else ''
                if cm and self.args.skip_comments:
                    continue
                self.match_line(rules, ln, finfo, 'L%d' % i, cm)

    # -- 設定ファイル ------------------------------------------------------
    def scan_conf(self, lines, finfo, kind, name):
        rules = []
        if kind in ('I', 'IC'):
            rules += self.by_target['I']
        if kind in ('C', 'IC'):
            rules += self.by_target['C']
        section = None
        seen_tz = False
        for i, ln in enumerate(lines, 1):
            s = ln.strip()
            if not s:
                continue
            m = re.match(r'^\[([^\]]+)\]', s)
            if m:
                section = m.group(1).strip()
            cm = 'Y' if s.startswith((';', '#')) else ''
            if cm:
                if self.args.skip_comments or kind != 'IC':
                    continue   # 設定ファイルのコメント行（無効化済み設定）は対象外
            if re.match(r'^\s*date\.timezone\s*=\s*["\']?\w', ln):
                seen_tz = True
            loc = 'L%d' % i + (' [%s]' % section if section else '')
            self.match_line(rules, ln, finfo, loc, cm, section=section if kind == 'C' else None)
        if kind == 'I' and name.startswith('php') and name.endswith('.ini') and not seen_tz and self.special_on('INI-TZ'):
            self.add('INI-TZ', '高', 'A', 'PHP7.0', 'date.timezone 未設定', '7.0 以降は無警告で UTC になり日時が 9 時間ずれる（サイレント）',
                     'date.timezone = Asia/Tokyo を設定', '§2-12 §3-8', finfo, '(ファイル全体)', '', 'date.timezone の有効な設定行なし')

    # -- PHP ---------------------------------------------------------------
    _STR = re.compile(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*\'''')
    _HEREDOC = re.compile(r'''<<<[ \t]*([r'"]?)([A-Za-z_]\w*)\1[ \t]*$''')
    _CLASS = re.compile(r'^\s*(?:abstract\s+|final\s+)*class\s+([A-Za-z_]\w*)', re.I)
    _FUNC = re.compile(r'\bfunction\s+&?\s*([A-Za-z_]\w*)\s*\(', re.I)
    _BT = re.compile(r'`[^`]+`')

    def scan_php(self, lines, finfo, enc):
        rules = self.by_target['P']
        a = self.args
        if enc.startswith(('SJIS', 'EUC', 'ISO-2022', '不明')) and self.special_on('ENC-01'):
            self.add('ENC-01', '高', 'A', 'PHP5.4+', 'ソースファイルが非 UTF-8 (%s)' % enc,
                     'zend.multibyte 未設定では SJIS の 5C 問題で Parse error。default_charset(UTF-8既定) と不整合で文字化け・htmlspecialchars が空文字',
                     'ソースを UTF-8(BOMなし) へ一括変換（暫定 zend.multibyte=On + zend.script_encoding）', '§2-11 §8-5', finfo, '(ファイル全体)', enc, '')
        if enc == 'UTF-8(BOM)' and self.special_on('ENC-02'):
            self.add('ENC-02', '中', 'A', '環境', 'UTF-8 BOM 付きソース', 'BOM が出力され header()/session_start() が失敗する', 'BOM を除去', '§8-5',
                     finfo, '(ファイル全体)', 'BOM', '')
        sjis = enc.startswith('SJIS')
        in_block = False
        hd = None
        cur_class = None
        for i, ln in enumerate(lines, 1):
            loc = 'L%d' % i
            s = ln.strip()
            if not s:
                continue
            # --- heredoc 追跡 ---
            if hd is not None:
                if re.match(r'^%s;?\s*$' % re.escape(hd), ln):
                    hd = None
                elif re.match(r'^[ \t]*%s(?![A-Za-z0-9_\x80-\uffff])' % re.escape(hd), ln) and self.special_on('PHP73-02'):
                    self.add('PHP73-02', '中', 'A', 'PHP7.3', 'ヒアドキュメント本文に終端識別子と同じ語で始まる行',
                             '7.3 以降はそこで終端とみなされ Parse error / 本文欠落', '識別子を一意な名前へ変更', '§4-28', finfo, loc, hd, ln)
                self.match_line(rules, ln, finfo, loc, '')
                continue
            m = self._HEREDOC.search(ln)
            # --- コメント判定 ---
            comment = ''
            if in_block:
                comment = 'Y'
                if '*/' in ln:
                    in_block = False
            else:
                nos = self._STR.sub('""', ln)
                if s.startswith(('//', '*', '/*')) or (s.startswith('#') and not s.startswith('#[')):
                    comment = 'Y'
                p = nos.rfind('/*')
                if p >= 0 and nos.find('*/', p) < 0:
                    in_block = True
                # --- バッククォート演算子 ---
                if not comment and '`' in nos and self.special_on('PHP85-02'):
                    code = re.sub(r'(?://|#).*$', '', nos)
                    mb = self._BT.search(code)
                    if mb:
                        self.add('PHP85-02', '低', 'B', 'PHP8.5', 'バッククォート演算子 `cmd` の可能性', 'Deprecated（shell_exec の別名）。JS テンプレート文字列等は対象外',
                                 'shell_exec() へ', '§7-24', finfo, loc, mb.group(0), ln)
            if m:
                hd = m.group(2)
            # --- PHP4 形式コンストラクタ ---
            mc = self._CLASS.match(ln)
            if mc:
                cur_class = mc.group(1).lower()
            if cur_class and 'unction' in ln:
                mf = None
                for mf in self._FUNC.finditer(ln):
                    if mf.group(1).lower() == cur_class:
                        break
                else:
                    mf = None
                if mf and mf.group(1).lower() == cur_class and not comment and self.special_on('PHP70-07'):
                    self.add('PHP70-07', '高', 'A', 'PHP7.0/8.0', 'PHP4 形式コンストラクタ（クラス名と同名のメソッド）',
                             '8.0 でコンストラクタとして呼ばれず初期化が走らない（サイレント）', '__construct() へリネーム（parent::クラス名() 呼び出しも修正）',
                             '§3-16 §5-14', finfo, loc, mf.group(0), ln)
            # --- SJIS 5C 問題 ---
            if sjis and any(ord(c) > 127 for c in ln):
                if self.special_on('ENC-03'):
                    bad = [c for c in ln if ord(c) > 0x7f and len(c.encode('cp932', 'ignore')) == 2 and c.encode('cp932', 'ignore')[1] == 0x5c]
                    if bad:
                        self.add('ENC-03', '高', 'B', 'PHP5.4+', 'SJIS の 5C 文字（%s）を含む行' % ''.join(sorted(set(bad)))[:40],
                                 '2バイト目が \\ (0x5C)。zend.multibyte なしでは文字列リテラルが壊れ Parse error / 文字化け',
                                 'ソースを UTF-8 化', '§2-11 §8-5', finfo, loc, ''.join(bad), ln, comment)
            if comment and a.skip_comments:
                continue
            self.match_line(rules, ln, finfo, loc, comment)

    # -- SQL: ENGINE 未指定の CREATE TABLE ---------------------------------
    def check_create_table(self, lines, finfo):
        if not self.special_on('SQL55-04'):
            return
        start = None
        buf = []
        for i, ln in enumerate(lines, 1):
            if start is None:
                if re.search(r'\bCREATE\s+(?:TEMPORARY\s+)?TABLE\b', ln, re.I):
                    start, buf = i, [ln]
            else:
                buf.append(ln)
            if start is not None and ';' in ln:
                stmt = ' '.join(buf)
                if not re.search(r'\b(?:ENGINE|TYPE)\s*=', stmt, re.I) and not re.search(r'\bCREATE\s+(?:TEMPORARY\s+)?TABLE\s+\S+\s+(?:LIKE|AS|SELECT)\b', stmt, re.I):
                    self.add('SQL55-04', '高', 'A', 'MySQL5.5', 'ENGINE 指定のない CREATE TABLE',
                             '5.1 では MyISAM、5.5 以降は InnoDB で作成される（FULLTEXT・ロック・AUTO_INCREMENT の挙動差）',
                             'ENGINE を明示', '§9-1', finfo, 'L%d' % start, '', buf[0])
                start, buf = None, []
            if start is not None and len(buf) > 2000:
                start, buf = None, []


_W = None


def _w_init(args):
    global _W
    _W = Scanner(args)


def _w_scan(item):
    _W.files, _W.findings = [], []
    _W.scan_one(item[0], item[1])
    return _W.files, _W.findings


def _clip(s, n):
    s = re.sub(r'\s+', ' ', s or '').strip()
    return s if len(s) <= n else s[:n] + '...'


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------
SEV_ORDER = {'高': 0, '中': 1, '低': 2}
CONF_LABEL = {'A': '確定', 'B': '要確認', 'C': '監査'}


def _xl(s):
    """Excel が数式として解釈しないようにする"""
    s = '' if s is None else str(s)
    return (' ' + s) if s[:1] in ('=', '+', '-', '@') else s


def write_csv(path, header, rows, enc):
    with io.open(path, 'w', encoding=enc, errors='replace', newline='') as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL, lineterminator='\r\n')
        w.writerow(header)
        for r in rows:
            w.writerow([_xl(x) for x in r])


def write_outputs(sc, outdir, root, elapsed):
    a = sc.args
    enc = 'cp932' if a.csv_encoding.lower() in ('cp932', 'sjis', 'shift_jis', 'ms932') else 'utf-8-sig'
    F = sorted(sc.findings, key=lambda x: (SEV_ORDER.get(x['sev'], 9), x['conf'], x['id'], x['file'], _lockey(x['loc'])))
    write_csv(os.path.join(outdir, 'findings.csv'),
              ['No', '重要度', '確度', 'ルールID', '導入Ver', 'ファイル', '位置', 'コメント行', '該当文字列', '行抜粋', '対象', '影響', '修正方針',
               'ガイド参照', 'ファイル種別', '文字コード', '判定(要対応/対応不要/保留)', '担当', '備考'],
              [[i, x['sev'], CONF_LABEL[x['conf']], x['id'], x['ver'], x['file'], x['loc'], x['comment'], x['matched'], x['excerpt'],
                x['title'], x['impact'], x['fix'], x['ref'], x['ftype'], x['enc'], '', '', ''] for i, x in enumerate(F, 1)], enc)

    cnt, fcnt = {}, {}
    for x in F:
        cnt[x['id']] = cnt.get(x['id'], 0) + 1
        fcnt.setdefault(x['id'], set()).add(x['file'])
    rows = []
    for r in RULES:
        rows.append([r['id'], r['ver'], r['sev'], CONF_LABEL[r['conf']], cnt.get(r['id'], 0), len(fcnt.get(r['id'], ())),
                     r['title'], r['impact'], r['fix'], r['ref'], r['targets'], '有効' if r['active'] else '無効(オプションにより除外)'])
    for sp in SPECIAL:
        rows.append([sp[0], sp[1], sp[2], CONF_LABEL[sp[3]], cnt.get(sp[0], 0), len(fcnt.get(sp[0], ())), sp[4], sp[5], sp[6], sp[7], sp[8],
                     '有効' if sc.special_on(sp[0]) else '無効(オプションにより除外)'])
    rows.sort(key=lambda r: (SEV_ORDER.get(r[2], 9), -r[4], r[0]))
    write_csv(os.path.join(outdir, 'summary.csv'),
              ['ルールID', '導入Ver', '重要度', '確度', '件数', 'ファイル数', '対象', '影響', '修正方針', 'ガイド参照', '適用種別(P/S/I/C/D)', '状態'], rows, enc)

    write_csv(os.path.join(outdir, 'files.csv'), ['ファイル', '種別', '文字コード', '行数/要素数', '検出件数', '状態'],
              [[f['rel'], f['type'], f['enc'], f['lines'], f['hits'], f['status']] for f in sorted(sc.files, key=lambda f: f['rel'])], enc)

    write_csv(os.path.join(outdir, 'manual_checklist.csv'), ['ID', '導入Ver', '重要度', '確認対象（機械検出不可）', '確認方法', 'ガイド参照', '結果', '備考'],
              [list(m) + ['', ''] for m in MANUAL], enc)

    write_html(sc, os.path.join(outdir, 'report.html'), root, F, rows, elapsed)


def _lockey(loc):
    m = re.match(r'L(\d+)', loc)
    return (0, int(m.group(1)), '') if m else (1, 0, loc)


def write_html(sc, path, root, F, sumrows, elapsed):
    a = sc.args
    e = html.escape
    sev_cnt = {}
    for x in F:
        k = (x['sev'], x['conf'])
        sev_cnt[k] = sev_cnt.get(k, 0) + 1
    by_rule = {}
    for x in F:
        by_rule.setdefault(x['id'], []).append(x)
    by_file = {}
    for x in F:
        by_file[x['file']] = by_file.get(x['file'], 0) + 1
    enc_cnt, type_cnt = {}, {}
    for f in sc.files:
        type_cnt[f['type']] = type_cnt.get(f['type'], 0) + 1
        if f['enc']:
            enc_cnt[f['enc']] = enc_cnt.get(f['enc'], 0) + 1
    o = []
    w = o.append
    w('<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><title>非互換スキャン結果</title><style>'
      'body{font-family:"Yu Gothic UI","Meiryo",sans-serif;font-size:13px;margin:20px;color:#222}'
      'h1{font-size:20px}h2{font-size:16px;border-bottom:2px solid #555;margin-top:28px;padding-bottom:3px}'
      'table{border-collapse:collapse;margin:8px 0}th,td{border:1px solid #bbb;padding:3px 7px;vertical-align:top;text-align:left}'
      'th{background:#eee;white-space:nowrap}td.n{text-align:right;white-space:nowrap}'
      '.s高{background:#f8d0d0;font-weight:bold}.s中{background:#fdecc0}.s低{background:#e4eefb}'
      'code{font-family:Consolas,"MS Gothic",monospace;font-size:12px;word-break:break-all}'
      'details{margin:6px 0;border:1px solid #ccc;padding:4px 8px}summary{cursor:pointer;font-weight:bold}'
      '.m{color:#666}.cm{color:#888}mark{background:#ffe54d}</style></head><body>')
    w('<h1>PHP 5.3→8.5 / MySQL 5.1→8.4 非互換スキャン結果</h1>')
    w('<p class="m">対象: <code>%s</code> ／ 実行: %s ／ 所要 %.1f 秒 ／ ツール v%s ／ 監査ルール: %s</p>'
      % (e(root), time.strftime('%Y-%m-%d %H:%M:%S'), elapsed, VERSION, '有効' if a.audit else '無効（--audit で有効化）'))
    w('<p>全件は <code>findings.csv</code>、ルール別は <code>summary.csv</code>、機械検出できない項目は <code>manual_checklist.csv</code> を参照。'
      '本レポートの明細は各ルール先頭 %d 件まで。</p>' % a.html_max)

    w('<h2>1. 件数サマリ</h2><table><tr><th>重要度</th><th>確定</th><th>要確認</th><th>監査</th><th>計</th></tr>')
    for s in ('高', '中', '低'):
        v = [sev_cnt.get((s, c), 0) for c in 'ABC']
        w('<tr><td class="s%s">%s</td><td class="n">%d</td><td class="n">%d</td><td class="n">%d</td><td class="n">%d</td></tr>' % (s, s, v[0], v[1], v[2], sum(v)))
    w('<tr><th>計</th><td class="n" colspan="4">%d 件 / %d ファイル走査（うち該当あり %d）</td></tr></table>' % (len(F), len(sc.files), len(by_file)))

    w('<h2>2. ファイル種別・文字コード</h2><table><tr><th>種別</th><th>ファイル数</th></tr>')
    for k, v in sorted(type_cnt.items(), key=lambda kv: -kv[1]):
        w('<tr><td>%s</td><td class="n">%d</td></tr>' % (e(k), v))
    w('</table><table><tr><th>文字コード</th><th>ファイル数</th></tr>')
    for k, v in sorted(enc_cnt.items(), key=lambda kv: -kv[1]):
        w('<tr><td>%s</td><td class="n">%d</td></tr>' % (e(k), v))
    w('</table>')
    bad = [f for f in sc.files if f['status'] != 'OK' and not f['status'].startswith('対象外')]
    if bad:
        w('<details><summary>未走査・要注意ファイル（%d 件）</summary><table><tr><th>ファイル</th><th>種別</th><th>状態</th></tr>' % len(bad))
        for f in bad[:2000]:
            w('<tr><td><code>%s</code></td><td>%s</td><td>%s</td></tr>' % (e(f['rel']), e(f['type']), e(f['status'])))
        w('</table></details>')

    w('<h2>3. ルール別件数（該当ありのみ）</h2><table><tr><th>ルールID</th><th>Ver</th><th>重要度</th><th>確度</th><th>件数</th><th>ファイル数</th><th>対象</th><th>影響</th><th>修正方針</th><th>参照</th></tr>')
    for r in sumrows:
        if r[4] == 0:
            continue
        w('<tr><td><a href="#r-%s">%s</a></td><td>%s</td><td class="s%s">%s</td><td>%s</td><td class="n">%d</td><td class="n">%d</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
          % (e(r[0]), e(r[0]), e(r[1]), r[2], r[2], r[3], r[4], r[5], e(r[6]), e(r[7]), e(r[8]), e(r[9])))
    w('</table>')
    zero = [r for r in sumrows if r[4] == 0 and r[11] == '有効']
    w('<details><summary>該当 0 件のルール（%d 件）</summary><p class="m">%s</p></details>' % (len(zero), e('、'.join('%s %s' % (r[0], r[6]) for r in zero))))

    w('<h2>4. 該当件数の多いファイル（上位 50）</h2><table><tr><th>ファイル</th><th>件数</th></tr>')
    for k, v in sorted(by_file.items(), key=lambda kv: -kv[1])[:50]:
        w('<tr><td><code>%s</code></td><td class="n">%d</td></tr>' % (e(k), v))
    w('</table>')

    w('<h2>5. 明細（ルール別）</h2>')
    for r in sumrows:
        rid = r[0]
        xs = by_rule.get(rid)
        if not xs:
            continue
        w('<details id="r-%s"><summary><span class="s%s">&nbsp;%s&nbsp;</span> %s %s — %d 件 [%s]</summary>' % (e(rid), r[2], r[2], e(rid), e(r[6]), len(xs), r[3]))
        w('<p><b>影響:</b> %s<br><b>修正方針:</b> %s<br><b>ガイド:</b> %s</p>' % (e(r[7]), e(r[8]), e(r[9])))
        w('<table><tr><th>ファイル</th><th>位置</th><th>行抜粋</th></tr>')
        for x in xs[:a.html_max]:
            ex = e(x['excerpt'])
            mt = e(x['matched'].rstrip('.'))
            if mt and mt in ex:
                ex = ex.replace(mt, '<mark>%s</mark>' % mt, 1)
            w('<tr%s><td><code>%s</code></td><td class="n">%s</td><td><code>%s</code></td></tr>'
              % (' class="cm"' if x['comment'] else '', e(x['file']), e(x['loc']), ex))
        w('</table>')
        if len(xs) > a.html_max:
            w('<p class="m">… 残り %d 件は findings.csv を参照</p>' % (len(xs) - a.html_max))
        w('</details>')

    w('<h2>6. 機械検出できない確認項目</h2><table><tr><th>ID</th><th>Ver</th><th>重要度</th><th>確認対象</th><th>確認方法</th><th>参照</th></tr>')
    for m in MANUAL:
        w('<tr><td>%s</td><td>%s</td><td class="s%s">%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (e(m[0]), e(m[1]), m[2], m[2], e(m[3]), e(m[4]), e(m[5])))
    w('</table>')
    w('<h2>7. 本ツールの限界</h2><ul>'
      '<li>行単位の正規表現照合。複数行にまたがる文、変数経由で組み立てられる SQL・関数名、eval は検出できない。</li>'
      '<li>型に依存する非互換（比較・算術・null 渡し・動的プロパティ等）は静的に判定できない。監査ルール（--audit）は候補を広く拾うのみ。</li>'
      '<li>「要確認」は誤検出を含む。「0 件」は該当なしの証明ではない（特に設計書は表記ゆれがある）。</li>'
      '<li>コメント行の判定は簡易（グレー表示）。旧形式 Office (xls/doc/ppt) は文字列の簡易抽出で位置は概算。PDF・画像・パスワード付きファイルは未対応。</li>'
      '</ul></body></html>')
    with io.open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(o))


def rules_markdown():
    def c(x):
        return (x or '').replace('|', '\\|').replace('\n', ' ')
    o = ['# ルール一覧', '',
         '`python incompat_scan.py --export-rules-md docs/RULES.md` で生成。手で編集しないこと。', '',
         '- 適用種別: P=PHPソース / S=SQL・スクリプト・汎用設定 / I=php.ini系 / C=my.cnf系 / D=設計書',
         '- 確度: 確定 / 要確認 / 監査（`--audit` 指定時のみ有効）', '',
         '## パターンルール（%d）' % len(RULES), '',
         '| ID | 導入Ver | 重要度 | 確度 | 種別 | 対象 | 影響 | 修正方針 |', '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for r in RULES:
        o.append('| %s | %s | %s | %s | %s | %s | %s | %s |' % (r['id'], c(r['ver']), r['sev'], CONF_LABEL[r['conf']], r['targets'],
                                                           c(r['title']), c(r['impact']), c(r['fix'])))
    o += ['', '## ファイル単位の特殊チェック（%d）' % len(SPECIAL), '',
          '| ID | 導入Ver | 重要度 | 確度 | 種別 | 対象 | 影響 | 修正方針 |', '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for sp in SPECIAL:
        o.append('| %s | %s | %s | %s | %s | %s | %s | %s |' % (sp[0], c(sp[1]), sp[2], CONF_LABEL[sp[3]], sp[8], c(sp[4]), c(sp[5]), c(sp[6])))
    o += ['', '## 機械検出できない確認項目（%d）' % len(MANUAL), '', '| ID | 導入Ver | 重要度 | 確認対象 | 確認方法 |', '| --- | --- | --- | --- | --- |']
    for m in MANUAL:
        o.append('| %s | %s | %s | %s | %s |' % (m[0], c(m[1]), m[2], c(m[3]), c(m[4])))
    return '\n'.join(o) + '\n'


# ---------------------------------------------------------------------------
def main():
    if sys.version_info < (3, 11):
        sys.exit('Python 3.11 以上が必要です（現在: %s）' % sys.version.split()[0])
    ap = argparse.ArgumentParser(description='PHP 5.3->8.5 / MySQL 5.1->8.4 非互換 該当箇所スキャナ (v%s)' % VERSION,
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument('root', nargs='?', help='調査対象フォルダ（ソース・設計書を含む）')
    ap.add_argument('-o', '--out', default='incompat_report', help='出力フォルダ（既定: ./incompat_report）')
    ap.add_argument('--audit', action='store_true', help='監査ルール（確度C: ==比較, count(), switch, LIMIT 等。件数大）も有効化')
    ap.add_argument('--no-heuristic', action='store_true', help='確定(A)ルールのみ')
    ap.add_argument('--only', help='ルールID前方一致で限定（カンマ区切り。例: PHP80,SQL,CNF）')
    ap.add_argument('--skip', help='ルールID前方一致で除外（カンマ区切り。例: DOC,PHPX-10）')
    ap.add_argument('--skip-comments', action='store_true', help='コメント行と判定した行を除外（既定は「コメント行=Y」を付けて出力）')
    ap.add_argument('--exclude-dir', action='append', help='除外するディレクトリ名（複数指定可。例: --exclude-dir vendor）')
    ap.add_argument('--all-text', action='store_true', help='未知の拡張子のテキストファイルも設計書として走査')
    ap.add_argument('--list-skipped', action='store_true', help='対象外としたファイルも files.csv に出力')
    ap.add_argument('--max-size', type=int, default=50, help='走査するファイルサイズ上限 MB（既定 50）')
    ap.add_argument('--excerpt', type=int, default=240, help='行抜粋の最大文字数（既定 240）')
    ap.add_argument('--html-max', type=int, default=200, help='report.html に載せるルール毎の明細件数（既定 200）')
    ap.add_argument('--csv-encoding', default='utf-8', help='CSV の文字コード: utf-8（BOM付き・既定）/ cp932')
    ap.add_argument('-j', '--jobs', type=int, default=0, help='並列プロセス数（既定 0 = CPU数に合わせ自動・最大8。1 で並列なし）')
    ap.add_argument('--export-rules-md', metavar='FILE', help='ルール一覧を Markdown で出力して終了（docs/RULES.md の生成用）')
    ap.add_argument('--version', action='version', version='incompat_scan ' + VERSION)
    ap.add_argument('--list-rules', action='store_true', help='ルール一覧を表示して終了')
    ap.add_argument('--dump-rules', metavar='FILE', help='ルール定義を JSON で出力して終了')
    args = ap.parse_args()

    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(errors='replace')
        except Exception:
            pass

    if args.dump_rules:
        keys = ('id', 'ver', 'sev', 'conf', 'targets', 'pattern', 'doc', 'ex', 'sect', 'cs', 'title', 'impact', 'fix', 'ref')
        with io.open(args.dump_rules, 'w', encoding='utf-8') as f:
            json.dump([dict((k, r[k]) for k in keys) for r in RULES], f, ensure_ascii=False, indent=1)
        print('%d ルールを %s に出力' % (len(RULES), args.dump_rules))
        return 0
    if args.export_rules_md:
        with io.open(args.export_rules_md, 'w', encoding='utf-8', newline='\n') as f:
            f.write(rules_markdown())
        print('%d ルールを %s に出力' % (len(RULES), args.export_rules_md))
        return 0
    sc = Scanner(args)
    if args.list_rules:
        for r in RULES:
            print('%-10s %-13s %s %s [%s] %s' % (r['id'], r['ver'], r['sev'], CONF_LABEL[r['conf']], r['targets'], r['title']))
        print('計 %d ルール（+ ファイル単位の特殊チェック %d 種、手動確認 %d 項目）' % (len(RULES), len(SPECIAL), len(MANUAL)))
        return 0
    if not args.root:
        ap.print_help()
        return 2
    if not os.path.isdir(args.root):
        print('フォルダが見つかりません: %s' % args.root, file=sys.stderr)
        return 2
    if not os.path.isdir(args.out):
        os.makedirs(args.out)
    out_abs = os.path.abspath(args.out)
    if out_abs.startswith(os.path.abspath(args.root) + os.sep):
        args.exclude_dir = (args.exclude_dir or []) + [os.path.basename(out_abs)]
    t0 = time.time()
    print('走査開始: %s' % os.path.abspath(args.root), file=sys.stderr)
    sc.scan_tree(args.root)
    el = time.time() - t0
    write_outputs(sc, args.out, os.path.abspath(args.root), el)
    n = {}
    for x in sc.findings:
        n[x['sev']] = n.get(x['sev'], 0) + 1
    print('完了: %d ファイル / %d 件（高 %d・中 %d・低 %d） %.1f 秒' % (len(sc.files), len(sc.findings), n.get('高', 0), n.get('中', 0), n.get('低', 0), el))
    print('出力: %s （report.html / findings.csv / summary.csv / files.csv / manual_checklist.csv）' % out_abs)
    return 0


if __name__ == '__main__':
    sys.exit(main())
