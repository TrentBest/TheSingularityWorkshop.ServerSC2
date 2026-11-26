# SC2 authoring proposal transport contract

## Status and ownership

`Sc2BotAuthoringProposal` is the ServerSC2 transport boundary for a submitted authoring proposal. It is deliberately not a second bot-domain model.

- SingularityBot remains the authority for BotDefinition, MatchDefinition, catalogue metadata, schema semantics, and domain diagnostics.
- ServerSC2 preserves the exact submitted UTF-8 JSON bytes and pins the contracts and trusted catalogue/runtime compatibility versions used to interpret them.
- ServerSC2 must resolve every pin against host-owned trusted registries and run the authoritative SingularityBot validators before accepting a proposal for launch.
- The browser does not supply a trusted validation receipt, executable path, implementation class, method, script, shell command, or launch permission.

## Envelope

The proposal contains:

- Proposal, bot identity, and immutable bot build IDs.
- The exact admitted build SHA-256.
- Authoring catalogue ID, version, and SHA-256.
- Runtime compatibility ID and version.
- An opaque BotDefinition document with its upstream contract ID/version and exact JSON bytes.
- An opaque MatchDefinition document with its upstream contract ID/version and exact JSON bytes.
- A server-computed integrity SHA-256 over all identity/version pins and both exact document payloads.

The BotDefinition and MatchDefinition contract IDs must be distinct. Each document must be valid UTF-8 JSON with an object root. The bytes are preserved exactly; ServerSC2 does not normalize JSON, infer domain fields, or silently rewrite definitions.

## Integrity and trust

`IntegritySha256` is deterministic for the same envelope values and exact payload bytes. It uses length-prefixed UTF-8 fields and payload bytes to avoid ambiguous concatenation. It is computed by the constructor and must be recomputed by the receiving server after deserialization. A browser-provided digest is never authoritative.

The envelope's IDs and digests are claims to resolve, not proof of trust. A future API must:

1. Authenticate and authorize the caller for the bot identity and proposal.
2. Resolve the exact immutable build from the host-owned package registry.
3. Resolve the exact catalogue snapshot and runtime compatibility version from trusted host registries.
4. Invoke SingularityBot's authoritative BotDefinition and MatchDefinition parsing and semantic validation.
5. Reject unknown, unavailable, race-incompatible, or version-mismatched implementations and capabilities.
6. Persist an immutable accepted proposal and server-owned validation receipt only after successful validation.
7. Revalidate the pinned proposal immediately before Runner handoff; never launch from browser state or a stale validation result.

## Explicitly not implemented by this contract

This type does not provide an HTTP endpoint, authentication, persistence, catalogue discovery, SingularityBot validation, runtime compatibility resolution, proposal editing/version history, or Runner launch authorization. Those require the ServerSC2 hosting/API boundary and the corresponding complete upstream SingularityBot contracts. In particular, this envelope does not imply that every command-layer implementation already publishes a complete settings schema or that MatchDefinition authoring is complete.

No browser host or new editor project is introduced here. The eventual browser Experience remains hosted by the established WebPage/WebApp path while ServerSC2 owns its SC2-specific API and launch boundary.
