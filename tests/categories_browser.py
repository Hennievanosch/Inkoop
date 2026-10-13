import argparse, json, os, socket, subprocess, tempfile, time
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright, expect

root=Path(__file__).resolve().parents[1]
(root/'test-results').mkdir(exist_ok=True)
parser=argparse.ArgumentParser();parser.add_argument('--published',action='store_true');args=parser.parse_args()
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
local=f'http://127.0.0.1:{port}'
base='https://tve-leveranciers.vercel.app' if args.published else local
folder=Path(tempfile.mkdtemp(prefix='tve-search-'))
env={**os.environ,'TVE_DB_PATH':str(folder/'buttons.sqlite')}
for key in ('SUPABASE_DB_URL','DATABASE_URL','VERCEL'):env.pop(key,None)
log=open(folder/'server.log','w')
process=subprocess.Popen([str(root/'.venv/bin/python'),'-m','uvicorn','backend.app:app','--host','127.0.0.1','--port',str(port)],cwd=root,env=env,stdout=log,stderr=log)
client=httpx.Client(timeout=45,follow_redirects=True)
try:
    for _ in range(100):
        try:
            if client.get(local+'/api/health').is_success:break
        except httpx.HTTPError:pass
        time.sleep(.1)
    else:raise RuntimeError('Lokale controle kon niet starten.')
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
        context=browser.new_context(viewport={'width':1440,'height':1000})
        if args.published:
            def transport(route):
                req=route.request
                headers={k:v for k,v in req.all_headers().items() if k.lower() not in ('host','content-length','accept-encoding')}
                is_api=req.url.startswith(base+'/api/')
                url=local+req.url[len(base):] if is_api else req.url
                if is_api and headers.get('origin')==base:headers['origin']=local
                client.cookies.clear()
                response=client.request(req.method,url,headers=headers,content=req.post_data_buffer)
                response_headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-encoding','content-length','transfer-encoding')}
                route.fulfill(status=response.status_code,headers=response_headers,body=response.content)
            context.route(base+'/**',transport)
        page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(base+'/#setup='+(folder/'buttons.token').read_text().strip())
        page.get_by_label('E-mailadres',exact=True).fill('buttons@example.test')
        page.get_by_label('Wachtwoord (minstens 12 tekens)',exact=True).fill('isolated-buttons-password')
        page.get_by_role('button',name='Account aanmaken',exact=True).click()
        expect(page.get_by_role('heading',name='Grip op uw leveranciers')).to_be_visible()
        with httpx.Client(base_url=local,timeout=25) as owner:
            assert owner.post('/api/auth/login',json={'email':'buttons@example.test','password':'isolated-buttons-password'}).is_success
            before=owner.get('/api/state').json()['state']
            original_rows={row['id']:row for row in before['rows']}
            categories={c['name']:c['id'] for c in before['categories']}
            supplier=next(s for s in before['suppliers'] if s['name']=='3M')
            company=next(c for c in before['companies'] if c['name']=='TVE')
            page.get_by_role('button',name='Categorieën',exact=True).click()
            expect(page.get_by_text('4 nog niet gekoppeld',exact=False)).to_be_visible()
            airtex=page.locator('.entity-table tbody tr').filter(has=page.get_by_role('button',name='Airtex',exact=True))
            expect(airtex.get_by_text('Nog niet gekoppeld',exact=True)).to_be_visible()
            airtex.get_by_role('button',name='Leverancier koppelen aan Airtex',exact=True).click()
            expect(page.get_by_role('dialog',name='Leverancier koppelen',exact=True)).to_be_visible()
            expect(page.get_by_label('Productcategorie',exact=True)).to_have_value(categories['Airtex'])
            expect(page.get_by_role('button',name='Bestaande leverancier',exact=True)).to_have_class('active')
            page.get_by_label('Leverancier',exact=True).select_option(supplier['id'])
            page.get_by_label('Productnaam',exact=True).fill('Airtex proefproduct')
            page.get_by_label('Productprijs TVE (€)',exact=True).fill('12,34')
            page.locator('.company-checks').get_by_text('TVE',exact=True).click()
            page.get_by_role('button',name='Opslaan',exact=True).click()
            expect(page.get_by_role('dialog')).to_have_count(0)
            expect(airtex.get_by_text('In gebruik',exact=True)).to_be_visible()
            after=owner.get('/api/state').json()['state']
            assert len(after['suppliers'])==56 and len(after['rows'])==64
            assert all(row==original_rows[row['id']] for row in after['rows'] if row['id'] in original_rows)
            added=next(row for row in after['rows'] if row['id'] not in original_rows)
            assert added['supplier_id']==supplier['id'] and added['category_id']==categories['Airtex']
            assert added['company_ids']==[company['id']] and added['company_prices'][company['id']]=='12.34'
            page.reload();expect(page.get_by_role('heading',name='Grip op uw leveranciers')).to_be_visible()
            search=page.get_by_label('Zoek leverancier',exact=True)
            search.fill('bestaat-helemaal-niet-987')
            page.get_by_label('Filter leverancier',exact=True).select_option(supplier['id'])
            page.get_by_label('Filter bedrijf',exact=True).select_option(company['id'])
            page.get_by_label('Filter categorie',exact=True).select_option(categories['Airtex'])
            page.get_by_role('button',name='Categorieën',exact=True).click()
            page.get_by_role('button',name='Bekijk leveranciers voor Folie',exact=True).click()
            folie_count=sum(row['category_id']==categories['Folie'] for row in after['rows'])
            expect(page.locator('.suppliers-panel .count-badge')).to_have_text(str(folie_count)+' regels')
            expect(page.locator('.supplier-selection')).to_contain_text('Folie')
            expect(page.locator('.supplier-selection')).not_to_contain_text('bestaat-helemaal-niet')
            page.get_by_role('button',name='Categorieën',exact=True).click()
            page.get_by_role('button',name='Leverancier koppelen aan Contour markering',exact=True).click()
            page.get_by_role('button',name='Nieuwe leverancier',exact=True).click()
            page.get_by_label('Leveranciersnaam',exact=True).fill('Categorie Testleverancier')
            page.get_by_role('button',name='Opslaan',exact=True).click()
            expect(page.get_by_role('dialog')).to_have_count(0)
            expect(page.get_by_text('2 nog niet gekoppeld',exact=False)).to_be_visible()
            final=owner.get('/api/state').json()['state']
            assert len(final['suppliers'])==57 and len(final['rows'])==65
            page.get_by_label('Zoek categorie',exact=True).fill(' contour  ')
            expect(page.locator('.entity-table tbody tr')).to_have_count(1)
            page.get_by_label('Zoek categorie',exact=True).fill('')
            page.get_by_role('button',name='Dashboard',exact=True).click()
            expect(page.locator('.filter-bar')).to_be_visible()
            page.get_by_label('Zoek leverancier',exact=True).fill('bestaat-helemaal-niet-987')
            page.locator('.chart-column').first.click()
            expect(page.locator('.suppliers-panel .count-badge')).to_have_text('0 regels')
            expect(page.locator('.filter-bar')).to_have_count(0)
            page.get_by_role('button',name='Filters wissen en leveranciers tonen',exact=True).click()
            expect(page.locator('.suppliers-panel .count-badge')).to_have_text('65 regels')
            page.locator('a.brand').click()
            expect(page.locator('.filter-bar')).to_be_visible()
            expect(page.get_by_label('Zoek leverancier',exact=True)).to_have_value('')
            page.get_by_role('button',name='Categorieën',exact=True).click()
            page.screenshot(path=str(root/'test-results/categorieen-koppelen.png'),full_page=True,animations='disabled')
            for width in (768,390):
                page.set_viewport_size({'width':width,'height':1000 if width>500 else 844})
                page.wait_for_timeout(150)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(root/f'test-results/categorieen-{width}.png'),full_page=True,animations='disabled')
        assert not errors,errors
        report={'frontend':base,'unused_excel_choices_preserved':True,'category_prefilled_with_existing_supplier_option':True,'links_existing_and_new_suppliers':True,'retains_other_product_rows_and_prices':True,'saved_links_survive_reload':True,'category_drill_clears_unrelated_filters':True,'empty_supplier_table_can_show_all_records':True,'homepage_keeps_search_controls':True,'category_search_handles_spaces':True,'tablet_and_mobile':True,'javascript_errors':errors,'authenticated_api':'isolated local SQLite','production_data_changed':False}
        suffix='-published' if args.published else ''
        (root/f'test-results/categorieen{suffix}.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))
        browser.close()
finally:
    process.terminate()
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:process.kill();process.wait()
    client.close();log.close()
