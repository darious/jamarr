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
