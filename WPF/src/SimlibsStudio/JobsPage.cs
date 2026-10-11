using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Text.Json.Nodes;
using Microsoft.Win32;
using SimlibsStudio.Bridge;
using SimlibsStudio.Controls;
using static SimlibsStudio.Bridge.JsonExt;

namespace SimlibsStudio;

/// <summary>任务记录页：任务表（状态/进度/耗时）+ 事件日志 + 历史结果直达 + 离线打开 CSV。</summary>
public sealed class JobsPage : PageBase
{
    private readonly StackPanel _list = new();
    private readonly TextBlock _logTitle = new()
    {
        FontSize = 12.5,
        FontWeight = FontWeights.SemiBold,
        Foreground = (Brush)Application.Current.Resources["Text.Primary"],
    };
    private readonly ListBox _logList = new()
    {
        FontFamily = new FontFamily("Consolas"),
        FontSize = 11.5,
        BorderThickness = new Thickness(0),
        Background = Brushes.Transparent,
        MaxHeight = 260,
    };
    private readonly SpectrumChart _historyChart = new();
    private readonly Dictionary<string, JobView> _jobs = new();
    private readonly Dictionary<string, Border> _cards = new();
    private string? _selectedJob;

    public JobsPage()
    {
        Content = BuildLayout();
        AppState.JobEvent += OnJobEvent;
        _historyChart.SetEmptyText("点击「打开历史 CSV」离线查看（wavelength,intensity 或 NIST 格式）");
    }

    private UIElement BuildLayout()
    {
        var grid = new Grid();
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(16) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1.1, GridUnitType.Star) });

        // —— 左：任务列表 ——
        var leftCard = new Border { Style = (Style)Application.Current.Resources["Card"] };
        var left = new DockPanel();
        var toolbar = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 0, 10) };
        toolbar.Children.Add(MakeGhost("刷新", () => AppState.RunBg(RefreshAsync, "刷新任务")));
        toolbar.Children.Add(MakeGhost("打开历史 CSV", OpenHistoryCsv));
        DockPanel.SetDock(toolbar, Dock.Top);
        left.Children.Add(toolbar);
        var scroll = new ScrollViewer { VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Padding = new Thickness(2) };
        scroll.Content = _list;
        left.Children.Add(scroll);
        leftCard.Child = left;
        Grid.SetColumn(leftCard, 0);
        grid.Children.Add(leftCard);

        // —— 右：详情 + 历史 CSV ——
        var rightCard = new Border { Style = (Style)Application.Current.Resources["Card"] };
        var right = new DockPanel();
        var logHeader = new Grid { Margin = new Thickness(0, 0, 0, 8) };
        logHeader.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        logHeader.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        Grid.SetColumn(_logTitle, 0);
        var clearBtn = MakeGhost("清除历史图谱", () => _historyChart.Clear("点击「打开历史 CSV」离线查看"));
        Grid.SetColumn(clearBtn, 1);
        logHeader.Children.Add(_logTitle);
        logHeader.Children.Add(clearBtn);
        DockPanel.SetDock(logHeader, Dock.Top);
        right.Children.Add(logHeader);

        _logList.ItemContainerStyle = (Style)Application.Current.Resources["CleanItem"];
        DockPanel.SetDock(_logList, Dock.Top);
        right.Children.Add(_logList);

        var chartHost = new Border
        {
            Child = _historyChart,
            Margin = new Thickness(0, 12, 0, 0),
        };
        right.Children.Add(chartHost);

        rightCard.Child = right;
        Grid.SetColumn(rightCard, 2);
        grid.Children.Add(rightCard);
        return grid;
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

    public override async void OnBridgeReady()
    {
        await RefreshAsync();
    }

    private async Task RefreshAsync()
    {
        var reply = await AppState.Bridge.SendAsync("list_jobs");
        _jobs.Clear();
        foreach (var job in reply.ObjectList("jobs"))
        {
            var view = JobView.Parse(job);
            _jobs[view.JobId] = view;
        }
        RenderList();
    }

    private void OnJobEvent(JobEventDto ev)
    {
        if (!_jobs.TryGetValue(ev.JobId, out var view))
        {
            view = new JobView { JobId = ev.JobId, Kind = "…", Summary = "" };
            _jobs[ev.JobId] = view;
        }
        if (ev.Status is not null) view.Status = ev.Status;
        if (ev.Progress.HasValue) view.Progress = ev.Progress.Value;
        if (ev.Message.Length > 0 && ev.Type == "log")
        {
            // 详情日志实时追加
            if (_selectedJob == ev.JobId)
            {
                _logList.Items.Add($"{ev.Ts}  {ev.Message}");
                if (_logList.Items.Count > 400) _logList.Items.RemoveAt(0);
                _logList.ScrollIntoView(_logList.Items[^1]);
            }
        }
        if (view.Kind == "…")
        {
            AppState.RunBg(async () =>
            {
                var reply = await AppState.Bridge.SendAsync("get_job",
                    new JsonObject { ["job_id"] = ev.JobId });
                var fresh = JobView.Parse(reply);
                _jobs[ev.JobId] = fresh;
                RenderList();
            }, "任务详情");
        }
        RenderList();
    }

    private void RenderList()
    {
        _list.Children.Clear();
        _cards.Clear();
        var ordered = _jobs.Values.OrderByDescending(j => j.Created).ToList();
        if (ordered.Count == 0)
        {
            _list.Children.Add(new TextBlock
            {
                Text = "暂无任务记录。\n运行单次/批量/扫描后，这里显示任务状态、进度与事件日志。",
                FontSize = 12,
                Foreground = (Brush)Application.Current.Resources["Text.Faint"],
                Margin = new Thickness(4, 10, 0, 0),
            });
            return;
        }
        foreach (var job in ordered)
        {
            var card = BuildJobCard(job);
            _cards[job.JobId] = card;
            _list.Children.Add(card);
        }
    }

    private Border BuildJobCard(JobView job)
    {
        var grid = new Grid { Margin = new Thickness(0) };
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

        // 行1：类型 + 状态 chip + 耗时
        var top = new Grid();
        top.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        top.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        top.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        top.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        top.Children.Add(new Chip(job.Kind, (Brush)Application.Current.Resources["Accent.C"]));
        var statusChip = new Chip(StatusText(job.Status), StatusBrush(job.Status))
        {
            Margin = new Thickness(8, 0, 0, 0),
        };
        Grid.SetColumn(statusChip, 1);
        top.Children.Add(statusChip);
        var duration = new TextBlock
        {
            Text = $"{job.Created} · {job.Duration}",
            FontSize = 11,
            Foreground = (Brush)Application.Current.Resources["Text.Faint"],
            HorizontalAlignment = HorizontalAlignment.Right,
            VerticalAlignment = VerticalAlignment.Center,
        };
        Grid.SetColumn(duration, 3);
        top.Children.Add(duration);
        Grid.SetRow(top, 0);
        grid.Children.Add(top);

        // 行2：摘要
        var summary = new TextBlock
        {
            Text = job.Summary.Length > 0 ? job.Summary : job.JobId,
            FontSize = 12,
            Foreground = (Brush)Application.Current.Resources["Text.Secondary"],
            TextTrimming = TextTrimming.CharacterEllipsis,
            Margin = new Thickness(0, 6, 0, 0),
        };
        Grid.SetRow(summary, 1);
        grid.Children.Add(summary);

        // 行3：进度条或操作按钮
        if (!job.IsTerminal)
        {
            var bar = new ProgressBar
            {
                Height = 4,
                Minimum = 0,
                Maximum = 100,
                Value = job.Progress,
                Margin = new Thickness(0, 8, 0, 0),
            };
            Grid.SetRow(bar, 2);
            grid.Children.Add(bar);
        }
        else
        {
            var actions = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 8, 0, 0) };
            if (job.Status == "completed")
            {
                actions.Children.Add(MakeGhost("查看结果", () => OpenResult(job)));
            }
            actions.Children.Add(MakeGhost("事件日志", () => ShowLog(job)));
            Grid.SetRow(actions, 2);
            grid.Children.Add(actions);
        }

        return new Border
        {
            Child = grid,
            Padding = new Thickness(12, 10, 12, 12),
            CornerRadius = new CornerRadius(11),
            Background = (Brush)Application.Current.Resources["Bg.Card2"],
            BorderBrush = (Brush)Application.Current.Resources["Line.Subtle"],
            BorderThickness = new Thickness(1),
            Margin = new Thickness(0, 0, 0, 10),
        };
    }

    private static string StatusText(string status) => status switch
    {
        "queued" => "排队",
        "running" => "运行中",
        "completed" => "已完成",
        "failed" => "失败",
        "cancelled" => "已取消",
        _ => status,
    };

    private static Brush StatusBrush(string status) => (Brush)Application.Current.Resources[status switch
    {
        "completed" => "State.Ok",
        "failed" => "State.Error",
        "cancelled" => "State.Warn",
        "running" => "State.Running",
        _ => "Text.Faint",
    }];

    private void ShowLog(JobView job)
    {
        _selectedJob = job.JobId;
        _logTitle.Text = $"事件日志 · {job.Kind} · {job.JobId}";
        _logList.Items.Clear();
        foreach (var ev in job.Events)
        {
            _logList.Items.Add($"{ev.Ts}  [{ev.Level}] {ev.Message}");
        }
        if (job.Events.Count == 0)
        {
            _logList.Items.Add("（此任务无事件记录，可能是历史会话任务）");
        }
        _logList.ScrollIntoView(_logList.Items[^1]);
    }

    private void OpenResult(JobView job)
    {
        try
        {
            if (job.Kind.Contains("单次"))
            {
                if (AppState.Window.TryGetPage<SinglePage>("single", out var single))
                {
                    AppState.Window.Go("single");
                    single.LoadJobId(job.JobId);
                }
            }
            else if (job.Kind.Contains("批量"))
            {
                if (AppState.Window.TryGetPage<BatchPage>("batch", out var batch))
                {
                    AppState.Window.Go("batch");
                    _ = batch.LoadJobAsync(job.JobId);
                }
            }
            else if (job.Kind.Contains("扫描"))
            {
                if (AppState.Window.TryGetPage<ScanPage>("scan", out var scan))
                {
                    AppState.Window.Go("scan");
                    scan.LoadJobId(job.JobId);
                }
            }
            else
            {
                AppState.Toast.Show("未知任务类型：" + job.Kind, "warn");
            }
        }
        catch (Exception exc)
        {
            AppState.Toast.Show(exc.Message, "error", "打开结果");
        }
    }

    private void OpenHistoryCsv()
    {
        var dlg = new OpenFileDialog
        {
            Filter = "CSV 数据|*.csv|全部文件|*.*",
            Title = "打开历史光谱 CSV",
        };
        if (dlg.ShowDialog() != true) return;
        AppState.RunBg(async () =>
        {
            var reply = await AppState.Bridge.SendAsync("open_history",
                new JsonObject { ["path"] = dlg.FileName });
            var series = reply.ObjectList("series")
                .Select(s => new SeriesData
                {
                    Label = s.JStr("label"),
                    Xs = s.DoubleArray("xs"),
                    Ys = s.DoubleArray("ys"),
                })
                .ToList();
            var meta = reply.Obj("meta") ?? new JsonObject();
            _historyChart.SetSpectrum(
                series.Count > 0 ? series[0].Xs : Array.Empty<double>(),
                series.Count > 0 ? series[0].Ys : Array.Empty<double>(),
                stick: false);
            if (series.Count > 1) _historyChart.SetIons(series);
            _historyChart.SetAnnotations(subtitle: meta.JStr("params", ""));
            _logTitle.Text = $"历史 CSV · {System.IO.Path.GetFileName(dlg.FileName)}";
            _logList.Items.Clear();
            _logList.Items.Add("来源   " + meta.JStr("source"));
            _logList.Items.Add("SHA256 " + meta.JStr("sha256", "—"));
            _logList.Items.Add("点数   " + meta.JStr("points", "—"));
            _logList.Items.Add("参数   " + meta.JStr("params", "参数未知（历史数据，非本次模拟）"));
            AppState.Toast.Show("历史 CSV 已载入（离线，不联网）", "ok", "历史记录");
        }, "打开历史 CSV");
    }
}
