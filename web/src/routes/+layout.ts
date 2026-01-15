// We run entirely on the client (static build served by FastAPI)
export const prerender = false;
export const ssr = false;

export async function load({ fetch, url }) {
    return { user: null };
}
