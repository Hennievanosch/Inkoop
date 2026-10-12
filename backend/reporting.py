"""Period reporting, explicit completion and scheduled reminder delivery."""
import calendar
import hmac
import hashlib
import json
import os
import smtplib
import ssl
from datetime import datetime, date, timedelta, timezone, time
from decimal import Decimal
from email.message import EmailMessage
from zoneinfo import ZoneInfo
from fastapi import Depends, HTTPException, Request

DEFAULT = {'frequency':'quarter','deadline':'day25','sender':'info@tve.nl'}
ZONE = ZoneInfo('Europe/Amsterdam')


def period(day, frequency='quarter'):
    month = day.month if frequency == 'month' else ((day.month-1)//3)*3+1
    start = date(day.year, month, 1)
    end_month = month if frequency == 'month' else month+2
    end = date(day.year, end_month, calendar.monthrange(day.year,end_month)[1])
    return start, end, f'{day.year}-{month:02}' if frequency == 'month' else f'{day.year}-Q{(month-1)//3+1}'


def deadline(end, rule):
    if rule == 'last_friday':
        return end-timedelta(days=(end.weekday()-4)%7)
    return end.replace(day=25)


def config(c):
    row=c.execute('SELECT value FROM settings WHERE key=?',('reporting_config',)).fetchone()
    return {**DEFAULT, **(json.loads(row['value']) if row else {})}


def totals(state, company_ids):
    values=[Decimal(value) for row in state['rows'] for key,value in row.get('company_prices',{}).items() if key in company_ids]
    return format(sum(values,Decimal('0')),'.2f')


def completeness(state, ids):
    expected=[(row,co) for row in state['rows'] for co in row['company_ids'] if co in ids]
    missing=sum(row.get('company_prices',{}).get(co) in (None,'') for row,co in expected)
    return {'expected':len(expected),'missing':missing}


def price_fingerprint(state, ids):
    prices=sorted((row['id'],co,row.get('company_prices',{}).get(co)) for row in state['rows'] for co in row['company_ids'] if co in ids)
    return hashlib.sha256(json.dumps(prices).encode()).hexdigest()


def valid_completion(c, user_id, key, state, ids):
    record=c.execute('SELECT value FROM settings WHERE key=?',(f'completion:{user_id}:{key}',)).fetchone()
    value=json.loads(record['value']) if record else None
    return value if value and value.get('fingerprint')==price_fingerprint(state,ids) else None


def register(app, db, user, admin, current_access, read_state, now, js, check_revision):
    @app.get('/api/reporting')
    def report(company_id:str='',u=Depends(user)):
        with db() as c:
            u=current_access(c,u['id']); state,revision=read_state(c); cfg=config(c)
            today=datetime.now(ZONE).date(); start,end,key=period(today,cfg['frequency'])
            ids={co['id'] for co in state['companies']} if u['role']=='admin' else set(u['company_ids'])
            personal_ids=ids
            if u['role']=='admin':
                selected=company_id or next(iter(co['id'] for co in state['companies']), '')
                if selected and selected not in ids:raise HTTPException(422,'Onbekend bedrijf.')
                personal_ids={selected}
            else:selected=''
            completion=valid_completion(c,u['id'],key,state,ids)
            # Use audited end-of-period states; periods before the first audit remain unknown.
            series=[]; cursor=start
            for _ in range(7):
                pstart,pend,pkey=period(cursor,cfg['frequency'])
                cutoff=datetime.combine(min(pend,today)+timedelta(days=1),time.min,ZONE).astimezone(timezone.utc).isoformat()
                audit=c.execute('SELECT after_data FROM audit WHERE at<? ORDER BY at DESC,rowid DESC LIMIT 1',(cutoff,)).fetchone()
                snapshot=json.loads(audit['after_data']) if audit else None
                if pkey==key:snapshot=state
                mine=totals(snapshot,personal_ids) if snapshot is not None else None
                all_ids={co['id'] for co in snapshot['companies']} if snapshot else set()
                item={'key':pkey,'total':mine,'current':pkey==key}
                if u['role']=='admin':item['group_total']=totals(snapshot,all_ids) if snapshot is not None else None
                series.insert(0,item);cursor=pstart-timedelta(days=1)
            due=deadline(end,cfg['deadline'])
            return {'companies':state['companies'] if u['role']=='admin' else [],'selected_company':selected,'config':cfg,'revision':revision,'period':key,'deadline':due.isoformat(),'overdue':today>due,'completion':completion,'coverage':completeness(state,ids),'series':series,'mail_ready':all(os.environ.get(k) for k in ['TVE_SMTP_HOST','TVE_SMTP_USER','TVE_SMTP_PASSWORD','CRON_SECRET'])}

    @app.post('/api/reporting/config')
    def update_config(body:dict,u=Depends(admin)):
        cfg={'frequency':body.get('frequency'),'deadline':body.get('deadline'),'sender':'info@tve.nl'}
        if cfg['frequency'] not in ['month','quarter'] or cfg['deadline'] not in ['day25','last_friday']:
            raise HTTPException(422,'Kies een geldige periode en deadline.')
        with db() as c:
            c.execute('BEGIN IMMEDIATE');admin(current_access(c,u['id']))
            _,revision=read_state(c);check_revision(body,revision)
            c.execute('DELETE FROM settings WHERE key=?',('reporting_config',))
            c.execute('INSERT INTO settings VALUES(?,?)',('reporting_config',js(cfg)))
            c.execute('UPDATE store SET revision=? WHERE id=1',(revision+1,))
        return cfg

    @app.post('/api/reporting/complete')
    def complete(body:dict,u=Depends(user)):
        with db() as c:
            c.execute('BEGIN IMMEDIATE');u=current_access(c,u['id']);state,revision=read_state(c);check_revision(body,revision)
            _,_,key=period(datetime.now(ZONE).date(),config(c)['frequency'])
            if body.get('period') != key:raise HTTPException(409,'De periode is veranderd. Vernieuw het dashboard.')
            ids={co['id'] for co in state['companies']} if u['role']=='admin' else set(u['company_ids'])
            coverage=completeness(state,ids)
            if not coverage['expected'] or coverage['missing']:raise HTTPException(422,'Vul eerst alle productprijzen voor uw bedrijven in. Nul is een geldige prijs.')
            value={'at':now(),'revision':revision,'company_ids':sorted(ids),'fingerprint':price_fingerprint(state,ids)}
            setting=f'completion:{u["id"]}:{key}'
            c.execute('DELETE FROM settings WHERE key=?',(setting,));c.execute('INSERT INTO settings VALUES(?,?)',(setting,js(value)))
        return value

    @app.get('/api/reminders')
    def reminders(request:Request):
        secret=os.environ.get('CRON_SECRET','')
        if not secret or not hmac.compare_digest(request.headers.get('authorization',''),'Bearer '+secret):raise HTTPException(401,'Geen toegang.')
        if not all(os.environ.get(k) for k in ['TVE_SMTP_HOST','TVE_SMTP_USER','TVE_SMTP_PASSWORD']):raise HTTPException(503,'De maildienst is nog niet ingesteld.')
        sent=0
        with db() as c:
            # Lock across instances so retries do not send the same reminder twice.
            c.execute('BEGIN IMMEDIATE');cfg=config(c);today=datetime.now(ZONE).date();_,end,key=period(today,cfg['frequency']);due=deadline(end,cfg['deadline'])
            if today<due:return {'sent':0}
            users=c.execute('SELECT u.id,u.email FROM users u JOIN user_access a ON a.user_id=u.id WHERE a.active=1').fetchall()
            for recipient in users:
                access=current_access(c,recipient['id']);state,_=read_state(c)
                ids={co['id'] for co in state['companies']} if access['role']=='admin' else set(access['company_ids'])
                if not completeness(state,ids)['expected']:continue
                marker=f'reminder:{recipient["id"]}:{key}'
                if valid_completion(c,recipient['id'],key,state,ids) or c.execute('SELECT 1 FROM settings WHERE key=?',(marker,)).fetchone():continue
                message=EmailMessage();message['From']=cfg['sender'];message['To']=recipient['email'];message['Subject']=f'TVE: vul uw prijzen in voor {key}'
                message.set_content(f'Uw prijsinvoer voor {key} is nog niet bevestigd. De deadline is {due:%d-%m-%Y}. Vul uw productprijzen in en bevestig de periode op het dashboard.\n\nhttps://tve-leveranciers.vercel.app\n')
                try:
                    with smtplib.SMTP(os.environ['TVE_SMTP_HOST'],int(os.environ.get('TVE_SMTP_PORT','587')),timeout=15) as smtp:
                        smtp.starttls(context=ssl.create_default_context());smtp.login(os.environ['TVE_SMTP_USER'],os.environ['TVE_SMTP_PASSWORD']);smtp.send_message(message)
                except (OSError,smtplib.SMTPException):raise HTTPException(502,'De herinnering kon niet worden verstuurd. Controleer de maildienst.') from None
                c.execute('INSERT INTO settings VALUES(?,?)',(marker,now()))
                # Persist each successful delivery before attempting another recipient.
                c.commit();c.execute('BEGIN IMMEDIATE');sent+=1
        return {'sent':sent}
