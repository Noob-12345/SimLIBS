using System.IO;

namespace SimlibsStudio;

/// <summary>极简文件日志（诊断启动链路用；logs/debug.log）。</summary>
public static class Dbg
{
    private static readonly object Gate = new();
    public static void Log(string message)
    {
        try
        {
            var dir = Path.Combine(Bridge.BridgeHost.WpfRoot, "logs");
            Directory.CreateDirectory(dir);
            lock (Gate)
            {
                File.AppendAllText(Path.Combine(dir, "debug.log"),
                    $"[{DateTime.Now:HH:mm:ss.fff}] {message}\n");
            }
        }
        catch
        {
            // 日志失败不影响运行
        }
    }
}
