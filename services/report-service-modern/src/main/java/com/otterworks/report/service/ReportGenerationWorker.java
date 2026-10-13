package com.otterworks.report.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.otterworks.report.config.ReportProperties;
import com.otterworks.report.model.Report;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportStatus;
import com.otterworks.report.repository.ReportRepository;
import com.otterworks.report.util.ReportDateUtils;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Component;

import java.io.File;
import java.time.Instant;
import java.util.List;
import java.util.Map;

@Component
public class ReportGenerationWorker {

    private static final Logger logger = LoggerFactory.getLogger(ReportGenerationWorker.class);
    private static final ObjectMapper PARAMETER_MAPPER = new ObjectMapper();
    private static final TypeReference<Map<String, String>> PARAMETER_TYPE = new TypeReference<>() { };

    private final ReportRepository reportRepository;
    private final ReportDataFetcher dataFetcher;
    private final PdfReportGenerator pdfGenerator;
    private final CsvReportGenerator csvGenerator;
    private final ExcelReportGenerator excelGenerator;
    private final ReportProperties properties;

    public ReportGenerationWorker(
            ReportRepository reportRepository,
            ReportDataFetcher dataFetcher,
            PdfReportGenerator pdfGenerator,
            CsvReportGenerator csvGenerator,
            ExcelReportGenerator excelGenerator,
            ReportProperties properties) {
        this.reportRepository = reportRepository;
        this.dataFetcher = dataFetcher;
        this.pdfGenerator = pdfGenerator;
        this.csvGenerator = csvGenerator;
        this.excelGenerator = excelGenerator;
        this.properties = properties;
    }

    @Async
    public void generateReportAsync(Long reportId) {
        Report report = reportRepository.findById(reportId).orElse(null);
        if (report == null) {
            logger.error("Report not found for generation: {}", reportId);
            return;
        }

        report.setStatus(ReportStatus.GENERATING);
        reportRepository.save(report);

        try {
            Map<String, String> params = report.getParameters() != null
                    ? PARAMETER_MAPPER.readValue(report.getParameters(), PARAMETER_TYPE)
                    : null;

            List<Map<String, Object>> data = fetchDataForCategory(
                    report.getCategory(), report.getDateFrom(), report.getDateTo(), params);

            int maxRows = properties.report().maxRows();
            if (data.size() > maxRows) {
                data = data.subList(0, maxRows);
                logger.warn("Report {} truncated to {} rows", reportId, maxRows);
            }

            File outputFile = generateFile(report, data);

            report.setStatus(ReportStatus.COMPLETED);
            report.setCompletedAt(ReportDateUtils.now());
            report.setFilePath(outputFile.getAbsolutePath());
            report.setFileSizeBytes(outputFile.length());
            report.setRowCount(data.size());
            reportRepository.save(report);

            logger.info("Report {} completed: {} rows, {} bytes, took {}", reportId, data.size(),
                    outputFile.length(),
                    ReportDateUtils.humanReadableDuration(report.getCreatedAt(), report.getCompletedAt()));
        } catch (Exception e) {
            logger.error("Report generation failed for {}: {}", reportId, e.getMessage(), e);
            report.setStatus(ReportStatus.FAILED);
            report.setCompletedAt(ReportDateUtils.now());
            report.setErrorMessage(e.getMessage());
            reportRepository.save(report);
        }
    }

    private List<Map<String, Object>> fetchDataForCategory(
            ReportCategory category, Instant dateFrom, Instant dateTo, Map<String, String> params) {
        return switch (category) {
            case USAGE_ANALYTICS, COLLABORATION_METRICS, SYSTEM_HEALTH ->
                    dataFetcher.fetchAnalyticsData(dateFrom, dateTo, params);
            case AUDIT_LOG, COMPLIANCE -> dataFetcher.fetchAuditData(dateFrom, dateTo, params);
            case USER_ACTIVITY, STORAGE_SUMMARY -> dataFetcher.fetchUserActivityData(dateFrom, dateTo, params);
        };
    }

    private File generateFile(Report report, List<Map<String, Object>> data) throws Exception {
        String outputDir = properties.report().outputDir();
        return switch (report.getReportType()) {
            case PDF -> pdfGenerator.generatePdf(report, data, outputDir);
            case CSV -> csvGenerator.generateCsv(report, data, outputDir);
            case EXCEL -> excelGenerator.generateExcel(report, data, outputDir);
        };
    }
}
