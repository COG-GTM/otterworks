package com.otterworks.legacyportal.security;

import java.nio.charset.StandardCharsets;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.oauth2.core.DelegatingOAuth2TokenValidator;
import org.springframework.security.oauth2.core.OAuth2Error;
import org.springframework.security.oauth2.core.OAuth2TokenValidator;
import org.springframework.security.oauth2.core.OAuth2TokenValidatorResult;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtValidators;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationConverter;
import org.springframework.security.oauth2.server.resource.authentication.JwtGrantedAuthoritiesConverter;
import org.springframework.security.web.SecurityFilterChain;

/**
 * Every {@code /api/**} route requires an access token issued by auth-service (HMAC-signed with
 * the shared {@code JWT_SECRET}); the token subject is the caller's user id and its {@code roles}
 * claim maps to {@code ROLE_*} authorities. Only the health probes are anonymous.
 */
@Configuration
@EnableMethodSecurity
public class SecurityConfig {

    static final String ROLES_CLAIM = "roles";
    static final String TOKEN_TYPE_CLAIM = "type";
    static final String ACCESS_TOKEN_TYPE = "access";
    private static final int MIN_SECRET_BYTES = 32;

    @Bean
    SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        http.csrf()
                .disable()
                .sessionManagement()
                .sessionCreationPolicy(SessionCreationPolicy.STATELESS)
                .and()
                .authorizeHttpRequests(
                        auth ->
                                auth.mvcMatchers(
                                                HttpMethod.GET,
                                                "/health",
                                                "/actuator/health",
                                                "/actuator/health/**",
                                                "/actuator/info")
                                        .permitAll()
                                        .mvcMatchers(
                                                HttpMethod.POST,
                                                "/api/announcements",
                                                "/api/announcements/{id}/publish")
                                        .hasRole(PortalRoles.ADMIN)
                                        .mvcMatchers("/api/**")
                                        .authenticated()
                                        .anyRequest()
                                        .denyAll())
                .oauth2ResourceServer(
                        oauth2 ->
                                oauth2.jwt(
                                        jwt ->
                                                jwt.jwtAuthenticationConverter(
                                                        jwtAuthenticationConverter())));
        return http.build();
    }

    @Bean
    JwtDecoder jwtDecoder(@Value("${legacy-portal.security.jwt-secret:}") String secret) {
        byte[] keyBytes = secret.getBytes(StandardCharsets.UTF_8);
        if (keyBytes.length < MIN_SECRET_BYTES) {
            throw new IllegalStateException(
                    "legacy-portal.security.jwt-secret (JWT_SECRET) must be set to auth-service's"
                            + " JWT secret (at least " + MIN_SECRET_BYTES + " bytes)");
        }
        MacAlgorithm algorithm = macAlgorithmFor(keyBytes.length);
        NimbusJwtDecoder decoder =
                NimbusJwtDecoder.withSecretKey(new SecretKeySpec(keyBytes, algorithm.getName()))
                        .macAlgorithm(algorithm)
                        .build();
        decoder.setJwtValidator(
                new DelegatingOAuth2TokenValidator<>(
                        JwtValidators.createDefault(), accessTokenOnly()));
        return decoder;
    }

    /**
     * auth-service signs with jjwt's {@code Keys.hmacShaKeyFor}, which picks the strongest HMAC
     * algorithm the key length allows; accept exactly that one.
     */
    static MacAlgorithm macAlgorithmFor(int keyLength) {
        if (keyLength >= 64) {
            return MacAlgorithm.HS512;
        }
        if (keyLength >= 48) {
            return MacAlgorithm.HS384;
        }
        return MacAlgorithm.HS256;
    }

    private static OAuth2TokenValidator<Jwt> accessTokenOnly() {
        OAuth2TokenValidatorResult failure =
                OAuth2TokenValidatorResult.failure(
                        new OAuth2Error("invalid_token", "an access token is required", null));
        return jwt ->
                ACCESS_TOKEN_TYPE.equals(jwt.getClaimAsString(TOKEN_TYPE_CLAIM))
                        ? OAuth2TokenValidatorResult.success()
                        : failure;
    }

    private static JwtAuthenticationConverter jwtAuthenticationConverter() {
        JwtGrantedAuthoritiesConverter authorities = new JwtGrantedAuthoritiesConverter();
        authorities.setAuthoritiesClaimName(ROLES_CLAIM);
        authorities.setAuthorityPrefix("ROLE_");
        JwtAuthenticationConverter converter = new JwtAuthenticationConverter();
        converter.setJwtGrantedAuthoritiesConverter(authorities);
        return converter;
    }
}
