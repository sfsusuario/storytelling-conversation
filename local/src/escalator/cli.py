from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import (CURATED_VOICES, DEFAULT_FPS, DEFAULT_HEIGHT,
                     DEFAULT_IMAGE_MODEL, DEFAULT_IMAGE_PROVIDER,
                     DEFAULT_KOKORO_VOICE, DEFAULT_LANGUAGE, DEFAULT_MOTION,
                     DEFAULT_TEXT_PROVIDER, DEFAULT_TTS_PROVIDER,
                     IMAGE_PROVIDERS,
                     DEFAULT_MUSIC_SOURCE, DEFAULT_MUSIC_VOLUME,
                     DEFAULT_STAGES, DEFAULT_TEXT_MODEL,
                     DEFAULT_VOICE, DEFAULT_VOICE_PITCH, DEFAULT_VOICE_RATE,
                     DEFAULT_WATERMARK, DEFAULT_WIDTH, STYLE_SETS,
                     PipelineOptions)

EXIT_USAGE, EXIT_API, EXIT_FFMPEG = 1, 2, 3


def _print_style_sets() -> None:
    print("Style sets (level 1 -> 5, always ascending):\n")
    for name in sorted(STYLE_SETS):
        ladder = " -> ".join(p.name for p in STYLE_SETS[name])
        print(f"  {name:<12} {ladder}")
    print("\nSpecial values: random (pick one set), mix (random persona per level)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="escalate",
        description="Escalating-sophistication video generator: portrait + "
                    "phrase -> multi-scene styled video with TTS narration.")
    p.add_argument("base_image", nargs="?", help="Portrait image file")
    p.add_argument("phrase", nargs="?", help="Short phrase to escalate")
    p.add_argument("--style-set", default="random",
                   help="Set name, 'random' (default) or 'mix'")
    p.add_argument("--seed", type=int, default=None,
                   help="Seed for reproducible random/mix selection")
    p.add_argument("--stages", type=int, default=DEFAULT_STAGES,
                   help=f"Number of scenes (default {DEFAULT_STAGES})")
    p.add_argument("--styles", default=None,
                   help="Semicolon-separated manual persona override")
    p.add_argument("--voice", default=DEFAULT_VOICE,
                   help=f"Voice name: Kokoro (em_alex, ef_dora, em_santa) or "
                        f"edge-tts (default {DEFAULT_VOICE}; e.g. "
                        f"{', '.join(CURATED_VOICES[:4])}). A voice of the "
                        "other provider is swapped for its default")
    p.add_argument("--voice-rate", default=DEFAULT_VOICE_RATE,
                   help="Speech rate offset (default "
                        f"{DEFAULT_VOICE_RATE.replace('%', '%%')}; "
                        "slower sounds older)")
    p.add_argument("--voice-pitch", default=DEFAULT_VOICE_PITCH,
                   help=f"Pitch offset (default {DEFAULT_VOICE_PITCH}; "
                        "lower sounds older)")
    p.add_argument("--language", default=DEFAULT_LANGUAGE,
                   help=f"Language for rewrites/narration (default "
                        f"'{DEFAULT_LANGUAGE}'; e.g. es, en, pt)")
    p.add_argument("--resolution", default=f"{DEFAULT_WIDTH}x{DEFAULT_HEIGHT}",
                   help=f"WxH (default {DEFAULT_WIDTH}x{DEFAULT_HEIGHT})")
    p.add_argument("--fps", type=int, default=DEFAULT_FPS)
    p.add_argument("--watermark", default=DEFAULT_WATERMARK,
                   help=f"Bottom-left watermark text (default '{DEFAULT_WATERMARK}'; "
                        "override default via ESCALATE_WATERMARK in .env)")
    p.add_argument("--no-watermark", action="store_true",
                   help="Disable the watermark")
    p.add_argument("--no-subtitles", action="store_true",
                   help="Do not burn narration subtitles into the video")
    p.add_argument("--music-volume", type=float, default=None,
                   help="Background music volume 0..0.6 (default "
                        "ESCALATE_MUSIC_VOLUME or 0.25; 0 = none)")
    p.add_argument("--no-music", action="store_true",
                   help="Disable the ambient background sound")
    p.add_argument("--music-source", choices=["synth", "track"],
                   default=DEFAULT_MUSIC_SOURCE,
                   help="synth = synthesized ambience, immune to TikTok/"
                        "YouTube copyright detection (default); track = "
                        "CC-BY music from incompetech (may be auto-blocked "
                        "on some platforms)")
    p.add_argument("--fit", choices=["crop", "blur", "pad"], default="crop",
                   help="How the image fills the phone frame: crop = fill "
                        "TikTok-style (default), blur = blurred background, "
                        "pad = black bars")
    p.add_argument("--output-dir", default=None,
                   help="Output directory (default: output/<phrase>-<hash>)")
    p.add_argument("--dry-run", action="store_true",
                   help="Text rewrites + manifest only, no media generation")
    p.add_argument("--test-mode", action="store_true",
                   help="Cheap full run: skips Gemini image generation (reuses "
                        "the portrait with a stage label) — only the Claude "
                        "text call plus free TTS")
    p.add_argument("--force", action="store_true",
                   help="Regenerate everything, ignoring cached assets")
    p.add_argument("--force-from", choices=["text", "images", "tts", "motion", "render"],
                   help="Regenerate from this stage onward")
    p.add_argument("--reencode-concat", action="store_true",
                   help="Re-encode when joining clips (fallback for glitchy joins)")
    p.add_argument("--text-provider",
                   choices=["auto", "ollama", "claude", "gemini"],
                   default=DEFAULT_TEXT_PROVIDER,
                   help="Who writes the rewrites: auto (default: local Ollama "
                        "if running, else Claude if ANTHROPIC_API_KEY is set, "
                        "else Gemini), ollama, claude, or gemini")
    p.add_argument("--image-provider", choices=IMAGE_PROVIDERS,
                   default=DEFAULT_IMAGE_PROVIDER,
                   help="Image backend: auto (default: local flux-kontext if "
                        "the XPU stack is installed, else gemini), "
                        "flux-kontext (local, best), sdxl-face (local, fast), "
                        "gemini (cloud)")
    p.add_argument("--motion", choices=["none", "rotate3d", "liveportrait"],
                   default=DEFAULT_MOTION,
                   help="Animate each scene: none (default), rotate3d (layered 3D "
                        "photo: the camera orbits the subject, ~1.5 min/scene on CPU), "
                        "liveportrait (face animation, ~7 min/scene on CPU, "
                        "needs setup-liveportrait.ps1)")
    p.add_argument("--tts-provider", choices=["kokoro", "edge"],
                   default=DEFAULT_TTS_PROVIDER,
                   help=f"Voice backend: kokoro (local, default voice "
                        f"{DEFAULT_KOKORO_VOICE}) or edge (online edge-tts)")
    p.add_argument("--text-model", default=DEFAULT_TEXT_MODEL,
                   help="Model for the rewrites (auto-adjusted to the "
                        "provider's default when it belongs to the other one)")
    p.add_argument("--image-model", default=DEFAULT_IMAGE_MODEL)
    p.add_argument("--list-style-sets", action="store_true",
                   help="List available style sets and exit")
    p.add_argument("--version", action="version", version=f"escalate {__version__}")
    return p


def options_from_args(args: argparse.Namespace) -> PipelineOptions:
    try:
        width, height = (int(x) for x in args.resolution.lower().split("x"))
    except ValueError:
        raise SystemExit(f"Invalid --resolution '{args.resolution}', expected WxH")
    styles = [s for s in (args.styles or "").split(";") if s.strip()] or None
    return PipelineOptions(
        base_image=Path(args.base_image),
        phrase=args.phrase,
        style_set=args.style_set,
        seed=args.seed,
        stages=len(styles) if styles else args.stages,
        styles=styles,
        voice=args.voice,
        voice_rate=args.voice_rate,
        voice_pitch=args.voice_pitch,
        language=args.language,
        width=width, height=height, fps=args.fps, fit=args.fit,
        watermark="" if args.no_watermark else args.watermark,
        subtitles=not args.no_subtitles,
        music_volume=0.0 if args.no_music else (
            args.music_volume if args.music_volume is not None
            else DEFAULT_MUSIC_VOLUME),
        music_source=args.music_source,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        dry_run=args.dry_run,
        test_mode=args.test_mode,
        force=args.force,
        force_from=args.force_from,
        reencode_concat=args.reencode_concat,
        text_provider=args.text_provider,
        text_model=args.text_model,
        image_provider=args.image_provider,
        image_model=args.image_model,
        tts_provider=args.tts_provider,
        motion=args.motion,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_style_sets:
        _print_style_sets()
        return 0

    if args.base_image == "ui" and args.phrase is None:
        from .ui import main as ui_main
        return ui_main()

    if not args.base_image or not args.phrase:
        build_parser().error("base_image and phrase are required "
                             "(or use --list-style-sets / 'escalate ui')")

    from .ffutil import FfmpegError
    from .image_gen import ImageGenError
    from .text_gen import TextGenError
    from .motion import MotionError
    from .tts import TtsError
    from .pipeline import run_pipeline

    options = options_from_args(args)
    try:
        result = run_pipeline(options)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USAGE
    except (TextGenError, ImageGenError, TtsError, MotionError) as e:
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
