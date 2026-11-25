using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using ServerApp.Core;
using ServerSC2.ServerAppAdapter;

namespace ServerSC2.ContractChecks;

internal static class FileSystemSc2BotRunnerResolverContractChecks
{
    [ModuleInitializer]
    internal static void Run()
    {
        var store = Path.Combine(Path.GetTempPath(), "ServerSC2.PackageResolverChecks", Guid.NewGuid().ToString("N"));
        var botIdentityId = "bot-1";
        var buildId = "build-1";
        var runnerBytes = Encoding.UTF8.GetBytes("runner-payload");
        var definitionBytes = Encoding.UTF8.GetBytes("{\"schemaVersion\":1}");
        var runnerHash = Hash(runnerBytes);
        var definitionHash = Hash(definitionBytes);
        var entries = new[]
        {
            new { path = "bot-definition.json", sha256 = definitionHash },
            new { path = "runner.bin", sha256 = runnerHash }
        };
        var canonical = "runnerExecutablePath\nrunner.bin\nbotDefinitionPath\nbot-definition.json\n" +
            string.Concat(entries.OrderBy(entry => entry.path, StringComparer.Ordinal)
                .Select(entry => $"{entry.path}\n{entry.sha256.ToLowerInvariant()}\n"));
        var packageDigest = Hash(Encoding.UTF8.GetBytes(canonical));
        var packageRoot = Path.Combine(store, botIdentityId, buildId, packageDigest.ToLowerInvariant());
        Directory.CreateDirectory(packageRoot);

        try
        {
            File.WriteAllBytes(Path.Combine(packageRoot, "runner.bin"), runnerBytes);
            File.WriteAllBytes(Path.Combine(packageRoot, "bot-definition.json"), definitionBytes);
            WriteManifest(packageRoot, packageDigest, entries);

            var build = new BotBuildReference(botIdentityId, buildId, packageDigest);
            var resolver = new FileSystemSc2BotRunnerResolver(store);
            var artifact = resolver.ResolveBotArtifact(build);
            artifact.ValidateFor(build);
            if (!File.Exists(artifact.RunnerExecutablePath) || !File.Exists(artifact.BotDefinitionPath))
                throw new InvalidOperationException("Resolved package did not return both payload files.");

            File.WriteAllText(Path.Combine(packageRoot, "bot-definition.json"), "tampered");
            ExpectRejected(() => resolver.ResolveBotArtifact(build),
                "modified BotDefinition payload");

            Console.WriteLine("PASS content-addressed bot package resolver checks");
        }
        finally
        {
            try { Directory.Delete(store, recursive: true); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
    }

    private static void WriteManifest(string packageRoot, string digest, object[] entries)
    {
        var manifest = new
        {
            schemaVersion = 1,
            contentSha256 = digest,
            runnerExecutablePath = "runner.bin",
            botDefinitionPath = "bot-definition.json",
            files = entries
        };
        File.WriteAllText(Path.Combine(packageRoot, "bot-build.json"), JsonSerializer.Serialize(manifest));
    }

    private static string Hash(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes));

    private static void ExpectRejected(Action action, string scenario)
    {
        try
        {
            action();
            throw new InvalidOperationException($"Expected resolver to reject {scenario}.");
        }
        catch (InvalidOperationException exception) when (
            exception.Message.Contains("Package payload 'bot-definition.json' failed SHA-256 verification.", StringComparison.Ordinal))
        {
            // The resolver rejected the tampered immutable payload.
        }
    }
}
