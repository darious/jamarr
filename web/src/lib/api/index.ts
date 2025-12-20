export interface Artist {
    name: string;
    image_url: string | null;
    art_id: number | null;
    art_sha1?: string | null;
    bio: string | null;
    similar_artists: string[];
    top_tracks: { name: string; album: string; date: string; duration_ms: number }[];
    singles?: { mbid: string; title: string; date: string; artist: string }[];
    sort_name: string;
    homepage: string | null;
    spotify_url: string | null;
    wikipedia_url: string | null;
    qobuz_url: string | null;
    musicbrainz_url: string | null;
    albums?: {
        mbid: string;
        title: string;
        date: string;
        artist: string;
        qobuz_url?: string;
        qobuz_id?: string;
        musicbrainz_url?: string;
    }[];
}

export interface Album {
    album: string;
    art_id: number | null;
    art_sha1?: string | null;
    artist_name: string;
    is_hires: number;
    year: string | null;
    track_count: number;
    total_duration: number;
    type: 'main' | 'appears_on';
    mb_release_id?: string;
    musicbrainz_url?: string;
}

export interface Track {
    id: number;
    path: string;
    title: string;
    artist: string;
    album: string;
    album_artist: string | null;
    track_no: number | null;
    disc_no: number | null;
    date: string | null;
    duration_seconds: number;
    art_id: number | null;
    art_sha1?: string | null;
    codec: string | null;
    bitrate: number | null;
    sample_rate_hz: number | null;
    bit_depth: number | null;
}

export async function fetchArtists(fetchFn: any = fetch): Promise<Artist[]> {
    const res = await fetchFn('/api/artists');
    if (!res.ok) throw new Error('Failed to fetch artists');
    return await res.json();
}

export async function fetchAlbums(params: { artist?: string } = {}, fetchFn: any = fetch): Promise<Album[]> {
    let url = '/api/albums';
    if (params.artist) {
        url += `?artist=${encodeURIComponent(params.artist)}`;
    }
    const res = await fetchFn(url);
    if (!res.ok) throw new Error('Failed to fetch albums');
    return await res.json();
}

export async function fetchTracks(params: { album?: string, artist?: string } = {}, fetchFn: any = fetch): Promise<Track[]> {
    // Note: Backend expects 'album' name as string, not ID.
    // The frontend route is /album/[artist]/[album], so we pass the album name.
    let url = '/api/tracks?';
    const q = new URLSearchParams();
    if (params.album) q.append('album', params.album);
    if (params.artist) q.append('artist', params.artist);

    const res = await fetchFn(url + q.toString());
    if (!res.ok) throw new Error('Failed to fetch tracks');
    return await res.json();
}

export async function triggerScan(): Promise<void> {
    const res = await fetch('/api/scan', { method: 'POST' });
    if (!res.ok) throw new Error('Failed to trigger scan');
}

export async function refreshArtistMetadata(artistName: string): Promise<void> {
    const res = await fetch(`/api/scan_artist?artist_name=${encodeURIComponent(artistName)}`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to refresh artist metadata');
}

export async function refreshArtistSingles(artistName: string): Promise<void> {
    const res = await fetch(`/api/scan_artist_singles?artist_name=${encodeURIComponent(artistName)}`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to refresh artist singles');
}

export async function fetchNewReleases(fetchFn: any = fetch): Promise<Album[]> {
    const res = await fetchFn('/api/home/new-releases');
    if (!res.ok) throw new Error('Failed to fetch new releases');
    return await res.json();
}

export async function fetchRecentlyAddedAlbums(fetchFn: any = fetch): Promise<Album[]> {
    const res = await fetchFn('/api/home/recently-added-albums');
    if (!res.ok) throw new Error('Failed to fetch recently added albums');
    return await res.json();
}

export async function fetchRecentlyPlayedAlbums(fetchFn: any = fetch): Promise<Album[]> {
    const res = await fetchFn('/api/home/recently-played-albums');
    if (!res.ok) throw new Error('Failed to fetch recently played albums');
    return await res.json();
}

export async function fetchRecentlyPlayedArtists(fetchFn: any = fetch): Promise<Artist[]> {
    const res = await fetchFn('/api/home/recently-played-artists');
    if (!res.ok) throw new Error('Failed to fetch recently played artists');
    return await res.json();
}

export async function fetchDiscoverArtists(fetchFn: any = fetch): Promise<Artist[]> {
    const res = await fetchFn('/api/home/discover-artists');
    if (!res.ok) throw new Error('Failed to fetch discover artists');
    return await res.json();
}
