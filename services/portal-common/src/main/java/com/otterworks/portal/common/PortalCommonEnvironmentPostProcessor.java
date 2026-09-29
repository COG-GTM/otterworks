package com.otterworks.portal.common;

import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.env.EnvironmentPostProcessor;
import org.springframework.core.env.ConfigurableEnvironment;
import org.springframework.core.env.MapPropertySource;

/**
 * Framework defaults every portal service runs with. Added as the lowest-precedence property
 * source, so a service's own configuration still overrides any of them.
 */
public class PortalCommonEnvironmentPostProcessor implements EnvironmentPostProcessor {

    public static final String PROPERTY_SOURCE_NAME = "portalCommonDefaults";

    static final Map<String, Object> DEFAULTS = defaults();

    @Override
    public void postProcessEnvironment(ConfigurableEnvironment environment, SpringApplication application) {
        if (!environment.getPropertySources().contains(PROPERTY_SOURCE_NAME)) {
            environment.getPropertySources().addLast(new MapPropertySource(PROPERTY_SOURCE_NAME, DEFAULTS));
        }
    }

    private static Map<String, Object> defaults() {
        Map<String, Object> defaults = new LinkedHashMap<>();
        // The default error body never exposes message, binding errors, exception or trace.
        defaults.put("server.error.include-message", "never");
        defaults.put("server.error.include-binding-errors", "never");
        defaults.put("server.error.include-stacktrace", "never");
        defaults.put("server.error.include-exception", "false");
        // MVC exceptions render Boot's default error body, not RFC 7807 problem details.
        defaults.put("spring.mvc.problemdetails.enabled", "false");
        return Map.copyOf(defaults);
    }
}
