import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

describe("auth store session-dead latch", () => {
    beforeEach(() => {
        vi.resetModules();
    });

    it("stops refresh attempts after the server rejects the refresh token", async () => {
        const auth = await import("./auth");
        const fetchImpl = vi.fn().mockResolvedValue({ ok: false, status: 401 });

        // First attempt hits the network and latches the dead session.
        expect(await auth.refreshAccessToken(fetchImpl as any)).toBe(false);
        expect(fetchImpl).toHaveBeenCalledTimes(1);
        expect(get(auth.sessionExpired)).toBe(true);

        // Replaying a rotated refresh token trips server-side reuse detection,
        // so subsequent attempts must not hit the network at all.
        expect(await auth.refreshAccessToken(fetchImpl as any)).toBe(false);
        expect(await auth.refreshAccessToken(fetchImpl as any)).toBe(false);
        expect(fetchImpl).toHaveBeenCalledTimes(1);
    });

    it("keeps retrying after transient failures", async () => {
        const auth = await import("./auth");
        const failing = vi.fn().mockRejectedValue(new Error("network down"));

        expect(await auth.refreshAccessToken(failing as any)).toBe(false);
        expect(get(auth.sessionExpired)).toBe(false);

        const ok = vi.fn().mockResolvedValue({
            ok: true,
            status: 200,
            json: async () => ({ access_token: "token-1" }),
        });
        expect(await auth.refreshAccessToken(ok as any)).toBe(true);
        expect(auth.getAccessToken()).toBe("token-1");
    });

    it("clears the latch on login via setAccessToken", async () => {
        const auth = await import("./auth");
        const rejecting = vi.fn().mockResolvedValue({ ok: false, status: 401 });

        await auth.refreshAccessToken(rejecting as any);
        expect(get(auth.sessionExpired)).toBe(true);

        auth.setAccessToken("fresh-token");
        expect(get(auth.sessionExpired)).toBe(false);
        expect(get(auth.isAuthenticated)).toBe(true);

        // Refresh may hit the network again for the new session.
        auth.clearAccessToken();
        const ok = vi.fn().mockResolvedValue({
            ok: true,
            status: 200,
            json: async () => ({ access_token: "token-2" }),
        });
        expect(await auth.refreshAccessToken(ok as any)).toBe(true);
        expect(ok).toHaveBeenCalledTimes(1);
    });
});
