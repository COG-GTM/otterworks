using System.Text.Json.Serialization;

namespace OtterWorks.Desktop.Models
{
    /// <summary>Request body for POST /auth/register.</summary>
    public class RegisterRequest
    {
        [JsonPropertyName("displayName")]
        public string DisplayName { get; set; }

        [JsonPropertyName("email")]
        public string Email { get; set; }

        [JsonPropertyName("password")]
        public string Password { get; set; }
    }

    /// <summary>Request body for POST /auth/login.</summary>
    public class LoginRequest
    {
        [JsonPropertyName("email")]
        public string Email { get; set; }

        [JsonPropertyName("password")]
        public string Password { get; set; }
    }

    /// <summary>
    /// Response body for /auth/register and /auth/login. Auth payloads are camelCase.
    /// </summary>
    public class AuthResponse
    {
        [JsonPropertyName("accessToken")]
        public string AccessToken { get; set; }

        [JsonPropertyName("refreshToken")]
        public string RefreshToken { get; set; }

        [JsonPropertyName("tokenType")]
        public string TokenType { get; set; }

        [JsonPropertyName("expiresIn")]
        public long ExpiresIn { get; set; }

        [JsonPropertyName("user")]
        public AuthUser User { get; set; }
    }

    public class AuthUser
    {
        [JsonPropertyName("id")]
        public string Id { get; set; }

        [JsonPropertyName("email")]
        public string Email { get; set; }

        [JsonPropertyName("displayName")]
        public string DisplayName { get; set; }
    }
}
