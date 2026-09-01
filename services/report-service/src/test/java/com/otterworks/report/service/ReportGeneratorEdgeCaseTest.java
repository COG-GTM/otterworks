package com.otterworks.report.service;

import com.otterworks.report.model.Report;
import com.otterworks.report.model.ReportStatus;
import com.otterworks.report.model.ReportType;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.File;
import java.io.FileInputStream;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

/**
 * Edge cases shared by the three report generators: rows containing {@code null} values,
 * a blank column name, and a report with no category set.
 *
 * The existing per-generator tests cover the well-formed happy paths; these cover the
 * defensive branches around them.
 */
public class ReportGeneratorEdgeCaseTest {

    @Rule
    public TemporaryFolder tempFolder = new TemporaryFolder();

    private static final Date FROM = new Date(1_704_067_200_000L); // 2024-01-01T00:00:00Z
    private static final Date TO = new Date(1_706_745_600_000L);   // 2024-02-01T00:00:00Z

    @Test
    public void csvRendersNullCellsAsEmptyStrings() throws Exception {
        File file = new CsvReportGenerator().generateCsv(
                report(ReportType.CSV), rowsWithNullAndBlankColumn(), outputDir());

        String content = readAll(file);
        assertTrue(content, content.contains("\"\""));
        assertTrue(content, content.contains("otter"));
    }

    @Test
    public void pdfRendersNullCellsAndBlankColumnNamesWithoutFailing() throws Exception {
        File file = new PdfReportGenerator().generatePdf(
                report(ReportType.PDF), rowsWithNullAndBlankColumn(), outputDir());

        assertTrue(file.exists());
        assertTrue("expected a non-trivial PDF, was " + file.length() + " bytes", file.length() > 500);
    }

    @Test
    public void pdfHandlesAnEmptyDataSet() throws Exception {
        File file = new PdfReportGenerator().generatePdf(
                report(ReportType.PDF), Collections.<Map<String, Object>>emptyList(), outputDir());

        assertTrue(file.exists());
        assertTrue(file.length() > 500);
    }

    @Test
    public void excelRendersNullCellsAsEmptyStringsAndFormatsBlankColumnNames() throws Exception {
        File file = new ExcelReportGenerator().generateExcel(
                report(ReportType.EXCEL), rowsWithNullAndBlankColumn(), outputDir());

        FileInputStream in = new FileInputStream(file);
        try {
            Workbook workbook = new XSSFWorkbook(in);
            try {
                Sheet data = workbook.getSheet("Data");
                assertEquals("Name", data.getRow(0).getCell(0).getStringCellValue());
                assertEquals("", data.getRow(0).getCell(2).getStringCellValue());
                assertEquals("otter", data.getRow(1).getCell(0).getStringCellValue());
                assertEquals("", data.getRow(1).getCell(1).getStringCellValue());
            } finally {
                workbook.close();
            }
        } finally {
            in.close();
        }
    }

    @Test
    public void excelWritesNotAvailableWhenTheReportHasNoCategory() throws Exception {
        Report report = report(ReportType.EXCEL);
        report.setCategory(null);

        File file = new ExcelReportGenerator().generateExcel(
                report, Collections.<Map<String, Object>>emptyList(), outputDir());

        FileInputStream in = new FileInputStream(file);
        try {
            Workbook workbook = new XSSFWorkbook(in);
            try {
                Sheet summary = workbook.getSheet("Summary");
                assertEquals("N/A", summary.getRow(3).getCell(1).getStringCellValue());
            } finally {
                workbook.close();
            }
        } finally {
            in.close();
        }
    }

    // ----- helpers -----

    private String outputDir() {
        return tempFolder.getRoot().getAbsolutePath();
    }

    private static String readAll(File file) throws Exception {
        return org.apache.commons.io.FileUtils.readFileToString(file, "UTF-8");
    }

    private static List<Map<String, Object>> rowsWithNullAndBlankColumn() {
        Map<String, Object> row = new LinkedHashMap<String, Object>();
        row.put("name", "otter");
        row.put("notes", null);
        row.put("", "unnamed column");
        List<Map<String, Object>> rows = new ArrayList<Map<String, Object>>();
        rows.add(row);
        return rows;
    }

    private static Report report(ReportType type) {
        Report report = new Report();
        report.setId(1L);
        report.setReportName("Edge Cases");
        report.setCategory(com.otterworks.report.model.ReportCategory.USAGE_ANALYTICS);
        report.setReportType(type);
        report.setStatus(ReportStatus.GENERATING);
        report.setRequestedBy("user-1");
        report.setCreatedAt(FROM);
        report.setDateFrom(FROM);
        report.setDateTo(TO);
        return report;
    }
}
