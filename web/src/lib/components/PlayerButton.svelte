<script lang="ts">
    import IconButton from "./IconButton.svelte";

    export let onClick: ((e: MouseEvent) => void | Promise<void>) | undefined =
        undefined;
    export let variant: "primary" | "outline" = "outline";
    export let size: "sm" | "md" = "md";
    export let disabled: boolean = false;
    export let title: string = "";
    export let className: string = "";

    // Map variants to IconButton variants
    const variantMap = {
        primary: "primary" as const,
        outline: "outline" as const,
    };
</script>

<IconButton
    {onClick}
    variant={variantMap[variant]}
    {title}
    className="transition-all {size === 'sm'
        ? 'h-8 w-8'
        : 'h-10 w-10'} {disabled
        ? 'opacity-50 pointer-events-none'
        : ''} {className}"
    {...$$restProps}
>
    <slot />
</IconButton>
