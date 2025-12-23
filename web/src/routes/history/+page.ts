export async function load({ fetch, url }) {
    const scope = url.searchParams.get('scope') || 'all';
    const daysParam = parseInt(url.searchParams.get('days') || '7', 10);
    const days = Number.isFinite(daysParam) ? Math.max(1, Math.min(daysParam, 365)) : 7;

    const [historyRes, statsRes] = await Promise.all([
        fetch(`/api/player/history?scope=${scope}`),
        fetch(`/api/player/history/stats?scope=${scope}&days=${days}`)
    ]);

    const history = historyRes.ok ? await historyRes.json() : [];
    const stats = statsRes.ok ? await statsRes.json() : { daily: [], artists: [], albums: [], tracks: [] };

    return { history, scope, days, stats };
}
