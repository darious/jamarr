import {
    fetchNewReleases,
    fetchRecentlyAddedAlbums,
    fetchRecentlyPlayedAlbums,
    fetchRecentlyPlayedArtists,
    fetchDiscoverArtists
} from '$lib/api';

export async function load({ fetch }) {
    const [
        newReleases,
        recentlyAddedAlbums,
        recentlyPlayedAlbums,
        recentlyPlayedArtists,
        discoverArtists
    ] = await Promise.all([
        fetchNewReleases(fetch),
        fetchRecentlyAddedAlbums(fetch),
        fetchRecentlyPlayedAlbums(fetch),
        fetchRecentlyPlayedArtists(fetch),
        fetchDiscoverArtists(fetch)
    ]);

    return {
        newReleases,
        recentlyAddedAlbums,
        recentlyPlayedAlbums,
        recentlyPlayedArtists,
        discoverArtists
    };
}
