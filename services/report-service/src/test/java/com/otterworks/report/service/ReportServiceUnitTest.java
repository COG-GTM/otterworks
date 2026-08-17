package com.otterworks.report.service;

import com.otterworks.report.config.AppConfig;
import com.otterworks.report.model.Report;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportRequest;
import com.otterworks.report.model.ReportStatus;
import com.otterworks.report.model.ReportType;
import com.otterworks.report.repository.ReportRepository;
import org.junit.After;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.MockitoJUnitRunner;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.io.File;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link ReportService} with all collaborators mocked.
 *
 * The transaction synchronization registry is initialised manually so the
 * afterCommit callbacks the service registers can be driven deterministically
 * without a real transaction manager.
 *
 * Written in JUnit 4 style to match the current stack.
 */
@RunWith(MockitoJUnitRunner.class)
public class ReportServiceUnitTest {

    @Rule
    public TemporaryFolder tempFolder = new TemporaryFolder();

    @Mock
    private ReportRepository reportRepository;

    @Mock
    private ReportGenerationWorker generationWorker;

    @Mock
    private AppConfig appConfig;

    private ReportService service;

    @Before
    public void setUp() {
        service = new ReportService(reportRepository, generationWorker, appConfig);
        TransactionSynchronizationManager.initSynchronization();
    }

    @After
    public void tearDown() {
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.clearSynchronization();
        }
    }

    private void triggerAfterCommit() {
        for (TransactionSynchronization sync
                : new ArrayList<>(TransactionSynchronizationManager.getSynchronizations())) {
            sync.afterCommit();
        }
    }

    private ReportRequest buildRequest() {
        ReportRequest request = new ReportRequest();
        request.setReportName("Quarterly Usage");
        request.setCategory(ReportCategory.USAGE_ANALYTICS);
        request.setReportType(ReportType.PDF);
        request.setRequestedBy("user-42");
        return request;
    }

    private void answerSaveWithId(final Long id) {
        when(reportRepository.save(any(Report.class))).thenAnswer(invocation -> {
            Report report = invocation.getArgument(0);
            report.setId(id);
            return report;
        });
    }

    @Test
    public void createReportPersistsPendingReportWithRequestedDateRange() {
        answerSaveWithId(7L);
        ReportRequest request = buildRequest();
        Date from = new Date(1704067200000L);
        Date to = new Date(1704153600000L);
        request.setDateFrom(from);
        request.setDateTo(to);

        Report saved = service.createReport(request);

        ArgumentCaptor<Report> captor = ArgumentCaptor.forClass(Report.class);
        verify(reportRepository).save(captor.capture());
        Report persisted = captor.getValue();
        assertEquals("Quarterly Usage", persisted.getReportName());
        assertEquals(ReportCategory.USAGE_ANALYTICS, persisted.getCategory());
        assertEquals(ReportType.PDF, persisted.getReportType());
        assertEquals("user-42", persisted.getRequestedBy());
        assertEquals(ReportStatus.PENDING, persisted.getStatus());
        assertEquals(from, persisted.getDateFrom());
        assertEquals(to, persisted.getDateTo());
        assertNotNull(persisted.getCreatedAt());
        assertNull(persisted.getParameters());
        assertEquals(Long.valueOf(7L), saved.getId());
    }

    @Test
    public void createReportDefaultsToTheLastThirtyDaysWhenNoRangeIsGiven() {
        answerSaveWithId(8L);
        Date before = new Date();

        Report saved = service.createReport(buildRequest());

        Date after = new Date();
        long thirtyDaysMs = 30L * 24 * 60 * 60 * 1000;
        assertTrue(saved.getDateFrom().getTime() <= after.getTime() - thirtyDaysMs);
        assertTrue(saved.getDateFrom().getTime() >= before.getTime() - thirtyDaysMs - 1000);
        assertTrue(saved.getDateTo().getTime() >= before.getTime());
        assertTrue(saved.getDateTo().getTime() <= after.getTime());
    }

    @Test
    public void createReportSerializesParametersToJson() {
        answerSaveWithId(9L);
        ReportRequest request = buildRequest();
        Map<String, String> params = new HashMap<>();
        params.put("metric", "uploads");
        request.setParameters(params);

        Report saved = service.createReport(request);

        assertEquals("{\"metric\":\"uploads\"}", saved.getParameters());
    }

    @Test
    public void createReportDefersGenerationUntilAfterCommit() {
        answerSaveWithId(11L);

        service.createReport(buildRequest());

        verify(generationWorker, never()).generateReportAsync(anyLong());

        triggerAfterCommit();

        verify(generationWorker).generateReportAsync(11L);
    }

    @Test
    public void getReportDelegatesToTheRepository() {
        Report report = new Report();
        report.setId(3L);
        when(reportRepository.findById(3L)).thenReturn(Optional.of(report));

        assertEquals(report, service.getReport(3L).get());
    }

    @Test
    public void getReportReturnsEmptyWhenUnknown() {
        when(reportRepository.findById(404L)).thenReturn(Optional.empty());

        assertFalse(service.getReport(404L).isPresent());
    }

    @Test
    public void getReportsByUserReturnsRepositoryResult() {
        List<Report> reports = Arrays.asList(new Report(), new Report());
        when(reportRepository.findByRequestedByOrderByCreatedAtDesc("user-42")).thenReturn(reports);

        assertEquals(reports, service.getReportsByUser("user-42"));
    }

    @Test
    public void getReportsByStatusReturnsRepositoryResult() {
        List<Report> reports = Arrays.asList(new Report());
        when(reportRepository.findByStatusOrderByCreatedAtAsc(ReportStatus.COMPLETED)).thenReturn(reports);

        assertEquals(reports, service.getReportsByStatus(ReportStatus.COMPLETED));
    }

    @Test
    public void deleteReportReturnsFalseForUnknownId() {
        when(reportRepository.findById(404L)).thenReturn(Optional.empty());

        assertFalse(service.deleteReport(404L));

        verify(reportRepository, never()).deleteById(anyLong());
        assertTrue(TransactionSynchronizationManager.getSynchronizations().isEmpty());
    }

    @Test
    public void deleteReportRemovesTheRecordAndDeletesTheFileAfterCommit() throws Exception {
        File file = tempFolder.newFile("report.csv");
        Report report = new Report();
        report.setId(5L);
        report.setFilePath(file.getAbsolutePath());
        when(reportRepository.findById(5L)).thenReturn(Optional.of(report));

        assertTrue(service.deleteReport(5L));

        verify(reportRepository).deleteById(5L);
        assertTrue("file must survive until the transaction commits", file.exists());

        triggerAfterCommit();

        assertFalse(file.exists());
    }

    @Test
    public void deleteReportRegistersNoFileCleanupWhenThereIsNoFilePath() {
        Report report = new Report();
        report.setId(6L);
        when(reportRepository.findById(6L)).thenReturn(Optional.of(report));

        assertTrue(service.deleteReport(6L));

        verify(reportRepository).deleteById(6L);
        assertTrue(TransactionSynchronizationManager.getSynchronizations().isEmpty());
    }

    @Test
    public void deleteReportToleratesAnAlreadyMissingFile() throws Exception {
        File file = tempFolder.newFile("gone.csv");
        assertTrue(file.delete());
        Report report = new Report();
        report.setId(7L);
        report.setFilePath(file.getAbsolutePath());
        when(reportRepository.findById(7L)).thenReturn(Optional.of(report));

        assertTrue(service.deleteReport(7L));

        triggerAfterCommit();

        assertFalse(file.exists());
    }

    @Test
    public void deleteReportSurvivesAFailingFileDeletion() throws Exception {
        // A non-empty directory cannot be deleted, which drives the failure branch.
        File dir = tempFolder.newFolder("undeletable");
        assertTrue(new File(dir, "child.txt").createNewFile());
        Report report = new Report();
        report.setId(8L);
        report.setFilePath(dir.getAbsolutePath());
        when(reportRepository.findById(8L)).thenReturn(Optional.of(report));

        assertTrue(service.deleteReport(8L));

        triggerAfterCommit();

        assertTrue(dir.exists());
    }
}
