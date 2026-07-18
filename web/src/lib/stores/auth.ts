import { writable } from 'svelte/store';

// Store access token in memory (not localStorage for security)
let accessToken: string | null = null;
let refreshTimer: ReturnType<typeof setInterval> | null = null;

// Writable store to track auth state
export const isAuthenticated = writable(false);

// Set once the server definitively rejects our refresh token (401/403).
// Refresh tokens rotate on every use, so replaying a dead one is interpreted
// server-side as theft and revokes every session for the user. Without this
// latch, background pollers re-trigger that replay forever (each fetchWithAuth
// call retries the refresh), logging the user out on all their devices.
export const sessionExpired = writable(false);
let sessionDead = false;

/**
 * Set the access token in memory
 */
export function setAccessToken(token: string) {
    accessToken = token;
    sessionDead = false;
    sessionExpired.set(false);
    isAuthenticated.set(true);
}

/**
 * Get the current access token
 */
export function getAccessToken(): string | null {
    return accessToken;
}

/**
 * Clear the access token from memory
 */
export function clearAccessToken() {
    accessToken = null;
    isAuthenticated.set(false);
    if (refreshTimer) {
        clearInterval(refreshTimer);
        refreshTimer = null;
    }
}

// Refresh lock to prevent multiple simultaneous refresh calls
let refreshPromise: Promise<boolean> | null = null;

/**
 * Refresh the access token using the refresh cookie
 * Returns true if successful, false otherwise
 * Uses a lock to prevent multiple simultaneous refresh attempts
 */
export async function refreshAccessToken(fetchImpl: typeof fetch = fetch): Promise<boolean> {
    // The server has rejected our refresh token; retrying can never succeed
    // and only re-triggers reuse detection. Only a fresh login resets this.
    if (sessionDead) {
        return false;
    }

    // If a refresh is already in progress, wait for it
    if (refreshPromise) {
        return refreshPromise;
    }

    // Create a new refresh promise
    refreshPromise = (async () => {
        try {
            const res = await fetchImpl('/api/auth/refresh', {
                method: 'POST',
                credentials: 'include', // Send refresh cookie
            });

            if (!res.ok) {
                if (res.status === 401 || res.status === 403) {
                    sessionDead = true;
                    sessionExpired.set(true);
                }
                clearAccessToken();
                return false;
            }

            const data = await res.json();
            if (data.access_token) {
                setAccessToken(data.access_token);
                return true;
            }

            return false;
        } catch (e) {
            console.error('[Auth] Failed to refresh access token:', e);
            clearAccessToken();
            return false;
        } finally {
            // Clear the lock after refresh completes
            refreshPromise = null;
        }
    })();

    return refreshPromise;
}

/**
 * Setup automatic token refresh
 * Refreshes token every 8 minutes (before 10min expiry)
 */
export function setupTokenRefresh() {
    // Clear any existing timer
    if (refreshTimer) {
        clearInterval(refreshTimer);
    }

    // Refresh every 8 minutes (480000ms)
    // This is 2 minutes before the 10-minute expiry
    refreshTimer = setInterval(async () => {
        const success = await refreshAccessToken();
        if (!success) {
            clearAccessToken();
        }
    }, 8 * 60 * 1000);
}

/**
 * Initialize auth on app load
 * Attempts to refresh token if refresh cookie exists
 */
export async function initializeAuth(fetchImpl: typeof fetch = fetch): Promise<boolean> {
    if (getAccessToken()) {
        setupTokenRefresh();
        return true;
    }
    const success = await refreshAccessToken(fetchImpl);
    if (success) {
        setupTokenRefresh();
    }
    return success;
}
