export const QUALITY_LADDER = [
    "original",
    "flac_24_48",
    "flac_16_48",
    "mp3_320",
    "opus_128",
] as const;

export const STALL_WINDOW_MS = 60_000;
export const STALL_THRESHOLD = 3;

export type StreamQuality = (typeof QUALITY_LADDER)[number];

export type AdaptiveQualityDecision = {
    events: number[];
    downgradeTo: StreamQuality | null;
};

export function normalizeQuality(value: string | null | undefined): StreamQuality {
    return QUALITY_LADDER.includes(value as StreamQuality)
        ? (value as StreamQuality)
        : "original";
}

export function nextLowerQuality(current: string | null | undefined): StreamQuality {
    const quality = normalizeQuality(current);
    const index = QUALITY_LADDER.indexOf(quality);
    return QUALITY_LADDER[Math.min(index + 1, QUALITY_LADDER.length - 1)];
}

export function canDowngradeQuality(current: string | null | undefined): boolean {
    return nextLowerQuality(current) !== normalizeQuality(current);
}

export function recordPlaybackHealthEvent(
    events: number[],
    currentQuality: string | null | undefined,
    nowMs = Date.now(),
): AdaptiveQualityDecision {
    const recentEvents = [...events.filter((t) => nowMs - t < STALL_WINDOW_MS), nowMs];
    if (recentEvents.length < STALL_THRESHOLD) {
        return { events: recentEvents, downgradeTo: null };
    }

    const current = normalizeQuality(currentQuality);
    const next = nextLowerQuality(current);
    return {
        events: recentEvents,
        downgradeTo: next === current ? null : next,
    };
}
