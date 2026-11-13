# ServerSC2 Pause Point

## Current state

- Repository work is on development; branches are exactly master and development.
- ServerSC2.Core validates the complete 1v1 port footprint and atomically leases two distinct SC2 listener ports plus one shared five-port multiplayer block per match.
- ServerSC2.ServerAppAdapter implements ServerApp.Core's IGameSessionAdapter contract through a source project reference. It validates game and adapter-version identity, maps the first immutable participant to the trusted host role and the second to the joiner role, assigns distinct listener ports, and retains/releases the match lease with session lifecycle.
- ISc2SessionRuntime is an injected boundary only. No concrete SimulationServer process supervisor or bot launcher exists yet.
- The intended runtime is a SimulationServer hosting one authoritative multiplayer match through two separate SC2 instances, with two independently launched SingularityBot runners.
- Contract checks cover profile/lease behavior and the adapter's assignment mapping, wrong-game rejection, and startup-failure lease cleanup.

## Verified integration facts

- Blizzard's SC2API multiplayer flow launches two SC2 instances on separate listener ports, designates one host to issue CreateGame, and joins both clients to that game.
- Each SingularityBot runner connects to its own SC2 listener endpoint using a distinct GamePort.
- SingularityBot development now has an explicit designated-host mode: `--CreateGame --Map <trusted-map-path>` creates a two-participant multiplayer game on the host SC2 instance before that runner performs its normal ladder join. The other runner joins without the host flag. This source change is not yet live-SC2 verified.
- Blizzard's reference coordinator passes the same match-level multiplayer PortSet structure to both clients. Both runners therefore use the same StartPort base; its `+1..+5` derived ports are shared match resources, not separately allocated per runner.
- The current ServerSC2 allocator remains insufficient: it must lease two distinct SC2 listener ports plus the shared five-port multiplayer block as one atomic match footprint.

See SIMULATION_SERVER.md and SC2_RUNTIME_PROTOCOL.md.

## Verification

The GitHub Actions workflow checks out ServerApp's development source alongside ServerSC2, builds both core and adapter projects, and runs the contract-check executable. The latest known commit status query did not return a check result. The current environment has no .NET SDK, so the authored checks have not been executed locally. Do not report them as passing until CI provides evidence.

## Next work

1. Run the new host-side `--CreateGame --Map` path against a runnable SC2 build and verify both runner joins.
2. Replace the current lease with an atomic footprint of two distinct SC2 listener ports plus one shared StartPort base and offsets `+1..+5`.
3. Implement typed per-participant runner launch data (including host designation) and allocator contract tests.
4. Implement a trusted process supervisor for both SC2 instances and both admitted SingularityBot runners.
5. Establish protocol-level readiness, authoritative result/replay capture, and bounded cleanup.
6. Add append-oriented durable session history after lifecycle evidence is trustworthy.

## Boundaries

No NuGet publishing, merge, release, deployment, or branch deletion has been performed. No database or ORM has been introduced.
