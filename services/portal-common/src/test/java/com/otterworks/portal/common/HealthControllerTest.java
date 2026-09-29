package com.otterworks.portal.common;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

/** The shared {@code /health} payload: {@code status}, the service's own name, the banner. */
class HealthControllerTest {

    private static final String BANNER =
            "OtterWorks Portal (on-prem) - contact portal-support@otterworks.example";

    private static PortalBrandingSettings branding;

    @BeforeAll
    static void loadBranding() throws Exception {
        branding = new PortalBrandingSettings();
        branding.load();
    }

    @Test
    void payloadCarriesStatusServiceNameAndBannerInThatOrder() throws Exception {
        MockMvc mockMvc = MockMvcBuilders.standaloneSetup(new HealthController("legacy-portal", branding)).build();

        mockMvc.perform(get("/health"))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(content().string(
                        "{\"status\":\"UP\",\"service\":\"legacy-portal\",\"banner\":\"" + BANNER + "\"}"));
    }

    @Test
    void serviceFieldIsTheConfiguredServiceName() throws Exception {
        MockMvc mockMvc = MockMvcBuilders.standaloneSetup(
                new HealthController("announcements-service", branding)).build();

        mockMvc.perform(get("/health"))
                .andExpect(content().string(
                        "{\"status\":\"UP\",\"service\":\"announcements-service\",\"banner\":\"" + BANNER + "\"}"));
    }

    @Test
    void payloadHasExactlyTheThreeFields() {
        Map<String, String> body = new HealthController("feedback-service", branding).health();

        assertEquals(List.of("status", "service", "banner"), List.copyOf(body.keySet()));
        assertEquals("UP", body.get("status"));
        assertEquals("feedback-service", body.get("service"));
        assertEquals(BANNER, body.get("banner"));
    }
}
