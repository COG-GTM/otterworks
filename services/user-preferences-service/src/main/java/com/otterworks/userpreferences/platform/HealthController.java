package com.otterworks.userpreferences.platform;

import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Lightweight health endpoint matching the {@code /health} convention used by the other OtterWorks
 * services and the Helm probes (Actuator's liveness/readiness groups are also enabled).
 */
@RestController
public class HealthController {

    private final PortalBrandingSettings branding;
    private final String serviceName;

    public HealthController(
            PortalBrandingSettings branding, @Value("${spring.application.name}") String serviceName) {
        this.branding = branding;
        this.serviceName = serviceName;
    }

    @GetMapping("/health")
    public Map<String, String> health() {
        Map<String, String> body = new LinkedHashMap<>();
        body.put("status", "UP");
        body.put("service", serviceName);
        body.put("banner", branding.bannerText());
        return body;
    }
}
