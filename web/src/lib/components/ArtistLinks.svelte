<script lang="ts">
    import { goto } from "$app/navigation";

    export let artists: { name: string; mbid?: string }[] | undefined =
        undefined;
    export let artist: { name: string; mbid?: string } | undefined = undefined;
    export let linkClass: string =
        "hover:text-default hover:underline cursor-pointer";
    export let separatorClass: string = "text-subtle";
    export let stopPropagation: boolean = true;
    export let onNavigate: (() => void) | undefined = undefined;

    function getArtistUrl(a: { name: string; mbid?: string }): string {
        if (a.mbid) return `/artist/${a.mbid}`;
        if (a.name) return `/artist/${encodeURIComponent(a.name)}`;
        return "#";
    }

    function handleClick(e: MouseEvent, url: string) {
        if (stopPropagation) {
            e.preventDefault();
            e.stopPropagation();
        }
        if (url && url !== "#") {
            if (onNavigate) onNavigate();
            goto(url);
        }
    }
</script>

{#if artists && artists.length > 0}
    <span>
        {#each artists as a, i}
            {@const url = getArtistUrl(a)}
            <a
                href={url}
                class={linkClass}
                on:click={(e) => handleClick(e, url)}
            >
                {a.name}
            </a>
            {#if i < artists.length - 2}
                <span class={separatorClass}>, </span>
            {:else if i === artists.length - 2}
                <span class={separatorClass}> & </span>
            {/if}
        {/each}
    </span>
{:else if artist}
    {@const url = getArtistUrl(artist)}
    <a href={url} class={linkClass} on:click={(e) => handleClick(e, url)}>
        {artist.name}
    </a>
{/if}
