from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import (CHARACTERS, DEFAULT_BACKGROUND, DEFAULT_BG_VOLUME,
                     DEFAULT_CHAR_SCALE, DEFAULT_TTS_ENGINE,
                     DEFAULT_CHROMA_BLEND, DEFAULT_CHROMA_SIMILARITY,
                     DEFAULT_FPS, DEFAULT_HEIGHT, DEFAULT_LANGUAGE,
                     DEFAULT_MAX_TURNS, DEFAULT_MIN_TURNS,
                     DEFAULT_TEXT_MODEL, DEFAULT_WATERMARK, DEFAULT_WIDTH,
                     CHARACTERS_DIR, PipelineOptions)

EXIT_USAGE, EXIT_API, EXIT_FFMPEG = 1, 2, 3


def _print_emotions() -> None:
    from .assets import available_emotions, scan_characters
    chars = scan_characters(CHARACTERS_DIR)
    emotions = available_emotions(chars)
    print("Emotions available to the scriptwriter (clips exist for every "
          "character):\n")
    for e in emotions:
        print(f"  {e}")
    print("\nPer character:")
    for name, clips in chars.items():
        missing = sorted(set().union(*(set(c) for c in chars.values())) - set(clips))
        extra = f"   (missing: {', '.join(missing)})" if missing else ""
        print(f"  {name:<8} {len(clips)} clips{extra}")


def build_parser() -> argparse.ArgumentParser:
    rick, morty = CHARACTERS["rick"], CHARACTERS["morty"]
    p = argparse.ArgumentParser(
        prog="charla",
        description="Two-character conversation video generator: free text "
                    "or news URL -> Rick/Morty dialogue with per-speaker "
                    "TTS voices, chroma-keyed over a background video.")
    p.add_argument("input", nargs="?",
                   help="Free text topic, or a news URL (http/https)")
    p.add_argument("--script-file", type=Path, default=None,
                   help="Manual DialogueScript JSON — skips the LLM entirely "
                        "(see examples/demo_script.json)")
    p.add_argument("--language", default=DEFAULT_LANGUAGE,
                   help=f"Dialogue language (default '{DEFAULT_LANGUAGE}')")
    p.add_argument("--min-turns", type=int, default=DEFAULT_MIN_TURNS)
    p.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    p.add_argument("--rick-voice", default=None,
                   help=f"edge-tts voice for rick (default {rick.voice})")
    p.add_argument("--rick-rate", default=None,
                   help="Rate offset for rick (default "
                        f"{rick.voice_rate.replace('%', '%%')}; slower = older)")
    p.add_argument("--rick-pitch", default=None,
                   help=f"Pitch offset for rick (default {rick.voice_pitch}; "
                        "lower = older)")
    p.add_argument("--morty-voice", default=None,
                   help=f"edge-tts voice for morty (default {morty.voice})")
    p.add_argument("--morty-rate", default=None,
                   help="Rate offset for morty (default "
                        f"{morty.voice_rate.replace('%', '%%')}; faster = younger)")
    p.add_argument("--morty-pitch", default=None,
                   help=f"Pitch offset for morty (default {morty.voice_pitch}; "
                        "higher = younger)")
    p.add_argument("--resolution", default=f"{DEFAULT_WIDTH}x{DEFAULT_HEIGHT}",
                   help=f"WxH (default {DEFAULT_WIDTH}x{DEFAULT_HEIGHT}, the "
                        "character clips' native size)")
    p.add_argument("--fps", type=int, default=DEFAULT_FPS)
    p.add_argument("--watermark", default=DEFAULT_WATERMARK,
                   help=f"Bottom-left watermark text (default '{DEFAULT_WATERMARK}'; "
                        "override default via CHARLA_WATERMARK in .env)")
    p.add_argument("--no-watermark", action="store_true",
                   help="Disable the watermark")
    p.add_argument("--no-subtitles", action="store_true",
                   help="Do not burn dialogue captions into the video")
    p.add_argument("--bg-volume", type=float, default=None,
                   help="Background video's own audio under the dialogue, "
                        f"0..0.6 (default {DEFAULT_BG_VOLUME}; 0 = none)")
    p.add_argument("--no-bg-audio", action="store_true",
                   help="Disable the background ambience entirely")
    p.add_argument("--background", type=Path, default=DEFAULT_BACKGROUND,
                   help=f"Background video (default {DEFAULT_BACKGROUND})")
    p.add_argument("--tts", dest="tts_engine",
                   choices=["edge", "xtts", "chatterbox"], default=None,
                   help="Voice engine: edge (edge-tts, + RVC if installed; "
                        "default), xtts (XTTS v2 cloned voices — fine-tuned "
                        "model in models/xtts/<char>/ or zero-shot; see "
                        "COLAB_XTTS.md) or chatterbox (Resemble AI, MIT, "
                        "zero-shot expressive cloning; see "
                        "install-chatterbox.ps1)")
    p.add_argument("--rvc", choices=["auto", "on", "off"], default="auto",
                   help="Dub-voice conversion with the Latino RVC models: "
                        "auto (default: use it when .rvc-venv and models "
                        "exist — see install-rvc.ps1), on (require), off")
    p.add_argument("--char-scale", type=float, default=DEFAULT_CHAR_SCALE,
                   help="Character size as a fraction of the frame height; "
                        "each speaker sits in their bottom corner (default "
                        f"{DEFAULT_CHAR_SCALE})")
    p.add_argument("--chroma-similarity", type=float,
                   default=DEFAULT_CHROMA_SIMILARITY,
                   help="colorkey similarity 0..1 (default "
                        f"{DEFAULT_CHROMA_SIMILARITY}; higher keys more green "
                        "but may eat the character)")
    p.add_argument("--chroma-blend", type=float, default=DEFAULT_CHROMA_BLEND,
                   help=f"colorkey edge blend (default {DEFAULT_CHROMA_BLEND})")
    p.add_argument("--output-dir", default=None,
                   help="Output directory (default: output/<input>-<hash>)")
    p.add_argument("--dry-run", action="store_true",
                   help="Script + manifest only, no media generation")
    p.add_argument("--force", action="store_true",
                   help="Regenerate everything, ignoring cached assets")
    p.add_argument("--force-from", choices=["script", "tts", "render"],
                   help="Regenerate from this stage onward")
    p.add_argument("--reencode-concat", action="store_true",
                   help="Re-encode when joining clips (fallback for glitchy joins)")
    p.add_argument("--text-provider", choices=["auto", "claude", "gemini"],
                   default="auto",
                   help="Which API writes the script: auto (default: Claude "
                        "if ANTHROPIC_API_KEY is set, else Gemini), claude, "
                        "or gemini")
    p.add_argument("--text-model", default=DEFAULT_TEXT_MODEL,
                   help="Model for the script (auto-adjusted to the "
                        "provider's default when it belongs to the other one)")
    p.add_argument("--list-emotions", action="store_true",
                   help="List emotions with clips on disk and exit")
    p.add_argument("--version", action="version", version=f"charla {__version__}")
    return p


def options_from_args(args: argparse.Namespace) -> PipelineOptions:
    try:
        width, height = (int(x) for x in args.resolution.lower().split("x"))
    except ValueError:
        raise SystemExit(f"Invalid --resolution '{args.resolution}', expected WxH")
    return PipelineOptions(
        input_text=args.input or "",
        script_file=args.script_file,
        language=args.language,
        min_turns=args.min_turns,
        max_turns=args.max_turns,
        width=width, height=height, fps=args.fps,
        watermark="" if args.no_watermark else args.watermark,
        subtitles=not args.no_subtitles,
        bg_volume=0.0 if args.no_bg_audio else (
            args.bg_volume if args.bg_volume is not None
            else DEFAULT_BG_VOLUME),
        background=args.background,
        tts_engine=args.tts_engine or DEFAULT_TTS_ENGINE,
        rvc=args.rvc,
        char_scale=args.char_scale,
        chroma_similarity=args.chroma_similarity,
        chroma_blend=args.chroma_blend,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        dry_run=args.dry_run,
        force=args.force,
        force_from=args.force_from,
        reencode_concat=args.reencode_concat,
        text_provider=args.text_provider,
        text_model=args.text_model,
        rick_voice=args.rick_voice, rick_rate=args.rick_rate,
        rick_pitch=args.rick_pitch,
        morty_voice=args.morty_voice, morty_rate=args.morty_rate,
        morty_pitch=args.morty_pitch,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_emotions:
        _print_emotions()
        return 0

    if not args.input and not args.script_file:
        build_parser().error("an input text/URL or --script-file is required "
                             "(or use --list-emotions)")

    from .assets import AssetsError
    from .ffutil import FfmpegError
    from .chatterbox import ChatterboxError
    from .rvc import RvcError
    from .xtts import XttsError
    from .scraper import ScrapeError
    from .script_gen import ScriptGenError
    from .tts import TtsError
    from .pipeline import run_pipeline

    options = options_from_args(args)
    try:
        result = run_pipeline(options)
    except (FileNotFoundError, ValueError, AssetsError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USAGE
    except (ScriptGenError, ScrapeError, TtsError, RvcError, XttsError,
            ChatterboxError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_API
    except FfmpegError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_FFMPEG

    if result.final_video:
        print(f"\nVideo:    {result.final_video}")
    print(f"Manifest: {result.manifest_path}")
    if result.social:
        print("\n--- Descripcion y hashtags recomendados ---")
        print(result.social)
        print(f"(guardado en {result.output_dir / 'social.txt'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
