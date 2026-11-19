using System;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace OtterWorks.Desktop.Services
{
    /// <summary>
    /// Application configuration loaded from <c>appsettings.json</c> next to the executable.
    /// The backend base URL is configurable so the app can point at a local Docker Compose
    /// stack (the default) or any reachable OtterWorks gateway.
    /// </summary>
    public class AppSettings
    {
        private const string DefaultBaseUrl = "http://localhost:8080/api/v1";

        [JsonPropertyName("apiBaseUrl")]
        public string ApiBaseUrl { get; set; } = DefaultBaseUrl;

        [JsonPropertyName("persistTokens")]
        public bool PersistTokens { get; set; }

        public static AppSettings Load()
        {
            try
            {
                string path = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "appsettings.json");
                if (File.Exists(path))
                {
                    string json = File.ReadAllText(path);
                    AppSettings settings = JsonSerializer.Deserialize<AppSettings>(json, AppJson.Options);
                    if (settings != null && !string.IsNullOrWhiteSpace(settings.ApiBaseUrl))
                    {
                        return settings;
                    }
                }
            }
            catch
            {
                // Fall back to defaults if the settings file is missing or malformed.
            }

            return new AppSettings { ApiBaseUrl = DefaultBaseUrl };
        }
    }
}
