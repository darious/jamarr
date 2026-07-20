import { redirect } from '@sveltejs/kit';
import {
    fetchWithAuth,
    fetchNewReleases,
    fetchRecentlyAddedAlbums,
    fetchRecentlyPlayedAlbums,
    fetchRecentlyPlayedArtists,
    fetchDiscoverArtists
} from '$lib/api';
import { initializeAuth } from '$lib/stores/auth';

export async function load({ fetch }) {
    // This is the app's landing route. Its data fetches are all authenticated,
    // so with a dead session they 401 and reject the load. That rejection
    // blanks the page (the layout's onMount login redirect never runs), so
    // establish auth here first and bounce to /login when the refresh cookie
    // is gone/rejected.
    const authed = await initializeAuth(fetch);
    if (!authed) {
        throw redirect(307, '/login');
    }

    const authFetch = (input: RequestInfo | URL, init?: RequestInit) =>
        fetchWithAuth(String(input), init, fetch);

    // Degrade gracefully: one failing section (a slow/erroring endpoint) must
    // not take down the whole home page. A blanket auth failure is already
    // handled above; here we only guard against individual section failures.
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
