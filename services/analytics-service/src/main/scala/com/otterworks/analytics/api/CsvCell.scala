package com.otterworks.analytics.api

/**
 * Cell encoding for the CSV export endpoints.
 *
 * Text cells are neutralized against spreadsheet formula injection (CWE-1236):
 * a value starting with `=`, `+`, `-`, `@`, tab, CR or LF is prefixed with a
 * single quote so Excel/LibreOffice/Sheets render it as a literal string. RFC
 * 4180 quoting alone does not stop formula evaluation. Numeric cells come from
 * typed numbers and are never prefixed, so negative values stay numeric.
 */
object CsvCell:

  private val FormulaTriggers: Set[Char] = Set('=', '+', '-', '@', '\t', '\r', '\n')

  def text(value: String): String = quote(neutralize(value))

  def number(value: BigDecimal): String = quote(value.toString)

  private[api] def neutralize(value: String): String =
    if value.nonEmpty && FormulaTriggers.contains(value.charAt(0)) then "'" + value
    else value

  private def quote(value: String): String =
    if value.exists(c => c == ',' || c == '"' || c == '\n' || c == '\r') then
      "\"" + value.replace("\"", "\"\"") + "\""
    else value
