import type { Artist } from '$api';
import { fetchArtists } from '$api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => {
  const artists: Artist[] = await fetchArtists(fetch);
  return { artists };
};
