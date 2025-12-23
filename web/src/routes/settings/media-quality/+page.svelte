<script lang="ts">
  import { onMount } from "svelte";
  import type {
    MediaQualityIssue,
    MediaQualitySummary,
  } from "$lib/api";
  import {
    fetchMediaQualityIssues,
    fetchMediaQualitySummary,
    runMediaQualityCheck,
  } from "$lib/api";

  let summary: MediaQualitySummary | null = null;
  let issues: MediaQualityIssue[] = [];
  let loading = true;
  let running = false;
  let force = false;
  let error = "";
  let issueCode = "";
  let issueOptions: string[] = [];

  async function load() {
    loading = true;
    error = "";
    try {
      summary = await fetchMediaQualitySummary();
      issueOptions = Object.keys(summary?.issue_counts || {}).sort();
      issues = await fetchMediaQualityIssues({
        limit: 300,
        issueCode: issueCode || undefined,
      });
    } catch (e: any) {
      error = e?.message || "Failed to load media quality data.";
    } finally {
      loading = false;
    }
  }

  async function runChecks() {
    running = true;
    error = "";
    try {
      await runMediaQualityCheck(force);
      await load();
    } catch (e: any) {
      error = e?.message || "Media quality checks failed.";
    } finally {
      running = false;
    }
  }

  function formatEntity(issue: MediaQualityIssue) {
    const ctx = issue.context || {};
    switch (issue.entity_type) {
      case "track":
        return `${ctx?.artist || "Unknown"} — ${ctx?.title || "Track #"+issue.entity_id}`;
      case "album":
        return ctx?.title || `Album ${issue.entity_id}`;
      case "artist":
        return ctx?.name || `Artist ${issue.entity_id}`;
      case "artwork":
        return `Artwork #${issue.entity_id}`;
      case "cache_file":
        return issue.details?.path || issue.entity_id || "Cache file";
      default:
        return issue.entity_id || issue.entity_type;
    }
  }

  function formatDetail(issue: MediaQualityIssue) {
    const d = issue.details || {};
    const parts: string[] = [];
    if (d.width && d.height) {
      parts.push(`${d.width}x${d.height}`);
    }
    if (d.bytes) parts.push(`${Math.round(d.bytes / 1024)} KB`);
    if (d.path && issue.entity_type !== "cache_file") parts.push(d.path);
    if (d.missing && Array.isArray(d.missing)) {
      parts.push(`Missing: ${d.missing.join(", ")}`);
    }
    if (!parts.length && d.path) parts.push(d.path);
    return parts.join(" • ") || issue.issue_code;
  }

  $: totalIssues = summary
    ? Object.values(summary.issue_counts || {}).reduce(
        (sum, v) => sum + (v || 0),
        0,
      )
    : 0;

  function formatRelated(issue: MediaQualityIssue) {
    const ctx = issue.context || {};
    const albumLink = (artist: string | undefined, album: string | undefined) => {
      if (!artist || !album) return null;
      return `/album/${encodeURIComponent(artist)}/${encodeURIComponent(album)}`;
    };

    switch (issue.entity_type) {
      case "track":
        return {
          label: ctx?.album ? `Album: ${ctx.album}` : "Track",
          href: albumLink(ctx?.artist, ctx?.album),
        };
      case "album":
        return {
          label: ctx?.title ? `Album: ${ctx.title}` : "Album",
          href: albumLink(ctx?.album_artist, ctx?.title),
        };
      case "artist":
        return { label: ctx?.name ? `Artist: ${ctx.name}` : "Artist", href: null };
      case "artwork":
        return {
          label: `Artwork ${ctx?.type || ""} ${ctx?.width || "?"}x${ctx?.height || "?"}`,
          href: albumLink(
            ctx?.sample_track?.artist || ctx?.sample_track?.album_artist,
            ctx?.sample_track?.album,
          ),
        };
      case "cache_file":
        return { label: issue.details?.path || "Cache file", href: null };
      default:
        return { label: "", href: null };
    }
  }

  onMount(load);
</script>

<div class="min-h-screen bg-gradient-to-br from-black via-surface-50/70 to-black text-white">
  <div class="mx-auto max-w-6xl px-6 py-10 space-y-6">
    <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <div>
        <p class="text-sm text-white/60">Settings</p>
        <h1 class="text-3xl font-semibold">Media Quality</h1>
        <p class="text-sm text-white/60">
          Validate cached artwork and core metadata without re-reading music files.
        </p>
      </div>
      <div class="flex flex-col items-start gap-3 md:flex-row md:items-center">
        <label class="flex items-center gap-2 text-sm text-white/70">
          <input
            class="checkbox checkbox-sm"
            type="checkbox"
            bind:checked={force}
          />
          Force re-check all artwork
        </label>
        <button
          class="btn bg-primary text-white hover:bg-primary/90 normal-case"
          on:click={runChecks}
          disabled={running}
        >
          {#if running}Running...{:else}Run checks{/if}
        </button>
      </div>
    </div>

    {#if error}
      <div class="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-100">
        {error}
      </div>
    {/if}

    <div class="grid gap-4 md:grid-cols-3">
      <div class="rounded-2xl border border-white/10 bg-white/5 p-5 backdrop-blur">
        <p class="text-sm text-white/60">Pending artwork checks</p>
        <p class="text-3xl font-semibold mt-2">{summary?.pending_artwork ?? "—"}</p>
        <p class="text-xs text-white/50 mt-1">Only new/unchecked artwork is scanned by default.</p>
      </div>
      <div class="rounded-2xl border border-white/10 bg-white/5 p-5 backdrop-blur">
        <p class="text-sm text-white/60">Artwork with issues</p>
        <p class="text-3xl font-semibold mt-2">{summary?.artwork_with_issues ?? "—"}</p>
        <p class="text-xs text-white/50 mt-1">Size, aspect, decode, and cache consistency flags.</p>
      </div>
      <div class="rounded-2xl border border-white/10 bg-white/5 p-5 backdrop-blur">
        <p class="text-sm text-white/60">Open issues</p>
        <p class="text-3xl font-semibold mt-2">{totalIssues}</p>
        <p class="text-xs text-white/50 mt-1">Includes missing tags, MusicBrainz IDs, and orphaned cache files.</p>
      </div>
    </div>

    <div class="rounded-2xl border border-white/10 bg-white/5 p-6 backdrop-blur">
      <div class="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div class="space-y-1">
          <h2 class="text-lg font-semibold">Open issues</h2>
          <p class="text-sm text-white/60">Latest recorded findings stored in the database.</p>
        </div>
        <div class="flex flex-col gap-2 md:flex-row md:items-center">
          <label class="flex items-center gap-2 text-sm text-white/70">
            <span>Filter by issue</span>
            <select
              class="media-filter select select-bordered select-sm bg-black/60 text-white"
              bind:value={issueCode}
              on:change={load}
            >
              <option value="">All</option>
              {#each issueOptions as code}
                <option value={code}>{code.replace(/_/g, " ")}</option>
              {/each}
            </select>
          </label>
          <button
            class="btn btn-sm normal-case border border-white/10 bg-white/10 text-white hover:bg-white/20"
            on:click={load}
            disabled={loading}
          >
            {#if loading}Refreshing...{:else}Refresh{/if}
          </button>
        </div>
      </div>

      {#if loading}
        <p class="text-sm text-white/60">Loading...</p>
      {:else if !issues.length}
        <div class="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-50">
          No open issues detected. Run checks to refresh results.
        </div>
      {:else}
        <div class="overflow-x-auto">
          <table class="min-w-full text-sm">
            <thead class="text-white/60">
              <tr class="border-b border-white/10">
                <th class="px-3 py-2 text-left font-medium">Issue</th>
                <th class="px-3 py-2 text-left font-medium">Entity</th>
                <th class="px-3 py-2 text-left font-medium">Related</th>
                <th class="px-3 py-2 text-left font-medium">Details</th>
                <th class="px-3 py-2 text-left font-medium">When</th>
              </tr>
            </thead>
            <tbody>
              {#each issues as issue}
                {#await Promise.resolve(formatRelated(issue)) then related}
                <tr class="border-b border-white/5 hover:bg-white/5">
                  <td class="px-3 py-2 font-medium">
                    {issue.issue_code.replace(/_/g, " ")}
                  </td>
                  <td class="px-3 py-2 text-white/80">
                    {formatEntity(issue)}
                  </td>
                  <td class="px-3 py-2 text-white/70">
                    {#if related?.href}
                      <a
                        class="text-primary hover:underline"
                        href={related.href}
                      >
                        {related.label}
                      </a>
                    {:else}
                      {related.label}
                    {/if}
                  </td>
                  <td class="px-3 py-2 text-white/70">
                    {formatDetail(issue)}
                  </td>
                  <td class="px-3 py-2 text-white/60">
                    {issue.created_at ? new Date(issue.created_at * 1000).toLocaleString() : "—"}
                  </td>
                </tr>
                {/await}
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    </div>
  </div>
</div>

<style>
  :global(select.media-filter) {
    background-color: rgba(15, 15, 20, 0.8);
    color: #f8fafc;
  }

  :global(select.media-filter option) {
    background-color: #0f1117;
    color: #f8fafc;
  }
</style>
