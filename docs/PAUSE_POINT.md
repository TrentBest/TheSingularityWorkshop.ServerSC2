# ServerSC2 Pause Point

## Current state

- Repository work is on development; branches are exactly master and development.
- ServerSC2.Core contains trusted profile validation and bounded process-local game/start port leases.
- ServerSC2.ServerAppAdapter implements ServerApp.Core's IGameSessionAdapter contract through a source project reference. It validates game and adapter-version identity, translates the immutable two-participant assignment into a typed SC2 launch request, and retains/releases its port lease with session lifecycle.
- ISc2SessionRuntime is an injected boundary only. No concrete SimulationServer process supervisor or bot launcher exists yet.
- The intended runtime is a SimulationServer hosting one authoritative multiplayer match through two separate SC2 instances, with two independently launched SingularityBot runners.
- Contract checks cover profile/lease behavior and the adapter's assignment mapping, wrong-game rejection, and startup-failure lease cleanup.

## Verified integration facts

- Blizzard's SC2API multiplayer flow launches two SC2 instances on separate listener ports, designates one host to issue CreateGame, and joins both clients to that game.
- SingularityBot's ladder runner connects to one supplied GamePort and issues JoinGameLadder; each runner therefore needs its own SC2 listener endpoint.
- The current SingularityBot RunLadder path does not create the game. Its local mode creates a separate bot-vs-computer game and is not suitable for the 1v1 host.
- JoinGameLadder computes shared/server/client port offsets from StartPort, but the correct shared-vs-distinct StartPort allocation and host WebSocket handoff are not yet proven.

See SIMULATION_SERVER.md and SC2_RUNTIME_PROTOCOL.md.

## Verification

The GitHub Actions workflow checks out ServerApp's development source alongside ServerSC2, builds both core and adapter projects, and runs the contract-check executable. The latest known commit status query did not return a check result. The current environment has no .NET SDK, so the authored checks have not been executed locally. Do not report them as passing until CI provides evidence.

## Next work

1. Close the host CreateGame / bot join WebSocket ownership question against a runnable SC2 build.
2. Prove the StartPort sharing model and calculate the complete non-overlapping port footprint for two SC2 instances plus their multiplayer communication ports.
3. Implement typed per-participant runner launch data and a testable port-footprint allocator.
4. Implement a trusted process supervisor for both SC2 instances and both admitted SingularityBot runners.
5. Establish protocol-level readiness, authoritative result/replay capture, and bounded cleanup.
6. Add append-oriented durable session history after lifecycle evidence is trustworthy.

## Boundaries

No NuGet publishing, merge, release, deployment, or branch deletion has been performed. No database or ORM has been introduced.
