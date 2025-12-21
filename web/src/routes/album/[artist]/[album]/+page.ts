import type { Album, Track } from '$api';
import { fetchAlbums, fetchTracks } from '$api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, fetch }) => {
  const artist = decodeURIComponent(params.artist);
  const album = decodeURIComponent(params.album);

  const tracks = await fetchTracks({ album, artist }, fetch);
  const albumMbid = tracks?.[0]?.mb_release_group_id || tracks?.[0]?.mb_release_id;
  const albums = await fetchAlbums(albumMbid ? { albumMbid } : { artist }, fetch);

  const albumMeta: Album | undefined = albumMbid
    ? albums.find((a) => (a as any).mbid === albumMbid || a.mb_release_id === albumMbid || a.album.toLowerCase() === album.toLowerCase())
    : albums.find((a) => a.album.toLowerCase() === album.toLowerCase());

  return {
    artist,
    album,
    tracks,
    albumMeta
  };
};
