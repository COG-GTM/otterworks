package com.otterworks.legacyportal.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.Map;
import javax.servlet.http.HttpServletResponse;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

/**
 * The portal sits directly on the VM network with no gateway in front of it, so it authenticates
 * every API call itself: only health probes are anonymous, and identity always comes from the
 * verified token, never from request parameters.
 */
@Configuration
@EnableWebSecurity
public class SecurityConfig {

    @Bean
    public SecurityFilterChain securityFilterChain(
            HttpSecurity http, JwtAccessTokenVerifier verifier, ObjectMapper objectMapper)
            throws Exception {
        http.csrf().disable()
                .httpBasic().disable()
                .formLogin().disable()
                .logout().disable()
                .requestCache().disable()
                .sessionManagement().sessionCreationPolicy(SessionCreationPolicy.STATELESS)
                .and()
                .addFilterBefore(
                        new JwtAuthenticationFilter(verifier),
                        UsernamePasswordAuthenticationFilter.class)
                .authorizeRequests(
                        auth ->
                                auth.antMatchers(HttpMethod.GET, "/health", "/actuator/health", "/actuator/health/**")
                                        .permitAll()
                                        .antMatchers(HttpMethod.POST, "/api/announcements", "/api/announcements/**")
                                        .hasRole(PortalPrincipal.ADMIN_ROLE)
                                        .antMatchers("/api/**")
                                        .authenticated()
                                        .anyRequest()
                                        .denyAll())
                .exceptionHandling(
                        ex ->
                                ex.authenticationEntryPoint(
                                                (req, res, e) ->
                                                        writeError(
                                                                objectMapper,
                                                                res,
                                                                HttpStatus.UNAUTHORIZED,
                                                                "a valid bearer access token is required"))
                                        .accessDeniedHandler(
                                                (req, res, e) ->
                                                        writeError(
                                                                objectMapper,
                                                                res,
                                                                HttpStatus.FORBIDDEN,
                                                                "access denied")));
        return http.build();
    }

    private static void writeError(
            ObjectMapper objectMapper, HttpServletResponse response, HttpStatus status, String message)
            throws IOException {
        Map<String, String> body = new LinkedHashMap<>();
        body.put("error", status.getReasonPhrase());
        body.put("message", message);
        response.setStatus(status.value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        if (status == HttpStatus.UNAUTHORIZED) {
            response.setHeader("WWW-Authenticate", "Bearer");
        }
        objectMapper.writeValue(response.getOutputStream(), body);
    }
}
