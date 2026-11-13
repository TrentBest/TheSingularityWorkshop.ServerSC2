# ServerSC2 Architecture

## Purpose

ServerSC2 is the StarCraft II-specific SimulationServer. It owns SC2-specific match provisioning, process supervision, protocol readiness, authoritative evidence collection, and cleanup. The target 1v1 topology uses a dedicated simulation-host/observer SC2 process plus two independent player SC2 processes and two admitted bot runners.

```text
ServerApp (game-neutral competition host)
  -> IGameSessionAdapter / immutable MatchAssignment
  -> ServerSC2.ServerAppAdapter
  -> SimulationServer / ISc2SessionRuntime
       + dedicated SC2 simulation host / observer
       + player SC2 instance A + admitted runner A
       + player SC2 instance B + admitted runner B
       + readiness, lifecycle, replay, result evidence
  -> approved FSM_COS RuntimeAssembly / MicroBundles where useful
  -> Experiences (reusable versioned artifacts)
```

The observer-host topology is a target architecture, not yet a live-SC2-verified implementation. See [OBSERVER_HOST_DESIGN.md](OBSERVER_HOST_DESIGN.md) for the candidate protocol sequence and proof gates. The current runtime source still launches the two-player-host topology; do not describe it as observer-hosted until the proof gates close.

FSM_COS composes approved MicroBundles. ServerSC2 configures and supervises the SC2 session. FSM_Foundry remains the workflow executor. Do not conflate bundle composition, process provisioning, and workflow execution.

## Ownership

| Concern | Owner |
|---|---|
| Competition definitions, immutable match assignments, bot-build admission | ServerApp |
| Generic IGameSessionAdapter contract and lifecycle validation | ServerApp.Core |
| SC2 maps, game version, player slots, port topology, launch policy | ServerSC2 |
| Simulation-host/observer and player SC2 process lifecycles, readiness, replay/result capture | ServerSC2 SimulationServer |
| Independent bot runner processes and session attachment | ServerSC2 SimulationServer |
| Bot strategy and bot-side SC2 protocol adapter | SingularityBot |
| Reusable MicroBundle artifacts | Experiences |
| Composition of approved bundles | FSM_COS |
| Host-authored workflow execution | FSM_Foundry |

ServerSC2 must not copy the generic bot-build registry or implement its own competing matchmaking/rating system.

## Trust and configuration

The SC2 server profile is trusted deployment configuration. It pins the adapter/game version, map identity, bounded port ranges, and maximum concurrency. It is not a client-supplied match payload. Executable paths, environment allowlists, process limits, and working directories must come from trusted host configuration and artifact resolution—not from participant metadata.

Every session is built from an immutable admitted match assignment. Each competitor receives a dedicated player SC2 listener and its own runner process. The simulation host is a separate SC2 process and must join as an observer; it is not assigned to either participant. A match must not become Ready until the observer and both player participants have independently passed protocol-level readiness checks.

## ServerApp adapter bridge

ServerSC2.ServerAppAdapter implements the game-neutral IGameSessionAdapter contract from ServerApp.Core. It accepts only an admitted immutable assignment, verifies the game and pinned adapter version, maps the two participant build references into typed launch records, and holds a bounded match-scoped port lease for the session lifetime.

The adapter depends on ServerApp.Core through a source project reference, not a published package. CI checks out ServerApp's development branch alongside this repository. The dependency is intentionally isolated in this adapter project; ServerSC2.Core remains independent of ServerApp.

ISc2SessionRuntime is an injected trusted boundary. The current concrete process runtime still implements the earlier two-SC2-process/two-runner topology. The observer-host implementation must add a third SC2 process with a distinct listener, observer join/readiness, and evidence collection. It must not grant either runner CreateGame authority.

## Port allocation

The current core atomically allocates two distinct SC2 listener ports and one shared five-port multiplayer block. That footprint is not assumed to cover a third SC2 client. The observer topology requires a protocol-derived PortSet allocation for one observer plus two players. The full listener and multiplayer footprint must be represented as one typed match lease, checked for overlap/capacity/overflow, and released on every terminal path.

A lease is process-local; it is not an OS socket reservation. The process supervisor must handle bind failures, verify actual protocol readiness, and clean up all child processes and leases.

## First vertical slice

1. Resolve an approved ServerApp role and trusted SC2 profile.
2. Validate a 1v1 immutable match assignment and exact bot-build artifacts.
3. Resolve both admitted runner artifacts and verify SHA-256 before launch.
4. Allocate a topology-correct match-scoped port set for the observer and two players.
5. Start the dedicated SC2 simulation host, create the match, and join it as an observer.
6. Start two independent player SC2 processes and two bot runners using fixed host-owned arguments.
7. Verify observer readiness and both participant joins, including distinct player IDs correlated to immutable assignments.
8. Observe terminal game state and preserve observer-authored result plus replay evidence.
9. Return a validated terminal snapshot to ServerApp.
10. Persist match/session history and accept the result idempotently before rating projection.

Failure at any stage must prevent false readiness or a fabricated result. Cleanup must be bounded, observable, and safe to retry. No fallback may silently make a competitor the host when the observer role fails.

## Explicit non-goals

- Bot strategy or build-order policy.
- A second generic competition platform.
- Client-selected executable paths, command lines, MicroBundle identities, or workflow handlers.
- A database/ORM. Durable state should use the ServerApp binary journal/checkpoint approach or a compatible append-oriented host-owned format.
- Public matchmaking, ranking, or tournament features before the local 1v1 evidence chain works.
