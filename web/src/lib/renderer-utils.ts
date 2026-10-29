export const DEFAULT_RENDERER_ICON = "/assets/icon-renderer.svg";
export const CAST_RENDERER_ICON = "/assets/icon-cast.svg";
export const LOCAL_RENDERER_ICON = "/assets/icon-browser.svg";

export interface RendererLike {
    udn?: string;
    renderer_id?: string;
    name?: string;
    type?: string;
    kind?: string;
    cast_type?: string;
    icon_url?: string;
    capabilities?: RendererCapabilitiesLike | null;
}

/** Subset of the server's renderer capability contract the UI acts on.
 *  Every field is optional: older servers and the local renderer may omit it. */
export interface RendererCapabilitiesLike {
    can_pause?: boolean;
    can_seek?: boolean;
    can_stage_next?: boolean;
    queue_ownership?: string;
    queue_operations?: string[];
    can_mute?: boolean;
}

export interface RendererControls {
    canPause: boolean;
    canSeek: boolean;
}

export function rendererKind(renderer: RendererLike | null | undefined): string {
    const raw = renderer?.kind || renderer?.type || renderer?.renderer_id?.split(":")[0] || "";
    if (raw === "cast" || raw === "chromecast") return "cast";
    if (raw === "upnp" || renderer?.udn?.startsWith("uuid:")) return "upnp";
    if (raw === "local" || renderer?.udn?.startsWith("local:")) return "local";
    return raw || "unknown";
}

export function rendererKindLabel(renderer: RendererLike | null | undefined): string {
    const kind = rendererKind(renderer);
    if (kind === "cast") {
        const castType = renderer?.cast_type;
        if (!castType || castType === "cast") return "Cast";
        return `Cast ${castType}`;
    }
    if (kind === "upnp") return "UPnP";
    if (kind === "local") return "Local";
    return kind.toUpperCase();
}

export function rendererSelectionId(renderer: RendererLike): string {
    return renderer.renderer_id || renderer.udn || "";
}

export function rendererMatchesActive(renderer: RendererLike, active: string): boolean {
    return rendererSelectionId(renderer) === active || renderer.udn === active;
}

export function getRendererFallback(renderer: RendererLike | null | undefined): string {
    const kind = rendererKind(renderer);
    if (kind === "local") return LOCAL_RENDERER_ICON;
    if (kind === "cast") return CAST_RENDERER_ICON;
    return DEFAULT_RENDERER_ICON;
}

export function getRendererIcon(renderer: RendererLike | null | undefined): string {
    if (renderer?.icon_url) return renderer.icon_url;
    return getRendererFallback(renderer);
}

/** Which transport controls the renderer supports. A flag counts as
 *  unsupported only when the server says so explicitly (`false`); a missing
 *  renderer or capability defaults to enabled. */
export function rendererControls(renderer: RendererLike | null | undefined): RendererControls {
    const caps = renderer?.capabilities;
    return {
        canPause: caps?.can_pause !== false,
        canSeek: caps?.can_seek !== false,
    };
}

/** Mute is offered only when the server says the renderer can do it
 *  (`can_mute: true`): unlike pause/seek, most backends can't, so a missing
 *  flag means no. The browser player mutes itself and never gets the button. */
export function rendererCanMute(renderer: RendererLike | null | undefined): boolean {
    if (!renderer || rendererKind(renderer) === "local") return false;
    return renderer.capabilities?.can_mute === true;
}

export type PlayButtonAction = "play" | "pause" | "stop";

/** What the play button does now: on a renderer that can't pause, the
 *  server's pause stops the track and play restarts it, so call it "stop". */
export function playButtonAction(isPlaying: boolean, controls: RendererControls): PlayButtonAction {
    if (!isPlaying) return "play";
    return controls.canPause ? "pause" : "stop";
}

export const PLAY_BUTTON_LABELS: Record<PlayButtonAction, string> = {
    play: "Play",
    pause: "Pause",
    stop: "Stop (this device can't pause; play restarts the track)",
};

export const SEEK_DISABLED_LABEL = "This device can't seek";

export function findActiveRenderer<T extends RendererLike>(
    renderers: T[] | null | undefined,
    active: string | null | undefined,
): T | undefined {
    if (!active || !renderers) return undefined;
    return renderers.find((r) => rendererMatchesActive(r, active));
}

export function activeRendererControls(
    renderers: RendererLike[] | null | undefined,
    active: string | null | undefined,
): RendererControls {
    return rendererControls(findActiveRenderer(renderers, active));
}
