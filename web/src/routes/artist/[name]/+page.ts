import type { Album, Artist } from '$api';
import { fetchAlbums, fetchArtists } from '$api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, fetch }) => {
  const name = params.name; // SvelteKit already decodes params
  // Fetch specific artist by name
  let artists: Artist[] = [];
  try {
    const fetchedArtists = await fetchArtists(fetch, { name });
    if (fetchedArtists.length > 0) {
      // The API performs normalized matching, so the first result is our artist
      artists = [fetchedArtists[0]];
    }
  } catch (e) {
    console.error('Failed to fetch artist details', e);
  }

  const artist = artists[0];
  const canonicalName = (artist?.name ?? name).trim();

  let albums: Album[] = [];
  try {
    albums = await fetchAlbums({ artist: canonicalName }, fetch);
  } catch (e) {
    console.error('Failed to fetch albums', e);
  }

  const similarArtists = (artist?.similar_artists || []).map((sim) => {
    return {
      name: sim.name,
      mbid: sim.mbid,
      art_id: sim.art_id,
      art_sha1: sim.art_sha1,
      image_url: sim.image_url,
      in_library: sim.in_library,
      external_url: sim.external_url
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
