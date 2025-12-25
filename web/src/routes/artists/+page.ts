import type { Artist } from '$api';
import { fetchArtists } from '$api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => {
  // Fetch all artists (lightweight) - limit to 5000 for now to prevent browser crash if library is huge
  const artists: Artist[] = await fetchArtists(fetch, { limit: 10000 });
  return { artists };
};
