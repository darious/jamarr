import { writable } from 'svelte/store';
import type { User } from '$lib/api';
import { fetchCurrentUser } from '$lib/api';

export const currentUser = writable<User | null>(null);
export const isAuthChecked = writable(false);

export async function hydrateUser(fetchFn: any = fetch): Promise<User | null> {
    try {
        const user = await fetchCurrentUser(fetchFn);
        currentUser.set(user);
        return user;
    } catch (e) {
        // If server is restarting (network error/502), do not log out immediately.
        // If 401, fetchCurrentUser returns null (handled above) or throws if we changed it.
        // Actually fetchCurrentUser returns null on 401 if we check implementation.
        // Let's check fetchCurrentUser implementation in api/index.ts.
        // It throws if !res.ok unless 401.
        // So if we are here, it is likely a network error or 500.
        // Checking error message or type is hard in simple JS without Axios.
        // Assumption: If the server is restarting, we want to keep the "stale" user
        // and let the next polling or action fail gracefully or succeed when server returns.

        console.warn("Failed to hydrate user (likely network error or server down):", e);
        // Do NOT set currentUser to null effectively "logging out" the UI.
        // Keep potential stale user.
        return null;
    } finally {
        isAuthChecked.set(true);
    }
}

export function setUser(user: User | null) {
    currentUser.set(user);
}

export function clearUser() {
    currentUser.set(null);
}
