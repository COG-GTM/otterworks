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
import org.mockito.Mock;
import org.mockito.invocation.InvocationOnMock;
import org.mockito.junit.MockitoJUnitRunner;
import org.mockito.stubbing.Answer;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.io.File;
import java.util.Arrays;
import java.util.Collections;
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
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link ReportService} with a mocked repository and worker.
 *
 * The service defers work to {@code afterCommit} callbacks, so each test opens a synchronization
 * scope with {@link TransactionSynchronizationManager} and drives the callbacks explicitly.
 * The existing {@code ReportServiceTest} covers the same service through the full Spring context;
 * this one covers the branches that an end-to-end MockMvc test cannot reach.
 */
@RunWith(MockitoJUnitRunner.class)
public class ReportServiceUnitTest {

    private static final Date FROM = new Date(1_704_067_200_000L); // 2024-01-01T00:00:00Z
    private static final Date TO = new Date(1_706_745_600_000L);   // 2024-02-01T00:00:00Z

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

    @Test
    public void createReportPersistsAPendingReportWithTheRequestedFields() {
        echoSavedReport(1L);
        ReportRequest request = request("Monthly Usage", ReportCategory.USAGE_ANALYTICS, ReportType.PDF);
        request.setDateFrom(FROM);
        request.setDateTo(TO);

        Report created = service.createReport(request);

        assertEquals(Long.valueOf(1L), created.getId());
        assertEquals("Monthly Usage", created.getReportName());
        assertEquals(ReportCategory.USAGE_ANALYTICS, created.getCategory());
        assertEquals(ReportType.PDF, created.getReportType());
        assertEquals(ReportStatus.PENDING, created.getStatus());
        assertEquals("user-1", created.getRequestedBy());
        assertEquals(FROM, created.getDateFrom());
        assertEquals(TO, created.getDateTo());
        assertNotNull(created.getCreatedAt());
    }

    @Test
    public void createReportDefaultsTheDateRangeToTheLastThirtyDays() {
        echoSavedReport(2L);

        long before = System.currentTimeMillis();
        Report created = service.createReport(request("No Dates", ReportCategory.AUDIT_LOG, ReportType.CSV));
        long after = System.currentTimeMillis();

        long thirtyDaysMs = 30L * 24 * 60 * 60 * 1000;
        assertTrue(created.getDateFrom().getTime() >= before - thirtyDaysMs);
        assertTrue(created.getDateFrom().getTime() <= after - thirtyDaysMs);
        assertTrue(created.getDateTo().getTime() >= before);
        assertTrue(created.getDateTo().getTime() <= after);
    }

    @Test
    public void createReportSerialisesParametersToJson() {
        echoSavedReport(3L);
        ReportRequest request = request("With Params", ReportCategory.COMPLIANCE, ReportType.EXCEL);
        Map<String, String> params = new HashMap<String, String>();
        params.put("metric", "logins");
        request.setParameters(params);

        Report created = service.createReport(request);

        assertEquals("{\"metric\":\"logins\"}", created.getParameters());
    }

    @Test
    public void createReportLeavesParametersUnsetWhenNoneAreSupplied() {
        echoSavedReport(4L);

        assertNull(service.createReport(request("No Params", ReportCategory.AUDIT_LOG, ReportType.CSV))
                .getParameters());
    }

    @Test
    public void createReportOnlyTriggersGenerationAfterTheTransactionCommits() {
        echoSavedReport(5L);

        service.createReport(request("Deferred", ReportCategory.AUDIT_LOG, ReportType.CSV));

        verifyNoInteractions(generationWorker);

        runAfterCommitCallbacks();

        verify(generationWorker).generateReportAsync(5L);
    }

    @Test
    public void getReportDelegatesToTheRepository() {
        Report report = new Report();
        report.setId(6L);
        when(reportRepository.findById(6L)).thenReturn(Optional.of(report));

        assertTrue(service.getReport(6L).isPresent());
        assertEquals(report, service.getReport(6L).get());
    }

    @Test
    public void getReportsByUserReturnsTheUsersReportsNewestFirst() {
        List<Report> reports = Arrays.asList(new Report(), new Report());
        when(reportRepository.findByRequestedByOrderByCreatedAtDesc("user-1")).thenReturn(reports);

        assertEquals(reports, service.getReportsByUser("user-1"));
    }

    @Test
    public void getReportsByStatusFiltersOnStatus() {
        List<Report> reports = Collections.singletonList(new Report());
        when(reportRepository.findByStatusOrderByCreatedAtAsc(ReportStatus.COMPLETED)).thenReturn(reports);

        assertEquals(reports, service.getReportsByStatus(ReportStatus.COMPLETED));
    }

    @Test
    public void deleteReportReturnsFalseForAnUnknownId() {
        when(reportRepository.findById(404L)).thenReturn(Optional.<Report>empty());

        assertFalse(service.deleteReport(404L));

        verify(reportRepository, never()).deleteById(any(Long.class));
    }

    @Test
    public void deleteReportRemovesTheRecordAndThenTheFileAfterCommit() throws Exception {
        File file = tempFolder.newFile("generated.csv");
        Report report = new Report();
        report.setId(7L);
        report.setFilePath(file.getAbsolutePath());
        when(reportRepository.findById(7L)).thenReturn(Optional.of(report));

        assertTrue(service.deleteReport(7L));

        verify(reportRepository).deleteById(7L);
        assertTrue("file must survive until commit", file.exists());

        runAfterCommitCallbacks();

        assertFalse("file must be removed after commit", file.exists());
    }

    @Test
    public void deleteReportToleratesAMissingFileOnDisk() {
        Report report = new Report();
        report.setId(8L);
        report.setFilePath(tempFolder.getRoot().getAbsolutePath() + "/never-written.csv");
        when(reportRepository.findById(8L)).thenReturn(Optional.of(report));

        assertTrue(service.deleteReport(8L));

        runAfterCommitCallbacks();

        verify(reportRepository).deleteById(8L);
    }

    @Test
    public void deleteReportKeepsTheRecordDeletedWhenTheFileCannotBeRemoved() throws Exception {
        // A non-empty directory at the recorded path exists but cannot be deleted.
        File undeletable = tempFolder.newFolder("stuck.csv");
        assertTrue(new File(undeletable, "child").createNewFile());
        Report report = new Report();
        report.setId(10L);
        report.setFilePath(undeletable.getAbsolutePath());
        when(reportRepository.findById(10L)).thenReturn(Optional.of(report));

        assertTrue(service.deleteReport(10L));

        runAfterCommitCallbacks();

        verify(reportRepository).deleteById(10L);
        assertTrue(undeletable.exists());
    }

    @Test
    public void deleteReportRegistersNoFileCleanupWhenNothingWasGenerated() {
        Report report = new Report();
        report.setId(9L);
        report.setFilePath(null);
        when(reportRepository.findById(9L)).thenReturn(Optional.of(report));

        assertTrue(service.deleteReport(9L));

        assertTrue(TransactionSynchronizationManager.getSynchronizations().isEmpty());
    }

    // ----- helpers -----

    private void echoSavedReport(final long assignedId) {
        when(reportRepository.save(any(Report.class))).thenAnswer(new Answer<Report>() {
            @Override
            public Report answer(InvocationOnMock invocation) {
                Report report = invocation.getArgument(0);
                report.setId(assignedId);
                return report;
            }
        });
    }

    private void runAfterCommitCallbacks() {
        for (TransactionSynchronization synchronization : TransactionSynchronizationManager.getSynchronizations()) {
            synchronization.afterCommit();
        }
    }

    private static ReportRequest request(String name, ReportCategory category, ReportType type) {
        ReportRequest request = new ReportRequest();
        request.setReportName(name);
        request.setCategory(category);
        request.setReportType(type);
        request.setRequestedBy("user-1");
        return request;
    }
}
