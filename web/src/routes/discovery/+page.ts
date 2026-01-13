import {
    fetchRecommendationSeeds,
    fetchRecommendationArtists,
    fetchRecommendationAlbums,
    fetchRecommendationTracks
} from '$lib/api';

export async function load({ fetch, url }) {
    const days = parseInt(url.searchParams.get('days') || '7');

    const [seeds, artists, albums, tracks] = await Promise.all([
        fetchRecommendationSeeds(days, fetch),
        fetchRecommendationArtists(days, fetch),
        fetchRecommendationAlbums(days, fetch),
        fetchRecommendationTracks(days, fetch)
    ]);

    return {
        seeds,
        artists,
        albums,
        tracks,
        days
    };
}
