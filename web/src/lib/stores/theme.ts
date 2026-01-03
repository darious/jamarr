import { writable, derived, type Writable, type Readable } from 'svelte/store';
import { browser } from '$app/environment';

export type ThemeMode = 'dark' | 'light' | 'system';
export type AccentColor = 'pink' | 'cyan' | 'blue' | 'purple' | 'orange' | 'yellow';

const STORAGE_KEY_MODE = 'jamarr-theme-mode';
const STORAGE_KEY_ACCENT = 'jamarr-theme-accent';

// Initialize from localStorage or defaults
function getInitialMode(): ThemeMode {
    if (!browser) return 'dark';
    const stored = localStorage.getItem(STORAGE_KEY_MODE);
    if (stored === 'dark' || stored === 'light' || stored === 'system') {
        return stored;
    }
    return 'dark';
}

function getInitialAccent(): AccentColor {
    if (!browser) return 'pink';
    const stored = localStorage.getItem(STORAGE_KEY_ACCENT);
    if (stored === 'pink' || stored === 'cyan' || stored === 'blue' || stored === 'purple' || stored === 'orange' || stored === 'yellow') {
        return stored;
    }
    return 'pink';
}

// Theme stores
export const themeMode: Writable<ThemeMode> = writable(getInitialMode());
export const themeAccent: Writable<AccentColor> = writable(getInitialAccent());

// Derived store that resolves 'system' to actual light/dark
export const effectiveMode: Readable<'light' | 'dark'> = derived(
    themeMode,
    ($mode) => {
        if ($mode === 'system') {
            if (browser && window.matchMedia) {
                return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
            }
            return 'dark';
        }
        return $mode;
    }
);

// Subscribe to changes and persist to localStorage
if (browser) {
    themeMode.subscribe((mode) => {
        localStorage.setItem(STORAGE_KEY_MODE, mode);
    });

    themeAccent.subscribe((accent) => {
        localStorage.setItem(STORAGE_KEY_ACCENT, accent);
    });

    // Listen for system theme changes
    if (window.matchMedia) {
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
            // Trigger a re-evaluation of effectiveMode
            themeMode.update(m => m);
        });
    }
}

// Helper functions
export function setThemeMode(mode: ThemeMode): void {
    themeMode.set(mode);
}

export function setThemeAccent(accent: AccentColor): void {
    themeAccent.set(accent);
}

export function cycleAccent(): void {
    themeAccent.update(current => {
        const accents: AccentColor[] = ['pink', 'cyan', 'blue', 'purple', 'orange', 'yellow'];
        const currentIndex = accents.indexOf(current);
        const nextIndex = (currentIndex + 1) % accents.length;
        return accents[nextIndex];
    });
}
