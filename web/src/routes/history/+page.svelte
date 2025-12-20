<script lang="ts">
  import { setQueue } from '$stores/player';

  export let data: { 
    history: Array<{
      id: number;
      timestamp: string;
      client_ip: string;
      hostname: string;
      track: {
        id: number;
        title: string;
        artist: string;
        album: string;
        art_id: number | null;
        duration_seconds: number;
        codec: string | null;
        bit_depth: number | null;
        sample_rate_hz: number | null;
        date: string | null;
      }
    }>
  };

  function formatTime(seconds: number) {
    if (!seconds) return '—';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  }

  function formatTimestamp(timestamp: string) {
    const date = new Date(timestamp);
    return date.toLocaleString();
  }

  async function playTrack(entry: typeof data.history[0]) {
    // Create a minimal track object for playback
    const track = {
      id: entry.track.id,
      title: entry.track.title,
      artist: entry.track.artist,
      album: entry.track.album,
      art_id: entry.track.art_id,
      duration_seconds: entry.track.duration_seconds,
      codec: entry.track.codec,
      bit_depth: entry.track.bit_depth,
      sample_rate_hz: entry.track.sample_rate_hz,
      path: '', // Will be fetched by backend
      album_artist: null,
      track_no: null,
      disc_no: null,
      date: entry.track.date,
      bitrate: null
    };
    await setQueue([track], 0);
  }
</script>

<div class="fixed inset-0 z-0 overflow-hidden pointer-events-none">
  <div class="absolute inset-0 bg-gradient-to-b from-surface-900/50 via-surface-900/80 to-surface-900"></div>
</div>

<section class="relative z-10 mx-auto flex w-full max-w-[1700px] flex-col gap-8 px-8 py-10">
  <div class="space-y-2">
    <p class="pill w-max bg-white/10 text-white/70 backdrop-blur-md">Playback</p>
    <h1 class="text-4xl md:text-6xl font-bold tracking-tight">History</h1>
    <p class="text-white/60">Recently played tracks</p>
  </div>

  <div class="glass-panel divide-y divide-white/5">
    {#if data.history.length === 0}
      <div class="p-6 text-white/60">No playback history yet.</div>
    {:else}
      {#each data.history as entry}
        <div class="group flex items-center gap-4 px-4 py-3 hover:bg-white/5 transition-colors">
          <!-- Artwork -->
          <div class="h-14 w-14 flex-shrink-0 rounded bg-white/10 overflow-hidden relative">
            <img 
              src={entry.track.art_id ? `/art/${entry.track.art_id}` : '/assets/logo.png'} 
              alt="Art" 
              class="h-full w-full object-cover"
              on:error={(e) => { e.currentTarget.src = '/assets/logo.png'; }} 
            />
            <div class="absolute inset-0 bg-black/40 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
              <button class="text-white hover:scale-110 transition-transform" on:click={() => playTrack(entry)}>
                <svg class="h-6 w-6" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
              </button>
            </div>
          </div>

          <!-- Track Info -->
          <div class="flex-1 min-w-0">
            <p class="truncate text-sm font-semibold text-white/90 group-hover:text-white">{entry.track.title}</p>
            <div class="flex items-center gap-2 text-xs text-white/50 mt-0.5">
              <span>{entry.track.artist}</span>
              <span class="text-white/30">•</span>
              <span>{entry.track.album}</span>
              {#if entry.track.codec}
                <span class="text-white/30">•</span>
                <span class="uppercase">{entry.track.codec}</span>
              {/if}
              {#if entry.track.bit_depth && entry.track.sample_rate_hz}
                <span class="text-white/30">•</span>
                <span>{entry.track.bit_depth}bit / {entry.track.sample_rate_hz / 1000}kHz</span>
              {/if}
            </div>
          </div>

          <!-- Timestamp & Client Info -->
          <div class="flex flex-col items-end gap-1 text-xs text-white/60">
            <span class="font-medium">{formatTimestamp(entry.timestamp)}</span>
            <span class="text-white/40">{entry.client_ip}</span>
          </div>

          <!-- Duration -->
          <div class="w-14 text-right text-xs text-white/60 font-medium tabular-nums">
            {formatTime(entry.track.duration_seconds)}
          </div>
        </div>
      {/each}
    {/if}
  </div>
</section>
