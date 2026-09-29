package com.otterworks.portal.common;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.boot.test.context.runner.WebApplicationContextRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** What a service gets by having portal-common on its classpath. */
class PortalCommonAutoConfigurationTest {

    private final WebApplicationContextRunner runner = new WebApplicationContextRunner()
            .withConfiguration(AutoConfigurations.of(PortalCommonAutoConfiguration.class));

    @Test
    void servletApplicationGetsTheSharedBeans() {
        runner.withPropertyValues("spring.application.name=preferences-service").run(context -> {
            assertThat(context).hasSingleBean(PortalBrandingSettings.class);
            assertThat(context).hasSingleBean(HealthController.class);
            assertThat(context).hasSingleBean(GlobalExceptionHandler.class);
            assertThat(context).hasSingleBean(LegacyWebMvcConfig.class);
            assertThat(context.getBean(PortalBrandingSettings.class).bannerText())
                    .isEqualTo("OtterWorks Portal (on-prem) - contact portal-support@otterworks.example");
        });
    }

    @Test
    void healthServiceNameDefaultsToSpringApplicationName() {
        runner.withPropertyValues("spring.application.name=preferences-service").run(context ->
                assertThat(context.getBean(HealthController.class).health())
                        .containsEntry("service", "preferences-service"));
    }

    @Test
    void healthServiceNameCanBeSetExplicitly() {
        runner.withPropertyValues(
                        "spring.application.name=preferences-service",
                        "portal.common.service-name=preferences")
                .run(context -> assertThat(context.getBean(HealthController.class).health())
                        .containsEntry("service", "preferences"));
    }

    @Test
    void serviceBeansTakePrecedence() {
        runner.withUserConfiguration(CustomBranding.class).run(context -> {
            assertThat(context).hasSingleBean(PortalBrandingSettings.class);
            assertThat(context.getBean(PortalBrandingSettings.class)).isSameAs(CustomBranding.INSTANCE);
        });
    }

    @Test
    void nonWebApplicationGetsNothing() {
        new ApplicationContextRunner()
                .withConfiguration(AutoConfigurations.of(PortalCommonAutoConfiguration.class))
                .run(context -> assertThat(context).doesNotHaveBean(HealthController.class)
                        .doesNotHaveBean(GlobalExceptionHandler.class)
                        .doesNotHaveBean(PortalBrandingSettings.class));
    }

    @Configuration(proxyBeanMethods = false)
    static class CustomBranding {
        static final PortalBrandingSettings INSTANCE = new PortalBrandingSettings();

        @Bean
        PortalBrandingSettings customBranding() {
            return INSTANCE;
        }
    }
}
