# Postwise Instaloader service

This Python service retrieves a single Instagram post/reel URL using Instaloader,
collects its caption and up to 20 carousel items, and extracts up to 60 timestamped
video frames and 30-second WAV audio chunks with FFmpeg. Videos have a combined
10-minute / 200 MB per-file limit. The response is bounded to 38 MB.

## Deployment

Deploy this directory's Dockerfile to a Python/container host with HTTPS and a
request timeout of at least 180 seconds. The existing Sites Worker cannot run this
Python process. Do not deploy this directory as the Sites Worker build.

Set a strong random POSTWISE_IMPORT_TOKEN secret on the container host. No token
is included in this repository. Optional: IG_USERNAME and IG_SESSION_FILE may point
to a server-mounted Instaloader session file created by the account owner. Do not
commit sessions or passwords. The service does not accept login credentials.

Configure these production secrets on the existing Postwise Site:

- INSTALOADER_SERVICE_URL: HTTPS origin of the deployed container, without /import
- INSTALOADER_SERVICE_TOKEN: same value as POSTWISE_IMPORT_TOKEN

Republish Postwise after setting secrets. The Import post button then calls this
service and fills the caption, ordered images, extracted video frames and audio.
The service does not use OpenAI; queue its output for ChatGPT or use the optional
API transcription/analysis path.

Requests are authenticated and imports serialized. Respect Instagram rate limits;
blocked/login-required responses stop without retries. A session does not guarantee
access. Instagram media stays in temporary files only for the request. Images/audio
are returned to the signed-in portal visitor and stored only if they queue them.

GET /health reports liveness. POST /import accepts {"url":"https://www.instagram.com/p/SHORTCODE/"}
and Authorization: Bearer <token>. Configure the host for one replica or an upstream
rate limit. No unattended import schedule is configured.

## Render Free setup

1. In Render choose **New → Web Service**.
2. Select **shopend/postwise-downloader**. If it is missing, grant Render access to this specific private repository.
3. Set **Language: Docker**, **Branch: main**, **Root Directory: leave blank**, **Dockerfile Path: ./Dockerfile**, **Instance Type: Free**.
4. Add the secret environment variable **POSTWISE_IMPORT_TOKEN** with a strong random value. Set **Health Check Path: /health**.
5. Deploy. After the service is live, configure its HTTPS address and the matching token on Postwise. Do not put secrets in this repository or chat.

Alternatively, use the included `render.yaml` Blueprint; it selects the Free plan and generates the importer token.

Render Free sleeps after inactivity and has limited CPU, RAM, bandwidth and build minutes. Start with short clips. Instagram access is not guaranteed: cloud IPs may be rate limited or login may be required. Local extraction tests used sample media; a live Instagram import has not yet been verified.
