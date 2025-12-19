import asyncio
import logging
import sys
import argparse
from app.db import init_db
from app.scanner.scan import scan_library

def configure_logging(verbosity):
    # Default level
    root_level = logging.INFO
    
    # -v: Show file scanning (app.scanner.scan DEBUG)
    # -vv: Show everything (root DEBUG)
    
    if verbosity == 1:
        # Verbose: Show file scanning logs
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler(sys.stdout)]
        )
        logging.getLogger("app.scanner.scan").setLevel(logging.DEBUG)
    elif verbosity >= 2:
        # Very Verbose: Show everything including API calls
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler(sys.stdout)]
        )
        # Ensure httpx is also debug if desired, or keep it quiet?
        # User asked for "all the api lookups", so httpx DEBUG is appropriate.
    else:
        # Default: INFO (High level only)
        # We want to hide DEBUG logs from app.scanner.scan and app.scanner.metadata
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler(sys.stdout)]
        )
        # Explicitly ensure these are not showing DEBUG
        logging.getLogger("app.scanner.scan").setLevel(logging.INFO)
        logging.getLogger("app.scanner.metadata").setLevel(logging.INFO)

async def main():
    parser = argparse.ArgumentParser(description="Scan music library")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (-v for files, -vv for API details)")
    parser.add_argument("--force-metadata", action="store_true", help="Force update of artist metadata")
    args = parser.parse_args()
    
    configure_logging(args.verbose)
    
    print("Initializing database...")
    await init_db()
    print("Starting library scan...")
    await scan_library(force_metadata=args.force_metadata)
    print("Scan complete.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScan interrupted.")
    except Exception as e:
        print(f"\nError during scan: {e}")
        sys.exit(1)
