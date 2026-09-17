package com.otterworks.report.service;

import com.otterworks.report.model.Report;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportStatus;
import com.otterworks.report.model.ReportType;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.ss.usermodel.WorkbookFactory;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Collections;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

/**
 * Edge cases shared by the three report generators: rows with null values, blank column names,
 * an empty result set, and a report with no category.
 *
 * The happy paths live in {@code CsvReportGeneratorTest}, {@code PdfReportGeneratorTest} and
 * {@code ExcelReportGeneratorTest}; this class only covers the defensive branches.
 */
public class ReportGeneratorEdgeCasesTest {

    /** 2024-01-01T00:00:00Z */
    private static final Date FROM = new Date(1_704_067_200_000L);

    /** 2024-01-08T00:00:00Z */
    private static final Date TO = new Date(1_704_672_000_000L);

    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    private CsvReportGenerator csvGenerator;
    private PdfReportGenerator pdfGenerator;
    private ExcelReportGenerator excelGenerator;

    @Before
    public void setUp() {
        csvGenerator = new CsvReportGenerator();
        pdfGenerator = new PdfReportGenerator();
        excelGenerator = new ExcelReportGenerator();
    }

    // ----- CSV -----

    @Test
    public void csvRendersNullCellValuesAsEmptyStrings() throws Exception {
        File file = csvGenerator.generateCsv(report(ReportType.CSV), rowWithNullValue(), outputDir());

        String content = new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8);
        assertTrue(content, content.contains("\"evt-1\",\"\""));
    }

    @Test
    public void csvWithNoDataStillProducesAFile() throws Exception {
        File file = csvGenerator.generateCsv(
                report(ReportType.CSV), Collections.<Map<String, Object>>emptyList(), outputDir());

        assertTrue(file.exists());
        assertEquals(0L, file.length());
    }

    // ----- PDF -----

    @Test
    public void pdfRendersNullCellValuesAndBlankColumnNames() throws Exception {
        File file = pdfGenerator.generatePdf(report(ReportType.PDF), rowWithBlankColumn(), outputDir());

        assertTrue(file.exists());
        assertTrue(file.length() > 0);
    }

    @Test
    public void pdfWithNoDataRendersThePlaceholderPage() throws Exception {
        File file = pdfGenerator.generatePdf(
                report(ReportType.PDF), Collections.<Map<String, Object>>emptyList(), outputDir());

        assertTrue(file.exists());
        assertTrue(file.length() > 0);
    }

    // ----- Excel -----

    @Test
    public void excelRendersNullCellValuesAndBlankColumnNames() throws Exception {
        File file = excelGenerator.generateExcel(
                report(ReportType.EXCEL), rowWithBlankColumn(), outputDir());

        try (Workbook workbook = WorkbookFactory.create(file)) {
            Sheet data = workbook.getSheet("Data");
            assertEquals("", data.getRow(0).getCell(1).getStringCellValue());
            assertEquals("", data.getRow(1).getCell(1).getStringCellValue());
        }
    }

    @Test
    public void excelSummarySheetFallsBackToNaForAReportWithoutACategory() throws Exception {
        Report report = report(ReportType.EXCEL);
        report.setCategory(null);

        File file = excelGenerator.generateExcel(
                report, Collections.<Map<String, Object>>emptyList(), outputDir());

        try (Workbook workbook = WorkbookFactory.create(file)) {
            assertEquals("N/A", workbook.getSheet("Summary").getRow(3).getCell(1).getStringCellValue());
        }
    }

    // ----- helpers -----

    private String outputDir() {
        return tmp.getRoot().getAbsolutePath();
    }

    private static List<Map<String, Object>> rowWithNullValue() {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("event_id", "evt-1");
        row.put("duration_ms", null);
        return Collections.singletonList(row);
    }

    /** A row whose second column has both a blank header and a null value. */
    private static List<Map<String, Object>> rowWithBlankColumn() {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("event_id", "evt-1");
        row.put("   ", null);
        return Collections.singletonList(row);
    }

    private static Report report(ReportType type) {
        Report report = new Report();
        report.setId(1L);
        report.setReportName("Edge Case Report");
        report.setCategory(ReportCategory.USAGE_ANALYTICS);
        report.setReportType(type);
        report.setStatus(ReportStatus.GENERATING);
        report.setRequestedBy("user-1");
        report.setDateFrom(FROM);
        report.setDateTo(TO);
        return report;
    }
}
