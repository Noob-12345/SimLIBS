using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Media.Animation;
using System.Windows.Controls.Primitives;
using System.Windows.Threading;
using SimlibsStudio.Bridge;
using SimlibsStudio.Controls;

namespace SimlibsStudio;

public partial class MainWindow : Window
{
    private readonly Dictionary<string, PageBase> _pages = new();
    private PageBase? _current;
    private readonly Dictionary<string, string> _jobStatus = new();
    private int _runningCount;
    private readonly DispatcherTimer _screenshotTimer;
    private readonly List<Action> _screenshotSteps = new();
    private bool _screenshotMode;

    public ToastService Toasts { get; }

    private static readonly Dictionary<string, (string Title, string Sub)> PageMeta = new()
    {
        ["single"] = ("单次模拟", "Te / Ne / R · 三条计算路径（本地 / 服务器 / 客户端）· 元素贡献视图"),
        ["batch"] = ("批量模拟", "组成池 / 随机规则 / CSV 模板 · 数据集与训练数据包导出"),
        ["scan"] = ("扫描动画", "沿 Te / Ne / R 轴逐帧扫描 · 自动播放 · 导出 PNG / GIF"),
        ["jobs"] = ("任务记录", "任务状态与事件日志 · 历史结果直达 · 离线打开历史 CSV"),
        ["settings"] = ("设置", "引擎路径 · 超时与网络 · 代理 · 输出目录"),
    };

    public MainWindow()
    {
        AppState.Theme.Load();   // 先加载持久化的外观（模式 × 强调色），窗口资源随取随用
        InitializeComponent();
        Toasts = new ToastService(ToastHost, Dispatcher);
        AppState.Initialize(this, Toasts);
        AppState.Theme.Changed += () =>
        {
            UpdateThemeIcon();
            foreach (var page in _pages.Values)
            {
                ThemeManager.RetargetTree(page);
                page.OnThemeChanged();
            }
        };

        _pages["single"] = new SinglePage();
        _pages["batch"] = new BatchPage();
        _pages["scan"] = new ScanPage();
        _pages["jobs"] = new JobsPage();
        _pages["settings"] = new SettingsPage();
        // 页面视觉树在首次布局时才构建；进入树时重定向旧画刷引用，保证换肤覆盖所有页面
        foreach (var page in _pages.Values)
        {
            var p = page;
            p.Loaded += (_, _) => ThemeManager.RetargetTree(p);
        }
        Go("single");

        AppState.JobEvent += OnJobEvent;
        AppState.BridgeReadyChanged += () =>
        {
            BridgeDot.SetResourceReference(System.Windows.Shapes.Shape.FillProperty,
                AppState.BridgeReady ? "State.Ok" : "State.Warn");
            BridgeText.Text = AppState.BridgeReady ? "后端运行中" : "后端未就绪";
            SideEngine.Text = AppState.BridgeReady
                ? (AppState.Mock ? "MOCK 演示引擎（合成谱）" : "真实引擎 · simLIBS")
                : "引擎启动中…";
            SideInterp.Text = AppState.Interpreter;
        };

        PreviewKeyDown += (_, e) =>
        {
            if (e.Key == Key.F2) Go("single");
            else if (e.Key == Key.F3) Go("batch");
            else if (e.Key == Key.F4) Go("scan");
            else if (e.Key == Key.F5) Go("jobs");
            else if (e.Key == Key.F6) Go("settings");
            else if (e.Key == Key.T && Keyboard.Modifiers.HasFlag(ModifierKeys.Control)) ToggleTheme();
        };

        _screenshotTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(400) };
    }

    // ---------------- 启动 ----------------

    public void Boot(bool mock)
    {
        if (mock) MockBadge.Visibility = Visibility.Visible;
        UpdateThemeIcon();
        Dbg.Log("Boot: starting bridge, mock=" + mock);
        AppState.StartBridge(mock);

        AppState.RunBg(async () =>
        {
            var sw = Stopwatch.StartNew();
            while (!AppState.BridgeReady && sw.Elapsed < TimeSpan.FromSeconds(120))
                await Task.Delay(150);
            if (!AppState.BridgeReady)
                throw new TimeoutException("后端握手超时（查看日志或用 --diagnose-self 检查）");
            await AppState.BootAsync();
            foreach (var page in _pages.Values) page.OnBridgeReady();
            HideBootOverlay();
        }, "启动");
    }

    private void HideBootOverlay()
    {
        Dispatcher.BeginInvoke(new Action(() =>
        {
            var fade = new DoubleAnimation(BootOverlay.Opacity, 0, TimeSpan.FromMilliseconds(320))
            {
                EasingFunction = new CubicEase(),
            };
            fade.Completed += (_, _) => BootOverlay.Visibility = Visibility.Collapsed;
            BootOverlay.BeginAnimation(OpacityProperty, fade);
        }));
    }

    // ---------------- 导航 ----------------

    public bool TryGetPage<T>(string id, out T? page) where T : PageBase
    {
        if (_pages.TryGetValue(id, out var p) && p is T typed)
        {
            page = typed;
            return true;
        }
        page = null;
        return false;
    }

    public void Go(string pageId, bool animate = true)
    {
        if (!_pages.TryGetValue(pageId, out var page)) return;
        if (ReferenceEquals(_current, page)) return;
        _current = page;
        PageHost.Content = page;

        if (PageMeta.TryGetValue(pageId, out var meta))
        {
            PageTitle.Text = meta.Title;
            PageSub.Text = meta.Sub;
        }
        var radio = pageId switch
        {
            "batch" => NavBatch,
            "scan" => NavScan,
            "jobs" => NavJobs,
            "settings" => NavSettings,
            _ => NavSingle,
        };
        radio.IsChecked = true;

        if (!animate) return;

        // 页面淡入 + 轻微上滑
        var fade = new DoubleAnimation(0, 1, TimeSpan.FromMilliseconds(220))
        {
            EasingFunction = new CubicEase(),
        };
        var slide = new TranslateTransform(0, 10);
        var slideAnim = new DoubleAnimation(10, 0, TimeSpan.FromMilliseconds(220))
        {
            EasingFunction = new CubicEase(),
        };
        PageHost.RenderTransform = slide;
        page.BeginAnimation(OpacityProperty, fade);
        slide.BeginAnimation(TranslateTransform.YProperty, slideAnim);
    }

    private void OnNavClick(object sender, RoutedEventArgs e)
    {
        if (sender is RadioButton { Tag: string pid }) Go(pid);
    }

    // ---------------- 标题栏 ----------------

    private void ToggleTheme() => AppState.Theme.Toggle();

    private void OnMinimize(object sender, RoutedEventArgs e) => WindowState = WindowState.Minimized;

    private void OnMaximize(object sender, RoutedEventArgs e)
    {
        WindowState = WindowState == WindowState.Maximized ? WindowState.Normal : WindowState.Maximized;
    }

    private void OnClose(object sender, RoutedEventArgs e) => Close();

    // ---------------- 任务事件与状态 ----------------

    private void OnJobEvent(JobEventDto ev)
    {
        if (ev.Status is not null)
        {
            var wasRunning = _jobStatus.TryGetValue(ev.JobId, out var prev) &&
                             prev is "queued" or "running";
            var nowRunning = ev.Status is "queued" or "running" && !ev.Final;
            _jobStatus[ev.JobId] = ev.Status;
            if (!wasRunning && nowRunning) _runningCount++;
            if (wasRunning && !nowRunning) _runningCount = Math.Max(0, _runningCount - 1);
            UpdateRunningPill();
        }
        else if (ev.Type == "status" && !_jobStatus.ContainsKey(ev.JobId))
        {
            _runningCount++;
            UpdateRunningPill();
        }
    }

    private void UpdateRunningPill()
    {
        Dispatcher.BeginInvoke(new Action(() =>
        {
            RunningPill.Visibility = _runningCount > 0 ? Visibility.Visible : Visibility.Collapsed;
            RunningText.Text = $"{_runningCount} 个任务运行中";
        }));
    }

    public void UpdateEngineChip(string engineLabel, string nistLabel)
    {
        Dispatcher.BeginInvoke(new Action(() =>
        {
            EngineChip.Text = $"{engineLabel} · {nistLabel}";
        }));
    }

    // ---------------- 截图自查（--screenshot） ----------------

    /// <summary>offscreen 巡回渲染各页面 PNG（自查用），完成后退出。</summary>
    public void StartScreenshotTour()
    {
        _screenshotMode = true;
        var outDir = Path.Combine(BridgeHost.WpfRoot, "output", "screenshots");
        Directory.CreateDirectory(outDir);
        var shots = new List<(string name, string page)>();

        void Step()
        {
            if (_screenshotSteps.Count == 0)
            {
                _screenshotTimer.Stop();
                Close();
                return;
            }
            _screenshotSteps[0]();
            _screenshotSteps.RemoveAt(0);
        }

        void Snap(string name, string page)
        {
            _screenshotSteps.Add(() =>
            {
                Go(page, animate: false);
                DoEvents();
                Dispatcher.Invoke(() =>
                {
                    var w = (int)Math.Max(1, ActualWidth);
                    var h = (int)Math.Max(1, ActualHeight);
                    var rtb = new RenderTargetBitmap(w, h, 96, 96, PixelFormats.Pbgra32);
                    rtb.Render(this);
                    var encoder = new PngBitmapEncoder();
                    encoder.Frames.Add(BitmapFrame.Create(rtb));
                    using var fs = File.Create(Path.Combine(outDir, name + ".png"));
                    encoder.Save(fs);
                    Console.WriteLine("saved " + name);
                });
            });
        }

        _screenshotSteps.Add(() =>
        {
            // 等 bridge ready + 默认参数
            var sw = Stopwatch.StartNew();
            while (!AppState.BridgeReady && sw.Elapsed < TimeSpan.FromSeconds(90))
            {
                DoEvents();
                Task.Delay(150).Wait();
                DoEvents();
            }
            HideBootOverlay();
            DoEvents();
        });

        foreach (var (name, page) in new[]
                 {
                     ("single-dark", "single"), ("batch-dark", "batch"), ("scan-dark", "scan"),
                     ("jobs-dark", "jobs"), ("settings-dark", "settings"),
                 })
        {
            Snap(name, page);
        }

        // mock 单次端到端自检：提交任务 → 等完成 → 截真实谱图
        if (TryGetPage<SinglePage>("single", out var single))
        {
            var sp = single;
            _screenshotSteps.Add(() =>
            {
                Go("single", animate: false);
                DoEvents();
                sp.StartRunForSelfTest();
            });
            _screenshotSteps.Add(() =>
            {
                var sw2 = Stopwatch.StartNew();
                while (sp.IsBusy && sw2.Elapsed < TimeSpan.FromSeconds(90))
                {
                    DoEvents();
                    Task.Delay(200).Wait();
                    DoEvents();
                }
                DoEvents();
            });
            Snap("single-result-dark", "single");
        }

        // 主题颜色预览弹窗 + 强调色切换 + 跟随系统模式
        _screenshotSteps.Add(() =>
        {
            DoEvents();
            ShowAccentFlyout();
            DoEvents();
        });
        Snap("accent-flyout-dark", "single");
        _screenshotSteps.Add(() =>
        {
            // Popup 是独立 HWND，窗口截图抓不到；直接渲染弹层内容
            if (_flyout?.Child is Border host)
            {
                host.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
                host.Arrange(new Rect(new Point(0, 0), host.DesiredSize));
                var w = (int)Math.Ceiling(host.DesiredSize.Width) + 2;
                var h = (int)Math.Ceiling(host.DesiredSize.Height) + 2;
                var rtb = new RenderTargetBitmap(w, h, 96, 96, PixelFormats.Pbgra32);
                rtb.Render(host);
                var encoder = new PngBitmapEncoder();
                encoder.Frames.Add(BitmapFrame.Create(rtb));
                using var fs = File.Create(Path.Combine(
                    BridgeHost.WpfRoot, "output", "screenshots", "accent-flyout-content.png"));
                encoder.Save(fs);
                Console.WriteLine("saved accent-flyout-content");
            }
            DoEvents();
        });
        _screenshotSteps.Add(() =>
        {
            CloseFlyout();
            AppState.Theme.SetAccent("violet");
            DoEvents();
        });
        Snap("single-violet-dark", "single");
        _screenshotSteps.Add(() =>
        {
            AppState.Theme.SetAccent("plasma");
            AppState.Theme.SetMode(SimlibsStudio.ThemeMode.System);
            DoEvents();
        });
        Snap("single-systemmode", "single");
        _screenshotSteps.Add(() =>
        {
            AppState.Theme.SetMode(SimlibsStudio.ThemeMode.Dark);
            DoEvents();
        });

        _screenshotSteps.Add(() =>
        {
            AppState.Theme.Toggle();
            DoEvents();
        });
        foreach (var (name, page) in new[]
                 {
                     ("single-light", "single"), ("batch-light", "batch"), ("settings-light", "settings"),
                 })
        {
            Snap(name, page);
        }
        _screenshotSteps.Add(() =>
        {
            AppState.Theme.Toggle();
            DoEvents();
        });

        Dbg.Log("Tour: steps=" + _screenshotSteps.Count);
        _screenshotTimer.Tick += (_, _) => Step();
        _screenshotTimer.Start();
    }

    private void DoEvents()
    {
        var frame = new DispatcherFrame();
        Dispatcher.CurrentDispatcher.BeginInvoke(DispatcherPriority.Background,
            new DispatcherOperationCallback(f =>
            {
                ((DispatcherFrame)f).Continue = false;
                return null;
            }), frame);
        Dispatcher.PushFrame(frame);
    }

    protected override void OnClosed(EventArgs e)
    {
        base.OnClosed(e);
        (AppState.Bridge as IDisposable)?.Dispose();
        if (_screenshotMode) Application.Current.Shutdown(0);
    }
}
