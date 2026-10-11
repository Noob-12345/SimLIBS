using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Threading;

namespace SimlibsStudio.Controls;

/// <summary>右下滑入 toast 通知（info/ok/warn/error 四色），自动消退，最多同时 5 条。</summary>
public sealed class ToastService
{
    private readonly Panel _host;
    private readonly Dispatcher _dispatcher;

    public ToastService(Panel host, Dispatcher dispatcher)
    {
        _host = host;
        _dispatcher = dispatcher;
    }

    public void Show(string message, string level = "info", string? title = null, int durationMs = 4600)
    {
        _dispatcher.BeginInvoke(() =>
        {
            while (_host.Children.Count >= 5) _host.Children.RemoveAt(0);

            var (accent, icon, defaultTitle) = level switch
            {
                "ok" => ("State.Ok", "✓", "成功"),
                "warn" => ("State.Warn", "!", "注意"),
                "error" => ("State.Error", "✕", "出错了"),
                _ => ("Accent.C", "ℹ", "提示"),
            };
            var accentBrush = (Brush)Application.Current.Resources[accent];

            var titleBlock = new TextBlock
            {
                Text = title ?? defaultTitle,
                FontSize = 12.5,
                FontWeight = FontWeights.SemiBold,
                Foreground = accentBrush,
            };
            var msgBlock = new TextBlock
            {
                Text = message,
                FontSize = 12,
                Foreground = (Brush)Application.Current.Resources["Text.Primary"],
                TextWrapping = TextWrapping.Wrap,
                MaxWidth = 300,
                Margin = new Thickness(0, 2, 0, 0),
            };
            var iconBlock = new TextBlock
            {
                Text = icon,
                FontSize = 15,
                FontWeight = FontWeights.Bold,
                Foreground = accentBrush,
                VerticalAlignment = VerticalAlignment.Top,
                Margin = new Thickness(0, 1, 0, 0),
            };

            var inner = new Grid { Margin = new Thickness(12, 10, 12, 11) };
            inner.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            inner.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            var stack = new StackPanel { Children = { titleBlock, msgBlock } };
            Grid.SetColumn(iconBlock, 0);
            Grid.SetColumn(stack, 1);
            inner.Children.Add(iconBlock);
            inner.Children.Add(stack);

            var bar = new Border
            {
                Width = 4,
                CornerRadius = new CornerRadius(4, 0, 0, 4),
                Background = accentBrush,
                VerticalAlignment = VerticalAlignment.Stretch,
            };

            var card = new Grid();
            card.Children.Add(new Border
            {
                Background = (Brush)Application.Current.Resources["Bg.Popup"],
                BorderBrush = (Brush)Application.Current.Resources["Line.Strong"],
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(12),
                Effect = (System.Windows.Media.Effects.Effect)Application.Current.Resources["Fx.Popup"],
                Child = inner,
            });
            card.Children.Add(bar);

            var toast = new Border { Child = card, Opacity = 0 };
            var translate = new TranslateTransform(40, 0);
            toast.RenderTransform = translate;

            _host.Children.Add(toast);

            var fadeIn = new DoubleAnimation(0, 1, TimeSpan.FromMilliseconds(220)) { EasingFunction = new CubicEase() };
            var slideIn = new DoubleAnimation(40, 0, TimeSpan.FromMilliseconds(260)) { EasingFunction = new CubicEase() };
            toast.BeginAnimation(UIElement.OpacityProperty, fadeIn);
            translate.BeginAnimation(TranslateTransform.XProperty, slideIn);

            var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(durationMs) };
            timer.Tick += (_, _) =>
            {
                timer.Stop();
                var fadeOut = new DoubleAnimation(toast.Opacity, 0, TimeSpan.FromMilliseconds(240))
                {
                    EasingFunction = new CubicEase(),
                };
                var slideOut = new DoubleAnimation(0, 40, TimeSpan.FromMilliseconds(240))
                {
                    EasingFunction = new CubicEase(),
                };
                fadeOut.Completed += (_, _) =>
                {
                    if (_host.Children.Contains(toast)) _host.Children.Remove(toast);
                };
                toast.BeginAnimation(UIElement.OpacityProperty, fadeOut);
                translate.BeginAnimation(TranslateTransform.XProperty, slideOut);
            };
            timer.Start();
        });
    }
}
