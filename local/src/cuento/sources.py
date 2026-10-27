"""Real stories from Reddit for the story modality, through the public RSS
feeds (no API key: the JSON API refuses unauthenticated clients).

Each feed entry already carries the full post text, so picking a story costs
no extra request. Reddit allows about one unauthenticated request per minute,
so every feed is cached on disk and the UI pages over the cached list.
"""
from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from .config import OUTPUT_ROOT

UA = "storytelling-studio/0.2 (local desktop tool)"
FEEDS_DIR = OUTPUT_ROOT / "_fuentes"   # <subreddit>-<period>.json
FEED_TTL = 30 * 60
MIN_WORDS, MAX_WORDS = 60, 2500        # shorter is not a story; longer loses the ending
PERIODS = ("week", "month")
PRESETS = [
    {"subreddit": "shortscarystories", "label": "Terror corto (inglés)", "tone": "general", "genre": "terror"},
    {"subreddit": "HistoriasDeTerror", "label": "Terror en español", "tone": "general", "genre": "terror"},
    {"subreddit": "nosleep", "label": "Terror largo, se resume (inglés)", "tone": "general", "genre": "terror"},
    {"subreddit": "LetsNotMeet", "label": "Encuentros reales inquietantes", "tone": "general", "genre": "terror"},
    {"subreddit": "Glitch_in_the_Matrix", "label": "Cosas inexplicables", "tone": "general", "genre": "misterio"},
    {"subreddit": "tifu", "label": "Metidas de pata (humor)", "tone": "general", "genre": "humor"},
]
_NS = {"a": "http://www.w3.org/2005/Atom"}
_SUB = re.compile(r"^[A-Za-z0-9_]{2,21}$")
# only a Reddit post: the pipeline downloads this URL server-side
_POST = re.compile(r"^https://(www\.)?reddit\.com/r/[A-Za-z0-9_]{2,21}/comments/[a-z0-9]+(/[^/?#]*)?/?$")


class SourceError(RuntimeError):
    def __init__(self, message: str, retry_in: int | None = None):
        super().__init__(message)
        self.retry_in = retry_in


def valid_subreddit(name: str) -> bool:
    return bool(_SUB.match(name or ""))


def valid_url(url: str) -> bool:
    return bool(_POST.match(url or ""))


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code in (429, 403):
            wait = int(float(e.headers.get("x-ratelimit-reset") or 60))
            raise SourceError(f"Reddit limita las peticiones; vuelve a intentarlo en {wait} s",
                              retry_in=wait) from e
        if e.code == 404:
            raise SourceError("Ese subreddit no existe") from e
        raise SourceError(f"Reddit respondió {e.code}") from e
    except (urllib.error.URLError, OSError) as e:
        raise SourceError(f"No se pudo conectar con Reddit ({e})") from e


def _text(content: str) -> str:
    """Plain text of a post from its RSS <content> (HTML inside div.md)."""
    m = re.search(r'<div class="md">(.*)', content, re.S)
    body = m.group(1) if m else ""
    body = body.split("<!-- SC_ON -->")[0]
    body = re.sub(r"</p>", "\n\n", body)
    body = re.sub(r"<br\s*/?>|</li>", "\n", body)
    body = html.unescape(re.sub(r"<[^>]+>", "", body))
    body = re.sub(r"[ \t]*\n[ \t]*", "\n", body)      # no stray spaces around breaks
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def _entries(xml: bytes) -> list[dict]:
    out = []
    for e in ET.fromstring(xml).findall("a:entry", _NS):
        link = e.find("a:link", _NS)
        text = _text(e.findtext("a:content", "", _NS))
        words = len(text.split())
        cat = e.find("a:category", _NS)
        out.append({
            "url": (link.get("href") if link is not None else "").rstrip("/") + "/",
            "title": (e.findtext("a:title", "", _NS) or "").strip(),
            "author": (e.findtext("a:author/a:name", "", _NS) or "").removeprefix("/u/"),
            "subreddit": cat.get("term", "") if cat is not None else "",
            "words": words,
            "text": text,
            "excerpt": re.sub(r"\s+", " ", text)[:160],
        })
    return out


def _parse(xml: bytes) -> list[dict]:
    """Entries that are stories: with text, not too short, not too long."""
    return [s for s in _entries(xml) if MIN_WORDS <= s["words"] <= MAX_WORDS]


def list_stories(subreddit: str, period: str = "week", refresh: bool = False) -> dict:
    """Top stories of a subreddit: {subreddit, period, fetched_at, stories,
    stale, retry_in}. Served from the disk cache while fresh; when Reddit
    limits us the old cache is returned with stale=True."""
    if not valid_subreddit(subreddit):
        raise SourceError("Nombre de subreddit no válido")
    if period not in PERIODS:
        raise SourceError(f"period debe ser {' o '.join(PERIODS)}")
    cache = FEEDS_DIR / f"{subreddit}-{period}.json"
    cached = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else None
    if cached and not refresh and time.time() - cached["fetched_at"] < FEED_TTL:
        return {**cached, "stale": False, "retry_in": None}
    try:
        stories = _parse(_fetch(f"https://www.reddit.com/r/{subreddit}/top/.rss?t={period}&limit=50"))
    except SourceError as e:
        if cached:
            return {**cached, "stale": True, "retry_in": e.retry_in}
        raise
    data = {"subreddit": subreddit, "period": period, "fetched_at": time.time(), "stories": stories}
    FEEDS_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return {**data, "stale": False, "retry_in": None}


def fetch_story(url: str) -> dict:
    """One post by URL: from any cached feed, else its own RSS (1 request)."""
    if not valid_url(url):
        raise SourceError("La URL debe ser un post de reddit.com")
    url = url.rstrip("/") + "/"
    for cache in FEEDS_DIR.glob("*.json") if FEEDS_DIR.is_dir() else []:
        try:
            for s in json.loads(cache.read_text(encoding="utf-8"))["stories"]:
                if s["url"] == url:
                    return s
        except (json.JSONDecodeError, KeyError):
            continue
    entries = _entries(_fetch(url + ".rss"))  # first entry = the post, then comments
    if not entries or not entries[0]["text"]:
        raise SourceError("No se pudo leer la historia de ese post")
    return entries[0]


def used_urls() -> set[str]:
    """Posts already turned into a video (from the run manifests)."""
    used = set()
    for manifest in OUTPUT_ROOT.glob("*/pipeline.json") if OUTPUT_ROOT.is_dir() else []:
        try:
            src = json.loads(manifest.read_text(encoding="utf-8")).get("Source")
        except (json.JSONDecodeError, OSError):
            continue
        if src:
            used.add(src.rstrip("/") + "/")
    return used
