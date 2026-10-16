"""Check complete supplier lists beyond 100 entries against an isolated SQLite database.

Run after the frontend build with the environment Python containing Playwright.
No production data or credentials are used.
"""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
folder = Path(tempfile.mkdtemp(prefix='tve-suppliers-scroll-'))
env = {**os.environ, 'TVE_DB_PATH': str(folder / 'scroll.sqlite')}
for name in ['DATABASE_URL', 'SUPABASE_DB_URL', 'VERCEL']:
    env.pop(name, None)
subprocess.run([sys.executable, '-c', 'from backend.app import initialize; initialize()'],
               cwd=ROOT, env=env, check=True, capture_output=True)
with sqlite3.connect(env['TVE_DB_PATH']) as db:
    state = json.loads(db.execute('SELECT payload FROM store WHERE id=1').fetchone()[0])
    for n in range(47):
        supplier_id = f'scroll-supplier-{n}'
        state['suppliers'].append({'id': supplier_id, 'name': f'ZZZ scroll {n:03d}'})
        state['rows'].append({'id': f'scroll-row-{n}', 'supplier_id': supplier_id,
                              'category_id': state['categories'][0]['id'],
                              'company_ids': [state['companies'][0]['id']], 'values': {}})
    db.execute('UPDATE store SET payload=? WHERE id=1', (json.dumps(state),))
row_count, supplier_count = len(state['rows']), len(state['suppliers'])
assert row_count == 110 and supplier_count == 103
with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
base = f'http://127.0.0.1:{port}'
with (folder / 'server.log').open('w') as log:
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app:app',
                                '--host', '127.0.0.1', '--port', str(port)],
                               cwd=ROOT, env=env, stdout=log, stderr=log)
    try:
        with httpx.Client(timeout=1, trust_env=False) as client:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError('Testserver gestopt: ' + (folder / 'server.log').read_text())
                try:
                    if client.get(base + '/api/health').is_success:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            else:
                raise RuntimeError('Testserver niet gereed')
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
                                        args=['--no-sandbox'])
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/#setup=' + (folder / 'scroll.token').read_text().strip())
            page.get_by_label('E-mailadres', exact=True).fill('scroll@example.test')
            page.get_by_label('Wachtwoord (minstens 12 tekens)', exact=True).fill('isolated-scroll-password')
            page.get_by_role('button', name='Account aanmaken', exact=True).click()
            expect(page.get_by_role('heading', name='Grip op uw leveranciers')).to_be_visible()
            page.locator('.chart-column').first.click()
            page.get_by_role('button', name='Alle leveranciers tonen', exact=True).click()
            table = page.locator('.suppliers-panel')
            expect(table.locator('tbody tr')).to_have_count(row_count)
            table.locator('tbody tr').last.scroll_into_view_if_needed()
            expect(table.locator('tbody tr').last).to_contain_text('ZZZ scroll 046')
            expect(table.get_by_label('Regels per pagina')).to_have_count(0)
            expect(page.get_by_role('button', name='Volgende pagina', exact=True)).to_have_count(0)
            select_all = table.get_by_label('Selecteer alle gefilterde regels', exact=True)
            select_all.check()
            expect(table.locator('.selection-bar')).to_contain_text('110 regels geselecteerd')
            select_all.uncheck()
            expect(table.locator('.selection-bar')).to_have_count(0)
            table.get_by_role('button', name='Leverancier', exact=True).click()
            expect(table.locator('tbody tr').first).to_contain_text('ZZZ scroll 046')
            print('PASS: alle 110 productregels, laatste regel bereikbaar, sorteren en alles selecteren')

            page.get_by_role('button', name='Totaalprijzen per bedrijf', exact=True).click()
            expect(page.locator('.calculated-prices-table tbody tr')).to_have_count(supplier_count)
            page.locator('.calculated-prices-table tbody tr').last.scroll_into_view_if_needed()
            expect(page.locator('.calculated-prices-table tbody tr').last).to_contain_text('ZZZ scroll 046')
            page.get_by_role('button', name='Handmatige totaalprijzen', exact=True).click()
            expect(page.locator('.price-table tbody tr')).to_have_count(supplier_count)
            expect(page.get_by_label('Leveranciers per pagina')).to_have_count(0)
            print('PASS: beide totaalprijsoverzichten tonen alle 103 leveranciers')

            page.get_by_role('button', name='Dashboard', exact=True).click()
            page.get_by_label('Filter leverancier', exact=True).select_option('scroll-supplier-46')
            page.locator('.chart-column').first.click()
            expect(page.locator('.suppliers-panel tbody tr')).to_have_count(1)
            expect(page.locator('.suppliers-panel tbody tr')).to_contain_text('ZZZ scroll 046')
            page.get_by_role('button', name='Alle leveranciers tonen', exact=True).click()
            expect(page.locator('.suppliers-panel tbody tr')).to_have_count(row_count)
            print('PASS: filteren en filters wissen behouden de volledige lijst')

            page.set_viewport_size({'width': 390, 'height': 844})
            page.locator('.suppliers-panel tbody tr').last.scroll_into_view_if_needed()
            expect(page.locator('.suppliers-panel tbody tr')).to_have_count(row_count)
            expect(page.get_by_role('button', name='Volgende pagina', exact=True)).to_have_count(0)
            assert not errors, errors
            print('PASS: mobiele lijst zonder paginering en zonder browserfouten')
            browser.close()
    finally:
        process.terminate()
        process.wait(timeout=10)
