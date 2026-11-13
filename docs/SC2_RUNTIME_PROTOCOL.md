# SC2 Runtime Protocol Notes

This document separates verified Blizzard protocol behavior, verified SingularityBot implementation details, and unresolved host integration details. Do not turn an unresolved detail into a launch assumption.

## Verified Blizzard SC2API facts

- SC2API is a protobuf protocol over WebSockets. Each SC2 process exposes its API at `/sc2api`; its listener address and port are configured with `-listen` and `-port`.
- Blizzard documents multiplayer setup as **two SC2 instances with separate listener ports**.
- One instance is designated the host and receives `Request.create_game` for a multiplayer map.
- Both SC2 clients then receive `Request.join_game`; both joins block until both clients connect.
- Each join request can carry a `server_ports` PortSet and one or more `client_ports` PortSets. A PortSet contains `game_port` and `base_port`. The deprecated `shared_port` field also exists.
- SC2 reports lifecycle states including `launched`, `init_game`, `in_game`, `ended`, and `quit`.

Primary references:
- https://github.com/Blizzard/s2client-proto/blob/master/docs/protocol.md
- https://github.com/Blizzard/s2client-proto/blob/master/s2clientprotocol/sc2api.proto
- https://github.com/Blizzard/s2client-api/blob/master/src/sc2api/sc2_coordinator.cc

## Verified SingularityBot source contract

Repository: https://github.com/TrentBest/TheSingularityWorkshop.SingularityBot, branch development.

- `src/SingularityBot/Program.cs` treats the run as local only when no connection arguments remain. Otherwise it calls `GameConnection.RunLadder`.
- `src/SingularityBot.Runner/Program.cs` forwards ladder arguments to the bot program. The runner is the host-facing executable entry point.
- `GameConnection.RunLadder` connects to the supplied `gamePort`, calls `JoinGameLadder(race, startPort)`, then enters the observation/action loop.
- Consequently, each runner's `GamePort` is the WebSocket listener of the SC2 process to which that runner connects. A two-runner match therefore requires two distinct SC2 listener endpoints/processes, not both runners pointed at one SC2 WebSocket listener.
- `JoinGameLadder` builds a join request with `shared_port = startPort + 1`, server PortSet `(startPort + 2, startPort + 3)`, and client PortSet `(startPort + 4, startPort + 5)`. It requests raw and score interface data.
- Both runner processes use the same `JoinGameLadder` implementation. This proves the arithmetic emitted by this bot version; it does **not** prove whether a deployed ladder host should give both runners the same start-port base or distinct bases.
- `RunLadder` does not call `CreateGame`. Its local path launches SC2, creates a one-participant game with a built-in computer opponent, and is not the competition-host path.
- The CLI parser accepts `--GamePort` / `-g`, `--StartPort` / `-o`, and `--OpponentId`. It advances arguments in name/value pairs. The host must emit only supported, correctly paired arguments.

Source links:
- https://github.com/TrentBest/TheSingularityWorkshop.SingularityBot/blob/development/src/SC2API.CSharp/GameConnection.cs
- https://github.com/TrentBest/TheSingularityWorkshop.SingularityBot/blob/development/src/SC2API.CSharp/CLArgs.cs
- https://github.com/TrentBest/TheSingularityWorkshop.SingularityBot/blob/development/src/SingularityBot/Program.cs
- https://github.com/TrentBest/TheSingularityWorkshop.SingularityBot/blob/development/src/SingularityBot.Runner/Program.cs

## Required SimulationServer topology

The verified architecture is:

1. ServerSC2 allocates and launches two separate SC2 processes, each with its own WebSocket listener port.
2. One SC2 instance must be designated as the multiplayer host and receive `CreateGame` for the configured map.
3. Each admitted SingularityBot runner connects to its assigned SC2 listener using that listener's `GamePort`.
4. Both SC2 clients participate in the same multiplayer session using the protocol's port-set handshake.
5. ServerSC2 observes authoritative game lifecycle/results and captures replay evidence independently of bot exit codes.

This establishes two distinct runner-to-SC2 endpoints and a host-created multiplayer game. It does not yet establish the precise sequencing/ownership of the host WebSocket connection, the mapping of the bot library's server/client PortSets to both instances, or whether the same `StartPort` base is supplied to both runners. The bot's current `RunLadder` path itself cannot perform step 2 because it only calls `JoinGameLadder`.

## Unresolved integration gate

Before implementing a real process supervisor, prove these remaining details against a runnable SC2 build and the exact SingularityBot revision:

1. How the host sends `CreateGame` and then permits the first bot runner to join the same SC2 instance without competing for its WebSocket connection.
2. Whether both runners receive the same `StartPort` base, and how the host/client PortSets are interpreted by each SC2 instance.
3. The complete collision-free port footprint per match: two SC2 listener ports plus every shared/server/client game/base port used by SC2.
4. How the host observes both player identities/results and saves the replay after terminal state.
5. Which process owns shutdown and how both SC2 processes and runner process trees are cleaned up after partial startup.

Do not infer these details from parameter names. The existing ServerSC2 lease (one game port plus one start-port base) is insufficient for a proven two-instance allocation and must not be treated as production-safe. Keep the runtime seam injected until this gate is closed.

## Readiness and completion rules

- An open TCP port or live process is not protocol readiness.
- Both runner processes must complete their protocol joins and be associated with the expected participant identities.
- A match is Ready only when both SC2 instances, the authoritative multiplayer game, and both admitted runners have passed their required readiness checks.
- A runner exit code is diagnostic only; it is never a win/loss declaration.
- A match is Completed only after SC2 reports terminal state and the host validates the player-result mapping.
- Replay and result artifacts must be bound to match/session identity, game/map version, and both bot build hashes.
- Ambiguous topology, missing result, mismatched identity, or partial startup fails closed.

## Implementation gate

The `ISc2SessionRuntime` seam remains the right place for the concrete SimulationServer. Next implement a testable port-footprint model and process-supervision contracts only after the remaining handshake ownership and port-sharing questions are resolved. The runtime must own fixed host launch arguments, both SC2 process trees, both runner process trees, protocol-level readiness, authoritative result/replay capture, and bounded cleanup.
