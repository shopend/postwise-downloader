"""Authenticated Instaloader + FFmpeg adapter for Postwise."""
import base64
import hmac
import ipaddress
import socket
import sys
import time
import stat
import signal
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, urljoin
import wave

LOCK = threading.BoundedSemaphore(1)
MAX_RESPONSE = 38_000_000

def shortcode(url):
    u = urlparse(url)
    m = re.fullmatch(r'/(?:p|reel|tv)/([A-Za-z0-9_-]+)/?', u.path)
    if u.username or u.password or u.port not in (None,443) or u.scheme != 'https' or u.hostname not in ('instagram.com', 'www.instagram.com') or not m:
        raise ValueError('Use an HTTPS Instagram post or reel URL.')
    return m.group(1)

def run(*args):
    # No shell, no stdin, no network protocols inside media decoders.
    binary, *options = args
    formats = [] if 'lavfi' in options else ['-format_whitelist','mov,matroska,webm,jpeg_pipe,png_pipe,webp_pipe,wav']
    return subprocess.check_output([binary, '-nostdin', '-protocol_whitelist', 'file,pipe', '-threads', '1', *formats, *options] if binary == 'ffmpeg' else [binary, '-protocol_whitelist', 'file,pipe', *formats, *options], timeout=45, stderr=subprocess.PIPE)


def media_host(url):
    u = urlparse(url)
    if (u.scheme != 'https' or u.username or u.password or u.port not in (None,443)
        or not u.hostname or not any(u.hostname == d or u.hostname.endswith('.'+d)
        for d in ('cdninstagram.com','fbcdn.net','instagram.com'))):
        raise ValueError('Instagram returned an unsupported media host.')
    addresses = socket.getaddrinfo(u.hostname,443,type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(x[4][0]).is_global for x in addresses):
        raise ValueError('Media host must resolve to public addresses.')


def download(loader, url, path, limit):
    import requests
    # Separate anonymous session: Instagram login cookies never go to media hosts.
    with requests.Session() as client:
        client.trust_env = False
        client.headers['User-Agent'] = 'Postwise/1.0'
        deadline = time.monotonic()+60
        for _ in range(4):
            media_host(url)
            with client.get(url, stream=True, allow_redirects=False, timeout=(10,15)) as response:
                if response.is_redirect:
                    url = urljoin(url,response.headers.get('Location',''))
                    continue
                response.raise_for_status()
                if int(response.headers.get('Content-Length','0')) > limit:
                    raise ValueError('Media exceeds the download size limit.')
                total = 0
                with open(path,'wb') as out:
                    for chunk in response.iter_content(65536):
                        total += len(chunk)
                        if total > limit or time.monotonic() > deadline:
                            raise ValueError('Media exceeds the download size or time limit.')
                        out.write(chunk)
                return total
        raise ValueError('Too many media redirects.')


def load_session(loader, username, filename):
    # Instaloader's pickle sessions are intentionally not loaded by this service.
    path = Path(filename)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError('Session must be a private regular JSON file (chmod 600).')
    if hasattr(os,'getuid') and info.st_uid != os.getuid():
        raise ValueError('Session must belong to the current user.')
    if info.st_size > 65536:
        raise ValueError('Session file too large.')
    data = json.loads(path.read_text())
    if data.get('username') != username or not isinstance(data.get('cookies'),dict):
        raise ValueError('Invalid local JSON session.')
    if any(not isinstance(k,str) or not isinstance(v,str) for k,v in data['cookies'].items()):
        raise ValueError('Invalid session cookies.')
    loader.context.load_session(username,data['cookies'])


def isolated_import(url):
    # Process timeout includes metadata, all downloads, probing and extraction.
    with tempfile.TemporaryDirectory(prefix='postwise-job-') as work:
        result = Path(work)/'result.json'
        process = subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--import-worker',str(result)],
            stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            start_new_session=True,env={**os.environ,'TMPDIR':work})
        try:
            process.communicate(json.dumps({'url':url}).encode(),timeout=210)
            if process.returncode:
                raise ValueError('Instagram retrieval failed. Check your local session and access, then try again.')
        except subprocess.TimeoutExpired:
            raise ValueError('Import exceeded 210 seconds. No partial result was saved.') from None
        finally:
            try: os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError: pass
            process.wait()
        if result.stat().st_size > MAX_RESPONSE:
            raise ValueError('Importer response too large.')
        return json.loads(result.read_text())

def load_post(url):
    import instaloader
    code = shortcode(url)
    loader = instaloader.Instaloader(max_connection_attempts=1, request_timeout=25, quiet=True)
    username, session = os.environ.get('IG_USERNAME'), os.environ.get('IG_SESSION_FILE')
    if username and session:
        load_session(loader, username, session)
    post = instaloader.Post.from_shortcode(loader.context, code)
    nodes = list(post.get_sidecar_nodes()) if post.typename == 'GraphSidecar' else [post]
    if len(nodes) > 20:
        raise ValueError('This importer supports up to 20 carousel items.')
    images, times, audio_paths, segments = [], [], [], []
    has_video = any(n.is_video for n in nodes)
    photo_count = sum(not n.is_video for n in nodes)
    video_count = sum(n.is_video for n in nodes)
    quota = max(1, (60-photo_count)//max(1, video_count))
    offset, notices, downloaded = 0.0, [], 0
    with tempfile.TemporaryDirectory(prefix='postwise-') as folder:
        root = Path(folder)
        for index, node in enumerate(nodes):
            path = root / f'media-{index}'
            downloaded += download(loader, node.video_url if node.is_video else (node.display_url if hasattr(node, 'display_url') else node.url), path, min(300_000_000-downloaded,200_000_000 if node.is_video else 20_000_000))
            if not node.is_video:
                jpg = run('ffmpeg', '-v', 'error', '-i', str(path), '-vf', 'scale=1280:1280:force_original_aspect_ratio=decrease', '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'mjpeg', '-')
                images.append('data:image/jpeg;base64,'+base64.b64encode(jpg).decode())
                times.append(offset)
                segments.append({'postItem':index+1,'type':'photo','frameStart':len(images)-1,'frameCount':1})
                continue
            probe = json.loads(run('ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)))
            duration = float(probe['format']['duration'])
            if not math.isfinite(duration) or duration <= 0 or offset + duration > 600:
                raise ValueError('Combined video duration must be at most 10 minutes.')
            count = min(quota, max(1, math.ceil(duration/5)))
            start_frame = len(images)
            for i in range(count):
                t = i*duration/count
                jpg = run('ffmpeg','-v','error','-ss',str(t),'-i',str(path),'-vf','scale=1280:1280:force_original_aspect_ratio=decrease','-frames:v','1','-f','image2pipe','-vcodec','mjpeg','-')
                images.append('data:image/jpeg;base64,'+base64.b64encode(jpg).decode()); times.append(round(offset+t,3))
            audio_path = root / f'audio-{index}.wav'
            if any(x.get('codec_type') == 'audio' for x in probe['streams']):
                run('ffmpeg','-v','error','-i',str(path),'-vn','-ac','1','-ar','16000','-t',str(duration),'-y',str(audio_path))
            else:
                notices.append(f'Video item {index+1} has no audio track.')
                run('ffmpeg','-v','error','-f','lavfi','-i','anullsrc=r=16000:cl=mono','-t',str(duration),'-y',str(audio_path))
            audio_paths.append(audio_path)
            segments.append({'postItem':index+1,'type':'video','start':offset,'duration':duration,'frameStart':start_frame,'frameCount':count})
            offset += duration
        chunks = []
        if audio_paths:
            pcm = b''
            for path in audio_paths:
                with wave.open(str(path),'rb') as f: pcm += f.readframes(f.getnframes())
            for start in range(0,len(pcm),30*16000*2):
                piece = pcm[start:start+30*16000*2]; out = io.BytesIO()
                with wave.open(out,'wb') as f:
                    f.setnchannels(1); f.setsampwidth(2); f.setframerate(16000); f.writeframes(piece)
                chunks.append({'start':start/32000,'end':(start+len(piece))/32000,'data':base64.b64encode(out.getvalue()).decode()})
        result = {'caption':post.caption or '', 'images':images, 'audioChunks':chunks, 'video':{'name':code,'duration':offset,'timestamps':times,'segments':segments,'audioStatus':'ready' if chunks else 'unavailable'} if has_video else None,'metadata':{'shortcode':code,'author':post.owner_username,'publishedAt':post.date_utc.isoformat(),'itemCount':len(nodes)},'notice':'Imported with Instaloader. '+('Videos sampled into timestamped frames; audio is ready for ChatGPT transcription. ' if has_video else 'Carousel images preserved in order. ')+' '.join(notices)}
        if len(json.dumps(result).encode()) > MAX_RESPONSE:
            raise ValueError('Extracted content exceeds 38 MB. Import a shorter video.')
        return result

class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(20)
    def valid_host(self):
        if os.environ.get('HOST') == '127.0.0.1':
            return self.headers.get('Host') in ('127.0.0.1:'+str(self.server.server_port),'localhost:'+str(self.server.server_port))
        return True
    def log_message(self, *args): pass
    def allowed_origin(self):
        if not self.valid_host(): return False
        origin = self.headers.get('Origin')
        allowed = os.environ.get('POSTWISE_ALLOWED_ORIGIN','https://postwise-knowledge-portal.shtoa.chatgpt.site')
        return origin is None or origin == allowed
    def cors(self):
        if self.headers.get('Origin') and self.allowed_origin():
            self.send_header('Access-Control-Allow-Origin',self.headers['Origin'])
            self.send_header('Vary','Origin')
            self.send_header('Access-Control-Allow-Private-Network','true')
    def send_json(self, status, value):
        raw = json.dumps(value).encode(); self.send_response(status)
        self.send_header('Content-Type','application/json'); self.send_header('Cache-Control','no-store')
        self.cors()
        self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_OPTIONS(self):
        if not self.allowed_origin(): return self.send_json(403,{'error':'Origin not allowed'})
        self.send_response(204); self.cors()
        self.send_header('Access-Control-Allow-Methods','POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers','Authorization, Content-Type')
        self.end_headers()
    def authorized(self):
        token = os.environ.get('POSTWISE_IMPORT_TOKEN','')
        return bool(token) and hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+token)
    def do_GET(self):
        if not self.allowed_origin(): return self.send_json(403,{'error':'Origin not allowed'})
        if self.path == '/health': return self.send_json(200,{'status':'ok','service':'postwise-compute'})
        self.send_json(404,{'error':'Not found'})
    def do_POST(self):
        paths = ('/import','/connect','/models','/analyze','/graph/build','/graph/query')
        if self.path not in paths: return self.send_json(404,{'error':'Not found'})
        if not self.allowed_origin(): return self.send_json(403,{'error':'Origin not allowed'})
        if not self.authorized(): return self.send_json(401,{'error':'Unauthorized'})
        try: size = int(self.headers.get('Content-Length','0'))
        except ValueError: return self.send_json(400,{'error':'Invalid content length'})
        limit = 4096 if self.path in ('/import','/connect','/models') else 20_000_000
        if size <= 0 or size > limit: return self.send_json(413,{'error':'Request too large'})
        if not LOCK.acquire(blocking=False): return self.send_json(429,{'error':'Compute service busy. Wait for the current operation.'})
        try:
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload,dict): raise ValueError('Expected a JSON object')
            if self.path == '/connect':
                import importlib.util
                result={'connected':True,'graphifyInstalled':bool(importlib.util.find_spec('graphify')),'localAI':'Ollama optional','mode':'local' if os.environ.get('HOST')=='127.0.0.1' else 'hosted'}
            elif self.path == '/models':
                from local_ai import models
                result=models()
            elif self.path == '/analyze':
                from local_ai import analyze
                result=analyze(payload)
            elif self.path == '/graph/build':
                from knowledge_graph import build_graph
                result=build_graph(payload.get('notes'))
            elif self.path == '/graph/query':
                from knowledge_graph import query_graph
                result=query_graph(payload.get('graph',{}),payload.get('query',''),payload.get('start'),payload.get('end'))
            else:
                shortcode(payload.get('url',''));result=isolated_import(payload['url'])
            self.send_json(200,result)
        except ModuleNotFoundError as e:
            self.send_json(503,{'error':'Optional dependency unavailable: '+str(e.name)+'. Install the documented dependency group on this compute host.'})
        except ValueError as e: self.send_json(400,{'error':str(e)})
        except Exception:
            self.send_json(502,{'error':'Processing failed. For Instagram, a valid session may be required or access may be limited. For local AI, check Ollama is running and the model supports the source inputs.'})
        finally: LOCK.release()

if __name__ == '__main__' and len(sys.argv) == 3 and sys.argv[1] == '--import-worker':
    # Limits are defense in depth; run as an unprivileged OS user as well.
    import resource
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CPU,(180,180))
    resource.setrlimit(resource.RLIMIT_FSIZE,(300_000_000,300_000_000))
    source = json.loads(sys.stdin.buffer.read(4097))
    Path(sys.argv[2]).write_text(json.dumps(load_post(source['url'])))
    raise SystemExit(0)

if __name__ == '__main__':
    if not os.environ.get('POSTWISE_IMPORT_TOKEN'): raise SystemExit('Set POSTWISE_IMPORT_TOKEN before starting.')
    ThreadingHTTPServer((os.environ.get('HOST','0.0.0.0'),int(os.environ.get('PORT','8080'))),Handler).serve_forever()
