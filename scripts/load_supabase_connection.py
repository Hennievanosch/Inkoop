"""Use a browser-encrypted connection file without exposing its token to chat or logs.

Run with the environment Python (cryptography installed), not the app venv.
The private recipient key stays outside both source and deployment directories.
"""
import argparse
import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT=Path(__file__).resolve().parent.parent
KEY=Path('/workspace/supabase-auth/tve-pairing-key.pem')


def decrypt_connection(file):
    if file.stat().st_size>8192:raise ValueError('Koppelingsbestand te groot.')
    data=json.loads(file.read_text())
    if data.get('format')!='tve-supabase-koppeling' or data.get('version')!=1:raise ValueError('Onbekend koppelingsbestand.')
    if KEY.stat().st_mode&0o077:raise ValueError('De privésleutel heeft onjuiste bestandsrechten.')
    private=serialization.load_pem_private_key(KEY.read_bytes(),password=None)
    public=private.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
    key_id=hashlib.sha256(public).hexdigest()[:32]
    if data.get('key_id')!=key_id:raise ValueError('Dit bestand hoort bij een andere koppelingssessie.')
    peer=ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),base64.b64decode(data['public_key'],validate=True))
    shared=private.exchange(ec.ECDH(),peer)
    token=AESGCM(shared).decrypt(base64.b64decode(data['nonce'],validate=True),base64.b64decode(data['ciphertext'],validate=True),('tve-supabase-koppeling-v1:'+key_id).encode()).decode()
    if not token.startswith('sbp_') or len(token)<24:raise ValueError('Geen persoonlijk Supabase-toegangstoken ontvangen.')
    return token


def main():
    parser=argparse.ArgumentParser();parser.add_argument('file',type=Path);parser.add_argument('--check-access',action='store_true');parser.add_argument('--supabase-project');args=parser.parse_args()
    try:token=decrypt_connection(args.file)
    except Exception:raise SystemExit('Koppelingsbestand kon niet veilig worden geopend. Gebruik het huidige formulier en lever het ongewijzigde bestand aan.')
    print('Koppelingsbestand geopend; tokenwaarde wordt niet getoond of opgeslagen.')
    command=[str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/deploy_cloud.py'),'--check-access' if args.check_access else '--deploy']
    if args.supabase_project:command+=['--supabase-project',args.supabase_project]
    result=subprocess.run(command,cwd=ROOT,env={**os.environ,'SUPABASE_ACCESS_TOKEN':token})
    raise SystemExit(result.returncode)


if __name__=='__main__':main()
