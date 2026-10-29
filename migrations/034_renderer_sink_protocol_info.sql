-- Complete GetProtocolInfo Sink entries (protocol:network:contentFormat:
-- additionalInfo, incl. MIME parameters and DLNA.ORG_PN/OP/FLAGS) per
-- renderer, for format negotiation. supported_mime_types stays as the bare
-- MIME view for compatibility.
ALTER TABLE renderer ADD COLUMN IF NOT EXISTS sink_protocol_info TEXT[];
