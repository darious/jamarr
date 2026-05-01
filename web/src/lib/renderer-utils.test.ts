import { describe, expect, it } from "vitest";
import {
    CAST_RENDERER_ICON,
    DEFAULT_RENDERER_ICON,
    LOCAL_RENDERER_ICON,
    getRendererFallback,
    rendererKind,
    rendererKindLabel,
    rendererMatchesActive,
    rendererSelectionId,
} from "./renderer-utils";

describe("renderer utils", () => {
    it("identifies and labels cast renderers from kind or renderer_id", () => {
        expect(rendererKind({ udn: "cast:abc", renderer_id: "cast:abc", kind: "cast" })).toBe("cast");
        expect(rendererKind({ udn: "cast:abc", renderer_id: "cast:abc" })).toBe("cast");
        expect(rendererKindLabel({ renderer_id: "cast:abc", kind: "cast", cast_type: "audio" })).toBe("Cast audio");
    });

    it("keeps upnp and local compatibility fallbacks", () => {
        expect(rendererKind({ udn: "uuid:speaker" })).toBe("upnp");
        expect(rendererKind({ udn: "local:web-client" })).toBe("local");
        expect(rendererKindLabel({ udn: "uuid:speaker" })).toBe("UPnP");
        expect(rendererKindLabel({ udn: "local:web-client" })).toBe("Local");
    });

    it("chooses protocol-specific fallback icons", () => {
        expect(getRendererFallback({ renderer_id: "cast:kitchen", kind: "cast" })).toBe(CAST_RENDERER_ICON);
        expect(getRendererFallback({ udn: "local:web-client" })).toBe(LOCAL_RENDERER_ICON);
        expect(getRendererFallback({ udn: "uuid:speaker" })).toBe(DEFAULT_RENDERER_ICON);
    });

    it("prefers renderer_id for selection while matching legacy udn", () => {
        const renderer = { udn: "uuid:speaker", renderer_id: "upnp:uuid:speaker" };
        expect(rendererSelectionId(renderer)).toBe("upnp:uuid:speaker");
        expect(rendererMatchesActive(renderer, "upnp:uuid:speaker")).toBe(true);
        expect(rendererMatchesActive(renderer, "uuid:speaker")).toBe(true);
    });
});
