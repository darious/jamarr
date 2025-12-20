from mutagen import File
from mutagen.flac import FLAC

path = "/mnt/music/testing/Bear's Den/Blue Hours (2022)/01 New Ways.flac"

try:
    f = File(path)
    if isinstance(f, FLAC) and f.pictures:
        pic = f.pictures[0]
        print(f"Picture found: {pic.mime}, {len(pic.data)} bytes")
    else:
        print("No FLAC picture found.")
except Exception as e:
    print(f"Error: {e}")
