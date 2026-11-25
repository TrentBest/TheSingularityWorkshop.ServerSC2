using ServerApp.Core;
using ServerSC2.Core;

namespace ServerSC2.ServerAppAdapter;

/// <summary>
/// Trusted deployment settings for the concrete SC2 process-backed ServerApp adapter.
/// Every path is host configuration; none is derived from a match request or participant.
/// </summary>
public sealed record Sc2GameSessionHostOptions(
    Sc2ServerProfile ServerProfile,
    Sc2ProcessRuntimeOptions ProcessRuntime,
    string BotPackageStoreRoot);

/// <summary>
/// Owns the concrete adapter, process runtime, and immutable bot-package resolver as one
/// host lifetime. Dispose the host during server-role shutdown to stop active processes.
/// </summary>
public sealed class Sc2GameSessionHost : IAsyncDisposable
{
    private readonly Sc2ProcessSessionRuntime _runtime;
    private int _disposed;

    internal Sc2GameSessionHost(
        Sc2GameSessionAdapter adapter,
        Sc2ProcessSessionRuntime runtime)
    {
        Adapter = adapter;
        _runtime = runtime;
    }

    /// <summary>The game-neutral adapter to register with ServerApp's session coordinator.</summary>
    public Sc2GameSessionAdapter Adapter { get; }

    public async ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0)
            return;

        try
        {
            await Adapter.DisposeAsync().ConfigureAwait(false);
        }
        finally
        {
            await _runtime.DisposeAsync().ConfigureAwait(false);
        }
    }
}

/// <summary>
/// Composition root for the current two-participant SC2 process runtime. It binds the
/// host-owned package-store root to FileSystemSc2BotRunnerResolver so callers cannot
/// accidentally construct the production adapter without immutable build resolution.
/// </summary>
public static class Sc2GameSessionHostFactory
{
    public static Sc2GameSessionHost Create(Sc2GameSessionHostOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);
        ArgumentNullException.ThrowIfNull(options.ServerProfile);
        ArgumentNullException.ThrowIfNull(options.ProcessRuntime);
        ArgumentException.ThrowIfNullOrWhiteSpace(options.BotPackageStoreRoot);

        var profileErrors = options.ServerProfile.Validate();
        if (profileErrors.Count != 0)
            throw new ArgumentException(
                $"The SC2 server profile is invalid: {string.Join(", ", profileErrors)}",
                nameof(options));

        var runtimeErrors = options.ProcessRuntime.Validate();
        if (runtimeErrors.Count != 0)
            throw new ArgumentException(
                $"The SC2 process runtime options are invalid: {string.Join(", ", runtimeErrors)}",
                nameof(options));

        if (options.ServerProfile.MaximumParticipantsPerMatch != 2)
            throw new InvalidOperationException(
                "The current process supervisor supports exactly two participants; observer-host topology is not yet integrated.");

        if (!string.Equals(
                options.ServerProfile.MapId,
                options.ProcessRuntime.MapId,
                StringComparison.Ordinal))
            throw new InvalidOperationException(
                "The trusted ServerApp profile and SC2 process runtime must select the same map.",
                nameof(options));

        var packageStoreRoot = Path.GetFullPath(options.BotPackageStoreRoot);
        if (!Directory.Exists(packageStoreRoot))
            throw new DirectoryNotFoundException(
                "The configured immutable bot package store does not exist.");

        var resolver = new FileSystemSc2BotRunnerResolver(packageStoreRoot);
        var runtime = new Sc2ProcessSessionRuntime(options.ProcessRuntime, resolver);
        try
        {
            var ports = new Sc2PortLeasePool(options.ServerProfile);
            var adapter = new Sc2GameSessionAdapter(options.ServerProfile, ports, runtime);
            return new Sc2GameSessionHost(adapter, runtime);
        }
        catch
        {
            runtime.DisposeAsync().AsTask().GetAwaiter().GetResult();
            throw;
        }
    }
}
