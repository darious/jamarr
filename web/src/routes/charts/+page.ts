import type { ChartAlbum } from '$api';
import { fetchChart, fetchWithAuth } from '$api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => {
  const authFetch = (input: RequestInfo | URL, init?: RequestInit) =>
    fetchWithAuth(String(input), init, fetch);
  const chart: ChartAlbum[] = await fetchChart(authFetch);
  return { chart };
};
