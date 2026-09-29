package com.otterworks.portal.common;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.boot.SpringApplication;
import org.springframework.core.env.MapPropertySource;
import org.springframework.core.env.StandardEnvironment;

/** The pinned Boot 3 web defaults and their precedence. */
class PortalCommonEnvironmentPostProcessorTest {

    private final PortalCommonEnvironmentPostProcessor processor = new PortalCommonEnvironmentPostProcessor();

    @Test
    void suppliesThePinnedDefaults() {
        StandardEnvironment environment = new StandardEnvironment();
        processor.postProcessEnvironment(environment, new SpringApplication());

        assertThat(environment.getProperty("server.error.include-message")).isEqualTo("never");
        assertThat(environment.getProperty("server.error.include-binding-errors")).isEqualTo("never");
        assertThat(environment.getProperty("server.error.include-stacktrace")).isEqualTo("never");
        assertThat(environment.getProperty("server.error.include-exception")).isEqualTo("false");
        assertThat(environment.getProperty("spring.mvc.problemdetails.enabled")).isEqualTo("false");
    }

    @Test
    void serviceConfigurationStillWins() {
        StandardEnvironment environment = new StandardEnvironment();
        environment.getPropertySources().addFirst(new MapPropertySource(
                "service", Map.of("server.error.include-message", "always")));
        processor.postProcessEnvironment(environment, new SpringApplication());

        assertThat(environment.getProperty("server.error.include-message")).isEqualTo("always");
        assertThat(environment.getPropertySources().stream().reduce((first, second) -> second).orElseThrow().getName())
                .isEqualTo(PortalCommonEnvironmentPostProcessor.PROPERTY_SOURCE_NAME);
    }

    @Test
    void isIdempotent() {
        StandardEnvironment environment = new StandardEnvironment();
        processor.postProcessEnvironment(environment, new SpringApplication());
        processor.postProcessEnvironment(environment, new SpringApplication());

        assertThat(environment.getPropertySources().stream()
                        .filter(source -> source.getName().equals(PortalCommonEnvironmentPostProcessor.PROPERTY_SOURCE_NAME)))
                .hasSize(1);
    }
}
