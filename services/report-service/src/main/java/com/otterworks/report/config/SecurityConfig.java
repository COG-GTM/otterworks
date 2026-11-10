package com.otterworks.report.config;

import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.jwk.source.ImmutableSecret;
import com.nimbusds.jose.proc.JWSVerificationKeySelector;
import com.nimbusds.jose.proc.SecurityContext;
import com.nimbusds.jwt.proc.DefaultJWTProcessor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
// LEGACY: WebSecurityConfigurerAdapter removed in Spring Security 6.
// Upgrade target: SecurityFilterChain @Bean method
import org.springframework.security.config.annotation.web.configuration.WebSecurityConfigurerAdapter;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.oauth2.core.DelegatingOAuth2TokenValidator;
import org.springframework.security.oauth2.core.OAuth2Error;
import org.springframework.security.oauth2.core.OAuth2TokenValidator;
import org.springframework.security.oauth2.core.OAuth2TokenValidatorResult;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtValidators;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;

import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

/**
 * Security configuration using the deprecated WebSecurityConfigurerAdapter pattern.
 *
 * Report endpoints require an access token issued by auth-service (forwarded unchanged
 * by the api-gateway), verified with the shared HMAC secret.
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

    // auth-service signs with jjwt, which picks HS256/384/512 from the secret's length.
    private static final Set<JWSAlgorithm> ACCEPTED_ALGORITHMS =
            new HashSet<>(Arrays.asList(JWSAlgorithm.HS256, JWSAlgorithm.HS384, JWSAlgorithm.HS512));

    @Value("${otterworks.security.jwt-secret:}")
    private String jwtSecret;

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
                .antMatchers("/api/v1/reports/**", "/api/v1/reports").authenticated()
            .and()
            .oauth2ResourceServer()
                .jwt()
                    .decoder(jwtDecoder())
                .and()
            .and()
            .headers()
                .frameOptions().deny()
                .contentTypeOptions().and()
                .xssProtection().block(true);
    }

    @Bean
    public JwtDecoder jwtDecoder() {
        byte[] key;
        if (jwtSecret == null || jwtSecret.isEmpty()) {
            // Fail closed: with no shared secret configured no token can validate.
            logger.error("JWT_SECRET is not set; every report API request will be rejected with 401");
            key = new byte[64];
            new SecureRandom().nextBytes(key);
        } else {
            key = jwtSecret.getBytes(StandardCharsets.UTF_8);
        }

        DefaultJWTProcessor<SecurityContext> processor = new DefaultJWTProcessor<>();
        processor.setJWSKeySelector(
                new JWSVerificationKeySelector<>(ACCEPTED_ALGORITHMS, new ImmutableSecret<>(key)));

        NimbusJwtDecoder decoder = new NimbusJwtDecoder(processor);
        decoder.setJwtValidator(new DelegatingOAuth2TokenValidator<>(
                JwtValidators.createDefault(), SecurityConfig::validateAccessToken));
        return decoder;
    }

    private static OAuth2TokenValidatorResult validateAccessToken(Jwt jwt) {
        if (jwt.getExpiresAt() == null) {
            return invalid("Token has no expiry");
        }
        String type = jwt.getClaimAsString("type");
        if (type != null && !"access".equalsIgnoreCase(type)) {
            return invalid("Only access tokens are accepted");
        }
        String subject = jwt.getSubject();
        String userId = jwt.getClaimAsString("user_id");
        if ((subject == null || subject.trim().isEmpty()) && (userId == null || userId.trim().isEmpty())) {
            return invalid("Token has no subject");
        }
        return OAuth2TokenValidatorResult.success();
    }

    private static OAuth2TokenValidatorResult invalid(String description) {
        return OAuth2TokenValidatorResult.failure(new OAuth2Error("invalid_token", description, null));
    }
}
