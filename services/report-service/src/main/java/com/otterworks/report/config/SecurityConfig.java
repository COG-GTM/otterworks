package com.otterworks.report.config;

import com.otterworks.report.security.JwtAuthenticationFilter;
import com.otterworks.report.security.JwtVerifier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpStatus;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
// LEGACY: WebSecurityConfigurerAdapter removed in Spring Security 6.
// Upgrade target: SecurityFilterChain @Bean method
import org.springframework.security.config.annotation.web.configuration.WebSecurityConfigurerAdapter;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.authentication.HttpStatusEntryPoint;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

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
public class SecurityConfig extends WebSecurityConfigurerAdapter {

    private static final Logger logger = LoggerFactory.getLogger(SecurityConfig.class);

    private final JwtVerifier jwtVerifier;

    public SecurityConfig(@Value("${otterworks.security.jwt-secret:}") String jwtSecret) {
        this.jwtVerifier = new JwtVerifier(jwtSecret);
        if (!jwtVerifier.isConfigured()) {
            logger.warn("JWT_SECRET is not set: every /api/v1/reports request will be rejected with 401");
        }
    }

    @Override
    protected void configure(HttpSecurity http) throws Exception {
        // LEGACY: Uses deprecated antMatchers() and authorizeRequests()
        // Upgrade: requestMatchers() and authorizeHttpRequests()
        http // nosemgrep: java.spring.security.audit.spring-csrf-disabled.spring-csrf-disabled
            .csrf().disable()
            .sessionManagement()
                .sessionCreationPolicy(SessionCreationPolicy.STATELESS)
            .and()
            .authorizeRequests()
                .antMatchers("/health", "/metrics", "/actuator/**").permitAll()
                .antMatchers("/swagger-ui/**", "/swagger-resources/**", "/v2/api-docs/**").permitAll()
                .antMatchers("/api/v1/reports/**").authenticated()
                .anyRequest().authenticated()
            .and()
            .addFilterBefore(new JwtAuthenticationFilter(jwtVerifier), UsernamePasswordAuthenticationFilter.class)
            .exceptionHandling()
                .authenticationEntryPoint(new HttpStatusEntryPoint(HttpStatus.UNAUTHORIZED))
            .and()
            .headers()
                .frameOptions().deny()
                .contentTypeOptions().and()
                .xssProtection().block(true);
    }
}
