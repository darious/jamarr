import { toStore } from 'svelte/store';
import { page as pageState } from '$app/state';

// SvelteKit 3 dropped `$app/stores`. `$app/state` only reacts inside runes, so
// legacy components (`$:`) read it through this store instead. Touch each field
// in the getter so the store tracks navigation changes.
export const page = toStore(() => ({
    url: pageState.url,
    params: pageState.params,
    status: pageState.status,
    error: pageState.error
}));
