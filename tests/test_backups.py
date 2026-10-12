"""Snapshot retention, durable restore and protected administrative operations."""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
import test_app as fixture
from backend.app import db


def clock(day):
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return datetime.fromisoformat(day+'T04:00:00+00:00').astimezone(tz)
    return Clock


class BackupTests(unittest.TestCase):
    get=fixture.AppTests.get
    action=fixture.AppTests.action
    invite=fixture.AppTests.invite
    accept=fixture.AppTests.accept

    def setUp(self):
        fixture.AppTests.setUp(self)
        with db() as c:
            c.execute('DELETE FROM backup_snapshots')
            c.execute("DELETE FROM settings WHERE key LIKE 'backup_month:%' OR key='reporting_config' OR key LIKE 'completion:%'")

    def create(self):
        r=self.client.post('/api/backups',json={'revision':self.get()['revision']})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()['id']

    def test_manual_snapshots_keep_only_seven_including_extras(self):
        ids=[self.create() for _ in range(9)]
        response=self.client.get('/api/backups');self.assertEqual(response.status_code,200)
        listing=response.json();self.assertEqual(listing['limit'],7)
        self.assertEqual([r['id'] for r in listing['backups']],list(reversed(ids[2:])))
        self.assertNotIn('payload',response.text);self.assertNotIn('checksum',response.text)

    def test_first_day_is_once_per_month_even_after_rotation_and_uses_amsterdam_date(self):
        with patch.dict('os.environ',{'CRON_SECRET':''}):
            with patch('backend.backups.datetime',clock('2026-11-02')):
                self.assertFalse(self.client.get('/api/backups/monthly').json()['created'])
            class Boundary(datetime):
                @classmethod
                def now(cls,tz=None):return datetime(2026,10,31,23,30,tzinfo=timezone.utc).astimezone(tz)
            with patch('backend.backups.datetime',Boundary):
                self.assertTrue(self.client.get('/api/backups/monthly').json()['created'])
            with patch('backend.backups.datetime',clock('2026-11-01')):
                self.assertFalse(self.client.get('/api/backups/monthly').json()['created'])
                for _ in range(8):self.create()
                self.assertFalse(self.client.get('/api/backups/monthly').json()['created'])
            with patch('backend.backups.datetime',clock('2026-12-01')):
                self.assertTrue(self.client.get('/api/backups/monthly').json()['created'])
        listing=self.client.get('/api/backups').json()['backups']
        self.assertEqual(len(listing),7);self.assertEqual(listing[0]['kind'],'monthly')

    def test_restore_oldest_snapshot_preserves_safety_copy_history_settings_and_login(self):
        before=self.get()['state'];backup_id=self.create()
        co=before['companies'][0]['id'];row=before['rows'][0]
        self.action('row_company_price',{'id':row['id'],'company_id':co,'price':'42','effective_date':'2026-09-01'})
        changed=self.get()['state']
        revision=self.get()['revision']
        self.assertEqual(self.client.post('/api/reporting/config',json={'frequency':'month','deadline':'last_friday','revision':revision}).status_code,200)
        for _ in range(6):self.create()
        revision=self.get()['revision']
        r=self.client.post('/api/backups/'+backup_id+'/restore',json={'revision':revision,'confirmed':True})
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['state'],before)
        self.assertEqual(r.json()['revision'],revision+1)
        self.assertEqual(self.client.get('/api/reporting').json()['config']['frequency'],'quarter')
        listing=self.client.get('/api/backups').json()['backups']
        self.assertEqual(len(listing),7);self.assertEqual(listing[0]['kind'],'before_restore')
        self.assertEqual(listing[0]['id'],r.json()['safety_backup_id'])
        r=self.client.post('/api/backups/'+listing[0]['id']+'/restore',json={'revision':self.get()['revision'],'confirmed':True})
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['state'],changed)
        self.assertEqual(self.client.get('/api/reporting').json()['config']['frequency'],'month')
        self.assertEqual(self.client.get('/api/auth/status').json()['user']['role'],'admin')

    def test_access_confirmation_and_stale_revision_are_required(self):
        from fastapi.testclient import TestClient
        from backend.app import app
        self.assertEqual(TestClient(app).get('/api/backups').status_code,401)
        backup_id=self.create();colleague=self.accept(self.invite())
        self.assertEqual(colleague.get('/api/backups').status_code,403)
        self.assertEqual(colleague.post('/api/backups',json={'revision':self.get()['revision']}).status_code,403)
        self.assertEqual(colleague.post('/api/backups/'+backup_id+'/restore',json={'revision':self.get()['revision'],'confirmed':True}).status_code,403)
        rev=self.get()['revision']
        self.assertEqual(self.client.post('/api/backups/'+backup_id+'/restore',json={'revision':rev}).status_code,422)
        self.action('entity_save',{'kind':'categories','name':'Na de back-up'})
        self.assertEqual(self.client.post('/api/backups/'+backup_id+'/restore',json={'revision':rev,'confirmed':True}).status_code,409)
        self.assertEqual(len(self.client.get('/api/backups').json()['backups']),1)
        with patch.dict('os.environ',{'CRON_SECRET':'only-test'}),patch('backend.backups.datetime',clock('2026-11-01')):
            self.assertEqual(self.client.get('/api/backups/monthly').status_code,401)
            self.assertTrue(self.client.get('/api/backups/monthly',headers={'Authorization':'Bearer only-test'}).json()['created'])

    def test_corrupted_backup_never_changes_live_data_or_rotates_snapshots(self):
        backup_id=self.create();before=self.get()
        with db() as c:c.execute('UPDATE backup_snapshots SET checksum=? WHERE id=?',('bad',backup_id))
        response=self.client.post('/api/backups/'+backup_id+'/restore',json={'revision':before['revision'],'confirmed':True})
        self.assertEqual(response.status_code,422);self.assertEqual(self.get(),before)
        self.assertEqual(len(self.client.get('/api/backups').json()['backups']),1)

if __name__=='__main__':unittest.main()
