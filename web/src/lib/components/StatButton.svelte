<script lang="ts">
    export let onClick: ((e: MouseEvent) => void | Promise<void>) | undefined =
        undefined;
    export let variant: "default" | "danger" = "default";
    export let disabled: boolean = false;
    export let title: string = "";
    export let className: string = "";

    function handleClick(e: MouseEvent) {
        if (disabled) return;
        if (onClick) {
            onClick(e);
        }
    }

    const variantClasses = {
        default:
            "bg-white/10 text-white/90 hover:bg-primary/20 hover:text-primary",
        danger: "bg-red-500/10 text-red-200 hover:bg-red-500/20 hover:text-red-100",
    };
</script>

<button
    type="button"
    {disabled}
    class="font-medium px-2 py-0.5 rounded-sm transition-colors {variantClasses[
        variant
    ]} {disabled ? 'opacity-50 cursor-not-allowed' : ''} {className}"
    on:click={handleClick}
    {title}
    {...$$restProps}
>
    <slot />
</button>
