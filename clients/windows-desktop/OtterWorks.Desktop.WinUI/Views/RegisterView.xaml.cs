using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using OtterWorks.Desktop.ViewModels;

namespace OtterWorks.Desktop.WinUI.Views
{
    public sealed partial class RegisterView : UserControl
    {
        public RegisterView(RegisterViewModel viewModel)
        {
            ViewModel = viewModel;
            InitializeComponent();
            DefaultButton.Attach(this, CreateAccountButton);
        }

        public RegisterViewModel ViewModel { get; }

        private void PasswordInput_PasswordChanged(object sender, RoutedEventArgs e)
        {
            ViewModel.Password = PasswordInput.Password;
        }
    }
}
