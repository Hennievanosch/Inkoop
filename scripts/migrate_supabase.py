"""Build an atomic, non-destructive migration from the current local SQLite snapshot.
SQL is transmitted directly to the management API or a database, never printed or saved.
"""
import hashlib
import json
import secrets
import sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
TABLE_COLUMNS={
 'store':['id','revision','payload'],
 'users':['id','email','password'],
 'user_access':['user_id','role','company_ids','active','version','display_name'],
 'invitations':['id','email','display_name','role','company_ids','token_hash','created_at','expires','invited_by','used_at','canceled_at'],
 'access_audit':['id','at','actor','action','details'],
 'audit':['id','at','actor','label','before_data','after_data'],
 'sessions':['token','user_id','expires'],
 'rate_limits':['key','count','until'],
 'settings':['key','value'],
}


def snapshot(source):
    c=sqlite3.connect(source);c.row_factory=sqlite3.Row
    try:
        c.execute('BEGIN')
        present={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        result={table:[dict(row) for row in c.execute('SELECT '+','.join(columns)+' FROM '+table)] if table in present else [] for table,columns in TABLE_COLUMNS.items()}
        if len(result['store'])!=1:raise RuntimeError('De bron bevat geen geldige leveranciersdatabase.')
        return result
    finally:c.close()


def literal(value):
    if value is None:return 'NULL'
    if isinstance(value,(int,float)):return str(value)
    return "'"+str(value).replace("'","''")+"'"


def migration_sql(source,setup_code):
    snap=snapshot(source);store=snap['store'][0]
    body=['PERFORM pg_advisory_xact_lock(1964098801);',
          'IF EXISTS(SELECT 1 FROM tve.store WHERE id=1) THEN',
          f"  IF EXISTS(SELECT 1 FROM tve.store WHERE id=1 AND revision={store['revision']} AND payload={literal(store['payload'])}) THEN RETURN; END IF;",
          "  RAISE EXCEPTION 'De doeldatabase bevat andere gegevens. Er is niets overschreven.';",
          'END IF;']
    for table,columns in TABLE_COLUMNS.items():
        for row in snap[table]:body.append('INSERT INTO tve.'+table+'('+','.join(columns)+') VALUES('+','.join(literal(row[x]) for x in columns)+');')
    if not snap['users'] and not any(x['key']=='setup_code_hash' for x in snap['settings']):
        digest=hashlib.sha256(setup_code.encode()).hexdigest()
        body.append(f"INSERT INTO tve.settings(key,value) VALUES('setup_code_hash',{literal(digest)});")
    body='\n'.join(body)
    tag='$migration_'+secrets.token_hex(16)+'$'
    while tag in body:tag='$migration_'+secrets.token_hex(16)+'$'
    sql='BEGIN; SET standard_conforming_strings=on;\n'+(ROOT/'supabase/schema.sql').read_text()+'\nDO '+tag+' BEGIN\n'+body+'\nEND '+tag+';\nCOMMIT;'
    data=json.loads(store['payload'])
    summary={'rows':len(data['rows']),'suppliers':len(data['suppliers']),'revision':store['revision'],'history':len(snap['audit'])}
    return sql,summary
