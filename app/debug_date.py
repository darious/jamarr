import os
import sys
# Manually setup path so we can import app if running as script from inside app dir
sys.path.append("/app")

from app.config import get_music_path
from app.scanner.tags import extract_tags
import mutagen

def main():
    root = get_music_path()
    
    # The path from DB is relative to music root: C/Coldplay/Parachutes (2000)/04 Coldplay - Parachutes - Sparks.flac
    rel_path = "C/Coldplay/Parachutes (2000)/04 Coldplay - Parachutes - Sparks.flac"
    full_path = os.path.join(root, rel_path)
    
    print(f"Checking: {full_path}")
    if not os.path.exists(full_path):
        print("File not found!")
        return

    print("\n--- Extract Tags (Current Clean Logic) ---")
    try:
        tags = extract_tags(full_path)
        print(f"Returns -> date: '{tags.get('date')}'")
        print("All relevant keys:")
        for k, v in tags.items():
            if "date" in k or "year" in k:
                print(f"{k}: {v}")
    except Exception as e:
        print(f"Error extracting tags: {e}")
    
    print("\n--- Raw Mutagen ---")
    try:
        f = mutagen.File(full_path)
        if f and f.tags:
            for k, v in f.tags.items():
                if "date" in k.lower() or "year" in k.lower():
                     print(f"Tag: {k} = {v}")
    except Exception as e:
        print(f"Error reading mutagen: {e}")

if __name__ == "__main__":
    main()
