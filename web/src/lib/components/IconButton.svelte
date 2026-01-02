<script lang="ts">
    export let variant: "primary" | "outline" | "ghost" = "outline";
    export let title: string = "";
    export let onClick: ((e: MouseEvent) => void | Promise<void>) | undefined =
        undefined;
    export let size: "sm" | "md" = "md";
    export let stopPropagation: boolean = false;

    export let className: string = "";

    function handleClick(e: MouseEvent) {
        if (stopPropagation) {
            e.stopPropagation();
        }
        onClick?.(e);
    }
</script>

<button
    class="btn btn-{variant} {size === 'sm'
        ? 'btn-sm'
        : ''} pointer-events-auto {className}"
    {title}
    on:click={handleClick}
    on:click
>
    <slot />
</button>
