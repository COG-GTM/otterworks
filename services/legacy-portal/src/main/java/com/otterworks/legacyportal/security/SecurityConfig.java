package com.otterworks.legacyportal.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Clock;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpStatus;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.HttpStatusEntryPoint;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.security.web.firewall.HttpStatusRequestRejectedHandler;
import org.springframework.security.web.firewall.RequestRejectedHandler;

/**
 * Stateless bearer-token security. The portal runs outside the API gateway, so it verifies
 * auth-service JWTs itself. User-scoped routes ({@code /api/preferences/**}) require a token;
 * the other modules keep their existing access.
 */
@Configuration
@EnableWebSecurity
public class SecurityConfig {

    private static final Logger log = LoggerFactory.getLogger(SecurityConfig.class);

    @Bean
    public JwtVerifier jwtVerifier(
            @Value("${legacyportal.security.jwt-secret:}") String secret, ObjectMapper mapper) {
        JwtVerifier verifier = new JwtVerifier(secret, mapper, Clock.systemUTC());
        if (!verifier.isConfigured()) {
            log.warn(
                    "JWT_SECRET is not set (or shorter than {} bytes): all /api/preferences requests"
                            + " will be rejected with 401",
                    JwtVerifier.MIN_SECRET_BYTES);
        }
        return verifier;
    }

    /** Firewall-rejected URLs (e.g. encoded {@code ;} or {@code ..}) are client errors: 400. */
    @Bean
    public RequestRejectedHandler requestRejectedHandler() {
        return new HttpStatusRequestRejectedHandler();
    }

    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http, JwtVerifier verifier)
            throws Exception {
        http.csrf().disable()
                .httpBasic().disable()
                .formLogin().disable()
                .logout().disable()
                .sessionManagement().sessionCreationPolicy(SessionCreationPolicy.STATELESS)
                .and()
                .exceptionHandling()
                .authenticationEntryPoint(new HttpStatusEntryPoint(HttpStatus.UNAUTHORIZED))
                .and()
                .addFilterBefore(
                        new JwtAuthenticationFilter(verifier),
                        UsernamePasswordAuthenticationFilter.class)
                .authorizeHttpRequests(
                        auth ->
                                auth.mvcMatchers("/api/preferences", "/api/preferences/**")
                                        .authenticated()
                                        .anyRequest()
                                        .permitAll());
        return http.build();
    }
}
