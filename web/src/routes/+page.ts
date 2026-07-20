import {
    fetchWithAuth,
    fetchNewReleases,
    fetchRecentlyAddedAlbums,
    fetchRecentlyPlayedAlbums,
    fetchRecentlyPlayedArtists,
    fetchDiscoverArtists
} from '$lib/api';

// Client-only (JWT auth works client-side). Auth redirects are owned by the
// root +layout.svelte (initializeAppShell -> /login). This load must NOT throw
// or redirect: a throw blanks the page, and a second redirect authority races
// the layout/login and produces a redirect loop. So every section degrades to
// an empty list on failure and the layout handles a dead session.
export const ssr = false;

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
        fetchNewReleases(authFetch).catch(() => []),
        fetchRecentlyAddedAlbums(authFetch).catch(() => []),
        fetchRecentlyPlayedAlbums(authFetch).catch(() => []),
        fetchRecentlyPlayedArtists(authFetch).catch(() => []),
        fetchDiscoverArtists(authFetch).catch(() => [])
    ]);

    return {
        newReleases,
        recentlyAddedAlbums,
        recentlyPlayedAlbums,
        recentlyPlayedArtists,
        discoverArtists
    };
}
