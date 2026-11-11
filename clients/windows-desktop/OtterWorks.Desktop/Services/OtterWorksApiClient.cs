using System;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using OtterWorks.Desktop.Models;

namespace OtterWorks.Desktop.Services
{
    /// <summary>
    /// Thin REST client for the OtterWorks API gateway. Auth payloads are camelCase and
    /// document/file payloads are snake_case; each model carries explicit
    /// <c>[JsonProperty]</c> attributes so a single serializer handles both shapes.
    /// </summary>
    public class OtterWorksApiClient
    {
        private readonly HttpClient _http;
        private readonly SessionState _session;
        private readonly string _baseUrl;

        public OtterWorksApiClient(AppSettings settings, SessionState session)
        {
            if (settings == null)
            {
                throw new ArgumentNullException(nameof(settings));
            }

            _session = session ?? throw new ArgumentNullException(nameof(session));
            _baseUrl = settings.ApiBaseUrl.TrimEnd('/');

            _http = new HttpClient { Timeout = TimeSpan.FromSeconds(30) };
        }

        public async Task<AuthResponse> RegisterAsync(string displayName, string email, string password)
        {
            // Register never says whether the email was new, so sign in to get tokens.
            var body = new RegisterRequest { DisplayName = displayName, Email = email, Password = password };
            await PostAsync<object>("/auth/register", body, authenticated: false).ConfigureAwait(false);
            return await LoginAsync(email, password).ConfigureAwait(false);
        }

        public async Task<AuthResponse> LoginAsync(string email, string password)
        {
            var body = new LoginRequest { Email = email, Password = password };
            return await PostAsync<AuthResponse>("/auth/login", body, authenticated: false)
                .ConfigureAwait(false);
        }

        public async Task<DocumentListResponse> GetDocumentsAsync(int page = 1, int size = 50)
        {
            string path = $"/documents?page={page}&size={size}";
            return await GetAsync<DocumentListResponse>(path).ConfigureAwait(false);
        }

        public async Task<Document> CreateDocumentAsync(string title)
        {
            var body = new CreateDocumentRequest { Title = title };
            return await PostAsync<Document>("/documents", body, authenticated: true)
                .ConfigureAwait(false);
        }

        public async Task<FileListResponse> GetFilesAsync(int page = 1, int pageSize = 50)
        {
            string path = $"/files?page={page}&page_size={pageSize}";
            return await GetAsync<FileListResponse>(path).ConfigureAwait(false);
        }

        private async Task<T> GetAsync<T>(string path)
        {
            using (var request = new HttpRequestMessage(HttpMethod.Get, BuildUri(path)))
            {
                ApplyAuth(request);
                return await SendAsync<T>(request).ConfigureAwait(false);
            }
        }

        private async Task<T> PostAsync<T>(string path, object body, bool authenticated)
        {
            using (var request = new HttpRequestMessage(HttpMethod.Post, BuildUri(path)))
            {
                string json = JsonConvert.SerializeObject(body);
                request.Content = new StringContent(json, Encoding.UTF8, "application/json");
                if (authenticated)
                {
                    ApplyAuth(request);
                }

                return await SendAsync<T>(request).ConfigureAwait(false);
            }
        }

        private async Task<T> SendAsync<T>(HttpRequestMessage request)
        {
            HttpResponseMessage response;
            try
            {
                response = await _http.SendAsync(request).ConfigureAwait(false);
            }
            catch (HttpRequestException ex)
            {
                throw new ApiException(
                    0,
                    "Could not reach the OtterWorks backend. Verify it is running and that the " +
                    "API base URL is correct.\n\n" + ex.Message);
            }
            catch (TaskCanceledException)
            {
                throw new ApiException(
                    0,
                    "The request to the OtterWorks backend timed out. Verify the server is " +
                    "running and responsive.");
            }

            using (response)
            {
                string content = response.Content == null
                    ? string.Empty
                    : await response.Content.ReadAsStringAsync().ConfigureAwait(false);

                if (!response.IsSuccessStatusCode)
                {
                    throw new ApiException(response.StatusCode, ExtractError(content, response.StatusCode));
                }

                if (string.IsNullOrWhiteSpace(content))
                {
                    return default(T);
                }

                try
                {
                    return JsonConvert.DeserializeObject<T>(content);
                }
                catch (JsonException)
                {
                    throw new ApiException(
                        response.StatusCode,
                        "The OtterWorks backend returned an unexpected (non-JSON) response.");
                }
            }
        }

        private void ApplyAuth(HttpRequestMessage request)
        {
            if (!string.IsNullOrEmpty(_session.AccessToken))
            {
                request.Headers.TryAddWithoutValidation("Authorization", "Bearer " + _session.AccessToken);
            }
        }

        private Uri BuildUri(string path)
        {
            return new Uri(_baseUrl + "/" + path.TrimStart('/'));
        }

        private static string ExtractError(string content, HttpStatusCode statusCode)
        {
            if (!string.IsNullOrWhiteSpace(content))
            {
                try
                {
                    JToken token = JToken.Parse(content);
                    if (token.Type == JTokenType.Object)
                    {
                        var obj = (JObject)token;
                        foreach (string key in new[] { "message", "error", "detail" })
                        {
                            JToken value = obj[key];
                            if (value != null && value.Type != JTokenType.Null)
                            {
                                return value.ToString();
                            }
                        }
                    }
                }
                catch (JsonException)
                {
                    // Not JSON; fall through to returning the raw content.
                }

                return content;
            }

            return $"Request failed with status {(int)statusCode} ({statusCode}).";
        }
    }
}
