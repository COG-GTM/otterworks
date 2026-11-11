package com.otterworks.report.config;

import org.junit.Test;
import org.springframework.boot.SpringApplication;
import org.springframework.core.env.MapPropertySource;
import org.springframework.core.env.StandardEnvironment;

import java.util.HashMap;
import java.util.Map;

public class DatasourceCredentialsValidatorTest {

    private static final String POSTGRES_URL = "jdbc:postgresql://localhost:5432/otterworks_reports";

    private final DatasourceCredentialsValidator validator = new DatasourceCredentialsValidator();

    private static StandardEnvironment environment(String url, String password) {
        Map<String, Object> props = new HashMap<>();
        props.put(DatasourceCredentialsValidator.URL_PROPERTY, url);
        props.put(DatasourceCredentialsValidator.PASSWORD_PROPERTY, password);
        StandardEnvironment env = new StandardEnvironment();
        env.getPropertySources().remove(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME);
        env.getPropertySources().remove(StandardEnvironment.SYSTEM_PROPERTIES_PROPERTY_SOURCE_NAME);
        env.getPropertySources().addFirst(new MapPropertySource("test", props));
        return env;
    }

    @Test(expected = IllegalStateException.class)
    public void failsWhenDbPasswordIsUnset() {
        validator.postProcessEnvironment(environment(POSTGRES_URL, "${DB_PASSWORD}"), new SpringApplication());
    }

    @Test(expected = IllegalStateException.class)
    public void failsWhenDbPasswordIsEmpty() {
        validator.postProcessEnvironment(environment(POSTGRES_URL, ""), new SpringApplication());
    }

    @Test
    public void passesWhenDbPasswordIsSet() {
        validator.postProcessEnvironment(environment(POSTGRES_URL, "s3cret"), new SpringApplication());
    }

    @Test
    public void allowsEmptyPasswordForNonPostgresDatasource() {
        validator.postProcessEnvironment(environment("jdbc:h2:mem:testdb", ""), new SpringApplication());
    }
}
