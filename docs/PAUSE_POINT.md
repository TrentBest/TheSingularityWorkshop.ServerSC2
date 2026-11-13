# ServerSC2 Pause Point

## Current state

- Repository work is on development; branches are exactly master and development.
- ServerSC2.Core contains trusted profile validation and bounded process-local game/start port leases.
- ServerSC2.ServerAppAdapter implements ServerApp.Core's IGameSessionAdapter contract through a source project reference. It validates game and adapter-version identity, translates the immutable two-participant assignment into a typed SC2 launch request, and retains/releases its port lease with session lifecycle.
- ISc2SessionRuntime is an injected boundary only. No concrete SimulationServer process supervisor or bot launcher exists yet.
- The intended runtime is one hosted authoritative SC2 match plus two independently launched SingularityBot runners, not two local single-player games.
- Contract checks cover profile/lease behavior and the adapter's assignment mapping, wrong-game rejection, and startup-failure lease cleanup.

## Verified bot integration

The SingularityBot development source confirms that its runner forwards ladder arguments to GameConnection.RunLadder, which connects to the supplied GamePort and builds SC2 shared/server/client port sets from StartPort. Its local mode launches SC2 and creates a bot-vs-computer game; that is not the competition-host path. The exact allocation/sharing of ports between two runners remains unresolved.

See SIMULATION_SERVER.md and SC2_RUNTIME_PROTOCOL.md.

## Verification

The GitHub Actions workflow checks out ServerApp's development source alongside ServerSC2, builds both core and adapter projects, and runs the contract-check executable. The latest known commit status query did not return a check result. The current environment has no .NET SDK, so the authored checks have not been executed locally. Do not report them as passing until CI provides evidence.

## Next work

1. Prove the exact two-runner SC2 port and process topology from the ladder-manager contract and protocol behavior.
2. Define typed per-participant runner launch data from the immutable assignment.
3. Implement a trusted process supervisor with fixed host-owned executable paths and arguments.
4. Launch both independently admitted bot builds and establish protocol-level readiness.
5. Capture authoritative result and replay evidence, then add append-oriented durable session history.

## Boundaries

No NuGet publishing, merge, release, deployment, or branch deletion has been performed. No database or ORM has been introduced.
