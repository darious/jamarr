import { writable } from 'svelte/store';
import type { User } from '$lib/api';
import { fetchCurrentUser } from '$lib/api';
import { setThemeAccent, type AccentColor } from './theme';

export const currentUser = writable<User | null>(null);
export const isAuthChecked = writable(false);

// Map hex colors to accent names
const hexToAccent: Record<string, AccentColor> = {
    '#ff006e': 'pink',
    '#00d9ff': 'cyan',
    '#3b82f6': 'blue',
    '#a855f7': 'purple',
    '#f97316': 'orange',
    '#eab308': 'yellow',
};

// Helper function to apply accent color from user data
export function applyUserAccentColor(user: User | null) {
    if (user?.accent_color && hexToAccent[user.accent_color]) {
        setThemeAccent(hexToAccent[user.accent_color]);
    }
}

export async function hydrateUser(fetchFn: any = fetch): Promise<User | null> {
    try {
        const user = await fetchCurrentUser(fetchFn);
        currentUser.set(user);

        // Apply user's accent color preference if set
        applyUserAccentColor(user);

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
    applyUserAccentColor(user);
}

export function clearUser() {
    currentUser.set(null);
}
