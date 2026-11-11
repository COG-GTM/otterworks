package com.otterworks.analytics.api

/** CSV cell encoding shared by the export endpoints. */
object Csv:

  // Leading characters a spreadsheet would evaluate as a formula.
  private val FormulaTriggers = Set('=', '+', '-', '@', '\t', '\r')

  /** Escapes a text cell: neutralizes formula triggers, then applies RFC 4180 quoting. */
  def textField(value: String): String =
    val neutralized =
      if value.nonEmpty && FormulaTriggers.contains(value.head) then "'" + value else value
    if neutralized.exists(c => c == ',' || c == '"' || c == '\n' || c == '\r') then
      "\"" + neutralized.replace("\"", "\"\"") + "\""
    else neutralized
