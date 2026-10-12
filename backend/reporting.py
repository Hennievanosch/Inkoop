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
from backend.price_history import historical_total

DEFAULT = {'frequency':'quarter','deadline':'day25','sender':'info@tve.nl'}
ZONE = ZoneInfo('Europe/Amsterdam')
MEASUREMENT_START = date(2027,1,1)


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


def completeness(state, ids, since=None, until=None):
    expected=[(row,co) for row in state['rows'] for co in row['company_ids'] if co in ids]
    def absent(row,co):
        if since is None:return row.get('company_prices',{}).get(co) in (None,'')
        records=[h for h in state.get('price_history',[]) if h['row_id']==row['id'] and h['company_id']==co and since.isoformat()<=h['date']<=until.isoformat()]
        if records:return max(records,key=lambda h:(h['date'],h['recorded_at']))['amount']==''
        day=row.get('price_effective_dates',{}).get(co)
        timestamp=row.get('price_entered_at',{}).get(co)
        if not day and timestamp:day=datetime.fromisoformat(timestamp).astimezone(ZONE).date().isoformat()
        return row.get('company_prices',{}).get(co) in (None,'') or day is None or not since.isoformat()<=day<=until.isoformat()
    missing=sum(absent(row,co) for row,co in expected)
    return {'expected':len(expected),'missing':missing}


def price_fingerprint(state, ids):
    prices=sorted((row['id'],co,row.get('company_prices',{}).get(co)) for row in state['rows'] for co in row['company_ids'] if co in ids)
    return hashlib.sha256(json.dumps(prices).encode()).hexdigest()


def valid_completion(c, user_id, key, state, ids):
    record=c.execute('SELECT value FROM settings WHERE key=?',(f'completion:{user_id}:{key}',)).fetchone()
    value=json.loads(record['value']) if record else None
    return value if value and value.get('fingerprint')==price_fingerprint(state,ids) else None


def report_data(c, state, revision, u, company_id='', today=None):
    """Use identical annual/quarterly totals for the app and its Excel dashboard."""
    cfg=config(c)
    today=today or datetime.now(ZONE).date(); start,end,key=period(today,cfg['frequency'])
    ids={co['id'] for co in state['companies']} if u['role']=='admin' else set(u['company_ids'])
    personal_ids=ids
    if u['role']=='admin':
        selected=company_id or next(iter(co['id'] for co in state['companies']), '')
        if selected and selected not in ids:raise HTTPException(422,'Onbekend bedrijf.')
        personal_ids={selected}
    else:selected=''
    completion=valid_completion(c,u['id'],key,state,ids)
    informative=today<MEASUREMENT_START
    if informative:start,end,key=date(2026,1,1),date(2026,12,31),'2026'
    periods=[(date(2026,1,1),date(2026,12,31),'2026','year')]
    if not informative:
        for year in range(max(2027,today.year-1),today.year+1):
            for quarter in range(1,5):
                pstart,pend,pkey=period(date(year,(quarter-1)*3+1,1),'quarter')
                periods.append((pstart,pend,pkey,'quarter'))
    series=[]
    for pstart,pend,pkey,granularity in periods:
        future=pstart>today
        current=pstart<=today<=pend
        snapshot=None
        if not future:
            cutoff=datetime.combine(min(pend,today)+timedelta(days=1),time.min,ZONE).astimezone(timezone.utc).isoformat()
            audit=c.execute('SELECT after_data FROM audit WHERE at<? ORDER BY at DESC,rowid DESC LIMIT 1',(cutoff,)).fetchone()
            snapshot=json.loads(audit['after_data']) if audit else None
            if current:snapshot=state
        since=pstart if granularity=='quarter' else None
        mine=None if future else historical_total(snapshot,state,personal_ids,min(pend,today),since=since)
        all_ids={co['id'] for co in state['companies']} | ({co['id'] for co in snapshot['companies']} if snapshot else set())
        if not current:all_ids|={h['company_id'] for h in state.get('price_history',[]) if h['company_id']!='general'}
        group=None if future else historical_total(snapshot,state,all_ids,min(pend,today),since=since)
        series.append({'key':pkey,'total':mine,'group_total':group,'current':current,'future':future,'granularity':granularity})
    due=None if informative else deadline(end,cfg['deadline'])
    coverage=completeness(state,ids,since=None if informative else start,until=min(end,today))
    if coverage['missing']:completion=None
    return {'companies':state['companies'] if u['role']=='admin' else [],'selected_company':selected,'config':cfg,'revision':revision,'period':key,'deadline':due.isoformat() if due else None,'overdue':bool(due and today>due),'informative_only':informative,'measurement_start':'2027-01-01','completion':completion if not informative else None,'coverage':coverage,'series':series,'mail_ready':all(os.environ.get(k) for k in ['TVE_SMTP_HOST','TVE_SMTP_USER','TVE_SMTP_PASSWORD','CRON_SECRET'])}


def register(app, db, user, admin, current_access, read_state, now, js, check_revision):
    @app.get('/api/reporting')
    def report(company_id:str='',u=Depends(user)):
        with db() as c:
            u=current_access(c,u['id']); state,revision=read_state(c)
            return report_data(c,state,revision,u,company_id)

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
            today=datetime.now(ZONE).date()
            if today<MEASUREMENT_START:raise HTTPException(422,'2026 is informatief. Periodebevestiging begint vanaf januari 2027.')
            start,end,key=period(today,config(c)['frequency'])
            if body.get('period') != key:raise HTTPException(409,'De periode is veranderd. Vernieuw het dashboard.')
            ids={co['id'] for co in state['companies']} if u['role']=='admin' else set(u['company_ids'])
            coverage=completeness(state,ids,since=start,until=min(end,today))
            if not coverage['expected'] or coverage['missing']:raise HTTPException(422,'Vul eerst alle productprijzen voor uw bedrijven in. Nul is een geldige prijs.')
            value={'at':now(),'revision':revision,'company_ids':sorted(ids),'fingerprint':price_fingerprint(state,ids)}
            setting=f'completion:{u["id"]}:{key}'
            c.execute('DELETE FROM settings WHERE key=?',(setting,));c.execute('INSERT INTO settings VALUES(?,?)',(setting,js(value)))
        return value

    @app.get('/api/reminders')
    def reminders(request:Request):
        secret=os.environ.get('CRON_SECRET','')
        if not secret or not hmac.compare_digest(request.headers.get('authorization',''),'Bearer '+secret):raise HTTPException(401,'Geen toegang.')
        if datetime.now(ZONE).date()<MEASUREMENT_START:return {'sent':0,'reason':'Kwartaalmetingen starten in januari 2027.'}
        if not all(os.environ.get(k) for k in ['TVE_SMTP_HOST','TVE_SMTP_USER','TVE_SMTP_PASSWORD']):raise HTTPException(503,'De maildienst is nog niet ingesteld.')
        sent=0
        with db() as c:
            # Lock across instances so retries do not send the same reminder twice.
            c.execute('BEGIN IMMEDIATE');cfg=config(c);today=datetime.now(ZONE).date();start,end,key=period(today,cfg['frequency']);due=deadline(end,cfg['deadline'])
            if today<due:return {'sent':0}
            users=c.execute('SELECT u.id,u.email FROM users u JOIN user_access a ON a.user_id=u.id WHERE a.active=1').fetchall()
            for recipient in users:
                access=current_access(c,recipient['id']);state,_=read_state(c)
                ids={co['id'] for co in state['companies']} if access['role']=='admin' else set(access['company_ids'])
                if not completeness(state,ids)['expected']:continue
                marker=f'reminder:{recipient["id"]}:{key}'
                if (valid_completion(c,recipient['id'],key,state,ids) and not completeness(state,ids,since=start,until=min(end,today))['missing']) or c.execute('SELECT 1 FROM settings WHERE key=?',(marker,)).fetchone():continue
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
