# ServerSC2 Architecture

## Purpose

ServerSC2 is the StarCraft II-specific game-session host. Its runtime is a SimulationServer: it hosts an authoritative SC2 simulation and connects two independent bot runner processes to that match.

~~~text
ServerApp (game-neutral competition host)
  -> IGameSessionAdapter / immutable MatchAssignment
  -> ServerSC2.ServerAppAdapter
  -> SimulationServer / ISc2SessionRuntime
       + SC2 multiplayer host instance (distinct listener)
       + SC2 multiplayer joining instance (distinct listener)
       + SingularityBot runner A (admitted build A)
       + SingularityBot runner B (admitted build B)
       + readiness, lifecycle, replay, result evidence
  -> approved FSM_COS RuntimeAssembly / MicroBundles where useful
  -> Experiences (reusable versioned artifacts)
~~~

FSM_COS composes approved MicroBundles. ServerSC2 configures and supervises the SC2 session. FSM_Foundry remains the workflow executor. Do not conflate bundle composition, process provisioning, and workflow execution.

## Ownership

| Concern | Owner |
|---|---|
| Competition definitions, immutable match assignments, bot-build admission | ServerApp |
| Generic IGameSessionAdapter contract and lifecycle validation | ServerApp.Core |
| SC2 maps, game version, player slots, port topology, launch policy | ServerSC2 |
| Both SC2 instance lifecycles, multiplayer host/join orchestration, health/readiness | ServerSC2 SimulationServer |
| Independent bot runner processes and session attachment | ServerSC2 SimulationServer |
| Bot strategy and bot-side SC2 protocol adapter | SingularityBot |
| Reusable MicroBundle artifacts | Experiences |
| Composition of approved bundles | FSM_COS |
| Host-authored workflow execution | FSM_Foundry |

ServerSC2 must not copy the generic bot-build registry or implement its own competing matchmaking/rating system.

## Trust and configuration

The SC2 server profile is trusted deployment configuration. It pins the adapter/game version, map identity, bounded port ranges, and maximum concurrency. It is not a client-supplied match payload. Executable paths, environment allowlists, process limits, and working directories must come from trusted host configuration and artifact resolution—not from participant metadata.

Every session is built from an immutable admitted match assignment. A match uses two SC2 instances with distinct WebSocket listener ports. A match must not become Ready until the host-created multiplayer session and both required participant runners have independently passed protocol-level readiness checks.

## ServerApp adapter bridge

ServerSC2.ServerAppAdapter implements the game-neutral IGameSessionAdapter contract from ServerApp.Core. It accepts only an admitted immutable assignment, verifies the game and pinned adapter version, maps the two participant build references into a typed launch request, and holds a bounded port lease for the session lifetime.

The adapter depends on ServerApp.Core through a source project reference, not a published package. CI checks out ServerApp's development branch alongside this repository. The dependency is intentionally isolated in this adapter project; ServerSC2.Core remains independent of ServerApp.

ISc2SessionRuntime is an injected trusted boundary. The bridge does not yet launch SC2 or participant processes. The concrete SimulationServer must own executable resolution, fixed argument construction, process-tree supervision, protocol readiness, replay/result capture, and bounded cleanup. Until that implementation exists, no actual match can be started by this repository.

## First implementation boundary

The core provides:
- validation of trusted SC2 server profiles;
- bounded, process-local allocation of game/start port resources (current single-pair model is provisional and not yet topology-correct);
- explicit lease disposal and reuse;
- a ServerApp adapter bridge with typed launch requests and session-scoped port ownership.

A lease is not an OS socket reservation. The process supervisor must still handle bind failures, verify the actual game process, and clean up all child processes and leases on every terminal path. The current one-game-port/one-start-base lease is insufficiently specified for two SC2 listener processes and the protocol's shared/server/client port sets; do not use it for real matches until the complete footprint is proven.

## First vertical slice

1. Resolve an approved ServerApp role and trusted SC2 profile.
2. Validate a 1v1 immutable match assignment and exact bot-build artifacts.
3. Allocate a topology-correct match-scoped port set.
4. Start the authoritative SC2 simulation host using fixed, host-owned arguments.
5. Start two independent bot processes using their exact admitted builds and the verified ladder connection contract.
6. Verify simulation and both participant readiness.
7. Observe terminal game state and preserve replay plus host-authored result evidence.
8. Return a validated terminal snapshot to ServerApp.
9. Persist match/session history and accept the result idempotently before rating projection.

Failure at any stage must prevent false readiness or a fabricated result. Cleanup must be bounded, observable, and safe to retry.

## Explicit non-goals

- Bot strategy or build-order policy.
- A second generic competition platform.
- Client-selected executable paths, command lines, MicroBundle identities, or workflow handlers.
- A database/ORM. Durable state should use the ServerApp binary journal/checkpoint approach or a compatible append-oriented host-owned format.
- Public matchmaking, ranking, or tournament features before the local 1v1 evidence chain works.

See SIMULATION_SERVER.md for the concrete two-runner lifecycle and SC2_RUNTIME_PROTOCOL.md for verified facts and unresolved topology.
