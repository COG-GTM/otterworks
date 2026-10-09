package com.otterworks.report.security;

import com.otterworks.report.support.TestTokens;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.junit.After;
import org.junit.Test;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.core.context.SecurityContextHolder;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;

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

    @Test
    public void untypedTokenIsIgnored() throws Exception {
        run(new JwtAuthenticationFilter(TestTokens.SECRET), TestTokens.signedToken(TestTokens.SECRET, "user-1", null, "ADMIN"));

        assertNull(SecurityContextHolder.getContext().getAuthentication());
    }

    @Test
    public void wronglyTypedClaimsAreIgnoredNotThrown() throws Exception {
        SecretKey key = Keys.hmacShaKeyFor(TestTokens.SECRET.getBytes(StandardCharsets.UTF_8));
        String numericType = Jwts.builder().setSubject("user-1").claim("type", 7).signWith(key).compact();
        String numericUserId = Jwts.builder().claim("user_id", 42).claim("type", "access").signWith(key).compact();

        JwtAuthenticationFilter filter = new JwtAuthenticationFilter(TestTokens.SECRET);
        run(filter, numericType);
        assertNull(SecurityContextHolder.getContext().getAuthentication());
        run(filter, numericUserId);
        assertNull(SecurityContextHolder.getContext().getAuthentication());
    }

    @Test(expected = IllegalStateException.class)
    public void noCallerWithoutAuthentication() {
        ReportCaller.current();
    }
}
