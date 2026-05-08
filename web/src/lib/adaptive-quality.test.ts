import { describe, expect, it } from "vitest";

import {
    canDowngradeQuality,
    nextLowerQuality,
    normalizeQuality,
    recordPlaybackHealthEvent,
} from "./adaptive-quality";

describe("adaptive quality policy", () => {
    it("walks the quality ladder down to opus 128", () => {
        expect(nextLowerQuality("original")).toBe("flac_24_48");
        expect(nextLowerQuality("flac_24_48")).toBe("flac_16_48");
        expect(nextLowerQuality("flac_16_48")).toBe("mp3_320");
        expect(nextLowerQuality("mp3_320")).toBe("opus_128");
        expect(nextLowerQuality("opus_128")).toBe("opus_128");
    });

    it("normalizes unknown qualities back to original", () => {
        expect(normalizeQuality("nonsense")).toBe("original");
        expect(nextLowerQuality("nonsense")).toBe("flac_24_48");
    });

    it("downgrades after three stall events inside one minute", () => {
        let decision = recordPlaybackHealthEvent([], "original", 1_000);
        expect(decision.downgradeTo).toBeNull();

        decision = recordPlaybackHealthEvent(decision.events, "original", 20_000);
        expect(decision.downgradeTo).toBeNull();

        decision = recordPlaybackHealthEvent(decision.events, "original", 40_000);
        expect(decision.downgradeTo).toBe("flac_24_48");
    });

    it("ignores stale stall events", () => {
        const decision = recordPlaybackHealthEvent([1_000, 10_000], "flac_24_48", 69_999);

        expect(decision.events).toEqual([10_000, 69_999]);
        expect(decision.downgradeTo).toBeNull();
    });

    it("does not downgrade below the final profile", () => {
        const decision = recordPlaybackHealthEvent([1_000, 2_000], "opus_128", 3_000);

        expect(canDowngradeQuality("opus_128")).toBe(false);
        expect(decision.downgradeTo).toBeNull();
    });
});
