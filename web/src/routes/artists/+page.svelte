<script lang="ts">
  import type { Artist } from "$lib/api";
  import { goto } from "$app/navigation";
  import { onMount } from "svelte";

  export let data: { artists: Artist[] };

  let artists: Artist[] = data.artists;

  onMount(() => {
    artists = data.artists || [];
  });

  const grouped = () => {
    const buckets: Record<string, Artist[]> = {};
    artists.forEach((artist) => {
      const char = (artist.sort_name || artist.name || "#")
        .charAt(0)
        .toUpperCase();
      const key = /[A-Z]/.test(char) ? char : "#";
      buckets[key] = buckets[key] || [];
      buckets[key].push(artist);
    });
    return Object.entries(buckets).sort((a, b) => a[0].localeCompare(b[0]));
  };
</script>

<section class="mx-auto flex w-full max-w-[1700px] flex-col gap-10 px-8 py-10">
  <div
    class="section-head sticky top-0 z-40 bg-surface-50/80 backdrop-blur-xl py-4 -mx-4 px-4 rounded-b-2xl transition-all border-b border-white/5 shadow-lg"
  >
    <div>
      <p class="text-sm uppercase tracking-wide text-white/60">Browse</p>
      <h2 class="text-2xl font-semibold">Artists A–Z</h2>
    </div>
    <div class="flex flex-wrap gap-2">
      {#each grouped() as [letter]}
        <a
          href={`#group-${letter}`}
          class="pill hover:bg-white/10 transition-colors">{letter}</a
        >
      {/each}
    </div>
  </div>

  <div class="flex flex-col gap-10">
    {#each grouped() as [letter, list]}
      <div id={`group-${letter}`} class="space-y-4">
        <div class="flex items-center gap-3">
          <div
            class="h-10 w-10 rounded-xl border border-white/10 bg-white/5 text-center text-xl font-semibold leading-10"
          >
            {letter}
          </div>
          <div class="text-sm text-white/60">{list.length} artists</div>
        </div>

        <div
          class="grid gap-5 [grid-template-columns:repeat(auto-fill,minmax(200px,1fr))]"
        >
          {#each list as artist}
            <a
              class="grid-card block cursor-pointer overflow-hidden focus:outline-none focus:ring-2 focus:ring-primary-400"
              href={`/artist/${encodeURIComponent(artist.name)}`}
            >
              <div class="aspect-square overflow-hidden rounded-xl">
                <img
                  src={artist.art_sha1
                    ? `/art/file/${artist.art_sha1}`
                    : artist.art_id
                      ? `/art/${artist.art_id}`
                      : "/assets/default-artist.svg"}
                  alt={artist.name}
                  class="aspect-square w-full rounded-2xl object-cover transition-transform duration-200 group-hover:scale-[1.03]"
                />
              </div>
              <div class="mt-3 space-y-1">
                <p class="text-base font-semibold line-clamp-1">
                  {artist.name}
                </p>
                <p class="text-xs text-white/60 line-clamp-2">
                  {artist.bio || "No bio yet."}
                </p>
              </div>
            </a>
          {/each}
        </div>
      </div>
    {/each}
  </div>
</section>
