using System;
using System.Globalization;
using Microsoft.UI.Xaml;

namespace OtterWorks.Desktop.Mvvm
{
    /// <summary>Helpers for x:Bind function bindings (WinUI has no value converters on x:Bind paths).</summary>
    public static class Display
    {
        public static Visibility VisibleIfText(string text) =>
            string.IsNullOrWhiteSpace(text) ? Visibility.Collapsed : Visibility.Visible;

        // WPF formats bindings with en-US unless a Language is set, and the 4.8 client sets none.
        private static readonly CultureInfo BindingCulture = CultureInfo.GetCultureInfo("en-US");

        /// <summary>Same text as WPF's <c>StringFormat=g</c>.</summary>
        public static string GeneralDateTime(DateTimeOffset? value) =>
            value?.ToString("g", BindingCulture) ?? string.Empty;

        /// <summary>Same text as the WPF runs "{WordCount} words · v {Version}".</summary>
        public static string WordsAndVersion(int wordCount, int version) =>
            string.Format(BindingCulture, "{0} words · v {1}", wordCount, version);
    }
}
