using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using OtterWorks.Desktop.Models;

namespace OtterWorks.Desktop.Services
{
    /// <summary>
    /// Holds the authenticated session (JWT access token + current user) in memory.
    /// When <see cref="AppSettings.PersistTokens"/> is enabled the session is also written
    /// to disk protected with the Windows Data Protection API (DPAPI, per-user scope), so
    /// tokens are never stored in plaintext.
    /// </summary>
    public class SessionState
    {
        private readonly bool _persist;
        private readonly string _storePath;

        public SessionState(bool persist)
        {
            _persist = persist;
            string dir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                "OtterWorks");
            _storePath = Path.Combine(dir, "session.dat");
        }

        public string AccessToken { get; private set; }

        public string RefreshToken { get; private set; }

        public AuthUser User { get; private set; }

        public bool IsAuthenticated => !string.IsNullOrEmpty(AccessToken);

        public void SetSession(AuthResponse response)
        {
            if (response == null)
            {
                throw new ArgumentNullException(nameof(response));
            }

            AccessToken = response.AccessToken;
            RefreshToken = response.RefreshToken;
            User = response.User;

            if (_persist)
            {
                Save();
            }
        }

        public void Clear()
        {
            AccessToken = null;
            RefreshToken = null;
            User = null;

            if (_persist)
            {
                TryDelete();
            }
        }

        /// <summary>Attempts to restore a persisted session. Returns true if one was loaded.</summary>
        public bool TryRestore()
        {
            if (!_persist || !File.Exists(_storePath))
            {
                return false;
            }

            try
            {
                byte[] protectedBytes = File.ReadAllBytes(_storePath);
                byte[] plainBytes = ProtectedData.Unprotect(protectedBytes, null, DataProtectionScope.CurrentUser);
                string json = Encoding.UTF8.GetString(plainBytes);
                PersistedSession session = JsonSerializer.Deserialize<PersistedSession>(json, AppJson.Options);
                if (session != null && !string.IsNullOrEmpty(session.AccessToken))
                {
                    AccessToken = session.AccessToken;
                    RefreshToken = session.RefreshToken;
                    User = session.User;
                    return true;
                }
            }
            catch
            {
                TryDelete();
            }

            return false;
        }

        private void Save()
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(_storePath));
                var session = new PersistedSession
                {
                    AccessToken = AccessToken,
                    RefreshToken = RefreshToken,
                    User = User,
                };
                byte[] plainBytes = Encoding.UTF8.GetBytes(AppJson.Serialize(session, typeof(PersistedSession)));
                byte[] protectedBytes = ProtectedData.Protect(plainBytes, null, DataProtectionScope.CurrentUser);
                File.WriteAllBytes(_storePath, protectedBytes);
            }
            catch
            {
                // Persistence is best-effort; the in-memory session still works.
            }
        }

        private void TryDelete()
        {
            try
            {
                if (File.Exists(_storePath))
                {
                    File.Delete(_storePath);
                }
            }
            catch
            {
                // Ignore cleanup failures.
            }
        }

        private class PersistedSession
        {
            public string AccessToken { get; set; }

            public string RefreshToken { get; set; }

            public AuthUser User { get; set; }
        }
    }
}
