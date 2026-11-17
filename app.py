import os
import re
import logging
from typing import Any
from urllib.parse import quote

from flask import Flask, jsonify, request, send_from_directory, Response, abort
import requests
import yt_dlp

app = Flask(__name__, static_folder="static")
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("music-player")

# InnerTube is used first for catalogue/search metadata. It is an unofficial,
# changing API, so a yt-dlp search fallback keeps search usable during outages.
try:
    from innertube import InnerTube
    music_client = InnerTube("WEB_REMIX")
except Exception as exc:
    log.warning("Could not initialise WEB_REMIX client: %s", exc)
    music_client = None


def walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk(value)


def text_of(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "simpleText" in value:
            return value["simpleText"]
        if "runs" in value:
            return "".join(str(x.get("text", "")) for x in value["runs"])
    return ""


def thumbnails(renderer):
    thumbs = renderer.get("thumbnail", {}).get("thumbnails", [])
    if not thumbs:
        thumbs = renderer.get("thumbnailRenderer", {}).get("musicThumbnailRenderer", {}).get("thumbnail", {}).get("thumbnails", [])
    return sorted(thumbs, key=lambda x: x.get("width", 0))[-1].get("url", "") if thumbs else ""


def parse_innertube(data):
    results, seen = [], set()
    for item in walk(data):
        renderer = None
        kind = None
        for key in ("musicResponsiveListItemRenderer", "musicTwoRowItemRenderer", "songTwoRowItemRenderer", "videoRenderer"):
            if key in item:
                renderer, kind = item[key], key
                break
        if not renderer:
            continue

        video_id = renderer.get("videoId")
        if not video_id:
            for nav in walk(renderer):
                endpoint = nav.get("watchEndpoint") or nav.get("watchPlaylistEndpoint")
                if endpoint and endpoint.get("videoId"):
                    video_id = endpoint["videoId"]
                    break
        if not video_id or video_id in seen:
            continue

        title = text_of(renderer.get("title"))
        if not title:
            title = text_of(renderer.get("headline"))
        if not title:
            for node in walk(renderer):
                if "title" in node and text_of(node["title"]):
                    title = text_of(node["title"])
                    break
        if not title:
            continue

        subtitle = text_of(renderer.get("shortBylineText") or renderer.get("longBylineText"))
        if not subtitle:
            runs = []
            for node in walk(renderer):
                if "text" in node and isinstance(node["text"], str):
                    runs.append(node["text"])
            subtitle = " • ".join(runs[:3])
        duration = ""
        for node in walk(renderer):
            if "lengthText" in node:
                duration = text_of(node["lengthText"])
                break
        seen.add(video_id)
        results.append({
            "id": video_id,
            "title": title,
            "artist": subtitle or "YouTube Music",
            "duration": duration,
            "thumbnail": thumbnails(renderer) or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            "source": "InnerTube"
        })
    return results


def fallback_search(query):
    opts = {"quiet": True, "skip_download": True, "extract_flat": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info("ytsearch15:" + query, download=False)
    out = []
    for item in (info or {}).get("entries", []) or []:
        if not item:
            continue
        vid = item.get("id")
        if not vid:
            continue
        out.append({
            "id": vid,
            "title": item.get("title") or "Unknown title",
            "artist": item.get("uploader") or item.get("channel") or "YouTube",
            "duration": item.get("duration_string") or "",
            "thumbnail": item.get("thumbnail") or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            "source": "YouTube fallback"
        })
    return out


@app.get("/")
def home():
    return send_from_directory("static", "index.html")


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "InnerTube Music Player"})


@app.get("/api/search")
def search():
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"results": [], "source": "none"})
    if len(query) > 160:
        return jsonify({"error": "Search query too long"}), 400

    if music_client:
        try:
            data = music_client.search(query=query)
            results = parse_innertube(data)
            if results:
                return jsonify({"results": results[:20], "source": "InnerTube"})
        except Exception as exc:
            log.warning("InnerTube search failed: %s", exc)

    try:
        results = fallback_search(query)
        return jsonify({"results": results, "source": "YouTube fallback"})
    except Exception as exc:
        log.exception("Search failed")
        return jsonify({"error": "Search is temporarily unavailable", "detail": str(exc)[:240], "results": []}), 502


@app.get("/api/stream/<video_id>")
def stream(video_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id):
        abort(400)
    url = "https://www.youtube.com/watch?v=" + quote(video_id)
    opts = {
        "quiet": True, "no_warnings": True, "format": "bestaudio[acodec!=none]/bestaudio",
        "noplaylist": True, "socket_timeout": 20,
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        audio_url = info.get("url")
        if not audio_url:
            abort(502)
        headers = {}
        if request.headers.get("Range"):
            headers["Range"] = request.headers["Range"]
        upstream = requests.get(audio_url, headers=headers, stream=True, timeout=25)
        excluded = {"content-encoding", "transfer-encoding", "connection"}
        response_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in excluded}
        response_headers["Accept-Ranges"] = "bytes"
        return Response(
            upstream.iter_content(chunk_size=64 * 1024),
            status=upstream.status_code,
            headers=response_headers,
            content_type=upstream.headers.get("Content-Type", "audio/webm"),
            direct_passthrough=True
        )
    except Exception as exc:
        log.exception("Audio extraction failed for %s", video_id)
        return jsonify({"error": "Could not load this track. Try another result.", "detail": str(exc)[:220]}), 502


@app.get("/<path:path>")
def static_files(path):
    return send_from_directory("static", path)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
