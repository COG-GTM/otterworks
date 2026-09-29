package com.otterworks.portal.common;

import org.springframework.boot.autoconfigure.AutoConfiguration;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication.Type;
import org.springframework.context.annotation.Bean;
import org.springframework.core.env.Environment;

/**
 * Shared portal infrastructure for every portal service: branding settings, {@code /health},
 * the JSON error mapping and trailing-slash matching. The framework defaults that go with it
 * ({@code server.error.include-*}, {@code spring.mvc.problemdetails.enabled}) are supplied by
 * {@link PortalCommonEnvironmentPostProcessor}.
 */
@AutoConfiguration
@ConditionalOnWebApplication(type = Type.SERVLET)
public class PortalCommonAutoConfiguration {

    /** Overrides the {@code service} field of {@code /health}; defaults to {@code spring.application.name}. */
    public static final String SERVICE_NAME_PROPERTY = "portal.common.service-name";

    @Bean
    @ConditionalOnMissingBean
    public PortalBrandingSettings portalBrandingSettings() {
        return new PortalBrandingSettings();
    }

    @Bean
    @ConditionalOnMissingBean
    public HealthController portalHealthController(
            Environment environment, PortalBrandingSettings branding) {
        String serviceName = environment.getProperty(
                SERVICE_NAME_PROPERTY, environment.getProperty("spring.application.name", "application"));
        return new HealthController(serviceName, branding);
    }

    @Bean
    @ConditionalOnMissingBean
    public GlobalExceptionHandler portalGlobalExceptionHandler() {
        return new GlobalExceptionHandler();
    }

    @Bean
    @ConditionalOnMissingBean
    public LegacyWebMvcConfig portalLegacyWebMvcConfig() {
        return new LegacyWebMvcConfig();
    }
}
