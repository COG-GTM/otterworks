package com.otterworks.announcements.platform;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.PathMatchConfigurer;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * Keeps trailing-slash URLs ({@code /api/x/} == {@code /api/x}) routable, as they were in
 * legacy-portal on Spring Framework 5.3, where trailing-slash matching was on by default. Spring 6
 * turned it off; existing portal clients still send both forms.
 *
 * <p>{@code setUseTrailingSlashMatch} is deprecated in Spring 6 and removed in 7; when moving to
 * Spring Boot 3.4+ replace this with {@code UrlHandlerFilter.trailingSlashHandler("/**")}.
 */
@Configuration(proxyBeanMethods = false)
public class LegacyPathMatchingConfig implements WebMvcConfigurer {

    @Override
    @SuppressWarnings("deprecation")
    public void configurePathMatch(PathMatchConfigurer configurer) {
        configurer.setUseTrailingSlashMatch(true);
    }
}
