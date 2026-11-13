# ServerSC2 Pause Point

## Current state

- Repository work is on development; branches are exactly master and development.
- ServerSC2.Core currently leases two distinct SC2 listener ports plus one shared five-port multiplayer block per match. This is the existing two-client footprint, not yet validated for an observer plus two competitors.
- ServerSC2.ServerAppAdapter implements ServerApp.Core's IGameSessionAdapter contract through a source project reference.
- The current Sc2ProcessSessionRuntime launches two SC2 instances and two admitted runner executables. One participant runner currently receives CreateGame authority; this is the old topology and must be replaced for observer-hosted competition.
- ISc2BotRunnerResolver is the trusted artifact-resolution boundary. Its implementation must resolve immutable build IDs and verify each artifact against its admitted SHA-256; this repository does not yet provide the artifact store/resolver.
- Contract checks cover profile/lease behavior, adapter assignment mapping, wrong-game rejection, startup-failure lease cleanup, and rejection of a runtime status carrying the wrong admitted match ID.
- The process supervisor is compiled by CI but has not been exercised against a live SC2 installation.

## Agreed target architecture

A match uses three SC2 processes and two bot runners:

1. Dedicated simulation host / observer: creates the multiplayer game, joins as observer, monitors lifecycle, and captures authoritative result/replay evidence.
2. Player SC2 instance A plus admitted runner A.
3. Player SC2 instance B plus admitted runner B.

Neither competitor creates the game. Each runner connects only to its own player SC2 listener. The observer's global perspective is never exposed to either bot. This is three supervised SC2 processes, not a requirement for three physical machines.

The protocol has an observer participation field (`observed_player_id`) and distinct observer actions, but the exact CreateGame-then-observer-join sequence and the complete three-client PortSet layout remain unproven. See [OBSERVER_HOST_DESIGN.md](OBSERVER_HOST_DESIGN.md).

## Next implementation gates

1. Prove dedicated host CreateGame followed by observer join against the pinned SC2 build; confirm all-player observer semantics.
2. Derive the complete PortSet footprint for three SC2 clients and update the atomic lease pool/profile validation.
3. Change typed launch records and the process supervisor to create one observer plus two player instances and two runners. Remove the competitor-host flag.
4. Implement trusted immutable artifact resolution and SHA-256 verification before any runner launch.
5. Capture observer-authoritative terminal results and replay, correlated to player IDs, immutable participants, map/game version, and both build hashes.
6. Add contract tests for observer readiness, no observer-to-bot information path, fairness metadata, startup failure, timeout, cancellation, early exit, and complete process-tree cleanup.
7. Run the three-process/two-runner live SC2 integration proof, then add durable append-oriented session history and idempotent ServerApp result handoff.

## Verification and boundaries

CI currently checks out ServerApp's development source, installs .NET 8, builds ServerSC2.Core and the adapter, and runs contract checks. CI success proves compilation and those contracts, not live SC2 integration. No live SC2 proof has been performed for the observer-host topology.

No NuGet publishing, merge, release, deployment, or branch deletion has been performed. No database or ORM has been introduced.
