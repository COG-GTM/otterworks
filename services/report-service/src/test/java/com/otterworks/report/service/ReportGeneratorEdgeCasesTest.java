package com.otterworks.report.service;

import com.itextpdf.text.pdf.PdfReader;
import com.itextpdf.text.pdf.parser.PdfTextExtractor;
import com.otterworks.report.model.Report;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportStatus;
import com.otterworks.report.model.ReportType;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/**
 * Edge-case tests shared by the three report generators: rows with missing values, blank
 * column names and reports with no data at all. The happy paths are covered by
 * {@link CsvReportGeneratorTest}, {@link PdfReportGeneratorTest} and
 * {@link ExcelReportGeneratorTest}; this class pins down what happens at the boundaries.
 */
public class ReportGeneratorEdgeCasesTest {

    @Rule
    public TemporaryFolder tempFolder = new TemporaryFolder();

    private final CsvReportGenerator csvGenerator = new CsvReportGenerator();
    private final PdfReportGenerator pdfGenerator = new PdfReportGenerator();
    private final ExcelReportGenerator excelGenerator = new ExcelReportGenerator();

    // ----- CSV -----

    @Test
    public void csvRendersMissingValuesAsEmptyFields() throws Exception {
        File file = csvGenerator.generateCsv(report("Sparse CSV"), sparseRows(), outputDir());

        List<String> lines = Files.readAllLines(file.toPath(), StandardCharsets.UTF_8);
        // 4 metadata comments + blank line + header + 2 data rows
        assertEquals(8, lines.size());
        assertEquals("\"event_id\",\"user_id\",\"\"", lines.get(5));
        assertEquals("\"evt-1\",\"user-1\",\"present\"", lines.get(6));
        assertEquals("\"evt-2\",\"\",\"\"", lines.get(7));
    }

    @Test
    public void csvForAnEmptyReportContainsNoRows() throws Exception {
        File file = csvGenerator.generateCsv(report("Empty CSV"), noRows(), outputDir());

        assertTrue(file.exists());
        assertEquals(Collections.emptyList(), Files.readAllLines(file.toPath(), StandardCharsets.UTF_8));
    }

    @Test
    public void csvFileNameIsDerivedFromTheReportName() throws Exception {
        File file = csvGenerator.generateCsv(report("Q1 / Usage Report!"), noRows(), outputDir());

        assertTrue(file.getName(), file.getName().matches("q1___usage_report__\\d{8}_\\d{6}\\.csv"));
    }

    // ----- PDF -----

    @Test
    public void pdfForAnEmptyReportStatesThatThereIsNoData() throws Exception {
        File file = pdfGenerator.generatePdf(report("Empty PDF"), noRows(), outputDir());

        String text = firstPageText(file);
        assertTrue(text, text.contains("No data available for the selected criteria."));
        assertTrue(text, text.contains("Rows: 0"));
    }

    @Test
    public void pdfRendersMissingValuesAsBlankCellsAndKeepsBlankHeaders() throws Exception {
        File file = pdfGenerator.generatePdf(report("Sparse PDF"), sparseRows(), outputDir());

        String text = firstPageText(file);
        assertTrue(text, text.contains("Event id"));
        assertTrue(text, text.contains("User id"));
        assertTrue(text, text.contains("evt-1"));
        assertTrue(text, text.contains("evt-2"));
        assertTrue(text, text.contains("Rows: 2"));
        assertFalse("missing values must not render as the literal null", text.contains("null"));
    }

    // ----- Excel -----

    @Test
    public void excelSummaryFallsBackToNaWhenTheReportHasNoCategory() throws Exception {
        Report report = report("Uncategorised");
        report.setCategory(null);

        File file = excelGenerator.generateExcel(report, noRows(), outputDir());

        try (Workbook workbook = new XSSFWorkbook(Files.newInputStream(file.toPath()))) {
            Sheet summary = workbook.getSheet("Summary");
            assertEquals("Category:", summary.getRow(3).getCell(0).getStringCellValue());
            assertEquals("N/A", summary.getRow(3).getCell(1).getStringCellValue());
            assertEquals(0d, summary.getRow(6).getCell(1).getNumericCellValue(), 0d);
            assertEquals(0, workbook.getSheet("Data").getPhysicalNumberOfRows());
        }
    }

    @Test
    public void excelRendersMissingValuesAsEmptyCellsAndBlankHeaders() throws Exception {
        File file = excelGenerator.generateExcel(report("Sparse Excel"), sparseRows(), outputDir());

        try (Workbook workbook = new XSSFWorkbook(Files.newInputStream(file.toPath()))) {
            Sheet data = workbook.getSheet("Data");
            Row header = data.getRow(0);
            assertEquals("Event id", header.getCell(0).getStringCellValue());
            assertEquals("User id", header.getCell(1).getStringCellValue());
            assertEquals("", header.getCell(2).getStringCellValue());

            assertEquals("evt-1", data.getRow(1).getCell(0).getStringCellValue());
            assertEquals("present", data.getRow(1).getCell(2).getStringCellValue());
            assertEquals("evt-2", data.getRow(2).getCell(0).getStringCellValue());
            assertEquals("", data.getRow(2).getCell(1).getStringCellValue());
            assertEquals("", data.getRow(2).getCell(2).getStringCellValue());
        }
    }

    // ----- helpers -----

    private String outputDir() {
        return tempFolder.getRoot().getAbsolutePath();
    }

    private String firstPageText(File pdf) throws Exception {
        PdfReader reader = new PdfReader(pdf.getAbsolutePath());
        try {
            return PdfTextExtractor.getTextFromPage(reader, 1);
        } finally {
            reader.close();
        }
    }

    private static Report report(String name) {
        Report report = new Report();
        report.setId(1L);
        report.setReportName(name);
        report.setCategory(ReportCategory.USAGE_ANALYTICS);
        report.setReportType(ReportType.CSV);
        report.setStatus(ReportStatus.GENERATING);
        report.setRequestedBy("edge-case-user");
        report.setDateFrom(new Date(1_704_067_200_000L)); // 2024-01-01T00:00:00Z
        report.setDateTo(new Date(1_706_745_600_000L));   // 2024-02-01T00:00:00Z
        return report;
    }

    /** Two rows whose third column has a blank name and whose values are partly missing. */
    private static List<Map<String, Object>> sparseRows() {
        List<Map<String, Object>> rows = new ArrayList<>();

        Map<String, Object> first = new LinkedHashMap<>();
        first.put("event_id", "evt-1");
        first.put("user_id", "user-1");
        first.put("", "present");
        rows.add(first);

        Map<String, Object> second = new LinkedHashMap<>();
        second.put("event_id", "evt-2");
        second.put("user_id", null);
        second.put("", null);
        rows.add(second);

        return rows;
    }

    private static List<Map<String, Object>> noRows() {
        return Collections.<Map<String, Object>>emptyList();
    }
}
