"""Verify a freshly deployed app, then remove only this run's temporary test data.

Refuses an existing user or modified supplier database. HTTPS requests retain
certificate/hostname verification through HTTPx, including browser transport.
Use the environment Python with Playwright and cryptography installed.
"""
import hashlib
import importlib.util
import json
import os
import secrets
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('loader',ROOT/'scripts/load_supabase_connection.py')
loader=importlib.util.module_from_spec(spec);spec.loader.exec_module(loader)
spec=importlib.util.spec_from_file_location('migration',ROOT/'scripts/migrate_supabase.py')
migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
private=json.loads((ROOT/'.deployment/private.json').read_text())
public=json.loads((ROOT/'.deployment/status.json').read_text())
BASE=public['url'].rstrip('/')
if BASE!='https://tve-leveranciers.vercel.app':raise SystemExit('Unexpected verification destination')
token=loader.decrypt_connection(Path('/workspace/supabase-auth/received-tve-connection.json'))
email='online-check-'+secrets.token_hex(8)+'@example.invalid'
password=secrets.token_urlsafe(32)
folder=Path(tempfile.mkdtemp(prefix='tve-online-check-'))
reports=ROOT/'test-results';reports.mkdir(exist_ok=True)
checks=[]
before=None


def query(sql,read_only=True):
    r=httpx.post('https://api.supabase.com/v1/projects/'+private['supabase_ref']+'/database/query',headers={'Authorization':'Bearer '+token},json={'query':sql,'read_only':read_only},timeout=60)
    if not r.is_success:raise RuntimeError('Database verification request failed: HTTP '+str(r.status_code))
    return r.json()


def snapshot():
    return query("SELECT json_build_object('store',(SELECT row_to_json(s) FROM tve.store s WHERE id=1),'audit',(SELECT json_agg(a ORDER BY seq) FROM tve.audit a),'settings',(SELECT json_agg(s) FROM tve.settings s),'users',(SELECT count(*) FROM tve.users),'imports',(SELECT count(*) FROM tve.imports),'sessions',(SELECT count(*) FROM tve.sessions)) AS data")[0]['data']


def restore():
    # Account/actor guards prevent a fixture cleanup from touching another user.
    s=before['store'];audit_ids=[a['id'] for a in before['audit']]
    code_hash=next(x['value'] for x in before['settings'] if x['key']=='setup_code_hash')
    literal=migration.literal
    ids=','.join(literal(x) for x in audit_ids)
    sql=f"""BEGIN;
SELECT pg_advisory_xact_lock(1964098801);
DO $guard$ BEGIN
 IF EXISTS(SELECT 1 FROM tve.users WHERE email<>{literal(email)}) OR
 EXISTS(SELECT 1 FROM tve.audit WHERE id NOT IN ({ids}) AND actor<>{literal(email)}) THEN
  RAISE EXCEPTION 'Verification cleanup refused: unexpected account or actor';
 END IF;
END $guard$;
DELETE FROM tve.sessions WHERE user_id IN (SELECT id FROM tve.users WHERE email={literal(email)});
DELETE FROM tve.imports WHERE user_id IN (SELECT id FROM tve.users WHERE email={literal(email)});
DELETE FROM tve.users WHERE email={literal(email)};
DELETE FROM tve.rate_limits WHERE key={literal(hashlib.sha256(email.encode()).hexdigest())};
DELETE FROM tve.audit WHERE id NOT IN ({ids}) AND actor={literal(email)};
UPDATE tve.store SET revision={s['revision']},payload={literal(s['payload'])} WHERE id=1;
INSERT INTO tve.settings(key,value) VALUES('setup_code_hash',{literal(code_hash)}) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value;
COMMIT;"""
    query(sql,False)
    final=snapshot()
    assert final['store']==before['store']
    assert final['audit']==before['audit']
    assert final['settings']==before['settings']
    assert final['users']==final['sessions']==final['imports']==0
    print('Temporary test data removed; exact original supplier state, revision, history and setup hash restored.',flush=True)


def passed(label):
    checks.append(label);print('PASS: '+label,flush=True)


def main():
    global before
    before=snapshot()
    state=json.loads(before['store']['payload'])
    if before['users'] or before['imports'] or before['sessions'] or before['store']['revision']!=1 or len(state['rows'])!=63 or len(state['suppliers'])!=56 or len(before['audit'])!=1:
        before=None
        raise RuntimeError('Online check requires a fresh, unmodified app without an owner account.')
    fd=os.open(ROOT/'.deployment/online-before-test.json',os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as file:json.dump(before,file)
    with httpx.Client(timeout=60,follow_redirects=True) as client, sync_playwright() as p:
        assert client.get(BASE+'/').status_code==200
        assert client.get(BASE+'/api/health').json()['storage']=='Supabase / PostgreSQL'
        assert client.get(BASE+'/api/state').status_code==401
        assert client.get(BASE+'/api/auth/status').json()['setup_required']
        passed('Publieke HTTPS-app gebruikt Supabase; leveranciersgegevens vereisen inloggen')
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
        context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True)
        page=context.new_page();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        def transport(route):
            request=route.request
            if not request.url.startswith(BASE+'/'):raise RuntimeError('Unexpected browser request destination')
            headers={k:v for k,v in request.headers.items() if k.lower() not in ('host','content-length','accept-encoding')}
            response=client.request(request.method,request.url,headers=headers,content=request.post_data_buffer)
            response_headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-encoding','content-length','transfer-encoding')}
            route.fulfill(status=response.status_code,headers=response_headers,body=response.content)
        context.route(BASE+'/**',transport)
        page.goto(BASE+'/#setup='+private['setup_code'],wait_until='networkidle')
        page.get_by_label('E-mailadres',exact=True).fill(email)
        page.get_by_label('Wachtwoord (minstens 12 tekens)',exact=True).fill(password)
        page.get_by_role('button',name='Account aanmaken',exact=True).click()
        expect(page.get_by_role('heading',name='Grip op uw leveranciers')).to_be_visible(timeout=30000)
        assert '#setup=' not in page.url
        cookie=next(c for c in context.cookies() if c['name']=='tve_session')
        assert cookie['httpOnly'] and cookie['secure'] and cookie['sameSite']=='Lax'
        for index,value in enumerate(('56','63','35','5')):
            expect(page.locator('.stat-card').nth(index).locator(':scope > strong')).to_have_text(value)
        page.screenshot(path=str(reports/'online-dashboard-desktop.png'),full_page=True)
        passed('Accountaanmaak, veilige sessie en oorspronkelijke dashboardtotalen 56 / 63 / 35 / 5')
        page.locator('.chart-column').first.click()
        expect(page.get_by_role('heading',name='Uw leveranciers')).to_be_visible()
        assert page.get_by_label('Filter bedrijf').input_value()
        assert page.locator('.data-table tbody tr').count()>0
        page.get_by_role('button',name='Wissen',exact=True).click()
        checkbox=page.locator('.data-table tbody tr').first.locator('.check-cell input').first
        old=checkbox.is_checked();checkbox.click()
        # The controlled cell updates after the real server confirms its save.
        expect(checkbox).to_be_checked(checked=not old)
        expect(page.locator('.save-state')).to_contain_text('Alle wijzigingen opgeslagen')
        page.reload();expect(page.get_by_role('heading',name='Grip op uw leveranciers')).to_be_visible()
        page.get_by_role('button',name='Leveranciers',exact=True).click()
        expect(page.locator('.data-table tbody tr').first.locator('.check-cell input').first).to_be_checked(checked=not old)
        passed('Grafiek opent gefilterde lijst; inline bedrijfskoppeling blijft na vernieuwen bewaard')
        page.get_by_role('button',name='Categorieën',exact=True).click()
        page.get_by_role('button',name='Categorie toevoegen',exact=True).click()
        page.get_by_label('Categorienaam',exact=True).fill('Online testcategorie')
        page.get_by_role('button',name='Opslaan',exact=True).click()
        expect(page.get_by_role('button',name='Online testcategorie',exact=True)).to_be_visible()
        page.get_by_role('button',name='Bedrijven',exact=True).click()
        page.get_by_role('button',name='Bedrijf toevoegen',exact=True).click()
        page.get_by_label('Bedrijfsnaam',exact=True).fill('Online testbedrijf')
        page.get_by_role('button',name='Opslaan',exact=True).click()
        expect(page.get_by_role('heading',name='Online testbedrijf',exact=True)).to_be_visible()
        page.get_by_role('button',name='Leveranciers',exact=True).click()
        page.get_by_role('button',name='Productregel toevoegen',exact=True).click()
        page.get_by_label('Leveranciersnaam',exact=True).fill('Online testleverancier')
        page.get_by_label('Productcategorie',exact=True).select_option(label='Online testcategorie')
        page.get_by_label('Online testbedrijf',exact=True).check()
        page.get_by_label('Contactpersoon',exact=True).fill('Online testcontact')
        page.get_by_role('button',name='Opslaan',exact=True).click()
        page.get_by_label('Zoek leverancier',exact=True).fill('Online testleverancier')
        expect(page.locator('.data-table tbody tr')).to_have_count(1)
        page.get_by_role('button',name='Productregel toevoegen',exact=True).click()
        page.get_by_role('button',name='Bestaande leverancier',exact=True).click()
        page.get_by_label('Leverancier',exact=True).select_option(label='Online testleverancier')
        page.get_by_label('Productcategorie',exact=True).select_option(label='Folie')
        page.get_by_role('button',name='Opslaan',exact=True).click()
        expect(page.locator('.data-table tbody tr')).to_have_count(2)
        page.locator('.inline-edit').first.click()
        page.get_by_label('Leveranciersnaam',exact=True).fill('Online testleverancier gewijzigd')
        page.get_by_role('button',name='Naam opslaan',exact=True).click()
        expect(page.locator('.supplier-name').filter(has_text='Online testleverancier gewijzigd')).to_have_count(2)
        passed('Categorie, bedrijf en twee afzonderlijke producten toegevoegd; hernoemen werkt op beide regels')
        page.get_by_role('button',name='Velden beheren',exact=True).click()
        page.get_by_role('button',name='Veld toevoegen',exact=True).click()
        page.get_by_label('Veldnaam',exact=True).fill('Online leverdatum')
        page.get_by_label('Type',exact=True).select_option('date')
        page.get_by_role('button',name='Opslaan',exact=True).click()
        page.get_by_role('button',name='Extra velden',exact=True).click()
        contact=page.locator('.inline-value').first.locator('input')
        contact.fill('Online contact gewijzigd');contact.press('Enter')
        expect(page.locator('.save-state')).to_contain_text('Alle wijzigingen opgeslagen')
        expect(contact).to_have_value('Online contact gewijzigd')
        page.get_by_label('Selecteer huidige pagina',exact=True).check()
        page.get_by_role('button',name='Gezamenlijk wijzigen',exact=True).click()
        page.get_by_label('TVE',exact=True).select_option('yes')
        page.get_by_role('button',name='Wijzigingen opslaan',exact=True).click()
        expect(page.locator('.selection-bar')).not_to_be_visible()
        assert all(page.locator('.data-table tbody tr').nth(i).locator('.check-cell input').first.is_checked() for i in range(2))
        page.get_by_role('button',name='Dashboard',exact=True).click()
        expect(page.locator('.stat-card').nth(0).locator(':scope > strong')).to_have_text('1')
        expect(page.locator('.stat-card').nth(1).locator(':scope > strong')).to_have_text('2')
        passed('Extra datumveld, celbewerking, bulkbewerking en direct reagerende grafieken')
        page.get_by_role('button',name='Import / export',exact=True).click()
        with page.expect_download() as pending:
            page.locator('.export-option').first.get_by_role('button',name='Excel',exact=True).click()
        export_path=folder/'export.xlsx';pending.value.save_as(export_path)
        page.locator('input[type=file][accept=".xlsx,.csv"]').set_input_files(export_path)
        expect(page.get_by_role('heading',name='1. Kolommen toewijzen')).to_be_visible()
        page.get_by_label('Importwijze',exact=True).select_option('update')
        page.get_by_role('button',name='Voorvertoning & dubbelen controleren',exact=True).click()
        expect(page.get_by_role('heading',name='2. Voorvertoning beoordelen')).to_be_visible()
        page.get_by_role('button',name='Import bevestigen',exact=True).click()
        expect(page.get_by_role('heading',name='Import voltooid',exact=True)).to_be_visible()
        expect(page.locator('.import-report')).to_contain_text('65')
        with page.expect_download() as pending:
            page.locator('.export-option').nth(1).get_by_role('button',name='CSV',exact=True).click()
        csv_path=folder/'filtered.csv';pending.value.save_as(csv_path)
        import csv
        with csv_path.open(encoding='utf-8-sig') as file:assert len(list(csv.reader(file,delimiter=';')))==3
        passed('Excel export/herimport met kolomtoewijzing en bevestiging; gefilterde CSV bevat twee productregels')
        with page.expect_download() as pending:page.get_by_role('button',name='Back-up maken',exact=True).click()
        backup_path=folder/'backup.json';pending.value.save_as(backup_path)
        backup=json.loads(backup_path.read_text());assert len(backup['state']['rows'])==65
        assert any(f['name']=='Online leverdatum' and f['type']=='date' for f in backup['state']['fields'])
        page.locator('input[type=file][accept=".json"]').set_input_files(backup_path)
        expect(page.get_by_role('dialog',name='Back-up herstellen',exact=True)).to_be_visible()
        page.get_by_role('button',name='Bevestigen en herstellen',exact=True).click()
        expect(page.get_by_role('dialog')).not_to_be_visible()
        passed('Volledige back-up inclusief extra velden en koppelingen gedownload, beoordeeld en hersteld')
        page.get_by_role('button',name='Leveranciers',exact=True).click()
        page.get_by_label('Selecteer huidige pagina',exact=True).check()
        page.get_by_role('button',name='Verwijderen',exact=True).click()
        page.get_by_role('dialog').get_by_role('button',name='Verwijderen',exact=True).click()
        expect(page.locator('.data-table tbody tr')).to_have_count(0)
        page.get_by_role('button',name='Geschiedenis & herstel',exact=True).click()
        page.get_by_role('button',name='Prullenbak (2)',exact=True).click()
        page.get_by_role('button',name='Herstellen',exact=True).first.click()
        page.get_by_role('button',name='Geschiedenis & herstel',exact=True).click()
        page.get_by_role('button',name='Prullenbak (1)',exact=True).click()
        page.get_by_role('button',name='Herstellen',exact=True).click()
        expect(page.locator('.data-table tbody tr')).to_have_count(2)
        passed('Verwijderen en herstel van beide productregels via de prullenbak')
        with httpx.Client(timeout=60,headers={'Origin':BASE}) as other:
            assert other.post(BASE+'/api/auth/login',json={'email':email,'password':password}).is_success
            latest=client.get(BASE+'/api/state').json()
            row=deepcopy(latest['state']['rows'][0]);first=deepcopy(row);second=deepcopy(row)
            field=latest['state']['fields'][0]['id'];first['values'][field]='Eerste sessie';second['values'][field]='Tweede sessie'
            assert other.post(BASE+'/api/action',json={'op':'row_save','data':first,'revision':latest['revision']}).status_code==200
            assert client.post(BASE+'/api/action',json={'op':'row_save','data':second,'revision':latest['revision']},headers={'Origin':BASE}).status_code==409
            current=client.get(BASE+'/api/state').json()
            assert next(r for r in current['state']['rows'] if r['id']==row['id'])['values'][field]=='Eerste sessie'
        passed('Twee online sessies: verouderde revisie geweigerd zonder overschrijving')
        stored=client.get(BASE+'/api/state').json()
        print('Checking data persistence across a new Vercel production deployment…',flush=True)
        process=subprocess.run(['python',str(ROOT/'scripts/load_supabase_connection.py'),'/workspace/supabase-auth/received-tve-connection.json','--supabase-project',private['supabase_ref']],cwd=ROOT,capture_output=True,text=True)
        if process.returncode:raise RuntimeError('Persistence deployment failed; see Vercel project status.')
        assert client.get(BASE+'/api/state').json()==stored
        page.reload();expect(page.get_by_role('heading',name='Grip op uw leveranciers')).to_be_visible()
        expect(page.locator('.stat-card').nth(0).locator(':scope > strong')).to_have_text('57')
        expect(page.locator('.stat-card').nth(1).locator(':scope > strong')).to_have_text('65')
        passed('Gegevens, extra velden, wijzigingen en sessie blijven behouden na een nieuwe Vercel-deployment')
        for width,height,name in ((820,1180,'tablet'),(390,844,'mobiel')):
            page.set_viewport_size({'width':width,'height':height})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(reports/f'online-dashboard-{name}.png'),full_page=True,animations='disabled')
        page.get_by_role('button',name='Menu openen',exact=True).click()
        page.get_by_role('button',name='Leveranciers',exact=True).click()
        expect(page.get_by_role('heading',name='Uw leveranciers')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(reports/'online-leveranciers-mobiel.png'),full_page=True,animations='disabled')
        assert not errors,errors
        passed('Desktop, tablet en mobiel geopend; menu en tabellen bruikbaar; geen JavaScript-runtimefouten')
        browser.close()
    report={'url':BASE,'storage':'Supabase / PostgreSQL','passed':checks,'transport':'HTTPx validates every actual HTTPS browser request; no TLS bypass','temporary_data_cleanup':False}
    (reports/'online-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    try:main()
    finally:
        if before:
            restore()
            path=reports/'online-report.json'
            if path.exists():
                report=json.loads(path.read_text());report['temporary_data_cleanup']=True
                path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
