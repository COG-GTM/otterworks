package com.otterworks.report.config;

import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Contact;
import io.swagger.v3.oas.models.info.Info;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * OpenAPI 3 configuration using springdoc-openapi.
 *
 * Swagger UI is served at /swagger-ui.html and the spec at /v3/api-docs.
 */
@Configuration
public class SwaggerConfig {

    @Bean
    public OpenAPI api() {
        return new OpenAPI().info(apiInfo());
    }

    private Info apiInfo() {
        return new Info()
                .title("OtterWorks Report Service API")
                .description("Legacy report generation service for PDF, CSV, and Excel exports")
                .version("0.1.0")
                .contact(new Contact().name("OtterWorks Engineering").email("engineering@otterworks.example.com"));
    }
}
