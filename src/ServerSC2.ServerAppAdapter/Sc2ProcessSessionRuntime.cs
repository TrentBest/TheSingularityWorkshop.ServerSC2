using System.Diagnostics;
using System.Globalization;
using ServerApp.Core;

namespace ServerSC2.ServerAppAdapter;

/// <summary>
/// Resolves an admitted immutable bot build to its executable runner. Implementations must
/// verify the returned artifact against BotBuildReference.ContentSha256 before returning it.
/// </summary>
public interface ISc2BotRunnerResolver
{
    string ResolveRunnerExecutable(BotBuildReference build);
}

/// <summary>Trusted machine-local paths and bounded lifecycle timeouts for one SC2 host.</summary>
public sealed record Sc2ProcessRuntimeOptions(
    string StarCraftExecutablePath,
    string StarCraftWorkingDirectory,
    string MapId,
    string MapPath,
    TimeSpan RunnerJoinTimeout,
    TimeSpan ProcessStopTimeout)
{
    public IReadOnlyList<string> Validate()
    {
        var errors = new List<string>();
        if (string.IsNullOrWhiteSpace(StarCraftExecutablePath)) errors.Add("runtime.sc2-executable.required");
        if (string.IsNullOrWhiteSpace(StarCraftWorkingDirectory)) errors.Add("runtime.sc2-working-directory.required");
        if (string.IsNullOrWhiteSpace(MapId)) errors.Add("runtime.map-id.required");
        if (string.IsNullOrWhiteSpace(MapPath)) errors.Add("runtime.map-path.required");
        if (RunnerJoinTimeout <= TimeSpan.Zero) errors.Add("runtime.join-timeout.invalid");
        if (ProcessStopTimeout <= TimeSpan.Zero) errors.Add("runtime.stop-timeout.invalid");
        return Array.AsReadOnly(errors.ToArray());
    }
}

/// <summary>
/// Owns the two SC2 processes and two immutable-build runner processes for each match.
/// Ready is returned only after both runners report protocol-level join acknowledgements.
/// Result markers are observed from both runners; they are not used to infer a winner here.
/// </summary>
public sealed class Sc2ProcessSessionRuntime : ISc2SessionRuntime, IAsyncDisposable
{
    private sealed record RunnerResult(uint PlayerId, string Result);

    private sealed class Runner
    {
        public required Process Process { get; init; }
        public TaskCompletionSource<uint> Joined { get; } =
            new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource<RunnerResult> Result { get; } =
            new(TaskCreationOptions.RunContinuationsAsynchronously);
        public string? LastError { get; set; }
    }

    private sealed class Session(string matchId, string sessionId)
    {
        public string MatchId { get; } = matchId;
        public string SessionId { get; } = sessionId;
        public List<Process> Sc2Processes { get; } = [];
        public List<Runner> Runners { get; } = [];
        public DateTimeOffset StartedAtUtc { get; } = DateTimeOffset.UtcNow;
        public SemaphoreSlim Gate { get; } = new(1, 1);
        public bool Stopping { get; set; }
    }

    private readonly Sc2ProcessRuntimeOptions _options;
    private readonly ISc2BotRunnerResolver _runnerResolver;
    private readonly Dictionary<string, Session> _sessions = new(StringComparer.Ordinal);
    private readonly object _gate = new();
    private bool _disposed;

    public Sc2ProcessSessionRuntime(
        Sc2ProcessRuntimeOptions options,
        ISc2BotRunnerResolver runnerResolver)
    {
        ArgumentNullException.ThrowIfNull(options);
        ArgumentNullException.ThrowIfNull(runnerResolver);
        var errors = options.Validate();
        if (errors.Count != 0)
            throw new ArgumentException($"Invalid SC2 process runtime options: {string.Join(", ", errors)}", nameof(options));
        _options = options;
        _runnerResolver = runnerResolver;
    }

    public async ValueTask<Sc2RuntimeSessionSnapshot> StartAsync(
        Sc2SessionLaunchRequest request,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);
        ValidateLaunch(request);
        if (!string.Equals(request.MapId, _options.MapId, StringComparison.Ordinal))
            throw new InvalidOperationException("The match assignment map does not match the trusted runtime map profile.");
        ValidateMachinePaths();

        var session = new Session(request.MatchId, request.SessionId);
        lock (_gate)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            if (!_sessions.TryAdd(request.SessionId, session))
                throw new InvalidOperationException("The SC2 runtime session ID is already active.");
        }

        try
        {
            foreach (var participant in request.Participants)
            {
                var startInfo = new ProcessStartInfo
                {
                    FileName = _options.StarCraftExecutablePath,
                    WorkingDirectory = _options.StarCraftWorkingDirectory,
                    UseShellExecute = false,
                    CreateNoWindow = true
                };
                startInfo.ArgumentList.Add("-listen");
                startInfo.ArgumentList.Add("127.0.0.1");
                startInfo.ArgumentList.Add("-port");
                startInfo.ArgumentList.Add(participant.GamePort.ToString(CultureInfo.InvariantCulture));
                startInfo.ArgumentList.Add("-displayMode");
                startInfo.ArgumentList.Add("0");
                session.Sc2Processes.Add(StartProcess(startInfo));
            }

            foreach (var participant in request.Participants)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var runnerPath = _runnerResolver.ResolveRunnerExecutable(participant.BotBuild);
                if (string.IsNullOrWhiteSpace(runnerPath) || !File.Exists(runnerPath))
                    throw new FileNotFoundException("The immutable bot build runner executable was not found.", runnerPath);

                var opponent = request.Participants.Single(p => p.ParticipantId != participant.ParticipantId);
                var startInfo = new ProcessStartInfo
                {
                    FileName = runnerPath,
                    WorkingDirectory = Path.GetDirectoryName(Path.GetFullPath(runnerPath))!,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true
                };
                AddArgument(startInfo, "--GamePort", participant.GamePort);
                AddArgument(startInfo, "--StartPort", request.StartPort);
                AddArgument(startInfo, "--OpponentId", opponent.ParticipantId);
                if (participant.IsGameHost)
                {
                    startInfo.ArgumentList.Add("--CreateGame");
                    startInfo.ArgumentList.Add("--Map");
                    startInfo.ArgumentList.Add(_options.MapPath);
                }

                var process = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
                var runner = new Runner { Process = process };
                process.OutputDataReceived += (_, eventArgs) => ObserveRunnerOutput(runner, eventArgs.Data);
                process.ErrorDataReceived += (_, eventArgs) =>
                {
                    if (!string.IsNullOrWhiteSpace(eventArgs.Data))
                        runner.LastError = eventArgs.Data;
                };
                process.Exited += (_, _) =>
                {
                    if (!runner.Joined.Task.IsCompleted)
                        runner.Joined.TrySetException(new InvalidOperationException(
                            $"Bot runner exited before joining (exit code {SafeExitCode(process)})."));
                    if (!runner.Result.Task.IsCompleted)
                        runner.LastError ??= $"Bot runner exited before reporting a result (exit code {SafeExitCode(process)}).";
                };
                if (!process.Start())
                    throw new InvalidOperationException("A bot runner process could not be started.");
                session.Runners.Add(runner);
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
            }

            var joined = await Task.WhenAll(session.Runners.Select(r => r.Joined.Task))
                .WaitAsync(_options.RunnerJoinTimeout, cancellationToken).ConfigureAwait(false);
            if (joined.Distinct().Count() != 2)
                throw new InvalidOperationException("The two SC2 runners reported duplicate player IDs.");

            return new Sc2RuntimeSessionSnapshot(
                request.MatchId, request.SessionId, GameSessionState.Ready, DateTimeOffset.UtcNow);
        }
        catch
        {
            await StopSessionAsync(session).ConfigureAwait(false);
            lock (_gate) _sessions.Remove(request.SessionId);
            throw;
        }
    }

    public async ValueTask<Sc2RuntimeSessionSnapshot?> GetStatusAsync(
        string sessionId,
        CancellationToken cancellationToken = default)
    {
        Session? session;
        lock (_gate) _sessions.TryGetValue(sessionId, out session);
        if (session is null) return null;

        await session.Gate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            if (session.Stopping)
                return new(session.MatchId, session.SessionId, GameSessionState.Aborted, DateTimeOffset.UtcNow);

            var failedRunner = session.Runners.FirstOrDefault(r =>
                r.Process.HasExited && !r.Result.Task.IsCompletedSuccessfully);
            if (failedRunner is not null)
                return Failed(session, "runner.exited-without-result",
                    failedRunner.LastError ?? $"Bot runner exited with code {SafeExitCode(failedRunner.Process)}.");

            var mismatchedResult = session.Runners.FirstOrDefault(r =>
                r.Result.Task.IsCompletedSuccessfully && r.Joined.Task.IsCompletedSuccessfully &&
                r.Result.Task.Result.PlayerId != r.Joined.Task.Result);
            if (mismatchedResult is not null)
                return Failed(session, "runner.result-player-mismatch",
                    "A runner's terminal result marker did not match its acknowledged SC2 player ID.");

            if (session.Runners.Count == 2 && session.Runners.All(r => r.Result.Task.IsCompletedSuccessfully))
                return new(session.MatchId, session.SessionId, GameSessionState.Completed, DateTimeOffset.UtcNow);

            return new(session.MatchId, session.SessionId, GameSessionState.Running, DateTimeOffset.UtcNow);
        }
        finally
        {
            session.Gate.Release();
        }
    }

    public async ValueTask StopAsync(
        string sessionId,
        CancellationToken cancellationToken = default)
    {
        Session? session;
        lock (_gate) _sessions.TryGetValue(sessionId, out session);
        if (session is null) return;

        await session.Gate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            await StopSessionAsync(session).ConfigureAwait(false);
            lock (_gate) _sessions.Remove(sessionId);
        }
        finally
        {
            session.Gate.Release();
        }
    }

    public async ValueTask DisposeAsync()
    {
        Session[] sessions;
        lock (_gate)
        {
            if (_disposed) return;
            _disposed = true;
            sessions = _sessions.Values.ToArray();
        }

        foreach (var session in sessions)
        {
            await session.Gate.WaitAsync(CancellationToken.None).ConfigureAwait(false);
            try { await StopSessionAsync(session).ConfigureAwait(false); }
            finally { session.Gate.Release(); }
        }

        lock (_gate) _sessions.Clear();
    }

    private void ValidateMachinePaths()
    {
        if (!File.Exists(_options.StarCraftExecutablePath))
            throw new FileNotFoundException("The configured StarCraft II executable was not found.", _options.StarCraftExecutablePath);
        if (!Directory.Exists(_options.StarCraftWorkingDirectory))
            throw new DirectoryNotFoundException("The configured StarCraft II working directory was not found.");
        if (!File.Exists(_options.MapPath))
            throw new FileNotFoundException("The configured multiplayer map was not found.", _options.MapPath);
    }

    private static void ValidateLaunch(Sc2SessionLaunchRequest request)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(request.MatchId);
        ArgumentException.ThrowIfNullOrWhiteSpace(request.SessionId);
        if (request.Participants is null || request.Participants.Count != 2)
            throw new InvalidOperationException("An SC2 process session requires exactly two participants.");
        if (request.Participants.Count(p => p.IsGameHost) != 1)
            throw new InvalidOperationException("Exactly one participant must own multiplayer game creation.");
        if (request.Participants.Select(p => p.ParticipantId).Distinct(StringComparer.Ordinal).Count() != 2)
            throw new InvalidOperationException("SC2 participant IDs must be unique.");
        if (request.Participants.Select(p => p.GamePort).Distinct().Count() != 2)
            throw new InvalidOperationException("Each SC2 process must have a distinct listener port.");
        if (request.Participants.Any(p => p.BotBuild is null || p.GamePort is < 1 or > 65535 ||
            string.IsNullOrWhiteSpace(p.BotBuild.BuildId) ||
            string.IsNullOrWhiteSpace(p.BotBuild.ContentSha256)))
            throw new InvalidOperationException("SC2 participant launch data is incomplete or invalid.");
        if (request.StartPort is < 1 or > 65530)
            throw new InvalidOperationException("The match-level StartPort cannot reserve its five derived ports.");
    }

    private static Process StartProcess(ProcessStartInfo startInfo)
    {
        var process = Process.Start(startInfo);
        return process ?? throw new InvalidOperationException($"Failed to start process '{startInfo.FileName}'.");
    }

    private static void AddArgument(ProcessStartInfo startInfo, string name, int value)
    {
        startInfo.ArgumentList.Add(name);
        startInfo.ArgumentList.Add(value.ToString(CultureInfo.InvariantCulture));
    }

    private static void AddArgument(ProcessStartInfo startInfo, string name, string value)
    {
        startInfo.ArgumentList.Add(name);
        startInfo.ArgumentList.Add(value);
    }

    private static void ObserveRunnerOutput(Runner runner, string? line)
    {
        if (string.IsNullOrWhiteSpace(line)) return;
        const string joinedPrefix = "SC2_JOINED playerId=";
        const string resultPrefix = "SC2_RESULT playerId=";
        if (line.StartsWith(joinedPrefix, StringComparison.Ordinal) &&
            uint.TryParse(line.AsSpan(joinedPrefix.Length), NumberStyles.None, CultureInfo.InvariantCulture, out var playerId))
            runner.Joined.TrySetResult(playerId);
        else if (line.StartsWith(resultPrefix, StringComparison.Ordinal))
        {
            var payload = line[resultPrefix.Length..];
            var separator = payload.IndexOf(" result=", StringComparison.Ordinal);
            if (separator > 0 &&
                uint.TryParse(payload.AsSpan(0, separator), NumberStyles.None, CultureInfo.InvariantCulture, out var playerId))
            {
                var result = payload[(separator + " result=".Length)..];
                if (!string.IsNullOrWhiteSpace(result))
                    runner.Result.TrySetResult(new RunnerResult(playerId, result));
            }
        }
    }

    private async ValueTask StopSessionAsync(Session session)
    {
        session.Stopping = true;
        foreach (var runner in session.Runners)
            TryKill(runner.Process);
        foreach (var process in session.Sc2Processes)
            TryKill(process);

        var processes = session.Runners.Select(r => r.Process).Concat(session.Sc2Processes);
        foreach (var process in processes)
        {
            try
            {
                if (!process.HasExited)
                    await process.WaitForExitAsync().WaitAsync(_options.ProcessStopTimeout).ConfigureAwait(false);
            }
            catch (TimeoutException)
            {
                TryKill(process);
            }
            catch (InvalidOperationException) { }
            finally
            {
                process.Dispose();
            }
        }
    }

    private static void TryKill(Process process)
    {
        try { if (!process.HasExited) process.Kill(entireProcessTree: true); }
        catch (InvalidOperationException) { }
        catch (System.ComponentModel.Win32Exception) { }
    }

    private static int SafeExitCode(Process process)
    {
        try { return process.HasExited ? process.ExitCode : -1; }
        catch (InvalidOperationException) { return -1; }
    }

    private static Sc2RuntimeSessionSnapshot Failed(Session session, string code, string message) =>
        new(session.MatchId, session.SessionId, GameSessionState.Failed, DateTimeOffset.UtcNow, code, message);
}
