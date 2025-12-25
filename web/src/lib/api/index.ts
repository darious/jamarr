export interface Artist {
    mbid?: string;
    name: string;
    image_url: string | null;
    art_id: number | null;
    art_sha1?: string | null;
    background_art_id?: number | null;
    background_sha1?: string | null;
    bio: string | null;
    similar_artists: {
        name: string;
        mbid?: string | null;
        image_url?: string | null;
        art_id?: number | null;
        art_sha1?: string | null;
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
    }[];
    sort_name: string;
    primary_album_count?: number;
    appears_on_album_count?: number;
    homepage: string | null;
    spotify_url: string | null;
    wikipedia_url: string | null;
    qobuz_url: string | null;
    musicbrainz_url: string | null;
    tidal_url?: string | null;
    lastfm_url?: string | null;
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
    mb_release_id?: string | null;
    mb_release_group_id?: string | null;
    popularity?: number;
}

export interface User {
    id: number;
    username: string;
    email: string;
    display_name: string;
    created_at?: string | null;
    last_login?: string | null;
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
    // Support album MBID query
    if ((params as any).albumMbid) {
        const q = params.artist ? '&' : '?';
        url += `${q}album_mbid=${encodeURIComponent((params as any).albumMbid)}`;
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
};

export async function triggerMetadataScan(opts: MetadataOptions = {}): Promise<void> {
    const res = await fetch('/api/library/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            type: 'metadata',
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
        })
    });
    if (!res.ok) throw new Error('Failed to trigger metadata scan');
}

export async function cancelScan(): Promise<void> {
    const res = await fetch('/api/library/cancel', { method: 'POST' });
    if (!res.ok) throw new Error('Failed to cancel scan');
}

export async function triggerFullScan(opts: { force?: boolean; path?: string } & MetadataOptions = {}): Promise<void> {
    const res = await fetch('/api/library/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            type: 'full',
            force: Boolean(opts.force),
            path: opts.path || null,
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

export interface MissingAlbum {
    mbid: string;
    title: string;
    release_date: string;
    primary_type: string;
    image_url: string | null;
    musicbrainz_url: string | null;
    tidal_url: string | null;
    qobuz_url: string | null;
}

export async function fetchMissingAlbums(mbid: string, fetchFn: any = fetch): Promise<MissingAlbum[]> {
    const res = await fetchFn(`/api/artists/${mbid}/missing`);
    if (!res.ok) throw new Error('Failed to fetch missing albums');
    return await res.json();
}

export async function triggerMissingAlbumsScan(mbid?: string, artistName?: string): Promise<void> {
    const params = new URLSearchParams();
    if (mbid) params.append('mbid', mbid);
    if (artistName) params.append('artist', artistName);

    const res = await fetch(`/api/scan/missing?${params.toString()}`, {
        method: 'POST',
    });
    if (!res.ok) throw new Error('Failed to trigger missing albums scan');
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

export type MediaQualityIssue = {
    id: number;
    entity_type: string;
    entity_id: string | null;
    issue_code: string;
    details: Record<string, any>;
    created_at: number | null;
    resolved_at: number | null;
    context?: Record<string, any> | null;
};

export type MediaQualitySummary = {
    issue_counts: Record<string, number>;
    pending_artwork: number;
    artwork_with_issues: number;
};

export async function runMediaQualityCheck(force = false): Promise<{ status: string; stats: any }> {
    const res = await fetch('/api/media-quality/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force }),
    });
    if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || 'Failed to run media quality checks');
    }
    return await res.json();
}

export async function fetchMediaQualityIssues(
    params: { entityType?: string; issueCode?: string; includeResolved?: boolean; limit?: number } = {},
    fetchFn: any = fetch,
): Promise<MediaQualityIssue[]> {
    const search = new URLSearchParams();
    if (params.entityType) search.append('entity_type', params.entityType);
    if (params.issueCode) search.append('issue_code', params.issueCode);
    if (params.includeResolved) search.append('include_resolved', 'true');
    if (params.limit) search.append('limit', String(params.limit));

    const res = await fetchFn(`/api/media-quality/issues?${search.toString()}`);
    if (!res.ok) throw new Error('Failed to fetch media quality issues');
    const data = await res.json();
    return data.issues || [];
}

export async function fetchMediaQualitySummary(fetchFn: any = fetch): Promise<MediaQualitySummary> {
    const res = await fetchFn('/api/media-quality/summary');
    if (!res.ok) throw new Error('Failed to fetch media quality summary');
    return await res.json();
}
