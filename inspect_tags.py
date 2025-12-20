from mutagen import File
from mutagen.flac import FLAC
import sys

path = "/mnt/music/testing/Bear's Den/Elysium (2014)/01 Bear's Den - Elysium - Elysium.flac"

try:
    f = File(path)
    print(f"File: {path}")
    print(f"Album: {f.get('ALBUM')}")
    
    if isinstance(f, FLAC) and f.pictures:
        pic = f.pictures[0]
        print(f"Picture found: {pic.mime}, {len(pic.data)} bytes")
        print(f"Description: {pic.desc}")
    else:
        print("No FLAC picture found.")
        
except Exception as e:
    print(f"Error: {e}")
