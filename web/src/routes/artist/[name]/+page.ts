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
    // sim is now an object with {name, mbid, image_url, art_id, art_sha1}
    // If sim already has library data, use it; otherwise try to find a match
    if (sim.mbid || sim.art_id) {
      return sim; // Already has library data from API
    }
    // Try to find in local artists list
    const libMatch = artists.find((a) => normalize(a.name) === normalize(sim.name));
    return {
      name: sim.name,
      mbid: libMatch?.mbid,
      art_id: libMatch?.art_id,
      art_sha1: libMatch?.art_sha1,
      background_art_id: libMatch?.background_art_id,
      background_sha1: libMatch?.background_sha1,
      image_url: libMatch?.image_url
    };
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
