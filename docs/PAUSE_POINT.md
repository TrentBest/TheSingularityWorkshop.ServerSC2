# ServerSC2 Pause Point

## Current state

- Repository work is on development; branches are intended to remain exactly master and development.
- ServerSC2.Core models a scaled multiplayer port reservation block for one observer plus N player clients. This is reservation planning, not live SC2 PortSet proof or an OS socket reservation.
- ServerSC2.ServerAppAdapter implements ServerApp.Core's IGameSessionAdapter contract through a source project reference.
- The current Sc2ProcessSessionRuntime is still the legacy two-player competitor-host implementation: two SC2 processes, two runners, and CreateGame authority assigned to one participant. Runner-emitted result markers are diagnostics only and cannot produce Completed. The fail-closed completion gate requires independently validated host-authoritative terminal results AND replay evidence; neither evidence source is wired yet.
- The current adapter/runtime explicitly reject participant counts other than two. Team IDs are carried in launch records but the runtime does not implement team-aware SC2 setup or format-aware results.
- Sc2MatchProcessPlan describes one neutral observer plus N participant SC2 clients and N bot runners. It validates pinned adapter/game/map metadata, participant identity/team/build SHA-256/listener ports, unique IDs/ports, observer-only CreateGame authority, and the complete multiplayer port block. It snapshots caller-owned participant collections before validation. This plan is not consumed by the process supervisor.
- ISc2BotRunnerResolver is only the trusted artifact-resolution boundary. Its implementation must resolve immutable build IDs and verify each artifact against its admitted SHA-256; this repository does not yet provide the artifact store/resolver.
- Contract checks cover profile/lease behavior, adapter assignment mapping, wrong-game rejection, startup-failure lease cleanup, mismatched runtime identity, observer authority isolation, participant scaling, port/build boundaries, required runtime metadata, mutable-input snapshotting, and null participant rejection.
- CI compiles the process supervisor and runs contract checks; it does not launch SC2 or prove protocol behavior.

## Agreed target architecture

ServerSC2 is an open host for SC2-compatible bot builds. It must not require a bot to use SingularityBot.

A match assignment defines N entrants, immutable build identities, a competition format, and team grouping. The target topology is one dedicated simulation host/observer plus N player SC2 processes and N independently supervised bot runners:

1. Dedicated simulation host / observer: creates the multiplayer game, joins as observer, monitors authoritative lifecycle, and captures result/replay evidence.
2. One player SC2 instance and one runner per entrant.
3. The observer has no competitor identity. No runner gets CreateGame authority or access to another runner's player endpoint.
4. Formats include 1v1, 2v2, 3v3, FFA, and multi-team formats such as 2v2v2, once the pinned SC2 build's player/team/port semantics are proven.

SingularityBot and ExampleBot are development foundations bot authors may choose to use. The generic host contract must also admit independent bots that implement the documented runner and SC2API compatibility requirements.

This is a target architecture, not live verified. The exact observer join, PortSet scaling, team mapping, and result semantics remain proof gates. See [OBSERVER_HOST_DESIGN.md](OBSERVER_HOST_DESIGN.md) and [SC2_RUNTIME_PROTOCOL.md](SC2_RUNTIME_PROTOCOL.md).

## Observer process-plan status

The process-plan contract is a validated intermediate representation, not an executable runtime. It has one observer process at ordinal zero, with no participant identity or participant listener, and exactly one CreateGame authority. Participant SC2 clients have distinct participant identities/listener ports and no CreateGame authority; each participant has one corresponding runner. Contract checks exercise participant counts through the 64-entrant upper bound.

The existing process supervisor remains the old two-client competitor-host implementation. It must not be described as observer-hosted, and the observer plan must not be wired into production launch until a real controller can own CreateGame, observer join/readiness, match lifecycle, and authoritative result/replay capture.

## Live protocol proof

The first implementation increment now exists at `tools/sc2-probe/`: an explicitly opt-in three-process/API bootstrap using Blizzard's generated protobuf package. It preflights trusted paths and listener ports, launches three isolated SC2 processes, sends RequestPing to each API endpoint, records build metadata/logs in a versioned manifest, and performs bounded process cleanup. CI executes only unit tests; it never launches SC2.

This is not yet the CreateGame/observer/player join proof. The PortSet payload, information isolation, authoritative result/replay path, and complete match lifecycle remain unimplemented. A bootstrap pass must not be called an observer-topology pass.

The live proof is the next engineering milestone. [SC2_RUNTIME_PROTOCOL.md](SC2_RUNTIME_PROTOCOL.md) now defines an opt-in standalone probe acceptance contract. It must remain separate from normal CI and production runtime until it can:

- use an exact pinned SC2 build and trusted map;
- launch a dedicated host plus two isolated player SC2 clients;
- exercise CreateGame, observer join, and both player joins using an experimentally verified order and complete PortSet payload;
- prove observer identity and distinct player identities;
- test player/observer information separation;
- capture observer-authoritative terminal results and a readable replay;
- retain versioned machine-readable evidence and raw logs;
- prove bounded cleanup for success and failure paths.

The probe is not implemented yet. Do not interpret the documented acceptance contract as a working harness or a live result. Its exact protocol client/protobuf implementation choice must be resolved before coding the probe; do not add a guessed protocol dependency or copy a bot-side adapter into ServerSC2.

## Next implementation gates

1. Extend the implemented three-process/API bootstrap with a protocol-driven CreateGame and observer/player join sequence, using live-verified PortSet semantics; keep CI-safe preflight/evidence tests separate from live SC2.
2. Prove dedicated host CreateGame followed by observer join against the pinned SC2 build; confirm all-player observer semantics and join ordering.
3. Derive and live-verify the complete PortSet footprint for observer plus N player clients.
4. Confirm SC2 player/team setup and result semantics for 1v1, team matches, FFA, and multi-team formats.
5. Replace two-participant assumptions with validated variable participant/team records across adapter, lease, runtime, and tests.
6. Define a generic runner contract independent of SingularityBot-specific CLI flags; test SingularityBot and an independent runner.
7. Change the process supervisor to one observer plus N player instances and N runners. Remove competitor-host authority.
8. Implement trusted immutable artifact resolution and SHA-256 verification before any runner launch.
9. Capture observer-authoritative format-aware results and replay, correlated to all player IDs, entrants, teams, map/game version, and build hashes.
10. Run live SC2 integration at 1v1 and at least one team/FFA format, then add durable append-oriented session history and idempotent ServerApp result handoff.

## Verification and boundaries

CI checks out ServerApp's development source, installs .NET 8, builds ServerSC2.Core and the adapter, and runs contract checks. CI success proves compilation and those contracts, not live SC2 integration. No live SC2 proof has been performed for the observer-host topology or additional match formats.

No NuGet publishing, merge, release, deployment, or branch deletion has been performed. No database or ORM has been introduced.
