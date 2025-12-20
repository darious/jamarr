from mutagen import File
from mutagen.flac import FLAC

path = "/mnt/music/testing/Bear's Den/Elysium (2014)/01 Bear's Den - Elysium - Elysium.flac"

try:
    f = File(path)
    if isinstance(f, FLAC):
        print(f"Total pictures: {len(f.pictures)}")
        for i, pic in enumerate(f.pictures):
            print(f"Pic {i}: {pic.mime}, {len(pic.data)} bytes, type={pic.type}")
    else:
        print("Not a FLAC file or no tags.")
except Exception as e:
    print(f"Error: {e}")
