import type { Track } from "$lib/api";

export type DownloadMode = "album" | "playlist";

interface DownloadOptions {
    mode: DownloadMode;
    folderName: string; // Artist for album, Playlist Name for playlist
    subFolderName?: string; // Album Name for album, null for playlist
    tracks: Track[];
}

export async function downloadTracks(options: DownloadOptions) {
    if (!window.showDirectoryPicker) {
        if (!window.isSecureContext) {
            alert(
                "Download failed: The File System Access API requires a secure context (HTTPS or localhost).\n\n" +
                "You are currently accessing the site via an insecure IP address. Please use localhost or set up HTTPS."
            );
        } else {
            alert("Your browser does not support the File System Access API.");
        }
        return;
    }

    try {
        // 1. Ask for root folder
        const rootHandle = await window.showDirectoryPicker();

        // 2. Create/Get Artist or Playlist folder
        const folderHandle = await rootHandle.getDirectoryHandle(
            sanitizeFilename(options.folderName),
            { create: true }
        );

        // 3. Create/Get Album subfolder if needed
        let targetHandle = folderHandle;
        if (options.subFolderName) {
            targetHandle = await folderHandle.getDirectoryHandle(
                sanitizeFilename(options.subFolderName),
                { create: true }
            );
        }

        // 4. Download tracks
        let downloadedCount = 0;

        // Check for existing files first
        let dirIsEmpty = true;
        // @ts-ignore - async iterator on values() is valid in modern browsers
        for await (const _ of targetHandle.values()) {
            dirIsEmpty = false;
            break;
        }

        let shouldOverwrite = false;
        if (!dirIsEmpty) {
            const result = confirm(`The folder "${targetHandle.name}" is not empty.\nDo you want to continue and overwrite existing files?`);
            if (!result) return;
            shouldOverwrite = true;
        }

        for (let i = 0; i < options.tracks.length; i++) {
            const track = options.tracks[i];

            let filename = "";
            const originalFilename = track.path.split('/').pop() || `track-${track.id}.mp3`;

            if (options.mode === "playlist") {
                // "Playlists/PlaylistName/Position CurrentFilename.ext"
                const totalTracks = options.tracks.length;
                const digits = totalTracks > 99 ? 3 : 2;
                const position = (i + 1).toString().padStart(digits, '0');

                filename = `${position} ${originalFilename}`;
            } else {
                // Album: "filenames can be as in the library"
                filename = originalFilename;
            }

            filename = sanitizeFilename(filename);

            try {
                const fileHandle = await targetHandle.getFileHandle(filename, { create: true });
                const writable = await fileHandle.createWritable();

                // Fetch content
                const response = await fetch(`/api/stream/${track.id}`);
                if (!response.ok) throw new Error(`Failed to fetch track ${track.id}`);

                if (response.body) {
                    await response.body.pipeTo(writable);
                    downloadedCount++;
                } else {
                    console.error("No body in response");
                }

            } catch (e) {
                console.error(`Failed to save ${filename}:`, e);
            }
        }

        alert(`Download complete!\nSaved ${downloadedCount} tracks.`);

    } catch (err) {
        if ((err as Error).name !== 'AbortError') {
            console.error("Download failed:", err);
            alert("Download failed. See console for details.");
        }
    }
}

function sanitizeFilename(name: string): string {
    return name.replace(/[/\\?%*:|"<>]/g, '-');
}
