"""Personal invitations and company access with isolated data and optional published UI assets.

Production supplier data and account credentials are never modified.
"""
import argparse
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
folder=Path(tempfile.mkdtemp(prefix='tve-invitations-'))
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
        errors=[]
        def context(viewport=None):
            ctx=browser.new_context(viewport=viewport or {'width':1440,'height':1000},permissions=['clipboard-read','clipboard-write'],timezone_id='Europe/Amsterdam')
            if args.published:
                assert client.get(BASE+'/api/health').json()['storage']=='Supabase / PostgreSQL'
                assert client.get(BASE+'/api/state').status_code==401
                def transport(route):
                    request=route.request
                    headers={key:value for key,value in request.all_headers().items() if key.lower() not in ['host','content-length','accept-encoding']}
                    local=request.url.startswith(BASE+'/api/')
                    target=LOCAL+request.url[len(BASE):] if local else request.url
                    if local and headers.get('origin')==BASE:headers['origin']=LOCAL
                    client.cookies.clear()
                    response=client.request(request.method,target,headers=headers,content=request.post_data_buffer)
                    rh={key:value for key,value in response.headers.items() if key.lower() not in ['content-encoding','content-length','transfer-encoding']}
                    route.fulfill(status=response.status_code,headers=rh,body=response.content)
                ctx.route(BASE+'/**',transport)
            return ctx
        def page_in(ctx):
            page=ctx.new_page();page.on('pageerror',lambda error:errors.append(str(error)));return page
        owner_context=context();owner_page=page_in(owner_context)
        owner_page.goto(BASE+'/#setup='+(folder/'prices.token').read_text().strip())
        owner_page.get_by_label('E-mailadres',exact=True).fill('owner@example.test')
        owner_page.get_by_label('Wachtwoord (minstens 12 tekens)',exact=True).fill('isolated-owner-password')
        owner_page.get_by_role('button',name='Account aanmaken',exact=True).click()
        expect(owner_page.get_by_role('heading',name='Grip op uw leveranciers')).to_be_visible()
        owner_api=httpx.Client(base_url=LOCAL,timeout=20)
        assert owner_api.post('/api/auth/login',json={'email':'owner@example.test','password':'isolated-owner-password'}).is_success
        original=owner_api.get('/api/state').json();state=original['state']
        tve=next(company['id'] for company in state['companies'] if company['name']=='TVE')
        forty=next(company['id'] for company in state['companies'] if company['name']=='FORTY FIVE')
        for name,companies,prices in [('Uitnodiging leverancier',[tve,forty],{tve:'12,34',forty:'99,99'}),('Privé ander bedrijf',[forty],{forty:'76,54'})]:
            latest=owner_api.get('/api/state').json()
            assert owner_api.post('/api/action',json={'op':'row_save','data':{'supplier_name':name,'product_name':'Testproduct','category_id':state['categories'][0]['id'],'company_ids':companies,'company_prices':prices,'values':{}},'revision':latest['revision']}).is_success
        owner_page.reload();expect(owner_page.get_by_role('heading',name='Grip op uw leveranciers')).to_be_visible()
        owner_page.get_by_role('button',name='Gebruikers',exact=True).click()
        expect(owner_page.get_by_role('heading',name='Gebruikers & uitnodigingen',exact=True)).to_be_visible()
        owner_page.get_by_role('button',name='Gebruiker uitnodigen',exact=True).click()
        owner_page.get_by_label('E-mailadres van de gebruiker',exact=True).fill('collega@example.test')
        owner_page.get_by_label('Naam (optioneel)',exact=True).fill('Collega TVE')
        owner_page.get_by_label('TVE',exact=True).check()
        owner_page.get_by_role('button',name='Uitnodigingslink maken',exact=True).click()
        expect(owner_page.get_by_role('dialog')).not_to_be_visible()
        link=owner_page.get_by_label('Uitnodigingslink',exact=True).input_value()
        assert link.startswith(BASE+'/#invite=')
        owner_page.get_by_role('button',name='Link kopiëren',exact=True).click()
        expect(owner_page.locator('.toast')).to_contain_text('Uitnodigingslink gekopieerd')
        assert owner_page.evaluate('() => navigator.clipboard.readText()')==link
        owner_page.screenshot(path=str(ROOT/'test-results/gebruikers-desktop.png'),full_page=True,animations='disabled')
        checks.append('Beheerder maakt en kopieert een uitnodigingslink met een bedrijfsrol; er wordt geen e-mail automatisch verstuurd')
        member_context=context({'width':390,'height':844});member_page=page_in(member_context)
        member_page.goto(link)
        expect(member_page.get_by_label('E-mailadres',exact=True)).to_have_value('collega@example.test')
        member_page.get_by_label('Kies een wachtwoord (minstens 12 tekens)',exact=True).fill('personal-colleague-password')
        member_page.get_by_label('Wachtwoord bevestigen',exact=True).fill('different-colleague-password')
        member_page.get_by_role('button',name='Account activeren',exact=True).click()
        expect(member_page.get_by_role('alert')).to_contain_text('komen niet overeen')
        member_page.get_by_label('Wachtwoord bevestigen',exact=True).fill('personal-colleague-password')
        member_page.screenshot(path=str(ROOT/'test-results/uitnodiging-mobiel.png'),full_page=True,animations='disabled')
        assert member_page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        member_page.get_by_role('button',name='Account activeren',exact=True).click()
        expect(member_page.get_by_role('heading',name='Grip op uw leveranciers')).to_be_visible()
        assert member_page.url==BASE+'/'
        checks.append('Ontvanger accepteert op mobiel met eigen wachtwoord; bevestiging wordt gecontroleerd en het token verdwijnt uit de URL')
        member_page.get_by_role('button',name='Menu openen',exact=True).click()
        expect(member_page.get_by_role('button',name='Gebruikers',exact=True)).to_have_count(0)
        expect(member_page.get_by_role('button',name='Import / export',exact=True)).to_have_count(0)
        member_page.get_by_role('button',name='Leveranciers',exact=True).click()
        select=member_page.get_by_label('Prijzen invoeren voor',exact=True)
        expect(select.locator('option')).to_have_count(1);expect(select.locator('option')).to_have_text('TVE')
        expect(member_page.get_by_role('button',name='Productregel toevoegen',exact=True)).to_have_count(0)
        expect(member_page.get_by_role('button',name='Exporteren',exact=True)).to_have_count(0)
        expect(member_page.locator('.product-inline input')).to_have_count(0)
        member_page.get_by_label('Zoek leverancier',exact=True).fill('Privé ander bedrijf')
        expect(member_page.locator('.product-prices-table tbody tr')).to_have_count(0)
        member_page.get_by_label('Zoek leverancier',exact=True).fill('Uitnodiging leverancier')
        expect(member_page.locator('.product-prices-table tbody tr')).to_have_count(1)
        price=member_page.get_by_label('Prijs Uitnodiging leverancier, Testproduct, TVE',exact=True)
        expect(price).to_have_value('12,34');price.fill('35,50');price.press('Enter');expect(price).to_have_value('35,50')
        latest=owner_api.get('/api/state').json();supplier=next(s for s in latest['state']['suppliers'] if s['name']=='Uitnodiging leverancier')
        row=next(r for r in latest['state']['rows'] if r['supplier_id']==supplier['id'])
        assert row['company_prices']=={tve:'35.50',forty:'99.99'}
        checks.append('Bedrijfsgebruiker ziet alleen eigen leveranciers en bedrijfsprijzen en kan geen beheer-, export- of productbewerkingen openen')
        member_page.get_by_role('button',name='Uitnodiging leverancier',exact=True).click()
        dialog=member_page.get_by_role('dialog',name='Alle prijzen per leverancier',exact=True)
        expect(dialog.locator('.supplier-price-matrix thead th')).to_have_count(2)
        expect(dialog.get_by_label('Totaal alle bedrijfsprijzen',exact=True)).to_have_text('€ 35,50')
        expect(dialog.get_by_role('button',name='Excel',exact=True)).to_have_count(0)
        dialog.get_by_role('button',name='Testproduct',exact=True).click()
        expect(member_page.get_by_role('dialog',name='Product bekijken',exact=True)).to_be_visible()
        detail_price=member_page.get_by_label('Productprijs TVE (€)',exact=True)
        detail_price.fill('45,60');detail_price.press('Enter');expect(detail_price).to_have_value('45,60')
        member_page.get_by_role('button',name='Sluiten',exact=True).click()
        expect(price).to_have_value('45,60')
        member_page.get_by_role('button',name='Totaalprijzen per bedrijf',exact=True).click()
        expect(member_page.get_by_label('Totaal bedrijfsprijzen Uitnodiging leverancier',exact=True)).to_have_text('€ 45,60')
        expect(member_page.get_by_role('button',name='Handmatige totaalprijzen',exact=True)).to_have_count(0)
        member_page.screenshot(path=str(ROOT/'test-results/bedrijfsgebruiker-mobiel.png'),full_page=True,animations='disabled')
        checks.append('Eigen prijzen zijn ook in het detailvenster bewerkbaar; leverancierssommen bevatten alleen eigen bedrijfsprijzen')
        owner_page.get_by_role('button',name='Vernieuwen',exact=True).click()
        owner_page.get_by_role('button',name='Bewerk toegang voor collega@example.test',exact=True).click()
        owner_page.get_by_label('TVE',exact=True).uncheck();owner_page.get_by_label('FORTY FIVE',exact=True).check()
        owner_page.get_by_role('button',name='Toegang opslaan',exact=True).click()
        expect(owner_page.get_by_role('dialog')).not_to_be_visible()
        expect(member_page.get_by_role('heading',name='Welkom terug',exact=True)).to_be_visible(timeout=20000)
        member_page.get_by_label('E-mailadres',exact=True).fill('collega@example.test')
        member_page.get_by_label('Wachtwoord',exact=True).fill('personal-colleague-password')
        member_page.get_by_role('button',name='Inloggen',exact=True).click()
        expect(member_page.get_by_role('heading',name='Grip op uw leveranciers')).to_be_visible()
        expect(member_page.locator('.company-access-note')).to_contain_text('FORTY FIVE')
        checks.append('Bedrijfstoegang wijzigen beëindigt bestaande sessies; opnieuw inloggen gebruikt direct de nieuwe rechten')
        owner_page.get_by_role('button',name='Bewerk toegang voor collega@example.test',exact=True).click()
        owner_page.get_by_label('Toegang actief',exact=True).uncheck()
        owner_page.get_by_role('button',name='Toegang opslaan',exact=True).click()
        expect(owner_page.get_by_role('dialog')).not_to_be_visible()
        member_page.reload();expect(member_page.get_by_role('heading',name='Welkom terug',exact=True)).to_be_visible()
        member_page.get_by_label('E-mailadres',exact=True).fill('collega@example.test')
        member_page.get_by_label('Wachtwoord',exact=True).fill('personal-colleague-password')
        member_page.get_by_role('button',name='Inloggen',exact=True).click()
        expect(member_page.get_by_role('alert')).to_contain_text('onjuist')
        owner_page.get_by_role('button',name='Bewerk toegang voor collega@example.test',exact=True).click()
        owner_page.get_by_label('Toegang actief',exact=True).check()
        owner_page.get_by_role('button',name='Toegang opslaan',exact=True).click()
        expect(owner_page.get_by_role('dialog')).not_to_be_visible()
        member_page.get_by_role('button',name='Inloggen',exact=True).click()
        expect(member_page.get_by_role('heading',name='Grip op uw leveranciers')).to_be_visible()
        checks.append('Toegang uitzetten weigert login en wist sessies; opnieuw activeren behoudt het persoonlijke wachtwoord')
        owner_page.get_by_role('button',name='Gebruiker uitnodigen',exact=True).click()
        owner_page.get_by_label('E-mailadres van de gebruiker',exact=True).fill('canceled@example.test')
        owner_page.get_by_label('TVE',exact=True).check()
        owner_page.get_by_role('button',name='Uitnodigingslink maken',exact=True).click()
        expect(owner_page.get_by_role('dialog')).not_to_be_visible()
        canceled=owner_page.get_by_label('Uitnodigingslink',exact=True).input_value()
        owner_page.get_by_role('button',name='Uitnodiging intrekken',exact=True).click()
        expect(owner_page.get_by_label('Uitnodigingslink',exact=True)).to_have_count(0)
        visitor_context=context();visitor_page=page_in(visitor_context)
        visitor_page.goto(canceled);expect(visitor_page.get_by_role('alert')).to_contain_text('niet meer geldig')
        expect(visitor_page.get_by_role('button',name='Account activeren',exact=True)).to_have_count(0)
        visitor_page.goto(link);expect(visitor_page.get_by_role('alert')).to_contain_text('niet meer geldig')
        checks.append('Ingetrokken en al gebruikte uitnodigingslinks kunnen geen nieuw account aanmaken')
        owner_page.set_viewport_size({'width':390,'height':844});owner_page.wait_for_timeout(350)
        assert owner_page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        owner_page.screenshot(path=str(ROOT/'test-results/gebruikers-mobiel.png'),full_page=True,animations='disabled')
        process.terminate();process.wait(10);process=start()
        member_page.reload();expect(member_page.get_by_role('heading',name='Grip op uw leveranciers')).to_be_visible()
        expect(member_page.locator('.company-access-note')).to_contain_text('FORTY FIVE')
        owner_page.reload();expect(owner_page.get_by_role('heading',name='Grip op uw leveranciers')).to_be_visible()
        owner_page.get_by_role('button',name='Menu openen',exact=True).click()
        owner_page.get_by_role('button',name='Gebruikers',exact=True).click()
        expect(owner_page.get_by_role('button',name='Bewerk toegang voor collega@example.test',exact=True)).to_be_visible()
        checks.append('Persoonlijke accounts, rechten, wachtwoorden en sessies blijven behouden na een daadwerkelijke backendherstart; mobiel loopt niet over')
        assert not errors,errors;checks.append('Geen JavaScript-runtimefouten')
        owner_api.close();browser.close()
    suffix='-published' if args.published else ''
    (ROOT/f'test-results/uitnodigingen-browser{suffix}.json').write_text(json.dumps({'passed':checks,'frontend':BASE,'authenticated_api':'isolated local SQLite','production_data_changed':False},ensure_ascii=False,indent=2))
    print(json.dumps({'passed':checks},ensure_ascii=False,indent=2))
finally:
    process.terminate();process.wait(10);log.close();client.close()
