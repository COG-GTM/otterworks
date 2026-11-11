package com.otterworks.report.service;

import com.opencsv.CSVWriter;
import com.otterworks.report.model.Report;
import com.otterworks.report.util.ReportDateUtils;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * Generates CSV reports using OpenCSV 4.6.
 *
 * LEGACY PATTERNS:
 * - OpenCSV 4.x (2018). Upgrade target: 5.9+ (different bean mapping API)
 * - FileWriter without explicit charset (platform-dependent encoding)
 * - Manual column extraction from Map keys
 *
 * UPGRADE NOTES:
 * - OpenCSV 5.x changed CSVWriter constructor signatures
 * - Bean-to-CSV mapping API completely rewritten in 5.x
 * - Should specify charset explicitly (StandardCharsets.UTF_8)
 */
@Component
public class CsvReportGenerator {

    private static final Logger logger = LoggerFactory.getLogger(CsvReportGenerator.class);

    private static final Pattern PLAIN_NUMBER = Pattern.compile("[+-]?\\d+(\\.\\d+)?([eE][+-]?\\d+)?");

    private final ReportHeaderRenderer headerRenderer;

    public CsvReportGenerator() {
        this(new ReportHeaderRenderer());
    }

    public CsvReportGenerator(ReportHeaderRenderer headerRenderer) {
        this.headerRenderer = headerRenderer;
    }

    /**
     * Generate a CSV report file.
     *
     * @return the File object for the generated CSV
     */
    public File generateCsv(Report report, List<Map<String, Object>> data, String outputDir) throws IOException {
        String fileName = buildFileName(report, "csv");
        File outputFile = new File(outputDir, fileName);
        outputFile.getParentFile().mkdirs();

        // LEGACY: FileWriter without charset (uses platform default encoding)
        // Modern: new OutputStreamWriter(new FileOutputStream(file), StandardCharsets.UTF_8)
        try (CSVWriter writer = new CSVWriter(new FileWriter(outputFile))) {

            if (!data.isEmpty()) {
                // Extract column headers from first row
                Set<String> columns = new LinkedHashSet<>(data.get(0).keySet());
                String[] header = columns.toArray(new String[0]);

                // Write metadata comments from the configured banner templates
                Map<String, String> bannerVars = new LinkedHashMap<String, String>();
                bannerVars.put("reportName", report.getReportName());
                bannerVars.put("generated", ReportDateUtils.toDisplayString(new Date()));
                bannerVars.put("periodFrom", ReportDateUtils.toDisplayString(report.getDateFrom()));
                bannerVars.put("periodTo", ReportDateUtils.toDisplayString(report.getDateTo()));
                bannerVars.put("rows", String.valueOf(data.size()));

                writeRow(writer, headerRenderer.title(bannerVars));
                writeRow(writer, headerRenderer.generated(bannerVars));
                writeRow(writer, headerRenderer.period(bannerVars));
                writeRow(writer, headerRenderer.rows(bannerVars));
                writeRow(writer, headerRenderer.footer());
                writeRow(writer, "");

                // Write header row
                writeRow(writer, header);

                // Write data rows
                for (Map<String, Object> row : data) {
                    String[] values = new String[columns.size()];
                    int i = 0;
                    for (String col : columns) {
                        Object value = row.get(col);
                        values[i++] = value != null ? value.toString() : "";
                    }
                    writeRow(writer, values);
                }
            }
        }

        logger.info("Generated CSV report: {} ({} bytes)", outputFile.getAbsolutePath(), outputFile.length());
        return outputFile;
    }

    private static void writeRow(CSVWriter writer, String... cells) {
        String[] escaped = new String[cells.length];
        for (int i = 0; i < cells.length; i++) {
            escaped[i] = escapeCell(cells[i]);
        }
        writer.writeNext(escaped);
    }

    /**
     * Neutralizes spreadsheet formula injection (OWASP "CSV Injection"): a cell
     * starting with =, +, -, @, tab or carriage return is prefixed with a single
     * quote so spreadsheet applications treat it as text. Plain numbers such as
     * -42 or +3.5 are left untouched.
     */
    static String escapeCell(String value) {
        if (value == null || value.isEmpty()) {
            return value;
        }
        char first = value.charAt(0);
        boolean formulaTrigger = first == '=' || first == '+' || first == '-' || first == '@'
                || first == '\t' || first == '\r';
        if (!formulaTrigger || PLAIN_NUMBER.matcher(value).matches()) {
            return value;
        }
        return "'" + value;
    }

    private String buildFileName(Report report, String extension) {
        String safeName = report.getReportName().replaceAll("[^a-zA-Z0-9]", "_").toLowerCase();
        return safeName + "_" + ReportDateUtils.toFileNameString(new Date()) + "." + extension;
    }
}
