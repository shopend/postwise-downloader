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


## Local computing without Render

The website can call a Python service on your own computer. It binds only to
127.0.0.1:8765 and accepts browser requests only from the configured Postwise
origin. A fresh session token is generated each launch; it is not saved.

### macOS / Linux

1. Install Python 3.10+ and FFmpeg using your system package manager.
2. Clone this private repository and open a terminal in it.
3. Run:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python run_local.py
```

### Windows

Install Python and FFmpeg, ensuring both are on PATH. In PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run_local.py
```

In Postwise, expand **Computing environment**, select **This computer**, paste
the session token from the terminal and click **Connect this computer**. Permit
local-network access if your browser asks. Keep the service running. The site
must be open in a browser on the same computer as the service, not a remote
cloud browser. If browser local-network/mixed-content policies block requests,
local mode is unavailable in that browser; no tunneling or public exposure is
configured automatically.

Local mode removes the Render requirement for retrieval and graph processing.
Instagram still requires internet access and may require an authorized session.
Queuing material for ChatGPT still uploads that material to the private portal
and uses cloud AI. Downloaded frames/audio remain local until you explicitly
queue them or choose a remote AI action.

### Optional Graphify

The official PyPI package named by Graphify Labs is `graphifyy`. This code uses
its Python graph-building API and does not call another LLM or install assistant
skills/hooks. After reviewing/approving that dependency, install:

```sh
python -m pip install -r requirements-graphify.txt
```

Then restart the local service and build the knowledge map in Postwise. Graphs
use up to 100 existing saved notes, preserve note-field provenance, and mark
heuristic shared-topic connections INFERRED. EXTRACTED refers to the saved note's
structure, not independent verification of the original Instagram post. Synonyms
are not automatically merged. Search, connection paths and JSON export are
available. Graph state is held in the browser until exported or rebuilt.

Docker keeps Graphify optional by default; use build argument INSTALL_GRAPHIFY=1
to include it after dependency approval. Heavy video/transcription extras are not
installed. Graphify installation/execution has not yet been validated in this
authoring session because automatic approval review blocked the package install.

### Optional local LLM (Ollama)

Install Ollama from its official distribution and install a model suitable for
your machine. Start Ollama on its default loopback address, then use **Find local
models** in Postwise. Choose an installed model and click **Analyze locally**.
Requests go through the local Python service to 127.0.0.1:11434; no remote model
endpoint is used by this adapter. Use a vision-capable model for screenshots.
This initial local adapter accepts at most 20 images and requires a pasted or
previously generated transcript for speech. It does not transcribe audio itself.
Generated notes are validated against the common teaching-note format. No
automatic fallback to a remote provider is performed.
