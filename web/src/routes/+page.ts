import {
    fetchWithAuth,
    fetchNewReleases,
    fetchRecentlyAddedAlbums,
    fetchRecentlyPlayedAlbums,
    fetchRecentlyPlayedArtists,
    fetchDiscoverArtists
} from '$lib/api';

export async function load({ fetch }) {
    const authFetch = (input: RequestInfo | URL, init?: RequestInit) =>
        fetchWithAuth(String(input), init, fetch);
    const [
        newReleases,
        recentlyAddedAlbums,
        recentlyPlayedAlbums,
        recentlyPlayedArtists,
        discoverArtists
    ] = await Promise.all([
        fetchNewReleases(authFetch),
        fetchRecentlyAddedAlbums(authFetch),
        fetchRecentlyPlayedAlbums(authFetch),
        fetchRecentlyPlayedArtists(authFetch),
        fetchDiscoverArtists(authFetch)
    ]);

    return {
        newReleases,
        recentlyAddedAlbums,
        recentlyPlayedAlbums,
        recentlyPlayedArtists,
        discoverArtists
    };
}
