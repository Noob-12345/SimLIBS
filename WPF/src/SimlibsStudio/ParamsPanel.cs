using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Text.Json.Nodes;
using SimlibsStudio.Controls;
using static SimlibsStudio.Bridge.JsonExt;

namespace SimlibsStudio;

/// <summary>
/// 共享模拟参数面板（单次 / 批量 / 扫描复用）：
/// 计算方式（local/server/client，v2）· Te/Ne/R 滑块 · 波长范围 · 最大离子电荷 ·
/// 重采样 · 强度尺度 · 离线展宽开关及参数。
/// </summary>
public sealed class ParamsPanel : StackPanel
{
    public Segmented ModeSeg = null!;
    public SmartSlider Te = null!;
    public SmartSlider Ne = null!;
    public SmartSlider R = null!;
    public TextBox LowW = null!;
    public TextBox UpW = null!;
    public Segmented ChargeSeg = null!;
    public CheckBox ResampleCheck = null!;
    public TextBox ResampleStep = null!;
    public Segmented IntensitySeg = null!;
    public CheckBox LocalBroaden = null!;
    public StackPanel LocalBroadenGroup = null!;
    public Segmented TempModeSeg = null!;
    public TextBox TempK = null!;
    public TextBox GaussianNm = null!;
    public TextBox LorentzNm = null!;
    public TextBox MinRelInt = null!;
    public TextBox GridStep = null!;
    public TextBlock ModeNote = null!;

    public string Mode => ModeSeg.SelectedIndex switch { 0 => "local", 1 => "server", _ => "client" };

    public event Action? Changed;

    public ParamsPanel(bool showMode = true, string? note = null)
    {
        Margin = new Thickness(0, 10, 0, 0);

        // —— 计算方式 ——
        ModeSeg = new Segmented();
        ModeSeg.SetItems(new[] { "本地模拟", "服务器计算", "客户端计算" }, 0,
            new[] { "离线谱线库 · LTE/Saha（无需网络）", "NIST 页面数据 + 官方 JS Recalculate（要求 R≥100）",
                    "HTTP 取 NIST 未展宽线表 + Python 高斯核合成（无需浏览器）" });
        ModeSeg.SelectionChanged += _ => { ApplyModeVisibility(); RaiseChanged(); };
        if (showMode)
        {
            Children.Add(new SectionHeader("计算方式（v2）"));
            Children.Add(ModeSeg);
        }
        ModeNote = new TextBlock
        {
            Text = note ?? "",
            FontSize = 11,
            TextWrapping = TextWrapping.Wrap,
            Foreground = (Brush)Application.Current.Resources["Text.Faint"],
            Margin = new Thickness(0, 5, 0, 0),
        };
        Children.Add(ModeNote);

        // —— 物理参数 ——
        Children.Add(new SectionHeader("等离子体参数") { Margin = new Thickness(0, 14, 0, 0) });
        Te = new SmartSlider("电子温度 Te", SmartSlider.ScaleMode.Linear, 0.5, 10, 1.0, 0.05, "eV",
            tooltip: "等离子体电子温度，0.5–10 eV");
        Te.ActualChanged += _ => RaiseChanged();
        Ne = new SmartSlider("电子密度 Ne", SmartSlider.ScaleMode.Expo, 14, 19, 1e17, 0.1, "cm⁻³",
            tooltip: "10^x 指数输入，14–19");
        Ne.ActualChanged += _ => RaiseChanged();
        R = new SmartSlider("仪器分辨率 R", SmartSlider.ScaleMode.Log, 100, 20000, 3000, 50, "",
            snapInteger: true, tooltip: "对数滑块 100–20000；服务器计算要求 ≥100");
        R.ActualChanged += _ => RaiseChanged();
        Children.Add(Te);
        Children.Add(Ne);
        Children.Add(R);

        var chargeRow = new Grid { Margin = new Thickness(0, 2, 0, 8) };
        chargeRow.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        chargeRow.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        chargeRow.Children.Add(new TextBlock
        {
            Text = "最大离子电荷",
            FontSize = 12.5,
            Foreground = (Brush)Application.Current.Resources["Text.Secondary"],
            VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(0, 0, 12, 0),
        });
        ChargeSeg = new Segmented { HorizontalAlignment = HorizontalAlignment.Left };
        ChargeSeg.SetItems(new[] { "0", "I", "II" }, 2, new[] { "仅中性", "含 I", "含 I/II" });
        ChargeSeg.SelectionChanged += _ => RaiseChanged();
        Grid.SetColumn(ChargeSeg, 1);
        chargeRow.Children.Add(ChargeSeg);
        Children.Add(chargeRow);

        // —— 波长范围 ——
        Children.Add(new SectionHeader("波长范围 (nm)") { Margin = new Thickness(0, 6, 0, 0) });
        var wlGrid = new Grid { Margin = new Thickness(0, 8, 0, 0) };
        wlGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        wlGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(14) });
        wlGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        LowW = MakeNumberBox("200");
        UpW = MakeNumberBox("500");
        Grid.SetColumn(LowW, 0);
        Grid.SetColumn(UpW, 2);
        wlGrid.Children.Add(LowW);
        wlGrid.Children.Add(UpW);
        Children.Add(wlGrid);
        var wlHint = new TextBlock
        {
            Text = "0 < 下界 < 上界；点数上限 200,000（范围/步长过大时会被拒绝）",
            FontSize = 10.5,
            Foreground = (Brush)Application.Current.Resources["Text.Faint"],
            Margin = new Thickness(0, 4, 0, 0),
        };
        Children.Add(wlHint);

        // —— 计算细节 ——
        Children.Add(new SectionHeader("计算细节") { Margin = new Thickness(0, 14, 0, 0) });

        var resampleRow = new Grid { Margin = new Thickness(0, 6, 0, 0) };
        resampleRow.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        resampleRow.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        ResampleCheck = new CheckBox
        {
            Style = (Style)Application.Current.Resources["ModCheck"],
            Content = "统一重采样",
        };
        ResampleCheck.Click += (_, _) => { ApplyModeVisibility(); RaiseChanged(); };
        ResampleStep = MakeNumberBox("0.005");
        ResampleStep.Width = 84;
        ResampleStep.Margin = new Thickness(0);
        var stepHost = new StackPanel { Orientation = Orientation.Horizontal };
        stepHost.Children.Add(new TextBlock
        {
            Text = "步长 nm",
            FontSize = 11,
            Foreground = (Brush)Application.Current.Resources["Text.Faint"],
            VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(10, 0, 6, 0),
        });
        stepHost.Children.Add(ResampleStep);
        Grid.SetColumn(ResampleCheck, 0);
        Grid.SetColumn(stepHost, 1);
        resampleRow.Children.Add(ResampleCheck);
        resampleRow.Children.Add(stepHost);
        Children.Add(resampleRow);

        var intensityRow = new Grid { Margin = new Thickness(0, 8, 0, 0) };
        intensityRow.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        intensityRow.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        intensityRow.Children.Add(new TextBlock
        {
            Text = "强度尺度",
            FontSize = 12.5,
            Foreground = (Brush)Application.Current.Resources["Text.Secondary"],
            VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(0, 0, 12, 0),
        });
        IntensitySeg = new Segmented { HorizontalAlignment = HorizontalAlignment.Left };
        IntensitySeg.SetItems(new[] { "Photon（相对光子）", "Energy flux" }, 0);
        IntensitySeg.SelectionChanged += _ => RaiseChanged();
        Grid.SetColumn(IntensitySeg, 1);
        intensityRow.Children.Add(IntensitySeg);
        Children.Add(intensityRow);

        LocalBroaden = new CheckBox
        {
            Style = (Style)Application.Current.Resources["ModCheck"],
            Content = "离线展宽（应用 R / 热多普勒 / 额外宽度；默认关闭 = 未展宽线谱）",
            Margin = new Thickness(0, 10, 0, 0),
        };
        LocalBroaden.Click += (_, _) => { ApplyModeVisibility(); RaiseChanged(); };
        Children.Add(LocalBroaden);

        LocalBroadenGroup = new StackPanel { Margin = new Thickness(18, 6, 0, 0) };
        var tempRow = new Grid();
        tempRow.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        tempRow.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        tempRow.Children.Add(new TextBlock
        {
            Text = "温度模式",
            FontSize = 12.5,
            Foreground = (Brush)Application.Current.Resources["Text.Secondary"],
            VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(0, 0, 12, 0),
        });
        TempModeSeg = new Segmented { HorizontalAlignment = HorizontalAlignment.Left };
        TempModeSeg.SetItems(new[] { "linked（Te 换算）", "manual（独立 K）" }, 0);
        TempModeSeg.SelectionChanged += _ => RaiseChanged();
        Grid.SetColumn(TempModeSeg, 1);
        tempRow.Children.Add(TempModeSeg);
        LocalBroadenGroup.Children.Add(tempRow);

        var fields = new Grid { Margin = new Thickness(0, 8, 0, 0) };
        for (var i = 0; i < 4; i++) fields.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        TempK = MakeNumberBox("0");
        GaussianNm = MakeNumberBox("0");
        LorentzNm = MakeNumberBox("0");
        MinRelInt = MakeNumberBox("0");
        LabelField(fields, 0, TempK, "重粒子温度 K");
        LabelField(fields, 1, GaussianNm, "额外高斯 nm");
        LabelField(fields, 2, LorentzNm, "额外洛伦兹 nm");
        LabelField(fields, 3, MinRelInt, "选线阈值");
        LocalBroadenGroup.Children.Add(fields);

        var gridRow = new Grid { Margin = new Thickness(0, 8, 0, 0) };
        gridRow.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        gridRow.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        GridStep = MakeNumberBox("0.01");
        LabelField(gridRow, 0, GridStep, "展宽/合成网格步长 nm");
        LocalBroadenGroup.Children.Add(gridRow);

        Children.Add(LocalBroadenGroup);

        ApplyModeVisibility();
    }

    private static TextBox MakeNumberBox(string text)
    {
        return new TextBox
        {
            Style = (Style)Application.Current.Resources["FieldBox"],
            Text = text,
            FontFamily = new FontFamily("Consolas"),
            FontSize = 12.5,
            Padding = new Thickness(8, 5, 8, 6),
        };
    }

    private static void LabelField(Grid grid, int col, FrameworkElement field, string label)
    {
        var stack = new StackPanel { Margin = new Thickness(0, 0, 8, 0) };
        stack.Children.Add(new TextBlock
        {
            Text = label,
            FontSize = 10.5,
            Foreground = (Brush)Application.Current.Resources["Text.Faint"],
            Margin = new Thickness(2, 0, 0, 4),
        });
        stack.Children.Add(field);
        Grid.SetColumn(stack, col);
        grid.Children.Add(stack);
    }

    private void RaiseChanged()
    {
        Changed?.Invoke();
    }

    /// <summary>按模式调整可见性（服务器/客户端隐藏本地展宽组等）。</summary>
    public void ApplyModeVisibility()
    {
        var mode = Mode;
        var isLocal = mode == "local";
        LocalBroaden.Visibility = isLocal ? Visibility.Visible : Visibility.Collapsed;
        LocalBroadenGroup.Visibility = isLocal && LocalBroaden.IsChecked == true
            ? Visibility.Visible : Visibility.Collapsed;
        IntensitySeg.IsEnabled = !isLocal;
        Te.IsEnabled = true;
        R.IsEnabled = true;
        // 服务器计算要求 R>=100
        if (mode == "server" && R.Minimum < 100) R.Minimum = 100;
        if (mode != "server" && R.Minimum < 100) R.Minimum = 100;  // 统一 100 起步
        ModeNote.Text = mode switch
        {
            "local" => "本地模拟：离线谱线库 LTE/I-II Saha 相对光子谱，无需网络与浏览器；默认输出未展宽线谱（精确线位/权重竖线）。",
            "server" => "服务器计算：NIST 页面数据 + 浏览器内官方 JS Recalculate，固定 NIST 展宽（w=λ/R），R 必须 ≥ 100，批量须勾选统一重采样。",
            _ => "客户端计算：HTTP 取 NIST 未展宽线表，Python 高斯核在统一目标网格合成（默认步长 0.01），无需浏览器。",
        };
    }

    /// <summary>从 default_params 恢复默认值。</summary>
    public void LoadDefaults(JsonObject defaults)
    {
        var p = defaults.Obj("params");
        if (p is null) return;
        Te.SetActual(p.Dbl("te", 1.0), raiseEvent: false);
        Ne.SetActual(p.Dbl("ne", 1e17), raiseEvent: false);
        R.SetActual(p.Dbl("resolution", 3000), raiseEvent: false);
        LowW.Text = p.Dbl("low_w", 200).ToString("0.##");
        UpW.Text = p.Dbl("up_w", 500).ToString("0.##");
        ChargeSeg.SelectedIndex = Math.Clamp(p.Int("max_ion_charge", 2), 0, 2);
        var mode = p.JStr("mode", "local");
        ModeSeg.SelectedIndex = mode switch { "server" => 1, "client" => 2, _ => 0 };
        LocalBroaden.IsChecked = p.Bool("local_broadening_enabled", false);
        ResampleCheck.IsChecked = p.Bool("resample", false);
        GridStep.Text = p.Dbl("broaden_grid_step", 0.01).ToString("0.###");
        TempModeSeg.SelectedIndex = p.JStr("local_temperature_mode", "linked") == "manual" ? 1 : 0;
        ApplyModeVisibility();
    }

    /// <summary>读取并校验参数；错误抛 FormatException（消息可直接展示）。</summary>
    public JsonObject Collect()
    {
        var mode = Mode;
        if (!double.TryParse(LowW.Text.Trim(), out var low) || !double.TryParse(UpW.Text.Trim(), out var up))
            throw new FormatException("波长范围必须是数字");
        if (!(0 < low && low < up))
            throw new FormatException("波长范围需满足 0 < 下界 < 上界");
        if (!double.TryParse(ResampleStep.Text.Trim(), out var resampleStep) || resampleStep <= 0)
            throw new FormatException("重采样步长必须是 > 0 的数字");
        var resample = ResampleCheck.IsChecked == true;
        if (!double.TryParse(GridStep.Text.Trim(), out var gridStep) || gridStep <= 0)
            throw new FormatException("网格步长必须是 > 0 的数字");
        if (mode == "server" && R.Actual < 100)
            throw new FormatException("服务器计算的官方 JS 重算要求 R ≥ 100");

        var points = (up - low) / (resample ? Math.Min(gridStep, resampleStep) : gridStep) + 1;
        if (points > 200_000)
            throw new FormatException(
                $"预计谱线点数 {points:N0} 超过单谱上限 200,000（缩小波长范围或加大步长）");

        var p = new JsonObject
        {
            ["te"] = Te.Actual,
            ["ne"] = Ne.Actual,
            ["resolution"] = (int)Math.Round(R.Actual),
            ["low_w"] = low,
            ["up_w"] = up,
            ["max_ion_charge"] = ChargeSeg.SelectedIndex,
            ["mode"] = mode,
            ["mode_version"] = 2,
            ["headless"] = true,
            ["resample"] = resample,
            ["broadening"] = mode == "local" ? "local" : "nist",
            ["broaden_convention"] = mode == "local" ? "physics" : "nist",
            ["broaden_grid_step"] = gridStep,
            ["local_temperature_mode"] = TempModeSeg.SelectedIndex == 1 ? "manual" : "linked",
            ["local_broadening_enabled"] = mode == "local" && LocalBroaden.IsChecked == true,
        };
        if (resample) p["resample_step"] = resampleStep;
        if (mode == "local")
        {
            p["intensity_scale"] = "photon";
            p["broaden_min_rel_int"] = ParseNonNegative(MinRelInt.Text, "选线阈值");
            if (LocalBroaden.IsChecked == true)
            {
                p["local_gaussian_nm"] = ParseNonNegative(GaussianNm.Text, "额外高斯宽度");
                p["local_lorentz_nm"] = ParseNonNegative(LorentzNm.Text, "额外洛伦兹宽度");
                var tempK = ParseNonNegative(TempK.Text, "重粒子温度");
                p["local_temperature_K"] = TempModeSeg.SelectedIndex == 1 ? tempK : 0;
            }
            else
            {
                p["local_gaussian_nm"] = 0;
                p["local_lorentz_nm"] = 0;
                p["local_temperature_K"] = 0;
            }
        }
        else
        {
            p["intensity_scale"] = IntensitySeg.SelectedIndex == 1 ? "energy" : "photon";
        }
        return p;
    }

    private static double ParseNonNegative(string text, string name)
    {
        if (!double.TryParse(text.Trim(), out var v) || v < 0)
            throw new FormatException($"{name}必须是 ≥ 0 的数字");
        return v;
    }
}
