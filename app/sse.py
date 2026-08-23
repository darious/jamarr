"""Shared plumbing for the server-sent-event endpoints."""

# A subscriber that only ever *reads* from an asyncio queue never finds out its
# client went away: nothing is written, so the disconnect is never observed and
# the generator blocks forever — leaking its task, and any resource the response
# holds. Emitting a comment on a timer forces a write often enough to notice.
SSE_HEARTBEAT_SECONDS = 15

# Yielded by a subscribe() generator in place of an event when the heartbeat
# fires. Distinct from None, which the managers use as the shutdown sentinel.
HEARTBEAT = object()

# EventSource ignores comment lines, so a keepalive is invisible to clients.
HEARTBEAT_FRAME = ": keep-alive\n\n"
