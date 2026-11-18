# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""フィクスチャを一時フォルダに生成してスキャンし、期待するルールが検出されることを確認する。"""
import csv
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, 'incompat_scan.py')
sys.path.insert(0, ROOT)
import incompat_scan  # noqa: E402

PHP = r'''<?
require_once 'DB.php';
$link = mysql_connect($host, $user, $pass) or die(mysql_error());
mysql_query("SET NAMES sjis");
if (get_magic_quotes_gpc()) { $q = stripslashes($_GET['q']); }
$res = mysql_query("SELECT SQL_CALC_FOUND_ROWS user_id FROM (SELECT * FROM logs ORDER BY created DESC) x GROUP BY user_id DESC LIMIT 10");
while (list($k, $v) = each($arr)) { echo $str{0}; }
$s = ereg_replace("[0-9]+", "", $s);
$a = split(",", $csv);
$x = preg_replace('/(\d+)/e', 'foo("\\1")', $s);
$y = $a ? 1 : $b ? 2 : 3;
echo "total: " . $a + $b;
if ($row['status'] == 0) { $n = count($rows); }
$v = (integer)$_POST['v'];
$out = `ls -la`;
$sql = "SELECT `id` FROM t WHERE rank = 1 AND d = '0000-00-00'";
$enc = mcrypt_encrypt(MCRYPT_RIJNDAEL_256, $key, $data, MCRYPT_MODE_CBC);
echo htmlspecialchars($_GET['name']);
function f(Foo $x = null) {}
$obj->$name['key'] = 1;
class User { function User($id) { $this->id = $id; } function __sleep() { return array(); } }
$html = <<<EOT
 EOT is here
EOT;
$pdo = new PDO("mysql:host=localhost;dbname=app", $u, $p);
switch ($x) { case 1; break; }
foo($a, &$b);
ini_set('mbstring.func_overload', 2);
'''

PHP_CLEAN = r'''<?php
$obj->each(function () {});
$list->split(',');
Foo::count($x);
$sql = "SELECT `id`, `rank` FROM t";
$s = "{$a}{$b}";
$n = $a ? 1 : ($b ? 2 : 3);
function g(?Foo $x = null) {}
$v = (int)$_POST['v'];
'''

SQL = '''CREATE TABLE users (
  id int(11) NOT NULL auto_increment,
  rank int NOT NULL,
  updated timestamp NOT NULL,
  created datetime NOT NULL default '0000-00-00 00:00:00',
  PRIMARY KEY (id)
) TYPE=MyISAM DEFAULT CHARSET=latin1;
CREATE TABLE t2 (id int, body text, FULLTEXT(body));
GRANT ALL ON app.* TO 'app'@'%' IDENTIFIED BY 'pw';
SHOW SLAVE STATUS;
'''

MYCNF = '''[client]
default-character-set = utf8
[mysqld]
default-character-set = sjis
skip-locking
key_buffer = 16M
query_cache_size = 32M
# log-slow-queries = /var/log/slow.log
expire_logs_days = 7
innodb_log_file_size = 256M
skip-character-set-client-handshake
sql_mode = NO_AUTO_CREATE_USER,NO_ENGINE_SUBSTITUTION
[mysqld_safe]
log-error=/var/log/mysqld.log
'''

PHPINI = '''register_globals = On
short_open_tag = On
;date.timezone =
mbstring.internal_encoding = EUC-JP
error_reporting = E_ALL & ~E_STRICT
extension=mysql.so
zend_extension=opcache.so
'''

NS_S = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'


def make_xlsx(path):
    ss = ('<sst xmlns="%s"><si><t>テーブル定義</t><rPh sb="0" eb="4"><t>mysql_query</t></rPh></si>'
          '<si><r><t>エンジン: </t></r><r><t>MyISAM、照合順序 utf8_general_ci</t></r></si>'
          '<si><t>SELECT * FROM m_user GROUP BY dept_id\n※ register_globals=On 前提</t></si></sst>') % NS_S
    wb = ('<workbook xmlns="%s" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
          '<sheets><sheet name="DB定義" sheetId="1" r:id="rId1"/></sheets></workbook>') % NS_S
    rel = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
           '<Relationship Id="rId1" Type="x" Target="%s"/></Relationships>')
    sh = ('<worksheet xmlns="%s"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
          '<row r="2"><c r="C2" t="s"><v>2</v></c><c r="D2"><v>5.3</v></c></row></sheetData></worksheet>') % NS_S
    dr = ('<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
          'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><xdr:sp><xdr:txBody><a:p><a:r>'
          '<a:t>セッションは session_register で</a:t></a:r><a:r><a:t>管理する</a:t></a:r></a:p></xdr:txBody></xdr:sp></xdr:wsDr>')
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('xl/sharedStrings.xml', ss)
        z.writestr('xl/workbook.xml', wb)
        z.writestr('xl/_rels/workbook.xml.rels', rel % 'worksheets/sheet1.xml')
        z.writestr('xl/worksheets/sheet1.xml', sh)
        z.writestr('xl/worksheets/_rels/sheet1.xml.rels', rel % '../drawings/drawing1.xml')
        z.writestr('xl/drawings/drawing1.xml', dr)


def make_docx(path):
    d = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
         '<w:p><w:r><w:t>暗号化は mcrypt (</w:t></w:r><w:r><w:t>MCRYPT_RIJNDAEL_256) を使用。</w:t></w:r></w:p>'
         '<w:p><w:r><w:t>my.cnf: skip-character-set-client-handshake を設定</w:t></w:r></w:p></w:body></w:document>')
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('word/document.xml', d)


def write(path, text, enc='utf-8'):
    d = os.path.dirname(path)
    if not os.path.isdir(d):
        os.makedirs(d)
    with io.open(path, 'w', encoding=enc, newline='\n') as f:
        f.write(text)


class ScanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='incompat_scan_test_')
        src = os.path.join(cls.tmp, 'target')
        write(os.path.join(src, 'src', 'index.php'), PHP)
        write(os.path.join(src, 'src', 'clean.php'), PHP_CLEAN)
        write(os.path.join(src, 'src', 'lib', 'sjis.php'), u'<?php\n$s = "表示 ソフト";\necho mysql_real_escape_string($s);\n', 'cp932')
        write(os.path.join(src, 'src', 'schema.sql'), SQL)
        write(os.path.join(src, 'src', '.htaccess'), 'php_value mbstring.func_overload 2\n')
        write(os.path.join(src, 'conf', 'my.cnf'), MYCNF)
        write(os.path.join(src, 'conf', 'php.ini'), PHPINI)
        write(os.path.join(src, 'doc', 'memo.txt'),
              u'本システムはＰＨＰ５．３、ＭｙＳＱＬ５．１（MyISAM）で稼働。文字コードはShift_JIS。\n'
              u'ログイン時は ｍｙｓｑｌ＿ｑｕｅｒｙ関数で PASSWORD() を照合する。\n')
        make_xlsx(os.path.join(src, 'doc', 'db.xlsx'))
        make_docx(os.path.join(src, 'doc', 'basic.docx'))
        with open(os.path.join(src, 'doc', 'old.xls'), 'wb') as f:
            f.write(b'\xd0\xcf\x11\xe0' + b'\x00' * 40 + u'関数 mysql_pconnect を使用 TYPE=MyISAM'.encode('utf-16-le') + b'\x00' * 8)
        with open(os.path.join(src, 'doc', 'locked.xlsx'), 'wb') as f:
            f.write(b'\xd0\xcf\x11\xe0' + b'\x00' * 100)
        with open(os.path.join(src, 'doc', 'spec.pdf'), 'wb') as f:
            f.write(b'%PDF-1.4')
        cls.out = os.path.join(cls.tmp, 'out')
        p = subprocess.run([sys.executable, '-W', 'error', SCRIPT, src, '-o', cls.out, '--audit', '-j', '1'],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert p.returncode == 0, p.stderr.decode('utf-8', 'replace')
        with io.open(os.path.join(cls.out, 'findings.csv'), encoding='utf-8-sig', newline='') as f:
            cls.rows = list(csv.DictReader(f))
        with io.open(os.path.join(cls.out, 'files.csv'), encoding='utf-8-sig', newline='') as f:
            cls.files = dict((r[u'ファイル'].replace('\\', '/'), r) for r in csv.DictReader(f))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def ids(self, suffix):
        return set(r[u'ルールID'] for r in self.rows if r[u'ファイル'].replace('\\', '/').endswith(suffix))

    def hit(self, suffix, rid):
        return [r for r in self.rows if r[u'ルールID'] == rid and r[u'ファイル'].replace('\\', '/').endswith(suffix)]

    def test_php_rules(self):
        expected = {'PHPX-01', 'PHP55-01', 'LNK-01', 'LNK-02', 'PHP54-02', 'SQL80-01', 'SQL57-01', 'SQL57-03', 'PHP72-04',
                    'PHP74-01', 'PHP70-01', 'PHP55-02', 'PHP74-02', 'PHP74-03', 'PHP80-01', 'PHP72-01', 'PHP85-01',
                    'PHP85-02', 'SQL80-09b', 'SQL57-02', 'PHP55-03', 'PHP54-04', 'PHP81-01', 'PHP84-01', 'PHP70-05',
                    'PHP70-07', 'PHP85-03', 'PHP73-02', 'PHP80-14', 'PHP85-04', 'PHP54-03', 'INI-01p', 'PHP74-09'}
        self.assertEqual(expected - self.ids('src/index.php'), set())

    def test_no_false_positive_on_clean_code(self):
        self.assertEqual(self.ids('src/clean.php'), set())

    def test_sjis_source(self):
        ids = self.ids('lib/sjis.php')
        self.assertIn('ENC-01', ids)
        self.assertIn('ENC-03', ids)
        self.assertIn('PHP55-01', ids)
        self.assertTrue(self.files['src/lib/sjis.php'][u'文字コード'].startswith('SJIS'))

    def test_sql(self):
        expected = {'SQL55-01', 'SQL55-04', 'SQL56-01', 'SQL56-04', 'SQL57-02', 'SQL80-09', 'SQL80-10b', 'SQL84-01', 'SQL55-05'}
        self.assertEqual(expected - self.ids('schema.sql'), set())

    def test_mycnf(self):
        ids = self.ids('conf/my.cnf')
        self.assertEqual({'CNF-55', 'CNF-55b', 'CNF-57b', 'CNF-57c', 'CNF-80', 'CNF-84', 'CNF-DEP', 'SQL80-06'} - ids, set())
        # [client] 節の default-character-set は CNF-55b の対象外、コメント行は対象外
        locs = [r[u'位置'] for r in self.hit('conf/my.cnf', 'CNF-55b')]
        self.assertEqual(len(locs), 1)
        self.assertIn('[mysqld]', locs[0])
        self.assertFalse(any('log-slow' in r[u'該当文字列'] for r in self.rows))
        # innodb_log_file_size は 8.4 で削除ではなく非推奨
        self.assertTrue(any('innodb_log_file_size' in r[u'該当文字列'] for r in self.hit('conf/my.cnf', 'CNF-DEP')))

    def test_phpini(self):
        ids = self.ids('conf/php.ini')
        self.assertEqual({'INI-01', 'INI-02', 'INI-03', 'INI-05', 'INI-06', 'INI-TZ', 'PHP84-02'} - ids, set())
        self.assertIn('INI-04', self.ids('.htaccess'))

    def test_design_docs(self):
        self.assertEqual({'DOC-01', 'DOC-02', 'PHP55-01', 'SQL57-04', 'SQL55-02'} - self.ids('doc/memo.txt'), set())
        x = self.ids('doc/db.xlsx')
        self.assertEqual({'SQL55-02', 'SQL57-01b', 'INI-01', 'PHP54-06', 'SQL80-10'} - x, set())
        self.assertNotIn('PHP55-01', x)  # ふりがな (rPh) は対象外
        self.assertEqual(self.hit('doc/db.xlsx', 'SQL57-01b')[0][u'位置'], u'DB定義!C2')
        self.assertTrue(self.hit('doc/db.xlsx', 'PHP54-06')[0][u'位置'].startswith(u'DB定義!図形'))
        self.assertEqual({'PHP55-03', 'CNF-84'} - self.ids('doc/basic.docx'), set())
        self.assertEqual({'PHP55-01', 'SQL55-01'} - self.ids('doc/old.xls'), set())

    def test_unreadable_files_are_listed(self):
        self.assertIn(u'読取不可', self.files['doc/locked.xlsx'][u'状態'])
        self.assertIn(u'未対応', self.files['doc/spec.pdf'][u'状態'])

    def test_outputs_exist(self):
        for name in ('report.html', 'summary.csv', 'files.csv', 'manual_checklist.csv'):
            self.assertTrue(os.path.getsize(os.path.join(self.out, name)) > 0, name)


class RuleTableTest(unittest.TestCase):
    def test_rule_ids_unique(self):
        ids = [r['id'] for r in incompat_scan.RULES] + [s[0] for s in incompat_scan.SPECIAL]
        self.assertEqual(len(ids), len(set(ids)))

    def test_rules_have_no_capturing_groups(self):
        import re
        for r in incompat_scan.RULES:
            for key in ('pattern', 'doc'):
                if r[key]:
                    self.assertEqual(re.compile(r[key]).groups, 0, r['id'])

    def test_rules_md_is_up_to_date(self):
        with io.open(os.path.join(ROOT, 'docs', 'RULES.md'), encoding='utf-8') as f:
            self.assertEqual(f.read(), incompat_scan.rules_markdown(),
                             'docs/RULES.md が古い: python incompat_scan.py --export-rules-md docs/RULES.md')


if __name__ == '__main__':
    unittest.main()
