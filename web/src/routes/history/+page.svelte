<script lang="ts">
  import { setQueue } from "$stores/player";
  import { goto, invalidateAll } from "$app/navigation";
  import { onMount } from "svelte";
  import { currentUser } from "$lib/stores/user";
  import IconButton from "$lib/components/IconButton.svelte";
  import TabButton from "$lib/components/TabButton.svelte";
  import HistoryChart from "$lib/components/HistoryChart.svelte";
  import { getArtUrl } from "$lib/api";
  let showScopeMenu = false;
  let showSourceMenu = false;
  let showRangeMenu = false;
  let scopeMenuContainer: HTMLElement | null = null;
  let sourceMenuContainer: HTMLElement | null = null;
  let rangeMenuContainer: HTMLElement | null = null;
  const rangeOptions = [
    { value: "last7", label: "Last 7 days" },
    { value: "last30", label: "Last 30 days" },
    { value: "last90", label: "Last 90 days" },
    { value: "last180", label: "Last 180 days" },
    { value: "last365", label: "Last 365 days" },
    { value: "all", label: "All time" },
    { value: "custom", label: "Custom" },
  ];

  export let data: {
    history: Array<{
      id: number;
      timestamp: string | number;
      client_ip: string;
      client_id: string | null;
      source?: string;
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
        art_sha1: string | null;
        mb_release_id?: string | null;
        duration_seconds: number;
        codec: string | null;
        bit_depth: number | null;
        sample_rate_hz: number | null;
        date: string | null;
      };
    }>;
    scope: string;
    source: string;
    range: string;
    dateFrom: string;
    dateTo: string;
    page: number;
    stats: {
      daily: { day: string; plays: number }[];
      artists: {
        artist: string;
        art_sha1: string | null;
        plays: number;
      }[];
      albums: {
        album: string;
        artist: string;
        art_sha1: string | null;
        mb_release_id?: string | null;
        plays: number;
      }[];
      tracks: {
        id: number;
        title: string;
        artist: string;
        album: string;
        art_sha1: string | null;
        mb_release_id?: string | null;
        plays: number;
      }[];
    };
    artistMbid?: string;
    artistName?: string;
    albumMbid?: string;
    albumName?: string;
    trackId?: string;
    trackName?: string;
  };

  let scope = data.scope || "mine";
  let source = data.source || "all";
  let range = data.range || "last7";
  let dateFrom = data.dateFrom;
  let dateTo = data.dateTo;
  let pendingRange = range;
  let pendingFrom = dateFrom;
  let pendingTo = dateTo;
  let restoredFilters = false;
  let artistMbid = data.artistMbid || "";
  let artistName = data.artistName || "";
  let albumMbid = data.albumMbid || "";
  let albumName = data.albumName || "";
  let trackId = data.trackId || "";
  let trackName = data.trackName || "";
  $: page = data.page || 1;
  $: if (data) {
    scope = data.scope || "mine";
    source = data.source || "all";
    range = data.range || "last7";
    dateFrom = data.dateFrom;
    dateTo = data.dateTo;
    artistMbid = data.artistMbid || "";
    artistName = data.artistName || "";
    albumMbid = data.albumMbid || "";
    albumName = data.albumName || "";
    trackId = data.trackId || "";
    trackName = data.trackName || "";
    if (!showRangeMenu) {
      pendingRange = range;
      pendingFrom = dateFrom;
      pendingTo = dateTo;
    }
  }
  $: hasNextPage = data.history.length === 20; // Assuming limit is 20
  $: dailyMax = Math.max(
    ...(data.stats.daily?.map((d) => Number(d.plays) || 0) || [1]),
    1,
  );

  function getRangeDaysCount() {
    if (!dateFrom || !dateTo) return 0;
    const fromDate = new Date(`${dateFrom}T00:00:00`);
    const toDate = new Date(`${dateTo}T00:00:00`);
    if (Number.isNaN(fromDate.getTime()) || Number.isNaN(toDate.getTime())) {
      return 0;
    }
    return Math.round((toDate.getTime() - fromDate.getTime()) / 86400000) + 1;
  }

  function formatMonthLabel(value: string) {
    const [year, month] = value.split("-");
    const monthIndex = Number(month) - 1;
    const names = [
      "Jan",
      "Feb",
      "Mar",
      "Apr",
      "May",
      "Jun",
      "Jul",
      "Aug",
      "Sep",
      "Oct",
      "Nov",
      "Dec",
    ];
    const name = names[monthIndex] || "???";
    return `${name} ${year}`;
  }

  function getChartRows(
    dailyStats: typeof data.stats.daily,
    currentFrom: string,
    currentTo: string,
  ) {
    const statsMap = new Map(
      (dailyStats || []).map((d) => [d.day, Number(d.plays)]),
    );
    const rangeDays = getRangeDaysCount();

    if (rangeDays > 365) {
      // Group by year for long ranges (> 365 days)
      const grouped = new Map<string, number>();
      for (const row of dailyStats || []) {
        const year = row.day.slice(0, 4);
        grouped.set(year, (grouped.get(year) || 0) + Number(row.plays));
      }
      return Array.from(grouped.entries())
        .sort((a, b) => (a[0] < b[0] ? 1 : -1))
        .map(([year, plays]) => ({
          label: year,
          plays,
        }));
    }

    if (rangeDays > 60) {
      // Group by month for medium ranges (> 60 days)
      const grouped = new Map<string, number>();
      for (const row of dailyStats || []) {
        const month = row.day.slice(0, 7);
        grouped.set(month, (grouped.get(month) || 0) + Number(row.plays));
      }
      return Array.from(grouped.entries())
        .sort((a, b) => (a[0] < b[0] ? 1 : -1))
        .map(([month, plays]) => ({
          label: formatMonthLabel(month),
          plays,
        }));
    }

    // Daily view: backfill missing days
    const rows = [];
    if (currentFrom && currentTo) {
      const [y1, m1, d1] = currentFrom.split("-").map(Number);
      const [y2, m2, d2] = currentTo.split("-").map(Number);
      const current = new Date(y1, m1 - 1, d1);
      const end = new Date(y2, m2 - 1, d2);

      // Safety break to prevent infinite loops
      let safety = 0;
      while (current <= end && safety < 1000) {
        const y = current.getFullYear();
        const m = String(current.getMonth() + 1).padStart(2, "0");
        const d = String(current.getDate()).padStart(2, "0");
        const dayStr = `${y}-${m}-${d}`;

        rows.push({
          label: dayStr,
          plays: statsMap.get(dayStr) || 0,
        });

        current.setDate(current.getDate() + 1);
        safety++;
      }
      return rows.reverse();
    }

    // Fallback
    return (dailyStats || []).map((row) => ({
      label: row.day,
      plays: Number(row.plays),
    }));
  }

  $: chartRows = getChartRows(data.stats.daily, dateFrom, dateTo);

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
    const year = date.getFullYear();
    const month = `${date.getMonth() + 1}`.padStart(2, "0");
    const day = `${date.getDate()}`.padStart(2, "0");
    const hours = `${date.getHours()}`.padStart(2, "0");
    const minutes = `${date.getMinutes()}`.padStart(2, "0");
    const seconds = `${date.getSeconds()}`.padStart(2, "0");
    return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
  }

  function handleImageError(e: Event) {
    const img = e.currentTarget as HTMLImageElement;
    img.src = "/assets/logo.png";
  }

  function handleScopeWindowClick(e: MouseEvent) {
    const target = e.target as Node;
    if (
      showScopeMenu &&
      scopeMenuContainer &&
      !scopeMenuContainer.contains(target)
    ) {
      showScopeMenu = false;
    }
    if (
      showSourceMenu &&
      sourceMenuContainer &&
      !sourceMenuContainer.contains(target)
    ) {
      showSourceMenu = false;
    }
    if (
      showRangeMenu &&
      rangeMenuContainer &&
      !rangeMenuContainer.contains(target)
    ) {
      showRangeMenu = false;
    }
  }

  async function playTrack(entry: (typeof data.history)[0]) {
    // Create a minimal track object for playback
    const track = {
      id: entry.track.id,
      title: entry.track.title,
      artist: entry.track.artist,
      album: entry.track.album,
      art_sha1: entry.track.art_sha1,
      duration_seconds: entry.track.duration_seconds,
      codec: entry.track.codec,
      bit_depth: entry.track.bit_depth,
      sample_rate_hz: entry.track.sample_rate_hz,
      mb_release_id: entry.track.mb_release_id,
      path: "", // Will be fetched by backend
      album_artist: null,
      track_no: null,
      disc_no: null,
      date: entry.track.date,
      bitrate: null,
    };
    await setQueue([track], 0);
  }

  function buildHistoryUrl(opts: {
    scope: string;
    source: string;
    range: string;
    from: string;
    to: string;
    page: number;
    includeArtist?: boolean;
    includeAlbum?: boolean;
    includeTrack?: boolean;
  }) {
    const params = new URLSearchParams();
    params.set("scope", opts.scope);
    params.set("source", opts.source);
    params.set("range", opts.range);
    params.set("from", opts.from);
    params.set("to", opts.to);
    params.set("page", String(opts.page));
    if (opts.includeArtist !== false && artistMbid) {
      params.set("artist_mbid", artistMbid);
      if (artistName) params.set("artist_name", artistName);
    }
    if (opts.includeAlbum !== false && albumMbid) {
      params.set("album_mbid", albumMbid);
      if (albumName) params.set("album_name", albumName);
    }
    if (opts.includeTrack !== false && trackId) {
      params.set("track_id", trackId);
      if (trackName) params.set("track_name", trackName);
    }
    return `/history?${params.toString()}`;
  }

  function clearArtistFilter() {
    goto(
      buildHistoryUrl({
        scope,
        source,
        range,
        from: dateFrom,
        to: dateTo,
        page: 1,
        includeArtist: false,
      }),
      { replaceState: true },
    );
  }

  function clearAlbumFilter() {
    goto(
      buildHistoryUrl({
        scope,
        source,
        range,
        from: dateFrom,
        to: dateTo,
        page: 1,
        includeAlbum: false,
      }),
      { replaceState: true },
    );
  }

  function clearTrackFilter() {
    goto(
      buildHistoryUrl({
        scope,
        source,
        range,
        from: dateFrom,
        to: dateTo,
        page: 1,
        includeTrack: false,
      }),
      { replaceState: true },
    );
  }

  function switchScope(nextScope: string) {
    if (scope === nextScope) return;
    scope = nextScope;
    saveFilters();
    goto(
      buildHistoryUrl({
        scope,
        source,
        range,
        from: dateFrom,
        to: dateTo,
        page: 1,
      }),
      {
        replaceState: true,
      },
    ); // Reset to page 1
  }

  function switchRange(nextRange: string, autoApply = false) {
    pendingRange = nextRange;
    if (nextRange !== "custom") {
      const today = new Date();
      const formatDate = (date: Date) => {
        const year = date.getFullYear();
        const month = `${date.getMonth() + 1}`.padStart(2, "0");
        const day = `${date.getDate()}`.padStart(2, "0");
        return `${year}-${month}-${day}`;
      };
      const setRange = (days: number) => {
        pendingTo = formatDate(today);
        const from = new Date(
          today.getFullYear(),
          today.getMonth(),
          today.getDate() - (days - 1),
        );
        pendingFrom = formatDate(from);
      };
      if (nextRange === "all") {
        pendingFrom = "1970-01-01";
        pendingTo = formatDate(today);
      } else if (nextRange === "last30") {
        setRange(30);
      } else if (nextRange === "last90") {
        setRange(90);
      } else if (nextRange === "last180") {
        setRange(180);
      } else if (nextRange === "last365") {
        setRange(365);
      } else {
        setRange(7);
      }
    }
    if (autoApply && nextRange !== "custom") {
      range = nextRange;
      dateFrom = pendingFrom;
      dateTo = pendingTo;
      saveFilters();
      goto(
        buildHistoryUrl({
          scope,
          source,
          range,
          from: dateFrom,
          to: dateTo,
          page: 1,
        }),
        {
          replaceState: true,
        },
      );
      showRangeMenu = false;
      return;
    }
    if (autoApply) {
      applyRange();
    }
  }

  function applyRange() {
    range = pendingRange === "custom" ? "custom" : pendingRange;
    dateFrom = pendingFrom;
    dateTo = pendingTo;
    saveFilters();
    goto(
      buildHistoryUrl({
        scope,
        source,
        range,
        from: dateFrom,
        to: dateTo,
        page: 1,
      }),
      {
        replaceState: true,
      },
    );
    showRangeMenu = false;
  }

  function cancelRange() {
    pendingRange = range;
    pendingFrom = dateFrom;
    pendingTo = dateTo;
    showRangeMenu = false;
  }

  function getRangeLabel(
    labelRange: string | undefined,
    labelFrom: string | undefined,
    labelTo: string | undefined,
  ) {
    if (!labelFrom || !labelTo) return "Last 7 days";
    if (labelFrom === "1970-01-01") return "All time";
    const parseDate = (value: string) => new Date(`${value}T00:00:00`);
    const from = parseDate(labelFrom);
    const to = parseDate(labelTo);
    if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime())) {
      return `${labelFrom} → ${labelTo}`;
    }
    const today = new Date();
    const todayKey = `${today.getFullYear()}-${`${today.getMonth() + 1}`.padStart(2, "0")}-${`${today.getDate()}`.padStart(2, "0")}`;
    const isToToday = labelTo === todayKey;
    const diffDays = Math.round((to.getTime() - from.getTime()) / 86400000) + 1;
    if (isToToday) {
      if (diffDays === 7) return "Last 7 days";
      if (diffDays === 30) return "Last 30 days";
      if (diffDays === 90) return "Last 90 days";
      if (diffDays === 180) return "Last 180 days";
      if (diffDays === 365) return "Last 365 days";
    }
    if (labelRange === "custom") {
      return `${labelFrom} → ${labelTo}`;
    }
    return `${labelFrom} → ${labelTo}`;
  }

  function switchSource(nextSource: string) {
    if (source === nextSource) return;
    source = nextSource;
    saveFilters();
    goto(
      buildHistoryUrl({
        scope,
        source,
        range,
        from: dateFrom,
        to: dateTo,
        page: 1,
      }),
      {
        replaceState: true,
      },
    ); // Reset to page 1
  }

  function updatePendingFrom(event: Event) {
    pendingFrom = (event.currentTarget as HTMLInputElement).value;
    pendingRange = "custom";
  }

  function updatePendingTo(event: Event) {
    pendingTo = (event.currentTarget as HTMLInputElement).value;
    pendingRange = "custom";
  }

  function getStorageKey() {
    const userId = $currentUser?.id ?? "anon";
    return `history-filters:${userId}`;
  }

  function saveFilters() {
    if (typeof localStorage === "undefined") return;
    const payload = {
      scope,
      source,
      range,
      from: dateFrom,
      to: dateTo,
    };
    localStorage.setItem(getStorageKey(), JSON.stringify(payload));
  }

  function restoreFilters() {
    if (restoredFilters || typeof localStorage === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const hasFilters =
      params.has("range") ||
      params.has("from") ||
      params.has("to") ||
      params.has("scope") ||
      params.has("source");
    if (hasFilters) {
      restoredFilters = true;
      return;
    }
    const raw = localStorage.getItem(getStorageKey());
    if (!raw) {
      restoredFilters = true;
      return;
    }
    try {
      const stored = JSON.parse(raw);
      const nextScope = stored.scope || scope;
      const nextSource = stored.source || source;
      const nextRange = stored.range || range;
      const nextFrom = stored.from || dateFrom;
      const nextTo = stored.to || dateTo;
      restoredFilters = true;
      goto(
        buildHistoryUrl({
          scope: nextScope,
          source: nextSource,
          range: nextRange,
          from: nextFrom,
          to: nextTo,
          page: 1,
        }),
        { replaceState: true },
      );
    } catch (e) {
      restoredFilters = true;
    }
  }

  onMount(() => {
    restoreFilters();
  });

  $: if ($currentUser && !restoredFilters) {
    restoreFilters();
  }

  function nextPage() {
    if (!hasNextPage) return;
    goto(
      buildHistoryUrl({
        scope,
        source,
        range,
        from: dateFrom,
        to: dateTo,
        page: page + 1,
      }),
    );
  }

  function prevPage() {
    if (page <= 1) return;
    goto(
      buildHistoryUrl({
        scope,
        source,
        range,
        from: dateFrom,
        to: dateTo,
        page: page - 1,
      }),
    );
  }
</script>

<svelte:window on:click={handleScopeWindowClick} />

<div class="fixed inset-0 z-0 overflow-hidden pointer-events-none">
  <div class="absolute inset-0 bg-surface-1"></div>
</div>

<section
  class="relative z-10 mx-auto flex w-full max-w-[1700px] flex-col gap-8 px-4 py-6 md:w-[calc(100vw-50px)] md:px-2 md:py-10"
>
  <div
    class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between"
  >
    <div class="space-y-2">
      <h1 class="text-4xl md:text-6xl font-bold tracking-tight">History</h1>
      {#if artistMbid}
        <div class="flex items-center gap-2">
          <span class="text-sm text-muted">Artist:</span>
          <span
            class="inline-flex items-center gap-2 rounded-full bg-surface-2 px-3 py-1 text-sm font-medium text-default"
          >
            {artistName || artistMbid}
            <button
              class="text-muted hover:text-default transition-colors"
              on:click={clearArtistFilter}
              aria-label="Clear artist filter"
              title="Clear artist filter"
            >
              ×
            </button>
          </span>
        </div>
      {/if}
      {#if albumMbid}
        <div class="flex items-center gap-2">
          <span class="text-sm text-muted">Album:</span>
          <span
            class="inline-flex items-center gap-2 rounded-full bg-surface-2 px-3 py-1 text-sm font-medium text-default"
          >
            {albumName || albumMbid}
            <button
              class="text-muted hover:text-default transition-colors"
              on:click={clearAlbumFilter}
              aria-label="Clear album filter"
              title="Clear album filter"
            >
              ×
            </button>
          </span>
        </div>
      {/if}
      {#if trackId}
        <div class="flex items-center gap-2">
          <span class="text-sm text-muted">Track:</span>
          <span
            class="inline-flex items-center gap-2 rounded-full bg-surface-2 px-3 py-1 text-sm font-medium text-default"
          >
            {trackName || trackId}
            <button
              class="text-muted hover:text-default transition-colors"
              on:click={clearTrackFilter}
              aria-label="Clear track filter"
              title="Clear track filter"
            >
              ×
            </button>
          </span>
        </div>
      {/if}
    </div>
    <div class="hidden items-center gap-4 md:flex">
      <div class="relative" bind:this={scopeMenuContainer}>
        <button
          class="px-4 py-2 text-sm font-normal text-muted hover:text-default transition-all border-b-2 border-transparent hover:border-accent min-w-[200px] justify-between flex items-center gap-2"
          on:click={() => {
            showScopeMenu = !showScopeMenu;
          }}
          aria-label="Select History Scope"
        >
          <span class="truncate max-w-[170px]">
            {scope === "mine" ? "My History" : "All History"}
          </span>
          <svg
            class="h-4 w-4 opacity-50"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M19 9l-7 7-7-7"
            />
          </svg>
        </button>
        {#if showScopeMenu}
          <div
            class="absolute right-0 mt-2 w-56 rounded-lg border border-subtle surface-glass-panel shadow-xl z-50"
          >
            <div class="p-2 space-y-1">
              <button
                class="w-full px-3 py-2 text-left text-sm text-muted hover:text-default transition-all border-b border-transparent hover:border-accent flex items-center justify-between {scope ===
                'mine'
                  ? 'text-default border-accent'
                  : ''}"
                on:click={() => {
                  switchScope("mine");
                  showScopeMenu = false;
                }}
              >
                <span>My History</span>
                {#if scope === "mine"}
                  <svg
                    class="h-4 w-4 text-primary-400"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      stroke-width="2"
                      d="M5 13l4 4L19 7"
                    />
                  </svg>
                {/if}
              </button>
              <button
                class="w-full px-3 py-2 text-left text-sm text-muted hover:text-default transition-all border-b border-transparent hover:border-accent flex items-center justify-between {scope ===
                'all'
                  ? 'text-default border-accent'
                  : ''}"
                on:click={() => {
                  switchScope("all");
                  showScopeMenu = false;
                }}
              >
                <span>All History</span>
                {#if scope === "all"}
                  <svg
                    class="h-4 w-4 text-primary-400"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      stroke-width="2"
                      d="M5 13l4 4L19 7"
                    />
                  </svg>
                {/if}
              </button>
            </div>
          </div>
        {/if}
      </div>

      <div class="relative" bind:this={sourceMenuContainer}>
        <button
          class="px-4 py-2 text-sm font-normal text-muted hover:text-default transition-all border-b-2 border-transparent hover:border-accent min-w-[200px] justify-between flex items-center gap-2"
          on:click={() => {
            showSourceMenu = !showSourceMenu;
          }}
          aria-label="Select History Source"
        >
          <span class="truncate max-w-[170px]">
            {source === "local"
              ? "Local Only"
              : source === "lastfm"
                ? "Last.fm Only"
                : "All Sources"}
          </span>
          <svg
            class="h-4 w-4 opacity-50"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M19 9l-7 7-7-7"
            />
          </svg>
        </button>
        {#if showSourceMenu}
          <div
            class="absolute right-0 mt-2 w-56 rounded-lg border border-subtle surface-glass-panel shadow-xl z-50"
          >
            <div class="p-2 space-y-1">
              <button
                class="w-full px-3 py-2 text-left text-sm text-muted hover:text-default transition-all border-b border-transparent hover:border-accent flex items-center justify-between {source ===
                'all'
                  ? 'text-default border-accent'
                  : ''}"
                on:click={() => {
                  switchSource("all");
                  showSourceMenu = false;
                }}
              >
                <span>All Sources</span>
                {#if source === "all"}
                  <svg
                    class="h-4 w-4 text-primary-400"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      stroke-width="2"
                      d="M5 13l4 4L19 7"
                    />
                  </svg>
                {/if}
              </button>
              <button
                class="w-full px-3 py-2 text-left text-sm text-muted hover:text-default transition-all border-b border-transparent hover:border-accent flex items-center justify-between {source ===
                'local'
                  ? 'text-default border-accent'
                  : ''}"
                on:click={() => {
                  switchSource("local");
                  showSourceMenu = false;
                }}
              >
                <span>Local Only</span>
                {#if source === "local"}
                  <svg
                    class="h-4 w-4 text-primary-400"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      stroke-width="2"
                      d="M5 13l4 4L19 7"
                    />
                  </svg>
                {/if}
              </button>
              <button
                class="w-full px-3 py-2 text-left text-sm text-muted hover:text-default transition-all border-b border-transparent hover:border-accent flex items-center justify-between {source ===
                'lastfm'
                  ? 'text-default border-accent'
                  : ''}"
                on:click={() => {
                  switchSource("lastfm");
                  showSourceMenu = false;
                }}
              >
                <span>Last.fm Only</span>
                {#if source === "lastfm"}
                  <svg
                    class="h-4 w-4 text-primary-400"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      stroke-width="2"
                      d="M5 13l4 4L19 7"
                    />
                  </svg>
                {/if}
              </button>
            </div>
          </div>
        {/if}
      </div>

      <div class="relative" bind:this={rangeMenuContainer}>
        <button
          class="px-4 py-2 text-sm font-normal text-muted hover:text-default transition-all border-b-2 border-transparent hover:border-accent min-w-[200px] justify-between flex items-center gap-2"
          on:click={() => {
            pendingRange = range;
            pendingFrom = dateFrom;
            pendingTo = dateTo;
            showRangeMenu = !showRangeMenu;
          }}
          aria-label="Select Date Range"
        >
          <span class="truncate max-w-[170px]">
            {getRangeLabel(data.range, data.dateFrom, data.dateTo)}
          </span>
          <svg
            class="h-4 w-4 opacity-50"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M19 9l-7 7-7-7"
            />
          </svg>
        </button>
        {#if showRangeMenu}
          <div
            class="absolute right-0 mt-2 w-80 rounded-lg border border-subtle surface-glass-panel shadow-xl z-50"
          >
            <div class="p-3 space-y-3">
              <div class="grid grid-cols-2 gap-2 text-sm">
                <TabButton
                  active={pendingRange === "last7"}
                  className="w-full justify-start text-left"
                  onClick={() => switchRange("last7", true)}
                >
                  Last 7 days
                </TabButton>
                <TabButton
                  active={pendingRange === "last180"}
                  className="w-full justify-start text-left"
                  onClick={() => switchRange("last180", true)}
                >
                  Last 180 days
                </TabButton>
                <TabButton
                  active={pendingRange === "last30"}
                  className="w-full justify-start text-left"
                  onClick={() => switchRange("last30", true)}
                >
                  Last 30 days
                </TabButton>
                <TabButton
                  active={pendingRange === "last365"}
                  className="w-full justify-start text-left"
                  onClick={() => switchRange("last365", true)}
                >
                  Last 365 days
                </TabButton>
                <TabButton
                  active={pendingRange === "last90"}
                  className="w-full justify-start text-left"
                  onClick={() => switchRange("last90", true)}
                >
                  Last 90 days
                </TabButton>
                <TabButton
                  active={pendingRange === "all"}
                  className="w-full justify-start text-left"
                  onClick={() => switchRange("all", true)}
                >
                  All time
                </TabButton>
              </div>
              <div class="h-px bg-white/10"></div>
              <div class="space-y-2 text-xs text-subtle">
                <div class="space-y-1">
                  <span class="uppercase tracking-wider text-[10px] text-muted">
                    From
                  </span>
                  <input
                    type="date"
                    class="w-full bg-transparent text-default border border-subtle rounded-md px-3 py-2"
                    value={pendingFrom}
                    on:change={updatePendingFrom}
                  />
                </div>
                <div class="space-y-1">
                  <span class="uppercase tracking-wider text-[10px] text-muted">
                    To
                  </span>
                  <input
                    type="date"
                    class="w-full bg-transparent text-default border border-subtle rounded-md px-3 py-2"
                    value={pendingTo}
                    on:change={updatePendingTo}
                  />
                </div>
              </div>
              <div class="flex items-center justify-end gap-2 pt-2">
                <TabButton className="text-xs" onClick={cancelRange}>
                  Cancel
                </TabButton>
                <TabButton className="text-xs" onClick={applyRange}>
                  Apply
                </TabButton>
              </div>
            </div>
          </div>
        {/if}
      </div>

      <div class="h-6 w-px bg-white/10 mx-2"></div>

      <TabButton onClick={() => invalidateAll()} title="Refresh History">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          stroke-width="1.5"
          stroke="currentColor"
          class="w-5 h-5"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99"
          />
        </svg>
      </TabButton>
    </div>
  </div>

  <div class="grid grid-cols-1 gap-3 md:hidden">
    <div class="grid grid-cols-2 gap-3">
      <label class="min-w-0">
        <span class="mb-1 block text-[11px] uppercase tracking-widest text-subtle">
          Scope
        </span>
        <select
          class="w-full rounded-xl border border-subtle bg-surface-2 px-3 py-3 text-sm text-default"
          bind:value={scope}
          on:change={(e) =>
            switchScope((e.currentTarget as HTMLSelectElement).value)}
        >
          <option value="mine">My History</option>
          <option value="all">All History</option>
        </select>
      </label>

      <label class="min-w-0">
        <span class="mb-1 block text-[11px] uppercase tracking-widest text-subtle">
          Source
        </span>
        <select
          class="w-full rounded-xl border border-subtle bg-surface-2 px-3 py-3 text-sm text-default"
          bind:value={source}
          on:change={(e) =>
            switchSource((e.currentTarget as HTMLSelectElement).value)}
        >
          <option value="all">All Sources</option>
          <option value="local">Local Only</option>
          <option value="lastfm">Last.fm Only</option>
        </select>
      </label>
    </div>

    <div class="rounded-2xl border border-subtle bg-surface-2/70 p-3 backdrop-blur-xs">
      <div class="mb-2 flex items-center justify-between gap-3">
        <div>
          <div class="text-[11px] uppercase tracking-widest text-subtle">Range</div>
          <div class="text-sm font-medium text-default">
            {getRangeLabel(data.range, data.dateFrom, data.dateTo)}
          </div>
        </div>
        <button class="btn btn-outline btn-sm" on:click={() => invalidateAll()} title="Refresh History">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            stroke-width="1.5"
            stroke="currentColor"
            class="h-4 w-4"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99"
            />
          </svg>
        </button>
      </div>

      <div class="grid grid-cols-2 gap-2">
        {#each rangeOptions as option}
          <button
            class={`rounded-xl px-3 py-2 text-left text-sm transition-colors ${
              range === option.value || pendingRange === option.value
                ? "border border-accent/40 bg-accent/15 text-default"
                : "border border-subtle bg-surface-3/50 text-muted hover:text-default"
            }`}
            on:click={() => {
              if (option.value === "custom") {
                pendingRange = "custom";
              } else {
                switchRange(option.value, true);
              }
            }}
          >
            {option.label}
          </button>
        {/each}
      </div>

      {#if range === "custom" || pendingRange === "custom"}
        <div class="mt-3 grid grid-cols-1 gap-2">
          <input
            type="date"
            class="w-full rounded-xl border border-subtle bg-transparent px-3 py-3 text-sm text-default"
            value={pendingFrom}
            on:change={updatePendingFrom}
          />
          <input
            type="date"
            class="w-full rounded-xl border border-subtle bg-transparent px-3 py-3 text-sm text-default"
            value={pendingTo}
            on:change={updatePendingTo}
          />
          <button class="btn btn-primary btn-sm justify-start" on:click={applyRange}>
            Apply custom range
          </button>
        </div>
      {/if}
    </div>
  </div>

  <!-- Stats -->
  <div class="grid gap-6 items-stretch lg:[grid-template-columns:35%_1fr]">
    <div class="glass-panel p-6 flex flex-col h-full">
      <div class="flex items-center justify-between">
        <div>
          <p class="text-sm text-subtle">Playback trend</p>
          <h2 class="text-xl font-semibold text-default">
            Plays per day ({getRangeLabel(
              data.range,
              data.dateFrom,
              data.dateTo,
            )})
          </h2>
        </div>
      </div>
      {#if chartRows.length === 0}
        <p class="text-muted text-sm mt-4">No data.</p>
      {:else}
        <div class="mt-4 h-[320px] md:h-[500px]">
          <HistoryChart rows={chartRows} />
        </div>
      {/if}
    </div>

    <div class="grid gap-4 md:gap-6 lg:grid-cols-3">
      <div
        class="rounded-2xl border border-subtle bg-surface-2 p-4 backdrop-blur-sm h-full"
      >
        <h3 class="text-md font-semibold mb-3 text-default">Top Artists</h3>
        {#if data.stats.artists.length === 0}
          <p class="text-muted text-sm">No data.</p>
        {:else}
          <div class="space-y-2 text-sm">
            {#each data.stats.artists.slice(0, 10) as artist (artist.artist)}
              <div class="flex items-center justify-between gap-3">
                <div class="flex items-center gap-3 min-w-0">
                  <div
                    class="h-9 w-9 rounded-sm bg-surface-3 overflow-hidden flex-shrink-0"
                  >
                    <img
                      src={artist.art_sha1
                        ? getArtUrl(artist.art_sha1, 50)
                        : "/assets/logo.png"}
                      alt={artist.artist}
                      class="h-full w-full object-cover"
                    />
                  </div>
                  <a
                    class="hover:text-default hover:underline truncate text-default"
                    href={`/artist/${encodeURIComponent(artist.artist)}`}
                  >
                    {artist.artist}
                  </a>
                </div>
                <span class="text-muted tabular-nums">{artist.plays}</span>
              </div>
            {/each}
          </div>
        {/if}
      </div>
      <div
        class="rounded-2xl border border-subtle bg-surface-2 p-4 backdrop-blur-sm h-full"
      >
        <h3 class="text-md font-semibold mb-3 text-default">Top Albums</h3>
        {#if data.stats.albums.length === 0}
          <p class="text-muted text-sm">No data.</p>
        {:else}
          <div class="space-y-2 text-sm">
            {#each data.stats.albums.slice(0, 10) as album (album.album + album.artist)}
              <div class="flex items-center justify-between gap-3">
                <div class="flex items-center gap-3 min-w-0">
                  <div
                    class="h-9 w-9 rounded-sm bg-surface-3 overflow-hidden flex-shrink-0"
                  >
                    <img
                      src={album.art_sha1
                        ? getArtUrl(album.art_sha1, 50)
                        : "/assets/logo.png"}
                      alt={album.album}
                      class="h-full w-full object-cover"
                    />
                  </div>
                  <div class="min-w-0">
                    <a
                      class="hover:text-default text-default hover:underline block truncate"
                      href={album.mb_release_id
                        ? `/album/${album.mb_release_id}`
                        : "#"}
                    >
                      {album.album}
                    </a>
                    <a
                      class="text-muted hover:text-default hover:underline text-xs"
                      href={`/artist/${encodeURIComponent(album.artist)}`}
                    >
                      {album.artist}
                    </a>
                  </div>
                </div>
                <span class="text-muted tabular-nums">{album.plays}</span>
              </div>
            {/each}
          </div>
        {/if}
      </div>
      <div
        class="rounded-2xl border border-subtle bg-surface-2 p-4 backdrop-blur-sm h-full"
      >
        <h3 class="text-md font-semibold mb-3 text-default">Top Tracks</h3>
        {#if data.stats.tracks.length === 0}
          <p class="text-muted text-sm">No data.</p>
        {:else}
          <div class="space-y-2 text-sm">
            {#each data.stats.tracks.slice(0, 10) as track (track.id)}
              <div class="flex items-center justify-between gap-3">
                <div class="flex items-center gap-3 min-w-0">
                  <div
                    class="h-9 w-9 rounded-sm bg-surface-3 overflow-hidden flex-shrink-0"
                  >
                    <img
                      src={track.art_sha1
                        ? getArtUrl(track.art_sha1, 50)
                        : "/assets/logo.png"}
                      alt={track.title}
                      class="h-full w-full object-cover"
                    />
                  </div>
                  <div class="min-w-0">
                    <a
                      class="hover:text-default text-default hover:underline block truncate"
                      href={track.mb_release_id
                        ? `/album/${track.mb_release_id}`
                        : "#"}
                    >
                      {track.title}
                    </a>
                    <a
                      class="text-muted hover:text-default hover:underline text-xs"
                      href={`/artist/${encodeURIComponent(track.artist)}`}
                    >
                      {track.artist}
                    </a>
                  </div>
                </div>
                <span class="text-muted tabular-nums">{track.plays}</span>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    </div>
  </div>

  <div class="mx-auto w-full max-w-[1200px]">
    <div class="glass-panel divide-y divide-subtle">
      {#if data.history.length === 0}
        <div class="p-6 text-muted">No playback history yet.</div>
      {:else}
        {#each data.history as entry}
          <div
            class="group flex items-start gap-3 px-3 py-3 transition-colors hover:bg-surface-2 sm:items-center sm:gap-4 sm:px-4"
          >
            <!-- Artwork -->
            <div
              class="relative h-12 w-12 flex-shrink-0 overflow-hidden rounded-sm bg-surface-3 sm:h-14 sm:w-14"
            >
              <img
                src={entry.track.art_sha1
                  ? getArtUrl(entry.track.art_sha1, 60)
                  : "/assets/logo.png"}
                alt="Art"
                class="h-full w-full object-cover"
                on:error={handleImageError}
              />
              <div
                class="absolute inset-0 bg-black/40 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <div
                  class="opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <IconButton
                    variant="ghost"
                    onClick={() => playTrack(entry)}
                    title="Play"
                  >
                    <svg
                      class="h-6 w-6 ml-0.5 text-white"
                      fill="currentColor"
                      viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg
                    >
                  </IconButton>
                </div>
              </div>
            </div>

            <!-- Track Info -->
            <div class="min-w-0 flex-1">
              <p
                class="truncate text-sm font-semibold text-default group-hover:text-default"
              >
                {entry.track.title}
              </p>
              <div class="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted">
                <a
                  href={`/artist/${encodeURIComponent(entry.track.artist)}`}
                  class="hover:text-default hover:underline"
                  on:click|preventDefault|stopPropagation={() =>
                    goto(`/artist/${encodeURIComponent(entry.track.artist)}`)}
                >
                  {entry.track.artist}
                </a>
                {#if entry.track.album}
                  <span class="text-subtle">•</span>
                  <a
                    href={entry.track.mb_release_id
                      ? `/album/${entry.track.mb_release_id}`
                      : "#"}
                    class="hover:text-default hover:underline"
                    on:click|preventDefault|stopPropagation={() => {
                      if (entry.track.mb_release_id) {
                        goto(`/album/${entry.track.mb_release_id}`);
                      }
                    }}
                  >
                    {entry.track.album}
                  </a>
                {/if}
                <span class="text-subtle">•</span>
                <span>{formatTime(entry.track.duration_seconds)}</span>
                {#if entry.track.codec}
                  <span class="text-subtle">•</span>
                  <span class="uppercase">{entry.track.codec}</span>
                {/if}
                {#if entry.track.bit_depth && entry.track.sample_rate_hz}
                  <span class="text-subtle">•</span>
                  <span>
                    {entry.track.bit_depth}bit / {(
                      entry.track.sample_rate_hz / 1000
                    ).toFixed(1)}kHz
                  </span>
                {/if}
              </div>
              <div class="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-subtle md:hidden">
                {#if entry.source === "lastfm"}
                  <img
                    src="/assets/logo-lastfm.png"
                    alt="Last.fm"
                    class="h-4 w-4 opacity-90"
                  />
                {/if}
                <span>{formatTimestamp(entry.timestamp)}</span>
                <span class="text-subtle">•</span>
                {#if entry.user}
                  <span>{entry.user.display_name || entry.user.username}</span>
                {:else}
                  <span>Unknown user</span>
                {/if}
              </div>
            </div>

            <!-- Timestamp & Client Info -->
            <div class="hidden items-center gap-4 md:flex">
              <div class="flex flex-col items-end gap-1 text-xs text-muted">
                <div class="flex items-center gap-2">
                  {#if entry.source === "lastfm"}
                    <img
                      src="/assets/logo-lastfm.png"
                      alt="Last.fm"
                      class="h-5 w-5 opacity-90"
                    />
                  {/if}
                  <span class="font-medium"
                    >{formatTimestamp(entry.timestamp)}</span
                  >
                </div>
                <div class="flex flex-col items-end text-[11px] text-subtle">
                  {#if entry.user}
                    <span>{entry.user.display_name || entry.user.username}</span
                    >
                  {:else}
                    <span>Unknown user</span>
                  {/if}
                  <span>{entry.client_ip}</span>
                  <span class="text-[10px] text-muted/60">
                    {entry.client_id || "Unknown Client"}
                  </span>
                </div>
              </div>

              <!-- Duration -->
              <div
                class="w-14 text-right text-xs text-muted font-medium tabular-nums"
              >
                {formatTime(entry.track.duration_seconds)}
              </div>
            </div>
          </div>
        {/each}
      {/if}
    </div>

    <!-- Pagination -->
    <div class="mt-6 flex items-center justify-between p-4 glass-panel">
      <button
        class="px-4 py-2 text-sm font-medium rounded-lg hover:bg-surface-3 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        disabled={page <= 1}
        on:click={prevPage}
      >
        Previous
      </button>
      <span class="text-sm text-subtle">Page {page}</span>
      <button
        class="px-4 py-2 text-sm font-medium rounded-lg hover:bg-surface-3 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        disabled={!hasNextPage}
        on:click={nextPage}
      >
        Next
      </button>
    </div>
  </div>
</section>
