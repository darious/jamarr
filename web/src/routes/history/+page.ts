export async function load({ fetch }) {
    const res = await fetch('/api/player/history');
    if (!res.ok) {
        return { history: [] };
    }
    const history = await res.json();
    return { history };
}
