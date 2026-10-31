"""Authenticated Instaloader + FFmpeg adapter for Postwise."""
import base64
import hmac
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
from urllib.parse import urlparse
import wave

LOCK = threading.BoundedSemaphore(1)
MAX_RESPONSE = 38_000_000

def shortcode(url):
    u = urlparse(url)
    m = re.fullmatch(r'/(?:p|reel|tv)/([A-Za-z0-9_-]+)/?', u.path)
    if u.scheme != 'https' or u.hostname not in ('instagram.com', 'www.instagram.com') or not m:
        raise ValueError('Use an HTTPS Instagram post or reel URL.')
    return m.group(1)

def run(*args):
    return subprocess.check_output(args, timeout=120, stderr=subprocess.PIPE)

def download(loader, url, path, limit):
    # Media URLs come only from Instaloader. Never accept arbitrary download URLs.
    for _ in range(4):
        u = urlparse(url)
        if u.scheme != 'https' or not u.hostname or not any(u.hostname.endswith('.' + d) or u.hostname == d for d in ('cdninstagram.com', 'fbcdn.net', 'instagram.com')):
            raise ValueError('Instagram returned an unsupported media host.')
        r = loader.context.get_raw(url)
        if r.is_redirect:
            url = r.headers['Location']
            continue
        total = 0
        with r, open(path, 'wb') as out:
            for chunk in r.iter_content(65536):
                total += len(chunk)
                if total > limit:
                    raise ValueError('Media exceeds the download size limit.')
                out.write(chunk)
        return
    raise ValueError('Too many media redirects.')

def load_post(url):
    import instaloader
    code = shortcode(url)
    loader = instaloader.Instaloader(max_connection_attempts=1, request_timeout=25, quiet=True)
    username, session = os.environ.get('IG_USERNAME'), os.environ.get('IG_SESSION_FILE')
    if username and session:
        loader.load_session_from_file(username, session)
    post = instaloader.Post.from_shortcode(loader.context, code)
    nodes = list(post.get_sidecar_nodes()) if post.typename == 'GraphSidecar' else [post]
    if len(nodes) > 20:
        raise ValueError('This importer supports up to 20 carousel items.')
    images, times, audio_paths, segments = [], [], [], []
    has_video = any(n.is_video for n in nodes)
    photo_count = sum(not n.is_video for n in nodes)
    video_count = sum(n.is_video for n in nodes)
    quota = max(1, (60-photo_count)//max(1, video_count))
    offset, notices = 0.0, []
    with tempfile.TemporaryDirectory(prefix='postwise-') as folder:
        root = Path(folder)
        for index, node in enumerate(nodes):
            path = root / f'media-{index}'
            download(loader, node.video_url if node.is_video else (node.display_url if hasattr(node, 'display_url') else node.url), path, 200_000_000 if node.is_video else 20_000_000)
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
    def log_message(self, *args): pass
    def send_json(self, status, value):
        raw = json.dumps(value).encode(); self.send_response(status)
        self.send_header('Content-Type','application/json'); self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        self.send_json(200 if self.path == '/health' else 404, {'status':'ok'} if self.path == '/health' else {'error':'Not found'})
    def do_POST(self):
        if self.path != '/import': return self.send_json(404,{'error':'Not found'})
        token = os.environ.get('POSTWISE_IMPORT_TOKEN','')
        if not token or not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+token):
            return self.send_json(401,{'error':'Unauthorized'})
        size = int(self.headers.get('Content-Length','0'))
        if size <= 0 or size > 4096: return self.send_json(413,{'error':'Request too large'})
        if not LOCK.acquire(blocking=False): return self.send_json(429,{'error':'Importer busy. Retry after the current import completes.'})
        try:
            payload = json.loads(self.rfile.read(size)); shortcode(payload.get('url',''))
            self.send_json(200,load_post(payload['url']))
        except ValueError as e: self.send_json(400,{'error':str(e)})
        except Exception:
            self.send_json(502,{'error':'Instagram retrieval failed. A valid session may be required, or Instagram may be limiting access. No automatic retries were made.'})
        finally: LOCK.release()

if __name__ == '__main__':
    if not os.environ.get('POSTWISE_IMPORT_TOKEN'): raise SystemExit('Set POSTWISE_IMPORT_TOKEN before starting.')
    ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PORT','8080'))),Handler).serve_forever()
