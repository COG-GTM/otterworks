package com.otterworks.report.security;

import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

import javax.servlet.FilterChain;
import javax.servlet.ServletException;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.Arrays;
import java.util.List;
import java.util.stream.Collectors;

/**
 * Authenticates from the {@code X-User-ID} / {@code X-User-Roles} headers that api-gateway
 * sets from the JWT it validated (it drops any client-supplied copies). Only installed when
 * no JWT secret is configured, i.e. where the service is reachable through the gateway only.
 */
public class GatewayIdentityFilter extends OncePerRequestFilter {

    static final String USER_ID_HEADER = "X-User-ID";
    static final String ROLES_HEADER = "X-User-Roles";

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String userId = request.getHeader(USER_ID_HEADER);
        if (userId != null && !userId.trim().isEmpty()) {
            authenticate(new ReportCaller(userId.trim(), parseRoles(request.getHeader(ROLES_HEADER))));
        }
        chain.doFilter(request, response);
    }

    static void authenticate(ReportCaller caller) {
        List<SimpleGrantedAuthority> authorities = caller.getRoles().stream()
                .map(role -> new SimpleGrantedAuthority("ROLE_" + role))
                .collect(Collectors.toList());
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(caller, null, authorities));
    }

    private static List<String> parseRoles(String header) {
        if (header == null) {
            return null;
        }
        return Arrays.stream(header.split(","))
                .map(String::trim)
                .filter(role -> !role.isEmpty())
                .collect(Collectors.toList());
    }
}
