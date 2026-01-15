import type { Album, Track } from '$api';
import { fetchAlbums, fetchTracks, fetchWithAuth } from '$api';
import type { PageLoad } from './$types';

export const ssr = false;

export const load: PageLoad = async ({ params, fetch }) => {
  const albumMbid = params.id;
  const authFetch = (input: RequestInfo | URL, init?: RequestInit) =>
    fetchWithAuth(String(input), init, fetch);

  // Fetch tracks by album MBID
  const tracks = await fetchTracks({ albumMbid }, authFetch);

  // Fetch album metadata
  const albums = await fetchAlbums({ albumMbid }, authFetch);

  const albumMeta: Album | undefined = albums.find(
    (a) => (a as any).mbid === albumMbid || a.mb_release_id === albumMbid
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
