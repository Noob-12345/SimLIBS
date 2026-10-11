using System.Diagnostics;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Text.Json.Nodes;
using Microsoft.Win32;
using SimlibsStudio.Bridge;
using SimlibsStudio.Controls;
using static SimlibsStudio.Bridge.JsonExt;

namespace SimlibsStudio;

/// <summary>设置页：引擎路径 / 超时 / 代理 / TLS / 输出目录 + 引擎状态。</summary>
public sealed class SettingsPage : PageBase
{
    private readonly Dictionary<string, TextBox> _fields = new();
    private readonly CheckBox _tlsCheck = new()
    {
        Style = (Style)Application.Current.Resources["ModCheck"],
        Content = "TLS 校验（对 NIST 请求验证证书；默认开启）",
    };
    private readonly WrapPanel _engineChips = new() { Margin = new Thickness(0, 10, 0, 0) };

    public SettingsPage()
    {
        Content = BuildLayout();
        if (AppState.BridgeReady) _ = LoadAsync();
    }

    private UIElement BuildLayout()
    {
        var scroll = new ScrollViewer { VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Padding = new Thickness(2) };
        var root = new StackPanel { MaxWidth = 860, HorizontalAlignment = HorizontalAlignment.Left };

        root.Children.Add(new SectionHeader("引擎状态"));
        var statusCard = new Border
        {
            Style = (Style)Application.Current.Resources["Card"],
            Child = WrapStack(
                MakeGhost("刷新状态", () => AppState.RunBg(RefreshStatusAsync, "刷新状态")),
                _engineChips),
            Margin = new Thickness(0, 10, 0, 0),
        };
        root.Children.Add(statusCard);

        root.Children.Add(new SectionHeader("路径") { Margin = new Thickness(0, 18, 0, 0) });
        var pathCard = new Border
        {
            Style = (Style)Application.Current.Resources["Card"],
            Margin = new Thickness(0, 10, 0, 0),
        };
        var pathStack = new StackPanel();
        pathStack.Children.Add(PathRow("python", "Python 解释器", "worker 子进程使用的解释器", isFolder: false));
        pathStack.Children.Add(PathRow("source", "源库目录", "包含 simLIBS/simulation.py 的目录", isFolder: true));
        pathStack.Children.Add(PathRow("chrome", "Chrome 路径", "server 模式浏览器；留空自动探测", isFolder: false));
        pathStack.Children.Add(PathRow("driver", "ChromeDriver 路径", "留空 = 启动任务时自动获取匹配版本", isFolder: false));
        pathStack.Children.Add(PathRow("output_dir", "输出目录", "任务结果/导出物根目录", isFolder: true));
        pathCard.Child = pathStack;
        root.Children.Add(pathCard);

        root.Children.Add(new SectionHeader("超时与网络") { Margin = new Thickness(0, 18, 0, 0) });
        var netCard = new Border
        {
            Style = (Style)Application.Current.Resources["Card"],
            Margin = new Thickness(0, 10, 0, 0),
        };
        var netStack = new StackPanel();
        var timeouts = new Grid();
        for (var i = 0; i < 3; i++) timeouts.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        for (var i = 0; i < 3; i++) timeouts.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(12) });
        AddField(timeouts, 0, "connect_timeout", "连接超时 s");
        AddField(timeouts, 2, "read_timeout", "读取超时 s");
        AddField(timeouts, 4, "page_load", "页面加载超时 s");
        netStack.Children.Add(timeouts);

        var deadlines = new Grid { Margin = new Thickness(0, 10, 0, 0) };
        for (var i = 0; i < 3; i++) deadlines.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        for (var i = 0; i < 3; i++) deadlines.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(12) });
        AddField(deadlines, 0, "static_deadline", "静态任务期限 s");
        AddField(deadlines, 2, "dynamic_deadline", "动态任务期限 s");
        netStack.Children.Add(deadlines);

        _tlsCheck.Margin = new Thickness(0, 12, 0, 0);
        netStack.Children.Add(_tlsCheck);
        netStack.Children.Add(PathRow("proxy", "HTTPS 代理", "针对 NIST 间歇性 TLS 干扰的可选缓解，如 http://127.0.0.1:7890；留空关闭", isFolder: false, isProxy: true));
        netCard.Child = netStack;
        root.Children.Add(netCard);

        var saveRow = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 18, 0, 0) };
        var save = new Button
        {
            Content = "保存设置",
            Style = (Style)Application.Current.Resources["BtnPrimary"],
            FontWeight = FontWeights.Bold,
            Padding = new Thickness(20, 9, 20, 10),
        };
        save.Click += (_, _) => AppState.RunBg(SaveAsync, "保存设置");
        var openOut = MakeGhost("打开输出目录", OpenOutputDir);
        openOut.Margin = new Thickness(12, 0, 0, 0);
        openOut.VerticalAlignment = VerticalAlignment.Center;
        saveRow.Children.Add(save);
        saveRow.Children.Add(openOut);
        root.Children.Add(saveRow);

        root.Children.Add(new TextBlock
        {
            Text = "设置持久化到 WPF/.wpf-settings.json（与 Qt 版 .cli-settings.json 互不影响）；代理保存到 .wpf-proxy.json，经环境变量传给 worker 子进程。",
            FontSize = 10.5,
            Foreground = (Brush)Application.Current.Resources["Text.Faint"],
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(0, 14, 0, 20),
        });

        scroll.Content = root;
        return scroll;
    }

    private static StackPanel WrapStack(params UIElement[] items)
    {
        var sp = new StackPanel();
        foreach (var it in items) sp.Children.Add(it);
        return sp;
    }

    private static Button MakeGhost(string text, Action onClick)
    {
        var b = new Button
        {
            Content = text,
            Style = (Style)Application.Current.Resources["BtnGhost"],
            FontSize = 11.5,
            Padding = new Thickness(10, 5, 10, 6),
            Margin = new Thickness(0, 0, 8, 0),
        };
        b.Click += (_, _) => onClick();
        return b;
    }

    private UIElement PathRow(string key, string label, string tooltip, bool isFolder, bool isProxy = false)
    {
        var box = new TextBox
        {
            Style = (Style)Application.Current.Resources["FieldBox"],
            FontFamily = new FontFamily("Consolas"),
            FontSize = 12,
            Padding = new Thickness(8, 5, 8, 6),
        };
        _fields[key] = box;

        var grid = new Grid { Margin = new Thickness(0, 0, 0, 10) };
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var stack = new StackPanel();
        stack.Children.Add(new TextBlock
        {
            Text = label,
            FontSize = 10.5,
            Foreground = (Brush)Application.Current.Resources["Text.Faint"],
            Margin = new Thickness(2, 0, 0, 4),
            ToolTip = tooltip,
        });
        stack.Children.Add(box);
        Grid.SetColumn(stack, 0);
        grid.Children.Add(stack);
        if (!isProxy)
        {
            var browse = new Button
            {
                Content = isFolder ? "目录…" : "浏览…",
                Style = (Style)Application.Current.Resources["BtnGhost"],
                FontSize = 11,
                Padding = new Thickness(10, 5, 10, 6),
                Margin = new Thickness(8, 14, 0, 0),
            };
            browse.Click += (_, _) => Browse(box, isFolder);
            Grid.SetColumn(browse, 1);
            grid.Children.Add(browse);
        }
        return grid;
    }

    private void AddField(Grid grid, int col, string key, string label)
    {
        var box = new TextBox
        {
            Style = (Style)Application.Current.Resources["FieldBox"],
            FontFamily = new FontFamily("Consolas"),
            FontSize = 12.5,
            Padding = new Thickness(8, 5, 8, 6),
        };
        _fields[key] = box;
        var stack = new StackPanel();
        stack.Children.Add(new TextBlock
        {
            Text = label,
            FontSize = 10.5,
            Foreground = (Brush)Application.Current.Resources["Text.Faint"],
            Margin = new Thickness(2, 0, 0, 4),
        });
        stack.Children.Add(box);
        Grid.SetColumn(stack, col);
        grid.Children.Add(stack);
    }

    private static void Browse(TextBox box, bool isFolder)
    {
        if (isFolder)
        {
            var dlg = new OpenFileDialog
            {
                CheckFileExists = false,
                CheckPathExists = true,
                ValidateNames = false,
                FileName = "选择此目录",
                Title = "选择目录",
            };
            if (dlg.ShowDialog() == true)
            {
                var dir = System.IO.Path.GetDirectoryName(dlg.FileName);
                if (dir is not null) box.Text = dir;
            }
        }
        else
        {
            var dlg = new OpenFileDialog { Title = "选择文件" };
            if (dlg.ShowDialog() == true) box.Text = dlg.FileName;
        }
    }

    public override async void OnBridgeReady()
    {
        await LoadAsync();
        await RefreshStatusAsync();
    }

    private async Task LoadAsync()
    {
        var s = await AppState.GetSettingsAsync(refresh: true);
        foreach (var (key, box) in _fields)
        {
            box.Text = s.Str(key) ?? "";
        }
        _tlsCheck.IsChecked = s.Bool("tls_verify", true);
    }

    private async Task SaveAsync()
    {
        var payload = new JsonObject();
        foreach (var (key, box) in _fields)
        {
            payload[key] = box.Text.Trim();
        }
        payload["tls_verify"] = _tlsCheck.IsChecked == true;
        var saved = await AppState.SaveSettingsAsync(payload);
        foreach (var (key, box) in _fields)
        {
            box.Text = saved.Str(key) ?? box.Text;
        }
        AppState.Toast.Show("设置已保存", "ok", "设置");
    }

    private async Task RefreshStatusAsync()
    {
        JsonObject status;
        try
        {
            status = await AppState.Bridge.SendAsync("engine_status",
                new JsonObject { ["mode"] = "server" }, timeoutMs: 20_000);
        }
        catch (BridgeException)
        {
            status = await AppState.Bridge.SendAsync("engine_status");
        }
        _engineChips.Children.Clear();
        void Add(string text, string? color = null)
        {
            _engineChips.Children.Add(new Chip(text,
                color is null ? null : (Brush)Application.Current.Resources[color]));
        }
        Add("引擎 · " + status.JStr("engine_label", "—"));
        var nistOk = status.Bool("nist_ok");
        Add("NIST · " + status.JStr("nist", "—"), nistOk ? "State.Ok" : "State.Warn");
        Add("Chrome · " + status.JStr("chrome", "—"));
        if (status.Str("driver") is { Length: > 0 } driver) Add("Driver · " + driver);
        Add("Python · " + status.JStr("python", "—"));
        Add($"运行中任务 · {status.Int("jobs_running")}");
        if (status.Obj("local") is { } local)
        {
            Add($"线库 · {local.Int("csv_count")} CSV / {local.ObjectList("stages").Count} 元素",
                local.Bool("ready") ? "State.Ok" : "State.Error");
        }
        // 状态栏同步
        AppState.Window.UpdateEngineChip(status.JStr("engine_label", "—"),
            nistOk ? "NIST 可达" : status.JStr("nist", "NIST 未知"));
    }

    private void OpenOutputDir()
    {
        try
        {
            var dir = _fields.TryGetValue("output_dir", out var box) && box.Text.Trim().Length > 0
                ? box.Text.Trim() : ".";
            Process.Start(new ProcessStartInfo
            {
                FileName = "explorer.exe",
                Arguments = $"\"{dir}\"",
                UseShellExecute = true,
            });
        }
        catch (Exception exc)
        {
            AppState.Toast.Show(exc.Message, "error", "打开目录");
        }
    }
}
