<script lang="ts">
  import { setQueue } from "$stores/player";
  import { goto } from "$app/navigation";

  export let data: {
    history: Array<{
      id: number;
      timestamp: string | number;
      client_ip: string;
      client_id: string | null;
      user?: {
        id: number | null;
        username: string | null;
        display_name: string | null;
        email: string | null;
      } | null;
      track: {
        id: number;
        title: string;
        artist: string;
        album: string;
        art_id: number | null;
        art_sha1: string | null;
        duration_seconds: number;
        codec: string | null;
        bit_depth: number | null;
        sample_rate_hz: number | null;
        date: string | null;
      };
    }>;
    scope: string;
    days: number;
    stats: {
      daily: { day: string; plays: number }[];
      artists: {
        artist: string;
        art_id: number | null;
        art_sha1: string | null;
        plays: number;
      }[];
      albums: {
        album: string;
        artist: string;
        art_id: number | null;
        art_sha1: string | null;
        plays: number;
      }[];
      tracks: {
        id: number;
        title: string;
        artist: string;
        album: string;
        art_id: number | null;
        art_sha1: string | null;
        plays: number;
      }[];
    };
  };

  let scope = data.scope || "all";
  let days = data.days || 7;
  $: dailyMax = Math.max(
    ...(data.stats.daily?.map((d) => Number(d.plays) || 0) || [1]),
    1,
  );

  function formatTime(seconds: number) {
    if (!seconds) return "—";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
  }

  function formatTimestamp(timestamp: string | number) {
    const date = new Date(
      typeof timestamp === "number" ? timestamp * 1000 : timestamp,
    );
    return date.toLocaleString();
  }

  function handleImageError(e: Event) {
    const img = e.currentTarget as HTMLImageElement;
    img.src = "/assets/logo.png";
  }

  async function playTrack(entry: (typeof data.history)[0]) {
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
      path: "", // Will be fetched by backend
      album_artist: null,
      track_no: null,
      disc_no: null,
      date: entry.track.date,
      bitrate: null,
    };
    await setQueue([track], 0);
  }

  function switchScope(nextScope: string) {
    if (scope === nextScope) return;
    scope = nextScope;
    goto(`/history?scope=${scope}&days=${days}`, { replaceState: true });
  }

  function updateDays(event: Event) {
    const val = parseInt((event.currentTarget as HTMLInputElement).value, 10);
    if (!Number.isFinite(val)) return;
    days = Math.max(1, Math.min(val, 365));
    goto(`/history?scope=${scope}&days=${days}`, { replaceState: true });
  }
</script>

<div class="fixed inset-0 z-0 overflow-hidden pointer-events-none">
  <div
    class="absolute inset-0 bg-gradient-to-b from-surface-900/50 via-surface-900/80 to-surface-900"
  ></div>
</div>

<section
  class="relative z-10 mx-auto flex w-full max-w-[1700px] flex-col gap-8 px-8 py-10"
>
  <div
    class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between"
  >
    <div class="space-y-2">
      <p class="pill w-max bg-white/10 text-white/70 backdrop-blur-md">
        Playback
      </p>
      <h1 class="text-4xl md:text-6xl font-bold tracking-tight">History</h1>
      <p class="text-white/60">Recently played tracks</p>
    </div>
    <div class="flex items-center gap-2">
      <button
        class={`btn btn-sm normal-case border border-white/10 bg-white/5 text-white hover:bg-white/10 ${scope === "mine" ? "bg-primary text-white border-primary" : ""}`}
        on:click={() => switchScope("mine")}
      >
        My History
      </button>
      <button
        class={`btn btn-sm normal-case border border-white/10 bg-white/5 text-white hover:bg-white/10 ${scope === "all" ? "bg-primary text-white border-primary" : ""}`}
        on:click={() => switchScope("all")}
      >
        All History
      </button>
      <div class="flex items-center gap-2 text-sm text-white/70">
        <label for="days" class="hidden md:inline">Days</label>
        <input
          id="days"
          type="number"
          min="1"
          max="365"
          class="input input-sm input-bordered w-20 bg-white/5 text-white"
          bind:value={days}
          on:change={updateDays}
        />
      </div>
    </div>
  </div>

  <!-- Stats -->
  <div class="glass-panel space-y-8 p-6">
    <div class="flex flex-col gap-3">
      <div class="flex items-center justify-between">
        <div>
          <p class="text-sm text-white/60">Playback trend</p>
          <h2 class="text-xl font-semibold text-white">
            Plays per day (last {days} days)
          </h2>
        </div>
      </div>
      {#if data.stats.daily.length === 0}
        <p class="text-white/60 text-sm">No data.</p>
      {:else}
        {#key `${scope}-${days}-daily`}
          <div class="space-y-2">
            {#each data.stats.daily as dayStat (dayStat.day)}
              <div class="flex items-center gap-3 text-sm text-white/80">
                <span class="w-28 text-white/60 font-mono">{dayStat.day}</span>
                <div
                  class="flex-1 h-2.5 rounded-full bg-white/5 overflow-hidden border border-white/5"
                >
                  <div
                    class="h-full rounded-full bg-gradient-to-r from-primary/70 via-primary to-white/80 transition-[width] duration-500"
                    style:width="{(dayStat.plays / dailyMax) * 100}%"
                  ></div>
                </div>
                <span class="w-12 text-right tabular-nums text-white/70">
                  {dayStat.plays}
                </span>
              </div>
            {/each}
          </div>
        {/key}
      {/if}
    </div>

    <div class="grid md:grid-cols-3 gap-6">
      <div
        class="rounded-2xl border border-white/5 bg-white/5 p-4 backdrop-blur"
      >
        <h3 class="text-md font-semibold mb-3">Top Artists</h3>
        {#if data.stats.artists.length === 0}
          <p class="text-white/60 text-sm">No data.</p>
        {:else}
          <div class="space-y-2 text-sm">
            {#each data.stats.artists as artist (artist.artist)}
              <div class="flex items-center justify-between gap-3">
                <div class="flex items-center gap-3 min-w-0">
                  <div
                    class="h-10 w-10 rounded bg-white/5 overflow-hidden flex-shrink-0"
                  >
                    <img
                      src={artist.art_sha1
                        ? `/api/art/file/${artist.art_sha1}?max_size=50`
                        : "/assets/logo.png"}
                      alt={artist.artist}
                      class="h-full w-full object-cover"
                    />
                  </div>
                  <a
                    class="hover:text-white hover:underline truncate"
                    href={`/artist/${encodeURIComponent(artist.artist)}`}
                  >
                    {artist.artist}
                  </a>
                </div>
                <span class="text-white/60 tabular-nums">{artist.plays}</span>
              </div>
            {/each}
          </div>
        {/if}
      </div>
      <div
        class="rounded-2xl border border-white/5 bg-white/5 p-4 backdrop-blur"
      >
        <h3 class="text-md font-semibold mb-3">Top Albums</h3>
        {#if data.stats.albums.length === 0}
          <p class="text-white/60 text-sm">No data.</p>
        {:else}
          <div class="space-y-2 text-sm">
            {#each data.stats.albums as album (album.album + album.artist)}
              <div class="flex items-center justify-between gap-3">
                <div class="flex items-center gap-3 min-w-0">
                  <div
                    class="h-10 w-10 rounded bg-white/5 overflow-hidden flex-shrink-0"
                  >
                    <img
                      src={album.art_sha1
                        ? `/api/art/file/${album.art_sha1}?max_size=50`
                        : "/assets/logo.png"}
                      alt={album.album}
                      class="h-full w-full object-cover"
                    />
                  </div>
                  <div class="min-w-0">
                    <a
                      class="hover:text-white hover:underline block truncate"
                      href={`/album/${encodeURIComponent(album.artist)}/${encodeURIComponent(album.album)}`}
                    >
                      {album.album}
                    </a>
                    <a
                      class="text-white/60 hover:text-white hover:underline text-xs"
                      href={`/artist/${encodeURIComponent(album.artist)}`}
                    >
                      {album.artist}
                    </a>
                  </div>
                </div>
                <span class="text-white/60 tabular-nums">{album.plays}</span>
              </div>
            {/each}
          </div>
        {/if}
      </div>
      <div
        class="rounded-2xl border border-white/5 bg-white/5 p-4 backdrop-blur"
      >
        <h3 class="text-md font-semibold mb-3">Top Tracks</h3>
        {#if data.stats.tracks.length === 0}
          <p class="text-white/60 text-sm">No data.</p>
        {:else}
          <div class="space-y-2 text-sm">
            {#each data.stats.tracks as track (track.id)}
              <div class="flex items-center justify-between gap-3">
                <div class="flex items-center gap-3 min-w-0">
                  <div
                    class="h-10 w-10 rounded bg-white/5 overflow-hidden flex-shrink-0"
                  >
                    <img
                      src={track.art_sha1
                        ? `/api/art/file/${track.art_sha1}?max_size=50`
                        : "/assets/logo.png"}
                      alt={track.title}
                      class="h-full w-full object-cover"
                    />
                  </div>
                  <div class="min-w-0">
                    <a
                      class="hover:text-white hover:underline block truncate"
                      href={`/album/${encodeURIComponent(track.artist)}/${encodeURIComponent(track.album)}`}
                    >
                      {track.title}
                    </a>
                    <a
                      class="text-white/60 hover:text-white hover:underline text-xs"
                      href={`/artist/${encodeURIComponent(track.artist)}`}
                    >
                      {track.artist}
                    </a>
                  </div>
                </div>
                <span class="text-white/60 tabular-nums">{track.plays}</span>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    </div>
  </div>

  <div class="glass-panel divide-y divide-white/5">
    {#if data.history.length === 0}
      <div class="p-6 text-white/60">No playback history yet.</div>
    {:else}
      {#each data.history as entry}
        <div
          class="group flex items-center gap-4 px-4 py-3 hover:bg-white/5 transition-colors"
        >
          <!-- Artwork -->
          <div
            class="h-14 w-14 flex-shrink-0 rounded bg-white/10 overflow-hidden relative"
          >
            <img
              src={entry.track.art_sha1
                ? `/api/art/file/${entry.track.art_sha1}?max_size=60`
                : "/assets/logo.png"}
              alt="Art"
              class="h-full w-full object-cover"
              on:error={handleImageError}
            />
            <div
              class="absolute inset-0 bg-black/40 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
            >
              <button
                class="text-white hover:scale-110 transition-transform"
                on:click={() => playTrack(entry)}
              >
                <svg class="h-6 w-6" fill="currentColor" viewBox="0 0 24 24"
                  ><path d="M8 5v14l11-7z" /></svg
                >
              </button>
            </div>
          </div>

          <!-- Track Info -->
          <div class="flex-1 min-w-0">
            <p
              class="truncate text-sm font-semibold text-white/90 group-hover:text-white"
            >
              {entry.track.title}
            </p>
            <div
              class="flex items-center gap-2 text-xs text-white/50 mt-0.5 flex-wrap"
            >
              <a
                href={`/artist/${encodeURIComponent(entry.track.artist)}`}
                class="hover:text-white hover:underline"
                on:click|stopPropagation
              >
                {entry.track.artist}
              </a>
              {#if entry.track.album}
                <span class="text-white/30">•</span>
                <a
                  href={`/album/${encodeURIComponent(entry.track.artist)}/${encodeURIComponent(entry.track.album)}`}
                  class="hover:text-white hover:underline"
                  on:click|stopPropagation
                >
                  {entry.track.album}
                </a>
              {/if}
              {#if entry.track.codec}
                <span class="text-white/30">•</span>
                <span class="uppercase">{entry.track.codec}</span>
              {/if}
              {#if entry.track.bit_depth && entry.track.sample_rate_hz}
                <span class="text-white/30">•</span>
                <span>
                  {entry.track.bit_depth}bit / {(
                    entry.track.sample_rate_hz / 1000
                  ).toFixed(1)}kHz
                </span>
              {/if}
            </div>
          </div>

          <!-- Timestamp & Client Info -->
          <div class="flex items-center gap-4">
            <div class="flex flex-col items-end gap-1 text-xs text-white/60">
              <span class="font-medium">{formatTimestamp(entry.timestamp)}</span
              >
              <div class="flex flex-col items-end text-[11px] text-white/50">
                {#if entry.user}
                  <span>{entry.user.display_name || entry.user.username}</span>
                {:else}
                  <span>Unknown user</span>
                {/if}
                <span>{entry.client_ip}</span>
                <span class="text-[10px] text-white/30">
                  {entry.client_id || "Unknown Client"}
                </span>
              </div>
            </div>

            <!-- Duration -->
            <div
              class="w-14 text-right text-xs text-white/60 font-medium tabular-nums"
            >
              {formatTime(entry.track.duration_seconds)}
            </div>
          </div>
        </div>
      {/each}
    {/if}
  </div>
</section>
