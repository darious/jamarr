import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

const fetchWithAuth = vi.fn();

vi.mock("$lib/api", () => ({
    fetchWithAuth,
}));

describe("player renderer store", () => {
    beforeEach(() => {
        fetchWithAuth.mockReset();
        const storage = new Map<string, string>([["jamarr_client_id", "web-client"]]);
        vi.stubGlobal("localStorage", {
            getItem: (key: string) => storage.get(key) ?? null,
            setItem: (key: string, value: string) => storage.set(key, value),
        });
    });

    it("posts canonical renderer_id when selecting a renderer", async () => {
        const { playerState, setRenderer } = await import("./player");
        fetchWithAuth
            .mockResolvedValueOnce({
                ok: true,
                json: async () => ({ active: "uuid:speaker", renderer_id: "upnp:uuid:speaker" }),
            })
            .mockResolvedValueOnce({
                ok: true,
                json: async () => ({
                    queue: [],
                    current_index: -1,
                    position_seconds: 0,
                    is_playing: false,
                    renderer: "uuid:speaker",
                    renderer_id: "upnp:uuid:speaker",
                    renderer_kind: "upnp",
                    volume: null,
                }),
            });

        await setRenderer("upnp:uuid:speaker");

        expect(fetchWithAuth.mock.calls[0][0]).toBe("/api/player/renderer");
        expect(JSON.parse(fetchWithAuth.mock.calls[0][1].body)).toEqual({
            renderer_id: "upnp:uuid:speaker",
        });
        expect(get(playerState).renderer).toBe("upnp:uuid:speaker");
        expect(get(playerState).renderer_kind).toBe("upnp");
    });

    it("gates seek on the active renderer's capabilities", async () => {
        const { playerState, rendererControls, seek } = await import("./player");
        playerState.update((s) => ({
            ...s,
            renderer: "upnp:uuid:ABC",
            renderers: [
                {
                    udn: "uuid:ABC",
                    renderer_id: "upnp:uuid:ABC",
                    name: "Living Room",
                    type: "upnp",
                    kind: "upnp",
                    capabilities: { can_pause: false, can_seek: false },
                },
            ],
            position_seconds: 12,
        }));

        expect(get(rendererControls)).toEqual({ canPause: false, canSeek: false });
        await seek(60);
        expect(fetchWithAuth).not.toHaveBeenCalled();
        expect(get(playerState).position_seconds).toBe(12);

        // A renderer without capabilities (older server) keeps seek enabled.
        playerState.update((s) => ({
            ...s,
            renderer: "uuid:speaker",
            renderers: [{ udn: "uuid:speaker", name: "Speaker", type: "upnp" }],
        }));
        expect(get(rendererControls)).toEqual({ canPause: true, canSeek: true });
        fetchWithAuth.mockResolvedValueOnce({ ok: true, json: async () => ({}) });
        await seek(30);
        expect(fetchWithAuth.mock.calls[0][0]).toBe("/api/player/seek");
        expect(get(playerState).position_seconds).toBe(30);
    });
});
