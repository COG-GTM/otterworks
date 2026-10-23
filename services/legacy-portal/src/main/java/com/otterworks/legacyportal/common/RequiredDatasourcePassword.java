package com.otterworks.legacyportal.common;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.env.EnvironmentPostProcessor;
import org.springframework.core.env.ConfigurableEnvironment;
import org.springframework.core.env.Profiles;
import org.springframework.util.StringUtils;

/**
 * Fails startup under the {@code postgres} profile when no datasource password is supplied.
 *
 * <p>Spring Boot binds an unresolved {@code ${SPRING_DATASOURCE_PASSWORD}} placeholder as the
 * literal string, so without this check the app would try to log in with that text instead of
 * refusing to start.
 */
public class RequiredDatasourcePassword implements EnvironmentPostProcessor {

    static final String PROFILE = "postgres";
    static final String PROPERTY = "spring.datasource.password";

    @Override
    public void postProcessEnvironment(
            ConfigurableEnvironment environment, SpringApplication application) {
        if (!environment.acceptsProfiles(Profiles.of(PROFILE))) {
            return;
        }
        String password;
        try {
            password = environment.getProperty(PROPERTY);
        } catch (IllegalArgumentException unresolvedPlaceholder) {
            password = null;
        }
        if (!StringUtils.hasText(password)) {
            throw new IllegalStateException(
                    "SPRING_DATASOURCE_PASSWORD must be set when the '"
                            + PROFILE
                            + "' profile is active; there is no default database password.");
        }
    }
}
