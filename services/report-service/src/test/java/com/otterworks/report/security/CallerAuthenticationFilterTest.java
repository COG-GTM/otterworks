package com.otterworks.report.security;

import org.junit.After;
import org.junit.Test;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

public class CallerAuthenticationFilterTest {

    private static final long FUTURE = System.currentTimeMillis() / 1000 + 3600;

    @After
    public void clearContext() {
        SecurityContextHolder.clearContext();
    }

    private ReportCaller authenticate(String secret, MockHttpServletRequest request) throws Exception {
        SecurityContextHolder.clearContext();
        new CallerAuthenticationFilter(secret).doFilter(request, new MockHttpServletResponse(), new MockFilterChain());
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        return auth == null ? null : (ReportCaller) auth.getPrincipal();
    }

    private MockHttpServletRequest withToken(String token) {
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/v1/reports");
        request.addHeader("Authorization", "Bearer " + token);
        return request;
    }

    @Test
    public void validTokenEstablishesCallerAndRoles() throws Exception {
        for (String alg : new String[] {"HS256", "HS384", "HS512"}) {
            ReportCaller caller = authenticate(TestTokens.SECRET,
                    withToken(TestTokens.token(TestTokens.SECRET, alg, "alice", "access", FUTURE, "USER", "ADMIN")));
            assertNotNull(alg, caller);
            assertEquals("alice", caller.getUserId());
            assertTrue(caller.isAdmin());
        }
    }

    @Test
    public void tokenSignedWithAnotherSecretIsRejected() throws Exception {
        assertNull(authenticate(TestTokens.SECRET,
                withToken(TestTokens.token("some-other-secret-value-0123456789abcdef", "HS384",
                        "alice", "access", FUTURE, "ADMIN"))));
    }

    @Test
    public void unsignedTokenIsRejected() throws Exception {
        assertNull(authenticate(TestTokens.SECRET,
                withToken(TestTokens.token(TestTokens.SECRET, "none", "alice", "access", FUTURE, "ADMIN"))));
    }

    @Test
    public void expiredTokenIsRejected() throws Exception {
        assertNull(authenticate(TestTokens.SECRET,
                withToken(TestTokens.token(TestTokens.SECRET, "HS384", "alice", "access",
                        System.currentTimeMillis() / 1000 - 10))));
    }

    @Test
    public void refreshTokenIsRejected() throws Exception {
        assertNull(authenticate(TestTokens.SECRET,
                withToken(TestTokens.token(TestTokens.SECRET, "HS384", "alice", "refresh", FUTURE))));
    }

    @Test
    public void gatewayHeadersAreIgnoredWhenSecretIsConfigured() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/v1/reports");
        request.addHeader("X-User-ID", "alice");
        request.addHeader("X-User-Roles", "ADMIN");
        assertNull(authenticate(TestTokens.SECRET, request));
    }

    @Test
    public void gatewayHeadersAreUsedWithoutSecret() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/v1/reports");
        request.addHeader("X-User-ID", "bob");
        request.addHeader("X-User-Roles", "USER");
        ReportCaller caller = authenticate("", request);
        assertNotNull(caller);
        assertEquals("bob", caller.getUserId());
        assertFalse(caller.isAdmin());
    }

    @Test
    public void noCredentialsLeavesRequestAnonymous() throws Exception {
        assertNull(authenticate(TestTokens.SECRET, new MockHttpServletRequest("GET", "/api/v1/reports")));
        assertNull(authenticate("", new MockHttpServletRequest("GET", "/api/v1/reports")));
    }
}
