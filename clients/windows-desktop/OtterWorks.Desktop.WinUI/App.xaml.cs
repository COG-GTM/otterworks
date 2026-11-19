using Microsoft.UI.Xaml;
using OtterWorks.Desktop.Services;
using OtterWorks.Desktop.ViewModels;
using OtterWorks.Desktop.WinUI.Views;

namespace OtterWorks.Desktop.WinUI
{
    /// <summary>Application entry point; wires up services and shows the shell window.</summary>
    public partial class App : Application
    {
        private MainWindow _window;

        public App()
        {
            InitializeComponent();
        }

        protected override void OnLaunched(LaunchActivatedEventArgs args)
        {
            AppSettings settings = AppSettings.Load();
            var session = new SessionState(settings.PersistTokens);
            session.TryRestore();

            var api = new OtterWorksApiClient(settings, session);
            var mainViewModel = new MainViewModel(api, session);

            _window = new MainWindow(mainViewModel);
            _window.Activate();
        }
    }
}
