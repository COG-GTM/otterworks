package com.otterworks.auth.config;

import com.otterworks.auth.security.JwtAuthFilter;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

@Configuration
@EnableWebSecurity
@EnableMethodSecurity
public class SecurityConfig {

  static final int MIN_BCRYPT_STRENGTH = 10;
  static final int MAX_BCRYPT_STRENGTH = 14;

  private final JwtAuthFilter jwtAuthFilter;

  public SecurityConfig(JwtAuthFilter jwtAuthFilter) {
    this.jwtAuthFilter = jwtAuthFilter;
  }

  @Bean
  public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
    http.csrf(csrf -> csrf.disable()) // nosemgrep: java.spring.security.audit.spring-csrf-disabled
        .sessionManagement(
            session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
        .authorizeHttpRequests(
            auth ->
                auth.requestMatchers(
                        "/health",
                        "/metrics",
                        "/actuator/health",
                        "/actuator/info",
                        "/actuator/prometheus",
                        "/api/v1/auth/register",
                        "/api/v1/auth/login",
                        "/api/v1/auth/refresh")
                    .permitAll()
                    .requestMatchers("/api/v1/auth/users/lookup", "/api/v1/auth/users/by-id/**")
                    .authenticated()
                    .requestMatchers("/api/v1/auth/users/**")
                    .hasRole("ADMIN")
                    .anyRequest()
                    .authenticated())
        .addFilterBefore(jwtAuthFilter, UsernamePasswordAuthenticationFilter.class);
    return http.build();
  }

  @Bean
  public PasswordEncoder passwordEncoder(@Value("${security.bcrypt-strength:10}") int strength) {
    return new BCryptPasswordEncoder(requireValidStrength(strength));
  }

  static int requireValidStrength(int strength) {
    if (strength < MIN_BCRYPT_STRENGTH || strength > MAX_BCRYPT_STRENGTH) {
      throw new IllegalArgumentException(
          "security.bcrypt-strength must be between "
              + MIN_BCRYPT_STRENGTH
              + " and "
              + MAX_BCRYPT_STRENGTH
              + ", got "
              + strength);
    }
    return strength;
  }
}
