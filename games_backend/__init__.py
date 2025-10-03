# Optional MySQL driver shim: allow using PyMySQL when mysqlclient isn't installed.
try:  # Prefer native mysqlclient (MySQLdb) if available
    import MySQLdb  # type: ignore  # noqa: F401
except Exception:
    try:
        import pymysql  # type: ignore

        pymysql.install_as_MySQLdb()
    except Exception:
        # If PyMySQL isn't installed, Django will raise a clear error when connecting.
        pass
