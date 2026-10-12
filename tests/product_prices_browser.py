"""Check product-price entry using temporary data; --published uses live UI assets.

Even in published mode all authenticated API calls use an isolated local backend.
The owner's production data and credentials are never changed.
"""
import argparse
import io
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
import httpx
from openpyxl import load_workbook
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parent.parent
parser=argparse.ArgumentParser();parser.add_argument('--published',action='store_true');args=parser.parse_args()
with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
LOCAL=f'http://127.0.0.1:{port}'
BASE='https://tve-leveranciers.vercel.app' if args.published else LOCAL
folder=Path(tempfile.mkdtemp(prefix='tve-product-prices-'))
env={**os.environ,'TVE_DB_PATH':str(folder/'prices.sqlite')}
for key in ['SUPABASE_DB_URL','DATABASE_URL','VERCEL']:env.pop(key,None)
log=open(folder/'server.log','w')
client=httpx.Client(timeout=45,follow_redirects=True)
def start():
    process=subprocess.Popen([str(ROOT/'.venv/bin/python'),'-m','uvicorn','backend.app:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=log)
    for _ in range(100):
        try:
            if client.get(LOCAL+'/api/health').is_success:return process
        except httpx.HTTPError:pass
        time.sleep(.1)
    raise RuntimeError('Geïsoleerde testserver kon niet starten.')
process=start();checks=[]
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
        context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True)
        if args.published:
            assert client.get(BASE+'/api/health').json()['storage']=='Supabase / PostgreSQL'
            assert client.get(BASE+'/api/state').status_code==401
            def transport(route):
                request=route.request
                headers={k:v for k,v in request.all_headers().items() if k.lower() not in ['host','content-length','accept-encoding']}
                local=request.url.startswith(BASE+'/api/')
                target=LOCAL+request.url[len(BASE):] if local else request.url
                if local and headers.get('origin')==BASE:headers['origin']=LOCAL
                client.cookies.clear()
                response=client.request(request.method,target,headers=headers,content=request.post_data_buffer)
                rh={k:v for k,v in response.headers.items() if k.lower() not in ['content-encoding','content-length','transfer-encoding']}
                route.fulfill(status=response.status_code,headers=rh,body=response.content)
            context.route(BASE+'/**',transport)
        page=context.new_page();errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(BASE+'/#setup='+(folder/'prices.token').read_text().strip())
        page.get_by_label('E-mailadres',exact=True).fill('productprijs@example.test')
        page.get_by_label('Wachtwoord (minstens 12 tekens)',exact=True).fill('isolated-product-price-password')
        page.get_by_role('button',name='Account aanmaken',exact=True).click()
        expect(page.get_by_role('heading',name='Grip op uw leveranciers')).to_be_visible()
        page.get_by_role('button',name='Leveranciers',exact=True).click()
        page.get_by_label('Prijzen invoeren voor',exact=True).select_option('general')
        expect(page.locator('.product-prices-table')).to_be_visible()
        checks.append('Leveranciers opent direct de eenvoudige tabel Leverancier / Product / Prijs')
        for name,price in [('Product A',''),('Product B','25,60')]:
            page.get_by_role('button',name='Productregel toevoegen',exact=True).click()
            if name=='Product A':page.get_by_label('Leveranciersnaam',exact=True).fill('Prijscontrole')
            else:
                page.get_by_role('button',name='Bestaande leverancier',exact=True).click()
                page.get_by_label('Leverancier',exact=True).select_option(label='Prijscontrole')
            page.get_by_label('Productcategorie',exact=True).select_option(label='Folie')
            page.get_by_label('Productnaam',exact=True).fill(name)
            page.get_by_label('Algemene prijs (€)',exact=True).fill(price)
            page.get_by_role('button',name='Opslaan',exact=True).click()
            expect(page.get_by_role('dialog')).not_to_be_visible()
        page.get_by_label('Zoek leverancier',exact=True).fill('Prijscontrole')
        expect(page.locator('.product-prices-table tbody tr')).to_have_count(2)
        a=page.get_by_label('Prijs Prijscontrole, Product A',exact=True)
        b=page.get_by_label('Prijs Prijscontrole, Product B',exact=True)
        a.fill('12,34');a.press('Enter');expect(a).to_have_value('12,34');expect(b).to_have_value('25,60')
        page.locator('.product-inline input').first.fill('Product A gewijzigd')
        page.locator('.product-inline input').first.press('Enter')
        a=page.get_by_label('Prijs Prijscontrole, Product A gewijzigd',exact=True)
        expect(a).to_have_value('12,34')
        checks.append('Twee specifieke producten bij één leverancier: eigen prijzen, komma-invoer en productnaam wijzigen')
        page.reload();expect(page.get_by_role('heading',name='Grip op uw leveranciers')).to_be_visible()
        page.get_by_role('button',name='Leveranciers',exact=True).click()
        page.get_by_label('Prijzen invoeren voor',exact=True).select_option('general')
        page.get_by_label('Zoek leverancier',exact=True).fill('Prijscontrole')
        expect(page.get_by_label('Prijs Prijscontrole, Product A gewijzigd',exact=True)).to_have_value('12,34')
        expect(page.get_by_label('Prijs Prijscontrole, Product B',exact=True)).to_have_value('25,60')
        checks.append('Productnamen en verschillende prijzen blijven bewaard na vernieuwen')
        a=page.get_by_label('Prijs Prijscontrole, Product A gewijzigd',exact=True)
        a.fill('-1');a.press('Enter');expect(page.locator('.save-state')).to_contain_text('Opslaan mislukt')
        a.press('Escape');expect(a).to_have_value('12,34')
        with httpx.Client(base_url=LOCAL,timeout=15) as other:
            assert other.post('/api/auth/login',json={'email':'productprijs@example.test','password':'isolated-product-price-password'}).is_success
            a.fill('99,50')
            latest=other.get('/api/state').json();target=next(r for r in latest['state']['rows'] if r.get('product_name')=='Product A gewijzigd')
            assert other.post('/api/action',json={'op':'row_price','data':{'id':target['id'],'price':'77,10'},'revision':latest['revision']}).is_success
            a.press('Enter');expect(page.locator('.product-prices-table .cell-error')).to_be_visible()
            expect(a).to_have_value('99,50');a.press('Escape');expect(a).to_have_value('77,10')
        checks.append('Ongeldige en gelijktijdige productprijswijzigingen overschrijven geen bewaarde bedragen')
        a.fill('12,34');a.press('Enter');expect(a).to_have_value('12,34')
        with page.expect_download() as download:page.get_by_role('button',name='Exporteren',exact=True).click()
        export_path=folder/'prijzen.xlsx';download.value.save_as(str(export_path))
        workbook=load_workbook(export_path,data_only=True)
        exported=list(workbook.active.values);headers=exported[0];pi=headers.index('Prijs (€)');ni=headers.index('Productnaam')
        assert {(r[ni],r[pi]) for r in exported[1:]}=={('Product A gewijzigd','12.34'),('Product B','25.60')}
        checks.append('Gefilterde Excel bevat de twee productnamen met hun eigen prijzen')
        page.screenshot(path=str(ROOT/'test-results/productprijzen-desktop.png'),full_page=True,animations='disabled')
        page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(350)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        last=page.get_by_label('Prijs Prijscontrole, Product B',exact=True).bounding_box()
        assert last['x']+last['width']<=390
        page.screenshot(path=str(ROOT/'test-results/productprijzen-mobiel.png'),full_page=True,animations='disabled')
        checks.append('Mobiel: leverancier, product en prijs zijn samen zichtbaar, zonder horizontale pagina-overloop')
        process.terminate();process.wait(10);process=start()
        page.reload();expect(page.get_by_role('heading',name='Grip op uw leveranciers')).to_be_visible()
        page.get_by_role('button',name='Menu openen',exact=True).click()
        page.get_by_role('button',name='Leveranciers',exact=True).click()
        page.get_by_label('Prijzen invoeren voor',exact=True).select_option('general')
        page.get_by_label('Zoek leverancier',exact=True).fill('Prijscontrole')
        expect(page.get_by_label('Prijs Prijscontrole, Product A gewijzigd',exact=True)).to_have_value('12,34')
        expect(page.get_by_label('Prijs Prijscontrole, Product B',exact=True)).to_have_value('25,60')
        checks.append('Daadwerkelijke backendherstart behoudt beide productprijzen en het testaccount')
        assert not errors,errors;checks.append('Geen JavaScript-runtimefouten')
        browser.close()
    suffix='-published' if args.published else ''
    (ROOT/f'test-results/productprijzen-browser{suffix}.json').write_text(json.dumps({'passed':checks,'frontend':BASE,'authenticated_api':'isolated local SQLite','production_data_changed':False},ensure_ascii=False,indent=2))
    print(json.dumps({'passed':checks},ensure_ascii=False,indent=2))
finally:
    process.terminate();process.wait(10);log.close();client.close()
