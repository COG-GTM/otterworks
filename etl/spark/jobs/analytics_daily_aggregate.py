"""PySpark aggregation for analytics_daily.

Submitted by the ``analytics_daily`` DAG via SparkSubmitOperator (``local[*]``) or as an
EMR step. Self-contained on purpose (no imports from the Airflow package) so it can be
shipped to a cluster as a single file.

Reads raw JSON-lines events (gzip ok) from ``--input`` and writes, under ``--output``:

* ``events/``      normalized, de-duplicated events as Parquet (overwritten per run)
* ``aggregates/``  one line of JSON: ``{"summary", "hourly_breakdown", "top_users"}``

Semantics mirror ``otterworks_etl.transforms.analytics`` (the reference implementation the
parity tests compare against).
"""

from __future__ import annotations

import argparse
import json
import sys

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.utils import AnalysisException

USER_ID_FIELDS = ("ownerId", "editedBy", "authorId", "deletedBy", "userId")
EVENT_KEY_FIELDS = ("eventId", "event_id", "id", "_source_id")
DOC_TYPES = ("document_created", "document_edited")
FILE_TYPES = ("file_uploaded", "file_shared", "file_deleted")
COUNTED_TYPES = ("document_created", "document_edited", "comment_added",
                 "file_uploaded", "file_shared", "file_deleted")
ISO_HOUR = r"^\d{4}-\d{2}-\d{2}[T ](\d{2}):"


def _nonempty(df: DataFrame, name: str):
    """Column as string, NULL when absent / null / empty string."""
    if name not in df.columns:
        return F.lit(None).cast("string")
    c = F.col(f"`{name}`").cast("string")
    return F.when(c.isNotNull() & (c != ""), c)


def read_events(spark: SparkSession, path: str) -> DataFrame:
    try:
        df = spark.read.option("mode", "PERMISSIVE").json(path)
    except AnalysisException:  # no input files for this ds
        return spark.createDataFrame([], "dummy string")
    if "_corrupt_record" in df.columns:
        df = df.filter(F.col("_corrupt_record").isNull()).drop("_corrupt_record")
    return df


def normalize(df: DataFrame) -> DataFrame:
    hour = F.regexp_extract(F.coalesce(_nonempty(df, "timestamp"), F.lit("")), ISO_HOUR, 1)
    out = df.select(
        F.coalesce(*[_nonempty(df, f) for f in EVENT_KEY_FIELDS]).alias("event_key"),
        F.coalesce(_nonempty(df, "eventType"), _nonempty(df, "event_type"),
                   F.lit("unknown")).alias("event_type"),
        F.coalesce(*[_nonempty(df, f) for f in USER_ID_FIELDS], F.lit("unknown")).alias("user_id"),
        _nonempty(df, "documentId").alias("document_id"),
        _nonempty(df, "fileId").alias("file_id"),
        F.coalesce(_nonempty(df, "sizeBytes").cast("double").cast("long"),
                   F.lit(0).cast("long")).alias("size_bytes"),
        F.when(hour == "", F.lit("00")).otherwise(hour).alias("hour"),
    )
    keyed = out.filter(F.col("event_key").isNotNull()).dropDuplicates(["event_key"])
    return keyed.unionByName(out.filter(F.col("event_key").isNull()))


def aggregate(events: DataFrame, top_n: int = 100) -> dict:
    events = events.cache()
    by_type = {r["event_type"]: r["count"] for r in events.groupBy("event_type").count().collect()}
    row = events.agg(
        F.count(F.lit(1)).alias("total_events"),
        F.countDistinct(F.when(F.col("user_id") != "unknown", F.col("user_id"))).alias("active_users"),
        F.countDistinct(F.when(F.col("event_type").isin(*DOC_TYPES),
                               F.col("document_id"))).alias("active_documents"),
        F.countDistinct(F.when(F.col("event_type").isin(*FILE_TYPES),
                               F.col("file_id"))).alias("active_files"),
        F.sum(F.when(F.col("event_type") == "file_uploaded", F.col("size_bytes"))
              .otherwise(0)).alias("bytes_uploaded"),
    ).collect()[0]
    summary = {
        "active_users": int(row["active_users"]),
        "active_documents": int(row["active_documents"]),
        "active_files": int(row["active_files"]),
        "total_events": int(row["total_events"]),
        "documents_created": int(by_type.get("document_created", 0)),
        "documents_edited": int(by_type.get("document_edited", 0)),
        "comments_added": int(by_type.get("comment_added", 0)),
        "files_uploaded": int(by_type.get("file_uploaded", 0)),
        "files_shared": int(by_type.get("file_shared", 0)),
        "files_deleted": int(by_type.get("file_deleted", 0)),
        "bytes_uploaded": int(row["bytes_uploaded"] or 0),
    }

    hourly: dict[str, dict] = {}
    for r in events.groupBy("hour", "event_type").count().collect():
        hourly.setdefault(r["hour"], {})[r["event_type"]] = int(r["count"])

    per_user = events.groupBy("user_id", "event_type").count()
    top = (per_user.groupBy("user_id").agg(F.sum("count").alias("total"))
           .orderBy(F.col("total").desc(), F.col("user_id").asc()).limit(top_n))
    actions: dict[str, dict] = {}
    for r in per_user.join(F.broadcast(top.select("user_id")), "user_id").collect():
        actions.setdefault(r["user_id"], {})[r["event_type"]] = int(r["count"])
    top_users = [{"user_id": r["user_id"], "actions": dict(sorted(actions[r["user_id"]].items())),
                  "total": int(r["total"])} for r in top.collect()]

    return {
        "summary": summary,
        "hourly_breakdown": {h: dict(sorted(c.items())) for h, c in sorted(hourly.items())},
        "top_users": top_users,
    }


def run(spark: SparkSession, ds: str, input_path: str, output_path: str, top_n: int) -> dict:
    events = normalize(read_events(spark, input_path)).withColumn("ds", F.lit(ds))
    events.write.mode("overwrite").parquet(f"{output_path}/events")
    agg = aggregate(events, top_n)
    (spark.createDataFrame([(json.dumps(agg, sort_keys=True),)], "value string")
     .coalesce(1).write.mode("overwrite").text(f"{output_path}/aggregates"))
    return agg


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--ds", required=True)
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--top-n", type=int, default=100)
    args = p.parse_args(argv)
    spark = (SparkSession.builder.appName(f"otterworks-analytics-{args.ds}")
             .config("spark.sql.session.timeZone", "UTC").getOrCreate())
    try:
        agg = run(spark, args.ds, args.input, args.output, args.top_n)
        print(json.dumps({"event": "spark_aggregate_complete", "ds": args.ds,
                          "output": args.output, **agg["summary"]}))
    finally:
        spark.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
