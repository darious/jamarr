import type { Artist } from '$api';
import { fetchArtists, fetchArtistIndex } from '$api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, url }) => {
  const start = url.searchParams.get('start') || '#';

  // Parallel fetch: artists for current view + available letters index
  const [artists, index] = await Promise.all([
    fetchArtists(fetch, { startsWith: start }),
    fetchArtistIndex(fetch)
  ]);

  return { artists, start, index };
};
