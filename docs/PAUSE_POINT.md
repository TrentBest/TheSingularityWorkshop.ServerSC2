# ServerSC2 Pause Point

## Current state

- Repository work is on development; branches are exactly master and development.
- ServerSC2.Core validates the complete 1v1 port footprint and atomically leases two distinct SC2 listener ports plus one shared five-port multiplayer block per match.
- ServerSC2.ServerAppAdapter implements ServerApp.Core's IGameSessionAdapter contract through a source project reference. It validates game and adapter-version identity, maps the first immutable participant to the trusted host role and the second to the joiner role, assigns distinct listener ports, and retains/releases the match lease with session lifecycle.
- `Sc2ProcessSessionRuntime` is the concrete `ISc2SessionRuntime` process supervisor. It launches two SC2 instances and two admitted runner executables, waits for both structured join acknowledgements, observes both terminal result markers, and owns process-tree cleanup.
- `ISc2BotRunnerResolver` is the trusted artifact-resolution boundary. Its implementation must resolve immutable build IDs and verify each artifact against its admitted SHA-256; this repository does not yet provide the artifact store/resolver.
- The intended runtime is a SimulationServer hosting one authoritative multiplayer match through two separate SC2 instances, with two independently launched SingularityBot runners.
- Contract checks cover profile/lease behavior, adapter assignment mapping, wrong-game rejection, startup-failure lease cleanup, and rejection of a runtime status carrying the wrong admitted match ID. The process supervisor is compiled by CI but has not yet been exercised against a live SC2 installation.

## Verified integration facts

- Blizzard's SC2API multiplayer flow launches two SC2 instances on separate listener ports, designates one host to issue CreateGame, and joins both clients to that game.
- Each SingularityBot runner connects to its own SC2 listener endpoint using a distinct GamePort.
- SingularityBot development now has an explicit designated-host mode: `--CreateGame --Map <trusted-map-path>` creates a two-participant multiplayer game on the host SC2 instance before that runner performs its normal ladder join. The other runner joins without the host flag. This source change is not yet live-SC2 verified.
- Blizzard's reference coordinator passes the same match-level multiplayer PortSet structure to both clients. Both runners therefore use the same StartPort base; its `+1..+5` derived ports are shared match resources, not separately allocated per runner.
- ServerSC2 now leases two distinct SC2 listener ports plus the shared five-port multiplayer block as one atomic match footprint. The lease is process-local and does not reserve OS sockets.

See SIMULATION_SERVER.md and SC2_RUNTIME_PROTOCOL.md.

## Verification

The GitHub Actions workflow checks out ServerApp's development source, installs .NET 8 with `actions/setup-dotnet@v4`, builds ServerSC2.Core and the adapter, and runs contract checks. CI run 61 completed successfully after the match-identity guard and its contract test were added; the earlier process-supervisor and player-ID correlation revisions also passed. SingularityBot CI passed for the structured lifecycle markers and fail-closed CreateGame/JoinGame response handling. This environment has no local .NET SDK, so no local build was run. CI success proves compilation and contract checks, not live SC2 integration.

## Next work

1. Verify the host-side `--CreateGame --Map` path against a runnable SC2 build and confirm both runners join the same game with distinct player IDs.
2. Supply the trusted `ISc2BotRunnerResolver` backed by ServerApp's immutable build registry/artifact store; verify content hashes before launch.
3. Persist the result values and map them to the immutable participant assignments; current runtime checks that each result marker's player ID matches that runner's join acknowledgement but does not yet expose durable result evidence.
4. Capture and validate SC2-authoritative result evidence and save the replay, binding both to match/session, map/game version, and build hashes.
5. Exercise timeout, early exit, partial startup, cancellation, and host disposal; verify all four process trees are stopped and ports released.
6. Add append-oriented durable session history after lifecycle evidence is trustworthy.

## Boundaries

No NuGet publishing, merge, release, deployment, or branch deletion has been performed. No database or ORM has been introduced.
