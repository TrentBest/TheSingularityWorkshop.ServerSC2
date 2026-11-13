using ServerSC2.Core;

var checks = new (string Name, Action Run)[]
{
    ("valid profile is accepted", ValidProfileIsAccepted),
    ("overlapping port ranges are rejected", OverlappingRangesAreRejected),
    ("insufficient port capacity is rejected", InsufficientCapacityIsRejected),
    ("leases allocate distinct game and start ports", LeasesAreDistinct),
    ("pool enforces maximum concurrency", PoolEnforcesCapacity),
    ("disposing a lease makes its slot reusable", DisposedLeaseIsReusable),
    ("lease disposal is idempotent", LeaseDisposalIsIdempotent)
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
