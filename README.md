# Wave — InnerTube Music Player

A small responsive music web player. InnerTube is used first for YouTube Music catalogue search; yt-dlp is used to resolve playable audio and as a search fallback.

## Deploy on Render

1. Create a GitHub repository and upload the contents of this folder.
2. In Render, choose **New → Web Service** and connect the repository.
3. Render detects `render.yaml`. If configuring manually:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app --workers 1 --threads 8 --timeout 120`
4. Deploy. Open the generated `onrender.com` URL.

No API key or `users.json` is required.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS/Termux: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://localhost:10000

## Notes

- InnerTube is an unofficial/private API and can change or rate-limit requests.
- YouTube playback extraction can fail for some tracks, regions, age restrictions, or anti-bot checks. Update yt-dlp when needed.
- Use only content you have permission to stream; respect YouTube's Terms and applicable copyright law.
- This is a basic player: search, play/pause, next/previous, seek and volume. No account or database is required.
