"""Durable, bounded application snapshots and atomic restore operations."""
import base64
import gzip
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import Depends, HTTPException, Request

ZONE=ZoneInfo('Europe/Amsterdam')
LIMIT=7


def snapshot(c, read_state, now, kind, actor):
    state,revision=read_state(c)
    history=[dict(r) for r in c.execute('SELECT * FROM audit ORDER BY rowid')]
    settings=[dict(r) for r in c.execute("SELECT key,value FROM settings WHERE key='reporting_config' OR key LIKE 'completion:%'")]
    payload={'version':1,'state':state,'history':history,'settings':settings}
    raw=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
    encoded=base64.b64encode(gzip.compress(raw)).decode()
    backup_id=str(uuid.uuid4());created=now()
    c.execute('INSERT INTO backup_snapshots(id,created_at,kind,actor,revision,payload,checksum) VALUES(?,?,?,?,?,?,?)',(backup_id,created,kind,actor,revision,encoded,hashlib.sha256(raw).hexdigest()))
    # Deterministic ordering even when multiple snapshots share a timestamp.
    keep=c.execute('SELECT id FROM backup_snapshots ORDER BY created_at DESC,rowid DESC LIMIT 7').fetchall()
    ids=[r['id'] for r in keep]
    c.execute('DELETE FROM backup_snapshots WHERE id NOT IN ('+','.join('?' for _ in ids)+')',tuple(ids))
    return backup_id


def decode(record):
    try:
        raw=gzip.decompress(base64.b64decode(record['payload'],validate=True))
        if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(),record['checksum']):raise ValueError()
        data=json.loads(raw)
        if data.get('version')!=1 or not isinstance(data.get('history'),list) or not isinstance(data.get('settings'),list):raise ValueError()
        return data
    except (ValueError,TypeError,KeyError,OSError,EOFError):
        raise HTTPException(422,'Deze back-up is beschadigd en kan niet worden teruggezet.') from None


def register(app,db,admin,check_admin,read_state,save,validate_state,check_revision,now,js):
    @app.get('/api/backups')
    def listing(u=Depends(admin)):
        with db() as c:
            check_admin(c,u)
            rows=c.execute('SELECT id,created_at,kind,actor,revision FROM backup_snapshots ORDER BY created_at DESC,rowid DESC').fetchall()
            _,revision=read_state(c)
        return {'backups':[dict(r) for r in rows],'limit':LIMIT,'revision':revision}

    @app.post('/api/backups')
    def create(body:dict,u=Depends(admin)):
        with db() as c:
            c.execute('BEGIN IMMEDIATE');u=check_admin(c,u)
            _,revision=read_state(c);check_revision(body,revision)
            backup_id=snapshot(c,read_state,now,'manual',u['email'])
        return {'id':backup_id,'message':'Extra back-up gemaakt.'}

    @app.post('/api/backups/{backup_id}/restore')
    def restore(backup_id:str,body:dict,u=Depends(admin)):
        if body.get('confirmed') is not True:raise HTTPException(422,'Bevestig eerst dat u deze back-up wilt terugzetten.')
        with db() as c:
            c.execute('BEGIN IMMEDIATE');u=check_admin(c,u)
            before,revision=read_state(c);check_revision(body,revision)
            record=c.execute('SELECT * FROM backup_snapshots WHERE id=?',(backup_id,)).fetchone()
            if not record:raise HTTPException(404,'Deze back-up is niet meer beschikbaar. Vernieuw de lijst.')
            data=decode(record);validate_state(data.get('state'))
            for item in data['history']:
                if not isinstance(item,dict) or not all(k in item for k in ['id','at','actor','label','before_data','after_data']):raise HTTPException(422,'Ongeldige wijzigingsgeschiedenis in de back-up.')
                try:validate_state(json.loads(item['before_data']));validate_state(json.loads(item['after_data']))
                except (ValueError,TypeError):raise HTTPException(422,'Ongeldige wijzigingsgeschiedenis in de back-up.') from None
            if any(not isinstance(item,dict) or item.get('key')!='reporting_config' and not str(item.get('key','')).startswith('completion:') or not isinstance(item.get('value'),str) for item in data['settings']):raise HTTPException(422,'Ongeldige instellingen in de back-up.')
            # Read the selected snapshot before rotation: restoring the oldest of seven is safe.
            safety_id=snapshot(c,read_state,now,'before_restore',u['email'])
            result=save(c,before,data['state'],revision,u['email'],'Back-up van '+record['created_at']+' teruggezet',record_dates=False)
            for item in data['history']:
                c.execute('INSERT OR IGNORE INTO audit(id,at,actor,label,before_data,after_data) VALUES(?,?,?,?,?,?)',tuple(item[k] for k in ['id','at','actor','label','before_data','after_data']))
            c.execute("DELETE FROM settings WHERE key='reporting_config' OR key LIKE 'completion:%'")
            for item in data['settings']:c.execute('INSERT INTO settings VALUES(?,?)',(item['key'],item['value']))
            result['safety_backup_id']=safety_id
        return result

    @app.get('/api/backups/monthly')
    def monthly(request:Request):
        secret=os.environ.get('CRON_SECRET','')
        if secret and not hmac.compare_digest(request.headers.get('authorization',''),'Bearer '+secret):raise HTTPException(401,'Geen toegang.')
        # Without a configured cron secret this endpoint still permits only the predefined,
        # once-per-month scheduled action. It never returns backup contents or permits restore.
        today=datetime.now(ZONE).date()
        if today.day!=1:return {'created':False}
        marker='backup_month:'+today.strftime('%Y-%m')
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM settings WHERE key=?',(marker,)).fetchone():return {'created':False}
            snapshot(c,read_state,now,'monthly','Systeem')
            c.execute('INSERT INTO settings VALUES(?,?)',(marker,now()))
        return {'created':True}
