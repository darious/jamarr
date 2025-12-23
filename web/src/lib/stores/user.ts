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
        currentUser.set(null);
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
