"""Command line: ``aoostar-lcd run | collect | display | preview | check | screen``."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from .asterctl import PINNED_TAG, AsterctlError
from .config import DEFAULT_CONFIG_PATH, Config, default_config, load_config
from .validate import ConfigError

log = logging.getLogger("aoostar_lcd")


def _config_path(args) -> str:
    return args.config or os.environ.get("AOOSTAR_LCD_CONFIG") or DEFAULT_CONFIG_PATH


def _load(args, allow_default: bool = False) -> Config:
    path = _config_path(args)
    if allow_default and not args.config and not Path(path).exists():
        log.info("no config file at %s; using the built-in demo configuration", path)
        return default_config()
    return load_config(path)


def cmd_run(args) -> int:
    from .app import run_display
    from .collector import Collector
    from .display import make_sink

    config = _load(args)
    sink = make_sink(config.display)
    collector = Collector(config.cards, config.collector.history_file)
    return run_display(config, sink, collector=collector, state_out=args.state_out)


def cmd_collect(args) -> int:
    from .app import run_collector

    return run_collector(_load(args), once=args.once, state_file=args.state)


def cmd_display(args) -> int:
    from .app import file_source, run_display
    from .display import make_sink

    config = _load(args)
    sink = make_sink(config.display)
    source = file_source(args.state or config.collector.state_file, config.collector.max_age)
    return run_display(config, sink, source=source)


def cmd_preview(args) -> int:
    from .app import preview

    config = _load(args, allow_default=True)
    at = None
    if args.at:
        try:
            at = datetime.fromisoformat(args.at)
        except ValueError:
            raise ConfigError(
                f"--at: use ISO format like 2026-01-15T10:24, got {args.at!r}"
            ) from None
    source = "live" if args.live else "state" if args.state else "sample"
    written = preview(
        config,
        out_dir=args.out,
        png=args.png,
        card_id=args.card,
        source=source,
        state_path=args.state,
        at=at,
        no_data=args.no_data_frame,
    )
    for path in written:
        print(path)
    return 0


def cmd_check(args) -> int:
    from .display import make_asterctl

    config = _load(args)
    print(f"config: {config.source} (OK)")
    print(
        f"language: {config.language}  display: {config.display.backend} "
        f"{config.display.width}x{config.display.height}"
    )
    for card in config.cards:
        state = "on " if card.enabled else "off"
        print(
            f"  [{state}] {card.id:<16} {card.type_name:<12} {card.duration:>5g} s  "
            f"refresh {card.collect_every:g} s"
        )
    if args.asterctl or config.display.backend == "asterctl":
        asterctl = make_asterctl(config.display)
        version = asterctl.check()
        print(
            f"asterctl: {asterctl.path()} version {'.'.join(map(str, version))} "
            f"(pinned {PINNED_TAG})"
        )
    return 0


def cmd_screen(args) -> int:
    from .display import make_asterctl

    config = _load(args)
    asterctl = make_asterctl(config.display)
    if args.state == "on":
        asterctl.on()
    else:
        asterctl.off()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aoostar-lcd",
        description="Rotating status cards for the AOOSTAR 960x376 USB LCD.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--log-level",
        default=os.environ.get("AOOSTAR_LCD_LOG_LEVEL", "INFO"),
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def with_config(p):
        p.add_argument(
            "-c",
            "--config",
            help=f"YAML file (default: $AOOSTAR_LCD_CONFIG or {DEFAULT_CONFIG_PATH})",
        )
        return p

    p = with_config(sub.add_parser("run", help="collect and display in one process"))
    p.add_argument("--state-out", help="also write the state JSON here (debugging)")
    p.set_defaults(func=cmd_run)

    p = with_config(sub.add_parser("collect", help="collector only: write the state file"))
    p.add_argument("--once", action="store_true", help="write one snapshot and exit")
    p.add_argument("--state", help="state file (default: collector.state_file)")
    p.set_defaults(func=cmd_collect)

    p = with_config(sub.add_parser("display", help="renderer only: read the state file"))
    p.add_argument("--state", help="state file (default: collector.state_file)")
    p.set_defaults(func=cmd_display)

    p = with_config(sub.add_parser("preview", help="render cards to PNG, no hardware"))
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument("--out", help="folder: one PNG per card")
    target.add_argument("--png", help="single PNG file (first card, or --card)")
    p.add_argument("--card", help="only this card id")
    data = p.add_mutually_exclusive_group()
    data.add_argument("--live", action="store_true", help="use this machine's real metrics")
    data.add_argument("--state", help="use a state file written by 'collect'")
    p.add_argument("--at", help="pretend the time is this (ISO), for reproducible clocks")
    p.add_argument(
        "--no-data-frame",
        action="store_true",
        help="also write no-data.png (the frame shown when the state is stale)",
    )
    p.set_defaults(func=cmd_preview)

    p = with_config(sub.add_parser("check", help="validate the config (and asterctl)"))
    p.add_argument(
        "--asterctl", action="store_true", help="check asterctl even if the backend is not asterctl"
    )
    p.set_defaults(func=cmd_check)

    p = with_config(sub.add_parser("screen", help="switch the panel on or off"))
    p.add_argument("state", choices=("on", "off"))
    p.set_defaults(func=cmd_screen)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=args.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("PIL").setLevel(logging.INFO)  # Pillow's DEBUG output is noise here
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"aoostar-lcd: configuration error: {exc}", file=sys.stderr)
        return 2
    except AsterctlError as exc:
        print(f"aoostar-lcd: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"aoostar-lcd: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
