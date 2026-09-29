package com.otterworks.portal.common;

import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/** {@code GET /health}: status, the service's own name and the portal banner. */
@RestController
public class HealthController {

    private final String serviceName;
    private final PortalBrandingSettings branding;

    public HealthController(String serviceName, PortalBrandingSettings branding) {
        this.serviceName = serviceName;
        this.branding = branding;
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
