# SC2 Runtime Protocol Notes

This document records protocol facts that constrain the first real process supervisor. It intentionally separates verified SC2API behavior from unresolved ladder-host integration details.

## Verified SC2API facts

- The SC2API is a protobuf protocol over WebSockets. The game API endpoint is `/sc2api`.
- The WebSocket listener address and port are configured on the SC2 process command line with `-listen` and `-port`.
- Blizzard's protocol documentation describes multiplayer setup as launching two game instances on separate ports, designating a host, sending `Request.create_game`, and sending `Request.join_game` from both clients.
- The SC2API protocol exposes game lifecycle status values including `launched`, `init_game`, `in_game`, `ended`, and `quit`.

References:
- [Blizzard s2client-proto protocol documentation](https://github.com/Blizzard/s2client-proto/blob/master/docs/protocol.md)
- [Blizzard SC2API protocol definitions](https://github.com/Blizzard/s2client-proto/blob/master/s2clientprotocol/sc2api.proto)
- [Blizzard SC2 Coordinator reference](https://blizzard.github.io/s2client-api/classsc2_1_1_coordinator.html)

## Existing SingularityBot integration facts

The currently documented bot-side ladder entry point accepts `GamePort`, `StartPort`, and `OpponentId`, and connects as a client to an already hosted SC2 session. That bot-side contract is not itself a complete two-participant game host. ServerSC2 must launch and supervise the authoritative game-side runtime and both independently admitted bot builds.

## Decisions intentionally not guessed

Before implementing a concrete supervisor, verify against the current SingularityBot source and its exact SC2 client library:

1. Whether the intended local 1v1 topology uses one shared SC2API process or two SC2API game instances, and which process is authoritative for `CreateGame`.
2. How the current bot's `StartPort` maps to the SC2API server/client port sets and how many ports must be reserved per match.
3. Whether both bot processes connect to the same WebSocket endpoint or to distinct game instances/endpoints.
4. How the bot client reports a terminal result and how replay saving is requested and confirmed.
5. Which exact game/map versions and local map identifiers are supported by the checked-in bot runtime.

The official SC2API documentation describes multi-instance multiplayer setup, while the bot's ladder-manager arguments describe a bot joining an existing host. Those are related but not interchangeable contracts. Do not launch a guessed topology, treat an open TCP port as readiness, or infer a winner from process exit codes.

## Implementation gate

The current `ISc2SessionRuntime` interface is the correct seam for the eventual process supervisor. It must not report `Ready` until the game process and both bot clients have passed protocol-level readiness. It must not report `Completed` until an authoritative game result is captured and validated. Replay and result artifacts must be bound to the immutable match/session identity.
