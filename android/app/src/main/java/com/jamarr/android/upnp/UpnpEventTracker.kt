package com.jamarr.android.upnp

/**
 * UPnP eventing state for the active renderer, kept free of jUPnP so it can
 * be unit tested. The controller feeds it subscription lifecycle callbacks,
 * LastChange events and poll results; it answers whether events are healthy
 * enough to poll only as a watchdog.
 *
 * A service is healthy once its subscription is established **and** the
 * device's initial event arrived (proof it can reach our callback), until the
 * subscription ends or fails. A watchdog poll that disagrees with state
 * evented more than [EVENT_SETTLE_MS] earlier is a missed event; two in a row
 * mark the service unreliable, which drops polling back to every second until
 * a fresh subscription delivers its initial event.
 */
class UpnpEventTracker(private val clock: () -> Long = System::currentTimeMillis) {

    class ServiceHealth {
        var established = false
            internal set
        var initialReceived = false
            internal set
        var lastEventAtMs: Long? = null
            internal set
        var events = 0
            internal set
        var failures = 0
            internal set
        var lastError: String? = null
            internal set
        var mismatches = 0
            internal set
        var unreliable = false
            internal set

        val healthy: Boolean get() = established && initialReceived && !unreliable

        internal fun reset() {
            established = false
            initialReceived = false
            mismatches = 0
            unreliable = false
        }
    }

    val avt = ServiceHealth()
    val rc = ServiceHealth()

    /** Last evented values; null until the device reports them. */
    var transportState: String? = null
        private set
    var trackUri: String? = null
        private set
    var volumePercent: Int? = null
        private set
    var muted: Boolean? = null
        private set

    /** Bumped on every evented transport-state or TrackURI change. */
    var generation = 0
        private set

    private fun health(service: String) = if (service == RENDERING_CONTROL) rc else avt

    @Synchronized
    fun onEstablished(service: String) {
        // initialReceived is left alone: jUPnP may deliver the initial event
        // before this callback. It is cleared whenever a subscription is lost.
        health(service).apply {
            established = true
            mismatches = 0
            unreliable = false
            failures = 0
            lastError = null
        }
    }

    /** Subscription ended (renewal failed, device removed, unsubscribed) or failed. */
    @Synchronized
    fun onLost(service: String, reason: String?, failure: Boolean) {
        health(service).apply {
            reset()
            if (failure) failures += 1
            lastError = reason
        }
    }

    /**
     * A LastChange event (already parsed). Returns true when it changed the
     * transport state or TrackURI, so the poll loop should look now.
     */
    @Synchronized
    fun onEvent(service: String, values: Map<String, String>, maxVolume: Int = 100): Boolean {
        val h = health(service)
        h.events += 1
        h.lastEventAtMs = clock()
        h.initialReceived = true
        var changed = false
        if (service == RENDERING_CONTROL) {
            values["Volume"]?.trim()?.toIntOrNull()?.let { raw ->
                val max = if (maxVolume > 0) maxVolume else 100
                volumePercent = (raw * 100.0 / max).let { Math.round(it).toInt() }.coerceIn(0, 100)
            }
            values["Mute"]?.trim()?.lowercase()?.let { muted = it == "1" || it == "true" || it == "yes" }
        } else {
            clean(values["TransportState"])?.uppercase()?.let {
                if (it != transportState) {
                    transportState = it
                    changed = true
                }
            }
            val uri = if (values.containsKey("CurrentTrackURI")) {
                clean(values["CurrentTrackURI"])
            } else if (trackUri == null && values.containsKey("AVTransportURI")) {
                clean(values["AVTransportURI"])
            } else {
                trackUri
            }
            if (uri != trackUri) {
                trackUri = uri
                changed = true
            }
        }
        if (changed) generation += 1
        return changed
    }

    /**
     * Reconcile a watchdog poll against evented state. Returns true on a
     * mismatch (the polled values are then adopted).
     */
    @Synchronized
    fun notePoll(polledState: String?, polledUri: String?): Boolean {
        if (!avt.healthy) return false
        val last = avt.lastEventAtMs
        if (last != null && clock() - last < EVENT_SETTLE_MS) return false
        val state = clean(polledState)?.uppercase()
        val uri = clean(polledUri)
        val stateDiffers = state != null && transportState != null && !sameState(state, transportState!!)
        val uriDiffers = uri != null && trackUri != null && !UpnpTrackSequencer.sameUri(uri, trackUri!!)
        if (!stateDiffers && !uriDiffers) {
            avt.mismatches = 0
            return false
        }
        if (stateDiffers) transportState = state
        if (uriDiffers) trackUri = uri
        generation += 1
        avt.mismatches += 1
        if (avt.mismatches >= MAX_MISMATCHES) avt.unreliable = true
        return true
    }

    /** Forget everything (renderer switched, stopped). */
    @Synchronized
    fun clear() {
        avt.reset()
        rc.reset()
        transportState = null
        trackUri = null
        volumePercent = null
        muted = null
    }

    /** Device poll interval: watchdog cadence while events are healthy. */
    @Synchronized
    fun pollIntervalMs(): Long = if (avt.healthy) EVENT_POLL_INTERVAL_MS else POLL_INTERVAL_MS

    companion object {
        const val POLL_INTERVAL_MS = 1_000L
        const val EVENT_POLL_INTERVAL_MS = 5_000L
        const val EVENT_SETTLE_MS = 2_000L
        const val MAX_MISMATCHES = 2

        private fun clean(value: String?): String? {
            val v = value?.trim() ?: return null
            return if (v.isEmpty() || v == "NOT_IMPLEMENTED") null else v
        }

        private fun sameState(a: String, b: String): Boolean {
            fun norm(s: String) = if (s == "TRANSITIONING") "PLAYING" else s
            return norm(a) == norm(b)
        }
    }
}

/**
 * Parses a UPnP AV `LastChange` document: the variables of InstanceID 0,
 * Master channel only for per-channel variables, values entity-decoded.
 * Deliberately lenient (regex, no schema validation): renderers send all
 * sorts of namespace prefixes and sloppy XML.
 */
object LastChangeParser {
    private val instanceRe = Regex(
        """<(?:\w+:)?InstanceID\b[^>]*\bval\s*=\s*("([^"]*)"|'([^']*)')[^>]*>(.*?)</(?:\w+:)?InstanceID>""",
        RegexOption.DOT_MATCHES_ALL,
    )
    private val elementRe = Regex("""<(?:\w+:)?(\w+)\b([^>]*?)/?>""")
    private val attrRe = Regex("""\b(\w+)\s*=\s*("([^"]*)"|'([^']*)')""")

    fun parse(xml: String?): Map<String, String> {
        if (xml.isNullOrBlank()) return emptyMap()
        val out = linkedMapOf<String, String>()
        for (instance in instanceRe.findAll(xml)) {
            val id = instance.groupValues[2].ifEmpty { instance.groupValues[3] }
            if (id != "0") continue
            for (element in elementRe.findAll(instance.groupValues[4])) {
                val name = element.groupValues[1]
                val attrs = attrRe.findAll(element.groupValues[2]).associate {
                    it.groupValues[1] to decode(it.groupValues[3].ifEmpty { it.groupValues[4] })
                }
                val value = attrs["val"] ?: continue
                val channel = attrs["channel"]
                if (channel != null && channel != "Master") continue
                out[name] = value
            }
        }
        return out
    }

    private val entityRe = Regex("&(amp|lt|gt|quot|apos);")

    /** One pass, so `&amp;lt;` becomes `&lt;` and not `<`. */
    private fun decode(s: String): String = entityRe.replace(s) { m ->
        when (m.groupValues[1]) {
            "amp" -> "&"
            "lt" -> "<"
            "gt" -> ">"
            "quot" -> "\""
            else -> "'"
        }
    }
}
