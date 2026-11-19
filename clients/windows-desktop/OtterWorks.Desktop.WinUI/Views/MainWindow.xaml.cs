using System.ComponentModel;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using OtterWorks.Desktop.ViewModels;
using Windows.Graphics;

namespace OtterWorks.Desktop.WinUI.Views
{
    public sealed partial class MainWindow : Window
    {
        private const int WindowWidth = 960;
        private const int WindowHeight = 640;

        public MainWindow(MainViewModel viewModel)
        {
            ViewModel = viewModel;
            InitializeComponent();

            SizeAndCenter();
            ViewModel.PropertyChanged += OnViewModelPropertyChanged;
            ShowCurrentView();
        }

        public MainViewModel ViewModel { get; }

        private void OnViewModelPropertyChanged(object sender, PropertyChangedEventArgs e)
        {
            if (e.PropertyName == nameof(MainViewModel.CurrentViewModel))
            {
                ShowCurrentView();
            }
        }

        // WinUI has no implicit DataTemplates keyed by type, so map each view model to its view here.
        private void ShowCurrentView()
        {
            CurrentView.Content = ViewModel.CurrentViewModel switch
            {
                LoginViewModel login => new LoginView(login),
                RegisterViewModel register => new RegisterView(register),
                _ => new TextBlock
                {
                    Text = "This screen has not been ported to WinUI yet.",
                    HorizontalAlignment = HorizontalAlignment.Center,
                    VerticalAlignment = VerticalAlignment.Center,
                },
            };
        }

        // Matches the WPF window: 960x640 device-independent pixels, centered on screen.
        private void SizeAndCenter()
        {
            double scale = GetDpiForWindow(WinRT.Interop.WindowNative.GetWindowHandle(this)) / 96.0;
            var size = new SizeInt32((int)(WindowWidth * scale), (int)(WindowHeight * scale));
            RectInt32 work = DisplayArea.GetFromWindowId(AppWindow.Id, DisplayAreaFallback.Primary).WorkArea;
            AppWindow.MoveAndResize(new RectInt32(
                work.X + ((work.Width - size.Width) / 2),
                work.Y + ((work.Height - size.Height) / 2),
                size.Width,
                size.Height));
        }

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern uint GetDpiForWindow(System.IntPtr hwnd);
    }
}
