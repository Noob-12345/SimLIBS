using System.IO;
using Microsoft.Win32;
using System.Windows;
using System.Windows.Media;
using System.Windows.Controls;
using System.Text.Json.Nodes;
using SimlibsStudio.Bridge;
using SimlibsStudio.Controls;

namespace SimlibsStudio;

/// <summary>全局应用状态：桥接宿主、元素表、默认参数、任务事件分发。</summary>
public static class AppState
{
    public static MainWindow Window { get; set; } = null!;
    public static BridgeHost Bridge { get; private set; } = null!;
    public static ToastService Toast { get; private set; } = null!;
    public static ThemeManager Theme { get; } = new();

    public static bool Mock { get; private set; }
    public static bool BridgeReady { get; private set; }
    public static string Interpreter { get; private set; } = "";
    public static List<string> Elements { get; private set; } = new();
    public static JsonObject DefaultParams { get; private set; } = new();

    /// <summary>任务事件（已解析，UI 线程触发）。</summary>
    public static event Action<JobEventDto>? JobEvent;
    /// <summary>桥就绪（UI 线程触发一次）。</summary>
    public static event Action? BridgeReadyChanged;
    /// <summary>桥崩溃（UI 线程）。</summary>
    public static event Action<string>? BridgeCrashed;

    private static JsonObject? _settingsCache;

    public static void Initialize(MainWindow window, ToastService toast)
    {
        Window = window;
        Toast = toast;
    }

    public static void StartBridge(bool mock)
    {
        Mock = mock;
        Bridge = new BridgeHost();
        Bridge.Event += OnBridgeEvent;
        Bridge.Crashed += reason => Window.Dispatcher.BeginInvoke(() =>
        {
            BridgeReady = false;
            BridgeReadyChanged?.Invoke();
            BridgeCrashed?.Invoke(reason);
            Toast.Show(reason, "error", "后端连接");
        });
        Bridge.Start(mock);
    }

    private static void OnBridgeEvent(JsonObject obj)
    {
        var kind = obj["event"]?.ToString() ?? "";
        if (kind == "bridge_log" && obj.JStr("level") == "error")
            Dbg.Log("bridge-error: " + obj.JStr("message"));
        Window.Dispatcher.BeginInvoke(() =>
        {
            switch (kind)
            {
                case "ready":
                    Interpreter = obj.Obj("data")?.JStr("interpreter") ?? "";
                    BridgeReady = true;
                    BridgeReadyChanged?.Invoke();
                    break;
                case "job_event":
                    var parsed = JobEventDto.Parse(obj.Obj("data") ?? new JsonObject());
                    if (parsed.Type == "status")   // 仅记录状态事件，避免进度刷屏
                        Dbg.Log($"evt: job_event {parsed.JobId} status={parsed.Status} final={parsed.Final}");
                    if (obj.Obj("data") is { } data)
                        JobEvent?.Invoke(parsed);
                    break;
                case "bridge_log":
                    var level = obj.JStr("level");
                    if (level == "error")
                        Toast.Show(obj.JStr("message"), "error", "后端日志");
                    break;
            }
        });
    }

    private static bool _logAllEvents;

    public static async Task BootAsync()
    {
        // default_params 提供元素表与 v2 local 默认参数
        DefaultParams = await Bridge.SendAsync("default_params");
        var symbols = DefaultParams["element_symbols"] as System.Text.Json.Nodes.JsonArray;
        Elements = symbols?.Select(n => n?.ToString() ?? "").Where(s => s.Length > 0).ToList()
                   ?? new List<string> { "Fe" };
        BridgeReadyChanged?.Invoke();
    }

    public static async Task<JsonObject> GetSettingsAsync(bool refresh = false)
    {
        if (_settingsCache is null || refresh)
            _settingsCache = await Bridge.SendAsync("get_settings");
        return _settingsCache;
    }

    public static async Task<JsonObject> SaveSettingsAsync(JsonObject settings)
    {
        _settingsCache = await Bridge.SendAsync("save_settings", settings);
        return _settingsCache;
    }

    public static void RaiseJobEvent(JobEventDto ev) => JobEvent?.Invoke(ev);

    /// <summary>后台任务统一错误处理：失败 toast，不崩应用。</summary>
    public static async void RunBg(Func<Task> work, string? context = null)
    {
        try
        {
            await work();
        }
        catch (BridgeException exc)
        {
            Dbg.Log("RunBg BridgeException [" + context + "]: " + exc.Message);
            Toast.Show(exc.Message, "error", context ?? "请求失败");
        }
        catch (Exception exc)
        {
            Dbg.Log("RunBg Exception [" + context + "]: " + exc);
            Toast.Show(exc.Message, "error", context ?? "内部错误");
        }
    }

    public static string LogPath
    {
        get
        {
            var dir = Path.Combine(BridgeHost.WpfRoot, "logs");
            Directory.CreateDirectory(dir);
            return Path.Combine(dir, "app.log");
        }
    }
}

/// <summary>外观模式：浅色 / 深色 / 跟随系统。</summary>
public enum ThemeMode
{
    Light,
    Dark,
    System,
}

/// <summary>预设强调色主题（预览卡片与 Themes/Accents/*.xaml 字典一一对应）。</summary>
public sealed record AccentTheme(string Id, string File, string Name, Color A, Color B, Color C);

public static class AccentCatalog
{
    public static readonly AccentTheme[] All =
    {
        new("plasma", "Plasma", "等离子", Color.FromRgb(0xef, 0x44, 0x44), Color.FromRgb(0xf9, 0x73, 0x16), Color.FromRgb(0x22, 0xd3, 0xee)),
        new("cyan", "Cyan", "深海青", Color.FromRgb(0x08, 0x91, 0xb2), Color.FromRgb(0x06, 0xb6, 0xd4), Color.FromRgb(0x0e, 0xa5, 0xe9)),
        new("blue", "Blue", "星舰蓝", Color.FromRgb(0x25, 0x63, 0xeb), Color.FromRgb(0x3b, 0x82, 0xf6), Color.FromRgb(0x38, 0xbd, 0xf8)),
        new("violet", "Violet", "星云紫", Color.FromRgb(0x7c, 0x3a, 0xed), Color.FromRgb(0xa8, 0x55, 0xf7), Color.FromRgb(0xc0, 0x84, 0xfc)),
        new("green", "Green", "翡翠", Color.FromRgb(0x05, 0x96, 0x69), Color.FromRgb(0x10, 0xb9, 0x81), Color.FromRgb(0x34, 0xd3, 0x99)),
        new("amber", "Amber", "熔金琥珀", Color.FromRgb(0xd9, 0x77, 0x06), Color.FromRgb(0xf5, 0x9e, 0x0b), Color.FromRgb(0xfb, 0xbf, 0x24)),
    };

    public static AccentTheme Get(string id) =>
        All.FirstOrDefault(a => a.Id == id) ?? All[0];
}

/// <summary>
/// 外观管理：模式（浅色 / 深色 / 跟随系统）× 强调色（6 套预设）。
/// 持久化到 WPF/.wpf-ui.json；跟随系统读取 Windows 个性化设置并监听变更。
/// </summary>
public sealed class ThemeManager
{
    private const string FileName = ".wpf-ui.json";
    private const string PersonalizeKey = @"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize";
    private static string FilePath => Path.Combine(BridgeHost.WpfRoot, FileName);

    public ThemeMode Mode { get; private set; } = ThemeMode.Dark;
    public string AccentId { get; private set; } = "plasma";
    public AccentTheme Accent => AccentCatalog.Get(AccentId);

    /// <summary>当前生效是否深色（System 模式按 Windows 个性化设置解析）。</summary>
    public bool Dark => Mode switch
    {
        ThemeMode.Light => false,
        ThemeMode.Dark => true,
        _ => !SystemPrefersLight(),
    };

    public event Action? Changed;

    public void Load()
    {
        try
        {
            if (JsonNode.Parse(File.ReadAllText(FilePath)) is JsonObject json)
            {
                Mode = json["mode"]?.ToString() switch
                {
                    "light" => ThemeMode.Light,
                    "system" => ThemeMode.System,
                    "dark" => ThemeMode.Dark,
                    _ => json["dark"] is JsonNode legacy              // 旧格式 {"dark":bool}
                        ? (legacy.ToString() is "false" or "False" or "0"
                            ? ThemeMode.Light : ThemeMode.Dark)
                        : ThemeMode.Dark,
                };
                if (json["accent"]?.ToString() is { Length: > 0 } accent)
                    AccentId = accent;
            }
        }
        catch { /* 缺文件/坏 JSON 用默认 */ }

        try
        {
            SystemEvents.UserPreferenceChanged += (_, e) =>
            {
                if (e.Category != UserPreferenceCategory.General) return;
                Application.Current?.Dispatcher.BeginInvoke(() =>
                {
                    if (Mode == ThemeMode.System) Apply();
                });
            };
        }
        catch { /* SystemEvents 不可用时仅失去实时跟随 */ }

        Apply();
    }

    public void SetMode(ThemeMode mode)
    {
        if (Mode == mode) return;
        Mode = mode;
        Save();
        Apply();
    }

    /// <summary>在浅/深之间快速切换（从跟随系统出发时解析为明确的另一侧）。</summary>
    public void Toggle() => SetMode(Dark ? ThemeMode.Light : ThemeMode.Dark);

    public void SetAccent(string id)
    {
        if (AccentId == id) return;
        AccentId = AccentCatalog.Get(id).Id;
        Save();
        Apply();
    }

    public static bool SystemPrefersLight()
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(PersonalizeKey);
            return key?.GetValue("AppsUseLightTheme") is int v && v == 1;
        }
        catch
        {
            return false;
        }
    }

    private void Save()
    {
        try
        {
            File.WriteAllText(FilePath, new JsonObject
            {
                ["mode"] = Mode.ToString().ToLowerInvariant(),
                ["accent"] = AccentId,
            }.ToJsonString());
        }
        catch { /* 持久化失败不致命 */ }
    }

    public void Apply()
    {
        var app = Application.Current;
        if (app is null) return;
        var dicts = app.Resources.MergedDictionaries;

        for (var i = dicts.Count - 1; i >= 0; i--)
        {
            var src = dicts[i].Source?.OriginalString ?? "";
            if (src.EndsWith("Dark.xaml") || src.EndsWith("Light.xaml") || src.Contains("Accents/"))
                dicts.RemoveAt(i);
        }
        dicts.Add(new ResourceDictionary
        {
            Source = new Uri(Dark ? "Themes/Dark.xaml" : "Themes/Light.xaml", UriKind.Relative),
        });
        dicts.Add(new ResourceDictionary
        {
            Source = new Uri($"Themes/Accents/{Accent.File}.xaml", UriKind.Relative),
        });

        Changed?.Invoke();
        RetargetAll();
    }

    /// <summary>换肤后把构造期旧画刷引用转为 DynamicResource（窗口 + 所有页面）。
    /// MainWindow 在 Changed 回调里对每个页面调用 <see cref="RetargetTree"/>。</summary>
    public static void RetargetAll()
    {
        var map = BuildPaletteMap();
        if (map.Count == 0) return;
        foreach (Window window in Application.Current.Windows)
            Walk(window, map);
    }

    public static void RetargetTree(DependencyObject root)
    {
        var map = BuildPaletteMap();
        if (map.Count == 0) return;
        Walk(root, map);
    }

    private static Dictionary<Brush, string> BuildPaletteMap()
    {
        var map = new Dictionary<Brush, string>();
        var app = Application.Current;
        if (app is null) return map;
        foreach (ResourceDictionary dict in app.Resources.MergedDictionaries)
        {
            var src = dict.Source?.OriginalString ?? "";
            if (src.EndsWith("Dark.xaml") || src.EndsWith("Light.xaml") || src.Contains("Accents/"))
                CollectBrushes(dict, map);
        }
        return map;
    }

    private static void CollectBrushes(ResourceDictionary dict, Dictionary<Brush, string> map)
    {
        foreach (var key in dict.Keys)
        {
            if (dict[key] is Brush brush && !map.ContainsKey(brush))
            {
                map[brush] = key.ToString() ?? "";
            }
        }
    }

    private static void Walk(DependencyObject node, Dictionary<Brush, string> map)
    {
        if (node is FrameworkElement fe)
        {
            TryRetarget(fe, TextBlock.ForegroundProperty, map);
            TryRetarget(fe, Control.ForegroundProperty, map);
            TryRetarget(fe, Control.BackgroundProperty, map);
            TryRetarget(fe, Control.BorderBrushProperty, map);
            TryRetarget(fe, System.Windows.Shapes.Shape.FillProperty, map);
            TryRetarget(fe, System.Windows.Shapes.Shape.StrokeProperty, map);
        }
        var count = VisualTreeHelper.GetChildrenCount(node);
        for (var i = 0; i < count; i++)
        {
            Walk(VisualTreeHelper.GetChild(node, i), map);
        }
    }

    private static void TryRetarget(FrameworkElement d, DependencyProperty dp, Dictionary<Brush, string> map)
    {
        if (d.GetValue(dp) is Brush brush && map.TryGetValue(brush, out var key) && key.Length > 0)
        {
            d.SetResourceReference(dp, key);
        }
    }
}
