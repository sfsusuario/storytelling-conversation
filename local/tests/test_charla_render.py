"""Captions of the Conversación renderer."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from charla.models import Turn  # noqa: E402
from charla.renderer import _estimate_word_timings, _subtitle_filters  # noqa: E402


def _turn(**kw) -> Turn:
    base = dict(index=1, turn_id="turn_01", speaker="rick", emotion="neutral",
                line="Morty, los pulpos tienen tres corazones y sangre azul, ¿lo sabías?",
                audio_duration=4.0)
    base.update(kw)
    return Turn(**base)


def test_estimated_timings_cover_the_whole_line():
    words = _estimate_word_timings("hola mundo cruel", 3.0)
    assert [w["w"] for w in words] == ["hola", "mundo", "cruel"]
    assert words[0]["t"] == 0 and abs(words[-1]["t"] + words[-1]["d"] - 3.0) < 1e-6
    assert _estimate_word_timings("", 3.0) == [] and _estimate_word_timings("x", 0) == []


def test_cloned_voice_gets_chunked_captions(tmp_path):
    # XTTS/Chatterbox leave word_timings None: still several short captions in sequence
    f = _subtitle_filters(_turn(), tmp_path, 4.5, 0.2, "fontsize=40", schwifty=False)
    assert f.count("drawtext=") >= 3
    files = sorted(tmp_path.glob("turn_01.sub*.txt"))
    assert len(files) >= 3 and all(len(p.read_text(encoding="utf-8")) < 40 for p in files)
    assert "turn_01.sub.txt" not in {p.name for p in files}


def test_no_audio_duration_falls_back_to_full_line(tmp_path):
    f = _subtitle_filters(_turn(audio_duration=None), tmp_path, 4.5, 0.2, "fontsize=40", schwifty=False)
    assert f.count("drawtext=") == 1 and (tmp_path / "turn_01.sub.txt").exists()
