package com.otterworks.report.service;

import com.otterworks.report.config.AppConfig;
import com.otterworks.report.model.Report;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.junit4.SpringRunner;

import java.io.File;
import java.util.Optional;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

@RunWith(SpringRunner.class)
@SpringBootTest
@ActiveProfiles("test")
public class ReportFileContainmentTest {

    @Autowired
    private ReportService reportService;

    @Autowired
    private AppConfig appConfig;

    private Report reportWithPath(String path) {
        Report report = new Report();
        report.setFilePath(path);
        return report;
    }

    @Test
    public void resolvesPathsInsideTheReportDirectory() throws Exception {
        File root = new File(appConfig.getReportOutputDir()).getCanonicalFile();
        File inside = new File(root, "report-1.csv");

        Optional<File> resolved = reportService.resolveReportFile(reportWithPath(inside.getPath()));

        assertTrue(resolved.isPresent());
        assertEquals(inside.getCanonicalFile(), resolved.get());
    }

    @Test
    public void refusesPathsOutsideTheReportDirectory() throws Exception {
        File root = new File(appConfig.getReportOutputDir()).getCanonicalFile();

        assertFalse(reportService.resolveReportFile(reportWithPath("/etc/passwd")).isPresent());
        assertFalse(reportService
                .resolveReportFile(reportWithPath(root.getPath() + "/../../etc/passwd"))
                .isPresent());
        assertFalse(reportService.resolveReportFile(reportWithPath(root.getPath())).isPresent());
        assertFalse(reportService.resolveReportFile(reportWithPath(null)).isPresent());
    }
}
