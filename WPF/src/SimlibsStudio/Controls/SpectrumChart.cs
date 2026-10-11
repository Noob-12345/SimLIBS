using System.Globalization;
using System.IO;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using SimlibsStudio.Bridge;
using static SimlibsStudio.Bridge.JsonExt;
using JsonObject = System.Text.Json.Nodes.JsonObject;

namespace SimlibsStudio.Controls;

/// <summary>
/// 光谱图控件（自绘，无第三方依赖）：
/// 左键框选缩放 · 中键/Shift+左键平移 · 滚轮以光标为中心缩放 · 右键/双击复位；
/// 未展宽线谱自动切换竖线（stick）渲染；支持元素贡献叠加（稳定按元素配色）。
/// </summary>
public sealed class SpectrumChart : FrameworkElement
{
    private const double ML = 64, MR = 20, MT = 30, MB = 38;

    private double[] _xs = Array.Empty<double>();
    private double[] _ys = Array.Empty<double>();
    private List<SeriesData> _ions = new();
    private bool _showIons;
    private bool _stickMode;

    private double _fullX0 = 0, _fullX1 = 1;   // 数据全域
    private double _x0 = 0, _x1 = 1;           // 当前可见域
    private string? _subtitle;
    private string? _frameText;
    private string _emptyText = "运行任务后显示光谱";
    private bool _previewBadge;                 // “示意预览”角标

    // 交互状态
    private bool _selecting;
    private double _selStartPx, _selEndPx;
    private bool _panning;
    private double _panStartPx, _panStartX0, _panStartX1;
    private Point _mouse;
    private bool _hovering;
    private int _hoverIndex = -1;

    // 渲染缓存（可见域变化时重建）
    private readonly List<(double px, double lo, double hi)> _columns = new();
    private double _yMax = 1;
    private bool _hasData;

    public event Action? ViewChanged;

    public SpectrumChart()
    {
        ClipToBounds = true;
        SnapsToDevicePixels = true;
        Cursor = Cursors.Cross;
    }

    // ---------------- 数据接入 ----------------

    public void SetSpectrum(double[] xs, double[] ys, bool stick)
    {
        _xs = xs ?? Array.Empty<double>();
        _ys = ys ?? Array.Empty<double>();
        _stickMode = stick;
        _hasData = _xs.Length > 1;
        if (_hasData)
        {
            _fullX0 = _xs[0];
            _fullX1 = _xs[^1];
            if (_fullX1 <= _fullX0) _fullX1 = _fullX0 + 1;
            _x0 = _fullX0;
            _x1 = _fullX1;
        }
        RebuildCache();
        InvalidateVisual();
    }

    public void SetIons(IEnumerable<SeriesData> ions)
    {
        _ions = ions?.ToList() ?? new List<SeriesData>();
        RebuildCache();
        InvalidateVisual();
    }

    public bool ShowIons
    {
        get => _showIons;
        set { _showIons = value; RebuildCache(); InvalidateVisual(); }
    }

    public void SetAnnotations(string? subtitle = null, string? frameText = null, bool? previewBadge = null)
    {
        if (subtitle != null) _subtitle = subtitle.Length == 0 ? null : subtitle;
        if (frameText != null) _frameText = frameText.Length == 0 ? null : frameText;
        if (previewBadge.HasValue) _previewBadge = previewBadge.Value;
        InvalidateVisual();
    }

    public void SetEmptyText(string text)
    {
        _emptyText = text;
        InvalidateVisual();
    }

    public void Clear(string emptyText = "运行任务后显示光谱")
    {
        _xs = Array.Empty<double>();
        _ys = Array.Empty<double>();
        _ions = new List<SeriesData>();
        _hasData = false;
        _emptyText = emptyText;
        _subtitle = null;
        _frameText = null;
        _previewBadge = false;
        InvalidateVisual();
    }

    public void ResetView()
    {
        _x0 = _fullX0;
        _x1 = _fullX1;
        RebuildCache();
        InvalidateVisual();
        ViewChanged?.Invoke();
    }

    /// <summary>当前可见域（供状态栏读数）。</summary>
    public (double x0, double x1) VisibleX => (_x0, _x1);

    /// <summary>渲染为 PNG（用于导出当前视图）。</summary>
    public void ExportPng(string path, int scale = 2)
    {
        var w = Math.Max(1, (int)ActualWidth);
        var h = Math.Max(1, (int)ActualHeight);
        var rtb = new RenderTargetBitmap(w * scale, h * scale, 96 * scale, 96 * scale, PixelFormats.Pbgra32);
        rtb.Render(this);
        var encoder = new PngBitmapEncoder();
        encoder.Frames.Add(BitmapFrame.Create(rtb));
        using var fs = File.Create(path);
        encoder.Save(fs);
    }

    // ---------------- 交互 ----------------

    private bool InPlot(Point p) =>
        p.X >= ML && p.X <= ActualWidth - MR && p.Y >= MT && p.Y <= ActualHeight - MB;

    private double PxToX(double px)
    {
        var w = Math.Max(1, ActualWidth - ML - MR);
        return _x0 + (px - ML) / w * (_x1 - _x0);
    }

    private double XToPx(double x)
    {
        var w = Math.Max(1, ActualWidth - ML - MR);
        return ML + (x - _x0) / Math.Max(1e-12, _x1 - _x0) * w;
    }

    protected override void OnMouseLeftButtonDown(MouseButtonEventArgs e)
    {
        Focus();
        if (e.ClickCount == 2)
        {
            ResetView();
            e.Handled = true;
            return;
        }
        var p = e.GetPosition(this);
        if (!InPlot(p)) return;
        if (Keyboard.Modifiers.HasFlag(ModifierKeys.Shift))
        {
            _panning = true;
            _panStartPx = p.X;
            _panStartX0 = _x0;
            _panStartX1 = _x1;
            CaptureMouse();
        }
        else
        {
            _selecting = true;
            _selStartPx = p.X;
            _selEndPx = p.X;
            CaptureMouse();
        }
        e.Handled = true;
    }

    protected override void OnMouseDown(MouseButtonEventArgs e)
    {
        if (e.ChangedButton != MouseButton.Middle) return;
        var p = e.GetPosition(this);
        if (!InPlot(p)) return;
        _panning = true;
        _panStartPx = p.X;
        _panStartX0 = _x0;
        _panStartX1 = _x1;
        CaptureMouse();
        e.Handled = true;
    }

    protected override void OnMouseMove(MouseEventArgs e)
    {
        var p = e.GetPosition(this);
        _mouse = p;
        _hovering = InPlot(p);

        if (_panning)
        {
            var w = Math.Max(1, ActualWidth - ML - MR);
            var shift = (p.X - _panStartPx) / w * (_panStartX1 - _panStartX0);
            var span = _panStartX1 - _panStartX0;
            _x0 = _panStartX0 - shift;
            _x1 = _panStartX0 - shift + span;
            ClampView();
            RebuildCache();
        }
        else if (_selecting)
        {
            _selEndPx = Math.Clamp(p.X, ML, ActualWidth - MR);
        }

        if (_hovering && _hasData)
        {
            _hoverIndex = FindNearest(PxToX(p.X));
        }
        InvalidateVisual();
        e.Handled = _panning || _selecting;
    }

    protected override void OnMouseLeftButtonUp(MouseButtonEventArgs e)
    {
        if (_selecting)
        {
            _selecting = false;
            ReleaseMouseCapture();
            if (Math.Abs(_selEndPx - _selStartPx) > 6)
            {
                var xa = PxToX(Math.Min(_selStartPx, _selEndPx));
                var xb = PxToX(Math.Max(_selStartPx, _selEndPx));
                _x0 = Math.Max(_fullX0, xa);
                _x1 = Math.Min(_fullX1, xb);
                if (_x1 - _x0 > 1e-9)
                {
                    ClampView();
                    RebuildCache();
                    ViewChanged?.Invoke();
                }
            }
            InvalidateVisual();
            e.Handled = true;
        }
        if (_panning)
        {
            _panning = false;
            ReleaseMouseCapture();
            ViewChanged?.Invoke();
            e.Handled = true;
        }
    }

    protected override void OnMouseUp(MouseButtonEventArgs e)
    {
        if (e.ChangedButton == MouseButton.Middle && _panning)
        {
            _panning = false;
            ReleaseMouseCapture();
            ViewChanged?.Invoke();
            e.Handled = true;
        }
        base.OnMouseUp(e);
    }

    protected override void OnMouseWheel(MouseWheelEventArgs e)
    {
        if (!_hasData || !InPlot(e.GetPosition(this))) return;
        var factor = e.Delta > 0 ? 1 / 1.25 : 1.25;
        var anchor = PxToX(e.GetPosition(this).X);
        var xa = anchor + (_x0 - anchor) * factor;
        var xb = anchor + (_x1 - anchor) * factor;
        if (xb - xa >= Math.Max(1e-6, (_fullX1 - _fullX0) * 1e-4))
        {
            _x0 = xa;
            _x1 = xb;
            ClampView();
            RebuildCache();
            InvalidateVisual();
            ViewChanged?.Invoke();
        }
        e.Handled = true;
    }

    protected override void OnMouseRightButtonDown(MouseButtonEventArgs e)
    {
        ResetView();
        e.Handled = true;
    }

    protected override void OnMouseLeave(MouseEventArgs e)
    {
        _hovering = false;
        _hoverIndex = -1;
        InvalidateVisual();
        base.OnMouseLeave(e);
    }

    private void ClampView()
    {
        if (_x0 < _fullX0) { _x1 += _fullX0 - _x0; _x0 = _fullX0; }
        if (_x1 > _fullX1) { _x0 -= _x1 - _fullX1; _x1 = _fullX1; }
        if (_x0 < _fullX0) _x0 = _fullX0;
        var span = _x1 - _x0;
        if (span <= 0 || !double.IsFinite(span))
        {
            _x0 = _fullX0;
            _x1 = _fullX1;
        }
    }

    private int FindNearest(double x)
    {
        if (_xs.Length == 0) return -1;
        var lo = 0;
        var hi = _xs.Length - 1;
        while (hi - lo > 1)
        {
            var mid = (lo + hi) / 2;
            if (_xs[mid] < x) lo = mid; else hi = mid;
        }
        return Math.Abs(_xs[lo] - x) <= Math.Abs(_xs[hi] - x) ? lo : hi;
    }

    // ---------------- 渲染 ----------------

    private static Brush? Res(object key) => Application.Current?.TryFindResource(key) as Brush;

    private static Brush PlotBg() => Res("Bg.Plot") ?? Brushes.Transparent;
    private Brush GridBrush() => Res("Bg.GridLine") ?? new SolidColorBrush(Color.FromRgb(0x20, 0x22, 0x2a));
    private Brush TextBrush() => Res("Text.Faint") ?? Brushes.Gray;
    private Brush TextBrush2() => Res("Text.Secondary") ?? Brushes.Gray;
    private Brush AccentBrush() => Res("Accent.B") ?? Brushes.Orange;
    private Brush AccentCBrush() => Res("Accent.C") ?? Brushes.Cyan;

    private static readonly Typeface UiFont = new(new FontFamily("Segoe UI, Microsoft YaHei UI"), FontStyles.Normal, FontWeights.Normal, FontStretches.Normal);
    private static readonly Typeface MonoFont = new(new FontFamily("Consolas"), FontStyles.Normal, FontWeights.Normal, FontStretches.Normal);

    private FormattedText Fmt(string text, double size, Brush brush, bool bold = false, bool mono = false)
    {
        return new FormattedText(text, CultureInfo.InvariantCulture, FlowDirection.LeftToRight,
            mono ? MonoFont : UiFont, size, brush,
            VisualTreeHelper.GetDpi(this).PixelsPerDip);
    }

    private static Color ElementColor(string element)
    {
        unchecked
        {
            var h = 23;
            foreach (var c in element) h = h * 31 + c;
            var hue = Math.Abs(h % 360) / 360.0;
            return Hsl(hue, 0.60, 0.58);
        }
    }

    private static Color Hsl(double h, double s, double l)
    {
        var c = (1 - Math.Abs(2 * l - 1)) * s;
        var x = c * (1 - Math.Abs(h * 6 % 2 - 1));
        var m = l - c / 2;
        var (r, g, b) = h switch
        {
            < 1.0 / 6 => (c, x, 0.0),
            < 2.0 / 6 => (x, c, 0.0),
            < 3.0 / 6 => (0.0, c, x),
            < 4.0 / 6 => (0.0, x, c),
            < 5.0 / 6 => (x, 0.0, c),
            _ => (c, 0.0, x),
        };
        return Color.FromRgb((byte)((r + m) * 255), (byte)((g + m) * 255), (byte)((b + m) * 255));
    }

    protected override void OnRender(DrawingContext dc)
    {
        var w = ActualWidth;
        var h = ActualHeight;
        if (w < 10 || h < 10) return;

        // 背景
        var full = new Rect(0, 0, w, h);
        dc.DrawRectangle(null, new Pen(Res("Line.Subtle") ?? Brushes.Transparent, 1), full);
        var plot = new Rect(ML, MT, w - ML - MR, h - MT - MB);
        dc.DrawRectangle(PlotBg(), null, plot);
        dc.PushClip(new RectangleGeometry(plot));

        if (_hasData)
        {
            RenderAxes(dc, plot);
            RenderIons(dc, plot);
            RenderSpectrum(dc, plot);
            RenderHover(dc, plot);
        }
        else
        {
            var t = Fmt(_emptyText, 14, TextBrush());
            dc.DrawText(t, new Point((w - t.Width) / 2, (h - t.Height) / 2 - 8));
            var t2 = Fmt("本地模拟 / 服务器计算 / 客户端计算 · 单次 · 批量 · 扫描", 11, TextBrush());
            dc.DrawText(t2, new Point((w - t2.Width) / 2, (h - t2.Height) / 2 + 14));
        }
        dc.Pop();

        if (_hasData) RenderAnnotations(dc, w, plot);
        if (_selecting && Math.Abs(_selEndPx - _selStartPx) > 2)
        {
            var rect = new Rect(Math.Min(_selStartPx, _selEndPx), MT,
                Math.Abs(_selEndPx - _selStartPx), plot.Height);
            var fill = AccentCBrush().Clone();
            fill.Opacity = 0.14;
            dc.DrawRectangle(fill, new Pen(AccentCBrush(), 1) { DashStyle = DashStyles.Dash }, rect);
        }
    }

    private void RenderAxes(DrawingContext dc, Rect plot)
    {
        var grid = new Pen(GridBrush(), 1);
        var tx = TextBrush();

        // X 轴
        var spanX = _x1 - _x0;
        var (stepX, decX) = NiceStep(spanX / 6);
        var start = Math.Ceiling(_x0 / stepX) * stepX;
        for (var v = start; v <= _x1 + 1e-9; v += stepX)
        {
            var px = XToPx(v);
            if (px < ML - 0.5 || px > plot.Right + 0.5) continue;
            dc.DrawLine(grid, new Point(px, plot.Top), new Point(px, plot.Bottom));
            var label = Fmt(v.ToString(decX > 0 ? $"F{decX}" : "G6"), 11, tx, mono: true);
            dc.DrawText(label, new Point(px - label.Width / 2, plot.Bottom + 6));
        }
        var xTitle = Fmt("波长 λ (nm)", 11, TextBrush2());
        dc.DrawText(xTitle, new Point(plot.Right - xTitle.Width, plot.Bottom + 20));

        // Y 轴（0 基线 + 顶值刻度）
        dc.DrawLine(grid, new Point(plot.Left, plot.Bottom), new Point(plot.Right, plot.Bottom));
        var baseline = new Pen(TextBrush(), 0.7);
        dc.DrawLine(baseline, new Point(plot.Left, plot.Bottom), new Point(plot.Left, plot.Top));
        var yTop = _yMax;
        if (yTop > 0)
        {
            var yPx = plot.Bottom - plot.Height;
            var yLabel = Fmt(FormatAxisNumber(yTop), 11, tx, mono: true);
            dc.DrawText(yLabel, new Point(plot.Left - yLabel.Width - 6, yPx - yLabel.Height / 2));
        }
        var zero = Fmt("0", 11, tx, mono: true);
        dc.DrawText(zero, new Point(plot.Left - zero.Width - 6, plot.Bottom - zero.Height / 2));

        // 强度轴标题（旋转）
        var yTitle = Fmt("相对强度 (a.u.)", 11, TextBrush2());
        dc.PushTransform(new RotateTransform(-90, plot.Left - 44, plot.Top + plot.Height / 2));
        dc.DrawText(yTitle, new Point(plot.Left - 44 - yTitle.Width / 2, plot.Top + plot.Height / 2 - yTitle.Height / 2));
        dc.Pop();
    }

    private void RenderSpectrum(DrawingContext dc, Rect plot)
    {
        if (_columns.Count == 0) return;
        var accent = AccentBrush();

        var geo = new StreamGeometry();
        using (var ctx = geo.Open())
        {
            bool first = true;
            foreach (var (px, lo, hi) in _columns)
            {
                var yHi = plot.Bottom - (hi / _yMax) * plot.Height;
                if (first) { ctx.BeginFigure(new Point(px, yHi), false, false); first = false; }
                else ctx.LineTo(new Point(px, yHi), true, false);
            }
            if (!_stickMode)
            {
                for (var i = _columns.Count - 1; i >= 0; i--)
                {
                    var (px, lo, _) = _columns[i];
                    ctx.LineTo(new Point(px, plot.Bottom - (lo / _yMax) * plot.Height), true, false);
                }
                ctx.Close();
            }
        }
        geo.Freeze();

        // 面积填充（仅连续谱）
        if (!_stickMode)
        {
            var fill = (Res("Gradient.Area") ?? Brushes.Orange).Clone();
            fill.Opacity = 0.55;
            dc.DrawGeometry(null, null, geo);
        }

        // 光晕层 + 主线
        var glow = new Pen(accent, _stickMode ? 1.6 : 3.2) { LineJoin = PenLineJoin.Round };
        glow.Freeze();
        dc.DrawGeometry(null, glow, geo);
        var main = new Pen(accent, _stickMode ? 0.7 : 1.3) { LineJoin = PenLineJoin.Round };
        main.Freeze();
        dc.DrawGeometry(null, main, geo);
    }

    private void RenderIons(DrawingContext dc, Rect plot)
    {
        if (!_showIons || _ions.Count == 0) return;
        foreach (var ion in _ions)
        {
            if (ion.Xs.Length == 0) continue;
            var color = ElementColor(NormalizeElementLabel(ion.Label));
            var pen = new Pen(new SolidColorBrush(Color.FromArgb(200, color.R, color.G, color.B)), 0.9);
            pen.Freeze();
            var geo = new StreamGeometry();
            using (var ctx = geo.Open())
            {
                var first = true;
                foreach (var (px, lo, hi) in ColumnsFor(ion.Xs, ion.Ys, plot))
                {
                    var yHi = plot.Bottom - (hi / Math.Max(1e-12, IonYMax(ion))) * plot.Height * 0.92;
                    if (first) { ctx.BeginFigure(new Point(px, yHi), false, false); first = false; }
                    else ctx.LineTo(new Point(px, yHi), true, false);
                }
            }
            geo.Freeze();
            dc.DrawGeometry(null, pen, geo);
        }
    }

    private double IonYMax(SeriesData ion)
    {
        var max = 0.0;
        var x0 = _x0;
        var x1 = _x1;
        for (var i = 0; i < ion.Xs.Length; i++)
        {
            if (ion.Xs[i] >= x0 && ion.Xs[i] <= x1 && ion.Ys[i] > max) max = ion.Ys[i];
        }
        return max > 0 ? max : 1;
    }

    private static string NormalizeElementLabel(string label)
    {
        // “Fe II” / “Fe III” → “Fe”
        var parts = label.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        return parts.Length > 0 ? parts[0] : label;
    }

    private void RenderHover(DrawingContext dc, Rect plot)
    {
        if (!_hovering || _hoverIndex < 0 || _hoverIndex >= _xs.Length) return;
        var x = _xs[_hoverIndex];
        var y = _ys[_hoverIndex];
        if (x < _x0 || x > _x1) return;
        var px = XToPx(x);
        var py = plot.Bottom - (y / Math.Max(1e-12, _yMax)) * plot.Height;

        var dash = new Pen(TextBrush2(), 0.8) { DashStyle = DashStyles.Dash };
        dash.Freeze();
        dc.DrawLine(dash, new Point(px, plot.Top), new Point(px, plot.Bottom));

        var dot = new EllipseGeometry(new Point(px, py), 3.2, 3.2);
        dc.DrawGeometry(AccentCBrush(), null, dot);

        var text = $"λ={x:0.###} nm · I={FormatAxisNumber(y)}";
        var label = Fmt(text, 11.5, TextBrush2(), mono: true);
        var bx = Math.Clamp(px + 10, plot.Left + 2, plot.Right - label.Width - 10);
        var by = Math.Clamp(py - 26, plot.Top + 2, plot.Bottom - 22);
        var bg = (Res("Bg.Popup") ?? Brushes.Black).Clone();
        bg.Opacity = 0.92;
        var rect = new Rect(bx, by, label.Width + 14, label.Height + 8);
        dc.DrawRoundedRectangle(bg, new Pen(Res("Line.Strong"), 1), rect, 6, 6);
        dc.DrawText(label, new Point(bx + 7, by + 4));
    }

    private void RenderAnnotations(DrawingContext dc, double w, Rect plot)
    {
        if (_frameText is { } frame)
        {
            var t = Fmt(frame, 12, TextBrush2(), mono: true);
            dc.DrawText(t, new Point(plot.Right - t.Width, plot.Top - t.Height - 6));
        }
        if (_subtitle is { } sub)
        {
            var t = Fmt(sub, 12, TextBrush2());
            dc.DrawText(t, new Point(plot.Left, plot.Top - t.Height - 6));
        }
        if (_previewBadge)
        {
            var t = Fmt("示意预览 · 非真实数据", 11, TextBrush2());
            var bg = (Res("Bg.Popup") ?? Brushes.Black).Clone();
            bg.Opacity = 0.85;
            var rect = new Rect(plot.Right - t.Width - 16, plot.Top + 8, t.Width + 12, t.Height + 8);
            dc.DrawRoundedRectangle(bg, new Pen(Res("Line.Strong"), 1), rect, 6, 6);
            dc.DrawText(t, new Point(plot.Right - t.Width - 10, plot.Top + 12));
        }
    }

    // ---------------- 视图缓存 ----------------

    private void RebuildCache()
    {
        _columns.Clear();
        if (!_hasData) return;

        var w = Math.Max(1, ActualWidth - ML - MR);
        var cols = (int)Math.Min(w, 4000);
        if (cols < 2) return;

        double x0 = _x0, x1 = _x1;
        var n = _xs.Length;

        var maxY = 0.0;
        for (var i = 0; i < n; i++)
        {
            if (_xs[i] >= x0 && _xs[i] <= x1 && _ys[i] > maxY) maxY = _ys[i];
        }
        _yMax = Math.Max(maxY * 1.08, 1e-12);

        var lo = new double[cols];
        var hi = new double[cols];
        var seen = new bool[cols];

        for (var i = 0; i < n; i++)
        {
            var x = _xs[i];
            if (x < x0 || x > x1) continue;
            var c = (int)((x - x0) / (x1 - x0) * (cols - 1) + 0.5);
            if (c < 0) c = 0;
            if (c >= cols) c = cols - 1;
            var y = _ys[i];
            if (!seen[c]) { lo[c] = y; hi[c] = y; seen[c] = true; }
            else
            {
                if (y < lo[c]) lo[c] = y;
                if (y > hi[c]) hi[c] = y;
            }
        }

        for (var c = 0; c < cols; c++)
        {
            if (!seen[c]) continue;
            _columns.Add((ML + (cols == 1 ? 0 : (double)c / (cols - 1) * w), lo[c], hi[c]));
        }
    }

    private List<(double px, double lo, double hi)> ColumnsFor(double[] xs, double[] ys, Rect plot)
    {
        var list = new List<(double, double, double)>();
        if (xs.Length == 0) return list;
        var w = plot.Width;
        var cols = (int)Math.Min(w, 2000);
        if (cols < 2) return list;
        var lo = new double[cols];
        var hi = new double[cols];
        var seen = new bool[cols];
        for (var i = 0; i < xs.Length; i++)
        {
            if (xs[i] < _x0 || xs[i] > _x1) continue;
            var c = (int)((xs[i] - _x0) / Math.Max(1e-12, _x1 - _x0) * (cols - 1) + 0.5);
            if (c < 0) c = 0;
            if (c >= cols) c = cols - 1;
            if (!seen[c]) { lo[c] = ys[i]; hi[c] = ys[i]; seen[c] = true; }
            else
            {
                if (ys[i] < lo[c]) lo[c] = ys[i];
                if (ys[i] > hi[c]) hi[c] = ys[i];
            }
        }
        for (var c = 0; c < cols; c++)
        {
            if (!seen[c]) continue;
            list.Add((plot.Left + (double)c / (cols - 1) * w, lo[c], hi[c]));
        }
        return list;
    }

    private static (double step, int decimals) NiceStep(double raw)
    {
        if (raw <= 0 || !double.IsFinite(raw)) return (1, 0);
        var mag = Math.Pow(10, Math.Floor(Math.Log10(raw)));
        var norm = raw / mag;
        double step = norm switch
        {
            < 1.5 => 1,
            < 3 => 2,
            < 7 => 5,
            _ => 10,
        };
        step *= mag;
        var dec = 0;
        if (step < 1)
        {
            dec = (int)Math.Ceiling(-Math.Log10(step));
            dec = Math.Clamp(dec, 0, 4);
        }
        return (step, dec);
    }

    private static string FormatAxisNumber(double v)
    {
        var a = Math.Abs(v);
        if (a >= 1e6 || (a < 1e-3 && a > 0))
            return v.ToString("G3", CultureInfo.InvariantCulture);
        return v.ToString("0.###", CultureInfo.InvariantCulture);
    }
}
