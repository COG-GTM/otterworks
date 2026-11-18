package com.otterworks.report.controller;

import com.otterworks.report.model.Report;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportStatus;
import com.otterworks.report.model.ReportType;
import com.otterworks.report.repository.ReportRepository;
import com.otterworks.report.service.ReportService;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.junit4.SpringRunner;
import org.springframework.test.web.servlet.MockMvc;

import java.io.File;
import java.nio.file.Files;
import java.util.Date;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.hamcrest.Matchers.is;

@RunWith(SpringRunner.class)
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
public class ReportDownloadAndDeleteIntegrationTest {

    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ReportRepository repository;

    @Autowired
    private ReportService reportService;

    private Report saveReport(ReportType type, ReportStatus status, String filePath) {
        Report r = new Report();
        r.setReportName("download-test");
        r.setCategory(ReportCategory.USAGE_ANALYTICS);
        r.setReportType(type);
        r.setStatus(status);
        r.setRequestedBy("download-user");
        r.setCreatedAt(new Date());
        r.setDateFrom(new Date(0));
        r.setDateTo(new Date());
        r.setFilePath(filePath);
        return repository.save(r);
    }

    private File fileWith(String name, byte[] bytes) throws Exception {
        File f = tmp.newFile(name);
        Files.write(f.toPath(), bytes);
        return f;
    }

    private void assertDownload(ReportType type, String fileName, String contentType) throws Exception {
        byte[] bytes = ("payload-" + type).getBytes();
        File f = fileWith(fileName, bytes);
        Report r = saveReport(type, ReportStatus.COMPLETED, f.getAbsolutePath());

        mockMvc.perform(get("/api/v1/reports/" + r.getId() + "/download"))
                .andExpect(status().isOk())
                .andExpect(header().string("Content-Type", contentType))
                .andExpect(header().string("Content-Disposition", "attachment; filename=\"" + fileName + "\""))
                .andExpect(header().longValue("Content-Length", bytes.length))
                .andExpect(content().bytes(bytes));
    }

    @Test
    public void downloadCompletedPdfReturnsFileWithPdfContentType() throws Exception {
        assertDownload(ReportType.PDF, "r.pdf", "application/pdf");
    }

    @Test
    public void downloadCompletedCsvReturnsFileWithCsvContentType() throws Exception {
        assertDownload(ReportType.CSV, "r.csv", "text/csv");
    }

    @Test
    public void downloadCompletedExcelReturnsFileWithXlsxContentType() throws Exception {
        assertDownload(ReportType.EXCEL, "r.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
    }

    @Test
    public void completedReportExposesDownloadUrl() throws Exception {
        File f = fileWith("meta.csv", new byte[]{1});
        Report r = saveReport(ReportType.CSV, ReportStatus.COMPLETED, f.getAbsolutePath());

        mockMvc.perform(get("/api/v1/reports/" + r.getId()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.downloadUrl", is("/api/v1/reports/" + r.getId() + "/download")));
    }

    @Test
    public void downloadGeneratingReportReturns409() throws Exception {
        Report r = saveReport(ReportType.PDF, ReportStatus.GENERATING, null);
        mockMvc.perform(get("/api/v1/reports/" + r.getId() + "/download"))
                .andExpect(status().isConflict());
    }

    @Test
    public void downloadFailedReportReturns404() throws Exception {
        File f = fileWith("failed.pdf", new byte[]{1});
        Report r = saveReport(ReportType.PDF, ReportStatus.FAILED, f.getAbsolutePath());
        mockMvc.perform(get("/api/v1/reports/" + r.getId() + "/download"))
                .andExpect(status().isNotFound());
    }

    @Test
    public void downloadCompletedReportWithoutFilePathReturns404() throws Exception {
        Report r = saveReport(ReportType.PDF, ReportStatus.COMPLETED, null);
        mockMvc.perform(get("/api/v1/reports/" + r.getId() + "/download"))
                .andExpect(status().isNotFound());
    }

    @Test
    public void downloadWhenFileMissingOnDiskReturns404() throws Exception {
        Report r = saveReport(ReportType.PDF, ReportStatus.COMPLETED,
                new File(tmp.getRoot(), "gone.pdf").getAbsolutePath());
        mockMvc.perform(get("/api/v1/reports/" + r.getId() + "/download"))
                .andExpect(status().isNotFound());
    }

    @Test
    public void downloadWhenFileUnreadableReturns404() throws Exception {
        File dir = tmp.newFolder("not-a-file.pdf");
        Report r = saveReport(ReportType.PDF, ReportStatus.COMPLETED, dir.getAbsolutePath());
        mockMvc.perform(get("/api/v1/reports/" + r.getId() + "/download"))
                .andExpect(status().isNotFound());
    }

    @Test
    public void deleteRemovesGeneratedFileAfterCommit() throws Exception {
        File f = fileWith("to-delete.pdf", new byte[]{1, 2});
        Report r = saveReport(ReportType.PDF, ReportStatus.COMPLETED, f.getAbsolutePath());

        mockMvc.perform(delete("/api/v1/reports/" + r.getId()))
                .andExpect(status().isNoContent());

        assertFalse(f.exists());
        assertFalse(repository.findById(r.getId()).isPresent());
    }

    @Test
    public void deleteSucceedsWhenFileAlreadyMissing() {
        Report r = saveReport(ReportType.PDF, ReportStatus.COMPLETED,
                new File(tmp.getRoot(), "never-existed.pdf").getAbsolutePath());
        assertTrue(reportService.deleteReport(r.getId()));
        assertFalse(repository.findById(r.getId()).isPresent());
    }

    @Test
    public void deleteKeepsGoingWhenFileCannotBeDeleted() throws Exception {
        File dir = tmp.newFolder("non-empty-dir.pdf");
        File child = new File(dir, "child");
        Files.write(child.toPath(), new byte[]{1});
        Report r = saveReport(ReportType.PDF, ReportStatus.COMPLETED, dir.getAbsolutePath());

        assertTrue(reportService.deleteReport(r.getId()));
        assertTrue(dir.exists());
        assertFalse(repository.findById(r.getId()).isPresent());
    }

    @Test
    public void deleteReportWithoutFileSucceeds() {
        Report r = saveReport(ReportType.CSV, ReportStatus.FAILED, null);
        assertTrue(reportService.deleteReport(r.getId()));
        assertFalse(repository.findById(r.getId()).isPresent());
    }
}
