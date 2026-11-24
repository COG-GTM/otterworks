using System;
using System.Net;

namespace OtterWorks.Desktop.Services
{
    /// <summary>
    /// Sends loopback requests directly instead of through a proxy, matching .NET Framework,
    /// which never proxies localhost. .NET (Core) otherwise routes them through
    /// <c>HTTP_PROXY</c> unless <c>NO_PROXY</c> excludes them.
    /// </summary>
    internal sealed class LoopbackBypassProxy : IWebProxy
    {
        private readonly IWebProxy _inner;

        public LoopbackBypassProxy(IWebProxy inner)
        {
            _inner = inner ?? throw new ArgumentNullException(nameof(inner));
        }

        public ICredentials Credentials
        {
            get { return _inner.Credentials; }
            set { _inner.Credentials = value; }
        }

        public Uri GetProxy(Uri destination)
        {
            return _inner.GetProxy(destination);
        }

        public bool IsBypassed(Uri host)
        {
            return host.IsLoopback || _inner.IsBypassed(host);
        }
    }
}
