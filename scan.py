import asyncio
import logging
import sys
import shutil
import os
import argparse
from app.db import init_db, DB_PATH
from app.scanner.scan import scan_library
from app.scanner.artwork import CACHE_DIR as ART_CACHE_DIR

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
    parser.add_argument("--reset", action="store_true", help="Wipe database and artwork cache before scanning")
    args = parser.parse_args()
    
    configure_logging(args.verbose)
    
    if args.reset:
        print("Resetting library...")
        # Drop DB
        if os.path.exists(DB_PATH):
            try:
                os.remove(DB_PATH)
                print(f"Deleted database: {DB_PATH}")
            except Exception as e:
                print(f"Error deleting database: {e}")
        
        # Clear Artwork
        # Note: ART_CACHE_DIR is 'cache/art' relative to CWD usually
        if os.path.exists(ART_CACHE_DIR):
            try:
                shutil.rmtree(ART_CACHE_DIR)
                print(f"Cleared artwork cache: {ART_CACHE_DIR}")
            except Exception as e:
                 print(f"Error clearing artwork cache: {e}")
        
        # Recreate directory just in case
        os.makedirs(ART_CACHE_DIR, exist_ok=True)
    
    print("Initializing database...")
    await init_db()
    
    # Ensure art dir exists (init_db creates cache/, but maybe not cache/art)
    os.makedirs(ART_CACHE_DIR, exist_ok=True)

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
