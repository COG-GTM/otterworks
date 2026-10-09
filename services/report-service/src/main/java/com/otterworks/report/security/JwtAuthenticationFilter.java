package com.otterworks.report.security;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.JwtParser;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

import javax.crypto.SecretKey;
import javax.servlet.FilterChain;
import javax.servlet.ServletException;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.Locale;

/**
 * Verifies the bearer JWT issued by auth-service (HMAC, shared JWT_SECRET) and populates the
 * security context with the caller's user ID and roles. Requests without a valid access token
 * stay unauthenticated and are rejected by {@link com.otterworks.report.config.SecurityConfig}.
 *
 * The gateway-injected X-User-ID header is deliberately ignored: report-service is reachable
 * inside a tenant namespace without passing through the gateway.
 */
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    private static final Logger logger = LoggerFactory.getLogger(JwtAuthenticationFilter.class);
    private static final String BEARER_PREFIX = "Bearer ";

    private final JwtParser parser;

    public JwtAuthenticationFilter(String secret) {
        this.parser = buildParser(secret);
    }

    private static JwtParser buildParser(String secret) {
        if (secret == null || secret.trim().isEmpty()) {
            logger.error("JWT_SECRET is not configured; all report API requests will be rejected");
            return null;
        }
        try {
            SecretKey key = Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
            return Jwts.parserBuilder().setSigningKey(key).build();
        } catch (io.jsonwebtoken.security.WeakKeyException e) {
            logger.error("JWT_SECRET is too short for HMAC-SHA256; all report API requests will be rejected");
            return null;
        }
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String header = request.getHeader(HttpHeaders.AUTHORIZATION);
        if (parser != null && header != null && header.startsWith(BEARER_PREFIX)) {
            authenticate(header.substring(BEARER_PREFIX.length()).trim());
        }
        chain.doFilter(request, response);
    }

    private void authenticate(String token) {
        Claims claims;
        try {
            claims = parser.parseClaimsJws(token).getBody();
        } catch (JwtException | IllegalArgumentException e) {
            logger.debug("Rejected report API token: {}", e.getClass().getSimpleName());
            return;
        }

        String type = claims.get("type", String.class);
        if (type != null && !"access".equals(type)) {
            logger.debug("Rejected non-access token of type {}", type);
            return;
        }

        String userId = claims.getSubject();
        if (userId == null || userId.trim().isEmpty()) {
            userId = claims.get("user_id", String.class);
        }
        if (userId == null || userId.trim().isEmpty()) {
            return;
        }

        List<GrantedAuthority> authorities = new ArrayList<>();
        Object roles = claims.get("roles");
        if (roles instanceof Collection) {
            for (Object role : (Collection<?>) roles) {
                if (role != null) {
                    authorities.add(new SimpleGrantedAuthority(
                            "ROLE_" + role.toString().trim().toUpperCase(Locale.ROOT)));
                }
            }
        }

        UsernamePasswordAuthenticationToken authentication =
                new UsernamePasswordAuthenticationToken(userId, null, authorities);
        SecurityContextHolder.getContext().setAuthentication(authentication);
    }
}
