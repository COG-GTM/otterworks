package com.otterworks.report.config;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.env.EnvironmentPostProcessor;
import org.springframework.core.Ordered;
import org.springframework.core.env.ConfigurableEnvironment;
import org.springframework.util.StringUtils;

/**
 * Fails startup before any connection attempt when the PostgreSQL password is
 * not supplied (DB_PASSWORD unset or empty). There is deliberately no default
 * credential in application.properties.
 */
public class DatasourceCredentialsValidator implements EnvironmentPostProcessor, Ordered {

    static final String PASSWORD_PROPERTY = "spring.datasource.password";
    static final String URL_PROPERTY = "spring.datasource.url";

    @Override
    public void postProcessEnvironment(ConfigurableEnvironment environment, SpringApplication application) {
        String password;
        try {
            password = environment.getProperty(PASSWORD_PROPERTY);
        } catch (IllegalArgumentException unresolved) {
            throw missingPassword(unresolved);
        }
        String url = environment.getProperty(URL_PROPERTY, "");
        if (url.startsWith("jdbc:postgresql:") && !StringUtils.hasText(password)) {
            throw missingPassword(null);
        }
    }

    private static IllegalStateException missingPassword(Throwable cause) {
        return new IllegalStateException(
                "DB_PASSWORD must be set: report-service has no default database password", cause);
    }

    @Override
    public int getOrder() {
        return Ordered.LOWEST_PRECEDENCE;
    }
}
