package com.otterworks.report.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.otterworks.report.model.Report;
import com.otterworks.report.model.ReportRequest;
import com.otterworks.report.model.ReportStatus;
import com.otterworks.report.repository.ReportRepository;
import com.otterworks.report.util.ReportDateUtils;
import jakarta.transaction.Transactional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.Optional;

@Service
public class ReportService {

    private static final Logger logger = LoggerFactory.getLogger(ReportService.class);
    private static final ObjectMapper PARAMETER_MAPPER = new ObjectMapper();

    private final ReportRepository reportRepository;
    private final ReportGenerationWorker generationWorker;

    public ReportService(ReportRepository reportRepository, ReportGenerationWorker generationWorker) {
        this.reportRepository = reportRepository;
        this.generationWorker = generationWorker;
    }

    @Transactional
    public Report createReport(ReportRequest request) {
        Instant now = ReportDateUtils.now();
        Report report = new Report();
        report.setReportName(request.reportName());
        report.setCategory(request.category());
        report.setReportType(request.reportType());
        report.setRequestedBy(request.requestedBy());
        report.setStatus(ReportStatus.PENDING);
        report.setCreatedAt(now);
        report.setDateFrom(Objects.requireNonNullElseGet(request.dateFrom(), () -> ReportDateUtils.daysAgo(30)));
        report.setDateTo(Objects.requireNonNullElse(request.dateTo(), now));

        if (request.parameters() != null) {
            try {
                report.setParameters(PARAMETER_MAPPER.writeValueAsString(request.parameters()));
            } catch (JsonProcessingException e) {
                logger.warn("Failed to serialize report parameters: {}", e.getMessage());
            }
        }

        Report saved = reportRepository.save(report);
        logger.info("Created report request: id={}, name={}, type={}",
                saved.getId(), saved.getReportName(), saved.getReportType());

        Long reportId = saved.getId();
        afterCommit(() -> generationWorker.generateReportAsync(reportId));
        return saved;
    }

    public Optional<Report> getReport(Long id) {
        return reportRepository.findById(id);
    }

    public List<Report> getReportsByUser(String userId) {
        return reportRepository.findByRequestedByOrderByCreatedAtDesc(userId);
    }

    public List<Report> getReportsByStatus(ReportStatus status) {
        return reportRepository.findByStatusOrderByCreatedAtAsc(status);
    }

    @Transactional
    public boolean deleteReport(Long id) {
        Optional<Report> report = reportRepository.findById(id);
        if (report.isEmpty()) {
            return false;
        }
        String filePath = report.get().getFilePath();
        reportRepository.deleteById(id);
        logger.info("Deleted report: {}", id);

        if (filePath != null) {
            afterCommit(() -> {
                try {
                    Files.deleteIfExists(Path.of(filePath));
                } catch (IOException e) {
                    logger.warn("Failed to delete report file: {}", filePath);
                }
            });
        }
        return true;
    }

    private static void afterCommit(Runnable action) {
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                action.run();
            }
        });
    }
}
