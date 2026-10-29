import { describe, expect, it } from "vitest";
import {
    PLAY_BUTTON_LABELS,
    activeRendererControls,
    findActiveRenderer,
    playButtonAction,
    rendererCanMute,
    rendererControls,
} from "./renderer-utils";

const local = {
    udn: "local:web-client",
    renderer_id: "local:web-client",
    kind: "local",
    capabilities: { can_pause: true, can_seek: true },
};
// A renderer whose server-side capabilities refuse pause and seek.
const limited = {
    udn: "uuid:ABC123",
    renderer_id: "upnp:uuid:ABC123",
    kind: "upnp",
    capabilities: { can_pause: false, can_seek: false },
};
const legacyUpnp = { udn: "uuid:speaker", renderer_id: "upnp:uuid:speaker" };

describe("renderer capability gating", () => {
    it("enables pause and seek when capabilities are missing", () => {
        expect(rendererControls(undefined)).toEqual({ canPause: true, canSeek: true });
        expect(rendererControls(legacyUpnp)).toEqual({ canPause: true, canSeek: true });
        expect(rendererControls({ capabilities: {} })).toEqual({ canPause: true, canSeek: true });
        expect(rendererControls({ capabilities: null })).toEqual({ canPause: true, canSeek: true });
    });

    it("disables only what the server explicitly refuses", () => {
        expect(rendererControls(limited)).toEqual({ canPause: false, canSeek: false });
        expect(rendererControls({ capabilities: { can_pause: true, can_seek: false } })).toEqual({
            canPause: true,
            canSeek: false,
        });
    });

    it("resolves the active renderer by renderer_id or udn", () => {
        const renderers = [local, limited, legacyUpnp];
        expect(findActiveRenderer(renderers, "upnp:uuid:ABC123")).toBe(limited);
        expect(findActiveRenderer(renderers, "uuid:ABC123")).toBe(limited);
        expect(findActiveRenderer(renderers, "")).toBeUndefined();
        expect(findActiveRenderer(undefined, "upnp:uuid:ABC123")).toBeUndefined();
        expect(activeRendererControls(renderers, "upnp:uuid:ABC123")).toEqual({
            canPause: false,
            canSeek: false,
        });
        expect(activeRendererControls(renderers, "local:web-client")).toEqual({
            canPause: true,
            canSeek: true,
        });
        // Unknown active renderer (list not loaded yet): stay enabled.
        expect(activeRendererControls([], "cast:kitchen")).toEqual({ canPause: true, canSeek: true });
    });

    it("turns the pause button into stop when the renderer can't pause", () => {
        const noPause = { canPause: false, canSeek: false };
        const full = { canPause: true, canSeek: true };
        expect(playButtonAction(false, noPause)).toBe("play");
        expect(playButtonAction(true, noPause)).toBe("stop");
        expect(playButtonAction(true, full)).toBe("pause");
        expect(PLAY_BUTTON_LABELS.stop).toMatch(/can't pause/);
    });
});

describe("mute gating", () => {
    it("offers mute only when the server says can_mute", () => {
        expect(rendererCanMute({ renderer_id: "upnp:uuid:a", capabilities: { can_mute: true } })).toBe(true);
        expect(rendererCanMute({ renderer_id: "upnp:uuid:a", capabilities: { can_mute: false } })).toBe(false);
        expect(rendererCanMute({ renderer_id: "cast:abc", kind: "cast", capabilities: {} })).toBe(false);
        expect(rendererCanMute({ renderer_id: "upnp:uuid:a" })).toBe(false);
        expect(rendererCanMute(undefined)).toBe(false);
    });

    it("never offers it for the browser player", () => {
        expect(rendererCanMute({ ...local, capabilities: { can_mute: true } })).toBe(false);
    });
});
