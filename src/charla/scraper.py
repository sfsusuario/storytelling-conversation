from __future__ import annotations

import json
from pathlib import Path

_MAX_ARTICLE_CHARS = 6000

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}


class ScrapeError(RuntimeError):
    pass


def fetch_article(url: str, cache_dir: Path, log=print) -> str:
    """Download a news article and return its clean text (cached on disk)."""
    cache_file = cache_dir / "article.json"
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if cached.get("url") == url and cached.get("text"):
                log("  article: article.json (cached)")
                return cached["text"]
        except json.JSONDecodeError:
            pass

    import requests
    import trafilatura

    try:
        response = requests.get(url, headers=_HEADERS, timeout=20)
        response.raise_for_status()
    except requests.RequestException as e:
        raise ScrapeError(f"Could not download {url}: {e}") from e

    text = trafilatura.extract(response.text, include_comments=False,
                               favor_precision=True, url=url)
    if not text or not text.strip():
        raise ScrapeError(
            f"No readable article found at {url} (paywall or script-only "
            "page?). Paste the article text directly instead of the URL.")
    text = text.strip()
    if len(text) > _MAX_ARTICLE_CHARS:
        text = text[:_MAX_ARTICLE_CHARS].rsplit(" ", 1)[0] + " …"

    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = cache_file.with_suffix(".tmp")
    tmp.write_text(json.dumps({"url": url, "text": text}, ensure_ascii=False,
                              indent=2), encoding="utf-8")
    tmp.replace(cache_file)
    log(f"  article: {len(text)} chars extracted")
    return text
