"""Commission Pay domain layer extracted from COMMISSION_PKG and DW_ETL_PKG.

Pure business rules: no SQL, no HTTP. Every function takes a tenant-bound
repository so callers cannot reach another tenant's rows.
"""
