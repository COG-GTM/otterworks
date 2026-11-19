using System;
using System.Threading.Tasks;
using System.Windows.Input;

namespace OtterWorks.Desktop.Mvvm
{
    /// <summary>A basic synchronous <see cref="ICommand"/> implementation.</summary>
    public class RelayCommand : ICommand, IRequeryable
    {
        private readonly Action _execute;
        private readonly Func<bool> _canExecute;

        public RelayCommand(Action execute, Func<bool> canExecute = null)
        {
            _execute = execute ?? throw new ArgumentNullException(nameof(execute));
            _canExecute = canExecute;
            CommandManager.Register(this);
        }

        public event EventHandler CanExecuteChanged;

        public bool CanExecute(object parameter) => _canExecute == null || _canExecute();

        public void Execute(object parameter) => _execute();

        void IRequeryable.RaiseCanExecuteChanged() => CanExecuteChanged?.Invoke(this, EventArgs.Empty);
    }

    /// <summary>
    /// An <see cref="ICommand"/> that runs an async delegate and guards against re-entrancy
    /// while the operation is in flight.
    /// </summary>
    public class AsyncRelayCommand : ICommand, IRequeryable
    {
        private readonly Func<Task> _execute;
        private readonly Func<bool> _canExecute;
        private bool _isRunning;

        public AsyncRelayCommand(Func<Task> execute, Func<bool> canExecute = null)
        {
            _execute = execute ?? throw new ArgumentNullException(nameof(execute));
            _canExecute = canExecute;
            CommandManager.Register(this);
        }

        public event EventHandler CanExecuteChanged;

        public bool CanExecute(object parameter) => !_isRunning && (_canExecute == null || _canExecute());

        public async void Execute(object parameter)
        {
            if (!CanExecute(parameter))
            {
                return;
            }

            _isRunning = true;
            CommandManager.InvalidateRequerySuggested();
            try
            {
                await _execute();
            }
            finally
            {
                _isRunning = false;
                CommandManager.InvalidateRequerySuggested();
            }
        }

        void IRequeryable.RaiseCanExecuteChanged() => CanExecuteChanged?.Invoke(this, EventArgs.Empty);
    }
}
