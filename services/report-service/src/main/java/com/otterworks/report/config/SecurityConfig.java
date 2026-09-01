package com.otterworks.report.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
// LEGACY: WebSecurityConfigurerAdapter removed in Spring Security 6.
// Upgrade target: SecurityFilterChain @Bean method
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;

/**
 * Security configuration using the deprecated WebSecurityConfigurerAdapter pattern.
 *
 * UPGRADE NOTES:
 * - Replace extends WebSecurityConfigurerAdapter with a @Bean SecurityFilterChain method
 * - Replace antMatchers() with requestMatchers()
 * - Replace authorizeRequests() with authorizeHttpRequests()
 * - Move from javax.servlet to jakarta.servlet
 */
@Configuration
@EnableWebSecurity
public class SecurityConfig {

    @Bean
    SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        // LEGACY: Uses deprecated antMatchers() and authorizeRequests()
        // Upgrade: requestMatchers() and authorizeHttpRequests()
        http // nosemgrep: java.spring.security.audit.spring-csrf-disabled.spring-csrf-disabled
                .csrf(csrf -> csrf.disable())
                .sessionManagement(management -> management
                        .sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(requests -> requests
                        .requestMatchers("/health", "/metrics", "/actuator/**").permitAll()
                        .requestMatchers("/swagger-ui/**", "/swagger-resources/**", "/v2/api-docs/**").permitAll()
                        .requestMatchers("/api/v1/reports/**").permitAll())
                .headers(headers -> headers
                        .frameOptions(options -> options.deny()
                                .contentTypeOptions())
                        .xssProtection(protection -> protection.block(true)));
        return http.build();
    }
}
