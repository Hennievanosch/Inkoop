"""Check the deployed frontend with a temporary local backend.

Production accounts/data are never changed. HTTPS assets use verified TLS;
only API requests are routed to this test's isolated SQLite fixture.
"""
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parent.parent
BASE='https://tve-leveranciers.vercel.app'
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
LOCAL=f'http://127.0.0.1:{port}'
folder=Path(tempfile.mkdtemp(prefix='tve-prices-preview-'))
env={**os.environ,'TVE_DB_PATH':str(folder/'preview.sqlite')}
for key in ['SUPABASE_DB_URL','DATABASE_URL','VERCEL']:env.pop(key,None)
log=open(folder/'server.log','w')
process=subprocess.Popen([str(ROOT/'.venv/bin/python'),'-m','uvicorn','backend.app:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=log)
checks=[]
try:
    with httpx.Client(timeout=45,follow_redirects=True) as client:
        for _ in range(100):
            try:
                if client.get(LOCAL+'/api/health').is_success:break
            except httpx.HTTPError:pass
            time.sleep(.1)
        else:raise RuntimeError('De geïsoleerde testserver kon niet starten.')
        assert client.get(BASE+'/api/health').json()['storage']=='Supabase / PostgreSQL'
        assert client.get(BASE+'/api/state').status_code==401
        checks.append('Werkelijke productie-API: Supabase gezond en gegevens vereisen inloggen')
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
            context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True)
            def transport(route):
                request=route.request
                headers={k:v for k,v in request.headers.items() if k.lower() not in ['host','content-length','accept-encoding']}
                local=request.url.startswith(BASE+'/api/')
                target=LOCAL+request.url[len(BASE):] if local else request.url
                if local and headers.get('origin')==BASE:headers['origin']=LOCAL
                # Browser cookies are forwarded explicitly; the HTTP client must
                # not inject another host's cookies into requests.
                client.cookies.clear()
                response=client.request(request.method,target,headers=headers,content=request.post_data_buffer)
                response_headers={k:v for k,v in response.headers.items() if k.lower() not in ['content-encoding','content-length','transfer-encoding']}
                route.fulfill(status=response.status_code,headers=response_headers,body=response.content)
            context.route(BASE+'/**',transport)
            page=context.new_page();errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(BASE+'/#setup='+(folder/'preview.token').read_text().strip())
            page.get_by_label('E-mailadres',exact=True).fill('preview@example.test')
            page.get_by_label('Wachtwoord (minstens 12 tekens)',exact=True).fill('isolated-preview-password')
            page.get_by_role('button',name='Account aanmaken',exact=True).click()
            expect(page.get_by_role('heading',name='Grip op uw leveranciers')).to_be_visible()
            page.get_by_role('button',name='Leveranciers',exact=True).click()
            page.get_by_role('button',name='Totaalprijzen per bedrijf',exact=True).click()
            page.get_by_role('button',name='Handmatige totaalprijzen',exact=True).click()
            first=page.locator('.price-table tbody tr').first
            name=first.locator('.supplier-name').inner_text()
            first.locator('input').first.fill('1500,75');first.locator('input').first.press('Enter')
            expect(first.locator('input').first).to_have_value('1500,75')
            expect(page.locator('.save-state')).to_contain_text('Alle wijzigingen opgeslagen')
            page.reload()
            expect(page.get_by_role('heading',name='Grip op uw leveranciers')).to_be_visible()
            page.get_by_role('button',name='Leveranciers',exact=True).click()
            page.get_by_label('Zoek leverancier',exact=True).fill(name)
            page.get_by_role('button',name='Totaalprijzen per bedrijf',exact=True).click()
            page.get_by_role('button',name='Handmatige totaalprijzen',exact=True).click()
            expect(page.get_by_label(f'Totaalprijs {name} voor TVE',exact=True)).to_have_value('1500,75')
            page.get_by_role('button',name=f'Alle prijzen voor {name}',exact=True).click()
            page.get_by_label('Totaalprijs voor FORTY FIVE',exact=True).fill('250,50')
            page.get_by_role('button',name='Prijzen opslaan',exact=True).click()
            expect(page.get_by_role('dialog')).not_to_be_visible()
            checks.append('Gepubliceerde interface: tabblad, celbewerking, formulier en vernieuwen werken met geïsoleerde API')
            page.get_by_role('button',name='Wissen',exact=True).click()
            page.get_by_label('Leveranciers per pagina',exact=True).select_option('60')
            expect(page.locator('.price-table tbody tr')).to_have_count(56)
            scroll=page.locator('.prices-panel .data-table-scroll')
            scroll.evaluate('(node)=>{node.scrollLeft=400}')
            left=scroll.bounding_box()['x']
            assert abs(page.locator('.price-table tbody td').first.bounding_box()['x']-left)<2
            scroll.evaluate('(node)=>{node.scrollLeft=0}')
            page.screenshot(path=str(ROOT/'test-results/prijzen-preview-desktop.png'),full_page=True,animations='disabled')
            page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(350)
            scroll.evaluate('(node)=>{node.scrollLeft=300}')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert abs(page.locator('.price-table tbody td').first.bounding_box()['x']-scroll.bounding_box()['x'])<2
            page.screenshot(path=str(ROOT/'test-results/prijzen-preview-mobiel.png'),full_page=True,animations='disabled')
            checks.append('Gepubliceerde interface: leverancierskolom blijft zichtbaar bij horizontaal scrollen op desktop en mobiel')
            assert not errors,errors
            checks.append('Geen JavaScript-runtimefouten')
            browser.close()
    (ROOT/'test-results/prijzen-preview-report.json').write_text(json.dumps({'passed':checks,'production_data_changed':False,'api_fixture':'isolated local SQLite','frontend':BASE},ensure_ascii=False,indent=2))
    print(json.dumps({'passed':checks},ensure_ascii=False,indent=2))
finally:
    process.terminate();process.wait(10);log.close()
