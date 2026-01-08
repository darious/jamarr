import os
import argparse
import io
from mutagen.flac import FLAC, Picture
from PIL import Image, ImageFile
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.panel import Panel

console = Console()
ImageFile.LOAD_TRUNCATED_IMAGES = True

def fix_large_art(file_path, max_size, apply_changes=False):
    try:
        audio = FLAC(file_path)
        if not audio.pictures:
            return False, "No embedded art", False

        # Prefer the first front cover; fall back to the first picture
        picture = next((p for p in audio.pictures if getattr(p, "type", None) == 3), audio.pictures[0])

        img = Image.open(io.BytesIO(picture.data)).convert("RGB")
        width, height = img.size

        if width <= max_size and height <= max_size:
            return False, "Resolution OK", False

        scale_factor = min(max_size / width, max_size / height)
        new_width = max(1, int(round(width * scale_factor)))
        new_height = max(1, int(round(height * scale_factor)))

        if not apply_changes:
            return False, f"{width}x{height} -> {new_width}x{new_height}", True

        resized = img.copy()
        resized.thumbnail((max_size, max_size), Image.LANCZOS)

        buf = io.BytesIO()
        try:
            resized.save(buf, format="JPEG", quality=90, optimize=True)
        except OSError:
            buf = io.BytesIO()
            resized.save(buf, format="JPEG", quality=90)
        new_data = buf.getvalue()

        new_pic = Picture()
        new_pic.data = new_data
        new_pic.type = picture.type or 3
        new_pic.mime = "image/jpeg"
        new_pic.desc = picture.desc or "Cover"
        new_pic.width, new_pic.height = resized.size
        new_pic.depth = 24
        new_pic.colors = 0

        audio.clear_pictures()
        audio.add_picture(new_pic)
        audio.save()

        return True, f"{width}x{height} -> {resized.size[0]}x{resized.size[1]}", False
    except Exception as e:
        return False, f"Error: {str(e)[:40]}", False

def main():
    parser = argparse.ArgumentParser(description="Naim-specific FLAC Artwork Fixer")
    parser.add_argument("path", help="Path to music")
    parser.add_argument("--size", type=int, default=2800, help="Max pixel size")
    parser.add_argument("--apply", action="store_true", help="Actually write changes (default is dry-run)")
    args = parser.parse_args()

    console.print(Panel.fit("[bold cyan]Naim Artwork Optimizer v2.0[/bold cyan]", border_style="blue"))

    flac_files = []
    # Expand path and handle relative paths correctly
    target_path = os.path.abspath(args.path)
    
    if os.path.isfile(target_path) and target_path.lower().endswith(".flac"):
        flac_files.append(target_path)
    elif os.path.isdir(target_path):
        for root, dirs, files in os.walk(target_path):
            dirs.sort()
            for name in sorted(files):
                if name.lower().endswith(".flac"):
                    flac_files.append(os.path.join(root, name))

    flac_files.sort(key=lambda path: (os.path.dirname(path).lower(), os.path.basename(path).lower()))

    if not flac_files:
        console.print(f"[yellow]No FLAC files found at {target_path}[/yellow]")
        return

    changed_count = 0
    would_fix_count = 0
    total_files = len(flac_files)
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), 
                  BarColumn(), TaskProgressColumn(), console=console) as progress:
        
        task = progress.add_task(f"Scanning {total_files} files...", total=total_files)

        for idx, file_path in enumerate(flac_files, start=1):
            changed, msg, would_fix = fix_large_art(file_path, args.size, args.apply)
            basename = os.path.basename(file_path)
            progress.update(task, description=f"Checking [dim]{idx}/{total_files}: {basename}[/dim]")

            if would_fix:
                console.print(f"[cyan]WOULD FIX:[/cyan] {basename} [dim]({msg})[/dim]")
                would_fix_count += 1
            elif changed:
                console.print(f"[bold green]FIXED:[/bold green] {basename} [cyan]({msg})[/cyan]")
                changed_count += 1
            elif msg not in ("Resolution OK", "No embedded art"):
                console.print(f"[yellow]SKIPPED:[/yellow] {basename} [dim]({msg})[/dim]")

            progress.advance(task)

    if args.apply:
        console.print(f"\n[bold blue]Done![/bold blue] Checked [bold cyan]{total_files}[/bold cyan] files. Fixed [bold green]{changed_count}[/bold green] files.")
    else:
        console.print(f"\n[bold blue]Done![/bold blue] Checked [bold cyan]{total_files}[/bold cyan] files. Would fix [bold green]{would_fix_count}[/bold green] files. Use [cyan]--apply[/cyan] to write changes.")

if __name__ == "__main__":
    main()
