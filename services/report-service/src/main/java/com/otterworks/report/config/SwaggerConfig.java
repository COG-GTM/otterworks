package com.otterworks.report.config;

import io.swagger.v3.oas.models.info.Contact;
import io.swagger.v3.oas.models.info.Info;
import org.springframework.context.annotation.Configuration;

/**
 * Swagger 2 configuration using SpringFox.
 *
 * LEGACY NOTES:
 * - SpringFox is a dead project (last release: July 2020, version 3.0.0)
 * - Uses Swagger 2 / OpenAPI 2.0 spec
 * - Known to break with Spring Boot 2.6+ (requires patching path-matching)
 * - Requires spring.mvc.pathmatch.matching-strategy=ant-path-matcher workaround
 *
 * UPGRADE TARGET:
 * - Replace with springdoc-openapi 2.x (actively maintained)
 * - Uses OpenAPI 3.0 spec natively
 * - No configuration workarounds needed
 * - Annotations: @Tag, @Operation, @Schema instead of @Api, @ApiOperation, @ApiModel
 */
@Configuration
public class SwaggerConfig {

    private Info apiInfo() {
        return new Info()
                .title("OtterWorks Report Service API")
                .description("Legacy report generation service for PDF, CSV, and Excel exports")
                .version("0.1.0")
                .contact(new Contact().name("OtterWorks Engineering").url("").email("engineering@otterworks.example.com"));
    }
}
