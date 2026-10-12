"""Verify the new dashboard and complete product list against disposable data."""
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parent.parent
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
base=f'http://127.0.0.1:{port}'
with tempfile.TemporaryDirectory(prefix='tve-period-browser-') as folder:
    env={**os.environ,'TVE_DB_PATH':str(Path(folder)/'browser.sqlite')}
    for key in ['VERCEL','SUPABASE_DB_URL','DATABASE_URL']:env.pop(key,None)
    with open(Path(folder)/'server.log','w') as log:
        process=subprocess.Popen([sys.executable,'-m','uvicorn','backend.app:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=log)
        try:
            for _ in range(100):
                try:
                    if httpx.get(base+'/api/health').is_success:break
                except httpx.HTTPError:pass
                time.sleep(.1)
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
                page=browser.new_page(viewport={'width':1440,'height':1100});errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(base+'/#setup='+Path(folder,'browser.token').read_text().strip())
                page.get_by_label('E-mailadres',exact=True).fill('period@example.test')
                page.get_by_label('Wachtwoord (minstens 12 tekens)',exact=True).fill('isolated-period-password')
                page.get_by_role('button',name='Account aanmaken',exact=True).click()
                expect(page.get_by_role('heading',name='Bedrijfsoverzicht',exact=True)).to_be_visible()
                expect(page.get_by_role('heading',name='Groepsoverzicht',exact=True)).to_be_visible()
                expect(page.locator('.period-bars').first.locator('.period-bar')).to_have_count(1)
                reporting=page.request.get(base+'/api/reporting').json()
                assert [p['key'] for p in reporting['series']]==['2026']
                assert page.locator('.period-bars').first.locator('.period-bar').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.period)')==['2026']
                expect(page.locator('.period-trend line')).to_have_count(0)
                for removed in ['Leveranciers per categorie','Categorieën × bedrijven','Verbindingen met bedrijven']:
                    expect(page.get_by_role('heading',name=removed,exact=True)).to_have_count(0)
                expect(page.get_by_role('button',name='Invoer voor deze periode bevestigen')).to_have_count(0)
                page.get_by_text('Invoerperiode en herinneringen instellen',exact=True).click()
                expect(page.get_by_label('Periode',exact=True)).to_have_value('quarter')
                expect(page.get_by_label('Deadline in de laatste maand')).to_have_value('day25')
                page.get_by_label('Periode',exact=True).select_option('month')
                page.get_by_role('button',name='Instellingen opslaan').click()
                expect(page.get_by_role('heading',name='Jaargegevens 2026 · informatief',exact=True)).to_be_visible()
                (ROOT/'test-results').mkdir(exist_ok=True)
                page.screenshot(path=str(ROOT/'test-results/period-dashboard.png'),full_page=True)
                page.get_by_role('button',name='Categorieën',exact=True).click()
                page.locator('.entity-table button[aria-label^="Bewerk "]').first.click()
                dialog=page.get_by_role('dialog');expect(dialog).to_be_visible()
                original=dialog.get_by_label('Categorienaam').input_value()
                state=page.request.get(base+'/api/state').json()['state']
                category=next(c for c in state['categories'] if c['name']==original)
                linked=[r['id'] for r in state['rows'] if r['category_id']==category['id']]
                dialog.get_by_label('Categorienaam').fill('Browsercontrole categorie')
                dialog.get_by_role('button',name='Opslaan',exact=True).click()
                expect(dialog).to_have_count(0)
                state=page.request.get(base+'/api/state').json()['state']
                assert next(c for c in state['categories'] if c['id']==category['id'])['name']=='Browsercontrole categorie'
                assert [r['id'] for r in state['rows'] if r['category_id']==category['id']]==linked
                page.get_by_role('button',name='Bedrijven',exact=True).click()
                page.get_by_role('button',name='Bewerk TVE',exact=True).click()
                expect(page.get_by_role('dialog').get_by_label('Bedrijfsnaam')).to_have_value('TVE')
                page.get_by_role('button',name='Sluiten',exact=True).click()
                page.get_by_role('button',name='Leveranciers',exact=True).click()
                expect(page.locator('.product-prices-table tbody tr')).to_have_count(63)
                expect(page.get_by_label('Producten per pagina')).to_have_count(0)
                price=page.locator('.product-prices-table tbody tr').first.locator('.price-input input')
                price.fill('12,34');price.press('Enter')
                expect(page.locator('.product-prices-table tbody tr').first).to_contain_text('Ingevoerd:')
                row=page.locator('.product-prices-table tbody tr').first
                row.locator('input[type=date]').fill('2026-06-30')
                price.fill('8,00');price.press('Enter')
                expect(price).to_have_value('8,00')
                expect(page.locator('.save-state')).to_contain_text('Alle wijzigingen opgeslagen')
                report=page.request.get(base+'/api/reporting').json()
                assert [p['key'] for p in report['series']]==['2026'],report
                assert report['series'][-1]['total']=='8.00',report
                page.set_viewport_size({'width':390,'height':844})
                page.get_by_role('button',name='Menu openen',exact=True).click()
                page.get_by_role('button',name='Dashboard',exact=True).click()
                expect(page.get_by_role('heading',name='Bedrijfsoverzicht',exact=True)).to_be_visible()
                page.screenshot(path=str(ROOT/'test-results/period-dashboard-mobile.png'),full_page=True)
                state=page.request.get(base+'/api/state').json()['state']
                company_id=state['companies'][0]['id']
                invitation=page.request.post(base+'/api/users/invite',data={'email':'company@example.test','display_name':'Bedrijf','role':'company','company_ids':[company_id]}).json()
                page.request.post(base+'/api/auth/logout',data={})
                page.request.post(base+'/api/auth/accept-invitation',data={'token':invitation['token'],'password':'isolated-company-password'})
                page.reload()
                expect(page.get_by_role('heading',name='Overzicht voor uw bedrijven',exact=True)).to_be_visible()
                expect(page.get_by_role('heading',name='Groepsoverzicht',exact=True)).to_be_visible()
                expect(page.get_by_label('Bedrijf in het overzicht')).to_have_count(0)
                assert not errors,errors
                browser.close()
                print('Browser OK: periods, group comparison, config save, 63 products, entry date and mobile dashboard')
        finally:
            process.terminate();process.wait(timeout=10)
