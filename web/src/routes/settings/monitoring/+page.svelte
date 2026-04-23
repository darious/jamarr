<script lang="ts">
  import { goto } from "$app/navigation";
  import { onDestroy, onMount } from "svelte";
  import {
    fetchMonitoringLog,
    fetchMonitoringSummary,
    type MonitoringLogResponse,
    type MonitoringSummary,
  } from "$lib/api";
  import TabButton from "$lib/components/TabButton.svelte";
  import { currentUser, hydrateUser, isAuthChecked } from "$stores/user";

  let user = null;
  let authReady = false;
  let unsubUser: (() => void) | undefined;
  let unsubAuth: (() => void) | undefined;

  let summary: MonitoringSummary | null = null;
  let logData: MonitoringLogResponse | null = null;
  let selectedLog = "security";
  let lineCount = 200;
  let loading = true;
  let logLoading = false;
  let error = "";

  $: selectedInfo = summary?.logs.find((log) => log.key === selectedLog);
  $: logText = logData?.lines.join("\n") || "";

  onMount(() => {
    unsubUser = currentUser.subscribe((value) => {
      user = value;
      if (authReady && !user) goto("/login");
      if (authReady && user && !user.is_admin) goto("/");
      if (authReady && user?.is_admin && !summary) loadMonitoring();
    });
    unsubAuth = isAuthChecked.subscribe((ready) => {
      authReady = ready;
      if (authReady && !user) goto("/login");
      if (authReady && user && !user.is_admin) goto("/");
      if (authReady && user?.is_admin && !summary) loadMonitoring();
    });
    hydrateUser().catch(() => {});
  });

  onDestroy(() => {
    if (unsubUser) unsubUser();
    if (unsubAuth) unsubAuth();
  });

  async function loadMonitoring() {
    loading = true;
    error = "";
    try {
      summary = await fetchMonitoringSummary();
      await loadLog();
    } catch (e: any) {
      error = e?.message || "Failed to load monitoring data.";
    } finally {
      loading = false;
    }
  }

  async function loadLog() {
    logLoading = true;
    error = "";
    try {
      logData = await fetchMonitoringLog(selectedLog, lineCount);
    } catch (e: any) {
      error = e?.message || "Failed to load log file.";
    } finally {
      logLoading = false;
    }
  }

  function formatBytes(size: number) {
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  }

  function formatModified(value: number | null) {
    if (!value) return "Never";
    return new Date(value * 1000).toLocaleString();
  }
</script>

<div class="mx-auto max-w-6xl px-4 py-10 md:px-8">
  <div class="mb-8 flex flex-col gap-2">
    <p class="text-sm text-subtle">Settings</p>
    <h1 class="text-3xl font-semibold">Monitoring</h1>
  </div>

  {#if error}
    <div
      class="mb-6 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200"
    >
      {error}
    </div>
  {/if}

  {#if loading}
    <div class="text-sm text-muted">Loading...</div>
  {:else if summary}
    <div class="mb-8 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {#each summary.logs as log}
        <button
          type="button"
          class={`rounded-lg border p-4 text-left transition ${
            selectedLog === log.key
              ? "border-accent bg-accent/10"
              : "border-subtle bg-surface-2/70 hover:border-muted"
          }`}
          on:click={() => {
            selectedLog = log.key;
            loadLog();
          }}
        >
          <div class="mb-2 flex items-center justify-between gap-3">
            <span class="font-medium">{log.name}</span>
            <span
              class={`badge ${log.exists ? "badge-success" : "badge-ghost"}`}
            >
              {log.exists ? "Active" : "Empty"}
            </span>
          </div>
          <div class="text-sm text-muted">{formatBytes(log.size_bytes)}</div>
          <div class="mt-1 text-xs text-subtle">
            {formatModified(log.modified_at)}
          </div>
        </button>
      {/each}
    </div>

    <section class="mb-8 rounded-xl border border-subtle bg-surface-2/70 p-5">
      <div class="mb-4 flex items-center justify-between gap-4">
        <h2 class="text-lg font-semibold">Security Alerts</h2>
        <TabButton type="button" on:click={loadMonitoring}>Refresh</TabButton>
      </div>
      {#if summary.alerts.length}
        <div class="space-y-2">
          {#each summary.alerts as alert}
            <div
              class="rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 font-mono text-xs text-yellow-100"
            >
              {alert}
            </div>
          {/each}
        </div>
      {:else}
        <div class="text-sm text-muted">No recent warnings.</div>
      {/if}
    </section>

    <section class="rounded-xl border border-subtle bg-surface-2/70 p-5">
      <div class="mb-4 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <h2 class="text-lg font-semibold">{selectedInfo?.name || "Log"}</h2>
          <p class="text-sm text-muted">{selectedInfo?.key || selectedLog}</p>
        </div>
        <div class="flex flex-wrap items-end gap-3">
          <label class="block text-sm text-muted">
            Log
            <select
              class="select select-bordered mt-1"
              bind:value={selectedLog}
              on:change={loadLog}
            >
              {#each summary.logs as log}
                <option value={log.key}>{log.name}</option>
              {/each}
            </select>
          </label>
          <label class="block text-sm text-muted">
            Lines
            <input
              class="input input-bordered mt-1 w-28"
              type="number"
              min="1"
              max="1000"
              bind:value={lineCount}
            />
          </label>
          <TabButton type="button" disabled={logLoading} on:click={loadLog}>
            {logLoading ? "Loading..." : "Reload"}
          </TabButton>
        </div>
      </div>

      <pre
        class="max-h-[60vh] overflow-auto rounded-lg border border-subtle bg-black/40 p-4 text-xs leading-relaxed text-slate-100"
      >{logText || "No log entries."}</pre>
    </section>
  {/if}
</div>
