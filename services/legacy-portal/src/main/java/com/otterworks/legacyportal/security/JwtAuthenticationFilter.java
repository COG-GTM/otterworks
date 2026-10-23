package com.otterworks.legacyportal.security;

import java.io.IOException;
import java.util.List;
import java.util.stream.Collectors;
import javax.servlet.FilterChain;
import javax.servlet.ServletException;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

/** Authenticates {@code Authorization: Bearer <access token>} requests. */
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    private static final String BEARER = "Bearer ";

    private final JwtAccessTokenVerifier verifier;

    public JwtAuthenticationFilter(JwtAccessTokenVerifier verifier) {
        this.verifier = verifier;
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String header = request.getHeader("Authorization");
        if (header != null && header.startsWith(BEARER)) {
            verifier.verify(header.substring(BEARER.length()).trim())
                    .ifPresent(
                            principal -> {
                                List<SimpleGrantedAuthority> authorities =
                                        principal.getRoles().stream()
                                                .map(role -> new SimpleGrantedAuthority("ROLE_" + role))
                                                .collect(Collectors.toList());
                                SecurityContextHolder.getContext()
                                        .setAuthentication(
                                                new UsernamePasswordAuthenticationToken(
                                                        principal, null, authorities));
                            });
        }
        chain.doFilter(request, response);
    }
}
