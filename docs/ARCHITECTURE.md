# ServerSC2 Architecture

## Purpose

ServerSC2 is the StarCraft II-specific SimulationServer. It hosts matches for independently developed, protocol-compatible SC2 bots. It owns SC2-specific match provisioning, process supervision, readiness, authoritative evidence collection, and cleanup.

The target topology is one dedicated simulation-host/observer process plus one independent player SC2 process and bot runner per admitted entrant. Match formats are data-driven: 1v1, 2v2, 3v3, FFA, multi-team formats such as 2v2v2, and other SC2-supported layouts. The host must not encode a fixed two-participant or single-opponent assumption.

```text
ServerApp (game-neutral competition host)
  -> immutable MatchAssignment (entrants, builds, teams, format)
  -> ServerSC2.ServerAppAdapter
  -> SimulationServer / ISc2SessionRuntime
       + dedicated SC2 simulation host / observer
       + N player SC2 instances + N independent bot runners
       + readiness, lifecycle, replay, result evidence
  -> approved FSM_COS RuntimeAssembly / MicroBundles where useful
  -> Experiences (reusable versioned artifacts)
```

The observer-host topology is a target architecture, not yet live-SC2-verified. See [OBSERVER_HOST_DESIGN.md](OBSERVER_HOST_DESIGN.md) for process roles, generic bot compatibility, fairness, and proof gates. Current runtime source still implements the earlier two-participant competitor-host path; do not describe it as observer-hosted or format-general until the proof gates close.

FSM_COS composes approved MicroBundles. ServerSC2 configures and supervises the SC2 session. FSM_Foundry remains the workflow executor. Do not conflate bundle composition, process provisioning, and workflow execution.

## Ownership

| Concern | Owner |
|---|---|
| Competition definitions, immutable match assignments, entrant/build admission, team/format policy | ServerApp |
| Generic IGameSessionAdapter contract and lifecycle validation | ServerApp.Core |
| SC2 maps, game version, player slots, team mapping, port topology, launch policy | ServerSC2 |
| Observer and player SC2 process lifecycles, readiness, replay/result capture | ServerSC2 SimulationServer |
| Independent bot runner processes and session attachment | ServerSC2 SimulationServer |
| Bot strategy, examples, and optional bot-side SC2 protocol adapter | Each bot implementation; SingularityBot is one toolkit/example |
| Reusable MicroBundle artifacts | Experiences |
| Composition of approved bundles | FSM_COS |
| Host-authored workflow execution | FSM_Foundry |

ServerSC2 must not copy the generic bot-build registry or implement its own competing matchmaking/rating system. It must not require entrants to use SingularityBot assemblies or strategy.

## Generic bot contract

A bot entrant supplies an immutable admitted build artifact and implements the documented host-facing runner contract. The contract defines how the host launches it, supplies its assigned SC2 listener and bounded configuration, observes protocol-level join identity, and collects terminal diagnostics/results. The bot speaks the supported SC2API protocol through its own implementation or a bundled adapter.

SingularityBot and ExampleBot are first-class development foundations. Developers can use your SC2 protocol/client code and strategy examples to create their own behaviors, but the ladder host must accept any independently implemented bot that satisfies the same compatibility contract. SingularityBot-specific CLI flags, strategy assumptions, or opponent identity parameters must not leak into ServerSC2's generic orchestration layer.

Executable paths, environment allowlists, process limits, and working directories come from trusted host configuration and artifact resolution—not participant metadata.

## Trust and configuration

The SC2 server profile is trusted deployment configuration. It pins the adapter/game version, map identity, bounded port ranges, and maximum concurrency. It is not a client-supplied match payload.

Every session is built from an immutable admitted match assignment. The assignment supplies the entrant identities, immutable build references, format, and team grouping. ServerSC2 validates those values against the selected SC2 profile and supported format before starting processes.

Each competitor receives a dedicated player SC2 listener and its own runner process. The simulation host is a separate SC2 process and must join as an observer; it is not assigned to any entrant. A match must not become Ready until the observer and every player participant have independently passed protocol-level readiness checks.

## ServerApp adapter bridge

ServerSC2.ServerAppAdapter implements the game-neutral IGameSessionAdapter contract from ServerApp.Core. It accepts only an admitted immutable assignment, verifies the game and pinned adapter version, maps every entrant build reference and team assignment into typed launch records, and holds a bounded match-scoped port lease for the session lifetime.

The adapter depends on ServerApp.Core through a source project reference, not a published package. CI checks out ServerApp's development branch alongside this repository. The dependency is intentionally isolated in this adapter project; ServerSC2.Core remains independent of ServerApp.

ISc2SessionRuntime is an injected trusted boundary. The current concrete process runtime still implements the earlier two-SC2-process/two-runner competitor-host topology. The target implementation must add an observer process, one player process per entrant, observer join/readiness, and evidence collection. It must not grant any runner CreateGame authority.

## Port allocation

The current core atomically allocates two distinct SC2 listener ports and one shared five-port multiplayer block. That footprint is not assumed to cover an observer plus arbitrary participant count. The target topology requires a protocol-derived PortSet allocation parameterized by the total SC2 client count.

The full listener and multiplayer footprint must be represented as one typed match lease, checked for overlap/capacity/overflow, and released on every terminal path. A lease is process-local; it is not an OS socket reservation. The process supervisor must handle bind failures, verify actual protocol readiness, and clean up all child processes and leases.

## First vertical slice

1. Validate a trusted SC2 profile and an immutable assignment with at least two entrants, explicit format, and team assignments.
2. Resolve every admitted runner artifact and verify SHA-256 before launch.
3. Validate that the selected map/game version supports the requested player/team format.
4. Allocate a topology-correct match-scoped port set for observer and all player clients.
5. Start the dedicated SC2 simulation host, create the match, and join as an observer.
6. Start one independent player SC2 process and one runner per entrant using fixed host-owned arguments.
7. Verify observer readiness and all participant joins, including unique player IDs correlated to immutable entrant/build/team assignments.
8. Observe terminal game state and preserve observer-authored result plus replay evidence.
9. Return a validated format-aware terminal snapshot to ServerApp.
10. Persist match/session history and accept the result idempotently before rating projection.

Failure at any stage must prevent false readiness or a fabricated result. Cleanup must be bounded, observable, and safe to retry. No fallback may silently make a competitor the host when the observer role fails.

## Explicit non-goals

- Bot strategy or build-order policy.
- A second generic competition platform.
- Client-selected executable paths, command lines, MicroBundle identities, or workflow handlers.
- A database/ORM. Durable state should use the ServerApp binary journal/checkpoint approach or a compatible append-oriented host-owned format.
- Public matchmaking, ranking, or tournament features before the local observer/result evidence chain works.
