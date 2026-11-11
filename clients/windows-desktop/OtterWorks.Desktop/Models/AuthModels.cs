using Newtonsoft.Json;

namespace OtterWorks.Desktop.Models
{
    /// <summary>Request body for POST /auth/register.</summary>
    public class RegisterRequest
    {
        [JsonProperty("displayName")]
        public string DisplayName { get; set; }

        [JsonProperty("email")]
        public string Email { get; set; }

        [JsonProperty("password")]
        public string Password { get; set; }
    }

    /// <summary>Request body for POST /auth/login.</summary>
    public class LoginRequest
    {
        [JsonProperty("email")]
        public string Email { get; set; }

        [JsonProperty("password")]
        public string Password { get; set; }
    }

    /// <summary>
    /// Response body for /auth/login. Auth payloads are camelCase.
    /// </summary>
    public class AuthResponse
    {
        [JsonProperty("accessToken")]
        public string AccessToken { get; set; }

        [JsonProperty("refreshToken")]
        public string RefreshToken { get; set; }

        [JsonProperty("tokenType")]
        public string TokenType { get; set; }

        [JsonProperty("expiresIn")]
        public long ExpiresIn { get; set; }

        [JsonProperty("user")]
        public AuthUser User { get; set; }
    }

    public class AuthUser
    {
        [JsonProperty("id")]
        public string Id { get; set; }

        [JsonProperty("email")]
        public string Email { get; set; }

        [JsonProperty("displayName")]
        public string DisplayName { get; set; }
    }
}
