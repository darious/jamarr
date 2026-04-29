<script lang="ts">
    export let checked: boolean = false;
    export let label: string = "";
    export let className: string = "";
    export let disabled: boolean = false;

    import { createEventDispatcher } from "svelte";
    const dispatch = createEventDispatcher();

    function toggle(e: MouseEvent) {
        if (!disabled) {
            checked = !checked;
            dispatch("click", e);
            dispatch("change", checked);
        }
    }
</script>

<button
    type="button"
    class="group flex items-center gap-3 text-left w-full hover:bg-surface-2 p-2 -ml-2 rounded-lg transition-colors {className} {disabled
        ? 'opacity-50 cursor-not-allowed'
        : 'cursor-pointer'}"
    on:click={toggle}
    {disabled}
>
    <div
        class={`relative flex items-center justify-center w-5 h-5 rounded-sm border transition-all duration-200 ${
            checked
                ? "bg-accent border-accent text-white"
                : "bg-transparent border-subtle group-hover:border-accent/50"
        }`}
    >
        {#if checked}
            <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 20 20"
                fill="currentColor"
                class="w-3.5 h-3.5"
            >
                <path
                    fill-rule="evenodd"
                    d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                    clip-rule="evenodd"
                />
            </svg>
        {/if}
    </div>
    <span
        class="text-sm text-muted group-hover:text-default select-none pt-0.5"
    >
        {label}
    </span>
</button>
