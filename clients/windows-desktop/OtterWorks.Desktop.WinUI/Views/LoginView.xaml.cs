using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using OtterWorks.Desktop.ViewModels;

namespace OtterWorks.Desktop.WinUI.Views
{
    public sealed partial class LoginView : UserControl
    {
        public LoginView(LoginViewModel viewModel)
        {
            ViewModel = viewModel;
            InitializeComponent();
            DefaultButton.Attach(this, SignInButton);
        }

        public LoginViewModel ViewModel { get; }

        private void PasswordInput_PasswordChanged(object sender, RoutedEventArgs e)
        {
            ViewModel.Password = PasswordInput.Password;
        }
    }
}
