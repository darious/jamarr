<script lang="ts">
  import { createEventDispatcher } from "svelte";

  export let items: { label: string; value: string }[] = [];
  export let activeValue: string;

  const dispatch = createEventDispatcher<{ change: string }>();

  function select(value: string) {
    activeValue = value;
    dispatch("change", value);
  }
</script>

<div
  class="flex gap-2 p-1.5 bg-black/20 backdrop-blur-xl rounded-xl w-fit border border-white/10 shadow-lg"
>
  {#each items as item}
    {@const isActive = activeValue === item.value}
    <button
      class={`relative px-5 py-2 rounded-lg text-sm font-medium transition-all duration-300 ease-out ${
        isActive
          ? "bg-accent/15 text-white shadow-[0_0_20px_var(--accent-glow)] border border-accent/30"
          : "text-white/60 hover:text-white/90 hover:bg-white/5"
      }`}
      on:click={() => select(item.value)}
    >
      {item.label}

      <!-- Bottom accent border for active tab -->
      {#if isActive}
        <div
          class="absolute bottom-0 left-1/2 -translate-x-1/2 w-3/4 h-0.5 bg-accent rounded-full shadow-[0_0_8px_var(--accent-glow)]"
        ></div>
      {/if}
    </button>
  {/each}
</div>
