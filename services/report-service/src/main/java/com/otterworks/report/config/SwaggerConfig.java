package com.otterworks.report.config;

import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Contact;
import io.swagger.v3.oas.models.info.Info;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * OpenAPI 3 metadata for the report service. Endpoint discovery is handled by
 * springdoc auto-configuration.
 */
@Configuration
public class SwaggerConfig {

    @Bean
    public OpenAPI reportServiceOpenApi() {
        return new OpenAPI().info(new Info()
                .title("OtterWorks Report Service API")
                .description("Report generation service for PDF, CSV, and Excel exports")
                .version("0.1.0")
                .contact(new Contact()
                        .name("OtterWorks Engineering")
                        .email("engineering@otterworks.example.com")));
    }
}
