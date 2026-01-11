export interface Artist {
    mbid?: string;
    name: string;
    image_url: string | null;
    art_sha1?: string | null;
    background_sha1?: string | null;
    bio: string | null;
    similar_artists: {
        name: string;
        mbid?: string | null;
        image_url?: string | null;
        art_sha1?: string | null;
        in_library?: boolean;
        external_url?: string | null;
    }[];
    genres?: {
        name: string;
        count: number;
    }[];
    top_tracks: {
        name: string;
        album: string;
        date: string;
        duration_ms: number;
        popularity?: number;
        local_track_id?: number | null;
        codec?: string | null;
        bit_depth?: number | null;
        sample_rate_hz?: number | null;
        duration_seconds?: number | null;
        art_sha1?: string | null;
        mb_release_id?: string | null;
    }[];
    singles?: {
        mbid: string;
        title: string;
        date: string;
        artist: string;
        local_track_id?: number | null;
        codec?: string | null;
        bit_depth?: number | null;
        sample_rate_hz?: number | null;
        art_sha1?: string | null;
        album?: string;
        mb_release_id?: string | null;
        popularity?: number;
    }[];
    sort_name: string;
    primary_album_count?: number;
    appears_on_album_count?: number;
    listens?: number;
    homepage: string | null;
    spotify_url: string | null;
    wikipedia_url: string | null;
    qobuz_url: string | null;
    musicbrainz_url: string | null;
    tidal_url?: string | null;
    lastfm_url?: string | null;
    discogs_url?: string | null;
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
    mbid?: string;
    album_mbid?: string;
    art_sha1?: string | null;
    artist_name: string;
    artist_mbid?: string;
    is_hires: number;
    year: string | null;
    track_count: number;
    total_duration: number;
    type: 'main' | 'appears_on';
    mb_release_id?: string;
    musicbrainz_url?: string;
    release_type?: string;
    description?: string;
    peak_chart_position?: number;
    label?: string;
    external_links?: { type: string; url: string }[];
    artists?: { name: string; mbid?: string }[];
    listens?: number;
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
    art_sha1?: string | null;
    codec: string | null;
    bitrate: number | null;
    sample_rate_hz: number | null;
    bit_depth: number | null;
    mb_release_id?: string | null;
    mb_release_group_id?: string | null;
    artist_mbid?: string | null;
    album_artist_mbid?: string | null;
    album_mbid?: string | null;
    popularity?: number;
    plays?: number;
    artists?: { name: string; mbid?: string }[];
}

export interface User {
    id: number;
    username: string;
    email: string;
    display_name: string;
    accent_color?: string;
    theme_mode?: 'dark' | 'light';
    created_at?: string | null;
    last_login?: string | null;
}

export async function fetchArtists(
    fetchFn: any = fetch,
    options: { limit?: number; offset?: number; name?: string; mbid?: string, startsWith?: string } = {}
): Promise<Artist[]> {
    const params = new URLSearchParams();
    if (options.limit !== undefined) params.append('limit', options.limit.toString());
    if (options.offset !== undefined) params.append('offset', options.offset.toString());
    if (options.name !== undefined) params.append('name', options.name);
    if (options.mbid !== undefined) params.append('mbid', options.mbid);
    if (options.startsWith !== undefined) params.append('starts_with', options.startsWith);

    const res = await fetchFn(`/api/artists?${params.toString()}`);
    if (!res.ok) throw new Error('Failed to fetch artists');
    return await res.json();
}

export async function fetchArtistIndex(fetchFn: any = fetch): Promise<string[]> {
    const res = await fetchFn('/api/artists/index');
    if (!res.ok) throw new Error('Failed to fetch artist index');
    return await res.json();
}

export async function fetchAlbums(params: { artist?: string; artistMbid?: string; albumMbid?: string } = {}, fetchFn: any = fetch): Promise<Album[]> {
    let url = '/api/albums';
    const query = new URLSearchParams();

    if (params.artist) {
        query.append('artist', params.artist);
    }
    if (params.artistMbid) {
        query.append('artist_mbid', params.artistMbid);
    }
    if (params.albumMbid) {
        query.append('album_mbid', params.albumMbid);
    }

    const queryString = query.toString();
    if (queryString) {
        url += `?${queryString}`;
    }

    const res = await fetchFn(url);
    if (!res.ok) throw new Error('Failed to fetch albums');
    return await res.json();
}

export async function fetchTracks(params: { album?: string, artist?: string, albumMbid?: string } = {}, fetchFn: any = fetch): Promise<Track[]> {
    // Note: Backend expects 'album' name as string, not ID.
    // The frontend route is /album/[artist]/[album], so we pass the album name.
    let url = '/api/tracks?';
    const q = new URLSearchParams();
    if (params.album) q.append('album', params.album);
    if (params.artist) q.append('artist', params.artist);
    if (params.albumMbid) q.append('album_mbid', params.albumMbid);

    const res = await fetchFn(url + q.toString());
    if (!res.ok) throw new Error('Failed to fetch tracks');
    return await res.json();
}

export async function triggerScan(forceRescan: boolean = false): Promise<void> {
    const res = await fetch('/api/library/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'filesystem', force: forceRescan })
    });
    if (!res.ok) throw new Error('Failed to trigger scan');
}

export async function triggerFilesystemScan(opts: { force?: boolean; path?: string } = {}): Promise<void> {
    const res = await fetch('/api/library/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'filesystem', force: Boolean(opts.force), path: opts.path || null })
    });
    if (!res.ok) throw new Error('Failed to trigger scan');
}


export async function refreshArtistMetadata(artistName: string): Promise<void> {
    const res = await fetch('/api/library/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'metadata', artist_filter: artistName })
    });
    if (!res.ok) throw new Error('Failed to refresh artist metadata');
}

export async function refreshArtistSingles(artistName: string): Promise<void> {
    return refreshArtistMetadata(artistName);
}

export type MetadataOptions = {
    artistFilter?: string;
    mbidFilter?: string;
    missingOnly?: boolean;
    fetchMetadata?: boolean;
    fetchBio?: boolean;
    fetchArtwork?: boolean;
    fetchSpotifyArtwork?: boolean;
    fetchLinks?: boolean;
    refreshTopTracks?: boolean;
    refreshSingles?: boolean;
    fetchSimilarArtists?: boolean;
    fetchAlbumMetadata?: boolean;
};

export async function triggerMetadataScan(opts: MetadataOptions & { path?: string } = {} as any): Promise<void> {
    const path = opts.path;
    const res = await fetch('/api/library/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            type: 'metadata',
            path: path || null,
            artist_filter: opts.artistFilter || null,
            mbid_filter: opts.mbidFilter || null,
            missing_only: Boolean(opts.missingOnly),
            fetch_metadata: Boolean(opts.fetchMetadata),
            fetch_bio: Boolean(opts.fetchBio),
            fetch_artwork: Boolean(opts.fetchArtwork),
            fetch_spotify_artwork: Boolean(opts.fetchSpotifyArtwork),
            fetch_links: opts.fetchLinks,
            refresh_top_tracks: Boolean(opts.refreshTopTracks),
            refresh_singles: Boolean(opts.refreshSingles),
            fetch_similar_artists: Boolean(opts.fetchSimilarArtists),
            fetch_album_metadata: Boolean(opts.fetchAlbumMetadata),
        })
    });
    if (!res.ok) throw new Error('Failed to trigger metadata scan');
}

export async function cancelScan(): Promise<void> {
    const res = await fetch('/api/library/cancel', { method: 'POST' });
    if (!res.ok) throw new Error('Failed to cancel scan');
}

export async function triggerFullScan(opts: { force?: boolean; path?: string } & MetadataOptions): Promise<void> {
    const path = opts?.path;
    const res = await fetch('/api/library/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            type: 'full',
            force: Boolean(opts.force),
            path: path || null,
            artist_filter: opts.artistFilter || null,
            mbid_filter: opts.mbidFilter || null,
            missing_only: Boolean(opts.missingOnly),
            fetch_metadata: opts.fetchMetadata !== false,
            fetch_bio: opts.fetchBio !== false,
            fetch_artwork: opts.fetchArtwork !== false,
            fetch_spotify_artwork: Boolean(opts.fetchSpotifyArtwork),
            fetch_links: opts.fetchLinks !== undefined ? opts.fetchLinks : (opts.fetchMetadata !== false),
            refresh_top_tracks: Boolean(opts.refreshTopTracks),
            refresh_singles: Boolean(opts.refreshSingles),
            fetch_similar_artists: Boolean(opts.fetchSimilarArtists),
            fetch_album_metadata: Boolean(opts.fetchAlbumMetadata),
        })
    });
    if (!res.ok) throw new Error('Failed to trigger full scan');
}

export async function triggerPrune(): Promise<void> {
    const res = await fetch('/api/library/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'prune' })
    });
    if (!res.ok) throw new Error('Failed to prune library');
}

export async function triggerOptimize(): Promise<void> {
    const res = await fetch('/api/library/optimize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
    });
    if (!res.ok) throw new Error('Failed to optimize database');
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
    const res = await fetchFn('/api/history/albums');
    if (!res.ok) throw new Error('Failed to fetch recently played albums');
    return await res.json();
}

export async function fetchRecentlyPlayedArtists(fetchFn: any = fetch): Promise<Artist[]> {
    const res = await fetchFn('/api/history/artists');
    if (!res.ok) throw new Error('Failed to fetch recently played artists');
    return await res.json();
}

export async function fetchDiscoverArtists(fetchFn: any = fetch): Promise<Artist[]> {
    const res = await fetchFn('/api/home/discover-artists');
    if (!res.ok) throw new Error('Failed to fetch discover artists');
    return await res.json();
}

export interface MissingAlbum {
    mbid: string;
    title: string;
    release_date: string;
    primary_type: string;
    musicbrainz_url: string | null;
}

export async function fetchMissingAlbums(mbid: string, fetchFn: any = fetch): Promise<MissingAlbum[]> {
    const res = await fetchFn(`/api/artists/${mbid}/missing`);
    if (!res.ok) throw new Error('Failed to fetch missing albums');
    return await res.json();
}

export async function triggerMissingAlbumsScan(mbid?: string, artistName?: string, path?: string): Promise<void> {
    const res = await fetch('/api/library/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            type: 'missing_albums',
            artist_filter: artistName || null,
            mbid_filter: mbid || null,
            path: path || null,
        })
    });
    if (!res.ok) throw new Error('Failed to trigger missing albums scan');
}


export async function triggerPearlarrDownload(mbid: string): Promise<void> {
    const res = await fetch('/api/download/pearlarr', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mbid })
    });
    if (!res.ok) throw new Error('Failed to trigger Pearlarr download');
}

export async function signup(
    data: { username: string; email: string; password: string; display_name?: string },
): Promise<User> {
    const res = await fetch('/api/auth/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(data)
    });
    if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || 'Failed to sign up');
    }
    return await res.json();
}

export async function login(data: { username: string; password: string }): Promise<User> {
    const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(data)
    });
    if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || 'Invalid credentials');
    }
    return await res.json();
}

export async function logout(): Promise<void> {
    await fetch('/api/auth/logout', {
        method: 'POST',
        credentials: 'include'
    });
}

export async function fetchCurrentUser(fetchFn: any = fetch): Promise<User | null> {
    const res = await fetchFn('/api/auth/me', { credentials: 'include' });
    if (res.status === 401) return null;
    if (!res.ok) throw new Error('Failed to fetch current user');
    return await res.json();
}

export async function updateProfile(data: { email: string; display_name?: string }): Promise<User> {
    const res = await fetch('/api/auth/profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(data)
    });
    if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || 'Failed to update profile');
    }
    return await res.json();
}

export async function changePassword(data: { current_password: string; new_password: string }): Promise<void> {
    const res = await fetch('/api/auth/password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(data)
    });
    if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || 'Failed to update password');
    }
}

export type ArtistStats = {
    total: number;
    with_background: number;
    sources: Record<string, number>;
    link_stats: Record<string, number>;
};

export type AlbumStats = {
    total: number;
    with_artwork: number;
    link_stats: Record<string, number>;
};

export type MediaQualitySummary = {
    artist_stats: {
        all: ArtistStats;
        primary: ArtistStats;
    };
    album_stats: AlbumStats;
};

export type EntityItem = {
    name: string;
    mbid: string;
    image_url: string | null;
    artist_name?: string | null;
};

export async function fetchMediaQualityItems(
    category: string,
    filterType: string,
    filterValue?: string
): Promise<EntityItem[]> {
    const search = new URLSearchParams();
    search.append('category', category);
    search.append('filter_type', filterType);
    if (filterValue) search.append('filter_value', filterValue);

    const res = await fetch(`/api/media-quality/items?${search.toString()}`);
    if (!res.ok) throw new Error('Failed to fetch media quality items');
    return await res.json();
}

export async function fetchMediaQualitySummary(fetchFn: any = fetch): Promise<MediaQualitySummary> {
    const res = await fetchFn('/api/media-quality/summary');
    if (!res.ok) throw new Error('Failed to fetch media quality summary');
    return await res.json();
}

export interface Playlist {
    id: number;
    user_id: number;
    name: string;
    description?: string;
    is_public: boolean;
    updated_at: string;
    track_count: number;
    total_duration: number;
    thumbnails?: string[];
}

export interface PlaylistTrack {
    playlist_track_id: number;
    position: number;
    track_id: number;
    title: string;
    artist: string;
    album: string;
    duration_seconds: number;
    art_sha1: string | null;
    artist_mbid?: string | null;
    album_mbid?: string | null;
    mb_release_id?: string | null;
    path: string;
    codec?: string;
    sample_rate_hz?: number;
    bit_depth?: number;
    artists?: { name: string; mbid?: string }[];
}

export interface PlaylistDetail extends Playlist {
    tracks: PlaylistTrack[];
}

export async function fetchPlaylists(fetchFn: any = fetch): Promise<Playlist[]> {
    const res = await fetchFn('/api/playlists');
    if (!res.ok) throw new Error('Failed to fetch playlists');
    return await res.json();
}

export async function fetchArtistPlaylists(artistMbid: string, fetchFn: any = fetch): Promise<Playlist[]> {
    const res = await fetchFn(`/api/artists/${artistMbid}/playlists`);
    if (!res.ok) throw new Error('Failed to fetch artist playlists');
    return await res.json();
}

export async function createPlaylist(data: { name: string; description?: string; is_public?: boolean }): Promise<Playlist> {
    const res = await fetch('/api/playlists', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    if (!res.ok) throw new Error('Failed to create playlist');
    return await res.json();
}

export async function getPlaylist(id: string | number, fetchFn: any = fetch): Promise<PlaylistDetail> {
    const res = await fetchFn(`/api/playlists/${id}`);
    if (!res.ok) {
        if (res.status === 404) throw new Error('Playlist not found');
        throw new Error('Failed to fetch playlist');
    }
    return await res.json();
}

export async function updatePlaylist(id: number, data: { name?: string; description?: string; is_public?: boolean }): Promise<void> {
    const res = await fetch(`/api/playlists/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    if (!res.ok) throw new Error('Failed to update playlist');
}

export async function deletePlaylist(id: number): Promise<void> {
    const res = await fetch(`/api/playlists/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Failed to delete playlist');
}

export async function addTracksToPlaylist(playlistId: number, trackIds: number[]): Promise<void> {
    const res = await fetch(`/api/playlists/${playlistId}/tracks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ track_ids: trackIds })
    });
    if (!res.ok) throw new Error('Failed to add tracks');
}

export async function removeTrackFromPlaylist(playlistId: number, playlistTrackId: number): Promise<void> {
    const res = await fetch(`/api/playlists/${playlistId}/tracks/${playlistTrackId}`, {
        method: 'DELETE'
    });
    if (!res.ok) throw new Error('Failed to remove track');
}

export async function reorderPlaylist(playlistId: number, orderedPlaylistTrackIds: number[]): Promise<void> {
    const res = await fetch(`/api/playlists/${playlistId}/reorder`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ allowed_playlist_track_ids: orderedPlaylistTrackIds })
    });
    if (!res.ok) throw new Error('Failed to reorder playlist');
}

export interface ChartAlbum {
    position: number;
    title: string;
    artist: string;
    last_week?: string;
    peak?: string;
    weeks?: string;
    status: string;
    release_mbid?: string;
    release_group_mbid?: string;
    in_library: boolean;
    local_album_mbid?: string;
    local_title?: string;
    local_artist?: string;
    artist_mbid?: string;
    art_sha1?: string;
    musicbrainz_url?: string;
}

export async function fetchChart(fetchFn: any = fetch): Promise<ChartAlbum[]> {
    const res = await fetchFn('/api/charts');
    if (!res.ok) throw new Error('Failed to fetch chart');
    return await res.json();
}

export async function refreshChart(): Promise<void> {
    const res = await fetch('/api/charts/refresh', { method: 'POST' });
    if (!res.ok) throw new Error('Failed to refresh chart');
}

// Last.fm Integration
export interface LastfmStatus {
    connected: boolean;
    username: string | null;
    enabled: boolean;
    connected_at: string | null;
}

export async function getLastfmStatus(): Promise<LastfmStatus> {
    const res = await fetch('/api/lastfm/status', { credentials: 'include' });
    if (!res.ok) throw new Error('Failed to fetch Last.fm status');
    return await res.json();
}

export async function startLastfmAuth(): Promise<{ auth_url: string }> {
    const res = await fetch('/api/lastfm/auth/start', { credentials: 'include' });
    if (!res.ok) throw new Error('Failed to start Last.fm authentication');
    return await res.json();
}

export async function disconnectLastfm(): Promise<void> {
    const res = await fetch('/api/lastfm/disconnect', {
        method: 'POST',
        credentials: 'include'
    });
    if (!res.ok) throw new Error('Failed to disconnect Last.fm');
}

export async function toggleLastfm(enabled: boolean): Promise<void> {
    const res = await fetch('/api/lastfm/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ enabled })
    });
    if (!res.ok) throw new Error('Failed to toggle Last.fm scrobbling');
}

export interface SyncScrobblesResponse {
    fetched: number;
    matched: number;
    skipped: number;
    unmatched: number;
    logs: string[];
}

export async function syncLastfmScrobbles(opts: {
    fetch_new?: boolean;
    rematch_all?: boolean;
    limit?: number;
} = {}): Promise<SyncScrobblesResponse> {
    const res = await fetch('/api/lastfm/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
            fetch_new: opts.fetch_new !== false,
            rematch_all: opts.rematch_all || false,
            limit: opts.limit ?? null
        })
    });
    if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || 'Failed to sync scrobbles');
    }
    return await res.json();
}
