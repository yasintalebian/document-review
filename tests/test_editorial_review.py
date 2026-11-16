import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
import zipfile
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree
from editorial_review import review, NS, W, jalali

NOW=datetime(2026,11,16,12,tzinfo=ZoneInfo('Asia/Tehran'))
class FakeClient:
    def complete(self,messages):
        assert 'approved_requirement' not in messages[1]['content']
        data=json.loads(messages[1]['content']);edits=[]
        for p in data['paragraphs']:
            if 'ميباشد' in p['text']:
                edits.append({'paragraph_id':p['paragraph_id'],'before':p['text'],
                    'after':p['text'].replace('ميباشد','می‌باشد'),'reason':'اصلاح نویسه و نیم‌فاصله'})
        return json.dumps({'edits':edits},ensure_ascii=False)

def fixture(path):
    d=Document();d.add_heading('خط‌مشی کلمه عبور',0)
    d.add_paragraph('کد مستند: SMIA.RG.17.Ver2.05')
    d.add_paragraph('تاریخ:11/06/1404')
    d.add_page_break();d.add_paragraph('شناسنامه سند')
    t=d.add_table(rows=1,cols=2);t.cell(0,0).text='زمان بازنگری سند';t.cell(0,1).text='11/06/1404'
    d.add_paragraph('تاییدیه سند')
    t=d.add_table(rows=2,cols=3)
    for c,v in zip(t.rows[0].cells,['','سمت سازمانی','تاریخ']):c.text=v
    for c,v in zip(t.rows[1].cells,['تصویب‌کننده','مدیر امنیت','12/06/1404']):c.text=v
    d.add_heading('هدف',1)
    d.add_heading('۵.۱ الزامات عمومی',2)
    p=d.add_paragraph();p.add_run('این یک متن آزمایشی ').bold=True;p.add_run('ميباشد و حداقل 13 کاراکتر لازم است.')
    d.save(path)

def xml(path,part='word/document.xml'):
    with zipfile.ZipFile(path) as z:return etree.fromstring(z.read(part))

def accepted(root):
    r=etree.fromstring(etree.tostring(root))
    for node in r.xpath('.//w:del',namespaces=NS):node.getparent().remove(node)
    return ''.join(r.xpath('.//w:t/text()',namespaces=NS))

class EditorialTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.src=self.root/'SMIA.RG.17.Ver2.05.docx';fixture(self.src)
    def tearDown(self):self.temp.cleanup()
    def test_end_to_end_dates_filename_and_revisions(self):
        digest=hashlib.sha256(self.src.read_bytes()).hexdigest()
        report=review(self.src,self.root/'out',FakeClient(),now=NOW)
        output=self.root/'out'/self.src.name
        self.assertTrue(output.exists());self.assertEqual(hashlib.sha256(self.src.read_bytes()).hexdigest(),digest)
        self.assertNotIn('iso_findings',report)
        self.assertEqual(report['summary']['findings_total'],4)
        content=xml(output);text=accepted(content)
        self.assertIn('25/08/1405',text);self.assertNotIn('12/06/1404',text)
        self.assertIn('می‌باشد',text);self.assertNotIn('ميباشد',text)
        self.assertEqual(len(content.xpath('.//w:p',namespaces=NS)),len(xml(self.src).xpath('.//w:p',namespaces=NS)))
        self.assertTrue(content.xpath('.//w:ins',namespaces=NS));self.assertTrue(content.xpath('.//w:del',namespaces=NS))
        self.assertTrue(xml(output,'word/settings.xml').xpath('./w:trackRevisions',namespaces=NS))
        self.assertTrue(content.xpath('.//w:r[w:rPr/w:b]/w:t',namespaces=NS))
        entry=next(f for f in report['findings'] if f['kind']=='editorial')
        self.assertEqual(entry['clause'],'۵.۱ الزامات عمومی');self.assertEqual(entry['page_source'],'cached_layout_estimate')
    def test_rejects_numeric_policy_change_without_output(self):
        class Bad(FakeClient):
            def complete(self,messages):return super().complete(messages).replace('حداقل 13 کاراکتر لازم است.", "reason"','حداقل 8 کاراکتر لازم است.", "reason"')
        with self.assertRaises(ValueError):review(self.src,self.root/'out',Bad(),now=NOW)
        self.assertFalse((self.root/'out'/self.src.name).exists())
    def test_rejects_mismatched_source(self):
        class Bad:
            def complete(self,messages):return json.dumps({'edits':[{'paragraph_id':999,'before':'x','after':'y','reason':'z'}]})
        with self.assertRaises(ValueError):review(self.src,self.root/'out',Bad(),now=NOW)
    def test_missing_dates_fail_before_llm(self):
        d=Document();d.add_paragraph('متن ساده');d.save(self.src)
        with self.assertRaisesRegex(ValueError,'Date fields'):review(self.src,self.root/'out',FakeClient(),now=NOW)
    def test_no_page_guess_when_no_layout_markers(self):
        d=Document();d.add_paragraph('این یک متن آزمایشی ميباشد.');d.save(self.src)
        report=review(self.src,self.root/'out',FakeClient(),now=NOW,strict_dates=False)
        self.assertIsNone(report['findings'][0]['page']);self.assertEqual(report['findings'][0]['page_source'],'unavailable')
    def test_output_cannot_overwrite(self):
        with self.assertRaises(ValueError):review(self.src,self.root,FakeClient(),now=NOW)
        review(self.src,self.root/'out',FakeClient(),now=NOW)
        with self.assertRaises(FileExistsError):review(self.src,self.root/'out',FakeClient(),now=NOW)
    def test_rejects_existing_revisions(self):
        review(self.src,self.root/'out',FakeClient(),now=NOW)
        with self.assertRaisesRegex(ValueError,'tracked changes'):review(self.root/'out'/self.src.name,self.root/'again',FakeClient(),now=NOW)
    def test_publish_preserves_filename_and_is_idempotent(self):
        from editorial_review import publish
        review(self.src,self.root/'out',FakeClient(),now=NOW)
        outbox=self.root/'outbox';outbox.mkdir()
        first=publish(self.root/'out',outbox)
        self.assertEqual(first,publish(self.root/'out',outbox))
        manifest=json.loads((first/'manifest.json').read_text())
        self.assertEqual(manifest['source_filename'],self.src.name)
        self.assertTrue((first/self.src.name).exists())
        self.assertEqual(len(list(outbox.iterdir())),1)

    def test_exact_page_map_is_bound_to_paragraph(self):
        from editorial_review import blocks_from
        blocks=blocks_from(xml(self.src))
        b=next(b for b in blocks if 'ميباشد' in b.text)
        mapping={str(b.index):{'text_sha256':hashlib.sha256(b.text.encode()).hexdigest(),'page':7}}
        report=review(self.src,self.root/'out',FakeClient(),now=NOW,page_map=mapping)
        e=next(f for f in report['findings'] if f['kind']=='editorial')
        self.assertEqual(e['page'],7);self.assertEqual(e['page_source'],'verified_source_page_map')

    def test_bad_page_map_rejected(self):
        with self.assertRaisesRegex(ValueError,'page-map'):
            review(self.src,self.root/'out',FakeClient(),now=NOW,page_map={'0':{'text_sha256':'wrong','page':1}})

    def test_rejecting_all_changes_restores_original_text(self):
        review(self.src,self.root/'out',FakeClient(),now=NOW)
        root=xml(self.root/'out'/self.src.name)
        for node in root.xpath('.//w:ins',namespaces=NS):node.getparent().remove(node)
        rejected=''.join(root.xpath('.//w:t/text() | .//w:delText/text()',namespaces=NS))
        original=''.join(xml(self.src).xpath('.//w:t/text()',namespaces=NS))
        self.assertEqual(rejected,original)

    def test_jalali_date(self):self.assertEqual(jalali(2026,11,16),(1405,8,25))
