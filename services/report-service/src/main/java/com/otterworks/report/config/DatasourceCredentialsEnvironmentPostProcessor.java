package com.otterworks.report.config;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.env.EnvironmentPostProcessor;
import org.springframework.core.Ordered;
import org.springframework.core.env.ConfigurableEnvironment;

/**
 * Fails startup when the datasource credentials are not supplied by the environment.
 *
 * Spring Boot's binder leaves unresolvable placeholders in place, so without this check
 * an unset DB_PASSWORD would be sent to Postgres as the literal string "${DB_PASSWORD}"
 * instead of stopping the service with a clear error.
 */
public class DatasourceCredentialsEnvironmentPostProcessor implements EnvironmentPostProcessor, Ordered {

    static final String[] REQUIRED_PROPERTIES = {
            "spring.datasource.username",
            "spring.datasource.password"
    };

    @Override
    public void postProcessEnvironment(ConfigurableEnvironment environment, SpringApplication application) {
        for (String property : REQUIRED_PROPERTIES) {
            String value;
            try {
                value = environment.getProperty(property);
            } catch (IllegalArgumentException unresolved) {
                throw missing(property, unresolved);
            }
            if (value == null) {
                throw missing(property, null);
            }
        }
    }

    private static IllegalStateException missing(String property, IllegalArgumentException cause) {
        return new IllegalStateException(property + " is not configured: set DB_USER and DB_PASSWORD "
                + "from the secret store; report-service ships no default database credentials", cause);
    }

    @Override
    public int getOrder() {
        return Ordered.LOWEST_PRECEDENCE;
    }
}
