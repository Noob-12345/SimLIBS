using System.Windows;
using System.IO;
using System.Windows.Controls;
using System.Windows.Media;
using System.Text.Json.Nodes;
using Microsoft.Win32;
using SimlibsStudio.Bridge;
using SimlibsStudio.Controls;
using static SimlibsStudio.Bridge.JsonExt;

namespace SimlibsStudio;

/// <summary>单次模拟页：配比 + 参数 → 三条计算路径 → 光谱图 + 元数据 + 导出。</summary>
public sealed class SinglePage : PageBase
{
    private readonly CompositionEditor _comp = new();
    private readonly ParamsPanel _params = new();

    private readonly Button _runBtn;
    private readonly Button _cancelBtn;
    private readonly ProgressBar _progress = new() { Height = 4, Minimum = 0, Maximum = 100 };
    private readonly TextBlock _statusText = new()
    {
        FontSize = 11.5,
        Foreground = (Brush)Application.Current.Resources["Text.Secondary"],
        TextTrimming = TextTrimming.CharacterEllipsis,
    };
    private readonly SpectrumChart _chart = new();
    private readonly WrapPanel _chips = new() { Margin = new Thickness(0, 8, 0, 0) };
    private readonly CheckBox _showIons = new()
    {
        Style = (Style)Application.Current.Resources["ModCheck"],
        Content = "元素贡献",
        ToolTip = "同元素离子求和，按元素稳定配色叠加显示",
    };
    private readonly TextBlock _resultTitle = new()
    {
        FontSize = 12.5,
        FontWeight = FontWeights.SemiBold,
        TextTrimming = TextTrimming.CharacterEllipsis,
    };

    private string? _jobId;
    private SingleResult? _result;
    private bool _running;

    public SinglePage()
    {
        _runBtn = MakeButton("▶  运行模拟", "BtnPrimary", FontWeights.Bold, RunAsync);
        _cancelBtn = MakeButton("取消", "BtnDanger", FontWeights.Normal, CancelAsync);
        _cancelBtn.Visibility = Visibility.Collapsed;
        Content = BuildLayout();
        _showIons.Click += (_, _) =>
        {
            _chart.ShowIons = _showIons.IsChecked == true;
        };
        AppState.JobEvent += OnJobEvent;
    }

    private UIElement BuildLayout()
    {
        var grid = new Grid();
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(368) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(18) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

        // —— 左：参数卡 ——
        var leftCard = new Border { Style = (Style)Application.Current.Resources["Card"] };
        var leftScroll = new ScrollViewer
        {
            VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
            Padding = new Thickness(2),
        };
        var left = new StackPanel();

        left.Children.Add(new SectionHeader("配比（总和 100%）"));
        left.Children.Add(_comp);

        left.Children.Add(new SectionHeader("预设") { Margin = new Thickness(0, 16, 0, 0) });
        var presetRow = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 8, 0, 0) };
        presetRow.Children.Add(MakeGhostButton("H 窄波段", () => ApplyPreset(true)));
        presetRow.Children.Add(MakeGhostButton("W-Fe-Mo", () => ApplyPreset(false)));
        left.Children.Add(presetRow);

        left.Children.Add(_params);

        var btnRow = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 16, 0, 0) };
        btnRow.Children.Add(_runBtn);
        btnRow.Children.Add(_cancelBtn);
        left.Children.Add(btnRow);

        left.Children.Add(_progress);
        _progress.Margin = new Thickness(0, 12, 0, 4);
        _progress.Visibility = Visibility.Collapsed;
        left.Children.Add(_statusText);

        leftScroll.Content = left;
        leftCard.Child = leftScroll;
        Grid.SetColumn(leftCard, 0);
        grid.Children.Add(leftCard);

        // —— 右：结果卡 ——
        var rightCard = new Border { Style = (Style)Application.Current.Resources["Card"] };
        var right = new DockPanel();

        var toolbar = new Grid { Margin = new Thickness(0, 0, 0, 10) };
        toolbar.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        toolbar.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var toolbarLeft = new StackPanel { Orientation = Orientation.Horizontal };
        toolbarLeft.Children.Add(_resultTitle);
        toolbarLeft.Children.Add(new TextBlock
        {
            Text = " · 框选缩放 / 滚轮缩放 / 右键复位",
            FontSize = 10.5,
            Foreground = (Brush)Application.Current.Resources["Text.Faint"],
            VerticalAlignment = VerticalAlignment.Center,
        });
        Grid.SetColumn(toolbarLeft, 0);
        var toolbarRight = new StackPanel { Orientation = Orientation.Horizontal };
        toolbarRight.Children.Add(_showIons);
        toolbarRight.Children.Add(MakeGhostButton("复位视图", () => _chart.ResetView()));
        toolbarRight.Children.Add(MakeGhostButton("导出 CSV", () => ExportAsync("csv")));
        toolbarRight.Children.Add(MakeGhostButton("导出 PNG", () => ExportAsync("png")));
        Grid.SetColumn(toolbarRight, 1);
        toolbar.Children.Add(toolbarLeft);
        toolbar.Children.Add(toolbarRight);
        DockPanel.SetDock(toolbar, Dock.Top);
        right.Children.Add(toolbar);

        _chart.SetEmptyText("运行单次模拟后显示光谱\n（取消/失败保留上一次成功图谱）");

        var chipsScroll = new ScrollViewer
        {
            VerticalScrollBarVisibility = ScrollBarVisibility.Disabled,
            HorizontalScrollBarVisibility = ScrollBarVisibility.Auto,
            Margin = new Thickness(0, 10, 0, 0),
        };
        chipsScroll.Content = _chips;
        DockPanel.SetDock(chipsScroll, Dock.Bottom);
        right.Children.Add(chipsScroll);

        // 图表必须最后加入 DockPanel（LastChildFill 填充剩余空间）
        right.Children.Add(_chart);

        rightCard.Child = right;
        Grid.SetColumn(rightCard, 2);
        grid.Children.Add(rightCard);
        return grid;
    }

    private static Button MakeButton(string text, string styleKey, FontWeight weight, Func<Task> onClick)
    {
        var b = new Button
        {
            Content = text,
            Style = (Style)Application.Current.Resources[styleKey],
            FontWeight = weight,
            Padding = new Thickness(18, 9, 18, 10),
        };
        b.Click += (_, _) => AppState.RunBg(onClick, text);
        return b;
    }

    private static Button MakeGhostButton(string text, Action onClick)
    {
        var b = new Button
        {
            Content = text,
            Style = (Style)Application.Current.Resources["BtnGhost"],
            FontSize = 11.5,
            Padding = new Thickness(10, 5, 10, 6),
            Margin = new Thickness(8, 0, 0, 0),
        };
        b.Click += (_, _) => onClick();
        return b;
    }

    public override void OnBridgeReady()
    {
        _params.LoadDefaults(AppState.DefaultParams);
    }

    public override void OnThemeChanged() => _chart.InvalidateVisual();

    private void ApplyPreset(bool narrowH)
    {
        if (narrowH)
        {
            _comp.SetRows(new[] { ("H", 100.0) });
            _params.Te.SetActual(1.0, raiseEvent: false);
            _params.Ne.SetActual(1e17, raiseEvent: false);
            _params.R.SetActual(1000, raiseEvent: false);
            _params.LowW.Text = "650";
            _params.UpW.Text = "660";
        }
        else
        {
            _comp.SetRows(new[] { ("W", 50.0), ("Fe", 25.0), ("Mo", 25.0) });
            _params.Te.SetActual(1.0, raiseEvent: false);
            _params.Ne.SetActual(1e17, raiseEvent: false);
            _params.R.SetActual(3000, raiseEvent: false);
            _params.LowW.Text = "200";
            _params.UpW.Text = "1000";
        }
        AppState.Toast.Show("预设已填充（不联网，点击运行后才计算）", "info", "预设");
    }

    // ---------------- 任务生命周期 ----------------

    private async Task RunAsync()
    {
        if (!AppState.BridgeReady)
        {
            AppState.Toast.Show("后端尚未就绪，请稍候", "warn");
            return;
        }
        if (_running) return;

        var composition = _comp.Collect();          // 校验失败抛 FormatException → toast
        var parameters = _params.Collect();
        var title = string.Join(" / ", composition.Select(c => $"{c.el} {c.pct:0.##}%"))
                    + $" · Te={parameters["te"]:0.##}eV";

        var body = new JsonObject
        {
            ["params"] = parameters,
            ["composition"] = new JsonArray(composition.Select(c =>
                (JsonNode)new JsonObject { ["el"] = c.el, ["pct"] = c.pct }).ToArray()),
            ["title"] = title,
        };

        var reply = await AppState.Bridge.SendAsync("start_single", body);
        _jobId = reply.JStr("job_id");
        await AppState.Bridge.SendAsync("subscribe", new JsonObject { ["job_id"] = _jobId });

        SetRunning(true, "任务已提交 · " + title);
    }

    private async Task CancelAsync()
    {
        if (_jobId is null) return;
        await AppState.Bridge.SendAsync("cancel", new JsonObject { ["job_id"] = _jobId });
        _statusText.Text = "已发送协作取消标记…";
    }

    private void SetRunning(bool running, string statusText)
    {
        Dbg.Log($"SinglePage: running={running} {statusText}");
        _running = running;
        _runBtn.IsEnabled = !running;
        _cancelBtn.Visibility = running ? Visibility.Visible : Visibility.Collapsed;
        _progress.Visibility = running ? Visibility.Visible : Visibility.Collapsed;
        _progress.Value = 0;
        _statusText.Text = statusText;
    }

    private void OnJobEvent(JobEventDto ev)
    {
        if (ev.JobId != _jobId) return;
        if (ev.Progress.HasValue)
        {
            _progress.Value = ev.Progress.Value;
        }
        if (ev.Message.Length > 0 && ev.Type is "log" or "status")
        {
            _statusText.Text = $"{ev.Ts}  {ev.Message}";
        }
        if (ev.Final)
        {
            if (ev.Status == "completed")
            {
                SetRunning(false, ev.Message.Length > 0 ? ev.Message : "完成");
                AppState.RunBg(LoadResultAsync, "载入结果");
            }
            else
            {
                SetRunning(false, $"任务{EvStatusText(ev.Status)} · 保留上一次成功图谱");
                AppState.Toast.Show(ev.Message.Length > 0 ? ev.Message : "任务未完成", "error", "单次模拟");
            }
        }
    }

    internal static string EvStatusText(string? status) => status switch
    {
        "failed" => "失败",
        "cancelled" => "已取消",
        _ => status ?? "结束",
    };

    private async Task LoadResultAsync()
    {
        if (_jobId is null) return;
        Dbg.Log("SinglePage: loading result for " + _jobId);
        var reply = await AppState.Bridge.SendAsync("get_result",
            new JsonObject { ["job_id"] = _jobId }, timeoutMs: 240_000);
        var result = SingleResult.Parse(reply);
        _result = result;
        ApplyResult(result);
    }

    private void ApplyResult(SingleResult result)
    {
        Dbg.Log($"SinglePage: apply result xs={result.Xs.Length}");
        var meta = result.Meta;
        var stick = meta.JStr("spectrum_style") == "stick";
        _chart.SetSpectrum(result.Xs, result.Ys, stick);
        _chart.SetAnnotations(
            subtitle: meta.JStr("intensity_scale") == "energy" ? "Energy flux (a.u.)" : "Photon (相对光子)",
            frameText: $"可见 {_chart.VisibleX.x0:0.##}–{_chart.VisibleX.x1:0.##} nm",
            previewBadge: false);

        // 元素贡献：同元素离子求和（网格一致时）
        _chart.SetIons(AggregateIons(result.Ions));
        _chart.ShowIons = _showIons.IsChecked == true;

        _resultTitle.Text = meta.JStr("source", "真实 NIST / SimulatedLIBS 模拟");
        BuildChips(meta, result);
        _statusText.Text = $"完成 · {_statusText.Text}";
    }

    private static List<SeriesData> AggregateIons(List<SeriesData> ions)
    {
        var groups = new Dictionary<string, List<SeriesData>>();
        foreach (var ion in ions)
        {
            var key = ion.Label.Split(' ', StringSplitOptions.RemoveEmptyEntries) is { Length: > 0 } p
                ? p[0] : ion.Label;
            if (!groups.TryGetValue(key, out var list))
            {
                groups[key] = list = new List<SeriesData>();
            }
            list.Add(ion);
        }
        var result = new List<SeriesData>();
        foreach (var (element, list) in groups)
        {
            var primary = list[0];
            if (list.Count == 1)
            {
                result.Add(new SeriesData { Label = element, Xs = primary.Xs, Ys = primary.Ys });
                continue;
            }
            var sameGrid = list.All(s => s.Xs.Length == primary.Xs.Length);
            if (sameGrid)
            {
                var ys = new double[primary.Ys.Length];
                foreach (var s in list)
                {
                    for (var i = 0; i < ys.Length; i++) ys[i] += s.Ys[i];
                }
                result.Add(new SeriesData { Label = element, Xs = primary.Xs, Ys = ys });
            }
            else
            {
                foreach (var s in list) result.Add(new SeriesData { Label = element, Xs = s.Xs, Ys = s.Ys });
            }
        }
        return result;
    }

    private void BuildChips(JsonObject meta, SingleResult result)
    {
        _chips.Children.Clear();
        void Add(string text, string? colorKey = null)
        {
            var chip = new Chip(text,
                colorKey is null ? null : (Brush)Application.Current.Resources[colorKey]);
            _chips.Children.Add(chip);
        }

        Add($"来源 · {meta.JStr("source", "—")}");
        Add($"点数 · {meta.JStr("points", "—")}");
        if (meta.Str("sha256") is { Length: > 0 } sha) Add($"SHA · {sha}");
        if (meta["ne_actual"] is not null) Add($"实际 Ne · {meta["ne_actual"]}");
        Add($"计算位置 · {meta.JStr("computation_location", "—")}");
        Add($"展宽 · {meta.JStr("broadening", "—")}");
        if (meta.Str("actual_resolution") is { Length: > 0 } ar) Add($"实际 R · {ar}");
        if (meta.Str("requested_resolution") is { Length: > 0 } rr) Add($"请求 R · {rr}");
        if (meta.Str("intensity_scale") is { Length: > 0 } scale) Add($"强度 · {scale}");
        if (meta.Str("duration") is { Length: > 0 } dur) Add($"耗时 · {dur}");
        if (meta.Str("resolution_warning") is { Length: > 0 } warn)
            Add("⚠ " + warn, "State.Warn");
        if (meta.Bool("local_broadening_enabled") == false && meta.JStr("spectrum_style") == "stick")
            Add("未展宽 · R 未应用", "State.Warn");
        var ions = meta["ions"] as System.Text.Json.Nodes.JsonArray;
        if (ions is { Count: > 0 })
            Add($"离子 · {string.Join(" / ", ions.Select(n => n?.ToString()))}");
    }

    // ---------------- 跨页：载入历史任务 / 读当前配比 ----------------

    public (string el, double pct)[] CurrentComposition() => _comp.Collect();

    internal bool IsBusy => _running;

    internal void StartRunForSelfTest() => AppState.RunBg(RunAsync, "自检");

    public void LoadJobId(string jobId)
    {
        _jobId = jobId;
        SetRunning(false, $"载入任务 {jobId} 的结果…");
        AppState.RunBg(LoadResultAsync, "载入结果");
    }

    private async Task ExportAsync(string kind)
    {
        if (_jobId is null || _result is null)
        {
            AppState.Toast.Show("还没有可导出的结果，先运行一次模拟", "warn");
            return;
        }
        var reply = await AppState.Bridge.SendAsync("export",
            new JsonObject { ["job_id"] = _jobId, ["kind"] = kind }, timeoutMs: 240_000);
        SaveExport(ExportResult.Parse(reply), $"单次模拟 {kind.ToUpper()}");
    }

    internal static void SaveExport(ExportResult export, string what)
    {
        var ext = export.Filename.EndsWith(".png") ? "png"
            : export.Filename.EndsWith(".zip") ? "zip"
            : export.Filename.EndsWith(".gif") ? "gif" : "csv";
        var dialog = new SaveFileDialog
        {
            FileName = export.Filename,
            Filter = ext switch
            {
                "png" => "PNG 图片|*.png",
                "zip" => "ZIP 压缩包|*.zip",
                "gif" => "GIF 动图|*.gif",
                _ => "CSV 数据|*.csv",
            },
        };
        if (dialog.ShowDialog() != true) return;
        if (export.Bytes is not null)
            File.WriteAllBytes(dialog.FileName, export.Bytes);
        else if (export.Text is not null)
            File.WriteAllText(dialog.FileName, export.Text);
        AppState.Toast.Show($"已保存 {dialog.FileName}", "ok", what);
    }
}
