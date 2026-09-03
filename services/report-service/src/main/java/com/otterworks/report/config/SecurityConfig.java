package com.otterworks.report.config;

import jakarta.servlet.DispatcherType;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.header.writers.XXssProtectionHeaderWriter;

/**
 * Security configuration as a {@link SecurityFilterChain} bean (Spring Security 6 style).
 */
@Configuration
@EnableWebSecurity
public class SecurityConfig {

    @Bean
    SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http // nosemgrep: java.spring.security.audit.spring-csrf-disabled.spring-csrf-disabled
                .csrf(csrf -> csrf.disable())
                .sessionManagement(management -> management
                        .sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(requests -> requests
                        .dispatcherTypeMatchers(DispatcherType.ERROR).permitAll()
                        .requestMatchers("/health", "/metrics", "/actuator/**").permitAll()
                        .requestMatchers("/swagger-ui/**", "/swagger-ui.html", "/v3/api-docs/**").permitAll()
                        .requestMatchers("/api/v1/reports/**").permitAll())  // TODO: Add JWT validation
                .headers(headers -> headers
                        .frameOptions(options -> options.deny())
                        .contentTypeOptions(options -> {})
                        .xssProtection(protection -> protection
                                .headerValue(XXssProtectionHeaderWriter.HeaderValue.ENABLED_MODE_BLOCK)));
        return http.build();
    }
}
