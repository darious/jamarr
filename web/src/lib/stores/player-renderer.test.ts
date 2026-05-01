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
});
