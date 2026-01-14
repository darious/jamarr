import { fetchCurrentUser } from "$lib/api";

// We run entirely on the client (static build served by FastAPI)
export const prerender = false;

export async function load({ fetch, url }) {
    const pathname = url.pathname;
    const isAuthPage = pathname.startsWith("/login") || pathname.startsWith("/signup");

    // Don't try to fetch user on auth pages
    if (isAuthPage) {
        return { user: null };
    }

    // Don't redirect here - let client-side handle it
    // Just try to fetch user, return null if fails
    let user = null;
    try {
        user = await fetchCurrentUser(fetch);
    } catch (e) {
        user = null;
    }

    // Return user (or null), client will handle redirect
    return { user };
}
