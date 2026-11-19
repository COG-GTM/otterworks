using System;
using System.Collections.Generic;

namespace OtterWorks.Desktop.Mvvm
{
    /// <summary>
    /// Stand-in for WPF's CommandManager, which WinUI does not have. Commands register here
    /// (weakly, so commands of discarded view models can be collected) and are told to raise
    /// CanExecuteChanged whenever view model state changes.
    /// </summary>
    public static class CommandManager
    {
        private static readonly List<WeakReference<IRequeryable>> Commands = new List<WeakReference<IRequeryable>>();

        internal static void Register(IRequeryable command)
        {
            Commands.Add(new WeakReference<IRequeryable>(command));
        }

        public static void InvalidateRequerySuggested()
        {
            foreach (WeakReference<IRequeryable> reference in Commands.ToArray())
            {
                if (reference.TryGetTarget(out IRequeryable command))
                {
                    command.RaiseCanExecuteChanged();
                }
                else
                {
                    Commands.Remove(reference);
                }
            }
        }
    }

    internal interface IRequeryable
    {
        void RaiseCanExecuteChanged();
    }
}
