package com.otterworks.report.security;

import com.otterworks.report.support.TestTokens;
import org.junit.After;
import org.junit.Test;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.core.context.SecurityContextHolder;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

public class JwtAuthenticationFilterTest {

    @After
    public void clearContext() {
        SecurityContextHolder.clearContext();
    }

    private void run(JwtAuthenticationFilter filter, String token) throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/v1/reports");
        if (token != null) {
            request.addHeader("Authorization", "Bearer " + token);
        }
        filter.doFilter(request, new MockHttpServletResponse(), new MockFilterChain());
    }

    @Test
    public void validTokenPopulatesCallerAndRoles() throws Exception {
        run(new JwtAuthenticationFilter(TestTokens.SECRET), TestTokens.token("user-1", "USER", "ADMIN"));

        ReportCaller caller = ReportCaller.current();
        assertEquals("user-1", caller.getUserId());
        assertTrue(caller.isAdmin());
    }

    @Test
    public void plainUserIsNotAdmin() throws Exception {
        run(new JwtAuthenticationFilter(TestTokens.SECRET), TestTokens.token("user-2", "USER"));

        assertFalse(ReportCaller.current().isAdmin());
    }

    @Test
    public void missingSecretFailsClosed() throws Exception {
        run(new JwtAuthenticationFilter(""), TestTokens.token("user-1", "ADMIN"));

        assertNull(SecurityContextHolder.getContext().getAuthentication());
    }

    @Test
    public void weakSecretFailsClosed() throws Exception {
        run(new JwtAuthenticationFilter("short"), TestTokens.token("user-1", "ADMIN"));

        assertNull(SecurityContextHolder.getContext().getAuthentication());
    }

    @Test
    public void expiredOrForgedTokenIsIgnored() throws Exception {
        String forged = TestTokens.signedToken("another-secret-another-secret-another-secret", "user-1", "access", "ADMIN");
        run(new JwtAuthenticationFilter(TestTokens.SECRET), forged);

        assertNull(SecurityContextHolder.getContext().getAuthentication());
    }

    @Test(expected = IllegalStateException.class)
    public void noCallerWithoutAuthentication() {
        ReportCaller.current();
    }
}
