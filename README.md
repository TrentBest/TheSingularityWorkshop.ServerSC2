<!-- The Singularity Workshop moniker -->
<p align="center"><a href="https://github.com/TrentBest"><img src="https://raw.githubusercontent.com/TrentBest/TheSingularityWorkshop.Visualize/development/docs/assets/moniker.svg" alt="The Singularity Workshop animated moniker" width="720" /></a></p>

# ServerSC2

**StarCraft II-specific competitive game-session host.** ServerSC2 is the game integration layer for the Workshop's competitive ladder—not a replacement for the reusable ServerApp platform and not a home for bot strategy.

## Responsibility boundary

- **ServerApp** owns game-neutral competition contracts, immutable bot-build admission, trusted role selection, and the generic game-session lifecycle contract.
- **ServerSC2** owns StarCraft II session configuration, game-specific slot and port allocation, SC2 process supervision, bot attachment, readiness, termination, replay capture, and authoritative game-result evidence.
- **SimulationServer** is the runtime model: host one authoritative SC2 simulation and launch/connect two independent bot runners from their admitted immutable builds.
- **Experiences** remains the source of reusable, versioned MicroBundles. ServerSC2 may compose approved bundles through FSM_COS; it does not duplicate their domain implementations.
- **SingularityBot** remains an independently launched player runtime. Its strategy and bot-side SC2 protocol adapter do not move into this repository.
- **FSM_COS** composes approved MicroBundles. **FSM_Foundry** executes host-authored workflows. **FSM_API** supplies runtime state/context primitives.

The first target is a controlled local 1v1 vertical slice. No public matchmaking, ratings, tournament system, or production anti-cheat claim is implied by this repository's existence.

## Trust model

Only trusted host configuration may choose the SC2 installation, maps, runtime roots, process limits, and adapter versions. A client or bot must never supply executable paths, arbitrary arguments, bundle IDs, or workflow handlers. Every match pins immutable participant build identities and a versioned game profile before launch.

## Development

Work on development. Keep master aligned with the last released state; do not publish, merge, release, or deploy without explicit authorization.

The current foundation includes validated server profiles, process-local port-pair leases, and a ServerApp IGameSessionAdapter bridge. The bridge is wired to an injected ISc2SessionRuntime contract; the concrete SimulationServer process supervisor and two-runner launcher are not implemented yet. Port leases prevent collisions among this host's own concurrent matches; they are not OS-level socket reservations.

See [the architecture](docs/ARCHITECTURE.md), [SimulationServer orchestration](docs/SIMULATION_SERVER.md), [SC2 runtime protocol notes](docs/SC2_RUNTIME_PROTOCOL.md), and [the pause point](docs/PAUSE_POINT.md).

## Status

Next: prove the two-runner GamePort/StartPort topology, then implement the trusted SC2 process supervisor, two independent bot launches, protocol readiness, replay/result evidence, and durable session journal.

---

<p align="center"><img src="https://raw.githubusercontent.com/TrentBest/FSM_API/master/Documentation/Branding/TheSingularityWorkshop.png" alt="The Singularity Workshop" width="360" /></p>
