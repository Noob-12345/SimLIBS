using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace SimlibsStudio.Controls;

/// <summary>分段单选（本地/服务器/客户端、轴选择等），替代 ComboBox 的轻量控件。</summary>
public sealed class Segmented : StackPanel
{
    public event Action<int>? SelectionChanged;

    private readonly List<RadioButton> _buttons = new();
    private string _groupId = "seg-" + Guid.NewGuid().ToString("N");
    private int _selectedIndex;
    private string[] _items = Array.Empty<string>();

    public int SelectedIndex
    {
        get => _selectedIndex;
        set
        {
            _selectedIndex = value;
            for (var i = 0; i < _buttons.Count; i++) _buttons[i].IsChecked = i == value;
        }
    }

    public string SelectedItem =>
        _selectedIndex >= 0 && _selectedIndex < _items.Length ? _items[_selectedIndex] : "";

    public Segmented()
    {
        Orientation = Orientation.Horizontal;
    }

    public void SetItems(IReadOnlyList<string> items, int selected = 0, IReadOnlyList<string>? tooltips = null)
    {
        Children.Clear();
        _buttons.Clear();
        _items = items.ToArray();
        _groupId = "seg-" + Guid.NewGuid().ToString("N");
        for (var i = 0; i < items.Count; i++)
        {
            var index = i;
            var rb = new RadioButton
            {
                GroupName = _groupId,
                Content = items[i],
                Style = (Style)Application.Current.Resources["SegItem"],
                Margin = new Thickness(0, 0, 6, 0),
                IsChecked = i == selected,
            };
            if (tooltips is not null && i < tooltips.Count) rb.ToolTip = tooltips[i];
            rb.Checked += (_, _) =>
            {
                _selectedIndex = index;
                SelectionChanged?.Invoke(index);
            };
            _buttons.Add(rb);
            Children.Add(rb);
        }
        _selectedIndex = selected;
    }

    public void SetItemEnabled(int index, bool enabled)
    {
        if (index >= 0 && index < _buttons.Count) _buttons[index].IsEnabled = enabled;
    }
}

/// <summary>节标题：左侧渐变小竖条 + 标题文字 + 右侧可附内容。</summary>
public sealed class SectionHeader : Grid
{
    public SectionHeader(string title, FrameworkElement? trailing = null)
    {
        HorizontalAlignment = HorizontalAlignment.Stretch;
        RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        var bar = new Border
        {
            Width = 4,
            CornerRadius = new CornerRadius(2),
            Background = (Brush)Application.Current.Resources["Gradient.Primary"],
            VerticalAlignment = VerticalAlignment.Stretch,
            Margin = new Thickness(0, 1, 0, 1),
        };
        var text = new TextBlock
        {
            Text = title,
            FontSize = 13,
            FontWeight = FontWeights.SemiBold,
            Margin = new Thickness(8, 0, 0, 0),
            VerticalAlignment = VerticalAlignment.Center,
            Foreground = (Brush)Application.Current.Resources["Text.Primary"],
        };
        ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
        ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Auto) });
        ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        SetColumn(bar, 0);
        SetColumn(text, 1);
        Children.Add(bar);
        Children.Add(text);
        if (trailing is not null)
        {
            trailing.HorizontalAlignment = HorizontalAlignment.Right;
            trailing.VerticalAlignment = VerticalAlignment.Center;
            SetColumn(trailing, 2);
            Children.Add(trailing);
        }
    }
}

/// <summary>状态徽章（任务状态、元数据 chip 等）。</summary>
public sealed class Chip : Border
{
    public Chip(string text, Brush? foreground = null, Brush? background = null, Brush? border = null)
    {
        CornerRadius = new CornerRadius(7);
        Padding = new Thickness(9, 4, 9, 5);
        HorizontalAlignment = HorizontalAlignment.Left;
        Background = background ?? (Brush)Application.Current.Resources["Bg.Card2"];
        BorderBrush = border ?? (Brush)Application.Current.Resources["Line.Subtle"];
        BorderThickness = new Thickness(1);
        Child = new TextBlock
        {
            Text = text,
            FontSize = 11.5,
            Foreground = foreground ?? (Brush)Application.Current.Resources["Text.Secondary"],
            TextTrimming = TextTrimming.CharacterEllipsis,
            MaxWidth = 420,
        };
    }

    public void SetText(string text)
    {
        if (Child is TextBlock tb) tb.Text = text;
    }
}
