using ServerSC2.Core;
using ServerSC2.ServerAppAdapter;
using ServerApp.Core;

var checks = new (string Name, Action Run)[]
{
    ("valid profile is accepted", ValidProfileIsAccepted),
    ("overlapping port ranges are rejected", OverlappingRangesAreRejected),
    ("insufficient port capacity is rejected", InsufficientCapacityIsRejected),
    ("leases allocate distinct game and start ports", LeasesAreDistinct),
    ("pool enforces maximum concurrency", PoolEnforcesCapacity),
    ("disposing a lease makes its slot reusable", DisposedLeaseIsReusable),
    ("lease disposal is idempotent", LeaseDisposalIsIdempotent),
    ("adapter maps immutable ServerApp assignments", AdapterMapsAssignment),
    ("adapter rejects wrong game before allocating ports", AdapterRejectsWrongGame),
    ("adapter releases a lease when runtime startup fails", AdapterReleasesOnStartupFailure)
};

var failures = new List<string>();
foreach (var check in checks)
{
    try
    {
        check.Run();
        Console.WriteLine($"PASS {check.Name}");
    }
    catch (Exception exception)
    {
        failures.Add($"{check.Name}: {exception.Message}");
        Console.WriteLine($"FAIL {check.Name}: {exception.Message}");
    }
}

Console.WriteLine($"{checks.Length - failures.Count}/{checks.Length} checks passed.");
return failures.Count == 0 ? 0 : 1;

static Sc2ServerProfile ValidProfile() => new(
    "sc2-local-1v1", "0.1.0", "5.0.14", "AbyssalReefLE",
    5000, 5003, 6000, 6003, 4);

static void ValidProfileIsAccepted() =>
    Assert(ValidProfile().Validate().Count == 0, "Expected valid profile.");

static void OverlappingRangesAreRejected()
{
    var profile = ValidProfile() with { StartPortFirst = 5002, StartPortLast = 5005 };
    Assert(profile.Validate().Contains("profile.port-ranges.overlap"), "Expected overlap rejection.");
}

static void InsufficientCapacityIsRejected()
{
    var errors = (ValidProfile() with { MaximumConcurrentMatches = 5 }).Validate();
    Assert(errors.Contains("profile.game-port-capacity.insufficient"), "Expected game-port capacity rejection.");
    Assert(errors.Contains("profile.start-port-capacity.insufficient"), "Expected start-port capacity rejection.");
}

static void LeasesAreDistinct()
{
    var pool = new Sc2PortLeasePool(ValidProfile());
    Assert(pool.TryAcquire(out var first) && first is not null, "First lease failed.");
    Assert(pool.TryAcquire(out var second) && second is not null, "Second lease failed.");
    using (first)
    using (second)
    {
        Assert(first!.GamePort != second!.GamePort, "Game ports collided.");
        Assert(first.StartPort != second.StartPort, "Start ports collided.");
        Assert(first.GamePort != first.StartPort, "Game and start port collided.");
    }
}

static void PoolEnforcesCapacity()
{
    var pool = new Sc2PortLeasePool(ValidProfile());
    var leases = new List<Sc2PortLease>();
    try
    {
        for (var i = 0; i < 4; i++)
        {
            Assert(pool.TryAcquire(out var lease) && lease is not null, $"Lease {i} failed.");
            leases.Add(lease!);
        }
        Assert(!pool.TryAcquire(out _), "Pool exceeded configured capacity.");
        Assert(pool.ActiveLeaseCount == 4, "Unexpected active lease count.");
    }
    finally
    {
        foreach (var lease in leases) lease.Dispose();
    }
}

static void DisposedLeaseIsReusable()
{
    var pool = new Sc2PortLeasePool(ValidProfile());
    Assert(pool.TryAcquire(out var first) && first is not null, "First lease failed.");
    var firstGamePort = first!.GamePort;
    first.Dispose();
    Assert(pool.TryAcquire(out var second) && second is not null, "Lease after release failed.");
    using (second)
        Assert(second!.GamePort == firstGamePort, "Released slot was not reused.");
}

static void LeaseDisposalIsIdempotent()
{
    var pool = new Sc2PortLeasePool(ValidProfile());
    Assert(pool.TryAcquire(out var lease) && lease is not null, "Lease failed.");
    lease!.Dispose();
    lease.Dispose();
    Assert(pool.ActiveLeaseCount == 0, "Lease was not released exactly once.");
}

static void Assert(bool condition, string message)
{
    if (!condition) throw new InvalidOperationException(message);
}


static CompetitionDefinition TestCompetition() => new(
    "sc2-ladder", Sc2GameSessionAdapter.StarCraftIIGameId, "ladder-rules", "1",
    [new CompetitionMatchFormat("1v1", [1, 1])]);

static MatchAssignment TestAssignment(string gameId = Sc2GameSessionAdapter.StarCraftIIGameId) => new(
    "match-001", "sc2-ladder", gameId, "ladder-rules", "1", "1v1", "0.1.0",
    DateTimeOffset.UtcNow,
    [
        new MatchParticipantAssignment("p1", "team-a", new BotBuildReference("bot-a", "build-a", new string('a', 64))),
        new MatchParticipantAssignment("p2", "team-b", new BotBuildReference("bot-b", "build-b", new string('b', 64)))
    ]);

static Sc2GameSessionAdapter CreateAdapter(Sc2PortLeasePool pool, FakeSc2Runtime runtime) =>
    new(ValidProfile(), pool, runtime);

static void AdapterMapsAssignment()
{
    var pool = new Sc2PortLeasePool(ValidProfile());
    var runtime = new FakeSc2Runtime();
    var adapter = CreateAdapter(pool, runtime);
    var result = adapter.StartAsync(new GameSessionStartRequest(TestAssignment(), "session-001"))
        .AsTask().GetAwaiter().GetResult();
    Assert(result.State == GameSessionState.Ready, "Adapter did not return Ready.");
    Assert(runtime.LastRequest is not null, "Runtime did not receive a launch request.");
    Assert(runtime.LastRequest!.Participants.Count == 2, "Expected two participant launch records.");
    Assert(runtime.LastRequest.Participants[0].BotBuild.BuildId == "build-a", "First immutable build was not preserved.");
    Assert(pool.ActiveLeaseCount == 1, "Port lease was not retained for the active session.");
    adapter.StopAsync("session-001").AsTask().GetAwaiter().GetResult();
    Assert(pool.ActiveLeaseCount == 0, "Port lease was not released after stop.");
    adapter.DisposeAsync().AsTask().GetAwaiter().GetResult();
}

static void AdapterRejectsWrongGame()
{
    var pool = new Sc2PortLeasePool(ValidProfile());
    var runtime = new FakeSc2Runtime();
    using var adapter = CreateAdapter(pool, runtime);
    try
    {
        adapter.StartAsync(new GameSessionStartRequest(TestAssignment("another-game"), "session-002"))
            .AsTask().GetAwaiter().GetResult();
        throw new InvalidOperationException("Expected wrong-game rejection.");
    }
    catch (InvalidOperationException exception) when (exception.Message.Contains("different game", StringComparison.Ordinal)) { }
    Assert(pool.ActiveLeaseCount == 0, "Wrong-game assignment consumed a port lease.");
    adapter.DisposeAsync().AsTask().GetAwaiter().GetResult();
}

static void AdapterReleasesOnStartupFailure()
{
    var pool = new Sc2PortLeasePool(ValidProfile());
    var runtime = new FakeSc2Runtime { ThrowOnStart = true };
    using var adapter = CreateAdapter(pool, runtime);
    try
    {
        adapter.StartAsync(new GameSessionStartRequest(TestAssignment(), "session-003"))
            .AsTask().GetAwaiter().GetResult();
        throw new InvalidOperationException("Expected runtime startup failure.");
    }
    catch (InvalidOperationException exception) when (exception.Message == "synthetic startup failure") { }
    Assert(pool.ActiveLeaseCount == 0, "Startup failure leaked the port lease.");
    adapter.DisposeAsync().AsTask().GetAwaiter().GetResult();
}

sealed class FakeSc2Runtime : ISc2SessionRuntime
{
    public Sc2SessionLaunchRequest? LastRequest { get; private set; }
    public bool ThrowOnStart { get; init; }

    public ValueTask<Sc2RuntimeSessionSnapshot> StartAsync(
        Sc2SessionLaunchRequest request, CancellationToken cancellationToken = default)
    {
        LastRequest = request;
        if (ThrowOnStart) throw new InvalidOperationException("synthetic startup failure");
        return ValueTask.FromResult(new Sc2RuntimeSessionSnapshot(
            request.MatchId, request.SessionId, ServerApp.Core.GameSessionState.Ready, DateTimeOffset.UtcNow));
    }

    public ValueTask<Sc2RuntimeSessionSnapshot?> GetStatusAsync(
        string sessionId, CancellationToken cancellationToken = default) =>
        ValueTask.FromResult<Sc2RuntimeSessionSnapshot?>(null);

    public ValueTask StopAsync(string sessionId, CancellationToken cancellationToken = default) =>
        ValueTask.CompletedTask;
}
