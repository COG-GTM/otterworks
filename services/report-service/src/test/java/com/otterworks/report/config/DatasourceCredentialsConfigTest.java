package com.otterworks.report.config;

import org.junit.Before;
import org.junit.Test;
import org.springframework.core.env.MapPropertySource;
import org.springframework.core.env.MutablePropertySources;
import org.springframework.core.env.StandardEnvironment;
import org.springframework.core.io.ClassPathResource;
import org.springframework.core.io.support.ResourcePropertySource;

import java.io.IOException;
import java.util.HashMap;
import java.util.Map;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

/**
 * The datasource credentials must come from the environment: application.properties
 * may not carry a fallback username/password, and startup must fail when DB_USER or
 * DB_PASSWORD is unset.
 */
public class DatasourceCredentialsConfigTest {

    private ResourcePropertySource applicationProperties;

    @Before
    public void setUp() throws IOException {
        applicationProperties = new ResourcePropertySource(new ClassPathResource("application.properties"));
    }

    @Test
    public void applicationPropertiesDoesNotCommitTheDevCredential() {
        for (String name : applicationProperties.getPropertyNames()) {
            String value = String.valueOf(applicationProperties.getProperty(name));
            assertFalse(name + " must not embed the dev password", value.contains("otterworks_dev"));
        }
    }

    @Test
    public void passwordIsUnresolvableWhenDbPasswordIsUnset() {
        StandardEnvironment environment = environmentWith(new HashMap<String, Object>());
        try {
            environment.getProperty("spring.datasource.password");
            fail("spring.datasource.password resolved without DB_PASSWORD");
        } catch (IllegalArgumentException expected) {
            assertTrue(expected.getMessage().contains("DB_PASSWORD"));
        }
    }

    @Test
    public void usernameIsUnresolvableWhenDbUserIsUnset() {
        StandardEnvironment environment = environmentWith(new HashMap<String, Object>());
        try {
            environment.getProperty("spring.datasource.username");
            fail("spring.datasource.username resolved without DB_USER");
        } catch (IllegalArgumentException expected) {
            assertTrue(expected.getMessage().contains("DB_USER"));
        }
    }

    @Test
    public void credentialsResolveFromTheEnvironment() {
        Map<String, Object> env = new HashMap<String, Object>();
        env.put("DB_USER", "reports_app");
        env.put("DB_PASSWORD", "injected-secret");
        StandardEnvironment environment = environmentWith(env);

        assertEquals("reports_app", environment.getProperty("spring.datasource.username"));
        assertEquals("injected-secret", environment.getProperty("spring.datasource.password"));
        assertEquals("jdbc:postgresql://localhost:5432/otterworks_reports",
                environment.getProperty("spring.datasource.url"));
    }

    @Test
    public void startupFailsWhenDbPasswordIsUnset() {
        Map<String, Object> env = new HashMap<String, Object>();
        env.put("DB_USER", "reports_app");
        try {
            new DatasourceCredentialsEnvironmentPostProcessor().postProcessEnvironment(environmentWith(env), null);
            fail("startup continued without DB_PASSWORD");
        } catch (IllegalStateException expected) {
            assertTrue(expected.getMessage().startsWith("spring.datasource.password is not configured"));
        }
    }

    @Test
    public void startupFailsWhenDbUserIsUnset() {
        Map<String, Object> env = new HashMap<String, Object>();
        env.put("DB_PASSWORD", "injected-secret");
        try {
            new DatasourceCredentialsEnvironmentPostProcessor().postProcessEnvironment(environmentWith(env), null);
            fail("startup continued without DB_USER");
        } catch (IllegalStateException expected) {
            assertTrue(expected.getMessage().startsWith("spring.datasource.username is not configured"));
        }
    }

    @Test
    public void startupProceedsWithInjectedCredentials() {
        Map<String, Object> env = new HashMap<String, Object>();
        env.put("DB_USER", "reports_app");
        env.put("DB_PASSWORD", "injected-secret");
        new DatasourceCredentialsEnvironmentPostProcessor().postProcessEnvironment(environmentWith(env), null);
    }

    @Test
    public void startupProceedsWithTheTestProfileEmptyPassword() throws IOException {
        StandardEnvironment environment = environmentWith(new HashMap<String, Object>());
        environment.getPropertySources().addFirst(
                new ResourcePropertySource(new ClassPathResource("application-test.properties")));
        new DatasourceCredentialsEnvironmentPostProcessor().postProcessEnvironment(environment, null);
    }

    private StandardEnvironment environmentWith(Map<String, Object> env) {
        StandardEnvironment environment = new StandardEnvironment();
        MutablePropertySources sources = environment.getPropertySources();
        sources.remove(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME);
        sources.remove(StandardEnvironment.SYSTEM_PROPERTIES_PROPERTY_SOURCE_NAME);
        sources.addFirst(new MapPropertySource("env", env));
        sources.addLast(applicationProperties);
        return environment;
    }
}
