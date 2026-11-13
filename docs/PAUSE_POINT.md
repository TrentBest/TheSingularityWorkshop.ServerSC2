# ServerSC2 Pause Point

## Current state

- Repository work is on `development`; branches are exactly `master` and `development`.
- `ServerSC2.Core` contains trusted profile validation and bounded process-local game/start port leases.
- `ServerSC2.ServerAppAdapter` implements ServerApp.Core's `IGameSessionAdapter` contract through a source project reference. It validates game and adapter-version identity, translates the immutable two-participant assignment into a typed SC2 launch request, and retains/releases its port lease with session lifecycle.
- `ISc2SessionRuntime` is an injected boundary only. No concrete SC2 process supervisor or bot launcher exists yet.
- Contract checks cover profile/lease behavior and the adapter's assignment mapping, wrong-game rejection, and startup-failure lease cleanup.

## Verification

The GitHub Actions workflow now checks out ServerApp's `development` source alongside ServerSC2, builds both core and adapter projects, and runs the contract-check executable. The latest commit status query did not return a check result. The current environment has no .NET SDK, so the authored checks have not been executed locally. Do not report them as passing until CI provides evidence.

## Next work

1. Verify the exact current SingularityBot ladder-client implementation and its port topology.
2. Resolve the SC2API multiplayer process topology from the official protocol and the bot implementation together.
3. Implement the trusted process supervisor with fixed host-owned executable paths and argument construction.
4. Launch both independently admitted bot builds and establish protocol-level readiness.
5. Capture authoritative result and replay evidence, then add append-oriented durable session history.

See [the architecture](ARCHITECTURE.md) and [SC2 runtime protocol notes](SC2_RUNTIME_PROTOCOL.md).

## Boundaries

No NuGet publishing, merge, release, deployment, or branch deletion has been performed. No database or ORM has been introduced.
