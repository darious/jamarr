# Tailwind CSS v3 → v4 Upgrade Plan

## Scope discovery (verified)

- `web/package.json`: `tailwindcss@^3.4.17`, `@skeletonlabs/skeleton@^2.10.3`, `@skeletonlabs/tw-plugin@^0.4.1`, `@tailwindcss/forms@^0.5.11`, `autoprefixer@^10.4.20`, `postcss@^8.5.6`.
- `web/tailwind.config.cjs`: registers `forms` + `skeleton` plugin with custom `jamarr` theme (color-primary/secondary/surface 50–900 RGB tokens).
- `web/postcss.config.cjs`: `tailwindcss` + `autoprefixer`.
- `web/src/app.postcss`: 536 lines. 10 `@apply` directives, 2 `@layer` blocks, `@tailwind base/components/utilities`.
- `web/src/**/*.svelte`: 36 files. **Zero `@apply` usage in component `<style>` blocks.** Zero `@skeletonlabs/*` JS imports.
- Skeleton coupling = TW plugin only (color tokens). No Skeleton components, no Skeleton stores.

**Implication:** Skeleton v2 → v4 component migration NOT required. Only need replicate color tokens natively in TW v4 `@theme`. Drop `@skeletonlabs/*` deps entirely.

## Migration target

- `tailwindcss@^4.1`
- `@tailwindcss/vite@^4.1` (replace PostCSS plugin path — Vite plugin faster, project already on Vite 7)
- `@tailwindcss/forms@^0.5.x` (v4-compat)
- Remove: `@skeletonlabs/skeleton`, `@skeletonlabs/tw-plugin`, `autoprefixer` (v4 bundles Lightning CSS), `postcss.config.cjs`, `tailwind.config.cjs`.

## Browser baseline

TW v4 requires Safari 16.4+, Chrome 111+, Firefox 128+. Confirm acceptable for jamarr user base before starting. Uses native `@property`, `color-mix()`, cascade layers.

## Step plan

### 1. Branch + codemod
```
git checkout -b chore/tailwind-v4
cd web && npx @tailwindcss/upgrade@latest
```
Codemod handles: utility renames (`shadow` → `shadow-sm`, `rounded-sm` → `rounded-xs`, `outline-none` → `outline-hidden`, `bg-opacity-*` → slash syntax), `@tailwind` → `@import "tailwindcss"`, basic config → CSS migration. Does NOT handle Skeleton plugin — will error or skip.

### 2. Drop Skeleton plugin
- Delete `tailwind.config.cjs`.
- Uninstall `@skeletonlabs/skeleton`, `@skeletonlabs/tw-plugin`.
- Port jamarr theme color tokens to `app.postcss` `@theme` block (see §4).

### 3. Vite plugin swap
`web/vite.config.ts`:
```ts
import tailwindcss from '@tailwindcss/vite';
plugins: [tailwindcss(), sveltekit()]
```
Delete `postcss.config.cjs`. Uninstall `autoprefixer`, `postcss`.

### 4. Rewrite `app.postcss` head
Replace:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```
with:
```css
@import "tailwindcss";
@plugin "@tailwindcss/forms";

@theme {
  --font-display: "Space Grotesk", "Inter", system-ui, sans-serif;
  --font-body: "Inter", system-ui, sans-serif;
  --shadow-glow: 0 18px 60px rgb(0 0 0 / 35%);

  /* ported from skeleton jamarr theme — RGB triplets for rgb()/<alpha> */
  --color-primary-50: rgb(239 246 255);
  /* ... 50–900 primary/secondary/surface ... */
}
```
Note: TW v4 uses `--color-*` directly. If Skeleton-style `rgb(var(--color-primary-500) / 0.5)` patterns exist in `app.postcss`, convert to TW v4 `--alpha()` or `color-mix()`.

### 5. Convert `@layer components` blocks
v4 supports `@layer components` + `@apply` in global CSS. Keep as-is unless codemod flagged them. The 10 `@apply` calls in `app.postcss` should still work.

If any Svelte `<style>` blocks later need `@apply`, add `@reference "../app.postcss";` at top of that style block (v4 isolates per-file context).

### 6. Variant order audit
v4 stacked variants apply left-to-right (was right-to-left in v3). Grep for chained variants:
```
grep -rE "[a-z]+:[a-z]+:" web/src --include="*.svelte"
```
Manually verify intent of each match.

### 7. Default-change audit
Visual diff likely on:
- Bare `border` class (was `gray-200`, now `currentColor`).
- `ring` (was 3px blue-500, now 1px currentColor).
- `space-x-*` reverse-flex layouts.
- Default color palette OKLCH shift.

Grep:
```
grep -rE "\b(border|ring|space-(x|y))\b" web/src --include="*.svelte"
```

### 8. Arbitrary CSS-var syntax
v3 `bg-[--my-var]` → v4 `bg-(--my-var)`. Codemod handles, verify:
```
grep -rE "\[--" web/src --include="*.svelte"
```

### 9. Forms plugin
`@plugin "@tailwindcss/forms";` in CSS. Drop from JS config (no JS config exists anymore).

### 10. Build + visual QA
```
npm run check
npm run build
npm run dev
```
Manual smoke pass on each route: home, library, artist, album, now playing, settings. Light + dark + each accent. Tablet/landscape breakpoint regression check.

### 11. Stylelint
`stylelint-config-standard` may flag `@import "tailwindcss"` / `@theme` / `@plugin`. Add ignores or upgrade stylelint config.

## Risks

| Risk | Mitigation |
|------|------------|
| Skeleton color tokens don't map cleanly to v4 `--color-*` (Skeleton uses RGB triplets for `rgb(var(--x) / α)`) | Audit `app.postcss` for `var(--color-*)` patterns before migrate. May need both forms during transition. |
| `data-theme="light"` token overrides break with v4 `@theme` scoping | v4 `@theme` is at `:root`. Light theme overrides in `[data-theme="light"]` selector remain valid plain CSS. Verify cascade. |
| Browser baseline drops users | Confirm analytics. Provide fallback message if blocking. |
| Lightning CSS strips needed prefixes | Spot-check `-webkit-backdrop-filter` etc in glass surfaces. v4 ships autoprefixer behavior. |
| Codemod misses Svelte `class:` directives | Manual grep pass post-codemod. |

## Rollback

Single commit, single branch. Revert = `git checkout main`. No DB or runtime state involved.

## Estimate

- Code change: ~1 day (codemod + Skeleton token port + audit grep passes).
- QA pass: ~0.5 day (every route × 2 modes × 6 accents).
- Total: ~1.5 days dev, contained to `web/`.

## Open questions

1. Browser baseline acceptable? (Drops Safari <16.4, ~2% global traffic.)
2. Keep jamarr palette identical or adopt v4 OKLCH defaults for non-brand colors?
3. Replace `autoprefixer` removal acceptable? (Lightning CSS handles prefixes but config is opaque.)
