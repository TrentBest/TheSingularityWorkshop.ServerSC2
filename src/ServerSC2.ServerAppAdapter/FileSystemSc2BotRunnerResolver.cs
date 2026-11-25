using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using ServerApp.Core;

namespace ServerSC2.ServerAppAdapter;

/// <summary>
/// Resolves immutable bot packages from a host-owned content-addressed store:
/// {store}/{BotIdentityId}/{BuildId}/{ContentSha256}/bot-build.json.
/// The store must be writable only by the trusted build-registration pipeline.
/// </summary>
public sealed class FileSystemSc2BotRunnerResolver : ISc2BotRunnerResolver
{
    private const string ManifestFileName = "bot-build.json";

    private sealed record PackageFile(string Path, string Sha256);

    private sealed record PackageManifest(
        int SchemaVersion,
        string ContentSha256,
        string RunnerExecutablePath,
        string BotDefinitionPath,
        IReadOnlyList<PackageFile> Files);

    private static readonly JsonSerializerOptions ManifestJsonOptions = new()
    {
        PropertyNameCaseInsensitive = false,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
        MaxDepth = 16
    };

    private readonly string _storeRoot;

    public FileSystemSc2BotRunnerResolver(string storeRoot)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(storeRoot);
        _storeRoot = Path.GetFullPath(storeRoot);
        if (!Directory.Exists(_storeRoot))
            throw new DirectoryNotFoundException("The configured immutable bot package store does not exist.");
    }

    public Sc2BotRunnerArtifact ResolveBotArtifact(BotBuildReference build)
    {
        ArgumentNullException.ThrowIfNull(build);
        ValidatePathSegment(build.BotIdentityId, nameof(build.BotIdentityId));
        ValidatePathSegment(build.BuildId, nameof(build.BuildId));
        if (!IsSha256(build.ContentSha256))
            throw new InvalidOperationException("The admitted bot build must contain a valid SHA-256 digest.");

        var packageRoot = Path.GetFullPath(Path.Combine(
            _storeRoot, build.BotIdentityId, build.BuildId, build.ContentSha256.ToLowerInvariant()));
        EnsureInsideStore(packageRoot);
        if (!Directory.Exists(packageRoot))
            throw new DirectoryNotFoundException("The exact admitted bot build package was not found.");

        var manifestPath = Path.Combine(packageRoot, ManifestFileName);
        if (!File.Exists(manifestPath))
            throw new FileNotFoundException("The immutable bot build package manifest is missing.", manifestPath);

        PackageManifest manifest;
        try
        {
            manifest = JsonSerializer.Deserialize<PackageManifest>(
                File.ReadAllText(manifestPath), ManifestJsonOptions)
                ?? throw new InvalidOperationException("The immutable bot build package manifest is empty.");
        }
        catch (JsonException exception)
        {
            throw new InvalidOperationException("The immutable bot build package manifest is invalid JSON.", exception);
        }

        if (manifest.SchemaVersion != 1 ||
            !string.Equals(manifest.ContentSha256, build.ContentSha256, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("The package manifest version or digest does not match the admitted build.");

        if (manifest.Files is null || manifest.Files.Count is < 2 or > 4096)
            throw new InvalidOperationException("The package manifest must declare between 2 and 4096 payload files.");

        var fileHashes = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var file in manifest.Files)
        {
            if (file is null || string.IsNullOrWhiteSpace(file.Path) || !IsSha256(file.Sha256))
                throw new InvalidOperationException("The package manifest contains an invalid file entry.");
            var normalizedPath = NormalizeRelativePath(file.Path);
            if (!fileHashes.TryAdd(normalizedPath, file.Sha256.ToLowerInvariant()))
                throw new InvalidOperationException("The package manifest contains duplicate payload paths.");

            var fullPath = ResolvePayloadPath(packageRoot, normalizedPath);
            if (!File.Exists(fullPath))
                throw new FileNotFoundException("A declared immutable bot package payload file is missing.", fullPath);
            VerifyHash(fullPath, file.Sha256, normalizedPath);
        }

        var computedDigest = ComputePackageDigest(fileHashes);
        if (!string.Equals(computedDigest, build.ContentSha256, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("The immutable bot package payload does not match its registered content digest.");

        var runnerRelativePath = NormalizeRelativePath(manifest.RunnerExecutablePath);
        var definitionRelativePath = NormalizeRelativePath(manifest.BotDefinitionPath);
        if (!fileHashes.TryGetValue(runnerRelativePath, out var runnerHash) ||
            !fileHashes.TryGetValue(definitionRelativePath, out var definitionHash))
            throw new InvalidOperationException("The package manifest must pin both the runner executable and BotDefinition.");

        return new Sc2BotRunnerArtifact(
            packageRoot,
            ResolvePayloadPath(packageRoot, runnerRelativePath),
            ResolvePayloadPath(packageRoot, definitionRelativePath),
            computedDigest,
            runnerHash,
            definitionHash);
    }

    private void EnsureInsideStore(string packageRoot)
    {
        var relative = Path.GetRelativePath(_storeRoot, packageRoot);
        if (relative == "." || relative == ".." ||
            relative.StartsWith(".." + Path.DirectorySeparatorChar, StringComparison.Ordinal) ||
            Path.IsPathRooted(relative))
            throw new InvalidOperationException("The immutable bot package path escaped the configured store.");
    }

    private static string ResolvePayloadPath(string packageRoot, string relativePath)
    {
        var fullPath = Path.GetFullPath(relativePath.Replace('/', Path.DirectorySeparatorChar), packageRoot);
        var relative = Path.GetRelativePath(packageRoot, fullPath);
        if (relative == "." || relative == ".." ||
            relative.StartsWith(".." + Path.DirectorySeparatorChar, StringComparison.Ordinal) ||
            Path.IsPathRooted(relative))
            throw new InvalidOperationException("A package payload path escaped its immutable package root.");
        return fullPath;
    }

    private static string NormalizeRelativePath(string path)
    {
        if (path.Contains('\\') || Path.IsPathRooted(path) ||
            path.Split('/').Any(segment => segment is "" or "." or ".."))
            throw new InvalidOperationException("Package payload paths must be normalized relative paths.");
        return path;
    }

    private static string ComputePackageDigest(IReadOnlyDictionary<string, string> files)
    {
        var canonical = new StringBuilder();
        foreach (var file in files.OrderBy(pair => pair.Key, StringComparer.Ordinal))
            canonical.Append(file.Key).Append('\n').Append(file.Value.ToLowerInvariant()).Append('\n');
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(canonical.ToString())));
    }

    private static void VerifyHash(string path, string expectedHash, string label)
    {
        using var stream = File.OpenRead(path);
        var actualHash = Convert.ToHexString(SHA256.HashData(stream));
        if (!string.Equals(actualHash, expectedHash, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException($"Package payload '{label}' failed SHA-256 verification.");
    }

    private static void ValidatePathSegment(string value, string parameterName)
    {
        if (string.IsNullOrWhiteSpace(value) || value is "." or ".." ||
            value.Any(character => !(char.IsAsciiLetterOrDigit(character) || character is '.' or '_' or '-')))
            throw new ArgumentException("Build identity and build ID must be safe single path segments.", parameterName);
    }

    private static bool IsSha256(string? value) =>
        value is { Length: 64 } && value.All(Uri.IsHexDigit);
}
