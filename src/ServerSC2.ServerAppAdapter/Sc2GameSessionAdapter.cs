using ServerApp.Core;
using ServerSC2.Core;

namespace ServerSC2.ServerAppAdapter;

/// <summary>Typed participant input derived only from an admitted, immutable ServerApp assignment.</summary>
public sealed record Sc2ParticipantLaunch(
    string ParticipantId,
    string TeamId,
    BotBuildReference BotBuild,
    int GamePort,
    bool IsGameHost);

/// <summary>Trusted SC2 launch envelope. No executable path or arbitrary command-line input is accepted.</summary>
public sealed record Sc2SessionLaunchRequest(
    string MatchId,
    string SessionId,
    string AdapterVersion,
    string GameVersion,
    string MapId,
    int StartPort,
    IReadOnlyList<Sc2ParticipantLaunch> Participants);

/// <summary>Game-runtime observation translated into the game-neutral ServerApp lifecycle.</summary>
public sealed record Sc2RuntimeSessionSnapshot(
    string MatchId,
    string SessionId,
    GameSessionState State,
    DateTimeOffset ObservedAtUtc,
    string? FailureCode = null,
    string? FailureMessage = null);

/// <summary>
/// The process supervisor boundary. Implementations must own all executable paths, fixed launch
/// arguments, process trees, readiness probes, replay/result capture, and bounded cleanup.
/// </summary>
public interface ISc2SessionRuntime
{
    ValueTask<Sc2RuntimeSessionSnapshot> StartAsync(
        Sc2SessionLaunchRequest request,
        CancellationToken cancellationToken = default);

    ValueTask<Sc2RuntimeSessionSnapshot?> GetStatusAsync(
        string sessionId,
        CancellationToken cancellationToken = default);

    ValueTask StopAsync(
        string sessionId,
        CancellationToken cancellationToken = default);
}

/// <summary>
/// Bridges ServerApp's game-neutral lifecycle to the SC2 runtime. This adapter deliberately
/// does not launch processes itself; it translates admitted assignments, leases ports, and
/// enforces identity/version boundaries around an injected trusted runtime.
/// </summary>
public sealed class Sc2GameSessionAdapter : IGameSessionAdapter, IAsyncDisposable
{
    public const string StarCraftIIGameId = "starcraft-ii";

    private sealed class ActiveSession(string sessionId, Sc2PortLease lease)
    {
        public string SessionId { get; } = sessionId;
        public Sc2PortLease Lease { get; } = lease;
        public SemaphoreSlim Gate { get; } = new(1, 1);
    }

    private readonly Sc2ServerProfile _profile;
    private readonly Sc2PortLeasePool _ports;
    private readonly ISc2SessionRuntime _runtime;
    private readonly string _gameId;
    private readonly Dictionary<string, ActiveSession> _sessions = new(StringComparer.Ordinal);
    private readonly object _sessionsGate = new();
    private bool _disposed;

    public Sc2GameSessionAdapter(
        Sc2ServerProfile profile,
        Sc2PortLeasePool ports,
        ISc2SessionRuntime runtime,
        string gameId = StarCraftIIGameId)
    {
        ArgumentNullException.ThrowIfNull(profile);
        ArgumentNullException.ThrowIfNull(ports);
        ArgumentNullException.ThrowIfNull(runtime);
        ArgumentException.ThrowIfNullOrWhiteSpace(gameId);

        var errors = profile.Validate();
        if (errors.Count != 0)
            throw new ArgumentException($"The SC2 profile is invalid: {string.Join(", ", errors)}", nameof(profile));

        _profile = profile;
        _ports = ports;
        _runtime = runtime;
        _gameId = gameId;
    }

    public string AdapterVersion => _profile.AdapterVersion;

    public async ValueTask<GameSessionSnapshot> StartAsync(
        GameSessionStartRequest request,
        CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        ArgumentNullException.ThrowIfNull(request);
        ArgumentNullException.ThrowIfNull(request.Assignment);
        ArgumentException.ThrowIfNullOrWhiteSpace(request.SessionId);

        var assignment = request.Assignment;
        if (!string.Equals(assignment.GameId, _gameId, StringComparison.Ordinal))
            throw new InvalidOperationException("The admitted assignment targets a different game.");
        if (!string.Equals(assignment.GameAdapterVersion, AdapterVersion, StringComparison.Ordinal))
            throw new InvalidOperationException("The admitted assignment pins a different SC2 adapter version.");
        if (assignment.Participants.Count != 2)
            throw new InvalidOperationException("The initial SC2 runtime supports exactly two admitted participants.");
        if (assignment.Participants.Any(p => p.BotBuild is null ||
            string.IsNullOrWhiteSpace(p.BotBuild.BuildId) ||
            string.IsNullOrWhiteSpace(p.BotBuild.ContentSha256)))
            throw new InvalidOperationException("Every SC2 participant must have an admitted immutable bot build.");

        lock (_sessionsGate)
        {
            if (_sessions.ContainsKey(request.SessionId))
                throw new InvalidOperationException("The SC2 session ID is already active.");
        }

        if (!_ports.TryAcquire(out var lease) || lease is null)
            throw new InvalidOperationException("The SC2 host has reached its configured concurrent-match capacity.");

        var active = new ActiveSession(request.SessionId, lease);
        lock (_sessionsGate)
        {
            if (_disposed || !_sessions.TryAdd(request.SessionId, active))
            {
                lease.Dispose();
                ObjectDisposedException.ThrowIf(_disposed, this);
                throw new InvalidOperationException("The SC2 session ID is already active.");
            }
        }

        await active.Gate.WaitAsync(CancellationToken.None).ConfigureAwait(false);
        try
        {
            if (_disposed)
            {
                RemoveAndRelease(request.SessionId, active);
                throw new ObjectDisposedException(nameof(Sc2GameSessionAdapter));
            }

            var launch = new Sc2SessionLaunchRequest(
                assignment.MatchId,
                request.SessionId,
                AdapterVersion,
                _profile.GameVersion,
                _profile.MapId,
                lease.StartPort,
                Array.AsReadOnly(assignment.Participants.Select((p, index) =>
                    new Sc2ParticipantLaunch(
                        p.ParticipantId,
                        p.TeamId,
                        p.BotBuild,
                        index == 0 ? lease.HostGamePort : lease.JoinerGamePort,
                        index == 0)).ToArray()));

            var observed = await _runtime.StartAsync(launch, cancellationToken).ConfigureAwait(false);
            var snapshot = ValidateAndTranslate(observed, assignment.MatchId, request.SessionId);
            if (snapshot.State == GameSessionState.Failed)
            {
                await StopAndReleaseAsync(request.SessionId, active).ConfigureAwait(false);
                return snapshot;
            }
            if (snapshot.State != GameSessionState.Ready)
                throw new InvalidOperationException("The SC2 runtime must complete all game and participant readiness checks before returning.");

            return snapshot;
        }
        catch
        {
            await StopAndReleaseAsync(request.SessionId, active).ConfigureAwait(false);
            throw;
        }
        finally
        {
            active.Gate.Release();
        }
    }

    public async ValueTask<GameSessionSnapshot?> GetStatusAsync(
        string sessionId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(sessionId);
        ActiveSession? active;
        lock (_sessionsGate)
            _sessions.TryGetValue(sessionId, out active);
        if (active is null)
            return null;

        await active.Gate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            var observed = await _runtime.GetStatusAsync(sessionId, cancellationToken).ConfigureAwait(false);
            if (observed is null)
                return null;

            var snapshot = ValidateAndTranslate(observed, observed.MatchId, sessionId);
            if (snapshot.State is GameSessionState.Completed or GameSessionState.Failed or GameSessionState.Aborted)
                await StopAndReleaseAsync(sessionId, active).ConfigureAwait(false);
            return snapshot;
        }
        finally
        {
            active.Gate.Release();
        }
    }

    public async ValueTask StopAsync(
        string sessionId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(sessionId);
        ActiveSession? active;
        lock (_sessionsGate)
            _sessions.TryGetValue(sessionId, out active);
        if (active is null)
            return;

        await active.Gate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            await _runtime.StopAsync(sessionId, cancellationToken).ConfigureAwait(false);
            RemoveAndRelease(sessionId, active);
        }
        finally
        {
            active.Gate.Release();
        }
    }

    public async ValueTask DisposeAsync()
    {
        ActiveSession[] active;
        lock (_sessionsGate)
        {
            if (_disposed)
                return;
            _disposed = true;
            active = _sessions.Values.ToArray();
        }

        List<Exception>? failures = null;
        foreach (var session in active)
        {
            await session.Gate.WaitAsync(CancellationToken.None).ConfigureAwait(false);
            try
            {
                try { await _runtime.StopAsync(session.SessionId, CancellationToken.None).ConfigureAwait(false); }
                catch (Exception exception) { (failures ??= []).Add(exception); }
                finally { session.Lease.Dispose(); }
            }
            finally
            {
                session.Gate.Release();
            }
        }

        lock (_sessionsGate)
            _sessions.Clear();

        if (failures is not null)
            throw new AggregateException("One or more SC2 sessions failed to stop during adapter disposal.", failures);
    }

    private GameSessionSnapshot ValidateAndTranslate(
        Sc2RuntimeSessionSnapshot? observed,
        string matchId,
        string sessionId)
    {
        if (observed is null ||
            !string.Equals(observed.MatchId, matchId, StringComparison.Ordinal) ||
            !string.Equals(observed.SessionId, sessionId, StringComparison.Ordinal) ||
            observed.ObservedAtUtc.Offset != TimeSpan.Zero ||
            !Enum.IsDefined(observed.State))
            throw new InvalidOperationException("The SC2 runtime returned an invalid or mismatched session snapshot.");

        if (observed.State == GameSessionState.Failed &&
            (string.IsNullOrWhiteSpace(observed.FailureCode) || string.IsNullOrWhiteSpace(observed.FailureMessage)))
            throw new InvalidOperationException("A failed SC2 runtime snapshot must include failure metadata.");
        if (observed.State != GameSessionState.Failed &&
            (observed.FailureCode is not null || observed.FailureMessage is not null))
            throw new InvalidOperationException("Only a failed SC2 runtime snapshot may include failure metadata.");

        return new GameSessionSnapshot(
            observed.MatchId, observed.SessionId, AdapterVersion, observed.State,
            observed.ObservedAtUtc, observed.FailureCode, observed.FailureMessage);
    }

    private async ValueTask StopAndReleaseAsync(string sessionId, ActiveSession active)
    {
        try { await _runtime.StopAsync(sessionId, CancellationToken.None).ConfigureAwait(false); }
        finally { RemoveAndRelease(sessionId, active); }
    }

    private void RemoveAndRelease(string sessionId, ActiveSession active)
    {
        lock (_sessionsGate)
        {
            if (_sessions.TryGetValue(sessionId, out var current) && ReferenceEquals(current, active))
                _sessions.Remove(sessionId);
        }
        active.Lease.Dispose();
    }
}
