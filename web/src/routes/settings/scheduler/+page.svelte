<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import {
    listSchedulerJobs,
    listSchedulerTasks,
    createSchedulerTask,
    updateSchedulerTask,
    deleteSchedulerTask,
    runSchedulerTask,
    stopSchedulerTask,
    listSchedulerRuns,
    type SchedulerJob,
    type ScheduledTask,
    type ScheduledRun,
  } from "$lib/api";

  let jobs: SchedulerJob[] = [];
  let tasks: ScheduledTask[] = [];
  let runsByTask: Record<number, ScheduledRun[]> = {};
  let loading = true;
  let error = "";
  let createError = "";
  let createSuccess = "";
  let selectedJob = "";
  let cron = "0 3 * * *";
  let enabled = true;
  let editingTaskId: number | null = null;
  let editCron = "";
  let expandedTaskId: number | null = null;
  let actionMessage = "";
  let showJobs = false;
  let jobsContainer: HTMLElement;
  $: selectedJobItem = jobs.find((job) => job.key === selectedJob);
  let pollHandle: ReturnType<typeof setInterval> | null = null;

  onMount(async () => {
    await loadData();
    const handleClick = (event: MouseEvent) => {
      if (
        showJobs &&
        jobsContainer &&
        !jobsContainer.contains(event.target as Node)
      ) {
        showJobs = false;
      }
    };
    document.addEventListener("click", handleClick);
    onDestroy(() => document.removeEventListener("click", handleClick));

    pollHandle = setInterval(async () => {
      try {
        tasks = await listSchedulerTasks();
      } catch {
        // Keep UI stable if polling fails.
      }
    }, 5000);
    onDestroy(() => {
      if (pollHandle) clearInterval(pollHandle);
    });
  });

  async function loadData() {
    loading = true;
    error = "";
    try {
      jobs = await listSchedulerJobs();
      if (!selectedJob && jobs.length) selectedJob = jobs[0].key;
      tasks = await listSchedulerTasks();
    } catch (e: any) {
      error = e?.message || "Failed to load scheduler data";
    } finally {
      loading = false;
    }
  }

  function formatTimestamp(ts: string | null) {
    if (!ts) return "—";
    const date = new Date(ts);
    if (Number.isNaN(date.getTime())) return ts;
    return date.toLocaleString();
  }

  function statusBadge(status: string | null) {
    if (!status) return "badge badge-ghost";
    if (status === "success") return "badge badge-success";
    if (status === "running") return "badge badge-info";
    if (status === "cancelled") return "badge badge-warning";
    if (status === "skipped") return "badge badge-warning";
    if (status === "interrupted") return "badge badge-warning";
    return "badge badge-error";
  }

  async function handleCreate() {
    createError = "";
    createSuccess = "";
    if (!selectedJob) {
      createError = "Please select a job.";
      return;
    }
    if (!cron.trim()) {
      createError = "Please enter a cron schedule.";
      return;
    }
    try {
      const created = await createSchedulerTask({
        job_key: selectedJob,
        cron: cron.trim(),
        enabled,
      });
      tasks = [created, ...tasks];
      createSuccess = "Scheduled job created.";
    } catch (e: any) {
      createError = e?.message || "Failed to create job.";
    }
  }

  async function toggleEnabled(task: ScheduledTask) {
    actionMessage = "";
    try {
      const updated = await updateSchedulerTask(task.id, {
        enabled: !task.enabled,
      });
      tasks = tasks.map((t) => (t.id === task.id ? updated : t));
    } catch (e: any) {
      actionMessage = e?.message || "Failed to update job.";
    }
  }

  function startEdit(task: ScheduledTask) {
    editingTaskId = task.id;
    editCron = task.cron;
  }

  function cancelEdit() {
    editingTaskId = null;
    editCron = "";
  }

  async function saveEdit(task: ScheduledTask) {
    actionMessage = "";
    try {
      const updated = await updateSchedulerTask(task.id, {
        cron: editCron.trim(),
      });
      tasks = tasks.map((t) => (t.id === task.id ? updated : t));
      cancelEdit();
    } catch (e: any) {
      actionMessage = e?.message || "Failed to update cron.";
    }
  }

  async function handleRun(task: ScheduledTask) {
    actionMessage = "";
    try {
      tasks = tasks.map((t) =>
        t.id === task.id ? { ...t, last_status: "running" } : t,
      );
      await runSchedulerTask(task.id);
      tasks = await listSchedulerTasks();
    } catch (e: any) {
      actionMessage = e?.message || "Failed to run job.";
    }
  }

  async function handleStop(task: ScheduledTask) {
    actionMessage = "";
    try {
      await stopSchedulerTask(task.id);
      tasks = await listSchedulerTasks();
    } catch (e: any) {
      actionMessage = e?.message || "Failed to stop job.";
    }
  }

  async function handleDelete(task: ScheduledTask) {
    if (!confirm(`Delete scheduled job "${task.job?.name || task.job_key}"?`)) {
      return;
    }
    actionMessage = "";
    try {
      await deleteSchedulerTask(task.id);
      tasks = tasks.filter((t) => t.id !== task.id);
    } catch (e: any) {
      actionMessage = e?.message || "Failed to delete job.";
    }
  }

  async function toggleRuns(taskId: number) {
    if (expandedTaskId === taskId) {
      expandedTaskId = null;
      return;
    }
    expandedTaskId = taskId;
    if (!runsByTask[taskId]) {
      runsByTask[taskId] = await listSchedulerRuns(taskId);
    }
  }
</script>

<div class="min-h-screen">
  <div class="mx-auto max-w-5xl px-6 py-10">
    <div class="mb-8 flex flex-col gap-2">
      <p class="text-sm text-subtle">Settings</p>
      <h1 class="text-3xl font-semibold">Scheduler</h1>
      <p class="text-sm text-muted">
        Schedule predefined jobs with cron syntax (UTC).
      </p>
    </div>

    {#if error}
      <div class="mb-6 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
        {error}
      </div>
    {/if}

    <div class="mb-6 surface-glass-panel rounded-2xl p-6 relative z-20 overflow-visible">
      <div class="mb-4">
        <h2 class="text-lg font-semibold">Add Scheduled Job</h2>
        <p class="text-sm text-muted">Pick a job and cron schedule.</p>
      </div>

      {#if createSuccess}
        <div class="mb-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-100">
          {createSuccess}
        </div>
      {/if}
      {#if createError}
        <div class="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
          {createError}
        </div>
      {/if}

      <div class="grid gap-4 md:grid-cols-2">
        <div class="relative" bind:this={jobsContainer}>
          <span class="text-sm text-muted">Job</span>
          <button
            type="button"
            class="mt-2 w-full px-4 py-2 text-sm font-normal text-muted hover:text-default transition-all border-b-2 border-transparent hover:border-accent rounded-lg border border-subtle bg-surface-2 justify-between flex items-center gap-2"
            on:click={() => (showJobs = !showJobs)}
            aria-label="Select scheduled job"
          >
            <span class="truncate">
              {selectedJobItem?.name || "Select Job"}
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
          {#if showJobs}
            <div
              class="absolute left-0 mt-2 w-full rounded-lg border border-subtle surface-glass-panel shadow-xl z-50 max-h-72 overflow-y-auto"
            >
              <div class="p-2 space-y-1">
                {#each jobs as job}
                  <button
                    type="button"
                    class="w-full px-3 py-2 text-left text-sm text-muted hover:text-default transition-all border-b border-transparent hover:border-accent flex items-center justify-between {selectedJob ===
                    job.key
                      ? 'text-default border-accent'
                      : ''}"
                    on:click={() => {
                      selectedJob = job.key;
                      showJobs = false;
                    }}
                  >
                    <span class="truncate">{job.name}</span>
                  </button>
                {/each}
              </div>
            </div>
          {/if}
        </div>
        <div>
          <label class="text-sm text-muted" for="scheduler-cron">Cron (UTC)</label>
          <input
            id="scheduler-cron"
            class="mt-2 w-full rounded-lg border border-subtle bg-surface-2 px-3 py-2 text-sm"
            type="text"
            bind:value={cron}
            placeholder="0 3 * * *"
          />
        </div>
      </div>

      <div class="mt-4 flex items-center gap-4">
        <label class="flex items-center gap-2 text-sm text-muted">
          <input type="checkbox" bind:checked={enabled} />
          Enabled
        </label>
        <button class="btn btn-primary btn-sm" on:click={handleCreate}>
          Add Job
        </button>
      </div>
    </div>

    <div class="surface-glass-panel rounded-2xl p-6 relative z-10">
      <div class="mb-4 flex items-center justify-between">
        <div>
          <h2 class="text-lg font-semibold">Scheduled Jobs</h2>
          <p class="text-sm text-muted">Last run, next run, and status.</p>
        </div>
        <button class="btn btn-outline btn-sm" on:click={loadData}>
          Refresh
        </button>
      </div>

      {#if actionMessage}
        <div class="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
          {actionMessage}
        </div>
      {/if}

      {#if loading}
        <div class="text-sm text-muted">Loading scheduler tasks...</div>
      {:else if !tasks.length}
        <div class="text-sm text-muted">No scheduled jobs yet.</div>
      {:else}
        <div class="space-y-4">
          {#each tasks as task}
            <div class="rounded-xl border border-subtle bg-surface-2 p-4">
              <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div class="flex flex-col gap-1">
                  <div class="text-sm font-semibold text-default">
                    {task.job?.name || task.job_key}
                  </div>
                  <div class="text-xs text-subtle">
                    {task.job?.description || "—"}
                  </div>
                </div>
                <div class="flex flex-wrap items-center gap-2">
                  <span class={statusBadge(task.last_status)}>
                    {task.last_status || "idle"}
                  </span>
                  {#if task.last_status === "running"}
                    <button class="btn btn-outline btn-xs" on:click={() => handleStop(task)}>
                      Stop
                    </button>
                  {:else}
                    <button class="btn btn-outline btn-xs" on:click={() => handleRun(task)}>
                      Run Now
                    </button>
                  {/if}
                  <button class="btn btn-outline btn-xs" on:click={() => toggleRuns(task.id)}>
                    Runs
                  </button>
                  <button class="btn btn-ghost btn-xs" on:click={() => startEdit(task)}>
                    Edit
                  </button>
                  <button class="btn btn-ghost btn-xs text-red-400" on:click={() => handleDelete(task)}>
                    Delete
                  </button>
                </div>
              </div>

              <div class="mt-4 grid gap-3 text-sm text-muted md:grid-cols-2">
                <div>
                  <div class="text-xs text-subtle">Cron (UTC)</div>
                  {#if editingTaskId === task.id}
                    <div class="mt-2 flex gap-2">
                      <input
                        class="w-full rounded-lg border border-subtle bg-surface px-3 py-2 text-xs"
                        type="text"
                        bind:value={editCron}
                      />
                      <button class="btn btn-primary btn-xs" on:click={() => saveEdit(task)}>
                        Save
                      </button>
                      <button class="btn btn-ghost btn-xs" on:click={cancelEdit}>
                        Cancel
                      </button>
                    </div>
                  {:else}
                    <div class="mt-1 text-sm text-default">{task.cron}</div>
                  {/if}
                </div>
                <div class="flex flex-col gap-2">
                  <div class="flex items-center justify-between">
                    <div>
                      <div class="text-xs text-subtle">Last Run</div>
                      <div class="text-sm text-default">{formatTimestamp(task.last_run_at)}</div>
                    </div>
                    <div>
                      <div class="text-xs text-subtle">Next Run</div>
                      <div class="text-sm text-default">{formatTimestamp(task.next_run_at)}</div>
                    </div>
                    <label class="flex items-center gap-2 text-xs text-subtle">
                      <input
                        type="checkbox"
                        checked={task.enabled}
                        on:change={() => toggleEnabled(task)}
                      />
                      Enabled
                    </label>
                  </div>
                  {#if task.last_error}
                    <div class="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
                      {task.last_error}
                    </div>
                  {/if}
                </div>
              </div>

              {#if expandedTaskId === task.id}
                <div class="mt-4 rounded-lg border border-subtle bg-surface px-3 py-2 text-xs text-muted">
                  <div class="mb-2 font-semibold text-default">Recent Runs</div>
                  {#if runsByTask[task.id]?.length}
                    <div class="space-y-2">
                      {#each runsByTask[task.id] as run}
                        <div class="flex flex-wrap items-center gap-3">
                          <span class={statusBadge(run.status)}>{run.status}</span>
                          <span>{formatTimestamp(run.started_at)}</span>
                          <span>{run.duration_ms ? `${run.duration_ms} ms` : "—"}</span>
                          {#if run.error}
                            <span class="text-red-200">{run.error}</span>
                          {/if}
                        </div>
                      {/each}
                    </div>
                  {:else}
                    <div>No runs yet.</div>
                  {/if}
                </div>
              {/if}
            </div>
          {/each}
        </div>
      {/if}
    </div>
  </div>
</div>
