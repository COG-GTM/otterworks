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
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;
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
import static org.junit.Assert.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link ReportService}, driven through mocked collaborators rather than a Spring
 * context (the existing {@code ReportServiceTest} covers the wired-up path).
 *
 * {@code createReport} and {@code deleteReport} defer work to
 * {@link TransactionSynchronizationManager} callbacks, so each test opens a synchronization scope
 * and fires {@code afterCommit()} explicitly to assert the deferred behaviour.
 */
public class ReportServiceUnitTest {

    /** 2024-01-01T00:00:00Z */
    private static final Date FROM = new Date(1_704_067_200_000L);

    /** 2024-01-08T00:00:00Z */
    private static final Date TO = new Date(1_704_672_000_000L);

    private static final long THIRTY_DAYS_MS = 30L * 24 * 60 * 60 * 1000;

    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    @Mock
    private ReportRepository reportRepository;

    @Mock
    private ReportGenerationWorker generationWorker;

    @Mock
    private AppConfig appConfig;

    private AutoCloseable mocks;
    private ReportService service;

    @Before
    public void setUp() {
        mocks = MockitoAnnotations.openMocks(this);
        service = new ReportService(reportRepository, generationWorker, appConfig);
        TransactionSynchronizationManager.initSynchronization();
    }

    @After
    public void tearDown() throws Exception {
        TransactionSynchronizationManager.clearSynchronization();
        mocks.close();
    }

    // ----- createReport -----

    @Test
    public void createReportPersistsThePendingRequest() {
        when(reportRepository.save(any(Report.class))).thenAnswer(saveWithId(7L));

        Report saved = service.createReport(request(FROM, TO, null));

        ArgumentCaptor<Report> captor = ArgumentCaptor.forClass(Report.class);
        verify(reportRepository).save(captor.capture());
        Report persisted = captor.getValue();

        assertEquals("Weekly Usage", persisted.getReportName());
        assertEquals(ReportCategory.USAGE_ANALYTICS, persisted.getCategory());
        assertEquals(ReportType.PDF, persisted.getReportType());
        assertEquals("user-1", persisted.getRequestedBy());
        assertEquals(ReportStatus.PENDING, persisted.getStatus());
        assertEquals(FROM, persisted.getDateFrom());
        assertEquals(TO, persisted.getDateTo());
        assertNotNull(persisted.getCreatedAt());
        assertEquals(Long.valueOf(7L), saved.getId());
    }

    @Test
    public void createReportDefaultsToTheLastThirtyDaysWhenNoRangeIsGiven() {
        when(reportRepository.save(any(Report.class))).thenAnswer(saveWithId(1L));

        Report saved = service.createReport(request(null, null, null));

        long span = saved.getDateTo().getTime() - saved.getDateFrom().getTime();
        assertTrue("expected a ~30 day default window but was " + span,
                Math.abs(span - THIRTY_DAYS_MS) < 5_000);
    }

    @Test
    public void createReportSerialisesParametersToJson() {
        when(reportRepository.save(any(Report.class))).thenAnswer(saveWithId(1L));

        Report saved = service.createReport(
                request(FROM, TO, Collections.singletonMap("metric", "downloads")));

        assertEquals("{\"metric\":\"downloads\"}", saved.getParameters());
    }

    @Test
    public void createReportDefersGenerationUntilAfterCommit() {
        when(reportRepository.save(any(Report.class))).thenAnswer(saveWithId(99L));

        service.createReport(request(FROM, TO, null));

        // Nothing must be dispatched while the transaction is still open.
        verifyNoInteractions(generationWorker);

        fireAfterCommit();

        verify(generationWorker).generateReportAsync(99L);
    }

    // ----- read paths -----

    @Test
    public void getReportDelegatesToTheRepository() {
        Report report = new Report();
        when(reportRepository.findById(5L)).thenReturn(Optional.of(report));

        assertEquals(Optional.of(report), service.getReport(5L));
    }

    @Test
    public void getReportReturnsEmptyForAnUnknownId() {
        when(reportRepository.findById(5L)).thenReturn(Optional.<Report>empty());

        assertFalse(service.getReport(5L).isPresent());
    }

    @Test
    public void getReportsByUserDelegatesToTheRepository() {
        List<Report> reports = Arrays.asList(new Report(), new Report());
        when(reportRepository.findByRequestedByOrderByCreatedAtDesc("user-1")).thenReturn(reports);

        assertEquals(reports, service.getReportsByUser("user-1"));
    }

    @Test
    public void getReportsByStatusDelegatesToTheRepository() {
        List<Report> reports = Collections.singletonList(new Report());
        when(reportRepository.findByStatusOrderByCreatedAtAsc(ReportStatus.COMPLETED)).thenReturn(reports);

        assertEquals(reports, service.getReportsByStatus(ReportStatus.COMPLETED));
    }

    // ----- deleteReport -----

    @Test
    public void deleteReportReturnsFalseForAnUnknownId() {
        when(reportRepository.findById(3L)).thenReturn(Optional.<Report>empty());

        assertFalse(service.deleteReport(3L));

        verify(reportRepository, never()).deleteById(any(Long.class));
    }

    @Test
    public void deleteReportWithoutAFileOnlyRemovesTheRecord() {
        Report report = new Report();
        report.setId(3L);
        when(reportRepository.findById(3L)).thenReturn(Optional.of(report));

        assertTrue(service.deleteReport(3L));

        verify(reportRepository).deleteById(3L);
        assertTrue(TransactionSynchronizationManager.getSynchronizations().isEmpty());
    }

    @Test
    public void deleteReportRemovesTheGeneratedFileAfterCommit() throws Exception {
        File file = tmp.newFile("generated.csv");
        Report report = new Report();
        report.setId(3L);
        report.setFilePath(file.getAbsolutePath());
        when(reportRepository.findById(3L)).thenReturn(Optional.of(report));

        assertTrue(service.deleteReport(3L));
        // The file must survive until the transaction commits.
        assertTrue(file.exists());

        fireAfterCommit();

        assertFalse(file.exists());
    }

    @Test
    public void deleteReportToleratesAnAlreadyMissingFile() {
        Report report = new Report();
        report.setId(3L);
        report.setFilePath(new File(tmp.getRoot(), "never-written.csv").getAbsolutePath());
        when(reportRepository.findById(3L)).thenReturn(Optional.of(report));

        assertTrue(service.deleteReport(3L));

        fireAfterCommit();
    }

    @Test
    public void deleteReportToleratesAFileThatCannotBeDeleted() throws Exception {
        // A non-empty directory cannot be removed by File.delete(), which exercises the
        // "failed to delete" branch without depending on filesystem permissions.
        File dir = tmp.newFolder("undeletable");
        assertTrue(new File(dir, "child.txt").createNewFile());

        Report report = new Report();
        report.setId(3L);
        report.setFilePath(dir.getAbsolutePath());
        when(reportRepository.findById(3L)).thenReturn(Optional.of(report));

        assertTrue(service.deleteReport(3L));

        fireAfterCommit();

        assertTrue(dir.exists());
    }

    // ----- helpers -----

    private static ReportRequest request(Date from, Date to, Map<String, String> parameters) {
        ReportRequest request = new ReportRequest();
        request.setReportName("Weekly Usage");
        request.setCategory(ReportCategory.USAGE_ANALYTICS);
        request.setReportType(ReportType.PDF);
        request.setRequestedBy("user-1");
        request.setDateFrom(from);
        request.setDateTo(to);
        request.setParameters(parameters == null ? null : new HashMap<>(parameters));
        return request;
    }

    private static org.mockito.stubbing.Answer<Report> saveWithId(final long id) {
        return invocation -> {
            Report report = invocation.getArgument(0);
            report.setId(id);
            return report;
        };
    }

    private static void fireAfterCommit() {
        for (TransactionSynchronization synchronization :
                TransactionSynchronizationManager.getSynchronizations()) {
            synchronization.afterCommit();
        }
    }
}
