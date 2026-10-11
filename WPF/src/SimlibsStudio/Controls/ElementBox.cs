using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;

namespace SimlibsStudio.Controls;

/// <summary>
/// 元素输入框：输入 f 弹出 Fe 供补全；失焦时 fe/hE 等大小写自动规范为 Fe/He。
/// </summary>
public sealed class ElementBox : Grid
{
    private readonly TextBox _box;
    private readonly Popup _popup;
    private readonly ListBox _list;
    private List<string> _source = new();
    private bool _suppress;

    public event Action<string>? SymbolCommitted;

    public ElementBox()
    {
        ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        _box = new TextBox
        {
            Style = (Style)Application.Current.Resources["FieldBox"],
            FontSize = 13,
            FontFamily = new FontFamily("Consolas"),
            Padding = new Thickness(8, 5, 8, 6),
            Tag = "元素符号，如 Fe",
        };
        SetColumn(_box, 0);
        Children.Add(_box);

        _list = new ListBox
        {
            MaxHeight = 190,
            BorderThickness = new Thickness(0),
            Background = Brushes.Transparent,
            ItemContainerStyle = (Style)Application.Current.Resources["CleanItem"],
            FontFamily = new FontFamily("Consolas"),
            FontSize = 13,
        };
        _list.PreviewMouseLeftButtonUp += (_, _) => CommitSelection();

        _popup = new Popup
        {
            PlacementTarget = _box,
            Placement = PlacementMode.Bottom,
            StaysOpen = false,
            AllowsTransparency = true,
            Child = new Border
            {
                Background = (Brush)Application.Current.Resources["Bg.Popup"],
                BorderBrush = (Brush)Application.Current.Resources["Line.Strong"],
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(10),
                Margin = new Thickness(0, 3, 8, 0),
                Padding = new Thickness(4),
                Effect = (System.Windows.Media.Effects.Effect)Application.Current.Resources["Fx.Popup"],
                Child = _list,
            },
        };

        _box.TextChanged += (_, _) => UpdateSuggestions();
        _box.LostFocus += (_, _) => Canonicalize();
        _box.KeyDown += OnKeyDown;
    }

    public string Text => _box.Text.Trim();

    /// <summary>规范后的元素符号（无效输入返回原文本）；空返回空串。</summary>
    public string Symbol
    {
        get
        {
            var t = _box.Text.Trim();
            return t.Length == 0 ? "" : Canonical(t);
        }
    }

    public void SetText(string symbol)
    {
        _box.Text = symbol;
    }

    public void SetSource(IReadOnlyList<string> elements) => _source = elements.ToList();

    public new bool IsEnabled
    {
        get => _box.IsEnabled;
        set => _box.IsEnabled = value;
    }

    private string Canonical(string raw)
    {
        var hit = _source.FirstOrDefault(e => string.Equals(e, raw, StringComparison.OrdinalIgnoreCase));
        if (hit is not null) return hit;
        // 通用规则：首字母大写 + 其余小写（fe → Fe）
        return raw.Length == 0 ? raw : char.ToUpper(raw[0]) + raw[1..].ToLower();
    }

    private void UpdateSuggestions()
    {
        if (_suppress) { _suppress = false; return; }
        var q = _box.Text.Trim();
        IEnumerable<string> matches;
        if (q.Length == 0)
        {
            matches = _source.Take(12);
        }
        else
        {
            var starts = _source.Where(e => e.StartsWith(q, StringComparison.OrdinalIgnoreCase)).ToList();
            var contains = _source.Where(e => !starts.Contains(e) && e.ToLower().Contains(q.ToLower())).ToList();
            matches = starts.Concat(contains).Take(12);
        }
        var items = matches.ToList();
        if (items.Count == 0)
        {
            _popup.IsOpen = false;
            return;
        }
        _list.Items.Clear();
        foreach (var it in items)
        {
            _list.Items.Add(new ListBoxItem { Content = it, Style = (Style)Application.Current.Resources["CleanItem"] });
        }
        _popup.IsOpen = true;
    }

    private void OnKeyDown(object sender, KeyEventArgs e)
    {
        if (!_popup.IsOpen) return;
        if (e.Key == Key.Down)
        {
            if (_list.Items.Count > 0)
                _list.SelectedIndex = Math.Min(_list.SelectedIndex + 1, _list.Items.Count - 1);
            e.Handled = true;
        }
        else if (e.Key == Key.Up)
        {
            _list.SelectedIndex = Math.Max(_list.SelectedIndex - 1, 0);
            e.Handled = true;
        }
        else if (e.Key == Key.Enter)
        {
            CommitSelection();
            e.Handled = true;
        }
        else if (e.Key == Key.Escape)
        {
            _popup.IsOpen = false;
            e.Handled = true;
        }
    }

    private void CommitSelection()
    {
        if (_list.SelectedItem is ListBoxItem item)
        {
            _suppress = true;
            _box.Text = item.Content.ToString();
        }
        _popup.IsOpen = false;
        _box.CaretIndex = _box.Text.Length;
        SymbolCommitted?.Invoke(Symbol);
    }

    private void Canonicalize()
    {
        _popup.IsOpen = false;
        var t = _box.Text.Trim();
        if (t.Length == 0) return;
        var canonical = Canonical(t);
        if (!ReferenceEquals(canonical, t) && canonical != t)
        {
            _suppress = true;
            _box.Text = canonical;
            SymbolCommitted?.Invoke(canonical);
        }
    }
}
