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
import org.mockito.junit.MockitoJUnitRunner;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.support.TransactionSynchronizationUtils;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
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
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link ReportService}.
 *
 * The repository and the async worker are mocked. Transaction synchronization is driven
 * manually ({@link TransactionSynchronizationManager}) so the deferred {@code afterCommit}
 * callbacks — async generation kick-off and report-file cleanup — can be asserted without a
 * real transaction manager.
 */
@RunWith(MockitoJUnitRunner.class)
public class ReportServiceUnitTest {

    private static final Date DATE_FROM = new Date(1_704_067_200_000L); // 2024-01-01T00:00:00Z
    private static final Date DATE_TO = new Date(1_706_745_600_000L);   // 2024-02-01T00:00:00Z

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
        // Never leak synchronizations into the next test.
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.clearSynchronization();
        }
    }

    // ----- createReport -----

    @Test
    public void createReportPersistsAPendingReportFromTheRequest() {
        ReportRequest request = request();
        request.setDateFrom(DATE_FROM);
        request.setDateTo(DATE_TO);
        when(reportRepository.save(any(Report.class))).thenAnswer(withId(11L));

        Report saved = service.createReport(request);

        assertEquals(Long.valueOf(11L), saved.getId());
        assertEquals("Monthly usage", saved.getReportName());
        assertEquals(ReportCategory.USAGE_ANALYTICS, saved.getCategory());
        assertEquals(ReportType.PDF, saved.getReportType());
        assertEquals("user-1", saved.getRequestedBy());
        assertEquals(ReportStatus.PENDING, saved.getStatus());
        assertEquals(DATE_FROM, saved.getDateFrom());
        assertEquals(DATE_TO, saved.getDateTo());
        assertNotNull(saved.getCreatedAt());
        assertNull(saved.getParameters());
    }

    @Test
    public void createReportDefaultsTheDateRangeToTheLastThirtyDays() {
        ReportRequest request = request();
        when(reportRepository.save(any(Report.class))).thenAnswer(withId(12L));

        long before = System.currentTimeMillis();
        Report saved = service.createReport(request);
        long after = System.currentTimeMillis();

        assertTrue(saved.getDateTo().getTime() >= before && saved.getDateTo().getTime() <= after);
        long spanMs = saved.getDateTo().getTime() - saved.getDateFrom().getTime();
        long thirtyDaysMs = 30L * 24 * 60 * 60 * 1000;
        assertTrue("default range should span ~30 days but was " + spanMs + "ms",
                Math.abs(spanMs - thirtyDaysMs) < 2 * 60 * 60 * 1000);
    }

    @Test
    public void createReportSerialisesParametersToJson() {
        ReportRequest request = request();
        Map<String, String> parameters = new HashMap<>();
        parameters.put("metric", "uploads");
        request.setParameters(parameters);
        when(reportRepository.save(any(Report.class))).thenAnswer(withId(13L));

        Report saved = service.createReport(request);

        assertEquals("{\"metric\":\"uploads\"}", saved.getParameters());
    }

    @Test
    public void asyncGenerationIsDeferredUntilTheTransactionCommits() {
        when(reportRepository.save(any(Report.class))).thenAnswer(withId(14L));

        service.createReport(request());

        verify(generationWorker, never()).generateReportAsync(anyLong());

        TransactionSynchronizationUtils.triggerAfterCommit();

        verify(generationWorker).generateReportAsync(14L);
    }

    // ----- read-only queries -----

    @Test
    public void getReportDelegatesToTheRepository() {
        Report report = new Report();
        when(reportRepository.findById(5L)).thenReturn(Optional.of(report));

        Optional<Report> found = service.getReport(5L);

        assertTrue(found.isPresent());
        assertSame(report, found.get());
    }

    @Test
    public void getReportsByUserDelegatesToTheRepository() {
        List<Report> reports = Arrays.asList(new Report(), new Report());
        when(reportRepository.findByRequestedByOrderByCreatedAtDesc("user-1")).thenReturn(reports);

        assertEquals(reports, service.getReportsByUser("user-1"));
    }

    @Test
    public void getReportsByStatusDelegatesToTheRepository() {
        when(reportRepository.findByStatusOrderByCreatedAtAsc(ReportStatus.FAILED))
                .thenReturn(Collections.<Report>emptyList());

        assertTrue(service.getReportsByStatus(ReportStatus.FAILED).isEmpty());
    }

    // ----- deleteReport -----

    @Test
    public void deleteReportReturnsFalseForAnUnknownReport() {
        when(reportRepository.findById(99L)).thenReturn(Optional.empty());

        assertFalse(service.deleteReport(99L));

        verify(reportRepository, never()).deleteById(anyLong());
        assertFalse(TransactionSynchronizationManager.getSynchronizations().iterator().hasNext());
    }

    @Test
    public void deleteReportRemovesTheRecordAndDefersFileDeletion() throws Exception {
        File file = tempFolder.newFile("generated.csv");
        Files.write(file.toPath(), "data".getBytes(StandardCharsets.UTF_8));
        Report report = new Report();
        report.setId(21L);
        report.setFilePath(file.getAbsolutePath());
        when(reportRepository.findById(21L)).thenReturn(Optional.of(report));

        assertTrue(service.deleteReport(21L));

        verify(reportRepository).deleteById(21L);
        assertTrue("file must survive until the transaction commits", file.exists());

        TransactionSynchronizationUtils.triggerAfterCommit();

        assertFalse("file must be gone after commit", file.exists());
    }

    @Test
    public void deleteReportToleratesAnAlreadyMissingFile() {
        Report report = new Report();
        report.setId(22L);
        report.setFilePath(new File(tempFolder.getRoot(), "never-written.csv").getAbsolutePath());
        when(reportRepository.findById(22L)).thenReturn(Optional.of(report));

        assertTrue(service.deleteReport(22L));

        TransactionSynchronizationUtils.triggerAfterCommit(); // must not throw
        verify(reportRepository).deleteById(22L);
    }

    @Test
    public void deleteReportRegistersNoCallbackWhenThereIsNoFile() {
        Report report = new Report();
        report.setId(23L);
        report.setFilePath(null);
        when(reportRepository.findById(23L)).thenReturn(Optional.of(report));

        assertTrue(service.deleteReport(23L));

        assertFalse(TransactionSynchronizationManager.getSynchronizations().iterator().hasNext());
        verifyNoInteractions(generationWorker);
    }

    // ----- helpers -----

    private static ReportRequest request() {
        ReportRequest request = new ReportRequest();
        request.setReportName("Monthly usage");
        request.setCategory(ReportCategory.USAGE_ANALYTICS);
        request.setReportType(ReportType.PDF);
        request.setRequestedBy("user-1");
        return request;
    }

    private static org.mockito.stubbing.Answer<Report> withId(long id) {
        return invocation -> {
            Report report = invocation.getArgument(0);
            report.setId(id);
            return report;
        };
    }
}
