import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchWithAuth = vi.fn();

vi.mock("$lib/api", () => ({
    fetchWithAuth,
}));

/**
 * Dragging the volume slider used to emit one request per input event, and for
 * a UPnP renderer each one becomes a SOAP call. A Naim Uniti Atom took ~20 in
 * two seconds and dropped the track it was playing mid-way through.
 */
describe("setVolume request coalescing", () => {
    beforeEach(() => {
        vi.resetModules();
        vi.useFakeTimers();
        fetchWithAuth.mockReset();
        fetchWithAuth.mockResolvedValue({ ok: true, json: async () => ({}) });
        const storage = new Map<string, string>([["jamarr_client_id", "web-client"]]);
        vi.stubGlobal("localStorage", {
            getItem: (key: string) => storage.get(key) ?? null,
            setItem: (key: string, value: string) => storage.set(key, value),
        });
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    const sentPercents = () =>
        fetchWithAuth.mock.calls.map((call) => JSON.parse(call[1].body).percent);

    it("collapses a slider drag into a single request", async () => {
        const { setVolume } = await import("./player");

        for (let percent = 20; percent <= 40; percent++) {
            setVolume(percent);
        }

        await vi.runAllTimersAsync();

        expect(fetchWithAuth).toHaveBeenCalledTimes(1);
        expect(sentPercents()).toEqual([40]);
    });

    it("always ends on the value the user landed on", async () => {
        const { setVolume } = await import("./player");

        setVolume(10);
        await vi.runAllTimersAsync();
        expect(sentPercents()).toEqual([10]);

        // A second drag, well after the first settled.
        setVolume(70);
        setVolume(72);
        setVolume(75);
        await vi.runAllTimersAsync();

        expect(sentPercents()).toEqual([10, 75]);
    });

    it("never runs two requests at once", async () => {
        const { setVolume } = await import("./player");

        let inFlight = 0;
        let maxInFlight = 0;
        fetchWithAuth.mockImplementation(async () => {
            inFlight += 1;
            maxInFlight = Math.max(maxInFlight, inFlight);
            await new Promise((resolve) => setTimeout(resolve, 400));
            inFlight -= 1;
            return { ok: true, json: async () => ({}) };
        });

        // Keep moving while a slow request is outstanding.
        for (let percent = 1; percent <= 30; percent++) {
            setVolume(percent);
            await vi.advanceTimersByTimeAsync(50);
        }
        await vi.runAllTimersAsync();

        expect(maxInFlight).toBe(1);
        // The last value must still reach the server.
        expect(sentPercents().at(-1)).toBe(30);
    });

    it("keeps sending after a failed request", async () => {
        const { setVolume } = await import("./player");

        fetchWithAuth.mockRejectedValueOnce(new Error("network down"));
        setVolume(33);
        await vi.runAllTimersAsync();

        setVolume(44);
        await vi.runAllTimersAsync();

        expect(sentPercents()).toEqual([33, 44]);
    });
});
