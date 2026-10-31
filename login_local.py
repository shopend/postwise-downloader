"""Interactive Instagram login; only JSON cookies are persisted locally."""
import getpass
import json
import os
from pathlib import Path
import instaloader

os.umask(0o077)
folder = Path.home()/'.postwise'
folder.mkdir(mode=0o700,exist_ok=True)
if folder.is_symlink():
    raise SystemExit('Session directory must not be a symlink.')
folder.chmod(0o700)
username = input('Instagram username: ').strip()
loader = instaloader.Instaloader(quiet=True,max_connection_attempts=1,request_timeout=25)
try:
    loader.login(username,getpass.getpass('Instagram password (not saved): '))
except instaloader.TwoFactorAuthRequiredException:
    loader.two_factor_login(input('Two-factor code: ').strip())
# No pickle loading or password storage. Atomic replacement of a private file.
target = folder/'instagram-session.json'
temporary = folder/('session-'+os.urandom(8).hex()+'.json')
with temporary.open('x') as out:
    json.dump({'username':username,'cookies':loader.context.save_session()},out)
temporary.chmod(0o600)
os.replace(temporary,target)
print('Session saved on this computer. Restart Postwise local compute to use it.')
