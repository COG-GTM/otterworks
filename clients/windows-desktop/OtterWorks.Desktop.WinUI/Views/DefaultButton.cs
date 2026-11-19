using System.Windows.Input;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Input;
using Windows.System;

namespace OtterWorks.Desktop.WinUI.Views
{
    /// <summary>
    /// Stand-in for WPF's <c>Button.IsDefault</c>: Enter anywhere in the view runs the button's
    /// command, unless focus is on another button, which takes Enter itself.
    /// </summary>
    internal static class DefaultButton
    {
        public static void Attach(UIElement root, Button button)
        {
            // handledEventsToo: text inputs mark Enter handled before it bubbles up.
            root.AddHandler(UIElement.KeyDownEvent, new KeyEventHandler((sender, e) =>
            {
                if (e.Key != VirtualKey.Enter || FocusManager.GetFocusedElement(root.XamlRoot) is ButtonBase)
                {
                    return;
                }

                ICommand command = button.Command;
                if (button.IsEnabled && command != null && command.CanExecute(null))
                {
                    command.Execute(null);
                    e.Handled = true;
                }
            }), true);
        }
    }
}
