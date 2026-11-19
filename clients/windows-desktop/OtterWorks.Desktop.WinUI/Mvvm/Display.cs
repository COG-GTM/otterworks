using Microsoft.UI.Xaml;

namespace OtterWorks.Desktop.Mvvm
{
    /// <summary>Helpers for x:Bind function bindings (WinUI has no value converters on x:Bind paths).</summary>
    public static class Display
    {
        public static Visibility VisibleIfText(string text) =>
            string.IsNullOrWhiteSpace(text) ? Visibility.Collapsed : Visibility.Visible;
    }
}
