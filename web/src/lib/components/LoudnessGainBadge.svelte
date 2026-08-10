<script lang="ts">
  export let gainDb: number | null | undefined = null;
  export let mode: string | null | undefined = null;
  export let normalized: boolean | null | undefined = false;
  export let targetLufs: number | null | undefined = null;
  export let tone: "default" | "overlay" = "default";
  export let compact = false;

  $: hasGain = typeof gainDb === "number" && Number.isFinite(gainDb);
  $: gainText = hasGain
    ? `${gainDb > 0 ? "+" : ""}${gainDb.toFixed(1)} dB`
    : "raw";
  $: modeLabel = mode === "album" ? "Album" : mode === "track" ? "Track" : "Gain";
  $: label = compact ? gainText : `${modeLabel} ${gainText}`;
  $: title = hasGain && normalized
    ? `Loudness normalization to ${targetLufs ?? -16} LUFS`
    : "Loudness normalization is not applied";
  $: classes =
    tone === "overlay"
      ? "border-white/20 bg-white/10 text-white/80"
      : "border-subtle bg-surface-2 text-muted";
</script>

<span
  class={`inline-flex h-5 items-center rounded border px-1.5 text-[11px] font-medium tabular-nums ${classes}`}
  title={title}
  aria-label={title}
>
  {label}
</span>
