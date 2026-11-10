package com.otterworks.report.controller;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.junit4.SpringRunner;
import org.springframework.test.web.servlet.MockMvc;

import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.hasItem;
import static org.hamcrest.Matchers.is;
import static org.hamcrest.Matchers.notNullValue;
import static org.hamcrest.Matchers.startsWith;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Verifies the springdoc OpenAPI document and Swagger UI are served and keep
 * the paths, operations and schemas of the former SpringFox /v2/api-docs.
 */
@RunWith(SpringRunner.class)
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
public class OpenApiDocsIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Test
    public void apiDocsExposeReportOperationsAndSchemas() throws Exception {
        mockMvc.perform(get("/v3/api-docs"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.openapi", startsWith("3.")))
                .andExpect(jsonPath("$.info.title", is("OtterWorks Report Service API")))
                .andExpect(jsonPath("$.paths['/api/v1/reports'].get.summary", is("List reports")))
                .andExpect(jsonPath("$.paths['/api/v1/reports'].post.summary", is("Create a new report")))
                .andExpect(jsonPath("$.paths['/api/v1/reports/{id}'].get.summary", is("Get report by ID")))
                .andExpect(jsonPath("$.paths['/api/v1/reports/{id}'].delete.summary", is("Delete a report")))
                .andExpect(jsonPath("$.paths['/api/v1/reports/{id}/download'].get.summary",
                        is("Download a generated report")))
                .andExpect(jsonPath("$.paths['/health'].get", notNullValue()))
                .andExpect(jsonPath("$.components.schemas.ReportRequest.required", hasItem("reportName")))
                .andExpect(jsonPath("$.components.schemas.ReportResponse.properties.downloadUrl", notNullValue()));
    }

    @Test
    public void swaggerUiRenders() throws Exception {
        mockMvc.perform(get("/swagger-ui/index.html"))
                .andExpect(status().isOk())
                .andExpect(content().string(containsString("Swagger UI")));
    }
}
