import type { Artist } from '$api';
import { fetchArtists, fetchArtistIndex, fetchWithAuth } from '$api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, url }) => {
  const start = url.searchParams.get('start') || '#';
  const favoriteOnly = url.searchParams.get('favorite_only') === '1';
  const authFetch = (input: RequestInfo | URL, init?: RequestInit) =>
    fetchWithAuth(String(input), init, fetch);

  // Parallel fetch: artists for current view + available letters index
  const [artists, index] = await Promise.all([
    fetchArtists(authFetch, favoriteOnly ? { favoriteOnly: true } : { startsWith: start }),
    fetchArtistIndex(authFetch)
  ]);

  return { artists, start, index, favoriteOnly };
};
