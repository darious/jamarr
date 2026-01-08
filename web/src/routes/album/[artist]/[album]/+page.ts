import { redirect } from '@sveltejs/kit';
import { fetchTracks } from '$api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, fetch }) => {
    const { artist, album } = params;

    try {
        // Legacy route: /album/[artist]/[album]
        // Fetch tracks to find the album MBID
        const tracks = await fetchTracks({ artist, album }, fetch);

        if (tracks.length > 0) {
            // Prefer release id when available
            const mbid = tracks[0].mb_release_id;

            if (mbid) {
                throw redirect(308, `/album/${mbid}`); // 308 Permanent Redirect for SEO/Caching
            }
        }
    } catch (e) {
        // If redirect was thrown, let it propagate
        if ((e as any)?.status === 308) throw e;
        console.warn(`Failed to resolve legacy album route: ${artist} - ${album}`, e);
    }

    // Fallback: This might 404 naturally if not handled, but strictly we should redirect.
    // If we can't find an MBID, we can't redirect to the new route.
    // We could error out or show a "Not Found" message.
    throw redirect(307, '/'); // Redirect to home if failed? Or let it 404? 
    // Better to let it 404 if not found? SvelteKit will 404 if load returns nothing?
    // Actually, we must return something or throw error.
};
