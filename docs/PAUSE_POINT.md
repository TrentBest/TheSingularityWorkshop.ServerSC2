# ServerSC2 Pause Point

## Current state

- Repository work is on development; branches are exactly master and development.
- ServerSC2.Core now reserves N participant listener ports plus a multiplayer block sized for one observer and N player clients. The block uses `2 * (N + 1) + 1` ports with a non-overlapping stride. This remains reservation planning, not live SC2 PortSet proof.
- ServerSC2.ServerAppAdapter implements ServerApp.Core's IGameSessionAdapter contract through a source project reference.
- The current Sc2ProcessSessionRuntime launches two SC2 instances and two admitted runner executables. One participant runner currently receives CreateGame authority; this is the old 1v1 topology and must be replaced. Runner-emitted result markers are diagnostics only and no longer produce Completed. The fail-closed completion gate requires independently validated host-authoritative terminal results AND replay evidence; no live evidence source is wired yet, so the current runtime cannot report successful match completion.
- The current adapter and runtime explicitly reject participant counts other than two. Team IDs are carried in launch records but the runtime does not yet implement team-aware SC2 setup or format-aware results.
- `Sc2MatchProcessPlan` now describes one neutral observer plus N participant SC2 clients and N bot runners. It validates pinned adapter/game/map metadata, participant identity/team/build SHA-256/listener ports, unique IDs/ports, observer-only CreateGame authority, and the complete multiplayer port block. It snapshots caller-owned participant collections before validation so later mutation cannot change the plan. This plan is not yet consumed by the process supervisor.
- ISc2BotRunnerResolver is the trusted artifact-resolution boundary. Its implementation must resolve immutable build IDs and verify each artifact against its admitted SHA-256; this repository does not yet provide the artifact store/resolver.
- Contract checks cover profile/lease behavior, adapter assignment mapping, wrong-game rejection, startup-failure lease cleanup, mismatched runtime identity, observer authority isolation, participant scaling, port/build boundaries, required runtime metadata, mutable-input snapshotting, and null participant rejection.
- The process supervisor is compiled by CI but has not been exercised against a live SC2 installation.

## Agreed target architecture

ServerSC2 is an open host for SC2-compatible bot builds. It must not require a bot to use SingularityBot.

A match assignment defines N entrants, immutable build identities, a competition format, and team grouping. The target topology is one dedicated simulation host/observer plus N player SC2 processes and N independently supervised bot runners:

1. Dedicated simulation host / observer: creates the multiplayer game, joins as observer, monitors lifecycle, and captures authoritative result/replay evidence.
2. One player SC2 instance and one runner per entrant.
3. The observer has no competitor identity. No runner gets CreateGame authority or access to another runner's player endpoint.
4. Formats include 1v1, 2v2, 3v3, FFA, and multi-team formats such as 2v2v2, once the pinned SC2 build's player/team/port semantics are proven.

SingularityBot and ExampleBot are development foundations bot authors may choose to use. The generic host contract must also admit independent bots that implement the documented runner and SC2API compatibility requirements.

This is a target architecture, not live verified. The exact observer join, PortSet scaling, team mapping, and result semantics remain proof gates. See [OBSERVER_HOST_DESIGN.md](OBSERVER_HOST_DESIGN.md).

## Observer process-plan status

The process-plan contract is now a validated intermediate representation, not an executable runtime. It has one observer process at ordinal zero, with no participant identity or participant listener, and exactly one CreateGame authority. Participant SC2 clients have distinct participant identities/listener ports and no CreateGame authority; each participant has one corresponding runner. The contract currently exercises participant counts through the 64-entrant upper bound.

The existing process supervisor remains the old two-client competitor-host implementation. It must not be described as observer-hosted, and the observer plan must not be wired into production launch until a real controller can own CreateGame, observer join/readiness, match lifecycle, and authoritative result/replay capture. This separation intentionally prevents a data-only plan from being mistaken for a working observer runtime.

## Next implementation gates

1. Prove dedicated host CreateGame followed by observer join against the pinned SC2 build; confirm all-player observer semantics.
2. Derive and live-verify the complete PortSet footprint for observer plus N player clients.
3. Confirm SC2 player/team setup and result semantics for 1v1, team matches, FFA, and multi-team formats.
4. Replace two-participant assumptions with validated variable participant/team records across adapter, lease, runtime, and tests.
5. Define a generic runner contract independent of SingularityBot-specific CLI flags; test SingularityBot and an independent runner.
6. Change the process supervisor to one observer plus N player instances and N runners. Remove competitor-host authority.
7. Implement trusted immutable artifact resolution and SHA-256 verification before any runner launch.
8. Capture observer-authoritative format-aware results and replay, correlated to all player IDs, entrants, teams, map/game version, and build hashes.
9. Add contract tests for observer readiness, participant/team identity, information isolation, fairness metadata, startup failure, timeout, cancellation, early exit, and complete process-tree cleanup.
10. Run live SC2 integration at 1v1 and at least one team/FFA format, then add durable append-oriented session history and idempotent ServerApp result handoff.

## Verification and boundaries

CI checks out ServerApp's development source, installs .NET 8, builds ServerSC2.Core and the adapter, and runs contract checks. CI success proves compilation and those contracts, not live SC2 integration. No live SC2 proof has been performed for the observer-host topology or the additional match formats.

No NuGet publishing, merge, release, deployment, or branch deletion has been performed. No database or ORM has been introduced.
