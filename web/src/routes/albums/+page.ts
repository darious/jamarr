import type { Album } from '$api';
import { fetchAlbums } from '$api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => {
  const albums: Album[] = await fetchAlbums({}, fetch);
  return { albums };
};
