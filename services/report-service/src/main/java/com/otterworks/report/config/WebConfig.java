package com.otterworks.report.config;

import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.Ordered;
import org.springframework.web.filter.UrlHandlerFilter;

/**
 * Spring MVC 6 no longer matches a trailing slash ({@code /api/v1/reports/}) to
 * {@code /api/v1/reports}. Boot 2 did, and the api-gateway forwards both forms, so
 * the trailing slash is stripped before Spring Security and MVC see the request.
 */
@Configuration
public class WebConfig {

    @Bean
    public FilterRegistrationBean<UrlHandlerFilter> trailingSlashFilter() {
        FilterRegistrationBean<UrlHandlerFilter> registration = new FilterRegistrationBean<>(
                UrlHandlerFilter.trailingSlashHandler("/**").wrapRequest().build());
        registration.setOrder(Ordered.HIGHEST_PRECEDENCE);
        return registration;
    }
}
