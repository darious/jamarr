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

<div class="flex gap-1 p-1 bg-white/5 rounded-lg w-fit backdrop-blur-md border border-white/5">
  {#each items as item}
    <button
      class="px-4 py-1.5 rounded-md text-sm font-medium transition-all duration-200"
      class:bg-white-10={activeValue === item.value}
      class:text-white={activeValue === item.value}
      class:shadow-lg={activeValue === item.value}
      class:text-white-50={activeValue !== item.value}
      class:hover:text-white-80={activeValue !== item.value}
      class:hover:bg-white-5={activeValue !== item.value}
      on:click={() => select(item.value)}
    >
      {item.label}
    </button>
  {/each}
</div>

<style>
  /* Custom utility classes mimicking the design system if not available globally */
  .bg-white-10 {
    background-color: rgba(255, 255, 255, 0.1);
  }
  .bg-white-5 {
    background-color: rgba(255, 255, 255, 0.05);
  }
  .text-white-50 {
    color: rgba(255, 255, 255, 0.5);
  }
  .text-white-80 {
    color: rgba(255, 255, 255, 0.8);
  }
</style>
