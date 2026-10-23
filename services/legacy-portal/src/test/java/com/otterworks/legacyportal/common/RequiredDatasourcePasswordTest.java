package com.otterworks.legacyportal.common;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;

import org.junit.jupiter.api.Test;
import org.springframework.boot.SpringApplication;
import org.springframework.mock.env.MockEnvironment;

class RequiredDatasourcePasswordTest {

    private final RequiredDatasourcePassword check = new RequiredDatasourcePassword();
    private final SpringApplication application = new SpringApplication();

    private static MockEnvironment postgres() {
        MockEnvironment environment = new MockEnvironment();
        environment.setActiveProfiles("postgres");
        return environment;
    }

    @Test
    void defaultProfileNeedsNoPassword() {
        assertDoesNotThrow(() -> check.postProcessEnvironment(new MockEnvironment(), application));
    }

    @Test
    void postgresProfileRejectsMissingPassword() {
        assertThrows(
                IllegalStateException.class,
                () -> check.postProcessEnvironment(postgres(), application));
    }

    @Test
    void postgresProfileRejectsUnresolvedPlaceholder() {
        MockEnvironment environment =
                postgres().withProperty("spring.datasource.password", "${SPRING_DATASOURCE_PASSWORD}");

        assertThrows(
                IllegalStateException.class,
                () -> check.postProcessEnvironment(environment, application));
    }

    @Test
    void postgresProfileRejectsBlankPassword() {
        MockEnvironment environment = postgres().withProperty("spring.datasource.password", " ");

        assertThrows(
                IllegalStateException.class,
                () -> check.postProcessEnvironment(environment, application));
    }

    @Test
    void postgresProfileAcceptsSuppliedPassword() {
        MockEnvironment environment =
                postgres()
                        .withProperty("spring.datasource.password", "${SPRING_DATASOURCE_PASSWORD}")
                        .withProperty("SPRING_DATASOURCE_PASSWORD", "s3cret-from-env");

        assertDoesNotThrow(() -> check.postProcessEnvironment(environment, application));
    }
}
