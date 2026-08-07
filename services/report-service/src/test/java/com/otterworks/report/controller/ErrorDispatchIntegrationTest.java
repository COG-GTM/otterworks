package com.otterworks.report.controller;

import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportRequest;
import com.otterworks.report.model.ReportType;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.test.context.ActiveProfiles;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Covers responses produced by the servlet container's ERROR dispatch.
 *
 * MockMvc never performs that dispatch, so {@link ReportControllerIntegrationTest} cannot
 * tell a real 400 apart from a 403 produced by the security chain rejecting /error.
 */
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = "otterworks.report.output-dir=${java.io.tmpdir}/error-dispatch-test-reports")
@ActiveProfiles("test")
public class ErrorDispatchIntegrationTest {

    @Autowired
    private TestRestTemplate restTemplate;

    @Test
    public void invalidRequestReturns400NotForbidden() {
        ResponseEntity<String> response = restTemplate.postForEntity(
                "/api/v1/reports", new ReportRequest(), String.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
    }

    @Test
    public void unknownReportReturns404NotForbidden() {
        ResponseEntity<String> response = restTemplate.getForEntity(
                "/api/v1/reports/999999", String.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
    }

    @Test
    public void openApiYamlIsReachable() {
        ResponseEntity<String> response = restTemplate.getForEntity(
                "/v3/api-docs.yaml", String.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    }

    @Test
    public void validRequestStillReturns202() {
        ReportRequest request = new ReportRequest();
        request.setReportName("Error Dispatch Probe");
        request.setCategory(ReportCategory.COMPLIANCE);
        request.setReportType(ReportType.CSV);
        request.setRequestedBy("error-dispatch-user");

        ResponseEntity<String> response = restTemplate.postForEntity(
                "/api/v1/reports", request, String.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.ACCEPTED);
    }
}
