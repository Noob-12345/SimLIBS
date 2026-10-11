using System.IO;
using SimlibsStudio.Bridge;
using System.Windows;
using SimlibsStudio.Controls;

namespace SimlibsStudio;

public partial class App : System.Windows.Application
{
    private MainWindow? _window;

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        // 全局异常兜底：记录 + toast，不让窗口闪退
        DispatcherUnhandledException += (_, args) =>
        {
            Dbg.Log("UNHANDLED: " + args.Exception);
            Log(args.Exception);
            try
            {
                if (_window is not null)
                    _window.Toasts.Show(args.Exception.Message, "error", "内部错误");
                args.Handled = true;
            }
            catch
            {
                // 连 UI 都不可用时只能放弃
            }
        };

        var args2 = new List<string>(e.Args);
        var screenshot = args2.Contains("--screenshot");
        // 截图模式默认 mock（确定性）；--real 时走真实引擎（local 离线模式，不联网）
        var mock = args2.Contains("--mock") || (screenshot && !args2.Contains("--real"));

        _window = new MainWindow();
        MainWindow = _window;
        _window.Show();

        _window.Boot(mock);
        if (screenshot)
        {
            _window.StartScreenshotTour();
        }
    }

    private static void Log(Exception exc)
    {
        try
        {
            var dir = Path.Combine(BridgeHost.WpfRoot, "logs");
            Directory.CreateDirectory(dir);
            File.AppendAllText(Path.Combine(dir, "app.log"),
                $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {exc}\n\n");
        }
        catch
        {
            // 日志失败时忽略
        }
    }
}
