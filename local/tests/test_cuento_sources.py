"""Reddit RSS sources: parsing, length filter, disk cache, rate-limit
fallback and the URL guards (the pipeline downloads what the browser sends)."""
import html

import pytest

from cuento import sources

URL = "https://www.reddit.com/r/shortscarystories/comments/abc/my_wife_and_i_switched_places/"


def _entry(title, author, body_html, post_id="abc", link=URL):
    content = html.escape(f'<!-- SC_OFF --><div class="md">{body_html}</div><!-- SC_ON -->')
    return (f"<entry><author><name>/u/{author}</name></author>"
            f'<category term="shortscarystories" label="r/shortscarystories"/>'
            f'<content type="html">{content}</content><id>t3_{post_id}</id>'
            f'<link href="{link}" /><title>{html.escape(title)}</title></entry>')


def feed_xml() -> bytes:
    short = "<p>Being married can be <em>difficult</em>.</p> <p>" + " ".join(["word"] * 110) + "</p>"
    long = "<p>" + " ".join(["long"] * 3000) + "</p>"
    entries = (_entry("My wife and I switched places", "ForgottenWell", short)
               + _entry("A very long one", "Writer", long, "lng", URL.replace("abc", "lng"))
               + '<entry><author><name>/u/Pic</name></author><content type="html">'
               + html.escape('<a href="https://i.redd.it/x.png">[link]</a>')
               + '</content><id>t3_img</id><link href="https://www.reddit.com/r/shortscarystories/comments/img/pic/" />'
               + "<title>Pic</title></entry>")
    return (f'<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">'
            f"{entries}</feed>").encode("utf-8")


def test_parse_extracts_text_and_filters_length():
    assert len(sources._entries(feed_xml())) == 3
    stories = sources._parse(feed_xml())
    assert [s["title"] for s in stories] == ["My wife and I switched places"]
    s = stories[0]
    assert s["author"] == "ForgottenWell" and s["subreddit"] == "shortscarystories" and s["url"] == URL
    assert s["text"].startswith("Being married can be difficult.") and s["words"] == 115
    assert "\n\n" in s["text"] and len(s["excerpt"]) <= 160 and "\n" not in s["excerpt"]


def test_list_stories_uses_cache_and_survives_rate_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "FEEDS_DIR", tmp_path / "f")
    calls = []
    monkeypatch.setattr(sources, "_fetch", lambda url: calls.append(url) or feed_xml())
    first = sources.list_stories("shortscarystories")
    second = sources.list_stories("shortscarystories")
    assert len(calls) == 1 and first["stories"] == second["stories"] and not second["stale"]
    assert "t=week" in calls[0] and (tmp_path / "f" / "shortscarystories-week.json").is_file()
    sources.list_stories("shortscarystories", refresh=True)
    assert len(calls) == 2
    # Reddit says wait: the old list is served, flagged
    monkeypatch.setattr(sources, "_fetch", lambda url: (_ for _ in ()).throw(sources.SourceError("limit", retry_in=40)))
    stale = sources.list_stories("shortscarystories", refresh=True)
    assert stale["stale"] and stale["retry_in"] == 40 and len(stale["stories"]) == 1
    with pytest.raises(sources.SourceError):
        sources.list_stories("nosleep")  # nothing cached for this one
    with pytest.raises(sources.SourceError):
        sources.list_stories("shortscarystories", period="year")


def test_fetch_story_from_cache_and_url_guards(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "FEEDS_DIR", tmp_path / "f")
    monkeypatch.setattr(sources, "_fetch", lambda url: feed_xml())
    sources.list_stories("shortscarystories")
    monkeypatch.setattr(sources, "_fetch", lambda url: (_ for _ in ()).throw(AssertionError("network")))
    story = sources.fetch_story(URL.rstrip("/"))
    assert story["author"] == "ForgottenWell" and story["text"]
    for bad in ("https://evil.com/r/x/comments/abc/t/", "https://www.reddit.com/user/x",
                "http://www.reddit.com/r/x/comments/abc/t/", ""):
        assert not sources.valid_url(bad), bad
        with pytest.raises(sources.SourceError):
            sources.fetch_story(bad)
    assert sources.valid_url("https://reddit.com/r/nosleep/comments/1xdfawi/")
    assert not sources.valid_subreddit("../x") and not sources.valid_subreddit("") and sources.valid_subreddit("tifu")
