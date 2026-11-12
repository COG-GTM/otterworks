package com.otterworks.report.config;

import org.springframework.security.core.authority.AuthorityUtils;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.authentication.preauth.PreAuthenticatedAuthenticationToken;
import org.springframework.web.filter.OncePerRequestFilter;

import javax.servlet.FilterChain;
import javax.servlet.ServletException;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import java.io.IOException;

/**
 * Authenticates the caller from the {@code X-User-ID} header the API gateway sets
 * after validating the JWT. The gateway strips any client-supplied value, so the
 * header identifies the signed-in user; a request without it stays anonymous.
 */
public class GatewayIdentityFilter extends OncePerRequestFilter {

    public static final String USER_ID_HEADER = "X-User-ID";

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        String userId = request.getHeader(USER_ID_HEADER);
        if (userId != null && !userId.trim().isEmpty()
                && SecurityContextHolder.getContext().getAuthentication() == null) {
            PreAuthenticatedAuthenticationToken auth = new PreAuthenticatedAuthenticationToken(
                    userId.trim(), "N/A", AuthorityUtils.createAuthorityList("ROLE_USER"));
            SecurityContextHolder.getContext().setAuthentication(auth);
        }
        chain.doFilter(request, response);
    }
}
