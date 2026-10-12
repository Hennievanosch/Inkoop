"""Provision this app in the user's authorized Vercel and Supabase accounts.
Only names, IDs, status and public deployment URLs are logged; credentials stay private.
"""
import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote,urlsplit,urlunsplit,parse_qsl
import httpx
from migrate_supabase import migration_sql

ROOT=Path(__file__).resolve().parent.parent
PRIVATE=ROOT/'.deployment/private.json'
PUBLIC=ROOT/'.deployment/status.json'
AUTH_DIR=Path('/workspace/vercel-auth')
CLI=Path('/workspace/deployment-tools/node_modules/.bin/vercel')


def write_private(data):
    PRIVATE.parent.mkdir(parents=True,exist_ok=True);PRIVATE.parent.chmod(0o700)
    fd=os.open(PRIVATE,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:json.dump(data,f)


def load_token():
    value=os.environ.get('VERCEL_TOKEN')
    if value:return value
    file=AUTH_DIR/'auth.json'
    if file.exists():
        file.chmod(0o600)
        data=json.loads(file.read_text())
        if data.get('refreshToken') and data.get('expiresAt',0)<time.time()+60:
            # The official CLI refreshes its OAuth session and updates auth.json.
            result=subprocess.run([str(CLI),'whoami','--global-config',str(AUTH_DIR)],env={**os.environ,'XDG_CACHE_HOME':'/workspace/vercel-auth/cache','VERCEL_TELEMETRY_DISABLED':'1'},capture_output=True,text=True)
            if result.returncode:raise RuntimeError('De Vercel-aanmelding kon niet worden vernieuwd. Meld opnieuw aan via de officiële CLI.')
            data=json.loads(file.read_text())
        return data.get('token')
    return None


def call(base,token,method,path,data=None,params=None):
    # Environment-injected authentication uses the configured HTTPS proxy.
    parsed=urlsplit(path)
    query={**dict(parse_qsl(parsed.query)),**(params or {})}
    with httpx.Client(timeout=60) as client:
        response=client.request(method,base+parsed.path,headers={'Authorization':'Bearer '+token},json=data,params=query)
    if response.status_code>=400:
        raise RuntimeError(f'{base.split("//")[-1]} {method} {path}: HTTP {response.status_code}. Controleer accountrechten/netwerktoegang; er is geen credentialwaarde gelogd.')
    return response.json() if response.content else {}


def vercel_team(explicit):
    if explicit:return explicit
    config=AUTH_DIR/'config.json'
    return json.loads(config.read_text()).get('currentTeam') if config.exists() else None


def prepare_vercel(args):
    token=load_token()
    if not token:raise RuntimeError('De Vercel-aanmelding ontbreekt. Meld u eerst veilig aan via de Vercel CLI.')
    state=json.loads(PRIVATE.read_text()) if PRIVATE.exists() else {'db_password':secrets.token_urlsafe(36),'setup_code':secrets.token_urlsafe(32)}
    team_id=args.vercel_team or state.get('vercel_team') or vercel_team(None)
    team={'teamId':team_id} if team_id else None
    def vc(method,path,data=None):return call('https://api.vercel.com',token,method,path,data,team)
    account=vc('GET','/v2/user')['user']
    print('Vercel-account:',account.get('username') or account.get('name'))
    if not state.get('vercel_project'):
        projects=vc('GET','/v9/projects').get('projects',[])
        if any(x['name']==args.name for x in projects):raise RuntimeError('Er bestaat al een gelijknamig Vercel-project. Het project is niet gewijzigd.')
        created=vc('POST','/v10/projects',{'name':args.name,'framework':None})
        state['vercel_project']=created['id'];state['vercel_org']=team_id or created.get('accountId') or account['id'];state['name']=args.name
        if team_id:state['vercel_team']=team_id
        write_private(state)
        print('Vercel-project aangemaakt:',created['name'])
    else:
        vc('GET','/v9/projects/'+state['vercel_project'])
        print('Vercel-project gekoppeld:',state['name'])
    if not state.get('dashboard_url'):
        teams=vc('GET','/v2/teams').get('teams',[]) if team_id else []
        slug=next((x['slug'] for x in teams if x['id']==team_id),account.get('username'))
        state['dashboard_url']='https://vercel.com/'+slug+'/'+state['name'];write_private(state)
    (ROOT/'.vercel').mkdir(exist_ok=True)
    (ROOT/'.vercel/project.json').write_text(json.dumps({'projectId':state['vercel_project'],'orgId':state['vercel_org'],'projectName':state['name']}))
    prior=json.loads(PUBLIC.read_text()) if PUBLIC.exists() else {}
    PUBLIC.write_text(json.dumps({**prior,'supabase_ref':state.get('supabase_ref'),'vercel_project':state['vercel_project'],'name':state['name'],'dashboard_url':state['dashboard_url'],'database_migrated':state.get('migrated',False),'summary':state.get('summary')},indent=2))
    return state,vc,token


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--name',default='tve-leveranciers');parser.add_argument('--supabase-org');parser.add_argument('--supabase-project');parser.add_argument('--vercel-team');parser.add_argument('--check-access',action='store_true');parser.add_argument('--prepare-vercel',action='store_true');parser.add_argument('--deploy',action='store_true');args=parser.parse_args()
    if args.prepare_vercel:
        state,_,_=prepare_vercel(args)
        print('Projectpagina:',state['dashboard_url'])
        return
    vercel=load_token();supabase=os.environ.get('SUPABASE_ACCESS_TOKEN')
    missing=[name for name,value in [('Vercel-aanmelding of VERCEL_TOKEN',vercel),('SUPABASE_ACCESS_TOKEN',supabase)] if not value]
    if missing:raise RuntimeError('Nog ontbrekend: '+', '.join(missing)+'. Gebruik de aanmelding/omgevingsinstellingen; deel geen waarden in de chat.')
    def sb(method,path,data=None):return call('https://api.supabase.com',supabase,method,path,data)
    team={'teamId':vercel_team(args.vercel_team)} if vercel_team(args.vercel_team) else None
    def vc(method,path,data=None):return call('https://api.vercel.com',vercel,method,path,data,team)
    account=vc('GET','/v2/user')['user'];orgs=sb('GET','/v1/organizations');projects=sb('GET','/v1/projects')
    print('Vercel-account:',account.get('username') or account.get('name'));print('Supabase-organisaties:',', '.join(x['name']+' ('+x.get('slug',x['id'])+')' for x in orgs))
    print('Toegankelijke Supabase-projecten:',', '.join(x['name']+' ('+(x.get('ref') or x['id'])+')' for x in projects))
    if args.check_access:return
    state,vc,vercel=prepare_vercel(args)
    if args.supabase_project:
        project=next((x for x in projects if args.supabase_project in [x.get('ref'),x['id']]),None)
        if not project:raise RuntimeError('Het gekozen Supabase-project is niet toegankelijk.')
        if state.get('supabase_ref') and state['supabase_ref']!=args.supabase_project:raise RuntimeError('Er is al een ander Supabase-project gekoppeld; geen gegevens gewijzigd.')
        state['supabase_ref']=args.supabase_project;state['supabase_region']=project.get('region');write_private(state)
        print('Bestaand Supabase-project gekoppeld:',project['name'])
    if not state.get('supabase_ref'):
        if args.supabase_org:
            org=next((x for x in orgs if args.supabase_org in [x.get('slug'),x['id']]),None)
            if not org:raise RuntimeError('De opgegeven Supabase-organisatie is niet toegankelijk.')
        elif len(orgs)==1:org=orgs[0]
        else:raise RuntimeError('Kies uw Supabase-organisatie of een toegankelijk bestaand project; er is geen project aangemaakt.')
        if any(x['name']==args.name and x.get('organization_slug')==org.get('slug') for x in projects):
            raise RuntimeError('Er bestaat al een gelijknamig Supabase-project. Koppel het bewust of kies een andere naam; het project is niet gewijzigd.')
        created=sb('POST','/v1/projects',{'name':args.name,'organization_slug':org.get('slug',org['id']),'db_pass':state['db_password'],'region_selection':{'type':'specific','code':'eu-central-1'}})
        state['supabase_ref']=created.get('ref') or created['id'];write_private(state)
        print('Supabase-project aangemaakt:',state['supabase_ref'])
    ref=state['supabase_ref']
    ready=sb('GET','/v1/projects/'+ref)
    if ready.get('status')!='ACTIVE_HEALTHY':
        print('Supabase wordt nog ingericht:',ready.get('status'),'; herhaal deze opdracht zodra het project gereed is.');return
    pools=sb('GET',f'/v1/projects/{ref}/config/database/pooler')
    pool=next((x for x in pools if x['database_type']=='PRIMARY' and x['pool_mode']=='transaction'),None)
    if not pool:raise RuntimeError('De Supabase-transactiepooler is nog niet beschikbaar.')
    if not state.get('migrated'):
        # Own role and schema: do not reset an existing project's postgres password.
        state.setdefault('app_role','tve_backend');state.setdefault('role_password',secrets.token_urlsafe(36));write_private(state)
        sql,summary=migration_sql(Path(os.environ.get('TVE_DB_PATH',ROOT/'data/tve.sqlite')),state['setup_code'])
        from migrate_supabase import literal
        role=state['app_role']
        if role!='tve_backend':raise RuntimeError('Onbekende backendrol; migratie gestopt.')
        setup="""DO $role_setup$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='tve_backend') THEN
  RAISE EXCEPTION 'De backendrol bestaat al; er is niets overschreven.';
 END IF;
 CREATE ROLE tve_backend LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD """+literal(state['role_password'])+""";
END $role_setup$;
GRANT tve_backend TO postgres;
GRANT CREATE ON DATABASE postgres TO tve_backend;
"""
        ownership="""ALTER SCHEMA tve OWNER TO tve_backend;
DO $role_ownership$ DECLARE t RECORD; BEGIN
 FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='tve' LOOP
  EXECUTE format('ALTER TABLE tve.%I OWNER TO tve_backend',t.tablename);
 END LOOP;
END $role_ownership$;
REVOKE CREATE ON DATABASE postgres FROM tve_backend;
"""
        sql=sql.replace('SET standard_conforming_strings=on;','SET standard_conforming_strings=on;\n'+setup,1).replace('\nCOMMIT;','\n'+ownership+'\nCOMMIT;')
        sb('POST',f'/v1/projects/{ref}/database/query',{'query':sql,'read_only':False})
        state['migrated']=True;state['summary']=summary;write_private(state);print('Gegevens gemigreerd:',summary)
    username=state['app_role']+'.'+ref
    # Supabase's connection_string is a template with bracketed placeholders.
    # The discrete host/port/database fields are the actual endpoint metadata.
    dsn=urlunsplit(('postgresql',quote(username,safe='')+':'+quote(state['role_password'],safe='')+'@'+str(pool['db_host'])+':'+str(pool['db_port']),'/'+pool['db_name'],'sslmode=verify-full',''))
    for key,value in [('SUPABASE_DB_URL',dsn),('TVE_SETUP_CODE',state['setup_code'])]:
        vc('POST',f'/v10/projects/{state["vercel_project"]}/env?upsert=true',{'key':key,'value':value,'type':'encrypted','target':['production','preview']})
    current=sb('POST',f'/v1/projects/{ref}/database/query',{'query':"SELECT revision,json_array_length(payload::json->'rows') AS rows,json_array_length(payload::json->'suppliers') AS suppliers FROM tve.store WHERE id=1",'read_only':True})
    print('Databasecontrole:',current)
    (ROOT/'.vercel').mkdir(exist_ok=True)
    (ROOT/'.vercel/project.json').write_text(json.dumps({'projectId':state['vercel_project'],'orgId':state['vercel_org'],'projectName':state['name']}))
    PUBLIC.write_text(json.dumps({**json.loads(PUBLIC.read_text()),'supabase_ref':ref,'database_migrated':True,'summary':state['summary']},indent=2))
    if not args.deploy:print('Koppeling voorbereid. Gebruik --deploy om de gecontroleerde app naar Vercel te deployen.');return
    command=[str(CLI),'deploy','--prod','--yes','--cwd',str(ROOT),'--global-config',str(AUTH_DIR)]
    if os.environ.get('VERCEL_TOKEN'):command+=['--token',os.environ['VERCEL_TOKEN']]
    if state.get('vercel_team'):command+=['--scope',state['vercel_team']]
    process=subprocess.run(command,env={**os.environ,'XDG_CACHE_HOME':'/workspace/vercel-auth/cache','VERCEL_TELEMETRY_DISABLED':'1'},capture_output=True,text=True)
    if process.returncode:raise RuntimeError('Vercel-deployment mislukt. Inspecteer de build via Vercel; credentials zijn niet gelogd. '+process.stderr.replace(vercel,'[afgeschermd]').replace(supabase,'[afgeschermd]').replace(state['db_password'],'[afgeschermd]').replace(state.get('role_password','__absent__'),'[afgeschermd]').replace(state['setup_code'],'[afgeschermd]')[-5000:])
    deployment=None
    # Current Vercel CLI emits a structured result when running inside Codex.
    decoder=json.JSONDecoder()
    for start,char in enumerate(process.stdout):
        if char!='{':continue
        try:value,_=decoder.raw_decode(process.stdout[start:])
        except ValueError:continue
        if isinstance(value,dict) and isinstance(value.get('deployment'),dict):deployment=value['deployment']
    urls=[x.strip() for x in process.stdout.splitlines() if x.strip().startswith('https://')]
    url=(deployment.get('productionUrl') or deployment.get('url')) if deployment else (urls[-1] if urls else None)
    if not url:raise RuntimeError('De Vercel-URL is nog niet bevestigd. Controleer de deploymentstatus.')
    PUBLIC.write_text(json.dumps({**json.loads(PUBLIC.read_text()),'url':url,'deployment_url':deployment.get('url') if deployment else url},indent=2))
    with httpx.Client(timeout=30) as client:
        response=client.get(url+'/api/health');response.raise_for_status()
        if response.json().get('storage')!='Supabase / PostgreSQL':raise RuntimeError('De deployment gebruikt niet de verwachte Supabase-opslag.')
        if client.get(url+'/api/state').status_code!=401:raise RuntimeError('De authenticatiecontrole van de publieke deployment is mislukt.')
    print('Vercel-deployment gecontroleerd:',url)
    print('De eenmalige openingslink staat alleen in de privé-status; gebruik scripts/opening_link.py met deze basis-URL.')


if __name__=='__main__':
    try:main()
    except (RuntimeError,httpx.HTTPError) as error:
        print(str(error),file=sys.stderr);sys.exit(1)
