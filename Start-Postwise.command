#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
umask 077
if ! command -v python3 >/dev/null || ! python3 -c 'import sys; assert sys.version_info >= (3,10)' 2>/dev/null; then
  echo 'Install Python 3.10 or newer from https://www.python.org/downloads/macos/'
  read -r -p 'Press Enter to close.'; exit 1
fi
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  echo 'FFmpeg is required. If you use Homebrew, run: brew install ffmpeg'
  read -r -p 'Press Enter to close.'; exit 1
fi
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
if ! .venv/bin/python -c 'import instaloader, requests; assert instaloader.__version__ == "4.16" and requests.__version__ == "2.34.2"' 2>/dev/null; then
  echo 'Installing the pinned Instagram downloader dependencies into this project only.'
  .venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
fi
if [ "${1:-}" = '--login' ]; then
  .venv/bin/python login_local.py
else
  open 'https://postwise-knowledge-portal.shtoa.chatgpt.site' || true
  exec .venv/bin/python run_local.py
fi
