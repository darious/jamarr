import type { Album, Artist } from '$api';
import { fetchAlbums, fetchArtists } from '$api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, fetch }) => {
  const name = params.name; // SvelteKit already decodes params
  let artists: Artist[] = [];
  try {
    artists = await fetchArtists(fetch);
  } catch (e) {
    console.error('Failed to fetch artists list', e);
  }

  const normalize = (str: string) => str.replace(/[’']/g, "'").toLowerCase();
  const artist = artists.find((a) => normalize(a.name) === normalize(name));
  const canonicalName = (artist?.name ?? name).trim();

  let albums: Album[] = [];
  try {
    albums = await fetchAlbums({ artist: canonicalName }, fetch);
  } catch (e) {
    console.error('Failed to fetch albums', e);
  }

  const similarArtists = (artist?.similar_artists || []).map((sim) => {
    const libMatch = artists.find((a) => normalize(a.name) === normalize(sim));
    return { name: sim, art_id: libMatch?.art_id };
  });

  return {
    name,
    canonicalName,
    artist,
    albums,
    similarArtists
  };
};

export const ssr = false;
