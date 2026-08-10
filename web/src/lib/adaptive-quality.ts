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

/** Output characteristics of the lossless rungs, mirroring the backend. */
const LOSSLESS_RUNGS: Partial<Record<StreamQuality, { sampleRateHz: number; bitDepth: number }>> = {
    flac_24_48: { sampleRateHz: 48_000, bitDepth: 24 },
    flac_16_48: { sampleRateHz: 48_000, bitDepth: 16 },
};

export type StreamSource = {
    sampleRateHz?: number | null;
    bitDepth?: number | null;
};

/**
 * Whether transcoding to `quality` would actually shrink this source.
 *
 * Lossy rungs always do. A lossless rung only does if it lowers the raw data
 * rate: FLAC 24/48 off a 16/44.1 source is an upsample, ~69% larger, so
 * stepping onto it to relieve a stall makes the stall worse.
 */
export function profileReducesSource(
    quality: StreamQuality,
    source?: StreamSource | null,
): boolean {
    const rung = LOSSLESS_RUNGS[quality];
    if (!rung) return true;
    const rate = source?.sampleRateHz;
    const depth = source?.bitDepth;
    if (!rate || !depth) return true;
    return rung.sampleRateHz * rung.bitDepth < rate * depth;
}

export function nextLowerQuality(
    current: string | null | undefined,
    source?: StreamSource | null,
): StreamQuality {
    const quality = normalizeQuality(current);
    const index = QUALITY_LADDER.indexOf(quality);
    for (const candidate of QUALITY_LADDER.slice(index + 1)) {
        if (profileReducesSource(candidate, source)) return candidate;
    }
    return quality;
}

export function canDowngradeQuality(
    current: string | null | undefined,
    source?: StreamSource | null,
): boolean {
    return nextLowerQuality(current, source) !== normalizeQuality(current);
}

export function recordPlaybackHealthEvent(
    events: number[],
    currentQuality: string | null | undefined,
    nowMs = Date.now(),
    source?: StreamSource | null,
): AdaptiveQualityDecision {
    const recentEvents = [...events.filter((t) => nowMs - t < STALL_WINDOW_MS), nowMs];
    if (recentEvents.length < STALL_THRESHOLD) {
        return { events: recentEvents, downgradeTo: null };
    }

    const current = normalizeQuality(currentQuality);
    const next = nextLowerQuality(current, source);
    return {
        events: recentEvents,
        downgradeTo: next === current ? null : next,
    };
}
