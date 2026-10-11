using System.Diagnostics;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;

namespace SimlibsStudio;


/// <summary>
/// 标题栏外观弹层：主题模式（浅色 / 深色 / 跟随系统）与主题颜色预览卡片，
/// 以及 GitHub 仓库直达。与 MainWindow.xaml.cs 同属 partial MainWindow。
/// </summary>
public partial class MainWindow
{
    private Popup? _flyout;

    // ---------------- 入口 ----------------

    private void OnThemeButtonClick(object sender, RoutedEventArgs e) => ShowThemeFlyout();

    private void OnAccentButtonClick(object sender, RoutedEventArgs e) => ShowAccentFlyout();

    private void OnGitHubClick(object sender, RoutedEventArgs e)
    {
        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = "https://github.com/Noob-12345/SimLIBS",
                UseShellExecute = true,
            });
        }
        catch (Exception exc)
        {
            Toasts.Show(exc.Message, "error", "打开仓库");
        }
    }

    private void UpdateThemeIcon()
    {
        ThemeIcon.Text = AppState.Theme.Mode switch
        {
            SimlibsStudio.ThemeMode.Light => "☀",
            SimlibsStudio.ThemeMode.System => "◐",
            _ => "☾",
        };
        ThemeBtn.ToolTip = AppState.Theme.Mode switch
        {
            SimlibsStudio.ThemeMode.Light => "当前：浅色（点击切换 浅色 / 深色 / 跟随系统）",
            SimlibsStudio.ThemeMode.System => "当前：跟随系统（点击切换 浅色 / 深色 / 跟随系统）",
            _ => "当前：深色（点击切换 浅色 / 深色 / 跟随系统）",
        };
    }

    // ---------------- 弹层骨架 ----------------

    private void CloseFlyout()
    {
        if (_flyout is not null)
        {
            _flyout.IsOpen = false;
            _flyout = null;
        }
    }

    private Popup OpenFlyout(FrameworkElement content, FrameworkElement target)
    {
        CloseFlyout();
        var popup = new Popup
        {
            PlacementTarget = target,
            Placement = PlacementMode.Bottom,
            StaysOpen = false,
            AllowsTransparency = true,
            PopupAnimation = PopupAnimation.Fade,
            Child = new Border
            {
                Background = (Brush)Application.Current.Resources["Bg.Popup"],
                BorderBrush = (Brush)Application.Current.Resources["Line.Strong"],
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(13),
                Margin = new Thickness(0, 4, 10, 0),
                Padding = new Thickness(8),
                Effect = (System.Windows.Media.Effects.Effect)Application.Current.Resources["Fx.Popup"],
                Child = content,
            },
        };
        _flyout = popup;
        popup.IsOpen = true;
        return popup;
    }

    // ---------------- 外观模式（浅色 / 深色 / 跟随系统） ----------------

    private void ShowThemeFlyout()
    {
        var list = new StackPanel { MinWidth = 198 };
        list.Children.Add(ModeOption("☀", "浅色", SimlibsStudio.ThemeMode.Light));
        list.Children.Add(ModeOption("☾", "深色", SimlibsStudio.ThemeMode.Dark));
        list.Children.Add(ModeOption("◐", "跟随系统", SimlibsStudio.ThemeMode.System));
        OpenFlyout(list, ThemeBtn);
    }

    private FrameworkElement ModeOption(string icon, string label, ThemeMode mode)
    {
        var active = AppState.Theme.Mode == mode;
        var row = new Grid { Margin = new Thickness(2) };
        row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

        row.Children.Add(new TextBlock
        {
            Text = icon,
            FontSize = 14,
            VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(4, 0, 10, 0),
            Foreground = (Brush)Application.Current.Resources["Text.Secondary"],
        });
        row.Children.Add(new TextBlock
        {
            Text = label,
            FontSize = 12.5,
            VerticalAlignment = VerticalAlignment.Center,
        });
        var check = new TextBlock
        {
            Text = "✓",
            FontSize = 12.5,
            FontWeight = FontWeights.Bold,
            Margin = new Thickness(10, 0, 2, 0),
            Visibility = active ? Visibility.Visible : Visibility.Collapsed,
        };
        check.SetResourceReference(TextBlock.ForegroundProperty, "Accent.B");
        Grid.SetColumn(check, 2);
        row.Children.Add(check);

        var host = new Border
        {
            CornerRadius = new CornerRadius(9),
            Padding = new Thickness(8, 7, 10, 8),
            Background = Brushes.Transparent,
            Child = row,
            Cursor = Cursors.Hand,
        };
        host.MouseEnter += (_, _) => host.Background = (Brush)Application.Current.Resources["Bg.Hover"];
        host.MouseLeave += (_, _) => host.Background = Brushes.Transparent;
        host.MouseLeftButtonUp += (_, _) =>
        {
            AppState.Theme.SetMode(mode);
            CloseFlyout();
        };
        return host;
    }

    // ---------------- 主题颜色预览卡片 ----------------

    private void ShowAccentFlyout()
    {
        var panel = new StackPanel();
        panel.Children.Add(new TextBlock
        {
            Text = "主题颜色",
            FontSize = 12.5,
            FontWeight = FontWeights.SemiBold,
            Margin = new Thickness(6, 2, 0, 8),
        });
        var wrap = new WrapPanel { Width = 3 * 166 + 12 };
        foreach (var t in AccentCatalog.All)
            wrap.Children.Add(MakeAccentCard(t));
        panel.Children.Add(wrap);
        OpenFlyout(panel, AccentBtn);
    }

    private FrameworkElement MakeAccentCard(AccentTheme t)
    {
        var active = AppState.Theme.AccentId == t.Id;
        var activeBrush = new SolidColorBrush(t.A);
        var hoverBrush = new SolidColorBrush(Color.FromArgb(0x88, t.A.R, t.A.G, t.A.B));
        var idleBrush = (Brush)Application.Current.Resources["Line.Subtle"];

        var card = new Border
        {
            Width = 158,
            Margin = new Thickness(4),
            CornerRadius = new CornerRadius(11),
            Padding = new Thickness(10, 9, 10, 9),
            Background = (Brush)Application.Current.Resources["Bg.Card2"],
            BorderBrush = active ? activeBrush : idleBrush,
            BorderThickness = new Thickness(active ? 1.6 : 1),
            Cursor = Cursors.Hand,
        };

        var stack = new StackPanel();
        stack.Children.Add(MakeMiniSpectrum(t));

        var row = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 8, 0, 0) };
        row.Children.Add(new Border
        {
            Width = 44,
            Height = 13,
            CornerRadius = new CornerRadius(7),
            Background = GradientBrush(t),
            VerticalAlignment = VerticalAlignment.Center,
        });
        var slider = new Grid { Width = 48, Margin = new Thickness(9, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center };
        slider.Children.Add(new Border
        {
            Height = 4,
            CornerRadius = new CornerRadius(2),
            Background = (Brush)Application.Current.Resources["Bg.Hover"],
            VerticalAlignment = VerticalAlignment.Center,
        });
        slider.Children.Add(new System.Windows.Shapes.Ellipse
        {
            Width = 9,
            Height = 9,
            Fill = new SolidColorBrush(t.A),
            Stroke = Brushes.White,
            StrokeThickness = 1,
            HorizontalAlignment = HorizontalAlignment.Left,
            Margin = new Thickness(32, 0, 0, 0),
            VerticalAlignment = VerticalAlignment.Center,
        });
        row.Children.Add(slider);
        stack.Children.Add(row);

        var nameRow = new Grid { Margin = new Thickness(0, 8, 0, 0) };
        nameRow.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        nameRow.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        nameRow.Children.Add(new TextBlock
        {
            Text = t.Name,
            FontSize = 12,
            VerticalAlignment = VerticalAlignment.Center,
        });
        nameRow.Children.Add(new TextBlock
        {
            Text = "✓",
            FontSize = 12,
            FontWeight = FontWeights.Bold,
            Foreground = new SolidColorBrush(t.A),
            Margin = new Thickness(0, 0, 2, 0),
            Visibility = active ? Visibility.Visible : Visibility.Collapsed,
        });
        stack.Children.Add(nameRow);
        card.Child = stack;

        card.MouseEnter += (_, _) => card.BorderBrush = active ? activeBrush : hoverBrush;
        card.MouseLeave += (_, _) =>
        {
            var nowActive = AppState.Theme.AccentId == t.Id;
            card.BorderBrush = nowActive ? activeBrush : idleBrush;
            card.BorderThickness = new Thickness(nowActive ? 1.6 : 1);
        };
        card.MouseLeftButtonUp += (_, _) =>
        {
            AppState.Theme.SetAccent(t.Id);
            CloseFlyout();
        };
        return card;
    }

    private static LinearGradientBrush GradientBrush(AccentTheme t) => new()
    {
        StartPoint = new Point(0, 0),
        EndPoint = new Point(1, 1),
        GradientStops =
        {
            new GradientStop(t.A, 0),
            new GradientStop(t.B, 1),
        },
    };

    /// <summary>迷你谱图缩略：渐变强调条 + 谱峰竖线 + 基线（全部使用该主题自己的颜色）。</summary>
    private static FrameworkElement MakeMiniSpectrum(AccentTheme t)
    {
        var canvas = new Canvas { Width = 138, Height = 26, ClipToBounds = true };

        var bar = new System.Windows.Shapes.Rectangle
        {
            Width = 138,
            Height = 3,
            RadiusX = 1.5,
            RadiusY = 1.5,
            Fill = GradientBrush(t),
        };
        Canvas.SetTop(bar, 0);
        canvas.Children.Add(bar);

        var baseline = new System.Windows.Shapes.Rectangle
        {
            Width = 138,
            Height = 1,
            Fill = new SolidColorBrush(Color.FromArgb(0x38, 0x88, 0x88, 0x88)),
        };
        Canvas.SetTop(baseline, 24);
        canvas.Children.Add(baseline);

        double[] xs = { 6, 12, 17, 28, 34, 41, 54, 60, 68, 82, 89, 100, 109, 120, 128 };
        double[] hs = { 10, 18, 7, 13, 22, 9, 17, 5, 14, 9, 21, 8, 16, 11, 6 };
        var geo = new StreamGeometry();
        using (var ctx = geo.Open())
        {
            for (var i = 0; i < xs.Length; i++)
            {
                var x = xs[i];
                var h = hs[i];
                ctx.BeginFigure(new Point(x, 24), true, true);
                ctx.LineTo(new Point(x + 0.6, 24 - h), true, false);
                ctx.LineTo(new Point(x + 1.2, 24), true, false);
            }
        }
        geo.Freeze();
        canvas.Children.Add(new System.Windows.Shapes.Path
        {
            Data = geo,
            Fill = new SolidColorBrush(t.A),
        });
        return canvas;
    }
}
