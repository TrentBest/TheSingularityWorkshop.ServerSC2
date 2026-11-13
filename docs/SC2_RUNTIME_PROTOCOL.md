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
- The development branch adds an explicit host-only `--CreateGame --Map <trusted-map-path>` mode. The host runner connects to its designated SC2 listener, sends `RequestCreateGame` with two participant slots, then joins on the same connection. The second runner omits `--CreateGame` and only joins. This source-level flow remains unverified against a running SC2 installation.
- After a successful join, each runner emits `SC2_JOINED playerId=<id>`; after observing terminal SC2 state it emits `SC2_RESULT playerId=<id> result=<result>`. These structured stdout markers are consumed by ServerSC2's process supervisor. The supervisor checks that each result marker's player ID matches that runner's earlier join acknowledgement.
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

The host runner owns the CreateGame request on its own SC2 WebSocket connection and then continues on that same connection into JoinGameLadder. ServerSC2's `Sc2ProcessSessionRuntime` now starts both SC2 processes, launches the two runner processes with trusted fixed arguments, and waits for both `SC2_JOINED` markers with distinct player IDs before returning Ready. Both runners receive the same StartPort base and distinct GamePort values. On observation of both result markers, the supervisor verifies each marker's player ID against the corresponding join acknowledgement before reporting Completed. Result values are not yet exposed as durable match evidence, and the exact live SC2 handshake remains unverified.

## Unresolved integration gate

The allocator, typed adapter mapping, and initial process supervisor now exist. Remaining integration gates must be proved against a runnable SC2 build and the exact SingularityBot revision:

1. Verify the host runner's `--CreateGame --Map` path and map/player setup against a runnable SC2 build.
2. Verify both runners join the same match with the shared multiplayer port set and receive distinct player IDs.
3. Persist each validated result value and map it to the immutable participant assignment.
4. Implement SC2 replay saving and validate the authoritative result/replay evidence.
5. Exercise bounded shutdown and cleanup of both SC2 processes and both runner process trees after success, timeout, and partial startup.

The allocator leases two distinct listener ports and one shared StartPort base with offsets `+1..+5` as one process-local unit. It is not an OS socket reservation, and it has not yet been exercised against a live SC2 installation. Keep the runtime seam injected until live handshake, result, replay, and cleanup gates are closed.

## Readiness and completion rules

- An open TCP port or live process is not protocol readiness.
- Both runner processes must complete their protocol joins, report distinct player IDs, and remain associated with their immutable participant assignments.
- The current supervisor returns Ready after both runner JoinGame responses have been acknowledged. This is a source-level readiness gate; live SC2 verification and direct game-state confirmation remain open.
- A runner exit code is diagnostic only; it is never a win/loss declaration.
- The current supervisor reports Completed after both runners emit terminal result markers and each marker's player ID matches that runner's acknowledged join ID. Durable result capture, independent host validation, and replay saving remain open.
- Replay and result artifacts must be bound to match/session identity, game/map version, and both bot build hashes.
- Ambiguous topology, missing result, mismatched identity, or partial startup fails closed.

## Implementation gate

The `Sc2ProcessSessionRuntime` now owns fixed SC2 launch arguments, two SC2 process handles, two runner process handles, join-marker readiness, result-marker observation, and process-tree termination. The trusted artifact resolver, result/player identity validation, replay capture, durable evidence, and live-SC2 proof remain open. The port allocator is process-local rather than an OS socket reservation.

## Observer-host target topology (not yet proven)

The agreed target for fair 1v1 matches is three SC2 client processes: a dedicated simulation-host process that creates the game and joins as an observer, plus one player SC2 process for each admitted bot. Neither competitor receives CreateGame authority.

The protocol's `RequestJoinGame` participation oneof supports either `race` (player) or `observed_player_id` (observer). Observer actions are a separate request type from player actions. The protocol comments describe the conventional two-player CreateGame/JoinGame flow, but that alone does not prove that a dedicated host can CreateGame and then join as an observer while two other clients join as players.

The following are explicit unresolved questions, not assumptions:
- Does the pinned SC2 build accept CreateGame followed by RequestJoinGame(observer) on the same dedicated host connection?
- Does `observed_player_id = 0` provide the intended all-player observer perspective in this live multiplayer flow?
- What exact server PortSet and repeated client PortSet collection must be supplied by the observer and both players?
- Does the current SingularityBot JoinGameLadder port arithmetic correctly represent the full three-client topology, or must the bot-side adapter contract change?
- Can the observer independently obtain terminal player results and save the authoritative replay without giving either bot access to observer data?

The current ServerSC2 source still launches two SC2 processes and two runners, and the current SingularityBot host runner sends CreateGame before joining as a player. That is the old competitor-host topology. Do not claim that the observer-host design is implemented or live verified.

The implementation order is therefore:
1. Build a minimal live protocol proof for CreateGame + observer join + two player joins on the pinned SC2 build.
2. Derive the complete PortSet layout from the reference coordinator and prove it with three clients.
3. Add an observer-only process role to ServerSC2; remove CreateGame authority from both competitor launch records.
4. Prove player observation isolation, result correlation, replay capture, and full cleanup.
5. Only then replace the existing port lease model and enable observer-hosted sessions by default.

See [OBSERVER_HOST_DESIGN.md](OBSERVER_HOST_DESIGN.md) for the complete process model, fairness policy, scaling boundary, and acceptance gates.
