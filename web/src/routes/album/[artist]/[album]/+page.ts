import type { Album, Track } from '$api';
import { fetchAlbums, fetchTracks } from '$api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, fetch }) => {
  const artist = decodeURIComponent(params.artist);
  const album = decodeURIComponent(params.album);

  const [tracks, albums] = await Promise.all([
    fetchTracks({ album, artist }, fetch),
    fetchAlbums({ artist }, fetch)
  ]);

  const albumMeta: Album | undefined = albums.find((a) => a.album.toLowerCase() === album.toLowerCase());

  return {
    artist,
    album,
    tracks,
    albumMeta
  };
};
