package com.otterworks.legacyportal.common;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.PathMatchConfigurer;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * Keeps the portal's route matching as clients know it: {@code /api/announcements/} matches
 * {@code /api/announcements}. See DECOMPOSITION.md, "Pinned framework defaults".
 */
@Configuration
public class LegacyWebMvcConfig implements WebMvcConfigurer {

    @Override
    @SuppressWarnings("deprecation")
    public void configurePathMatch(PathMatchConfigurer configurer) {
        configurer.setUseTrailingSlashMatch(true);
    }
}
