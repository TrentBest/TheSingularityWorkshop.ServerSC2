# ServerSC2 Pause Point

## Repository state

- Repository bootstrapped on `development`; `master` remains the empty initial baseline.
- Added ownership and trust-boundary documentation.
- Added `ServerSC2.Core` with trusted profile validation and a bounded process-local game/start port-pair lease pool.
- Added a dependency-free contract-check executable for profile validation, allocation uniqueness, exhaustion, and lease reuse.

## Not implemented yet

- ServerApp `IGameSessionAdapter` bridge.
- Actual SC2 executable discovery/launch and process supervision.
- Participant process launch/attachment and readiness.
- OS-level port conflict handling, process cleanup, and crash recovery.
- Replay capture, authoritative result evidence, and durable match/session history.
- Trusted role manifest integration and FSM_COS RuntimeAssembly acquisition.
- End-to-end local 1v1 test against an installed SC2 runtime.

## Resume order

1. Verify source builds and contract checks in CI.
2. Add a ServerApp adapter project referencing the exact ServerApp.Core contract (source checkout in CI; package only after a separately authorized release).
3. Define the trusted SC2 installation/profile resolver and process supervisor interface.
4. Implement a real local process launch with bounded cancellation, readiness, drain, termination observation, and cleanup.
5. Integrate SingularityBot's existing ladder connection path without moving strategy into ServerSC2.
6. Capture and validate replay/result evidence; persist match history without a database.
7. Prove one local 1v1 match before exposing network admission or matchmaking.

No merge, NuGet publication, release, deployment, or branch deletion has been performed or is implied.
