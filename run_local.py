"""Launch a loopback-only Postwise compute service without Render."""
import os
from pathlib import Path
import secrets

os.environ.setdefault('HOST','127.0.0.1')
os.environ.setdefault('PORT','8765')
os.environ.setdefault('POSTWISE_ALLOWED_ORIGIN','https://postwise-knowledge-portal.shtoa.chatgpt.site')
# A session-only token: never stored in source, browser storage or a settings file.
os.environ.setdefault('POSTWISE_IMPORT_TOKEN',secrets.token_urlsafe(32))
print('\nPostwise local compute: http://127.0.0.1:'+os.environ['PORT'],flush=True)
print('Paste this session token into Postwise → This computer:',flush=True)
print(os.environ['POSTWISE_IMPORT_TOKEN'],flush=True)
print('Keep this terminal open. Closing it stops the service.\n',flush=True)
from server import Handler, ThreadingHTTPServer
ThreadingHTTPServer((os.environ['HOST'],int(os.environ['PORT'])),Handler).serve_forever()
