export async function load({ fetch, url }) {
    const scope = url.searchParams.get('scope') || 'mine';
    const source = url.searchParams.get('source') || 'all';
    const artistMbid = url.searchParams.get('artist_mbid') || '';
    const artistName = url.searchParams.get('artist_name') || '';
    const albumMbid = url.searchParams.get('album_mbid') || '';
    const albumName = url.searchParams.get('album_name') || '';
    const rangeParam = url.searchParams.get('range');
    const fromParam = url.searchParams.get('from');
    const toParam = url.searchParams.get('to');

    const formatDate = (date: Date) => {
        const year = date.getFullYear();
        const month = `${date.getMonth() + 1}`.padStart(2, '0');
        const day = `${date.getDate()}`.padStart(2, '0');
        return `${year}-${month}-${day}`;
    };

    const today = new Date();
    const defaultTo = formatDate(today);
    const defaultFrom = formatDate(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 6));

    const parseDate = (value: string) => new Date(`${value}T00:00:00`);
    const guessRange = (from: string, to: string) => {
        if (from === '1970-01-01') return 'all';
        const fromDate = parseDate(from);
        const toDate = parseDate(to);
        const todayDate = new Date(formatDate(today));
        const isToToday = toDate.getTime() === todayDate.getTime();
        if (!isToToday) return 'custom';
        const diffDays = Math.round((toDate.getTime() - fromDate.getTime()) / 86400000) + 1;
        if (diffDays === 7) return 'last7';
        if (diffDays === 30) return 'last30';
        if (diffDays === 90) return 'last90';
        if (diffDays === 180) return 'last180';
        if (diffDays === 365) return 'last365';
        return 'custom';
    };

    let dateFrom = fromParam;
    let dateTo = toParam;

    const requestedRange = rangeParam || (fromParam && toParam ? guessRange(fromParam, toParam) : 'last7');

    if (requestedRange !== 'custom') {
        switch (requestedRange) {
            case 'last30':
                dateFrom = formatDate(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 29));
                dateTo = defaultTo;
                break;
            case 'last90':
                dateFrom = formatDate(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 89));
                dateTo = defaultTo;
                break;
            case 'last180':
                dateFrom = formatDate(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 179));
                dateTo = defaultTo;
                break;
            case 'last365':
                dateFrom = formatDate(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 364));
                dateTo = defaultTo;
                break;
            case 'all':
                dateFrom = '1970-01-01';
                dateTo = defaultTo;
                break;
            case 'last7':
            default:
                dateFrom = defaultFrom;
                dateTo = defaultTo;
                break;
        }
    } else {
        dateFrom = dateFrom || defaultFrom;
        dateTo = dateTo || defaultTo;
    }
    const inferredRange = guessRange(dateFrom, dateTo);
    let range = requestedRange;
    if (requestedRange === 'custom') {
        range = 'custom';
    } else if (inferredRange !== requestedRange) {
        range = inferredRange;
    }

    const pageParam = parseInt(url.searchParams.get('page') || '1', 10);
    const page = Number.isFinite(pageParam) ? Math.max(1, pageParam) : 1;

    const artistQuery = artistMbid ? `&artist_mbid=${encodeURIComponent(artistMbid)}` : '';
    const albumQuery = albumMbid ? `&album_mbid=${encodeURIComponent(albumMbid)}` : '';
    const [historyRes, statsRes] = await Promise.all([
        fetch(`/api/history/tracks?scope=${scope}&source=${source}&from=${dateFrom}&to=${dateTo}&page=${page}${artistQuery}${albumQuery}`),
        fetch(`/api/history/stats?scope=${scope}&source=${source}&from=${dateFrom}&to=${dateTo}${artistQuery}${albumQuery}`)
    ]);

    const history = historyRes.ok ? await historyRes.json() : [];
    const stats = statsRes.ok ? await statsRes.json() : { daily: [], artists: [], albums: [], tracks: [] };

    return { history, scope, source, range, dateFrom, dateTo, page, stats, artistMbid, artistName, albumMbid, albumName };
}
