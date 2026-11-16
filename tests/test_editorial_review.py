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
    def test_numeric_policy_change_is_rejected_not_applied(self):
        class Bad(FakeClient):
            def complete(self,messages):return super().complete(messages).replace('حداقل 13 کاراکتر لازم است.", "reason"','حداقل 8 کاراکتر لازم است.", "reason"')
        report=review(self.src,self.root/'out',Bad(),now=NOW)
        text=accepted(xml(self.root/'out'/self.src.name))
        self.assertIn('حداقل 13 کاراکتر',text);self.assertNotIn('حداقل 8',text)
        self.assertEqual([f['kind'] for f in report['findings']].count('editorial'),0)
        self.assertEqual(len(report['rejected_suggestions']),1)
        self.assertIn('عدد',report['rejected_suggestions'][0]['reason_rejected'])
    def test_mismatched_source_is_rejected_not_fatal(self):
        class Bad:
            def complete(self,messages):return json.dumps({'edits':[{'paragraph_id':999,'before':'x','after':'y','reason':'z'}]})
        report=review(self.src,self.root/'out',Bad(),now=NOW)
        self.assertEqual(report['rejected_suggestions'][0]['paragraph'],999)
        self.assertEqual(report['summary']['findings_total'],3)  # dates only
    def test_one_bad_suggestion_does_not_block_good_ones(self):
        class Mixed(FakeClient):
            def complete(self,messages):
                data=json.loads(super().complete(messages))
                data['edits'].append({'paragraph_id':-5,'after':'x','reason':'y'})
                return json.dumps(data,ensure_ascii=False)
        report=review(self.src,self.root/'out',Mixed(),now=NOW)
        self.assertIn('می‌باشد',accepted(xml(self.root/'out'/self.src.name)))
        self.assertEqual(len(report['rejected_suggestions']),1)
    def test_reasoning_text_and_retry_are_tolerated(self):
        class Chatty(FakeClient):
            calls=0
            def complete(self,messages):
                Chatty.calls+=1
                if Chatty.calls==1:return 'not json at all'
                return '<think>checking</think>\nHere you go:\n'+super().complete(messages)+'\nDone.'
        report=review(self.src,self.root/'out',Chatty(),now=NOW)
        self.assertEqual(Chatty.calls,2);self.assertEqual(report['failed_batches'],[])
        self.assertIn('می‌باشد',accepted(xml(self.root/'out'/self.src.name)))
    def test_no_usable_llm_reply_writes_nothing(self):
        class Broken:
            def complete(self,messages):return 'sorry'
        with self.assertRaisesRegex(ValueError,'No usable LLM response'):review(self.src,self.root/'out',Broken(),now=NOW)
        self.assertFalse((self.root/'out'/self.src.name).exists())
    def test_bookmarks_and_rendered_page_breaks_stay_editable(self):
        root=xml(self.src)
        p=next(p for p in root.xpath('.//w:p',namespaces=NS) if 'ميباشد' in ''.join(p.xpath('.//w:t/text()',namespaces=NS)))
        first_run=p.find(W+'r')
        first_run.insert(1,etree.Element(W+'lastRenderedPageBreak'))
        p.insert(list(p).index(first_run),etree.Element(W+'bookmarkStart',{W+'id':'7',W+'name':'_Toc1'}))
        p.append(etree.Element(W+'bookmarkEnd',{W+'id':'7'}))
        rewritten=self.root/'bm.docx'
        with zipfile.ZipFile(self.src) as zin, zipfile.ZipFile(rewritten,'w') as zout:
            for e in zin.infolist():
                zout.writestr(e,etree.tostring(root) if e.filename=='word/document.xml' else zin.read(e.filename))
        rewritten=rewritten.rename(self.root/'SMIA.RG.17.Ver2.05-bm.docx')
        report=review(rewritten,self.root/'out',FakeClient(),now=NOW)
        out=xml(self.root/'out'/rewritten.name)
        self.assertIn('می‌باشد',accepted(out))
        self.assertTrue(out.xpath('.//w:bookmarkStart[@w:name="_Toc1"]',namespaces=NS))
        self.assertTrue(out.xpath('.//w:bookmarkEnd[@w:id="7"]',namespaces=NS))
        self.assertNotIn(next(b for b in report['findings'] if b['kind']=='editorial')['paragraph'],report['skipped_paragraphs'])
    def _long_doc(self, n=6):
        d=Document();d.add_paragraph('تاریخ:11/06/1404');d.add_paragraph('هدف')
        for i in range(n):d.add_paragraph('این پاراگراف شماره‌دار آزمایشی ميباشد و متن کافی دارد '+'الف'*i)
        d.save(self.src)
    def test_timeout_splits_batch_and_keeps_going(self):
        from llm_client import LLMRequestError
        self._long_doc()
        class Slow(FakeClient):
            sizes=[]
            def complete(self,messages):
                n=len(json.loads(messages[1]['content'])['paragraphs']);Slow.sizes.append(n)
                if n>2:raise LLMRequestError('Could not reach the internal LLM: The read operation timed out')
                return super().complete(messages)
        report=review(self.src,self.root/'out',Slow(),now=NOW,strict_dates=False)
        self.assertEqual(Slow.sizes,[6,3,1,2,3,1,2])
        self.assertEqual([f['kind'] for f in report['findings']].count('editorial'),6)
        self.assertEqual(report['failed_batches'],[])
    def test_single_paragraph_timeout_is_recorded_not_fatal(self):
        from llm_client import LLMRequestError
        self._long_doc(3)
        class OneBad(FakeClient):
            def complete(self,messages):
                paras=json.loads(messages[1]['content'])['paragraphs']
                if any('الفالف' in p['text'] for p in paras):raise LLMRequestError('timed out')
                return super().complete(messages)
        report=review(self.src,self.root/'out',OneBad(),now=NOW,strict_dates=False)
        self.assertEqual(len(report['failed_batches']),1)
        self.assertEqual([f['kind'] for f in report['findings']].count('editorial'),2)
    def test_llm_that_never_answers_aborts_without_output(self):
        from llm_client import LLMRequestError
        self._long_doc()
        class Dead:
            def complete(self,messages):raise LLMRequestError('timed out')
        with self.assertRaisesRegex(ValueError,'three times'):review(self.src,self.root/'out',Dead(),now=NOW,strict_dates=False)
        self.assertFalse((self.root/'out'/self.src.name).exists())
    def test_batch_size_env(self):
        import os
        from editorial_review import batch_chars
        os.environ['EDITORIAL_BATCH_CHARS']='800'
        try:self.assertEqual(batch_chars(),800)
        finally:del os.environ['EDITORIAL_BATCH_CHARS']
        self.assertEqual(batch_chars(),2500)
    def test_manually_numbered_headings_are_sections(self):
        from editorial_review import blocks_from, bare
        self.assertEqual(bare('۱. هدف'),'هدف');self.assertEqual(bare('5-2 الزامات عمومی'),'الزامات عمومی')
        d=Document();d.add_paragraph('تاریخ:11/06/1404');d.add_paragraph('۱. هدف')
        d.add_paragraph('۳) دامنه کاربرد');d.add_paragraph('این یک متن آزمایشی ميباشد و طولانی است.');d.save(self.src)
        blocks=blocks_from(xml(self.src))
        self.assertEqual(blocks[-1].section,'۳) دامنه کاربرد')
        report=review(self.src,self.root/'out',FakeClient(),now=NOW,strict_dates=False)
        self.assertIn('cover_date',report['date_fields_found'])
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
