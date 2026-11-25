using System.Security.Cryptography;
using ServerApp.Core;

namespace ServerSC2.ServerAppAdapter;

/// <summary>
/// A trusted, immutable package resolution for one admitted bot build. Paths are produced by
/// the host resolver, never by a participant. ContentSha256 identifies the complete package;
/// the two file hashes independently pin the exact runner and authored definition payloads.
/// </summary>
public sealed record Sc2BotRunnerArtifact(
    string PackageRootPath,
    string RunnerExecutablePath,
    string BotDefinitionPath,
    string ContentSha256,
    string RunnerExecutableSha256,
    string BotDefinitionSha256)
{
    /// <summary>
    /// Validates package identity, path containment, file presence, and payload hashes before
    /// any SC2 or runner process is started.
    /// </summary>
    public void ValidateFor(BotBuildReference build)
    {
        ArgumentNullException.ThrowIfNull(build);
        if (string.IsNullOrWhiteSpace(build.BuildId) ||
            !IsSha256(build.ContentSha256) ||
            !IsSha256(ContentSha256) ||
            !string.Equals(ContentSha256, build.ContentSha256, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("The resolved bot package digest does not match the admitted immutable build.");

        if (string.IsNullOrWhiteSpace(PackageRootPath) ||
            string.IsNullOrWhiteSpace(RunnerExecutablePath) ||
            string.IsNullOrWhiteSpace(BotDefinitionPath))
            throw new InvalidOperationException("The resolved bot package is missing its root, runner, or BotDefinition path.");

        var root = Path.GetFullPath(PackageRootPath);
        if (!Directory.Exists(root))
            throw new DirectoryNotFoundException("The resolved immutable bot package directory does not exist.");

        var runner = ResolvePackageFile(root, RunnerExecutablePath, "runner executable");
        var definition = ResolvePackageFile(root, BotDefinitionPath, "BotDefinition");
        if (!File.Exists(runner))
            throw new FileNotFoundException("The resolved immutable bot runner executable does not exist.", runner);
        if (!File.Exists(definition))
            throw new FileNotFoundException("The resolved immutable BotDefinition artifact does not exist.", definition);

        VerifyFileHash(runner, RunnerExecutableSha256, "runner executable");
        VerifyFileHash(definition, BotDefinitionSha256, "BotDefinition");
    }

    private static string ResolvePackageFile(string root, string path, string label)
    {
        var fullPath = Path.GetFullPath(path, root);
        var relative = Path.GetRelativePath(root, fullPath);
        if (relative == "." || relative == ".." ||
            relative.StartsWith(".." + Path.DirectorySeparatorChar, StringComparison.Ordinal) ||
            Path.IsPathRooted(relative))
            throw new InvalidOperationException($"The resolved {label} must remain inside its immutable package root.");
        return fullPath;
    }

    private static void VerifyFileHash(string path, string expectedHash, string label)
    {
        if (!IsSha256(expectedHash))
            throw new InvalidOperationException($"The resolved {label} SHA-256 is missing or invalid.");
        using var stream = File.OpenRead(path);
        var actualHash = Convert.ToHexString(SHA256.HashData(stream));
        if (!string.Equals(actualHash, expectedHash, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException($"The resolved {label} does not match its immutable SHA-256.");
    }

    private static bool IsSha256(string? value) =>
        value is { Length: 64 } && value.All(Uri.IsHexDigit);
}

/// <summary>
/// Resolves only host-registered immutable bot builds. Implementations must verify the complete
/// package digest against BotBuildReference.ContentSha256 and return trusted package-local paths.
/// </summary>
public interface ISc2BotRunnerResolver
{
    Sc2BotRunnerArtifact ResolveBotArtifact(BotBuildReference build);
}
