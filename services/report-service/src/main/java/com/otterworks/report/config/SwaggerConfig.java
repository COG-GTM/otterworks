package com.otterworks.report.config;

import java.lang.reflect.Field;
import java.util.List;
import java.util.stream.Collectors;
import org.springframework.beans.BeansException;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.util.ReflectionUtils;
import org.springframework.web.servlet.mvc.method.RequestMappingInfoHandlerMapping;
import springfox.documentation.builders.ApiInfoBuilder;
import springfox.documentation.builders.PathSelectors;
import springfox.documentation.builders.RequestHandlerSelectors;
import springfox.documentation.service.ApiInfo;
import springfox.documentation.service.Contact;
import springfox.documentation.spi.DocumentationType;
import springfox.documentation.spring.web.plugins.Docket;
import springfox.documentation.spring.web.plugins.WebMvcRequestHandlerProvider;

/**
 * Swagger 2 configuration using SpringFox.
 *
 * LEGACY NOTES:
 * - SpringFox is a dead project (last release: July 2020, version 3.0.0)
 * - Uses Swagger 2 / OpenAPI 2.0 spec
 * - Known to break with Spring Boot 2.6+ (requires patching path-matching)
 * - Requires spring.mvc.pathmatch.matching-strategy=ant-path-matcher workaround
 * - On Boot 2.6+ the actuator endpoint mappings still use PathPatternParser, which crashes
 *   SpringFox's bootstrapper; see springfoxHandlerProviderBeanPostProcessor below
 *
 * UPGRADE TARGET:
 * - Replace with springdoc-openapi 2.x (actively maintained)
 * - Uses OpenAPI 3.0 spec natively
 * - No configuration workarounds needed
 * - Annotations: @Tag, @Operation, @Schema instead of @Api, @ApiOperation, @ApiModel
 */
@Configuration
public class SwaggerConfig {

    @Bean
    public Docket api() {
        return new Docket(DocumentationType.SWAGGER_2)
                .select()
                .apis(RequestHandlerSelectors.basePackage("com.otterworks.report.controller"))
                .paths(PathSelectors.any())
                .build()
                .apiInfo(apiInfo());
    }

    /**
     * Keeps SpringFox to the ant-path-matcher handler mappings so the actuator's
     * PathPatternParser-based mappings don't NPE its bootstrapper on Spring Boot 2.6+.
     */
    @Bean
    public static BeanPostProcessor springfoxHandlerProviderBeanPostProcessor() {
        return new BeanPostProcessor() {
            @Override
            public Object postProcessAfterInitialization(Object bean, String beanName) throws BeansException {
                if (bean instanceof WebMvcRequestHandlerProvider) {
                    List<RequestMappingInfoHandlerMapping> mappings = handlerMappings(bean);
                    List<RequestMappingInfoHandlerMapping> antMappings = mappings.stream()
                            .filter(mapping -> mapping.getPatternParser() == null)
                            .collect(Collectors.toList());
                    mappings.clear();
                    mappings.addAll(antMappings);
                }
                return bean;
            }

            @SuppressWarnings("unchecked")
            private List<RequestMappingInfoHandlerMapping> handlerMappings(Object bean) {
                Field field = ReflectionUtils.findField(bean.getClass(), "handlerMappings");
                ReflectionUtils.makeAccessible(field);
                return (List<RequestMappingInfoHandlerMapping>) ReflectionUtils.getField(field, bean);
            }
        };
    }

    private ApiInfo apiInfo() {
        return new ApiInfoBuilder()
                .title("OtterWorks Report Service API")
                .description("Legacy report generation service for PDF, CSV, and Excel exports")
                .version("0.1.0")
                .contact(new Contact("OtterWorks Engineering", "", "engineering@otterworks.example.com"))
                .build();
    }
}
