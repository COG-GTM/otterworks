package com.otterworks.report.security;

import org.springframework.http.HttpHeaders;
import org.springframework.web.filter.OncePerRequestFilter;

import javax.servlet.FilterChain;
import javax.servlet.ServletException;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.Optional;

/**
 * Authenticates requests from the {@code Authorization: Bearer} token; identity headers are
 * ignored. Requests without a valid token stay anonymous and are rejected on protected paths.
 */
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    private static final String BEARER_PREFIX = "bearer ";

    private final JwtVerifier verifier;

    public JwtAuthenticationFilter(JwtVerifier verifier) {
        this.verifier = verifier;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String header = request.getHeader(HttpHeaders.AUTHORIZATION);
        if (header != null && header.length() > BEARER_PREFIX.length()
                && header.regionMatches(true, 0, BEARER_PREFIX, 0, BEARER_PREFIX.length())) {
            Optional<ReportCaller> caller = verifier.verify(header.substring(BEARER_PREFIX.length()).trim());
            caller.ifPresent(GatewayIdentityFilter::authenticate);
        }
        chain.doFilter(request, response);
    }
}
