package com.otterworks.report.service;

import com.otterworks.report.model.Report;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportStatus;
import com.otterworks.report.model.ReportType;
import com.lowagie.text.pdf.PdfReader;
import com.lowagie.text.pdf.parser.PdfTextExtractor;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

/**
 * Unit tests for {@link PdfReportGenerator}.
 *
 * Validates that the generator produces a syntactically valid PDF file with
 * correct size, header bytes, and non-trivial content. Does not require a
 * Spring context -- instantiates the generator directly.
 *
 * Written in JUnit 4 style to match the current stack. After the JUnit 5
 * migration (Axis 4), replace:
 *   - org.junit.Test   -> org.junit.jupiter.api.Test
 *   - org.junit.Before -> org.junit.jupiter.api.BeforeEach
 *   - org.junit.After  -> org.junit.jupiter.api.AfterEach
 *   - org.junit.Assert -> org.junit.jupiter.api.Assertions
 */
public class PdfReportGeneratorTest {

    private PdfReportGenerator generator;
    private File outputDir;

    @Before
    public void setUp() {
        generator = new PdfReportGenerator();
        outputDir = new File(System.getProperty("java.io.tmpdir"), "pdf-test-" + System.currentTimeMillis());
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
    public void generatePdfProducesNonEmptyFile() throws IOException {
        Report report = buildReport("Usage Analytics Report");
        List<Map<String, Object>> data = buildSampleData(5);

        File pdf = generator.generatePdf(report, data, outputDir.getAbsolutePath());

        assertNotNull("PDF file should not be null", pdf);
        assertTrue("PDF file should exist", pdf.exists());
        assertTrue("PDF file should have content", pdf.length() > 0);
        assertTrue("PDF file should have .pdf extension", pdf.getName().endsWith(".pdf"));
    }

    @Test
    public void generatedPdfStartsWithPdfHeader() throws IOException {
        Report report = buildReport("Header Check Report");
        List<Map<String, Object>> data = buildSampleData(3);

        File pdf = generator.generatePdf(report, data, outputDir.getAbsolutePath());

        byte[] header = new byte[5];
        try (FileInputStream fis = new FileInputStream(pdf)) {
            int bytesRead = fis.read(header);
            assertEquals("Should read 5 header bytes", 5, bytesRead);
        }
        // PDF files always start with %PDF-
        assertEquals("First byte should be '%'", '%', (char) header[0]);
        assertEquals("Second byte should be 'P'", 'P', (char) header[1]);
        assertEquals("Third byte should be 'D'", 'D', (char) header[2]);
        assertEquals("Fourth byte should be 'F'", 'F', (char) header[3]);
        assertEquals("Fifth byte should be '-'", '-', (char) header[4]);
    }

    @Test
    public void generatePdfWithMultipleRowsProducesLargerFile() throws IOException {
        Report report1 = buildReport("Small Data Report");
        List<Map<String, Object>> smallData = buildSampleData(2);
        File smallPdf = generator.generatePdf(report1, smallData, outputDir.getAbsolutePath());

        Report report2 = buildReport("Large Data Report");
        List<Map<String, Object>> largeData = buildSampleData(50);
        File largePdf = generator.generatePdf(report2, largeData, outputDir.getAbsolutePath());

        assertTrue("Larger dataset should produce a larger PDF",
                largePdf.length() > smallPdf.length());
    }

    @Test
    public void generatePdfWithEmptyDataProducesValidPdf() throws IOException {
        Report report = buildReport("Empty Data Report");
        List<Map<String, Object>> emptyData = new ArrayList<Map<String, Object>>();

        File pdf = generator.generatePdf(report, emptyData, outputDir.getAbsolutePath());

        assertNotNull("PDF file should not be null", pdf);
        assertTrue("PDF file should exist even with no data", pdf.exists());
        assertTrue("PDF file should have content (header/footer)", pdf.length() > 0);

        byte[] header = new byte[5];
        try (FileInputStream fis = new FileInputStream(pdf)) {
            fis.read(header);
        }
        assertEquals('%', (char) header[0]);
        assertEquals('P', (char) header[1]);
    }

    @Test
    public void generatePdfFileNameContainsReportName() throws IOException {
        Report report = buildReport("Quarterly Audit Summary");
        List<Map<String, Object>> data = buildSampleData(1);

        File pdf = generator.generatePdf(report, data, outputDir.getAbsolutePath());

        assertTrue("File name should contain sanitized report name",
                pdf.getName().startsWith("quarterly_audit_summary_"));
    }

    @Test
    public void generatedPdfContainsExpectedText() throws IOException {
        Report report = buildReport("Usage Analytics Report");
        List<Map<String, Object>> data = buildSampleData(3);

        File pdf = generator.generatePdf(report, data, outputDir.getAbsolutePath());

        PdfReader reader = new PdfReader(pdf.getAbsolutePath());
        String text;
        try {
            assertEquals("Report should fit on one page", 1, reader.getNumberOfPages());
            text = new PdfTextExtractor(reader).getTextFromPage(1);
        } finally {
            reader.close();
        }
        for (String expected : Arrays.asList(
                "OtterWorks Report", "Usage Analytics Report", "Period:", "Rows: 3",
                "User id", "Action", "File count", "Bytes transferred",
                "alice", "upload", "carol", "3072",
                "This report was generated by OtterWorks Report Service v0.1.0.")) {
            assertTrue("PDF text should contain '" + expected + "' but was: " + text, text.contains(expected));
        }
    }

    // ---- Helpers ----

    private Report buildReport(String name) {
        Report report = new Report();
        report.setId(1L);
        report.setReportName(name);
        report.setCategory(ReportCategory.USAGE_ANALYTICS);
        report.setReportType(ReportType.PDF);
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
        String[] actions = {"login", "upload", "download", "share", "delete"};

        for (int i = 0; i < rows; i++) {
            Map<String, Object> row = new LinkedHashMap<String, Object>();
            row.put("user_id", users[i % users.length]);
            row.put("action", actions[i % actions.length]);
            row.put("timestamp", new Date(System.currentTimeMillis() - (long) i * 3600000));
            row.put("file_count", i * 3 + 1);
            row.put("bytes_transferred", (i + 1) * 1024L);
            data.add(row);
        }
        return data;
    }
}
