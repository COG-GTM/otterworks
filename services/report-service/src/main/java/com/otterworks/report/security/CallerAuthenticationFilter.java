package com.otterworks.report.security;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import javax.servlet.FilterChain;
import javax.servlet.ServletException;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.util.Base64;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * Establishes the caller's identity for report endpoints.
 *
 * When a JWT secret is configured, the identity comes only from a valid HMAC-signed
 * access token in the Authorization header (the same token the api-gateway validated),
 * so a request that reaches this service directly cannot claim another user's identity.
 * Without a secret, the identity headers injected by the api-gateway are trusted; the
 * gateway strips client-supplied copies of them.
 */
public class CallerAuthenticationFilter extends OncePerRequestFilter {

    static final String USER_ID_HEADER = "X-User-ID";
    static final String USER_ROLES_HEADER = "X-User-Roles";

    private static final Logger logger = LoggerFactory.getLogger(CallerAuthenticationFilter.class);
    private static final Map<String, String> HMAC_ALGORITHMS = new HashMap<>();

    static {
        HMAC_ALGORITHMS.put("HS256", "HmacSHA256");
        HMAC_ALGORITHMS.put("HS384", "HmacSHA384");
        HMAC_ALGORITHMS.put("HS512", "HmacSHA512");
    }

    private final byte[] secret;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public CallerAuthenticationFilter(String jwtSecret) {
        this.secret = (jwtSecret == null || jwtSecret.isEmpty())
                ? null
                : jwtSecret.getBytes(StandardCharsets.UTF_8);
        if (this.secret == null) {
            logger.warn("JWT secret not configured: trusting api-gateway identity headers");
        }
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        ReportCaller caller = secret != null ? fromBearerToken(request) : fromGatewayHeaders(request);
        if (caller != null) {
            UsernamePasswordAuthenticationToken authentication = new UsernamePasswordAuthenticationToken(
                    caller, null,
                    caller.getRoles().stream()
                            .map(role -> new SimpleGrantedAuthority("ROLE_" + role))
                            .collect(Collectors.toList()));
            SecurityContextHolder.getContext().setAuthentication(authentication);
        }
        chain.doFilter(request, response);
    }

    private ReportCaller fromGatewayHeaders(HttpServletRequest request) {
        String userId = request.getHeader(USER_ID_HEADER);
        if (userId == null || userId.trim().isEmpty()) {
            return null;
        }
        Set<String> roles = new LinkedHashSet<>();
        String rolesHeader = request.getHeader(USER_ROLES_HEADER);
        if (rolesHeader != null) {
            for (String role : rolesHeader.split(",")) {
                addRole(roles, role);
            }
        }
        return new ReportCaller(userId.trim(), roles);
    }

    private ReportCaller fromBearerToken(HttpServletRequest request) {
        String header = request.getHeader("Authorization");
        if (header == null || !header.regionMatches(true, 0, "Bearer ", 0, 7)) {
            return null;
        }
        try {
            JsonNode claims = verify(header.substring(7).trim());
            if (claims == null) {
                return null;
            }
            if ("refresh".equals(claims.path("type").asText(null))) {
                return null;
            }
            JsonNode exp = claims.get("exp");
            if (exp == null || !exp.isNumber() || exp.asLong() * 1000L <= System.currentTimeMillis()) {
                return null;
            }
            String userId = claims.path("sub").asText("");
            if (userId.isEmpty()) {
                userId = claims.path("user_id").asText("");
            }
            if (userId.isEmpty()) {
                return null;
            }
            Set<String> roles = new LinkedHashSet<>();
            JsonNode rolesNode = claims.get("roles");
            if (rolesNode != null && rolesNode.isArray()) {
                rolesNode.forEach(role -> addRole(roles, role.asText("")));
            }
            return new ReportCaller(userId, roles);
        } catch (IOException | IllegalArgumentException | GeneralSecurityException e) {
            logger.debug("Rejected bearer token: {}", e.getMessage());
            return null;
        }
    }

    private JsonNode verify(String token) throws IOException, GeneralSecurityException {
        String[] parts = token.split("\\.", -1);
        if (parts.length != 3) {
            return null;
        }
        Base64.Decoder decoder = Base64.getUrlDecoder();
        JsonNode header = objectMapper.readTree(decoder.decode(parts[0]));
        String macAlgorithm = HMAC_ALGORITHMS.get(header.path("alg").asText(""));
        if (macAlgorithm == null) {
            return null;
        }
        Mac mac = Mac.getInstance(macAlgorithm);
        mac.init(new SecretKeySpec(secret, macAlgorithm));
        byte[] expected = mac.doFinal((parts[0] + "." + parts[1]).getBytes(StandardCharsets.US_ASCII));
        if (!MessageDigest.isEqual(expected, decoder.decode(parts[2]))) {
            return null;
        }
        JsonNode claims = objectMapper.readTree(decoder.decode(parts[1]));
        return claims.isObject() ? claims : null;
    }

    private static void addRole(Set<String> roles, String role) {
        String normalized = role.trim().toUpperCase(Locale.ROOT);
        if (normalized.startsWith("ROLE_")) {
            normalized = normalized.substring(5);
        }
        if (!normalized.isEmpty()) {
            roles.add(normalized);
        }
    }
}
