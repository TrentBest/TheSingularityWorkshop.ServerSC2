using ServerSC2.Core;
using ServerSC2.ServerAppAdapter;
using ServerApp.Core;

var checks = new (string Name, Action Run)[]
{
    ("valid profile is accepted", ValidProfileIsAccepted),
    ("overlapping port ranges are rejected", OverlappingRangesAreRejected),
    ("insufficient port capacity is rejected", InsufficientCapacityIsRejected),
    ("leases allocate participant listeners and an observer-capable multiplayer block", LeasesAreDistinct),
    ("leases size participant ports and multiplayer blocks by format", VariableParticipantLease),
    ("pool enforces maximum concurrency", PoolEnforcesCapacity),
    ("disposing a lease makes its slot reusable", DisposedLeaseIsReusable),
    ("lease disposal is idempotent", LeaseDisposalIsIdempotent),
    ("adapter maps immutable ServerApp assignments", AdapterMapsAssignment),
    ("adapter rejects mismatched observed match identity", AdapterRejectsMismatchedObservedMatch),
    ("adapter rejects wrong game before allocating ports", AdapterRejectsWrongGame),
    ("adapter releases a lease when runtime startup fails", AdapterReleasesOnStartupFailure),
    ("observer process plan isolates CreateGame authority", ObserverPlanIsolatesCreateGame),
    ("observer process plan scales to arbitrary participant counts", ObserverPlanScales),
    ("observer process plan rejects invalid build and port boundaries", ObserverPlanRejectsInvalidBoundaries)
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
    5000, 5007, 6000, 6024, 4);

static void ValidProfileIsAccepted() =>
    Assert(ValidProfile().Validate().Count == 0, "Expected valid profile.");

static void OverlappingRangesAreRejected()
{
    var profile = ValidProfile() with { GamePortFirst = 6000, GamePortLast = 6018 };
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
        Assert(first!.HostGamePort != first.JoinerGamePort, "The two listeners must differ.");
        Assert(second!.HostGamePort != second.JoinerGamePort, "The two listeners must differ.");
        Assert(first.HostGamePort != second.HostGamePort && first.HostGamePort != second.JoinerGamePort &&
            first.JoinerGamePort != second.HostGamePort && first.JoinerGamePort != second.JoinerGamePort,
            "Concurrent match listener ports collided.");
        Assert(first.StartPort != second.StartPort, "Multiplayer block bases collided.");
        Assert(first.StartPort + 7 < second.StartPort || second.StartPort + 7 < first.StartPort,
            "Concurrent multiplayer port blocks overlapped.");
        Assert(first.HostGamePort != first.StartPort && first.JoinerGamePort != first.StartPort + 1,
            "Listener and multiplayer ports collided.");
    }
}

static void VariableParticipantLease()
{
    var profile = ValidProfile() with
    {
        GamePortLast = 5011,
        StartPortLast = 6031,
        MaximumParticipantsPerMatch = 3
    };
    Assert(profile.Validate().Count == 0, "Expected the three-participant profile to be valid.");

    var pool = new Sc2PortLeasePool(profile);
    Assert(pool.TryAcquire(2, out var twoPlayer) && twoPlayer is not null, "Two-participant lease failed.");
    Assert(pool.TryAcquire(3, out var threePlayer) && threePlayer is not null, "Three-participant lease failed.");
    using (twoPlayer)
    using (threePlayer)
    {
        Assert(twoPlayer!.ParticipantGamePorts.Count == 2, "Two-participant lease has the wrong listener count.");
        Assert(threePlayer!.ParticipantGamePorts.Count == 3, "Three-participant lease has the wrong listener count.");
        Assert(twoPlayer.MultiplayerPortCount == 9 && threePlayer.MultiplayerPortCount == 9,
            "The lease did not reserve the profile's observer-plus-participant multiplayer footprint.");
        Assert(twoPlayer.ParticipantGamePorts.Intersect(threePlayer.ParticipantGamePorts).Count() == 0,
            "Participant listener ranges collided.");
        var firstBlock = Enumerable.Range(twoPlayer.StartPort, twoPlayer.MultiplayerPortCount + 1);
        var secondBlock = Enumerable.Range(threePlayer.StartPort, threePlayer.MultiplayerPortCount + 1);
        Assert(!firstBlock.Intersect(secondBlock).Any(), "Multiplayer port blocks collided.");
    }

    Assert(!pool.TryAcquire(4, out _), "The pool accepted more participants than the profile allows.");
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
    var firstGamePort = first!.HostGamePort;
    first.Dispose();
    Assert(pool.TryAcquire(out var second) && second is not null, "Lease after release failed.");
    using (second)
        Assert(second!.HostGamePort == firstGamePort, "Released slot was not reused.");
}

static void LeaseDisposalIsIdempotent()
{
    var pool = new Sc2PortLeasePool(ValidProfile());
    Assert(pool.TryAcquire(out var lease) && lease is not null, "Lease failed.");
    lease!.Dispose();
    lease.Dispose();
    Assert(pool.ActiveLeaseCount == 0, "Lease was not released exactly once.");
}


static Sc2SessionLaunchRequest ObserverLaunchRequest(int participantCount)
{
    var participants = Enumerable.Range(0, participantCount)
        .Select(index => new Sc2ParticipantLaunch(
            $"p{index + 1}",
            $"team-{index / 2 + 1}",
            new BotBuildReference($"bot-{index + 1}", $"build-{index + 1}", new string("abcdef0123456789"[index % 16], 64)),
            5000 + index,
            false))
        .ToArray();
    return new Sc2SessionLaunchRequest(
        "match-observer", "session-observer", "0.1.0", "5.0.14", "AbyssalReefLE",
        6000, Array.AsReadOnly(participants));
}

static void ObserverPlanIsolatesCreateGame()
{
    var plan = Sc2MatchProcessPlan.Create(ObserverLaunchRequest(2));
    Assert(plan.Sc2Clients.Count == 3, "Expected one observer and two participant SC2 clients.");
    Assert(plan.BotRunners.Count == 2, "Expected one bot runner per participant.");
    Assert(plan.Sc2Clients.Count(client => client.Role == Sc2ProcessRole.Observer) == 1,
        "Expected exactly one observer process.");
    Assert(plan.Sc2Clients.Count(client => client.HasCreateGameAuthority) == 1,
        "Expected exactly one CreateGame authority.");
    var observer = plan.Sc2Clients.Single(client => client.Role == Sc2ProcessRole.Observer);
    Assert(observer.ParticipantId is null && observer.GamePort is null && observer.HasCreateGameAuthority,
        "Observer must be neutral and exclusively own CreateGame authority.");
    Assert(plan.Sc2Clients.Where(client => client.Role == Sc2ProcessRole.Participant)
        .All(client => !client.HasCreateGameAuthority && client.ParticipantId is not null && client.GamePort is not null),
        "Participant SC2 clients must have identity/listener ports and no CreateGame authority.");
}

static void ObserverPlanScales()
{
    for (var count = 2; count <= 8; count++)
    {
        var plan = Sc2MatchProcessPlan.Create(ObserverLaunchRequest(count));
        Assert(plan.Sc2Clients.Count == count + 1, $"Expected {count + 1} SC2 clients for {count} participants.");
        Assert(plan.BotRunners.Count == count, $"Expected {count} runners for {count} participants.");
        Assert(plan.Sc2Clients.Select(client => client.ClientOrdinal).Distinct().Count() == count + 1,
            "SC2 client ordinals must be unique.");
    }

    var invalid = ObserverLaunchRequest(2);
    var participantWithAuthority = invalid with
    {
        Participants = Array.AsReadOnly(invalid.Participants.Select((participant, index) =>
            index == 0 ? participant with { IsGameHost = true } : participant).ToArray())
    };
    try
    {
        Sc2MatchProcessPlan.Create(participantWithAuthority);
        throw new InvalidOperationException("Expected participant CreateGame authority to be rejected.");
    }
    catch (InvalidOperationException exception) when (exception.Message.Contains("cannot own CreateGame", StringComparison.Ordinal)) { }
}

static void ObserverPlanRejectsInvalidBoundaries()
{
    var valid = ObserverLaunchRequest(2);
    var invalidHash = valid with
    {
        Participants = Array.AsReadOnly(valid.Participants.Select((participant, index) =>
            index == 0 ? participant with
            {
                BotBuild = participant.BotBuild with { ContentSha256 = "not-a-sha256" }
            } : participant).ToArray())
    };
    AssertThrows(() => Sc2MatchProcessPlan.Create(invalidHash), "SHA-256");

    var overlappingListener = valid with
    {
        Participants = Array.AsReadOnly(valid.Participants.Select((participant, index) =>
            index == 0 ? participant with { GamePort = 6001 } : participant).ToArray())
    };
    AssertThrows(() => Sc2MatchProcessPlan.Create(overlappingListener), "cannot overlap");

    var overflowingBlock = valid with { StartPort = 65530 };
    AssertThrows(() => Sc2MatchProcessPlan.Create(overflowingBlock), "cannot reserve");
}

static void AssertThrows(Action action, string expectedMessage)
{
    try
    {
        action();
        throw new InvalidOperationException($"Expected rejection containing '{expectedMessage}'.");
    }
    catch (InvalidOperationException exception) when (exception.Message.Contains(expectedMessage, StringComparison.Ordinal)) { }
}

static void Assert(bool condition, string message)
{
    if (!condition) throw new InvalidOperationException(message);
}


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
    var launchRequest = runtime.LastRequest ?? throw new InvalidOperationException("Runtime did not receive a launch request.");
    Assert(launchRequest.Participants.Count == 2, "Expected two participant launch records.");
    Assert(launchRequest.Participants[0].BotBuild.BuildId == "build-a", "First immutable build was not preserved.");
    Assert(launchRequest.Participants[0].IsGameHost, "First participant was not designated host.");
    Assert(!launchRequest.Participants[1].IsGameHost, "Second participant was incorrectly designated host.");
    Assert(launchRequest.Participants[0].GamePort != launchRequest.Participants[1].GamePort,
        "Participants must receive distinct SC2 listener ports.");
    Assert(launchRequest.StartPort == 6000, "Expected one shared match-level StartPort base.");
    Assert(pool.ActiveLeaseCount == 1, "Port lease was not retained for the active session.");
    adapter.StopAsync("session-001").AsTask().GetAwaiter().GetResult();
    Assert(pool.ActiveLeaseCount == 0, "Port lease was not released after stop.");
    adapter.DisposeAsync().AsTask().GetAwaiter().GetResult();
}


static void AdapterRejectsMismatchedObservedMatch()
{
    var pool = new Sc2PortLeasePool(ValidProfile());
    var runtime = new FakeSc2Runtime();
    var adapter = CreateAdapter(pool, runtime);
    adapter.StartAsync(new GameSessionStartRequest(TestAssignment(), "session-004"))
        .AsTask().GetAwaiter().GetResult();
    runtime.StatusToReturn = new Sc2RuntimeSessionSnapshot(
        "different-match", "session-004", GameSessionState.Ready, DateTimeOffset.UtcNow);
    try
    {
        adapter.GetStatusAsync("session-004").AsTask().GetAwaiter().GetResult();
        throw new InvalidOperationException("Expected mismatched match identity rejection.");
    }
    catch (InvalidOperationException exception) when (exception.Message.Contains("invalid or mismatched", StringComparison.Ordinal)) { }
    adapter.StopAsync("session-004").AsTask().GetAwaiter().GetResult();
    Assert(pool.ActiveLeaseCount == 0, "Mismatched status cleanup did not release the port lease.");
    adapter.DisposeAsync().AsTask().GetAwaiter().GetResult();
}

static void AdapterRejectsWrongGame()
{
    var pool = new Sc2PortLeasePool(ValidProfile());
    var runtime = new FakeSc2Runtime();
    var adapter = CreateAdapter(pool, runtime);
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
    var adapter = CreateAdapter(pool, runtime);
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
    public Sc2RuntimeSessionSnapshot? StatusToReturn { get; set; }
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
        ValueTask.FromResult(StatusToReturn);

    public ValueTask StopAsync(string sessionId, CancellationToken cancellationToken = default) =>
        ValueTask.CompletedTask;
}
