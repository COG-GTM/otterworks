package com.otterworks.userpreferences.platform;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * Portal branding strings from {@code portal-settings.properties}. Placeholders inside the file
 * resolve through Spring's environment, so any key can be overridden per environment (for example
 * {@code PORTAL_ENVIRONMENT=eks}) without rebuilding the image.
 */
@Component
public class PortalBrandingSettings {

    private final String bannerText;
    private final String supportContact;

    public PortalBrandingSettings(
            @Value("${portal.banner:OtterWorks Portal}") String bannerText,
            @Value("${portal.support:}") String supportContact) {
        this.bannerText = bannerText;
        this.supportContact = supportContact;
    }

    public String bannerText() {
        return bannerText;
    }

    public String supportContact() {
        return supportContact;
    }
}
