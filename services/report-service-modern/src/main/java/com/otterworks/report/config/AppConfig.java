package com.otterworks.report.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

import java.net.http.HttpClient;

/**
 * Outbound HTTP wiring: Spring 6.1 {@link RestClient} on top of the JDK {@link HttpClient}
 * (replaces RestTemplate + Apache HttpComponents 4.x).
 */
@Configuration
public class AppConfig {

    @Bean
    public RestClient reportRestClient(RestClient.Builder builder, ReportProperties properties) {
        HttpClient httpClient = HttpClient.newBuilder()
                .connectTimeout(properties.report().connectionTimeout())
                .build();
        JdkClientHttpRequestFactory requestFactory = new JdkClientHttpRequestFactory(httpClient);
        requestFactory.setReadTimeout(properties.report().readTimeout());
        return builder.requestFactory(requestFactory).build();
    }
}
