using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;

namespace SimlibsStudio.Controls;

/// <summary>
/// 滑块 + 数字输入双向同步（与 Qt 版约定一致）：
/// Linear = 线性直输；Log = 滑块按 log10 走、输入实际值；Expo = 滑块/输入均为 10^ 指数。
/// <see cref="Actual"/> 始终是请求协议需要的物理值（Expo 模式下为 10^指数）。
/// </summary>
public sealed class SmartSlider : Grid
{
    public enum ScaleMode { Linear, Log, Expo }

    private readonly Slider _slider;
    private readonly TextBox _box;
    private readonly TextBlock _hint;
    private readonly TextBlock _title;
    private bool _syncing;

    public event Action<double>? ActualChanged;

    public ScaleMode Mode { get; set; } = ScaleMode.Linear;
    public double Minimum { get; set; } = 0;
    public double Maximum { get; set; } = 100;
    public double Step { get; set; } = 0.01;
    public bool SnapInteger { get; set; }
    public string Unit { get; set; } = "";

    public SmartSlider(string title, ScaleMode mode, double min, double max, double initial,
        double step, string unit = "", bool snapInteger = false, string? tooltip = null)
    {
        Mode = mode;
        Minimum = min;
        Maximum = max;
        Step = step;
        Unit = unit;
        SnapInteger = snapInteger;
        Margin = new Thickness(0, 2, 0, 6);

        RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

        _title = new TextBlock
        {
            Text = title,
            FontSize = 12.5,
            Foreground = (Brush)Application.Current.Resources["Text.Secondary"],
            VerticalAlignment = VerticalAlignment.Center,
            ToolTip = tooltip,
        };
        _box = new TextBox
        {
            Style = (Style)Application.Current.Resources["FieldBox"],
            Width = 96,
            FontSize = 12.5,
            FontFamily = new FontFamily("Consolas"),
            Padding = new Thickness(7, 4, 7, 5),
            HorizontalAlignment = HorizontalAlignment.Right,
        };
        _box.LostFocus += (_, _) => CommitBox();
        _box.KeyDown += (_, e) =>
        {
            if (e.Key == Key.Enter) CommitBox();
        };

        SetRow(_title, 0);
        SetRow(_box, 0);
        SetColumn(_title, 0);
        SetColumn(_box, 1);
        ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        Children.Add(_title);
        Children.Add(_box);

        _slider = new Slider
        {
            Style = (Style)Application.Current.Resources["ModSlider"],
            IsSnapToTickEnabled = false,
            Margin = new Thickness(0, 6, 0, 0),
        };
        _slider.ValueChanged += (_, _) => SliderMoved();
        SetRow(_slider, 1);
        Children.Add(_slider);

        _hint = new TextBlock
        {
            FontSize = 11,
            FontFamily = new FontFamily("Consolas"),
            Foreground = (Brush)Application.Current.Resources["Text.Faint"],
            HorizontalAlignment = HorizontalAlignment.Right,
            Margin = new Thickness(0, 3, 2, 0),
        };
        SetRow(_hint, 2);
        Children.Add(_hint);

        SetActual(initial, raiseEvent: false);
    }

    public double Actual { get; private set; }

    public void SetActual(double value, bool raiseEvent = true)
    {
        value = Clamp(value);
        if (SnapInteger) value = Math.Round(value);
        Actual = value;
        _syncing = true;
        try
        {
            _slider.Minimum = SliderMin();
            _slider.Maximum = SliderMax();
            _slider.SmallChange = Step;
            _slider.LargeChange = Step * 10;
            _slider.Value = ActualToSlider(value);
            _box.Text = BoxText(value);
            _hint.Text = HintText();
        }
        finally
        {
            _syncing = false;
        }
        if (raiseEvent) ActualChanged?.Invoke(value);
    }

    public new bool IsEnabled
    {
        get => _slider.IsEnabled;
        set
        {
            _slider.IsEnabled = value;
            _box.IsEnabled = value;
            _title.Opacity = value ? 1 : 0.45;
            _hint.Opacity = value ? 1 : 0.45;
        }
    }

    private double Clamp(double v) => Mode switch
    {
        // Expo 模式：Minimum/Maximum 是指数边界，Actual 是 10^指数
        ScaleMode.Expo => Math.Pow(10, Math.Clamp(Math.Log10(Math.Max(1e-12, v)), Minimum, Maximum)),
        _ => Math.Clamp(v, Minimum, Maximum),
    };

    private double SliderMin() => Mode switch
    {
        ScaleMode.Log => Math.Log10(Minimum),
        _ => Minimum,   // Linear / Expo：滑块空间 = 线性值（Expo = 指数）
    };

    private double SliderMax() => Mode switch
    {
        ScaleMode.Log => Math.Log10(Maximum),
        _ => Maximum,
    };

    private double ActualToSlider(double v) => Mode switch
    {
        ScaleMode.Log => Math.Log10(Math.Max(1e-12, v)),
        ScaleMode.Expo => Math.Log10(Math.Max(1e-12, v)),  // 滑块位置 = 指数
        _ => v,
    };

    private double SliderToActual(double pos) => Mode switch
    {
        ScaleMode.Log => Math.Pow(10, pos),
        ScaleMode.Expo => Math.Pow(10, pos),
        _ => pos,
    };

    private string BoxText(double v) => Mode switch
    {
        ScaleMode.Expo => Math.Log10(Math.Max(1e-12, v)).ToString("0.##"),
        ScaleMode.Log => SnapInteger ? Math.Round(v).ToString() : v.ToString("0.###"),
        _ => SnapInteger ? Math.Round(v).ToString() : v.ToString("0.##"),
    };

    private string HintText()
    {
        if (Mode == ScaleMode.Expo)
        {
            // Actual 即物理值（10^指数）；指数 = log10(Actual)
            var exp = Math.Log10(Math.Max(1e-12, Actual));
            return $"10^{exp:0.##} = {FormatSci(Actual)} {(Unit.Length > 0 ? Unit : "")}".TrimEnd();
        }
        if (Mode == ScaleMode.Log)
        {
            return $"log₁₀={Math.Log10(Math.Max(1e-12, Actual)):0.##} {(Unit.Length > 0 ? Unit : "")}".TrimEnd();
        }
        return "";
    }

    internal static string FormatSci(double v)
    {
        if (v == 0) return "0";
        var exp = Math.Floor(Math.Log10(Math.Abs(v)));
        var mant = v / Math.Pow(10, exp);
        if (exp is >= -2 and <= 3) return v.ToString("0.###");
        return $"{mant:0.###}×10{Sup(exp)}";
    }

    private static string Sup(double v)
    {
        var s = v.ToString("0");
        return string.Concat(s.Select(c => c switch
        {
            '-' => "⁻",
            '0' => "⁰",
            '1' => "¹",
            '2' => "²",
            '3' => "³",
            '4' => "⁴",
            '5' => "⁵",
            '6' => "⁶",
            '7' => "⁷",
            '8' => "⁸",
            '9' => "⁹",
            _ => c.ToString(),
        }));
    }

    private void SliderMoved()
    {
        if (_syncing) return;
        var value = Clamp(SliderToActual(_slider.Value));
        if (SnapInteger) value = Math.Round(value);
        Actual = value;
        _syncing = true;
        try
        {
            _box.Text = BoxText(value);
            _hint.Text = HintText();
        }
        finally
        {
            _syncing = false;
        }
        ActualChanged?.Invoke(value);
    }

    private void CommitBox()
    {
        if (_syncing) return;
        if (!double.TryParse(_box.Text.Trim(), out var v))
        {
            _box.Text = BoxText(Actual);
            return;
        }
        // Expo 模式：输入的是 10^ 指数
        SetActual(Mode == ScaleMode.Expo ? Math.Pow(10, v) : v);
    }
}
