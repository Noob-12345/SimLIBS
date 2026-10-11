using System.Windows.Controls;

namespace SimlibsStudio;

/// <summary>页面基类：桥就绪 / 主题变化回调。</summary>
public class PageBase : UserControl
{
    public virtual void OnBridgeReady() { }
    public virtual void OnThemeChanged() { }
}
