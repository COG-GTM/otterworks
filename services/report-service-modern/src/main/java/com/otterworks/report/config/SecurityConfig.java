package com.otterworks.report.config;

import jakarta.servlet.DispatcherType;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.header.writers.XXssProtectionHeaderWriter;

/**
 * Component-based security configuration (replaces WebSecurityConfigurerAdapter).
 * Mirrors the legacy rules; the ERROR/FORWARD dispatch permit keeps Spring Boot's /error
 * JSON bodies visible, as Spring Security 5 did, because Security 6 also authorizes error dispatches.
 */
@Configuration
@EnableWebSecurity
public class SecurityConfig {

    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        http
            .csrf(AbstractHttpConfigurer::disable) // nosemgrep: java.spring.security.audit.spring-csrf-disabled.spring-csrf-disabled
            .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(auth -> auth
                .dispatcherTypeMatchers(DispatcherType.ERROR, DispatcherType.FORWARD).permitAll()
                .requestMatchers("/health", "/metrics", "/actuator/**").permitAll()
                .requestMatchers("/swagger-ui/**", "/swagger-ui.html", "/v3/api-docs/**").permitAll()
                .requestMatchers("/api/v1/reports/**", "/api/v1/reports").permitAll() // TODO: Add JWT validation
                // Parity with legacy: no authentication mechanism is configured, so unmatched paths must reach
                // MVC and return 404 rather than 403. Add JWT validation here when the platform adopts it.
                .anyRequest().permitAll())
            .headers(headers -> headers
                .frameOptions(frame -> frame.deny())
                .contentTypeOptions(contentType -> { })
                .xssProtection(xss -> xss.headerValue(XXssProtectionHeaderWriter.HeaderValue.ENABLED_MODE_BLOCK)));
        return http.build();
    }
}
