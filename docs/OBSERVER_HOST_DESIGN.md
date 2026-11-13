# Observer-Hosted SC2 Match Topology

## Decision

The target 1v1 topology uses three independently supervised StarCraft II client processes per match. A dedicated simulation-host process creates the multiplayer game and joins it as an observer. Two other SC2 processes each host one admitted bot runner as a player participant.

The competitors are symmetric: neither competitor creates the game, chooses the opponent's endpoint, or owns the session lifecycle. The observer host is infrastructure, not a third competitor.

This is a target architecture and an implementation plan. The exact CreateGame-then-observer-join sequence, observer port configuration, replay capture, and lifecycle behavior must be proven against the pinned SC2 build before this topology is declared operational.

## Process roles

| Process | Responsibility | Authority |
|---|---|---|
| Simulation host / observer | Create the multiplayer game, join as observer, monitor lifecycle, collect replay/result evidence | Match orchestration and observation only; no player actions |
| Player A SC2 instance | Expose its own SC2API listener and provide player A's observation/action channel | Player A game session |
| Player B SC2 instance | Expose its own SC2API listener and provide player B's observation/action channel | Player B game session |
| Bot runner A | Connect only to player A's listener and submit player A actions | Player A only |
| Bot runner B | Connect only to player B's listener and submit player B actions | Player B only |

These are three SC2 processes, not necessarily three physical machines. A single trusted host can supervise all three locally at first. The process boundaries and endpoint assignments should permit later placement on separate workers.

## Candidate startup sequence

1. Validate the immutable ServerApp match assignment, both admitted build identities, trusted map, game version, and runtime profile.
2. Resolve and verify both runner artifacts by immutable build identity and SHA-256 before starting any process.
3. Atomically lease three distinct SC2 listener ports and the complete multiplayer PortSet footprint required by all three SC2 clients.
4. Start the dedicated simulation-host SC2 process with its own listener.
5. Connect to that listener and issue CreateGame for the trusted multiplayer map and exactly two participant slots.
6. Join that same SC2 client as an observer, initially investigating `observed_player_id = 0` for the all-player observer perspective.
7. Start the two player SC2 processes with distinct listeners.
8. Launch each immutable bot runner with only its assigned player listener and the shared, correctly constructed match PortSet configuration. Neither runner receives CreateGame authority.
9. Require observer readiness and both player join acknowledgements. Validate two distinct player IDs and bind each ID to the immutable participant assignment.
10. Observe authoritative game lifecycle and terminal player results from the observer channel. Save replay and diagnostics under the immutable match/session identity.
11. Stop both runners and all three SC2 process trees, then release the complete lease on every terminal path.

The exact ordering of steps 5–8 may need adjustment to satisfy SC2's multiplayer handshake. The runtime must implement the ordering established by a live integration proof, not assume this candidate sequence is valid.

## Port allocation

The current allocator leases two SC2 listener ports plus one shared five-port block. That is not sufficient evidence for a third SC2 client.

Before changing the allocator, derive the complete topology from Blizzard's `RequestJoinGame`, `PortSet`, and reference coordinator `SetupPorts` behavior. Determine:
- the observer's listener port;
- the server PortSet;
- every client PortSet required by two players plus one observer;
- whether the same complete PortSet collection must be supplied to each joining client;
- whether observer participation consumes the same networking footprint as a player;
- collision-free allocation across concurrent matches.

Represent the result as a typed match-level lease, not scattered integer offsets. Validate range overlap, capacity, overflow, and release/reuse in contract tests. A process-local lease prevents collisions within one host process; it is not an OS socket reservation.

## Fairness and information boundaries

- Both player clients use the same pinned game version, map, game settings, and equivalent launch policy.
- Randomize or alternate player slot / starting-location assignment under trusted match policy. Do not permanently map assignment order to a favored spawn.
- Give both runner processes equivalent resource limits, working-directory isolation, environment allowlists, and logging.
- Each runner connects only to its own player SC2 listener. Never forward observer observations, global vision, replay state, or observer-derived hidden information to either bot.
- The observer process has no player identity and must not issue player actions. Its observer API surface is read-only for match adjudication; any camera/perspective controls are presentation-only.
- Record build hashes, game/map version, player IDs, assigned slots, start locations, and evidence hashes so results can be audited.

A neutral observer removes the designated-competitor-host asymmetry. It does not by itself eliminate map-side, scheduling, hardware, latency, or resource asymmetries; those require explicit match policy and measurement.

## Scaling beyond 1v1

The observer-host pattern separates match ownership from participant count. A later multiplayer session can retain one simulation host/observer and allocate one player SC2 client plus one admitted runner per participant, subject to the SC2 protocol's actual player and port limits. ServerApp remains responsible for generic competition policy and immutable admission; ServerSC2 owns SC2-specific topology and lifecycle.

Do not generalize the allocator to arbitrary participant counts until the two-player-plus-observer proof establishes the actual SC2 client PortSet semantics and supported limits.

## Required proof gates

1. **Protocol proof:** CreateGame from the dedicated host followed by observer join succeeds on the pinned SC2 version; confirm `observed_player_id = 0` semantics and observer status.
2. **Port proof:** all three SC2 clients join one match with the derived PortSet layout; no port collision across concurrent matches.
3. **Isolation proof:** each bot receives only its own player observation and cannot connect to the observer endpoint or submit observer/player actions through another process.
4. **Fairness proof:** both players receive symmetric settings and resource budgets; slot assignment is not fixed to one participant.
5. **Lifecycle proof:** startup, readiness, early exit, timeout, cancellation, match completion, replay save, and cleanup all work with three SC2 processes and two runners.
6. **Evidence proof:** observer-captured terminal results map to the two acknowledged player IDs and immutable participant/build identities; replay and result artifacts are retained and verifiable.
7. **CI proof:** fake-runtime contract checks cover the three-role topology, port lease, observer readiness, participant identity, fail-closed behavior, and partial-start cleanup. Live SC2 proof remains a separate integration gate.

Until these gates close, the existing two-process path must not be described as an observer-host implementation. Do not silently fall back to competitor-hosted matches if observer startup fails; fail closed and report the missing capability.

### Current reference-coordinator arithmetic

Blizzard's reference `Coordinator::SetupPorts(num_agents, port_start)` allocates:
- one shared port at base + 1;
- one server PortSet at base + 2 and base + 3;
- one client PortSet (two ports) for each additional client, starting at base + 4.

For three SC2 clients, that produces a seven-port multiplayer block (base + 1 through base + 7), in addition to three distinct SC2 WebSocket listener ports. This is the reference coordinator's arithmetic; whether the observer participates in this exact three-client PortSet topology must still be verified live.

The current SingularityBot `JoinGameLadder` sends only one client PortSet. If all three SC2 clients require the full PortSet collection, the bot-side ladder adapter must be extended to accept and submit both client PortSets. ServerSC2 must not assume that allocating a third listener alone makes the existing runner compatible.
