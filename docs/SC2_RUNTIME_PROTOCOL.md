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
- Both runner processes use the same `JoinGameLadder` implementation. The Blizzard C++ coordinator builds one shared `GameSettings.ports` structure in `SetupPorts` and passes that same structure to each agent's `RequestJoinGame`; the standard coordinator therefore uses one match-scoped multiplayer port set shared by both join requests, not a separately allocated set per bot. The bot's `StartPort` base is consequently a match-level value for both runners, while each runner's `GamePort` remains its own SC2 listener.
- `SetupPorts` allocates the multiplayer ports consecutively after the SC2 listener ports: shared port, server game/base ports, and client game/base ports. The current SingularityBot arithmetic maps these to `StartPort + 1` through `StartPort + 5`.
- `RunLadder` originally did not call `CreateGame`. The development branch now adds an explicit host-only `--CreateGame --Map <trusted-map-path>` mode: that runner connects to its designated SC2 host listener, sends `RequestCreateGame` with two participant slots, then proceeds through its existing `JoinGameLadder` path. The second runner omits `--CreateGame` and only joins. This is a source-level integration change, not yet validated against a running SC2 installation.
- The local path still launches SC2 and creates a one-participant game with a built-in computer opponent; it is not the competition-host path.
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

The host runner now owns the CreateGame request on its own SC2 WebSocket connection and then continues on that same connection into JoinGameLadder; this follows Blizzard's coordinator pattern, which creates the game through its first client before issuing join requests through both clients. The match-level StartPort base and its five derived multiplayer ports are shared by both join requests, while each runner receives its own SC2 listener GamePort. The exact listener/port reservation behavior still needs a live integration test. The bot's current `RunLadder` path itself cannot perform step 2 because it only calls `JoinGameLadder`.

## Unresolved integration gate

Before implementing a real process supervisor, prove these remaining details against a runnable SC2 build and the exact SingularityBot revision:

1. Verify the host runner's new `--CreateGame --Map` path against a runnable SC2 build and ensure the map/player setup is accepted.
2. Implement a match lease containing two distinct SC2 listener ports plus one shared StartPort base whose `+1..+5` multiplayer ports are reserved atomically; ensure no overlap across concurrent matches.
3. Verify both runners join with the same multiplayer port set and receive the expected distinct player IDs.
4. How the host observes both player identities/results and saves the replay after terminal state.
5. Which process owns shutdown and how both SC2 processes and runner process trees are cleaned up after partial startup.

Do not infer these details from parameter names. The existing ServerSC2 lease (one game port plus one start-port base) is insufficient: it must become two distinct listener ports plus one shared match-level StartPort base and its five reserved derived ports. Do not treat the current allocator as production-safe. Keep the runtime seam injected until this gate is closed.

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
