<script lang="ts">
  import { onMount } from "svelte";
  import { scaleBand, scaleLinear } from "d3-scale";

  export let rows: { label: string; plays: number }[] = [];

  let container: HTMLDivElement | null = null;
  let width = 600;
  let height = 400; // Default fallback

  // Reactively update dimensions
  $: maxPlays = Math.max(1, ...rows.map((r) => r.plays || 0));
  // Remove fixed height calculation based on rows
  // $: height = Math.max(220, rows.length * 24 + 32);

  // Margins
  const margin = { top: 10, right: 44, bottom: 25, left: 80 };

  // Calculate inner dimensions
  $: innerWidth = Math.max(0, width - margin.left - margin.right);
  $: innerHeight = Math.max(0, height - margin.top - margin.bottom);

  // Create scales
  $: xScale = scaleLinear().domain([0, maxPlays]).range([0, innerWidth]);

  $: yScale = scaleBand()
    .domain(rows.map((r) => r.label))
    .range([0, innerHeight])
    .padding(0.25);

  $: xTicks = xScale.ticks(5);

  onMount(() => {
    const updateDimensions = () => {
      if (container) {
        width = Math.max(container.clientWidth, 320);
        height = Math.max(container.clientHeight, 220);
      }
    };
    updateDimensions();
    const observer = new ResizeObserver(updateDimensions);
    if (container) {
      observer.observe(container);
    }
    return () => observer.disconnect();
  });
</script>

<div
  bind:this={container}
  class="w-full h-full"
  bind:clientHeight={height}
  bind:clientWidth={width}
>
  <svg {width} {height} class="w-full h-full block">
    <g transform={`translate(${margin.left}, ${margin.top})`}>
      <!-- Background Bar Area -->
      <rect
        width={innerWidth}
        height={innerHeight}
        style="fill: var(--surface-2); rx: 12px;"
      />

      <!-- X Axis -->
      <g transform={`translate(0, ${innerHeight})`}>
        {#each xTicks as tick}
          <g transform={`translate(${xScale(tick)}, 0)`}>
            <!-- Grid Line -->
            <line
              y2={-innerHeight}
              stroke="var(--border-subtle)"
              stroke-dasharray="2,2"
            />
            <!-- Tick Label -->
            <text
              y="16"
              text-anchor="middle"
              style="fill: var(--text-muted); font-size: 10px; font-family: monospace;"
            >
              {tick}
            </text>
          </g>
        {/each}
      </g>

      <!-- Bars -->
      {#each rows as row}
        <g class="group">
          <!-- Hover Target (invisible but wider for better UX) -->
          <rect
            x={0}
            y={yScale(row.label)}
            width={innerWidth}
            height={yScale.bandwidth()}
            fill="transparent"
          />

          <rect
            x={xScale(0)}
            y={yScale(row.label)}
            width={xScale(row.plays) - xScale(0)}
            height={yScale.bandwidth()}
            style="fill: var(--accent); transition: opacity 0.2s;"
            class="opacity-90 group-hover:opacity-100"
            rx="4"
          />
          <!-- Y Axis Label (Date/Month) -->
          <text
            x={-8}
            y={(yScale(row.label) || 0) + yScale.bandwidth() / 2}
            style="fill: var(--text-muted); font-size: 11px; font-family: monospace;"
            text-anchor="end"
            dominant-baseline="middle"
          >
            {row.label}
          </text>
          <!-- Value Label (Plays) -->
          <text
            x={innerWidth - (innerWidth - xScale(row.plays)) + 8}
            y={(yScale(row.label) || 0) + yScale.bandwidth() / 2}
            style="fill: var(--text-muted); font-size: 11px; transition: opacity 0.2s; pointer-events: none;"
            class="opacity-0 group-hover:opacity-100"
            text-anchor="start"
            dominant-baseline="middle"
          >
            {row.plays}
          </text>
        </g>
      {/each}
    </g>
  </svg>
</div>
