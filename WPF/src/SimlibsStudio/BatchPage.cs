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

/// <summary>
/// 批量模拟页：三种生成方式（组成池 / 随机规则 / CSV 模板，与 Web 同协议）→
/// 样本结果表 + 数据集/训练包/实际参数/模板 四种导出。
/// </summary>
public sealed class BatchPage : PageBase
{
    private readonly Segmented _genSeg = new();
    private readonly CompositionEditor _poolComp = new(allowBlocks: true);
    private readonly StackPanel _poolPanel;
    private readonly StackPanel _randomPanel;
    private readonly StackPanel _templatePanel;

    // 随机规则
    private readonly CheckBox _teEnable = MakeCheck("随机化 Te");
    private readonly TextBox _teMin = MakeBox("0.8");
    private readonly TextBox _teMax = MakeBox("1.4");
    private readonly CheckBox _neEnable = MakeCheck("随机化 Ne");
    private readonly TextBox _neMin = MakeBox("16");
    private readonly TextBox _neMax = MakeBox("18.5");
    private readonly TextBox _poolTeMin = MakeBox("1.0");
    private readonly TextBox _poolTeMax = MakeBox("1.0");
    private readonly TextBox _poolNeMin = MakeBox("17");
    private readonly TextBox _poolNeMax = MakeBox("17");
    private readonly StackPanel _concRows = new();
    private readonly TextBox _seedBox = MakeBox("7");

    // 模板
    private readonly TextBox _templatePath = MakeBox("");
    private readonly TextBox _templateRepeats = MakeBox("1");
    private readonly TextBox _templateNameCol = MakeBox("name");

    // 公共
    private readonly ParamsPanel _params = new();
    private readonly TextBox _nSamples = MakeBox("24");
    private readonly TextBox _batchSize = MakeBox("32");
    private readonly Button _runBtn;
    private readonly Button _cancelBtn;
    private readonly ProgressBar _progress = new() { Height = 4, Minimum = 0, Maximum = 100 };
    private readonly TextBlock _statusText = new()
    {
        FontSize = 11.5,
        Foreground = (Brush)Application.Current.Resources["Text.Secondary"],
        TextTrimming = TextTrimming.CharacterEllipsis,
    };

    // 结果区
    private readonly WrapPanel _summaryChips = new() { Margin = new Thickness(0, 0, 0, 10) };
    private readonly StackPanel _samplesPanel = new();
    private readonly TextBlock _wideNote = new()
    {
        FontSize = 11,
        Foreground = (Brush)Application.Current.Resources["Text.Faint"],
        TextWrapping = TextWrapping.Wrap,
        Margin = new Thickness(0, 10, 0, 0),
    };
    private readonly Button _btnDataset;
    private readonly Button _btnTraining;
    private readonly Button _btnParams;
    private readonly Button _btnTemplate;

    private string? _jobId;
    private BatchResult? _result;
    private bool _running;

    public BatchPage()
    {
        _poolPanel = BuildPoolPanel();
        _randomPanel = BuildRandomPanel();
        _templatePanel = BuildTemplatePanel();
        _runBtn = MakeButton("▶  运行批量", "BtnPrimary", FontWeights.Bold, RunAsync);
        _cancelBtn = MakeButton("取消", "BtnDanger", FontWeights.Normal, CancelAsync);
        _cancelBtn.Visibility = Visibility.Collapsed;
        _btnDataset = MakeGhost("数据集 CSV", () => ExportAsync("dataset"));
        _btnTraining = MakeGhost("训练包 ZIP", () => ExportAsync("training"));
        _btnParams = MakeGhost("实际参数 CSV", () => ExportAsync("parameters"));
        _btnTemplate = MakeGhost("模板 CSV", () => ExportAsync("template"));
        Content = BuildLayout();
        _genSeg.SelectionChanged += _ => ApplyGenVisibility();
        AppState.JobEvent += OnJobEvent;
        ApplyGenVisibility();
    }

    // ---------------- 左栏构建 ----------------

    private UIElement BuildLayout()
    {
        var grid = new Grid();
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(388) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(18) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

        var leftCard = new Border { Style = (Style)Application.Current.Resources["Card"] };
        var leftScroll = new ScrollViewer { VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Padding = new Thickness(2) };
        var left = new StackPanel();

        left.Children.Add(new SectionHeader("生成方式"));
        _genSeg.SetItems(new[] { "组成池", "随机规则", "CSV 模板" }, 0, new[]
        {
            "候选组成池随机选行 + 均匀 Te/Ne",
            "Te/Ne 边界 + 逐元素浓度上下界（有界顺序分配，种子确定）",
            "严格按模板 CSV 行执行（行内参数列可覆盖基础参数）",
        });
        left.Children.Add(_genSeg);

        _poolPanel.Margin = new Thickness(0, 12, 0, 0);
        _randomPanel.Margin = new Thickness(0, 12, 0, 0);
        _templatePanel.Margin = new Thickness(0, 12, 0, 0);
        left.Children.Add(_poolPanel);
        left.Children.Add(_randomPanel);
        left.Children.Add(_templatePanel);

        left.Children.Add(_params);

        var commonGrid = new Grid { Margin = new Thickness(0, 14, 0, 0) };
        commonGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        commonGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(10) });
        commonGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        commonGrid.Children.Add(Labeled(_nSamples, "样本数（1–5000）", 0));
        commonGrid.Children.Add(Labeled(_batchSize, "每包样本数（随请求下发）", 2));
        left.Children.Add(commonGrid);
        _seedBox.Margin = new Thickness(0, 8, 0, 0);
        left.Children.Add(Labeled(_seedBox, "随机种子（种子确定，可复跑续跑）", -1));

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

        // —— 右：结果 ——
        var rightCard = new Border { Style = (Style)Application.Current.Resources["Card"] };
        var rightScroll = new ScrollViewer { VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Padding = new Thickness(2) };
        var right = new StackPanel();

        var exportRow = new StackPanel { Orientation = Orientation.Horizontal };
        exportRow.Children.Add(MakeGhost("刷新样本表", () => ReloadAsync()));
        exportRow.Children.Add(_btnDataset);
        exportRow.Children.Add(_btnTraining);
        exportRow.Children.Add(_btnParams);
        exportRow.Children.Add(_btnTemplate);
        right.Children.Add(exportRow);

        right.Children.Add(_summaryChips);
        right.Children.Add(new SectionHeader("样本预览（前 12 行）") { Margin = new Thickness(0, 6, 0, 0) });
        right.Children.Add(_samplesPanel);
        right.Children.Add(_wideNote);
        var empty = new TextBlock
        {
            Text = "尚未运行批量任务。\n运行后此处显示样本参数预览与宽表首尾，完整数据经导出获取。",
            FontSize = 12,
            Foreground = (Brush)Application.Current.Resources["Text.Faint"],
            Margin = new Thickness(0, 26, 0, 0),
            TextAlignment = TextAlignment.Center,
            Name = "BatchEmpty",
        };
        right.Children.Add(empty);
        _batchEmpty = empty;

        rightScroll.Content = right;
        rightCard.Child = rightScroll;
        Grid.SetColumn(rightCard, 2);
        grid.Children.Add(rightCard);
        return grid;
    }

    private TextBlock _batchEmpty;

    private StackPanel BuildPoolPanel()
    {
        var panel = new StackPanel();
        var actions = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 0, 2) };
        actions.Children.Add(MakeGhost("导入组成 CSV", ImportPoolCsv));
        actions.Children.Add(MakeGhost("用当前配比", UseCurrentComposition));
        panel.Children.Add(actions);
        panel.Children.Add(_poolComp);
        panel.Children.Add(new TextBlock
        {
            Text = "每个组成块总和须为 100%（「＋新组成」分块为多候选池，随机选行）；CSV 支持 name / 元素符号 / *_at% 列映射",
            FontSize = 10.5,
            Foreground = (Brush)Application.Current.Resources["Text.Faint"],
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(0, 2, 0, 0),
        });
        panel.Children.Add(BuildTeNeRange());
        return panel;
    }

    private UIElement BuildTeNeRange()
    {
        var grid = new Grid { Margin = new Thickness(0, 8, 0, 0) };
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(10) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        grid.Children.Add(Labeled(_poolTeMin, "Te 下界 eV", 0));
        grid.Children.Add(Labeled(_poolTeMax, "Te 上界 eV", 2));
        var grid2 = new Grid { Margin = new Thickness(0, 8, 0, 0) };
        grid2.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        grid2.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(10) });
        grid2.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        grid2.Children.Add(Labeled(_poolNeMin, "Ne 10^x 下界", 0));
        grid2.Children.Add(Labeled(_poolNeMax, "Ne 10^x 上界", 2));
        var stack = new StackPanel();
        stack.Children.Add(grid);
        stack.Children.Add(grid2);
        stack.Children.Add(new TextBlock
        {
            Text = "组成池模式：样本 Te/Ne 在此区间均匀取值（上下界可相等 = 固定值）",
            FontSize = 10.5,
            Foreground = (Brush)Application.Current.Resources["Text.Faint"],
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(0, 4, 0, 0),
        });
        return stack;
    }

    private StackPanel BuildRandomPanel()
    {
        var panel = new StackPanel();
        var teGrid = new Grid();
        teGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        teGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        teGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(76) });
        teGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(76) });
        _teMin.Margin = new Thickness(8, 0, 4, 0);
        _teMax.Margin = new Thickness(0);
        Grid.SetColumn(_teEnable, 0);
        Grid.SetColumn(_teMin, 2);
        Grid.SetColumn(_teMax, 3);
        teGrid.Children.Add(_teEnable);
        teGrid.Children.Add(_teMin);
        teGrid.Children.Add(_teMax);
        panel.Children.Add(teGrid);

        var neGrid = new Grid { Margin = new Thickness(0, 8, 0, 0) };
        neGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        neGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        neGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(76) });
        neGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(76) });
        _neMin.Margin = new Thickness(8, 0, 4, 0);
        Grid.SetColumn(_neEnable, 0);
        Grid.SetColumn(_neMin, 2);
        Grid.SetColumn(_neMax, 3);
        neGrid.Children.Add(_neEnable);
        neGrid.Children.Add(_neMin);
        neGrid.Children.Add(_neMax);
        panel.Children.Add(neGrid);
        panel.Children.Add(new TextBlock
        {
            Text = "Te 为 eV 实际值；Ne 为 10^x 指数。不勾选 = 用基础参数固定值。",
            FontSize = 10.5,
            Foreground = (Brush)Application.Current.Resources["Text.Faint"],
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(0, 4, 0, 0),
        });

        panel.Children.Add(new SectionHeader("逐元素浓度") { Margin = new Thickness(0, 12, 0, 0) });
        panel.Children.Add(_concRows);
        panel.Children.Add(MakeGhost("从配比同步元素", SyncConcRows));
        panel.Children.Add(new TextBlock
        {
            Text = "勾选 = 该元素在 [min,max] 内随机；不勾选 = 固定值（浓度）。有界顺序分配保证总和恒 100%。",
            FontSize = 10.5,
            Foreground = (Brush)Application.Current.Resources["Text.Faint"],
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(0, 6, 0, 0),
        });
        SyncConcRows();
        return panel;
    }

    private void SyncConcRows()
    {
        _concRows.Children.Clear();
        try
        {
            var rows = _poolComp.Collect();     // 复用组成池元素列表（不校验总和时用宽松读取）
            foreach (var (el, _) in rows)
            {
                _concRows.Children.Add(ConcRow(el));
            }
        }
        catch (FormatException)
        {
            foreach (var (el, _) in ReadPoolLoose())
            {
                _concRows.Children.Add(ConcRow(el));
            }
        }
        if (_concRows.Children.Count == 0)
        {
            _concRows.Children.Add(ConcRow("Fe"));
        }
    }

    private (string el, double pct)[] ReadPoolLoose()
    {
        var list = new List<(string, double)>();
        foreach (var row in _poolComp.CollectRows())
        {
            list.Add(row);
        }
        return list.ToArray();
    }

    private UIElement ConcRow(string el)
    {
        var grid = new Grid { Margin = new Thickness(0, 0, 0, 6) };
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(56) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(62) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(62) });
        grid.Children.Add(new TextBlock
        {
            Text = el,
            FontFamily = new FontFamily("Consolas"),
            FontSize = 13,
            FontWeight = FontWeights.SemiBold,
            VerticalAlignment = VerticalAlignment.Center,
        });
        var enable = MakeCheck("随机");
        Grid.SetColumn(enable, 1);
        enable.Margin = new Thickness(8, 0, 10, 0);
        enable.Click += (_, _) => UpdateConcRowState(grid);
        var minBox = MakeBox("40");
        var maxBox = MakeBox("60");
        minBox.Margin = new Thickness(0, 0, 4, 0);
        Grid.SetColumn(minBox, 3);
        Grid.SetColumn(maxBox, 4);
        grid.Children.Add(enable);
        grid.Children.Add(minBox);
        grid.Children.Add(maxBox);
        UpdateConcRowState(grid);
        return grid;
    }

    private static void UpdateConcRowState(Grid row)
    {
        var enable = row.Children.OfType<CheckBox>().First();
        var boxes = row.Children.OfType<TextBox>().ToList();
        var active = enable.IsChecked == true;
        foreach (var b in boxes) b.IsEnabled = active;
    }

    private StackPanel BuildTemplatePanel()
    {
        var panel = new StackPanel();
        var pickRow = new Grid();
        pickRow.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        pickRow.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        Grid.SetColumn(_templatePath, 0);
        var pick = MakeGhost("浏览…", PickTemplateCsv);
        pick.Margin = new Thickness(8, 0, 0, 0);
        Grid.SetColumn(pick, 1);
        pickRow.Children.Add(_templatePath);
        pickRow.Children.Add(pick);
        panel.Children.Add(pickRow);

        var optGrid = new Grid { Margin = new Thickness(0, 8, 0, 0) };
        optGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        optGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(10) });
        optGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        optGrid.Children.Add(Labeled(_templateRepeats, "每行重复次数", 0));
        optGrid.Children.Add(Labeled(_templateNameCol, "名称列", 2));
        panel.Children.Add(optGrid);

        panel.Children.Add(new TextBlock
        {
            Text = "模板列：name + 元素符号列（组成，可自动归一）+ Te/Ne/resolution/low_w/up_w/mode 等参数列可覆盖基础参数；样本数 = 行数 × 重复。",
            FontSize = 10.5,
            Foreground = (Brush)Application.Current.Resources["Text.Faint"],
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(0, 6, 0, 0),
        });
        return panel;
    }

    private static FrameworkElement Labeled(Control field, string label, int col)
    {
        var stack = new StackPanel();
        stack.Children.Add(new TextBlock
        {
            Text = label,
            FontSize = 10.5,
            Foreground = (Brush)Application.Current.Resources["Text.Faint"],
            Margin = new Thickness(2, 0, 0, 4),
        });
        stack.Children.Add(field);
        if (col >= 0) Grid.SetColumn(stack, col);
        return stack;
    }

    private static CheckBox MakeCheck(string text)
    {
        return new CheckBox
        {
            Style = (Style)Application.Current.Resources["ModCheck"],
            Content = text,
            VerticalContentAlignment = VerticalAlignment.Center,
        };
    }

    private static TextBox MakeBox(string text)
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

    public override void OnBridgeReady()
    {
        _params.LoadDefaults(AppState.DefaultParams);
    }

    public override void OnThemeChanged() { /* 文本页，无需处理 */ }

    private void ApplyGenVisibility()
    {
        _poolPanel.Visibility = _genSeg.SelectedIndex == 0 ? Visibility.Visible : Visibility.Collapsed;
        _randomPanel.Visibility = _genSeg.SelectedIndex == 1 ? Visibility.Visible : Visibility.Collapsed;
        _templatePanel.Visibility = _genSeg.SelectedIndex == 2 ? Visibility.Visible : Visibility.Collapsed;
    }

    // ---------------- 组成池辅助 ----------------

    private void UseCurrentComposition()
    {
        if (AppState.Window is MainWindow win && win.TryGetPage<SinglePage>("single", out var page))
        {
            try
            {
                _poolComp.SetRows(page.CurrentComposition());
                AppState.Toast.Show("已载入单次模拟页的当前配比", "ok", "组成池");
            }
            catch (FormatException exc)
            {
                AppState.Toast.Show(exc.Message, "warn", "单次页配比未就绪");
            }
        }
    }

    private void ImportPoolCsv()
    {
        var dlg = new OpenFileDialog { Filter = "CSV 数据|*.csv|全部文件|*.*", Title = "导入组成池 CSV" };
        if (dlg.ShowDialog() != true) return;
        try
        {
            var rows = ParsePoolCsv(dlg.FileName);
            if (rows.Count == 0) throw new FormatException("未从 CSV 解析到有效组成行");
            _poolComp.SetRows(rows[0]);
            // 多行组成池：附加行
            foreach (var row in rows.Skip(1))
            {
                _poolComp.AddPoolRow(row);
            }
            AppState.Toast.Show($"已导入 {rows.Count} 行组成池", "ok", "组成池");
        }
        catch (Exception exc) when (exc is FormatException or IOException)
        {
            AppState.Toast.Show(exc.Message, "error", "导入 CSV");
        }
    }

    private List<(string el, double pct)[]> ParsePoolCsv(string path)
    {
        var lines = File.ReadAllLines(path);
        if (lines.Length < 2) throw new FormatException("CSV 至少需要表头 + 1 行数据");
        var header = SplitCsvLine(lines[0]);
        var nameIdx = -1;
        var elementIdx = new List<(int idx, string el)>();
        for (var i = 0; i < header.Length; i++)
        {
            var col = header[i].Trim();
            if (col.Equals("name", StringComparison.OrdinalIgnoreCase)) nameIdx = i;
            var el = col;
            if (el.EndsWith("_at%", StringComparison.OrdinalIgnoreCase))
                el = el[..^4];
            if (AppState.Elements.Contains(el) && col is not ("wavelength" or "intensity" or "Wavelength (nm)"))
            {
                elementIdx.Add((i, el));
            }
        }
        if (elementIdx.Count == 0)
            throw new FormatException("未找到元素组成列（元素符号列或 *_at% 列）");

        var result = new List<(string, double)[]>();
        for (var r = 1; r < lines.Length; r++)
        {
            if (lines[r].Trim().Length == 0) continue;
            var cells = SplitCsvLine(lines[r]);
            var row = new List<(string, double)>();
            foreach (var (idx, el) in elementIdx)
            {
                if (idx < cells.Length && double.TryParse(cells[idx].Trim(), out var pct))
                    row.Add((el, pct));
            }
            if (row.Count > 0) result.Add(row.ToArray());
        }
        return result;
    }

    private static string[] SplitCsvLine(string line)
    {
        var cells = new List<string>();
        var current = new System.Text.StringBuilder();
        var inQuote = false;
        foreach (var ch in line)
        {
            if (ch == '"') inQuote = !inQuote;
            else if (ch == ',' && !inQuote)
            {
                cells.Add(current.ToString());
                current.Clear();
            }
            else current.Append(ch);
        }
        cells.Add(current.ToString());
        return cells.ToArray();
    }

    private void PickTemplateCsv()
    {
        var dlg = new OpenFileDialog { Filter = "CSV 数据|*.csv|全部文件|*.*", Title = "选择模板 CSV" };
        if (dlg.ShowDialog() == true) _templatePath.Text = dlg.FileName;
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

        var parameters = _params.Collect();
        if (!int.TryParse(_nSamples.Text.Trim(), out var nSamples) || nSamples is < 1 or > 5000)
            throw new FormatException("样本数必须是 1–5000 的整数");
        if (!int.TryParse(_batchSize.Text.Trim(), out var batchSize) || batchSize is < 1 or > 5000)
            throw new FormatException("每包样本数必须是 1–5000 的整数");
        if (!int.TryParse(_seedBox.Text.Trim(), out var seed) || seed < 0)
            throw new FormatException("种子必须是非负整数");
        // te/ne 范围：组成池用池面板输入框；随机规则用规则输入框
        var teMinBox = _genSeg.SelectedIndex == 0 ? _poolTeMin : _teMin;
        var teMaxBox = _genSeg.SelectedIndex == 0 ? _poolTeMax : _teMax;
        var neMinBox = _genSeg.SelectedIndex == 0 ? _poolNeMin : _neMin;
        var neMaxBox = _genSeg.SelectedIndex == 0 ? _poolNeMax : _neMax;
        if (!double.TryParse(teMinBox.Text.Trim(), out var teMin) ||
            !double.TryParse(teMaxBox.Text.Trim(), out var teMax) || teMin > teMax)
            throw new FormatException("Te 范围 min 不能大于 max");
        if (!double.TryParse(neMinBox.Text.Trim(), out var neMinExp) ||
            !double.TryParse(neMaxBox.Text.Trim(), out var neMaxExp) || neMinExp > neMaxExp)
            throw new FormatException("Ne 指数范围 min 不能大于 max");
        var teRange = new JsonArray { teMin, teMax };
        var neRange = new JsonArray { neMinExp, neMaxExp };

        var body = new JsonObject
        {
            ["params"] = parameters,
            ["n_samples"] = nSamples,
            ["seed"] = seed,
            ["batch_size"] = batchSize,
            ["te_range"] = teRange,
            ["ne_range"] = neRange,
        };

        switch (_genSeg.SelectedIndex)
        {
            case 0:
            {
                // 组成池：每行 100% 校验
                var rows = _poolComp.CollectPool();
                body["compositions"] = new JsonArray(rows.Select(r =>
                    (JsonNode)new JsonObject
                    {
                        ["name"] = r.Name,
                        ["items"] = new JsonArray(r.Items.Select(i =>
                            (JsonNode)new JsonObject { ["el"] = i.el, ["pct"] = i.pct }).ToArray()),
                    }).ToArray());
                break;
            }
            case 1:
            {
                var rule = new JsonObject { ["kind"] = "random" };
                rule["te"] = new JsonObject
                {
                    ["enabled"] = _teEnable.IsChecked == true,
                    ["min"] = teMin,
                    ["max"] = teMax,
                };
                rule["ne"] = new JsonObject
                {
                    ["enabled"] = _neEnable.IsChecked == true,
                    ["min"] = Math.Pow(10, neMinExp),
                    ["max"] = Math.Pow(10, neMaxExp),
                };
                var concs = new JsonArray();
                foreach (var child in _concRows.Children)
                {
                    if (child is not Grid g) continue;
                    var el = g.Children.OfType<TextBlock>().First().Text;
                    var enable = g.Children.OfType<CheckBox>().First();
                    var boxes = g.Children.OfType<TextBox>().ToList();
                    if (!double.TryParse(boxes[0].Text.Trim(), out var lo) ||
                        !double.TryParse(boxes[1].Text.Trim(), out var hi) ||
                        lo < 0 || hi > 100 || lo > hi)
                        throw new FormatException($"{el} 浓度边界须为 0–100 且 min ≤ max");
                    concs.Add(new JsonObject
                    {
                        ["el"] = el,
                        ["enabled"] = enable.IsChecked == true,
                        ["min"] = lo,
                        ["max"] = hi,
                    });
                }
                rule["concentrations"] = concs;
                body["generation"] = rule;
                break;
            }
            default:
            {
                var path = _templatePath.Text.Trim();
                if (path.Length == 0 || !File.Exists(path))
                    throw new FormatException("请先选择模板 CSV 文件");
                if (!int.TryParse(_templateRepeats.Text.Trim(), out var repeats) || repeats < 1)
                    throw new FormatException("每行重复次数须 ≥ 1");
                body["template_csv"] = File.ReadAllText(path);
                body["repeats"] = repeats;
                body["name_column"] = _templateNameCol.Text.Trim().Length > 0
                    ? _templateNameCol.Text.Trim() : "name";
                break;
            }
        }

        // 服务器/客户端的 NIST 展宽批量要求统一重采样（与后端同规则的前端提示）
        var mode = parameters.JStr("mode");
        if (mode is "server" or "client" && parameters.Bool("resample") == false)
            throw new FormatException("服务器/客户端计算的批量须勾选「统一重采样」");

        var reply = await AppState.Bridge.SendAsync("start_batch", body);
        _jobId = reply.JStr("job_id");
        await AppState.Bridge.SendAsync("subscribe", new JsonObject { ["job_id"] = _jobId });
        SetRunning(true, $"批量任务已提交 · {nSamples} 样本");
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
                SetRunning(false, "批量完成");
                AppState.RunBg(async () => await LoadBatchAsync(), "载入批量结果");
            }
            else
            {
                SetRunning(false, $"任务{SinglePage.EvStatusText(ev.Status)} · 已完成样本保留");
                AppState.Toast.Show(ev.Message.Length > 0 ? ev.Message : "任务未完成", "error", "批量模拟");
            }
        }
    }

    private async Task ReloadAsync()
    {
        if (_jobId is not null) await LoadBatchAsync();
    }

    private async Task LoadBatchAsync()
    {
        if (_jobId is null) return;
        var reply = await AppState.Bridge.SendAsync("get_result",
            new JsonObject { ["job_id"] = _jobId }, timeoutMs: 240_000);
        var result = BatchResult.Parse(reply);
        _result = result;
        RenderBatch(result);
    }

    private void RenderBatch(BatchResult r)
    {
        _batchEmpty.Visibility = Visibility.Collapsed;
        _summaryChips.Children.Clear();
        void AddChip(string text, string? color = null)
        {
            _summaryChips.Children.Add(new Chip(text,
                color is null ? null : (Brush)Application.Current.Resources[color]));
        }
        AddChip($"完成 {r.Completed}/{r.Total}", r.Partial ? "State.Warn" : "State.Ok");
        if (r.Failed > 0) AddChip($"失败 {r.Failed}", "State.Error");
        if (r.Partial) AddChip("部分完成（已完成样本保留，可续跑）", "State.Warn");
        if (r.IntensityScale.Length > 0) AddChip($"强度 · {r.IntensityScale}");
        AddChip(r.TrainingAvailable
            ? "训练包已生成"
            : "无完整训练包（" + (r.TrainingReason.Length > 0 ? r.TrainingReason : "部分完成") + "）",
            r.TrainingAvailable ? "State.Ok" : "State.Warn");

        _btnDataset.IsEnabled = _jobId is not null;
        _btnTraining.IsEnabled = r.TrainingAvailable;
        _btnParams.IsEnabled = r.ParamsAvailable;
        _btnTemplate.IsEnabled = r.TemplateAvailable;

        // 样本表（自绘表头）
        _samplesPanel.Children.Clear();
        if (r.Samples.Count > 0)
        {
            _samplesPanel.Children.Add(SampleHeaderRow());
            for (var i = 0; i < r.Samples.Count; i++)
            {
                var s = r.Samples[i];
                var row = SampleRow(
                    $"{i + 1,2}",
                    s.Name,
                    $"{s.Te:0.###}",
                    SmartSlider.FormatSci(s.Ne),
                    s.Composition);
                if (i % 2 == 1) row.Background = (Brush)Application.Current.Resources["Bg.RowAlt"];
                _samplesPanel.Children.Add(row);
            }
        }
        _wideNote.Text = r.WideCols.Count > 0
            ? r.WideNote + "\n宽表首列：" + string.Join(" | ", r.WideCols)
            : "";
    }

    private static Border SampleHeaderRow()
    {
        var grid = SampleGrid("#", "样本", "Te eV", "Ne cm⁻³", "组成");
        return new Border
        {
            Child = grid,
            Padding = new Thickness(10, 6, 10, 6),
            BorderBrush = (Brush)Application.Current.Resources["Line.Subtle"],
            BorderThickness = new Thickness(0, 0, 0, 1),
        };
    }

    private static Border SampleRow(string idx, string name, string te, string ne, string comp)
    {
        var grid = SampleGrid(idx, name, te, ne, comp);
        return new Border { Child = grid, Padding = new Thickness(10, 6, 10, 7), CornerRadius = new CornerRadius(6) };
    }

    private static Grid SampleGrid(string c1, string c2, string c3, string c4, string c5)
    {
        var grid = new Grid();
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(30) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(96) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(64) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(96) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        Add(grid, 0, c1);
        Add(grid, 1, c2);
        Add(grid, 2, c3);
        Add(grid, 3, c4);
        var comp = new TextBlock
        {
            Text = c5,
            FontSize = 11.5,
            FontFamily = new FontFamily("Consolas"),
            Foreground = (Brush)Application.Current.Resources["Text.Secondary"],
            TextTrimming = TextTrimming.CharacterEllipsis,
            VerticalAlignment = VerticalAlignment.Center,
        };
        Grid.SetColumn(comp, 4);
        grid.Children.Add(comp);
        return grid;

        static void Add(Grid grid, int col, string text)
        {
            var tb = new TextBlock
            {
                Text = text,
                FontSize = 11.5,
                FontFamily = new FontFamily("Consolas"),
                Foreground = (Brush)Application.Current.Resources["Text.Primary"],
                VerticalAlignment = VerticalAlignment.Center,
                TextTrimming = TextTrimming.CharacterEllipsis,
            };
            Grid.SetColumn(tb, col);
            grid.Children.Add(tb);
        }
    }

    // ---------------- 导出 ----------------

    private async Task ExportAsync(string kind)
    {
        if (_jobId is null)
        {
            AppState.Toast.Show("先运行批量模拟才有可导出的数据", "warn");
            return;
        }
        var reply = await AppState.Bridge.SendAsync("export",
            new JsonObject { ["job_id"] = _jobId, ["kind"] = kind }, timeoutMs: 300_000);
        SinglePage.SaveExport(ExportResult.Parse(reply), $"批量 {kind}");
    }

    // ---------------- 跨页：载入历史任务 ----------------

    public async Task LoadJobAsync(string jobId)
    {
        _jobId = jobId;
        SetRunning(false, $"载入任务 {jobId} 的结果…");
        await LoadBatchAsync();
    }
}
