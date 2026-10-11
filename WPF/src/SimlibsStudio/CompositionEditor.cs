using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using SimlibsStudio.Controls;

namespace SimlibsStudio;

/// <summary>
/// 配比编辑器：元素行（ElementBox + 百分比 + 删除）、归一化、总和 100% 校验。
/// 单次模拟与批量组成池共用。
/// </summary>
public sealed class CompositionEditor : StackPanel
{
    private sealed class Row
    {
        public ElementBox Element = null!;
        public TextBox Pct = null!;
        public Button Remove = null!;
        public Border Root = null!;
    }

    private readonly StackPanel _rowsPanel = new() { Margin = new Thickness(0, 8, 0, 0) };
    private readonly TextBlock _totalText = new()
    {
        FontSize = 11.5,
        FontFamily = new FontFamily("Consolas"),
        Foreground = (Brush)Application.Current.Resources["Text.Faint"],
        VerticalAlignment = VerticalAlignment.Center,
    };
    private bool _building;

    public event Action? Changed;

    public CompositionEditor(bool compact = false, bool allowBlocks = false)
    {
        var header = new Grid { Margin = new Thickness(0, 0, 0, 0) };
        header.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        header.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var title = new TextBlock
        {
            Text = "元素配比",
            FontSize = 12.5,
            FontWeight = FontWeights.SemiBold,
            Foreground = (Brush)Application.Current.Resources["Text.Primary"],
            VerticalAlignment = VerticalAlignment.Center,
        };
        var buttons = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
        buttons.Children.Add(_totalText);
        buttons.Children.Add(MakeMiniButton("归一化", () => Normalize()));
        if (allowBlocks)
            buttons.Children.Add(MakeMiniButton("＋ 新组成", () => AddSeparator()));
        buttons.Children.Add(MakeMiniButton("＋ 添加", () => AddRow()));
        Grid.SetColumn(title, 0);
        Grid.SetColumn(buttons, 1);
        header.Children.Add(title);
        header.Children.Add(buttons);

        Children.Add(header);
        Children.Add(_rowsPanel);

        if (!compact && _rowsPanel.Children.Count == 0)
        {
            AddRow("Fe", "100");
        }
    }

    private static Button MakeMiniButton(string text, Action onClick)
    {
        var b = new Button
        {
            Content = text,
            Style = (Style)Application.Current.Resources["BtnGhost"],
            FontSize = 11.5,
            Padding = new Thickness(9, 4, 9, 5),
            Margin = new Thickness(8, 0, 0, 0),
        };
        b.Click += (_, _) => onClick();
        return b;
    }

    public void AddRow(string el = "", string pct = "")
    {
        if (_rowsPanel.Children.Count >= 32) return;
        var row = new Row();
        var grid = new Grid { Margin = new Thickness(0, 0, 0, 7) };
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(84) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

        row.Element = new ElementBox { Margin = new Thickness(0, 0, 7, 0) };
        row.Element.SetSource(AppState.Elements);
        row.Element.SymbolCommitted += _ => RaiseChanged();
        if (el.Length > 0) row.Element.SetText(el);

        row.Pct = new TextBox
        {
            Style = (Style)Application.Current.Resources["FieldBox"],
            FontFamily = new FontFamily("Consolas"),
            FontSize = 12.5,
            Padding = new Thickness(7, 5, 7, 6),
            Text = pct,
        };
        row.Pct.LostFocus += (_, _) => RaiseChanged();
        row.Pct.TextChanged += (_, _) => { if (!_building) UpdateTotal(); };

        row.Remove = new Button
        {
            Content = "✕",
            Style = (Style)Application.Current.Resources["BtnIcon"],
            FontSize = 11,
            Width = 30,
            Height = 30,
            Margin = new Thickness(5, 0, 0, 0),
            ToolTip = "删除此行",
        };
        row.Remove.Click += (_, _) => RemoveRow(row);

        Grid.SetColumn(row.Element, 0);
        Grid.SetColumn(row.Pct, 1);
        Grid.SetColumn(row.Remove, 2);
        grid.Children.Add(row.Element);
        grid.Children.Add(row.Pct);
        grid.Children.Add(row.Remove);
        row.Root = new Border { Child = grid };

        _rowsPanel.Children.Add(row.Root);
        UpdateTotal();
        RaiseChanged();
    }

    private void RemoveRow(Row row)
    {
        if (_rowsPanel.Children.Count <= 1) return;   // 至少保留一行
        _rowsPanel.Children.Remove(row.Root);
        UpdateTotal();
        RaiseChanged();
    }

    /// <summary>遍历行；分隔线返回 null。</summary>
    private List<Row?> Rows()
    {
        var list = new List<Row?>();
        foreach (var child in _rowsPanel.Children)
        {
            if (child is not Border b || b.Child is not Grid g)
            {
                list.Add(null);   // 组成块分隔线
                continue;
            }
            var elementBox = g.Children.OfType<ElementBox>().First();
            var pct = g.Children.OfType<TextBox>().First();
            list.Add(new Row { Element = elementBox, Pct = pct });
        }
        return list;
    }

    private IEnumerable<List<Row?>> Blocks()
    {
        var current = new List<Row?>();
        foreach (var row in Rows())
        {
            if (row is null)
            {
                if (current.Count > 0) { yield return current; current = new List<Row?>(); }
            }
            else current.Add(row);
        }
        if (current.Count > 0) yield return current;
    }

    private void RaiseChanged()
    {
        UpdateTotal();
        Changed?.Invoke();
    }

    private void UpdateTotal()
    {
        var blocks = Blocks().Where(b => b.Count > 0).ToList();
        if (blocks.Count <= 1)
        {
            var total = BlockTotal(blocks.Count == 1 ? blocks[0] : new List<Row?>());
            _totalText.Text = $"Σ {total:0.##}%";
            _totalText.SetResourceReference(TextBlock.ForegroundProperty,
                Math.Abs(total - 100) < 1e-6 ? "State.Ok" : "State.Warn");
        }
        else
        {
            var parts = blocks.Select((b, i) => $"{i + 1}:{BlockTotal(b):0.#}%");
            var allOk = blocks.All(b => Math.Abs(BlockTotal(b) - 100) < 1e-6);
            _totalText.Text = $"{blocks.Count} 组成 · {string.Join(' ', parts)}";
            _totalText.SetResourceReference(TextBlock.ForegroundProperty,
                allOk ? "State.Ok" : "State.Warn");
        }
    }

    private static double BlockTotal(List<Row?> block)
    {
        double total = 0;
        foreach (var row in block)
        {
            if (row is not null && double.TryParse(row.Pct.Text.Trim(), out var v)) total += v;
        }
        return total;
    }

    public double Total
    {
        get
        {
            double total = 0;
            foreach (var row in Rows())
                if (row is not null && double.TryParse(row.Pct.Text.Trim(), out var v)) total += v;
            return total;
        }
    }

    /// <summary>按比例缩放到总和 100%；组成池模式下逐块归一化。</summary>
    public void Normalize()
    {
        _building = true;
        try
        {
            foreach (var block in Blocks())
            {
                var total = BlockTotal(block);
                if (total <= 0) continue;
                foreach (var row in block)
                {
                    if (row is null) continue;
                    if (double.TryParse(row.Pct.Text.Trim(), out var v) && v > 0)
                        row.Pct.Text = (v / total * 100).ToString("0.######");
                    else
                        row.Pct.Text = "0";
                }
            }
        }
        finally
        {
            _building = false;
        }
        RaiseChanged();
    }

    /// <summary>读取当前配比；校验失败抛 FormatException（消息可直接 toast）。</summary>
    public (string el, double pct)[] Collect()
    {
        var rows = Rows();
        if (rows.Count == 0) throw new FormatException("配比至少需要一个元素");
        if (rows.Count > 32) throw new FormatException("元素数量过多（≤32）");

        var result = new List<(string, double)>();
        var seen = new HashSet<string>();
        foreach (var row in rows)
        {
            var el = row.Element.Symbol;
            if (el.Length == 0) throw new FormatException("存在未填写的元素符号");
            if (!AppState.Elements.Contains(el))
                throw new FormatException($"无效元素符号：{el}（使用 Fe 等规范大小写）");
            if (!seen.Add(el)) throw new FormatException($"元素重复：{el}");
            if (!double.TryParse(row.Pct.Text.Trim(), out var pct) || pct < 0)
                throw new FormatException($"{el} 的配比必须是 ≥ 0 的数字");
            result.Add((el, pct));
        }
        var total = result.Sum(r => r.Item2);
        if (Math.Abs(total - 100.0) > 1e-6)
            throw new FormatException($"配比总和必须为 100%（当前 {total:0.######}%，可用「归一化」）");
        return result.ToArray();
    }

    /// <summary>整体设置行（用于预设 / 用当前配比）。</summary>
    public void SetRows((string el, double pct)[] items)
    {
        _building = true;
        try
        {
            _rowsPanel.Children.Clear();
            foreach (var (el, pct) in items)
                AddRow(el, pct.ToString("0.######"));
        }
        finally
        {
            _building = false;
        }
        UpdateTotal();
        Changed?.Invoke();
    }

    /// <summary>宽松读取（不做符号/总和校验），供随机规则同步元素列表。</summary>
    public (string el, double pct)[] CollectRows()
    {
        var list = new List<(string, double)>();
        foreach (var row in Rows())
        {
            if (row is null) continue;
            var el = row.Element.Symbol;
            if (el.Length == 0) continue;
            double.TryParse(row.Pct.Text.Trim(), out var pct);
            list.Add((el, pct));
        }
        return list.ToArray();
    }

    /// <summary>插入组成块分隔线（组成池多候选时使用）。</summary>
    public void AddSeparator()
    {
        _rowsPanel.Children.Add(new Border
        {
            Height = 1,
            Margin = new Thickness(0, 2, 0, 10),
            BorderBrush = (Brush)Application.Current.Resources["Line.Strong"],
            BorderThickness = new Thickness(0, 0, 0, 1),
            Opacity = 0.8,
        });
        _separatorCount++;
        UpdateTotal();
    }

    private int _separatorCount;

    /// <summary>追加一个组成块（导入 CSV 多行时使用）；首块前自动补分隔线。</summary>
    public void AddPoolRow((string el, double pct)[] items)
    {
        if (_rowsPanel.Children.Count > 0) AddSeparator();
        _building = true;
        try
        {
            foreach (var (el, pct) in items)
                AddRow(el, pct.ToString("0.######"));
        }
        finally
        {
            _building = false;
        }
        UpdateTotal();
        Changed?.Invoke();
    }

    /// <summary>
    /// 组成池收集：行块以分隔线切分，每块是一个候选组成（各自总和须 100%）。
    /// </summary>
    public (string Name, (string el, double pct)[] Items)[] CollectPool()
    {
        var blocks = new List<List<Row>>();
        var current = new List<Row>();
        foreach (var row in Rows())
        {
            if (row is null)
            {
                if (current.Count > 0) { blocks.Add(current); current = new List<Row>(); }
            }
            else current.Add(row);
        }
        if (current.Count > 0) blocks.Add(current);

        if (blocks.Count == 0) throw new FormatException("配比至少需要一个元素");
        var pool = new List<(string, (string, double)[])>();
        for (var b = 0; b < blocks.Count; b++)
        {
            pool.Add(($"{blocks[b][0].Element.Symbol}-{b + 1:00}", ValidateBlock(blocks[b], b + 1)));
        }
        return pool.ToArray();
    }

    private (string, double)[] ValidateBlock(List<Row> rows, int index)
    {
        if (rows.Count == 0) throw new FormatException($"组成 {index} 为空");
        if (rows.Count > 32) throw new FormatException($"组成 {index} 元素数量过多（≤32）");
        var result = new List<(string, double)>();
        var seen = new HashSet<string>();
        foreach (var row in rows)
        {
            var el = row.Element.Symbol;
            if (el.Length == 0) throw new FormatException($"组成 {index} 存在未填写的元素符号");
            if (!AppState.Elements.Contains(el))
                throw new FormatException($"无效元素符号：{el}（使用 Fe 等规范大小写）");
            if (!seen.Add(el)) throw new FormatException($"组成 {index} 元素重复：{el}");
            if (!double.TryParse(row.Pct.Text.Trim(), out var pct) || pct < 0)
                throw new FormatException($"组成 {index} 的 {el} 配比必须是 ≥ 0 的数字");
            result.Add((el, pct));
        }
        var total = result.Sum(r => r.Item2);
        if (Math.Abs(total - 100.0) > 1e-6)
            throw new FormatException($"组成 {index} 总和必须为 100%（当前 {total:0.######}%，可用「归一化」）");
        return result.ToArray();
    }
}
