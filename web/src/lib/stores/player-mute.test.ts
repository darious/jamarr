import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

const fetchWithAuth = vi.fn();

vi.mock("$lib/api", () => ({
    fetchWithAuth,
}));

describe("renderer mute", () => {
    beforeEach(() => {
        vi.resetModules();
        fetchWithAuth.mockReset();
        const storage = new Map<string, string>([["jamarr_client_id", "web-client"]]);
        vi.stubGlobal("localStorage", {
            getItem: (key: string) => storage.get(key) ?? null,
            setItem: (key: string, value: string) => storage.set(key, value),
        });
    });

    it("posts to the mute endpoint and keeps the server's answer", async () => {
        fetchWithAuth.mockResolvedValue({ ok: true, json: async () => ({ status: "ok", muted: true }) });
        const { playerState, setMuted } = await import("./player");

        expect(await setMuted(true)).toBe(true);

        expect(fetchWithAuth).toHaveBeenCalledTimes(1);
        const [url, init] = fetchWithAuth.mock.calls[0];
        expect(url).toBe("/api/player/mute");
        expect(init.method).toBe("POST");
        expect(JSON.parse(init.body)).toEqual({ muted: true });
        expect(get(playerState).muted).toBe(true);
    });

    it("reverts the optimistic flip when the renderer refuses", async () => {
        fetchWithAuth.mockResolvedValue({ ok: false, status: 400, json: async () => ({}) });
        const { playerState, setMuted } = await import("./player");
        playerState.update((s) => ({ ...s, muted: false }));

        expect(await setMuted(true)).toBe(false);
        expect(get(playerState).muted).toBe(false);
    });

    it("shows the control only for an active renderer with can_mute", async () => {
        const { playerState, canMute } = await import("./player");
        const renderer = (canMuteFlag: boolean) => ({
            udn: "uuid:a",
            renderer_id: "upnp:uuid:a",
            name: "Speaker",
            type: "upnp",
            capabilities: { can_mute: canMuteFlag },
        });

        playerState.update((s) => ({ ...s, renderers: [renderer(true)], renderer: "upnp:uuid:a" }));
        expect(get(canMute)).toBe(true);

        playerState.update((s) => ({ ...s, renderers: [renderer(false)] }));
        expect(get(canMute)).toBe(false);

        playerState.update((s) => ({ ...s, renderers: [renderer(true)], renderer: "local:web-client" }));
        expect(get(canMute)).toBe(false);
    });
});
