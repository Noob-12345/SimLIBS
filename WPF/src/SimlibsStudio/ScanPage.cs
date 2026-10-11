using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using System.Text.Json.Nodes;
using SimlibsStudio.Bridge;
using SimlibsStudio.Controls;
using static SimlibsStudio.Bridge.JsonExt;

namespace SimlibsStudio;

/// <summary>扫描动画页：Te/Ne/R 轴扫描 → 帧序列自动播放，导出 PNG/GIF。</summary>
public sealed class ScanPage : PageBase
{
    private readonly CompositionEditor _comp = new();
    private readonly ParamsPanel _params = new();

    private readonly Segmented _axisSeg = new();
    private TextBox _startBox;
    private TextBox _endBox;
    private TextBox _framesBox;
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
    private readonly Button _playBtn = new()
    {
        Content = "▶",
        Style = (Style)Application.Current.Resources["BtnGhost"],
        Width = 44,
        Padding = new Thickness(0, 6, 0, 7),
    };
    private readonly Slider _frameSlider = new()
    {
        Style = (Style)Application.Current.Resources["ModSlider"],
        Minimum = 0,
        Maximum = 0,
        IsEnabled = false,
    };
    private readonly TextBlock _valueText = new()
    {
        FontSize = 12,
        FontFamily = new FontFamily("Consolas"),
        VerticalAlignment = VerticalAlignment.Center,
        Foreground = (Brush)Application.Current.Resources["Text.Primary"],
    };
    private readonly TextBlock _resultTitle = new()
    {
        FontSize = 12.5,
        FontWeight = FontWeights.SemiBold,
        TextTrimming = TextTrimming.CharacterEllipsis,
    };

    private string? _jobId;
    private ScanResult? _scan;
    private int _currentFrame = -1;
    private bool _running;
    private bool _frameLoading;
    private readonly Dictionary<int, SingleResult> _frameCache = new();
    private readonly Queue<int> _cacheOrder = new();
    private readonly DispatcherTimer _timer;

    public ScanPage()
    {
        _timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(450) };
        _timer.Tick += (_, _) => AdvanceFrame();
        _frameSlider.ValueChanged += (_, _) =>
        {
            var idx = (int)Math.Round(_frameSlider.Value);
            if (!_frameLoading && _scan is not null && idx != _currentFrame)
                SetFrame(idx);
        };
        _runBtn = MakeButton("▶  运行扫描", "BtnPrimary", FontWeights.Bold, RunAsync);
        _cancelBtn = MakeButton("取消", "BtnDanger", FontWeights.Normal, CancelAsync);
        _cancelBtn.Visibility = Visibility.Collapsed;
        Content = BuildLayout();
        AppState.JobEvent += OnJobEvent;
    }

    private UIElement BuildLayout()
    {
        var grid = new Grid();
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(368) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(18) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

        // —— 左：参数 ——
        var leftCard = new Border { Style = (Style)Application.Current.Resources["Card"] };
        var leftScroll = new ScrollViewer { VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Padding = new Thickness(2) };
        var left = new StackPanel();

        left.Children.Add(new SectionHeader("元素配比"));
        left.Children.Add(_comp);

        left.Children.Add(new SectionHeader("扫描设置") { Margin = new Thickness(0, 16, 0, 0) });
        _axisSeg.SetItems(new[] { "Te 轴", "Ne 轴（10^x）", "R 轴" }, 0);
        _axisSeg.SelectionChanged += _ => UpdateAxisHints();
        left.Children.Add(_axisSeg);

        var rangeGrid = new Grid { Margin = new Thickness(0, 10, 0, 0) };
        for (var i = 0; i < 5; i++)
            rangeGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = i == 1 || i == 3 ? new GridLength(26) : new GridLength(1, GridUnitType.Star) });
        _startBox = MakeBox("0.8");
        _endBox = MakeBox("1.2");
        _framesBox = MakeBox("12");
        _framesBox.ToolTip = "帧数 2–200";
        Grid.SetColumn(_startBox, 0);
        Grid.SetColumn(_endBox, 2);
        Grid.SetColumn(_framesBox, 4);
        var arrow = new TextBlock { Text = "→", Foreground = (Brush)Application.Current.Resources["Text.Faint"], HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 0, 8) };
        var framesLabel = new TextBlock { Text = "帧", Foreground = (Brush)Application.Current.Resources["Text.Faint"], HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 0, 8) };
        Grid.SetColumn(arrow, 1);
        Grid.SetColumn(framesLabel, 3);
        rangeGrid.Children.Add(_startBox);
        rangeGrid.Children.Add(arrow);
        rangeGrid.Children.Add(_endBox);
        rangeGrid.Children.Add(framesLabel);
        rangeGrid.Children.Add(_framesBox);
        left.Children.Add(rangeGrid);

        _axisHint = new TextBlock
        {
            Text = "Te 起点 < 终点（eV）",
            FontSize = 10.5,
            Foreground = (Brush)Application.Current.Resources["Text.Faint"],
            Margin = new Thickness(0, 5, 0, 0),
        };
        left.Children.Add(_axisHint);

        left.Children.Add(_params);

        var btnRow = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 16, 0, 0) };
        btnRow.Children.Add(_runBtn);
        btnRow.Children.Add(_cancelBtn);
        left.Children.Add(btnRow);

        _progress.Margin = new Thickness(0, 12, 0, 4);
        _progress.Visibility = Visibility.Collapsed;
        left.Children.Add(_progress);
        left.Children.Add(_statusText);

        leftScroll.Content = left;
        leftCard.Child = leftScroll;
        Grid.SetColumn(leftCard, 0);
        grid.Children.Add(leftCard);

        // —— 右：结果与播放器 ——
        var rightCard = new Border { Style = (Style)Application.Current.Resources["Card"] };
        var right = new DockPanel();

        var toolbar = new Grid { Margin = new Thickness(0, 0, 0, 10) };
        toolbar.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        toolbar.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        Grid.SetColumn(_resultTitle, 0);
        var exportRow = new StackPanel { Orientation = Orientation.Horizontal };
        exportRow.Children.Add(MakeGhostButton("导出当前帧 PNG", () => ExportAsync("png")));
        exportRow.Children.Add(MakeGhostButton("导出整段 GIF", () => ExportAsync("gif")));
        exportRow.Children.Add(MakeGhostButton("复位视图", () => _chart.ResetView()));
        Grid.SetColumn(exportRow, 1);
        toolbar.Children.Add(_resultTitle);
        toolbar.Children.Add(exportRow);
        DockPanel.SetDock(toolbar, Dock.Top);
        right.Children.Add(toolbar);

        _chart.SetEmptyText("运行扫描后逐帧显示光谱动画");

        // 播放条
        var playBar = new Border
        {
            Background = (Brush)Application.Current.Resources["Bg.Card2"],
            BorderBrush = (Brush)Application.Current.Resources["Line.Subtle"],
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(11),
            Padding = new Thickness(12, 8, 12, 9),
            Margin = new Thickness(0, 10, 0, 0),
        };
        var playGrid = new Grid();
        playGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        playGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        playGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        playGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var prev = MakeGhostButton("⏮", () => StepFrame(-1), width: 38);
        var next = MakeGhostButton("⏭", () => StepFrame(1), width: 38);
        prev.Margin = new Thickness(0);
        Grid.SetColumn(prev, 0);
        _playBtn.Margin = new Thickness(6, 0, 0, 0);
        Grid.SetColumn(_playBtn, 1);
        _playBtn.Click += (_, _) => TogglePlay();
        _frameSlider.Margin = new Thickness(14, 0, 14, 0);
        _frameSlider.VerticalAlignment = VerticalAlignment.Center;
        Grid.SetColumn(_frameSlider, 2);
        Grid.SetColumn(_valueText, 3);
        playGrid.Children.Add(prev);
        playGrid.Children.Add(_playBtn);
        playGrid.Children.Add(_frameSlider);
        playGrid.Children.Add(_valueText);
        playBar.Child = playGrid;
        DockPanel.SetDock(playBar, Dock.Bottom);
        right.Children.Add(playBar);

        // 图表必须最后加入 DockPanel（LastChildFill 填充剩余空间）
        right.Children.Add(_chart);

        rightCard.Child = right;
        Grid.SetColumn(rightCard, 2);
        grid.Children.Add(rightCard);
        return grid;
    }

    private TextBlock _axisHint;

    private static TextBox MakeBox(string text)
    {
        return new TextBox
        {
            Style = (Style)Application.Current.Resources["FieldBox"],
            Text = text,
            FontFamily = new FontFamily("Consolas"),
            FontSize = 12.5,
            Padding = new Thickness(8, 5, 8, 6),
            Margin = new Thickness(0, 0, 0, 8),
        };
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

    private static Button MakeGhostButton(string text, Action onClick, int? width = null)
    {
        var b = new Button
        {
            Content = text,
            Style = (Style)Application.Current.Resources["BtnGhost"],
            FontSize = 11.5,
            Padding = new Thickness(10, 5, 10, 6),
            Margin = new Thickness(8, 0, 0, 0),
        };
        if (width.HasValue) { b.Width = width.Value; b.Padding = new Thickness(0, 5, 0, 6); }
        b.Click += (_, _) => onClick();
        return b;
    }

    public override void OnBridgeReady()
    {
        _params.LoadDefaults(AppState.DefaultParams);
    }

    public override void OnThemeChanged() => _chart.InvalidateVisual();

    private void UpdateAxisHints()
    {
        _axisHint.Text = _axisSeg.SelectedIndex switch
        {
            1 => "Ne 以 10^x 指数输入，起点 < 终点",
            2 => "R 取整后仍需递增（各帧取整值不能重复）",
            _ => "Te 起点 < 终点（eV）",
        };
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

        var composition = _comp.Collect();
        var parameters = _params.Collect();
        if (!double.TryParse(_startBox.Text.Trim(), out var start))
            throw new FormatException("扫描起点必须是数字");
        if (!double.TryParse(_endBox.Text.Trim(), out var end))
            throw new FormatException("扫描终点必须是数字");
        if (!int.TryParse(_framesBox.Text.Trim(), out var frames) || frames is < 2 or > 200)
            throw new FormatException("帧数必须是 2–200 的整数");

        var axis = _axisSeg.SelectedIndex switch { 0 => "te", 1 => "ne", _ => "r" };
        if (axis == "r" && (int)start >= (int)end)
            throw new FormatException("R 扫描取整后需要 起点 < 终点");
        if (axis != "r" && !(start < end))
            throw new FormatException("扫描需要 起点 < 终点");

        var body = new JsonObject
        {
            ["params"] = parameters,
            ["composition"] = new JsonArray(composition.Select(c =>
                (JsonNode)new JsonObject { ["el"] = c.el, ["pct"] = c.pct }).ToArray()),
            ["axis"] = axis,
            ["start"] = start,
            ["end"] = end,
            ["frames"] = frames,
        };

        var reply = await AppState.Bridge.SendAsync("start_scan", body);
        _jobId = reply.JStr("job_id");
        await AppState.Bridge.SendAsync("subscribe", new JsonObject { ["job_id"] = _jobId });
        SetRunning(true, "扫描任务已提交");
    }

    private async Task CancelAsync()
    {
        if (_jobId is null) return;
        await AppState.Bridge.SendAsync("cancel", new JsonObject { ["job_id"] = _jobId });
        _statusText.Text = "已发送协作取消标记…";
    }

    private void SetRunning(bool running, string statusText)
    {
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
        if (ev.Progress.HasValue) _progress.Value = ev.Progress.Value;
        if (ev.Message.Length > 0 && ev.Type is "log" or "status")
            _statusText.Text = $"{ev.Ts}  {ev.Message}";
        if (ev.Final)
        {
            if (ev.Status == "completed")
            {
                SetRunning(false, "扫描完成");
                AppState.RunBg(async () => await LoadScanAsync(), "载入扫描");
            }
            else
            {
                SetRunning(false, $"任务{SinglePage.EvStatusText(ev.Status)}");
                AppState.Toast.Show(ev.Message.Length > 0 ? ev.Message : "任务未完成", "error", "扫描动画");
            }
        }
    }

    private async Task LoadScanAsync()
    {
        if (_jobId is null) return;
        var reply = await AppState.Bridge.SendAsync("get_result",
            new JsonObject { ["job_id"] = _jobId }, timeoutMs: 240_000);
        var scan = ScanResult.Parse(reply);
        _scan = scan;
        _frameCache.Clear();
        _cacheOrder.Clear();
        _resultTitle.Text = scan.ParamsSummary;

        _frameLoading = true;
        _frameSlider.Maximum = Math.Max(0, scan.Frames.Count - 1);
        _frameSlider.Value = 0;
        _frameLoading = false;
        _frameSlider.IsEnabled = scan.Frames.Count > 1;
        SetFrame(0);
    }

    // ---------------- 播放 ----------------

    private void TogglePlay()
    {
        if (_scan is null) return;
        if (_timer.IsEnabled)
        {
            _timer.Stop();
            _playBtn.Content = "▶";
        }
        else
        {
            _timer.Start();
            _playBtn.Content = "⏸";
        }
    }

    private void AdvanceFrame()
    {
        if (_scan is null || _scan.Frames.Count == 0) return;
        var next = (_currentFrame + 1) % _scan.Frames.Count;
        SetFrame(next);
        _frameSlider.Value = next;
    }

    private void StepFrame(int delta)
    {
        if (_scan is null || _scan.Frames.Count == 0) return;
        var next = Math.Clamp(_currentFrame + delta, 0, _scan.Frames.Count - 1);
        SetFrame(next);
        _frameSlider.Value = next;
    }

    private void SetFrame(int index)
    {
        if (_scan is null || index < 0 || index >= _scan.Frames.Count) return;
        _currentFrame = index;
        var info = _scan.Frames[index];
        _valueText.Text = FrameLabel(index, info.Value);

        if (_scan.Embedded && info.Xs.Length > 1)
        {
            ShowFrame(info.Xs, info.Ys, null);
            return;
        }
        if (_frameCache.TryGetValue(index, out var cached))
        {
            ShowFrame(cached.Xs, cached.Ys, null);
            return;
        }
        // 懒加载（真实后端：按帧取全量；缓存 3 帧）
        var jobId = _jobId;
        _valueText.Text += " · 载入中…";
        AppState.RunBg(async () =>
        {
            if (jobId is null) return;
            var reply = await AppState.Bridge.SendAsync("get_result",
                new JsonObject { ["job_id"] = jobId, ["frame"] = index }, timeoutMs: 240_000);
            var frame = SingleResult.Parse(reply);
            _frameCache[index] = frame;
            _cacheOrder.Enqueue(index);
            while (_cacheOrder.Count > 3 && _cacheOrder.TryDequeue(out var old))
            {
                if (old != index) _frameCache.Remove(old);
            }
            if (_currentFrame == index)
                ShowFrame(frame.Xs, frame.Ys, frame.Meta);
        }, "载入帧");
    }

    private string FrameLabel(int index, double value)
    {
        var axis = _scan?.Axis ?? "te";
        var unit = _scan?.Unit ?? "";
        var name = axis switch { "te" => "Te", "ne" => "Ne", _ => "R" };
        var valueText = axis == "ne" ? $"10^{value:0.##}" : value.ToString("0.###");
        return $"帧 {index + 1}/{_scan?.Frames.Count ?? 0} · {name}={valueText}{unit}";
    }

    private void ShowFrame(double[] xs, double[] ys, JsonObject? meta)
    {
        var stick = meta is not null && meta.JStr("spectrum_style") == "stick";
        _chart.SetSpectrum(xs, ys, stick);
        _chart.SetAnnotations(subtitle: "", frameText: _scan?.ParamsSummary);
    }

    // ---------------- 跨页：载入历史任务 ----------------

    public void LoadJobId(string jobId)
    {
        _jobId = jobId;
        SetRunning(false, $"载入任务 {jobId} 的结果…");
        AppState.RunBg(async () => await LoadScanAsync(), "载入扫描");
    }

    // ---------------- 导出 ----------------

    private async Task ExportAsync(string kind)
    {
        if (_jobId is null || _scan is null)
        {
            AppState.Toast.Show("还没有可导出的扫描结果，先运行一次", "warn");
            return;
        }
        var body = new JsonObject { ["job_id"] = _jobId, ["kind"] = kind };
        if (kind == "png") body["frame"] = Math.Max(0, _currentFrame);
        var reply = await AppState.Bridge.SendAsync("export", body, timeoutMs: 300_000);
        SinglePage.SaveExport(ExportResult.Parse(reply), $"扫描 {kind.ToUpper()}");
    }
}
