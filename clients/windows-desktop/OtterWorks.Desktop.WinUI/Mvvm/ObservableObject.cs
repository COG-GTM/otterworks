using System.ComponentModel;
using System.Runtime.CompilerServices;

namespace OtterWorks.Desktop.Mvvm
{
    /// <summary>
    /// Base class implementing <see cref="INotifyPropertyChanged"/> for view models. Every
    /// property change also re-queries command state, which WPF's CommandManager did for us.
    /// </summary>
    public abstract class ObservableObject : INotifyPropertyChanged
    {
        public event PropertyChangedEventHandler PropertyChanged;

        protected bool SetProperty<T>(ref T field, T value, [CallerMemberName] string propertyName = null)
        {
            if (Equals(field, value))
            {
                return false;
            }

            field = value;
            OnPropertyChanged(propertyName);
            return true;
        }

        protected void OnPropertyChanged([CallerMemberName] string propertyName = null)
        {
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
            CommandManager.InvalidateRequerySuggested();
        }
    }
}
