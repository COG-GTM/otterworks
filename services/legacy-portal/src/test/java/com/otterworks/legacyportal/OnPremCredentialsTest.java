package com.otterworks.legacyportal;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Collections;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.junit.jupiter.api.Test;
import org.springframework.boot.env.YamlPropertySourceLoader;
import org.springframework.core.env.MapPropertySource;
import org.springframework.core.env.MutablePropertySources;
import org.springframework.core.env.PropertySource;
import org.springframework.core.env.PropertySourcesPropertyResolver;
import org.springframework.core.io.ClassPathResource;

/** The on-prem PostgreSQL stack must never fall back to a committed database password. */
class OnPremCredentialsTest {

    private static PropertySource<?> postgresProfile() throws Exception {
        List<PropertySource<?>> documents =
                new YamlPropertySourceLoader()
                        .load("application.yml", new ClassPathResource("application.yml"));
        return documents.stream()
                .filter(d -> "postgres".equals(String.valueOf(d.getProperty("spring.config.activate.on-profile"))))
                .findFirst()
                .orElseThrow(() -> new AssertionError("postgres profile missing from application.yml"));
    }

    private static PropertySourcesPropertyResolver resolver(PropertySource<?>... sources) {
        MutablePropertySources propertySources = new MutablePropertySources();
        for (PropertySource<?> source : sources) {
            propertySources.addLast(source);
        }
        return new PropertySourcesPropertyResolver(propertySources);
    }

    @Test
    void postgresProfileHasNoDefaultPassword() throws Exception {
        PropertySource<?> postgres = postgresProfile();

        assertEquals(
                "${SPRING_DATASOURCE_PASSWORD}",
                String.valueOf(postgres.getProperty("spring.datasource.password")));
        assertThrows(
                IllegalArgumentException.class,
                () -> resolver(postgres).getProperty("spring.datasource.password"));
    }

    @Test
    void postgresProfileUsesSuppliedPassword() throws Exception {
        PropertySource<?> env =
                new MapPropertySource(
                        "env", Collections.singletonMap("SPRING_DATASOURCE_PASSWORD", "s3cret-from-env"));

        assertEquals(
                "s3cret-from-env",
                resolver(env, postgresProfile()).getProperty("spring.datasource.password"));
    }

    @Test
    void onPremComposeRequiresDbPassword() throws Exception {
        String compose =
                new String(
                        Files.readAllBytes(Paths.get("docker-compose.onprem.yml")),
                        StandardCharsets.UTF_8);

        assertFalse(compose.contains("DB_PASSWORD:-"), "DB_PASSWORD must not have a default");
        Matcher passwords =
                Pattern.compile("(?m)^\\s*(POSTGRES_PASSWORD|SPRING_DATASOURCE_PASSWORD):\\s*(.+)$")
                        .matcher(compose);
        int count = 0;
        while (passwords.find()) {
            count++;
            assertTrue(
                    passwords.group(2).startsWith("${DB_PASSWORD:?"),
                    passwords.group(1) + " must require DB_PASSWORD, got: " + passwords.group(2));
        }
        assertEquals(2, count);
    }
}
