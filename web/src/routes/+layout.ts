import { fetchCurrentUser } from "$lib/api";
import { redirect } from "@sveltejs/kit";

// We run entirely on the client (static build served by FastAPI)
export const prerender = false;

export async function load({ fetch, url }) {
    const pathname = url.pathname;
    const isAuthPage = pathname.startsWith("/login") || pathname.startsWith("/signup");

    let user = null;
    try {
        user = await fetchCurrentUser(fetch);
    } catch (e) {
        user = null;
    }

    if (!user && !isAuthPage) {
        throw redirect(302, "/login");
    }

    return { user };
}
