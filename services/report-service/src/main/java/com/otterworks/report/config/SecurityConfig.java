package com.otterworks.report.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.header.writers.XXssProtectionHeaderWriter;

/**
 * Security configuration for the report service.
 *
 * Stateless (no session), CSRF disabled for the JSON API, and the health,
 * actuator, OpenAPI and report endpoints are open. Frame options are denied and
 * the content-type-options / XSS protection headers are written on every response.
 *
 * Nothing is authenticated yet, so the terminal rule permits the remainder —
 * without it Spring Security 6 would answer every unmapped path, and the /error
 * dispatch behind a 4xx/5xx, with an empty 403.
 */
@Configuration
@EnableWebSecurity
public class SecurityConfig {

    @Bean
    SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http // nosemgrep: java.spring.security.audit.spring-csrf-disabled.spring-csrf-disabled
                .csrf(csrf -> csrf.disable())
                .sessionManagement(session -> session
                        .sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(requests -> requests
                        .requestMatchers("/health", "/metrics", "/actuator/**").permitAll()
                        .requestMatchers("/swagger-ui.html", "/swagger-ui/**", "/swagger-resources/**",
                                "/v3/api-docs/**").permitAll()
                        .requestMatchers("/api/v1/reports/**").permitAll()  // TODO: Add JWT validation
                        .requestMatchers("/error").permitAll()
                        .anyRequest().permitAll())
                .headers(headers -> headers
                        .frameOptions(frameOptions -> frameOptions.deny())
                        .contentTypeOptions(contentTypeOptions -> {})
                        .xssProtection(xss -> xss
                                .headerValue(XXssProtectionHeaderWriter.HeaderValue.ENABLED_MODE_BLOCK)));
        return http.build();
    }
}
