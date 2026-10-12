"""Annual 2026 baseline, explicit quarterly measurements from 2027 and reminder checks."""
import json
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch
import test_app as fixture
from backend.app import db
from backend.reporting import period, deadline


def clock(day):
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return datetime.fromisoformat(day+'T10:00:00+00:00').astimezone(tz)
    return Clock


class PeriodTests(unittest.TestCase):
    get=fixture.AppTests.get
    action=fixture.AppTests.action
    invite=fixture.AppTests.invite
    accept=fixture.AppTests.accept

    def setUp(self):
        fixture.AppTests.setUp(self)
        with db() as c:
            c.execute("DELETE FROM settings WHERE key LIKE 'completion:%' OR key LIKE 'reminder:%' OR key='reporting_config'")

    def test_2026_is_one_annual_column_and_scopes_company_details(self):
        state=self.get()['state'];row=state['rows'][0];a,b=[x['id'] for x in state['companies'][:2]]
        self.action('row_save',{**row,'company_ids':[a,b],'company_prices':{a:'12',b:'999'}})
        colleague=self.accept(self.invite([a]));report=colleague.get('/api/reporting').json()
        self.assertEqual([p['key'] for p in report['series']],['2026'])
        self.assertTrue(report['informative_only']);self.assertIsNone(report['deadline'])
        self.assertEqual(report['series'][0]['total'],'12.00');self.assertEqual(report['series'][0]['group_total'],'1011.00')
        self.assertNotIn(b,json.dumps(report))
        self.assertEqual(colleague.get('/api/reporting?company_id='+b).json()['series'][0]['total'],'12.00')
        scoped=next(r for r in colleague.get('/api/state').json()['state']['rows'] if r['id']==row['id'])
        self.assertEqual(set(scoped['price_entered_at']),{a});self.assertNotIn('updated_by',scoped)
        self.assertEqual(colleague.post('/api/reporting/config',json={'frequency':'month','deadline':'day25','revision':self.get()['revision']}).status_code,403)
        self.assertEqual(colleague.post('/api/reporting/complete',json={'period':'2026','revision':self.get()['revision']}).status_code,422)

    def test_2026_effective_dates_do_not_split_or_add_versions_and_backup_restores(self):
        state=self.get()['state'];row=state['rows'][0];co=state['companies'][0]['id']
        for day,value in [('2026-07-01','30'),('2026-02-01','10'),('2026-05-01','20')]:
            self.action('row_company_price',{'id':row['id'],'company_id':co,'price':value,'effective_date':day})
        report=self.client.get('/api/reporting?company_id='+co).json()
        self.assertEqual(len(report['series']),1);self.assertEqual(report['series'][0]['total'],'20.00')
        self.action('row_company_price',{'id':row['id'],'company_id':co,'price':'31','effective_date':'2026-07-01'})
        self.assertEqual(self.client.get('/api/reporting?company_id='+co).json()['series'][0]['total'],'31.00')
        self.assertEqual(len(self.get()['state']['price_history']),3)
        backup=self.client.get('/api/backup');expected=self.get()['state']
        self.action('row_company_price',{'id':row['id'],'company_id':co,'price':'32','effective_date':'2026-07-01'})
        preview=self.client.post('/api/backup/preview',files={'file':('history.json',backup.content)})
        self.assertEqual(preview.status_code,200,preview.text)
        restored=self.client.post('/api/backup/restore',json={'token':preview.json()['token'],'revision':self.get()['revision']})
        self.assertEqual(restored.status_code,200,restored.text);self.assertEqual(restored.json()['state'],expected)

    def test_existing_dated_prices_preserve_the_current_annual_amount_until_corrected(self):
        state=self.get()['state'];row=state['rows'][0];co=state['companies'][0]['id']
        row['company_prices']={co:'30.00'}
        state['price_history']=[{'row_id':row['id'],'company_id':co,'date':day,'amount':amount,'recorded_at':recorded} for day,amount,recorded in [('2026-07-01','30.00','2026-10-01T10:00:00+00:00'),('2026-05-01','20.00','2026-10-02T10:00:00+00:00')]]
        with db() as c:c.execute('UPDATE store SET payload=? WHERE id=1',(json.dumps(state),))
        self.assertEqual(self.client.get('/api/reporting?company_id='+co).json()['series'][0]['total'],'30.00')
        self.action('row_company_price',{'id':row['id'],'company_id':co,'price':'8','effective_date':'2026-06-01'})
        self.assertEqual(self.client.get('/api/reporting?company_id='+co).json()['series'][0]['total'],'8.00')

    def test_2027_does_not_copy_annual_2026_into_quarters_or_fill_future_quarters(self):
        state=self.get()['state'];row=state['rows'][0];co=state['companies'][0]['id']
        self.action('row_company_price',{'id':row['id'],'company_id':co,'price':'100','effective_date':'2026-09-01'})
        Clock=clock('2027-04-15')
        with patch('backend.reporting.datetime',Clock),patch('backend.price_history.datetime',Clock):
            report=self.client.get('/api/reporting?company_id='+co).json()
            self.assertEqual([p['key'] for p in report['series']],['2026','2027-Q1','2027-Q2','2027-Q3','2027-Q4'])
            self.assertEqual(report['series'][0]['total'],'100.00')
            self.assertTrue(all(p['total'] is None for p in report['series'][1:]))
            self.action('row_company_price',{'id':row['id'],'company_id':co,'price':'7','effective_date':'2027-01-10'})
            report=self.client.get('/api/reporting?company_id='+co).json()
            self.assertEqual(report['series'][1]['total'],'7.00');self.assertIsNone(report['series'][2]['total'])
            self.action('row_company_price',{'id':row['id'],'company_id':co,'price':'9','effective_date':'2027-04-10'})
            report=self.client.get('/api/reporting?company_id='+co).json()
            self.assertEqual(report['series'][2]['total'],'9.00')
            for p in report['series'][3:]:self.assertTrue(p['future']);self.assertIsNone(p['total']);self.assertIsNone(p['group_total'])
            self.assertFalse(report['informative_only'])

    def test_2027_completion_requires_input_for_that_quarter_even_if_old_prices_exist(self):
        co=self.get()['state']['companies'][0]['id'];colleague=self.accept(self.invite([co]))
        Clock=clock('2027-04-15')
        with patch('backend.reporting.datetime',Clock),patch('backend.price_history.datetime',Clock):
            report=colleague.get('/api/reporting').json();body={'period':report['period'],'revision':self.get()['revision']}
            self.assertEqual(colleague.post('/api/reporting/complete',json=body).status_code,422)
            for row in self.get()['state']['rows']:
                if co in row['company_ids']:self.action('row_company_price',{'id':row['id'],'company_id':co,'price':'0','effective_date':'2027-04-10'})
            body['revision']=self.get()['revision']
            self.assertEqual(colleague.post('/api/reporting/complete',json={**body,'period':'2000-Q1'}).status_code,409)
            self.assertEqual(colleague.post('/api/reporting/complete',json=body).status_code,200)
            self.assertIsNotNone(colleague.get('/api/reporting').json()['completion'])

    def test_no_2026_reminders_then_2027_reminders_are_authorized_and_deduplicated(self):
        self.assertEqual(self.client.get('/api/reminders').status_code,401)
        env={'CRON_SECRET':'test-cron','TVE_SMTP_HOST':'smtp.example.test','TVE_SMTP_USER':'info@tve.nl','TVE_SMTP_PASSWORD':'test-only'}
        with patch.dict('os.environ',env),patch('backend.reporting.smtplib.SMTP') as smtp:
            early=self.client.get('/api/reminders',headers={'Authorization':'Bearer test-cron'})
            self.assertEqual(early.json()['sent'],0);smtp.assert_not_called()
            with patch('backend.reporting.datetime',clock('2027-03-25')):
                first=self.client.get('/api/reminders',headers={'Authorization':'Bearer test-cron'})
                self.assertEqual(first.status_code,200,first.text);self.assertEqual(first.json()['sent'],1)
                self.assertEqual(self.client.get('/api/reminders',headers={'Authorization':'Bearer test-cron'}).json()['sent'],0)
            mail=smtp.return_value.__enter__.return_value
            self.assertEqual(mail.send_message.call_count,1);self.assertEqual(mail.send_message.call_args.args[0]['From'],'info@tve.nl')

    def test_invalid_dates_and_setting_conflicts_are_rejected(self):
        state=self.get()['state'];row=state['rows'][0];co=state['companies'][0]['id']
        for day in ['', '2026-02-30','2099-01-01']:
            self.action('row_company_price',{'id':row['id'],'company_id':co,'price':'20','effective_date':day},expected=422)
        rev=self.get()['revision']
        self.assertEqual(self.client.post('/api/reporting/config',json={'frequency':'quarter','deadline':'last_friday','revision':rev}).status_code,200)
        self.assertEqual(self.client.post('/api/reporting/config',json={'frequency':'quarter','deadline':'day25','revision':rev}).status_code,409)

    def test_calendar_boundaries_and_2028_year_groups(self):
        self.assertEqual(period(date(2027,1,1)),(date(2027,1,1),date(2027,3,31),'2027-Q1'))
        self.assertEqual(period(date(2028,2,10),'month')[1],date(2028,2,29))
        self.assertEqual(deadline(date(2026,3,31),'last_friday'),date(2026,3,27))
        with patch('backend.reporting.datetime',clock('2028-04-15')):
            report=self.client.get('/api/reporting').json()
        self.assertEqual([p['key'] for p in report['series']],['2026']+[f'{year}-Q{q}' for year in [2027,2028] for q in range(1,5)])

if __name__=='__main__':unittest.main()
