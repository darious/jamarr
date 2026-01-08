import type { Album, Artist } from '$api';
import { fetchAlbums, fetchArtists } from '$api';
import type { PageLoad } from './$types';

import { redirect } from '@sveltejs/kit';

export const load: PageLoad = async ({ params, fetch }) => {
  const mbidOrName = params.id;

  // Simple UUID check (8-4-4-4-12 hex digits)
  const isUUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(mbidOrName);

  let mbid = mbidOrName;

  if (!isUUID) {
    // Assume it's a legacy name-based URL
    try {
      const fetchedArtists = await fetchArtists(fetch, { name: mbidOrName });
      if (fetchedArtists.length > 0 && fetchedArtists[0].mbid) {
        throw redirect(308, `/artist/${fetchedArtists[0].mbid}`);
      }
    } catch (e) {
      if ((e as any)?.status === 308) throw e;
      // Continue to 404/Empty if not found
    }
    // If we couldn't resolve name to MBID, we might fail downstream, but let it proceed to try? 
    // fetchArtists({ mbid: non-uuid }) will return empty.
  }

  // Fetch specific artist by MBID
  let artists: Artist[] = [];
  try {
    const fetchedArtists = await fetchArtists(fetch, { mbid });
    if (fetchedArtists.length > 0) {
      artists = [fetchedArtists[0]];
    }
  } catch (e) {
    console.error('Failed to fetch artist details', e);
  }

  const artist = artists[0];
  const name = artist?.name || 'Unknown Artist';
  const canonicalName = (artist?.name ?? name).trim();

  let albums: Album[] = [];
  try {
    // Now we can fetch albums specifically for this artist MBID
    albums = await fetchAlbums({ artistMbid: mbid }, fetch);
  } catch (e) {
    console.error('Failed to fetch albums', e);
  }

  const similarArtists = (artist?.similar_artists || []).map((sim) => {
    return {
      name: sim.name,
      mbid: sim.mbid,
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
