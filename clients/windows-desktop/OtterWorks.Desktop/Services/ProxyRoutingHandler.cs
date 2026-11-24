#if NET
using System;
using System.Net;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;

namespace OtterWorks.Desktop.Services
{
    /// <summary>
    /// Picks the proxy for every request and redirect hop the way .NET Framework does:
    /// loopback goes direct, anything else uses the default (Windows) proxy with its PAC
    /// and failover. A handler's proxy choice applies to all of its hops, so redirects are
    /// followed here, using the same rules as <see cref="HttpClientHandler"/>.
    /// </summary>
    internal sealed class ProxyRoutingHandler : HttpMessageHandler
    {
        private const int MaxRedirects = 50;

        private readonly HttpMessageInvoker _direct =
            new HttpMessageInvoker(new HttpClientHandler { UseProxy = false, AllowAutoRedirect = false });

        private readonly HttpMessageInvoker _proxied =
            new HttpMessageInvoker(new HttpClientHandler { AllowAutoRedirect = false });

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            for (int redirects = 0; ; redirects++)
            {
                HttpMessageInvoker invoker = request.RequestUri.IsLoopback ? _direct : _proxied;
                HttpResponseMessage response =
                    await invoker.SendAsync(request, cancellationToken).ConfigureAwait(false);

                Uri location = redirects < MaxRedirects ? GetRedirectUri(request.RequestUri, response) : null;
                if (location == null)
                {
                    return response;
                }

                HttpStatusCode status = response.StatusCode;
                response.Dispose();

                if (RequiresGet(request.Method, status))
                {
                    request.Method = HttpMethod.Get;
                    request.Content = null;
                }

                request.RequestUri = location;
                request.Headers.Authorization = null;
            }
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _direct.Dispose();
                _proxied.Dispose();
            }

            base.Dispose(disposing);
        }

        private static Uri GetRedirectUri(Uri requestUri, HttpResponseMessage response)
        {
            switch (response.StatusCode)
            {
                case HttpStatusCode.MultipleChoices:
                case HttpStatusCode.Moved:
                case HttpStatusCode.Found:
                case HttpStatusCode.SeeOther:
                case HttpStatusCode.TemporaryRedirect:
                case HttpStatusCode.PermanentRedirect:
                    break;
                default:
                    return null;
            }

            Uri location = response.Headers.Location;
            if (location == null)
            {
                return null;
            }

            if (!location.IsAbsoluteUri)
            {
                location = new Uri(requestUri, location);
            }

            if (!string.IsNullOrEmpty(requestUri.Fragment) && string.IsNullOrEmpty(location.Fragment))
            {
                location = new UriBuilder(location) { Fragment = requestUri.Fragment.Substring(1) }.Uri;
            }

            bool supported = location.Scheme == Uri.UriSchemeHttp || location.Scheme == Uri.UriSchemeHttps;
            bool downgrade = requestUri.Scheme == Uri.UriSchemeHttps && location.Scheme == Uri.UriSchemeHttp;
            return supported && !downgrade ? location : null;
        }

        private static bool RequiresGet(HttpMethod method, HttpStatusCode status)
        {
            switch (status)
            {
                case HttpStatusCode.MultipleChoices:
                case HttpStatusCode.Moved:
                case HttpStatusCode.Found:
                    return method == HttpMethod.Post;
                case HttpStatusCode.SeeOther:
                    return method != HttpMethod.Get && method != HttpMethod.Head;
                default:
                    return false;
            }
        }
    }
}
#endif
