"""Effective price dates, separate from the timestamp of recording."""
from datetime import date, datetime
from zoneinfo import ZoneInfo
from decimal import Decimal
from fastapi import HTTPException
ZONE=ZoneInfo('Europe/Amsterdam')


def effective_date(value):
    try:
        if not isinstance(value,str) or len(value)!=10:raise ValueError()
        day=date.fromisoformat(value)
        if day>datetime.now(ZONE).date():raise ValueError()
        return day.isoformat()
    except ValueError:
        raise HTTPException(422,'Kies een geldige invoerdatum, vandaag of in het verleden.') from None


def price_order(item, annual=False):
    is_annual=annual and item['date'].startswith('2026') and item.get('granularity')=='year'
    return (item['date'][:4],int(is_annual),item['recorded_at'] if is_annual else item['date'],item['recorded_at'])


def record_prices(state, before, row, values, day, recorded_at, normalize):
    day=effective_date(day)
    old=next((r for r in before['rows'] if r['id']==row['id']),{})
    history=state.setdefault('price_history',[])
    for company_id,value in values.items():
        amount=normalize(value)
        records=[h for h in history if h['row_id']==row['id'] and h['company_id']==company_id]
        previous=old.get('price') if company_id=='general' else old.get('company_prices',{}).get(company_id)
        if not records and previous is not None:
            timestamp=old.get('price_entered_at',{}).get(company_id,recorded_at)
            baseline=datetime.fromisoformat(timestamp).astimezone(ZONE).date().isoformat()
            history.append({'row_id':row['id'],'company_id':company_id,'date':baseline,'amount':previous,'recorded_at':timestamp,'granularity':'year' if baseline.startswith('2026') else 'quarter'})
        # A correction on the same effective date replaces that date's amount;
        # the separate audit trail retains the original input and correction.
        history[:]=[h for h in history if not (h['row_id']==row['id'] and h['company_id']==company_id and h['date']==day)]
        history.append({'row_id':row['id'],'company_id':company_id,'date':day,'amount':amount,'recorded_at':recorded_at,'granularity':'year' if day.startswith('2026') else 'quarter'})
        latest=max((h for h in history if h['row_id']==row['id'] and h['company_id']==company_id),key=lambda h:price_order(h,annual=True))
        if company_id=='general':
            if latest['amount']=='':row.pop('price',None)
            else:row['price']=latest['amount']
        else:
            if latest['amount']=='':row.get('company_prices',{}).pop(company_id,None)
            else:row.setdefault('company_prices',{})[company_id]=latest['amount']
        row.setdefault('price_effective_dates',{})[company_id]=latest['date']


def historical_total(snapshot, state, company_ids, day, since=None):
    values={}
    tracked={(h['row_id'],h['company_id']) for h in state.get('price_history',[])}
    for row in (snapshot or {}).get('rows',[]):
        for co,amount in row.get('company_prices',{}).items():
            if co not in company_ids:continue
            key=(row['id'],co)
            if since is not None:
                if key in tracked:continue
                effective=row.get('price_effective_dates',{}).get(co)
                if not effective:
                    timestamp=row.get('price_entered_at',{}).get(co)
                    effective=datetime.fromisoformat(timestamp).astimezone(ZONE).date().isoformat() if timestamp else None
                if effective is None or not since.isoformat()<=effective<=day.isoformat():continue
            values[key]=Decimal(amount)
    observations={}
    deleted={t['row']['id']:datetime.fromisoformat(t['deleted_at']).astimezone(ZONE).date() for t in state.get('trash',[]) if 'row' in t}
    for h in state.get('price_history',[]):
        if h['company_id'] not in company_ids or h['date']>day.isoformat():continue
        if since is not None and h['date']<since.isoformat():continue
        if h['row_id'] in deleted and deleted[h['row_id']]<=day:continue
        key=(h['row_id'],h['company_id'])
        order=lambda item:price_order(item,annual=since is None)
        if key not in observations or order(h)>order(observations[key]):observations[key]=h
    for key,h in observations.items():values[key]=Decimal(h['amount'] or '0')
    if since is not None and not values and not observations:return None
    if snapshot is None and not observations:return None
    return format(sum(values.values(),Decimal('0')),'.2f')
