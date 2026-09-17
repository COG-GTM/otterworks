package com.otterworks.report.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
// LEGACY: WebSecurityConfigurerAdapter removed in Spring Security 6.
// Upgrade target: SecurityFilterChain @Bean method
import org.springframework.security.config.annotation.web.configuration.WebSecurityConfigurerAdapter;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.csrf.CookieCsrfTokenRepository;

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

    @Override
    protected void configure(HttpSecurity http) throws Exception {
        // LEGACY: Uses deprecated antMatchers() and authorizeRequests()
        // Upgrade: requestMatchers() and authorizeHttpRequests()
        http
            // CSRF protection is on. The report API itself is exempt because it is
            // stateless and bearer-token authenticated at the gateway: it holds no
            // session and sets no cookie for a cross-site request to ride on. Any
            // endpoint that does use ambient credentials is covered by the
            // double-submit cookie token.
            .csrf()
                .csrfTokenRepository(CookieCsrfTokenRepository.withHttpOnlyFalse())
                .ignoringAntMatchers("/api/v1/reports/**")
            .and()
            .sessionManagement()
                .sessionCreationPolicy(SessionCreationPolicy.STATELESS)
            .and()
            .authorizeRequests()
                // Liveness/readiness and the scrape endpoint only; the rest of the
                // actuator surface exposes internals and requires authentication.
                .antMatchers("/health", "/metrics").permitAll()
                .antMatchers("/swagger-ui/**", "/swagger-resources/**", "/v2/api-docs/**").permitAll()
                .antMatchers("/api/v1/reports/**").permitAll()  // TODO: Add JWT validation
                .anyRequest().authenticated()
            .and()
            .headers()
                .frameOptions().deny()
                .contentTypeOptions().and()
                .xssProtection().block(true);
    }
}
