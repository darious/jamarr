<script lang="ts">
    export let artists: { name: string; mbid?: string }[] | undefined =
        undefined;
    export let artist: { name: string; mbid?: string } | undefined = undefined;
    export let linkClass: string =
        "hover:text-default hover:underline cursor-pointer";
    export let separatorClass: string = "text-subtle";
    export let stopPropagation: boolean = true;

    function getArtistUrl(a: { name: string; mbid?: string }): string {
        if (a.mbid) return `/artist/${a.mbid}`;
        if (a.name) return `/artist/${encodeURIComponent(a.name)}`;
        return "#";
    }

    function handleClick(e: MouseEvent) {
        if (stopPropagation) {
            e.stopPropagation();
        }
    }
</script>

{#if artists && artists.length > 0}
    <span>
        {#each artists as a, i}
            <a href={getArtistUrl(a)} class={linkClass} on:click={handleClick}>
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
    <a href={getArtistUrl(artist)} class={linkClass} on:click={handleClick}>
        {artist.name}
    </a>
{/if}
