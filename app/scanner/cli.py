import asyncio
import argparse
import logging
from rich.console import Console

# from rich.logger import RichHandler # generic rich not available
from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    TextColumn,
    MofNCompleteColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from app.scanner.core import Scanner
from app.scanner.audio_analysis import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_CONCURRENCY,
    DEFAULT_SILENCE_MIN_DURATION_SECONDS,
    DEFAULT_SILENCE_THRESHOLD_DB,
    AudioAnalysisRunner,
)

# Configure Logging (Standard)
logging.basicConfig(
    level="INFO",
    format="%(message)s",  # Simplified format to blend with Rich
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("jamarr_cli")

# Silence noisy libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

console = Console()


class CLILogger:
    def __init__(self, progress):
        self.progress = progress
        self.task_id = None

    def emit_progress(self, current, total, message):
        if self.task_id is None:
            self.task_id = self.progress.add_task(message, total=total)

        # Always update
        self.progress.update(
            self.task_id, completed=current, total=total, description=message
        )


async def main():
    # Parent parser for global arguments
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )

    parser = argparse.ArgumentParser(
        description="Jamarr Library Scanner CLI", parents=[parent_parser]
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Command: SCAN
    scan_parser = subparsers.add_parser(
        "scan", help="Scan local music files", parents=[parent_parser]
    )
    scan_parser.add_argument(
        "--path", help="Specific path to scan (default: config music path)"
    )
    scan_parser.add_argument(
        "--force", action="store_true", help="Force rescan of all files"
    )

    # Command: METADATA
    meta_parser = subparsers.add_parser(
        "metadata", help="Fetch artist metadata", parents=[parent_parser]
    )
    meta_parser.add_argument("--artist", help="Filter by artist name")
    meta_parser.add_argument("--mbid", help="Filter by MusicBrainz ID")
    meta_parser.add_argument(
        "--links-only", action="store_true", help="Only update links (Tidal/Qobuz/Wiki)"
    )
    meta_parser.add_argument(
        "--bio-only",
        action="store_true",
        help="Only update Bio & Image (skip albums/links)",
    )

    # Command: PRUNE (Remove Orphans)
    subparsers.add_parser(
        "prune",
        help="Remove orphaned database entries and artwork",
        parents=[parent_parser],
    )

    # Command: FULL
    full_parser = subparsers.add_parser(
        "full", help="Full Library Scan & Update", parents=[parent_parser]
    )
    full_parser.add_argument(
        "--force",
        action="store_true",
        help="Force filesystem rescan and full metadata update (otherwise fills only missing metadata)",
    )

    # Command: AUDIO ANALYSIS
    audio_parser = subparsers.add_parser(
        "audio-analysis",
        help="Analyze local audio files and store derived track metrics",
        parents=[parent_parser],
    )
    audio_parser.add_argument(
        "--phase",
        choices=["1", "2", "3", "4", "all"],
        default="1",
        help="Analysis phase to run.",
    )
    audio_parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Number of DB rows to select per batch (default: {DEFAULT_BATCH_SIZE})",
    )
    audio_parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"Number of ffmpeg analyses to run at once (default: {DEFAULT_CONCURRENCY})",
    )
    audio_parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of tracks to process in this run",
    )
    audio_parser.add_argument(
        "--track-id",
        type=int,
        help="Analyze one track ID",
    )
    audio_parser.add_argument(
        "--path",
        help="Analyze one relative file path or all tracks under a relative directory",
    )
    audio_parser.add_argument(
        "--force",
        action="store_true",
        help="Analyze selected tracks even when cached analysis is current",
    )
    audio_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which tracks would be selected without running ffmpeg or writing results",
    )
    audio_parser.add_argument(
        "--silence-threshold-db",
        type=float,
        default=DEFAULT_SILENCE_THRESHOLD_DB,
        help=f"Silence threshold in dBFS (default: {DEFAULT_SILENCE_THRESHOLD_DB:g})",
    )
    audio_parser.add_argument(
        "--silence-min-duration",
        type=float,
        default=DEFAULT_SILENCE_MIN_DURATION_SECONDS,
        help=f"Minimum silence duration in seconds (default: {DEFAULT_SILENCE_MIN_DURATION_SECONDS:g})",
    )
    audio_parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Per-track ffmpeg timeout in seconds (default: 600)",
    )

    args = parser.parse_args()

    # Apply Verbose Logging
    if getattr(args, "verbose", False):
        logging.getLogger("app").setLevel(logging.DEBUG)
        logging.getLogger("jamarr_cli").setLevel(logging.DEBUG)
        logger.debug("Verbose mode enabled.")

    scanner = Scanner()

    if args.command == "scan":
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            scanner.scan_logger = CLILogger(progress)
            await scanner.scan_filesystem(root_path=args.path, force_rescan=args.force)
            console.print("[green]Scan Complete![/green]")

    elif args.command == "metadata":
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        ) as progress:
            scanner.scan_logger = CLILogger(progress)
            if args.links_only:
                await scanner.update_links(
                    artist_filter=args.artist, mbid_filter=args.mbid
                )
            else:
                await scanner.update_metadata(
                    artist_filter=args.artist,
                    mbid_filter=args.mbid,
                    bio_only=args.bio_only,
                )
            console.print("[green]Metadata Update Complete![/green]")

    elif args.command == "prune":
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            scanner.scan_logger = CLILogger(progress)
            await scanner.prune_library()
            console.print("[green]Library Pruned & Cleaned![/green]")

    elif args.command == "full":
        # Chain them
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
        ) as progress:
            scanner.scan_logger = CLILogger(progress)
            force_flag = getattr(args, "force", False)
            metadata_missing_only = not force_flag
            artist_mbids = (
                await scanner.scan_filesystem(force_rescan=force_flag) or set()
            )
            mbid_filter = None if force_flag else {mb for mb, _ in artist_mbids if mb}
            if not force_flag and not mbid_filter:
                console.print(
                    "[yellow]No new/updated artists detected; skipping metadata.[/yellow]"
                )
            else:
                await scanner.update_metadata(
                    missing_only=metadata_missing_only, mbid_filter=mbid_filter
                )
            await scanner.prune_library()
            console.print("[green]Full Library Update Complete![/green]")

    elif args.command == "audio-analysis":
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task_id = None

            def progress_cb(current, total, message):
                nonlocal task_id
                display_total = total if total is not None else max(current, 1)
                if task_id is None:
                    task_id = progress.add_task(message, total=display_total)
                progress.update(
                    task_id,
                    completed=current,
                    total=display_total,
                    description=message,
                )

            runner = AudioAnalysisRunner(
                batch_size=args.batch_size,
                concurrency=args.concurrency,
                limit=args.limit,
                force=args.force,
                dry_run=args.dry_run,
                track_id=args.track_id,
                path=args.path,
                silence_threshold_db=args.silence_threshold_db,
                silence_min_duration_seconds=args.silence_min_duration,
                timeout_seconds=args.timeout,
                progress_cb=progress_cb,
            )
            phase_methods = {
                "1": runner.run_phase1,
                "2": runner.run_phase2,
                "3": runner.run_phase3,
                "4": runner.run_phase4,
            }
            if args.phase == "all":
                all_stats = {}
                for phase in ["1", "2", "3", "4"]:
                    all_stats[f"phase{phase}"] = await phase_methods[phase]()
                console.print(f"[green]Audio analysis complete:[/green] {all_stats}")
            else:
                stats = await phase_methods[args.phase]()
                console.print(f"[green]Audio analysis complete:[/green] {stats}")

    else:
        parser.print_help()


if __name__ == "__main__":
    import sys

    from app.db import init_db
    from app.scanner.core import warm_dns_cache

    async def run():
        await init_db()
        # Warm DNS cache before network-backed scanner commands.
        if "audio-analysis" not in sys.argv[1:]:
            await warm_dns_cache()
        await main()

    asyncio.run(run())
