<!-- The Singularity Workshop moniker -->
<p align="center"><a href="https://github.com/TrentBest"><img src="https://raw.githubusercontent.com/TrentBest/TheSingularityWorkshop.Visualize/development/docs/assets/moniker.svg" alt="The Singularity Workshop animated moniker" width="720" /></a></p>

# ServerSC2

**StarCraft II-specific competitive game-session host.** ServerSC2 is the game integration layer for the Workshop's competitive ladder—not a replacement for the reusable ServerApp platform and not a home for bot strategy.

## Responsibility boundary

- **ServerApp** owns game-neutral competition contracts, immutable bot-build admission, trusted role selection, and the generic game-session lifecycle contract.
- **ServerSC2** owns StarCraft II session configuration, game-specific slot and port allocation, SC2 process supervision, bot attachment, readiness, termination, replay capture, and authoritative game-result evidence.
- **SimulationServer** is the target runtime model: one neutral simulation-host/observer creates and observes the match, while each admitted entrant receives an isolated player SC2 process and independently supervised runner. The current production supervisor is still the legacy two-player competitor-host implementation; the observer topology is not yet live-proven.
- **Experiences** remains the source of reusable, versioned MicroBundles. ServerSC2 may compose approved bundles through FSM_COS; it does not duplicate their domain implementations.
- **SingularityBot** remains an independently launched player runtime and a bot-authoring foundation. Its strategy and bot-side SC2 protocol adapter do not move into this repository, and it is not a required host dependency.
- **FSM_COS** composes approved MicroBundles. **FSM_Foundry** executes host-authored workflows. **FSM_API** supplies runtime state/context primitives.

The first target is a controlled local 1v1 vertical slice. No public matchmaking, ratings, tournament system, or production anti-cheat claim is implied by this repository's existence.

## Trust model

Only trusted host configuration may choose the SC2 installation, maps, runtime roots, process limits, and adapter versions. A client or bot must never supply executable paths, arbitrary arguments, bundle IDs, or workflow handlers. Every match pins immutable participant build identities and a versioned game profile before launch.

## Development

Work on development. Keep master aligned with the last released state; do not publish, merge, release, or deploy without explicit authorization.

The current foundation includes validated server profiles, a scaled observer-plus-participants port reservation model, a ServerApp IGameSessionAdapter bridge, an observer-oriented process-plan contract, and an initial legacy process supervisor. That supervisor still launches two SC2 instances plus two runners and grants CreateGame authority to one participant; it is not the target observer topology. It waits for both structured join acknowledgements, but runner result markers are diagnostics only and cannot complete a match. Completion is fail-closed until host-authoritative SC2 terminal results and validated replay evidence are both available. The trusted artifact resolver and live-SC2, result/replay, and cleanup proofs remain outstanding. Port reservations are process-local and are not OS-level socket reservations.

See [the architecture](docs/ARCHITECTURE.md), [SimulationServer orchestration](docs/SIMULATION_SERVER.md), [SC2 runtime protocol notes](docs/SC2_RUNTIME_PROTOCOL.md), [observer-host design](docs/OBSERVER_HOST_DESIGN.md), and [the pause point](docs/PAUSE_POINT.md).

## Status

Next: extend the standalone, explicitly opt-in SC2 protocol probe described in [SC2_RUNTIME_PROTOCOL.md](docs/SC2_RUNTIME_PROTOCOL.md). The first bootstrap increment now preflights trusted inputs, launches three isolated SC2 processes, pings each protobuf API endpoint, records build metadata, and performs bounded cleanup; it does not yet create or join a game. It must prove CreateGame, observer join, two player joins, observer-authoritative results/replay, information isolation, and bounded cleanup against a pinned SC2 build before the production supervisor topology changes. A submission queue and cup progression remain later ServerApp competition-policy work; they are not prerequisites for proving the local match protocol.

---

<p align="center"><img src="https://raw.githubusercontent.com/TrentBest/FSM_API/master/Documentation/Branding/TheSingularityWorkshop.png" alt="The Singularity Workshop" width="360" /></p>
