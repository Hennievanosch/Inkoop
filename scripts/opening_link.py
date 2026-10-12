"""Print the private, one-time opening link only on the operator's own terminal."""
import sys
import os
import json
from pathlib import Path
root=Path(__file__).resolve().parent.parent
token=Path(os.environ.get('TVE_DB_PATH',root/'data/tve.sqlite')).with_suffix('.token')
base=sys.argv[1].rstrip('/') if len(sys.argv)>1 else 'http://127.0.0.1:8000'
cloud=root/'.deployment/private.json'
if len(sys.argv)>1 and base.startswith('https://') and cloud.exists():
    print(base+'/#setup='+json.loads(cloud.read_text())['setup_code'])
elif token.exists():
    print(base+'/#setup='+token.read_text().strip())
else:
    print(base+' (account ingesteld; log in met uw eigen e-mailadres en wachtwoord)')
