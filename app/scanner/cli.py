import asyncio
import argparse
import logging
from rich.console import Console
# from rich.logger import RichHandler # generic rich not available
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn

from app.scanner.core import Scanner

# Configure Logging (Standard)
logging.basicConfig(
    level="INFO",
    format="%(message)s", # Simplified format to blend with Rich
    datefmt="%H:%M:%S"
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
        self.progress.update(self.task_id, completed=current, total=total, description=message)

async def main():
    # Parent parser for global arguments
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    parser = argparse.ArgumentParser(description="Jamarr Library Scanner CLI", parents=[parent_parser])
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Command: SCAN
    scan_parser = subparsers.add_parser("scan", help="Scan local music files", parents=[parent_parser])
    scan_parser.add_argument("--path", help="Specific path to scan (default: config music path)")
    scan_parser.add_argument("--force", action="store_true", help="Force rescan of all files")

    # Command: METADATA
    meta_parser = subparsers.add_parser("metadata", help="Fetch artist metadata", parents=[parent_parser])
    meta_parser.add_argument("--artist", help="Filter by artist name")
    meta_parser.add_argument("--mbid", help="Filter by MusicBrainz ID")
    meta_parser.add_argument("--links-only", action="store_true", help="Only update links (Tidal/Qobuz/Wiki)")
    meta_parser.add_argument("--bio-only", action="store_true", help="Only update Bio & Image (skip albums/links)")

    # Command: PRUNE (Remove Orphans)
    subparsers.add_parser("prune", help="Remove orphaned database entries and artwork", parents=[parent_parser])

    # Command: FULL
    subparsers.add_parser("full", help="Full Library Scan & Update", parents=[parent_parser])

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
            console=console
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
            console=console
        ) as progress:
            scanner.scan_logger = CLILogger(progress)
            if args.links_only:
                 await scanner.update_links(artist_filter=args.artist, mbid_filter=args.mbid)
            else:
                 await scanner.update_metadata(artist_filter=args.artist, mbid_filter=args.mbid, bio_only=args.bio_only)
            console.print("[green]Metadata Update Complete![/green]")
    
    elif args.command == "prune":
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
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
             console=console
        ) as progress:
             scanner.scan_logger = CLILogger(progress)
             await scanner.scan_filesystem()
             await scanner.update_metadata()
             await scanner.prune_library()
             console.print("[green]Full Library Update Complete![/green]")
    
    else:
        parser.print_help()

if __name__ == "__main__":
    from app.db import init_db
    async def run():
        await init_db()
        await main()
    asyncio.run(run())
