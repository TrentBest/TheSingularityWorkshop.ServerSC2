# SC2 Match Topology and Observer Integration

## Decision and current integration candidate

ServerSC2 hosts arbitrary SC2 bot competitions, not just 1v1. A match is defined by an immutable set of admitted bot entrants and a trusted competition format. Supported formats should include 1v1, 2v2, 3v3, FFA, and multi-team formats such as 2v2v2, subject to the pinned SC2 build's actual player, team, and networking limits.

**The current cross-repository integration candidate is participant-hosted game creation:** Participant A's SC2 connection issues `CreateGame` and then joins as Participant A; Participant B and every additional entrant join from their own SC2 processes; an independent observer joins from its own SC2 process. Participant A remains an ordinary competitor and must not receive observer data or authority over another entrant. The observer is infrastructure, never a competitor, and owns read-only observation, terminal-result collection, and replay capture.

This candidate is grounded in the SingularityBot runner contract and source inspection, and is the sequence selected in ServerSC2 issue #1. It is **not live-proven**. Do not substitute the earlier observer-created-game sequence as the integration contract, and do not describe this topology as operational until the pinned-build proof gates below pass. If later protocol evidence requires a different sequence, update both repositories' versioned contracts and tests together before production wiring.

The number of competitors and their team grouping come from the immutable match assignment. ServerSC2 must not hard-code two participants, a single opponent, or a binary win/loss model. The exact SC2 player/team setup mapping must be verified against the pinned game build before each format is enabled.

## Process roles

| Process | Responsibility | Authority |
|---|---|---|
| Participant A SC2 instance | Create the multiplayer game and join as Participant A; expose only Participant A's player listener | Ordinary entrant; no observer privileges or cross-entrant access |
| Independent observer SC2 instance | Join the created game as observer, monitor lifecycle, collect replay/result evidence | Match observation only; no player actions |
| Player SC2 instance per remaining entrant | Expose that entrant's SC2API listener and provide its observation/action channel | That entrant's game session only |
| Bot runner per entrant | Connect only to its assigned player listener and submit actions for that entrant | That entrant only |

These are independently supervised processes, not necessarily separate physical machines. A single trusted host can supervise them locally at first. Process and endpoint boundaries should permit later placement on separate workers.

## Bot compatibility and open ladder

ServerSC2 is a host for compatible SC2 bots, not a SingularityBot-only host.

- Admission identifies an immutable bot build and its content hash. The artifact may be built with SingularityBot, ExampleBot, or an independent implementation.
- The host-facing contract is a documented runner launch/attachment contract: trusted executable artifact, fixed host-supplied arguments or environment, assigned SC2 listener, bounded working directory/resources, and structured join/result evidence.
- A bot must implement or be packaged behind that contract and speak the supported SC2API protocol. It does not need to reference SingularityBot assemblies or inherit its strategy.
- SingularityBot is a first-class example and development toolkit: bot developers can reuse its protocol adapter, ExampleBot foundations, and strategy infrastructure to create their own behaviors. Those are developer conveniences, not ladder admission requirements.
- ServerSC2 must not copy SingularityBot strategy or require its private CLI flags such as `--OpponentId`. Any SingularityBot-specific adapter belongs in the bot package or an explicit compatibility shim, outside the generic host contract.
- Artifact resolution and SHA-256 verification remain host-owned. Never accept arbitrary executable paths or command lines from entrant metadata.

## Candidate startup sequence

1. Validate the immutable ServerApp match assignment, all admitted build identities, trusted map/game profile, format, participant count, and team assignments.
2. Resolve and verify every runner artifact by immutable build identity and SHA-256 before starting any process.
3. Validate that the selected format and team layout are supported by the pinned SC2 version.
4. Atomically lease one distinct SC2 listener port per entrant plus one observer listener, and the complete multiplayer PortSet footprint required by the SC2 clients.
5. Start Participant A's SC2 process with its assigned listener.
6. Launch Participant A's runner in the versioned create-and-join mode: it connects to its own listener, issues CreateGame for the trusted multiplayer map and exact supported player/team setup, then joins as Participant A.
7. Start one independent player SC2 process per remaining entrant and launch each runner with only its assigned listener. Each joins the already-created game; no runner receives another entrant's endpoint.
8. Start the independent observer SC2 process with its own listener and join as observer, initially investigating `observed_player_id = 0` for the all-player observer perspective.
9. Supply the protocol-derived, correctly constructed match PortSet configuration to each client as required by the pinned SC2 build.
10. Require observer readiness and every player join acknowledgement. Validate unique player IDs and bind each ID to the immutable entrant/build/team assignment.
11. Observe authoritative game lifecycle and terminal results from the observer channel. Save replay and diagnostics under the immutable match/session identity.
12. Stop all runners and SC2 process trees, then release the complete lease on every terminal path.

The exact ordering of steps 6–9 may need adjustment to satisfy SC2's multiplayer handshake. Implement the sequence established by live integration proof, not this candidate ordering by assumption.

## Port allocation

The existing allocator leases two SC2 listener ports plus one shared five-port block. That is not sufficient for the target topology.

Before changing the allocator, derive and live-verify the complete topology from Blizzard's `RequestJoinGame`, `PortSet`, and reference coordinator `SetupPorts` behavior. Determine:
- the observer's listener port;
- one listener per competitor;
- the server PortSet and every client PortSet required by the observer plus all players;
- whether the same complete PortSet collection must be supplied to every joining client;
- whether observer participation consumes the same networking footprint as a player;
- how the required footprint scales with N participants;
- collision-free allocation across concurrent matches.

Represent the result as a typed match-level lease, not scattered integer offsets. Validate range overlap, capacity, overflow, and release/reuse in contract tests. A process-local lease prevents collisions within one host process; it is not an OS socket reservation.

The reference coordinator's current arithmetic is documented in [SC2_RUNTIME_PROTOCOL.md](SC2_RUNTIME_PROTOCOL.md). It is not proof that an observer counts as an ordinary multiplayer client in the target flow.

## Fairness and information boundaries

- All player clients use the same pinned game version, map, game settings, and equivalent launch policy.
- Entrant-to-player-slot and starting-location assignment must be randomized or rotated under trusted match policy. Team assignments must be preserved, and no entrant should be permanently favored by assignment order.
- Give every runner equivalent resource limits, working-directory isolation, environment allowlists, and logging.
- Each runner connects only to its own player SC2 listener. Never forward observer observations, global vision, replay state, or observer-derived hidden information to any bot.
- The observer process has no player identity and must not issue player actions. Its observer API surface is read-only for adjudication; camera/perspective controls are presentation-only.
- Record build hashes, game/map version, entrant IDs, SC2 player IDs, team IDs, assigned slots, start locations, resource budgets, and evidence hashes.
- Define format-specific result semantics. FFA ranking, team wins, draws, ties, disconnects, and forfeits must not be collapsed into a two-player result model.

A neutral observer removes the designated-competitor-host asymmetry. It does not by itself eliminate map-side, scheduling, hardware, latency, or resource asymmetries; those require explicit match policy and measurement.

## Scaling beyond 1v1

The architecture scales by adding one player SC2 client and one runner per admitted entrant while retaining one observer host, within verified SC2 limits. The allocator and supervisor must be parameterized by participant count and format; they must not special-case exactly two players or infer a single opponent.

ServerApp remains responsible for generic competition policy and immutable admission. ServerSC2 owns SC2-specific topology, map/game setup, team mapping, process lifecycle, and authoritative evidence. Other game adapters can use the same game-neutral ServerApp competition model without depending on SC2.

## Required proof gates

1. **Protocol proof:** Participant A's CreateGame-then-player-join sequence, independent player joins, and independent observer join succeed on the pinned SC2 version; confirm `observed_player_id = 0` semantics.
2. **Format proof:** prove player/team setup and result semantics for each enabled format (1v1, teams, FFA, multi-team); do not advertise unsupported formats.
3. **Port proof:** all SC2 clients join one match with the derived PortSet layout; no port collision across concurrent matches.
4. **Isolation proof:** each bot receives only its own player observation and cannot connect to the observer endpoint or another entrant's listener.
5. **Fairness proof:** all entrants receive symmetric settings and resource budgets; slot/team assignment follows trusted policy.
6. **Lifecycle proof:** startup, readiness, early exit, timeout, cancellation, match completion, replay save, and cleanup work for variable participant counts.
7. **Evidence proof:** observer-captured results map to every acknowledged player ID, immutable entrant/build identity, and team assignment; replay and result artifacts are retained and verifiable.
8. **Compatibility proof:** at least one SingularityBot-based runner and one independent SC2 bot runner can enter the same generic host contract without host-side strategy dependencies.
9. **CI proof:** fake-runtime contract checks cover variable participant counts, team/format validation, port lease, observer readiness, identity mapping, fail-closed behavior, and partial-start cleanup. Live SC2 proof remains a separate integration gate.

Until these gates close, the existing two-process path must not be described as observer-hosted. Do not silently fall back to competitor-hosted matches if observer startup fails; fail closed and report the missing capability.
