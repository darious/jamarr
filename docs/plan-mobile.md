# Mobile Responsiveness Plan

## Problem Summary

The frontend works well on desktop and acceptably on tablet, but several core UI patterns are still desktop-first and break down on phone-sized screens.

The main issues are:

- The global header is too dense for small screens. Navigation, renderer selection, settings, and search all compete for horizontal space.
- Search is effectively unavailable on mobile because the current search bar is hidden on small screens.
- The persistent player bar is built as a dense three-column desktop layout and will compress poorly on narrow viewports.
- The queue drawer is a desktop side panel with fixed dimensions and offsets, not a mobile sheet.
- Home and discovery pages rely heavily on fixed-width horizontal card rails.
- Artist and album detail pages use large sticky/two-column layouts that need a different mobile composition.
- Some index and filter screens are built for wide displays and need touch-first controls on mobile.

## Guiding Principle

The fix should start with shared layout primitives and shell behavior before changing individual pages. If the shell, player, and overlay patterns remain desktop-shaped, page-level tweaks will only produce partial improvements.

## Plan

### 1. Define viewport targets and page patterns

Use explicit breakpoints for phone, tablet, and desktop, then classify each screen into a small set of layout patterns:

- index grid
- carousel/list
- detail page
- dense data page
- modal/sheet

This avoids one-off responsive fixes and gives the frontend a consistent model for cross-device behavior.

### 2. Refactor the app shell before route pages

Rework the global layout into a responsive shell with:

- a compact mobile header
- a collapsible mobile navigation pattern
- a mobile-first renderer switcher
- a search entry point that works on phone
- page padding that accounts for the persistent player

This is the highest-leverage change because the current shell imposes desktop assumptions on every route.

### 3. Redesign search and navigation for mobile explicitly

Do not just unhide the current search bar. Replace it with a mobile search trigger that opens a full-width overlay or sheet and gives enough room for results and actions.

The goal is:

- fast search access on phone
- large enough tap targets
- clear close/back behavior
- usable result rows without cramping

### 4. Split the player into desktop, tablet, and mobile variants

Keep the playback logic intact, but render different control layouts by breakpoint:

- phone: compact mini-player with essential controls and queue access
- tablet: medium-density control bar
- desktop: full control surface

The current one-layout-for-all approach is too dense for mobile.

### 5. Convert overlays and drawers to responsive sheets

Queue, now-playing, settings menus, and similar overlays should become bottom sheets or full-screen overlays on phone instead of floating desktop panels.

Start with:

- queue
- renderer picker
- settings/menu popovers
- search results surface

### 6. Replace fixed-width card rails with adaptive content patterns

Home and discovery currently use many fixed-width cards inside horizontal scrollers. On phone, some of these should remain swipeable, but others should become stacked or grid-based layouts with larger tap targets and persistent actions.

The goal is to decide section-by-section whether mobile should use:

- horizontal swipe rail
- 2-up grid
- 1-up stacked list

instead of forcing every section into the same card-rail pattern.

### 7. Recompose artist and album detail pages for mobile

These pages need alternate structure at small widths, not just smaller spacing.

Artist pages should shift toward:

- compact hero
- key actions near the top
- horizontal segmented tab control
- vertically stacked sections

Album pages should shift toward:

- single-column flow
- artwork first
- actions next
- metadata after that
- track list below

Sticky desktop column behavior should be removed or replaced on phone.

### 8. Normalize reusable cards and lists for density

Shared components such as track rows and media cards should support size or density variants so mobile layouts can use:

- smaller artwork
- reduced metadata density
- simpler action presentation
- clearer touch targets

This prevents every route from inventing its own mobile override.

### 9. Simplify filter-heavy and data-dense pages for touch

Pages such as artists, history, renderers, settings, and playlists need:

- mobile-friendly filter controls
- less simultaneous horizontal control density
- dropdown or sheet behavior sized for touch
- reduced row complexity where needed

These pages do not need the same visual treatment as media discovery pages, but they do need clear touch-first interaction patterns.

### 10. Add a responsive QA pass and acceptance criteria

Before implementation is considered complete, define target widths and test every major route at phone, tablet, and desktop sizes.

Acceptance criteria:

- no horizontal page overflow
- no clipped persistent controls
- tap targets are large enough for touch
- search is fully usable on phone
- queue is fully usable on phone
- player does not obscure critical content
- detail pages are readable without zooming

## Recommended Implementation Order

1. Shell and navigation
2. Player bar and queue
3. Shared cards and list components
4. Home and discovery
5. Artist and album detail pages
6. History, artists index, renderers, settings, and playlists
7. Final responsive QA sweep

## Notes

- No code changes are included in this document.
- The purpose of this plan is to guide a structured mobile-first pass without disrupting current desktop behavior.
