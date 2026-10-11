using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace SimlibsStudio.Bridge;

/// <summary>
/// Python 桥接进程宿主：以子进程运行 backend/wpf_bridge.py，stdin/stdout 走 UTF-8 JSON 行。
/// 请求/响应按 id 关联；事件行原样回调。进程崩溃通过 Crashed 事件上报。
/// </summary>
public sealed class BridgeHost : IDisposable
{
    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        WriteIndented = false,
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };

    private Process? _proc;
    private StreamWriter? _writer;
    private readonly ConcurrentDictionary<int, TaskCompletionSource<JsonObject>> _pending = new();
    private int _nextId;
    private readonly StringBuilder _errTail = new();

    public bool Mock { get; private set; }
    public bool Running => _proc is { HasExited: false };
    public string StderrTail => _errTail.ToString();

    /// <summary>桥事件：ready / job_event / bridge_log（后台线程触发）。</summary>
    public event Action<JsonObject>? Event;
    /// <summary>桥进程退出（含崩溃）。</summary>
    public event Action<string>? Crashed;

    public static string WpfRoot => FindRoot();
    public static string BridgeScript => Path.Combine(WpfRoot, "backend", "wpf_bridge.py");

    private static string FindRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        for (var i = 0; i < 8 && dir is not null; i++)
        {
            if (File.Exists(Path.Combine(dir.FullName, "backend", "wpf_bridge.py")))
                return dir.FullName;
            dir = dir.Parent;
        }
        return AppContext.BaseDirectory;   // 兜底：至少不抛
    }

    public static string ResolvePython()
    {
        foreach (var candidate in new[]
                 {
                     @"E:\Anaconda\envs\simLIBS\python.exe",
                     @"D:\Anaconda3\envs\simLIBS\python.exe",
                 })
        {
            if (File.Exists(candidate)) return candidate;
        }
        return "python";
    }

    public void Start(bool mock)
    {
        Mock = mock;
        var psi = new ProcessStartInfo
        {
            FileName = ResolvePython(),
            Arguments = $"-B \"{BridgeScript}\"{(mock ? " --mock" : "")}",
            WorkingDirectory = WpfRoot,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
        psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
        psi.EnvironmentVariables["PYTHONUTF8"] = "1";

        _proc = Process.Start(psi) ?? throw new InvalidOperationException("无法启动 Python 桥接进程");
        Dbg.Log($"bridge started pid={_proc.Id}");
        _writer = new StreamWriter(_proc.StandardInput.BaseStream, new UTF8Encoding(false)) { AutoFlush = true };
        _ = Task.Run(() => ReadLoopAsync(_proc));
        _ = Task.Run(() => ErrLoopAsync(_proc));
    }

    private async Task ReadLoopAsync(Process proc)
    {
        try
        {
            var reader = proc.StandardOutput;
            while (await reader.ReadLineAsync() is { } line)
            {
                if (string.IsNullOrWhiteSpace(line)) continue;
                JsonObject? obj;
                try
                {
                    obj = JsonNode.Parse(line) as JsonObject;
                }
                catch (JsonException)
                {
                    continue;
                }
                if (obj is null) continue;
                if (obj.ContainsKey("event"))
                {
                    Event?.Invoke(obj);
                    continue;
                }
                var id = obj["id"] is JsonNode idNode && int.TryParse(idNode.ToString(), out var i) ? i : -1;
                if (_pending.TryRemove(id, out var tcs)) tcs.TrySetResult(obj);
            }
        }
        catch (Exception)
        {
            // 流随进程退出而中断，走 Crashed 上报
        }
        if (!disposed)
        {
            Crashed?.Invoke($"桥接进程已退出（代码 {_proc?.ExitCode ?? -1}）{TailInfo()}");
        }
    }

    private async Task ErrLoopAsync(Process proc)
    {
        try
        {
            while (await proc.StandardError.ReadLineAsync() is { } line)
            {
                lock (_errTail)
                {
                    _errTail.AppendLine(line);
                    if (_errTail.Length > 8000) _errTail.Remove(0, _errTail.Length - 8000);
                }
            }
        }
        catch (Exception)
        {
            // 同上
        }
    }

    private string TailInfo()
    {
        lock (_errTail)
        {
            var tail = _errTail.ToString().TrimEnd();
            if (tail.Length == 0) return "";
            var last = tail.Split('\n')[^1].Trim();
            return last.Length > 0 ? $" · {last}" : "";
        }
    }

    /// <summary>发送命令并等待响应；业务错误抛 BridgeException。</summary>
    public async Task<JsonObject> SendAsync(string cmd, JsonObject? data = null,
        int timeoutMs = 180_000, CancellationToken ct = default)
    {
        if (_writer is null || _proc is null)
            throw new InvalidOperationException("桥接进程尚未启动");
        var id = Interlocked.Increment(ref _nextId);
        var tcs = new TaskCompletionSource<JsonObject>(TaskCreationOptions.RunContinuationsAsynchronously);
        _pending[id] = tcs;

        var message = new JsonObject
        {
            ["id"] = id,
            ["cmd"] = cmd,
            ["data"] = data ?? new JsonObject(),
        };
        try
        {
            await _writer.WriteLineAsync(message.ToJsonString(JsonOpts));
        }
        catch (Exception)
        {
            _pending.TryRemove(id, out _);
            throw;
        }

        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(timeoutMs);
        try
        {
            var resp = await tcs.Task.WaitAsync(cts.Token);
            if (resp["ok"]?.GetValue<bool>() != true)
            {
                var err = resp["error"];
                throw new BridgeException(
                    err?["code"]?.ToString() ?? "error",
                    err?["message"]?.ToString() ?? "未知错误");
            }
            return resp["data"] as JsonObject ?? new JsonObject();
        }
        catch (OperationCanceledException)
        {
            _pending.TryRemove(id, out _);
            throw new BridgeException("timeout", $"{cmd} 超时（{timeoutMs / 1000}s）");
        }
        finally
        {
            _pending.TryRemove(id, out _);
        }
    }

    private bool disposed;

    public void Dispose()
    {
        disposed = true;
        try
        {
            _writer?.Dispose();
        }
        catch { /* ignore */ }
        try
        {
            _proc?.Kill(entireProcessTree: true);
        }
        catch { /* ignore */ }
        try
        {
            _proc?.Dispose();
        }
        catch { /* ignore */ }
    }
}
