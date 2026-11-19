using Microsoft.UI.Xaml.Controls;
using OtterWorks.Desktop.ViewModels;

namespace OtterWorks.Desktop.WinUI.Views
{
    public sealed partial class DocumentsView : UserControl
    {
        public DocumentsView(DocumentsViewModel viewModel)
        {
            ViewModel = viewModel;
            InitializeComponent();
        }

        public DocumentsViewModel ViewModel { get; }
    }
}
