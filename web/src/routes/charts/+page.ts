import type { ChartAlbum } from '$api';
import { fetchChart } from '$api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => {
  const chart: ChartAlbum[] = await fetchChart(fetch);
  return { chart };
};
