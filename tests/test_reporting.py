"""Period boundaries, access isolation, completion and reminder retry checks."""
import json
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch
import test_app as fixture
from backend.app import db, uid
from backend.reporting import period, deadline

class PeriodTests(unittest.TestCase):
    get=fixture.AppTests.get
    action=fixture.AppTests.action
    invite=fixture.AppTests.invite
    accept=fixture.AppTests.accept

    def setUp(self):
        fixture.AppTests.setUp(self)
        with db() as c:
            c.execute("DELETE FROM settings WHERE key LIKE 'completion:%' OR key LIKE 'reminder:%' OR key='reporting_config'")

    def test_calendar_boundaries(self):
        self.assertEqual(period(date(2027,1,1)),(date(2027,1,1),date(2027,3,31),'2027-Q1'))
        self.assertEqual(period(date(2026,12,31))[2],'2026-Q4')
        self.assertEqual(period(date(2028,2,10),'month')[1],date(2028,2,29))
        self.assertEqual(deadline(date(2026,3,31),'last_friday'),date(2026,3,27))
        self.assertEqual(deadline(date(2026,3,31),'day25'),date(2026,3,25))

    def test_dates_and_personal_history_never_expose_other_company(self):
        state=self.get()['state'];row=state['rows'][0];a,b=[x['id'] for x in state['companies'][:2]]
        self.action('row_save',{**row,'company_ids':[a,b],'company_prices':{a:'12',b:'999'}})
        stored=next(r for r in self.get()['state']['rows'] if r['id']==row['id'])
        self.assertIn('updated_at',stored);self.assertIn(a,stored['price_entered_at'])
        colleague=self.accept(self.invite([a]))
        report=colleague.get('/api/reporting').json()
        self.assertEqual(report['series'][-1]['total'],'12.00')
        self.assertNotIn('group_total',json.dumps(report));self.assertNotIn(b,json.dumps(report))
        self.assertEqual(len(report['series']),7);self.assertIsNone(report['series'][0]['total'])
        scoped=next(r for r in colleague.get('/api/state').json()['state']['rows'] if r['id']==row['id'])
        self.assertEqual(set(scoped['price_entered_at']),{a});self.assertNotIn('updated_by',scoped)
        self.assertEqual(colleague.post('/api/reporting/config',json={'frequency':'month','deadline':'day25','revision':self.get()['revision']}).status_code,403)

    def test_completion_requires_prices_and_tracks_period(self):
        co=self.get()['state']['companies'][0]['id'];colleague=self.accept(self.invite([co]));report=colleague.get('/api/reporting').json()
        body={'period':report['period'],'revision':self.get()['revision']}
        self.assertEqual(colleague.post('/api/reporting/complete',json=body).status_code,422)
        for row in self.get()['state']['rows']:
            if co in row['company_ids']:self.action('row_company_price',{'id':row['id'],'company_id':co,'price':'0'})
        body['revision']=self.get()['revision']
        self.assertEqual(colleague.post('/api/reporting/complete',json={**body,'period':'2000-Q1'}).status_code,409)
        self.assertEqual(colleague.post('/api/reporting/complete',json=body).status_code,200)
        self.assertIsNotNone(colleague.get('/api/reporting').json()['completion'])
        row=next(row for row in self.get()['state']['rows'] if co in row['company_ids'])
        self.action('row_company_price',{'id':row['id'],'company_id':co,'price':'1'})
        self.assertIsNone(colleague.get('/api/reporting').json()['completion'])

    def test_period_totals_use_last_snapshot_before_cutoff(self):
        state=self.get()['state'];co=state['companies'][0]['id'];state['rows'][0]['company_prices']={co:'10'}
        with db() as c:
            c.execute('DELETE FROM audit')
            for at,value in [('2026-06-30T21:59:00+00:00','10'),('2026-06-30T22:01:00+00:00','20')]:
                state['rows'][0]['company_prices']={co:value}
                c.execute('INSERT INTO audit(id,at,actor,label,before_data,after_data) VALUES(?,?,?,?,?,?)',(uid(),at,'test','price',json.dumps(state),json.dumps(state)))
        r=self.client.get('/api/reporting?company_id='+co).json()
        q2=next(p for p in r['series'] if p['key']=='2026-Q2');q3=next(p for p in r['series'] if p['key']=='2026-Q3')
        self.assertEqual(q2['total'],'10.00');self.assertEqual(q3['total'],'20.00')

    def test_config_revision_and_reminders_are_authorized_and_deduplicated(self):
        rev=self.get()['revision'];r=self.client.post('/api/reporting/config',json={'frequency':'month','deadline':'last_friday','revision':rev})
        self.assertEqual(r.status_code,200);self.assertEqual(self.get()['revision'],rev+1)
        self.assertEqual(self.client.post('/api/reporting/config',json={'frequency':'quarter','deadline':'day25','revision':rev}).status_code,409)
        self.assertEqual(self.client.get('/api/reminders').status_code,401)
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return datetime(2026,10,30,10,tzinfo=timezone.utc).astimezone(tz)
        env={'CRON_SECRET':'test-cron','TVE_SMTP_HOST':'smtp.example.test','TVE_SMTP_USER':'info@tve.nl','TVE_SMTP_PASSWORD':'test-only'}
        with patch.dict('os.environ',env),patch('backend.reporting.datetime',Clock),patch('backend.reporting.smtplib.SMTP') as smtp:
            first=self.client.get('/api/reminders',headers={'Authorization':'Bearer test-cron'})
            self.assertEqual(first.status_code,200,first.text);self.assertEqual(first.json()['sent'],1)
            second=self.client.get('/api/reminders',headers={'Authorization':'Bearer test-cron'})
            self.assertEqual(second.json()['sent'],0)
            mail=smtp.return_value.__enter__.return_value
            self.assertEqual(mail.send_message.call_count,1)
            self.assertEqual(mail.send_message.call_args.args[0]['From'],'info@tve.nl')

if __name__=='__main__':unittest.main()
