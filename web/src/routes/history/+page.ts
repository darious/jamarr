export async function load({ fetch, url }) {
    const scope = url.searchParams.get('scope') || 'mine';
    const source = url.searchParams.get('source') || 'all';
    const daysParam = parseInt(url.searchParams.get('days') || '7', 10);
    const days = Number.isFinite(daysParam) ? Math.max(1, Math.min(daysParam, 365)) : 7;

    const pageParam = parseInt(url.searchParams.get('page') || '1', 10);
    const page = Number.isFinite(pageParam) ? Math.max(1, pageParam) : 1;

    const [historyRes, statsRes] = await Promise.all([
        fetch(`/api/history/tracks?scope=${scope}&source=${source}&days=${days}&page=${page}`),
        fetch(`/api/history/stats?scope=${scope}&source=${source}&days=${days}`)
    ]);

    const history = historyRes.ok ? await historyRes.json() : [];
    const stats = statsRes.ok ? await statsRes.json() : { daily: [], artists: [], albums: [], tracks: [] };

    return { history, scope, source, days, page, stats };
}
