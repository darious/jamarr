import type { Album, Track } from '$api';
import { fetchAlbums, fetchTracks } from '$api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, fetch }) => {
  const albumMbid = params.id;

  // Fetch tracks by album MBID
  const tracks = await fetchTracks({ albumMbid }, fetch);

  // Fetch album metadata
  const albums = await fetchAlbums({ albumMbid }, fetch);

  const albumMeta: Album | undefined = albums.find(
    (a) => (a as any).mbid === albumMbid || a.mb_release_id === albumMbid || a.album_mbid === albumMbid
  );

  const artist = albumMeta?.artist_name || tracks?.[0]?.artist || 'Unknown Artist';
  const album = albumMeta?.album || tracks?.[0]?.album || 'Unknown Album';

  return {
    artist,
    album,
    tracks,
    albumMeta
  };
};
