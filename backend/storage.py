"""Connection adapters for local SQLite and private Supabase PostgreSQL storage."""
import os
import re
import sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
DB_PATH=Path(os.environ.get('TVE_DB_PATH',ROOT/'data/tve.sqlite'))
DATABASE_URL=os.environ.get('SUPABASE_DB_URL') or os.environ.get('DATABASE_URL')
IS_POSTGRES=bool(DATABASE_URL)
IS_VERCEL=os.environ.get('VERCEL')=='1'
STORAGE_NAME='Supabase / PostgreSQL' if IS_POSTGRES else 'SQLite'
_supabase_ca_path=None


def database_ca():
    """Trust Supabase's published database CA while preserving HTTPS verification."""
    global _supabase_ca_path
    explicit=os.environ.get('TVE_DATABASE_CA')
    if explicit:return explicit
    bundled=ROOT/'supabase/prod-ca-2021.crt'
    if bundled.exists():return str(bundled)
    if _supabase_ca_path:return _supabase_ca_path
    # Official certificate used by the Supabase dashboard's SSL configuration.
    # HTTPS validates the artifact transport; libpq then validates DB host and CA.
    import httpx
    import ssl
    import tempfile
    try:
        response=httpx.get('https://supabase-downloads.s3.amazonaws.com/prod/ssl/prod-ca-2021.crt',timeout=20)
        response.raise_for_status()
        if len(response.content)>16384 or b'-----BEGIN CERTIFICATE-----' not in response.content:
            raise ValueError('Invalid CA artifact')
        with tempfile.NamedTemporaryFile(prefix='tve-supabase-ca-',suffix='.crt',delete=False) as file:
            file.write(response.content)
            path=file.name
        ssl.create_default_context(cafile=path)
        _supabase_ca_path=path
        return path
    except (httpx.HTTPError,ValueError,ssl.SSLError):
        import logging
        logging.getLogger(__name__).error('Official Supabase database CA unavailable')
        raise RuntimeError('Het Supabase-databasecertificaat is tijdelijk niet beschikbaar.') from None


class Row(dict):
    def __getitem__(self,key):
        if isinstance(key,int):return list(self.values())[key]
        return super().__getitem__(key)


class Cursor:
    def __init__(self,cursor):self.cursor=cursor
    def fetchone(self):
        result=self.cursor.fetchone()
        return Row(result) if result is not None else None
    def fetchall(self):return [Row(row) for row in self.cursor.fetchall()]
    def __iter__(self):return iter(self.fetchall())


class PostgresConnection:
    def __init__(self):
        import psycopg
        from psycopg.rows import dict_row
        # Production TLS uses hostname and CA validation. Only loopback test databases
        # may explicitly use sslmode=disable, and that is never used for Supabase.
        from urllib.parse import urlparse
        parsed=urlparse(DATABASE_URL)
        is_loopback=parsed.hostname in ['127.0.0.1','localhost','::1']
        options={'connect_timeout':12,'row_factory':dict_row,'prepare_threshold':None}
        if not is_loopback:
            options.update(sslmode='verify-full',sslrootcert=database_ca())
        try:self.connection=psycopg.connect(DATABASE_URL,**options)
        except psycopg.OperationalError as error:
            # Log only an allowlisted diagnosis, never connection strings or secrets.
            import logging
            detail=str(error).lower()
            kind=('TLS certificate' if 'certificate' in detail else
                  'authentication' if any(x in detail for x in ('password','authentication','tenant','user not found')) else
                  'DNS' if any(x in detail for x in ('resolve','translate host')) else
                  'timeout' if 'timeout' in detail else
                  'connection refused' if 'refused' in detail else 'connection unavailable')
            logging.getLogger(__name__).error('PostgreSQL connection: %s',kind)
            raise RuntimeError('De PostgreSQL-verbinding is tijdelijk niet beschikbaar.') from None
        self.connection.execute('SET search_path TO tve, pg_catalog')
        self.connection.execute("SET statement_timeout TO '20000ms'")

    def __enter__(self):return self
    def __exit__(self,exc_type,exc,tb):
        try:
            if exc_type:self.connection.rollback()
            else:self.connection.commit()
        finally:self.connection.close()

    def execute(self,sql,params=()):
        if sql=='BEGIN IMMEDIATE':
            # One transaction-scoped lock protects read/check/write and account creation
            # across independent Vercel instances. READ COMMITTED sees fresh data after waiting.
            return Cursor(self.connection.execute('SELECT pg_advisory_xact_lock(1964098801)'))
        # Psycopg parses every percent sign whenever parameters are supplied,
        # even for an empty tuple. SQL LIKE wildcards must remain SQL literals.
        # This matters for the completion settings included in a backup.
        if params:sql=sql.replace('%','%%').replace('?', '%s')
        sql=re.sub(r'\browid\b','seq',sql)
        if sql.startswith('INSERT OR REPLACE INTO rate_limits'):
            sql=sql.replace('INSERT OR REPLACE','INSERT')+' ON CONFLICT(key) DO UPDATE SET count=EXCLUDED.count, until=EXCLUDED.until'
        elif sql.startswith('INSERT OR IGNORE'):
            sql=sql.replace('INSERT OR IGNORE','INSERT')+' ON CONFLICT DO NOTHING'
        return Cursor(self.connection.execute(sql,params if params else None))

    def executescript(self,script):
        import psycopg
        try:self.connection.execute(script)
        except psycopg.Error as error:
            import logging
            # This method only runs the fixed public schema, with no secret values.
            logging.getLogger(__name__).error('PostgreSQL schema: %s %s',error.sqlstate,error.diag.message_primary)
            raise RuntimeError('Het databaseschema kon niet worden gecontroleerd.') from None

    def commit(self):
        self.connection.commit()


def connect():
    if IS_VERCEL and not IS_POSTGRES:
        raise RuntimeError('Supabase is nog niet geconfigureerd. Stel SUPABASE_DB_URL in op Vercel; lokale opslag is daar niet toegestaan.')
    if IS_POSTGRES:return PostgresConnection()
    conn=sqlite3.connect(DB_PATH,timeout=15)
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=15000')
    return conn
