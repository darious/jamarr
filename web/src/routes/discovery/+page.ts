import {
    fetchRecommendationSeeds,
    fetchRecommendationArtists,
    fetchRecommendationAlbums,
    fetchRecommendationTracks,
    fetchWithAuth
} from '$lib/api';

// Disable SSR for this page - we need JWT auth which only works client-side
export const ssr = false;

export async function load({ url, fetch }) {
    const days = parseInt(url.searchParams.get('days') || '7');

    const authFetch = (input: RequestInfo | URL, init?: RequestInit) => fetchWithAuth(String(input), init, fetch);

    const [seeds, artists, albums, tracks] = await Promise.all([
        fetchRecommendationSeeds(days, authFetch),
        fetchRecommendationArtists(days, authFetch),
        fetchRecommendationAlbums(days, authFetch),
        fetchRecommendationTracks(days, authFetch)
    ]);

    return {
        seeds,
        artists,
        albums,
        tracks,
        days
    };
}
