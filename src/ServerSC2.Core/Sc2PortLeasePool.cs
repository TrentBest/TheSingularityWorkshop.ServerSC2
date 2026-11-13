namespace ServerSC2.Core;

/// <summary>A process-local lease for one distinct SC2 game/start port pair.</summary>
public sealed class Sc2PortLease : IDisposable
{
    private Action<Guid>? _release;

    internal Sc2PortLease(Guid leaseId, int gamePort, int startPort, Action<Guid> release)
    {
        LeaseId = leaseId;
        GamePort = gamePort;
        StartPort = startPort;
        _release = release;
    }

    public Guid LeaseId { get; }
    public int GamePort { get; }
    public int StartPort { get; }

    public void Dispose() => Interlocked.Exchange(ref _release, null)?.Invoke(LeaseId);
}

/// <summary>
/// Allocates bounded, non-overlapping game/start port pairs for concurrent sessions within
/// one ServerSC2 host process. The OS-level process supervisor must still handle bind failures.
/// </summary>
public sealed class Sc2PortLeasePool
{
    private readonly object _gate = new();
    private readonly Sc2ServerProfile _profile;
    private readonly Dictionary<Guid, int> _leases = new();

    public Sc2PortLeasePool(Sc2ServerProfile profile)
    {
        ArgumentNullException.ThrowIfNull(profile);
        var errors = profile.Validate();
        if (errors.Count != 0)
            throw new ArgumentException($"The SC2 server profile is invalid: {string.Join(", ", errors)}", nameof(profile));
        _profile = profile;
    }

    public int ActiveLeaseCount
    {
        get { lock (_gate) return _leases.Count; }
    }

    public bool TryAcquire(out Sc2PortLease? lease)
    {
        lock (_gate)
        {
            if (_leases.Count >= _profile.MaximumConcurrentMatches)
            {
                lease = null;
                return false;
            }

            var usedSlots = _leases.Values.ToHashSet();
            for (var slot = 0; slot < _profile.MaximumConcurrentMatches; slot++)
            {
                if (usedSlots.Contains(slot))
                    continue;

                var leaseId = Guid.NewGuid();
                _leases.Add(leaseId, slot);
                lease = new Sc2PortLease(
                    leaseId,
                    checked(_profile.GamePortFirst + slot),
                    checked(_profile.StartPortFirst + slot),
                    Release);
                return true;
            }

            lease = null;
            return false;
        }
    }

    private void Release(Guid leaseId)
    {
        lock (_gate)
            _leases.Remove(leaseId);
    }
}
