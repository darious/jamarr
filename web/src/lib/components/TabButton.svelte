<script lang="ts">
    export let active: boolean = false;
    export let onClick: ((e: MouseEvent) => void | Promise<void>) | undefined =
        undefined;
    export let title: string = "";
    export let className: string = "";
    export let disabled: boolean = false;
    export let type: "button" | "submit" | "reset" = "button";

    function handleClick(e: MouseEvent) {
        if (disabled) return;
        if (onClick) {
            onClick(e);
        }
    }
</script>

<button
    {type}
    {disabled}
    class={`px-4 py-2 text-sm font-normal transition-all border-b-2 flex items-center ${
        active
            ? "text-default border-accent"
            : disabled
              ? "text-subtle border-transparent cursor-not-allowed"
              : "text-muted border-transparent hover:text-default hover:border-accent"
    } ${className}`}
    on:click={handleClick}
    {title}
    {...$$restProps}
>
    <slot />
</button>
