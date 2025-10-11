#!/usr/bin/env python3
"""
Standalone loader for the Deepfake questions dataset.

Reads a CSV whose header matches the DB fields (id, real_img, ai_img, analysis) and
imports the rows into the `deepfake_deepfakequestion` table.

The script is intentionally lightweight and does not import Django; it connects
directly via PyMySQL using a DATABASE_URL provided either as a CLI argument or read
from the project's .env file.
"""

import argparse
import csv
import sys
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

try:
    import pymysql
except Exception as exc:  # pragma: no cover
    print("PyMySQL is required. Install via `pip install PyMySQL`.", file=sys.stderr)
    raise


EXPECTED_HEADERS = ["id", "real_img", "ai_img", "analysis"]


def _read_env_database_url(base_dir: Path) -> Optional[str]:
    env_path = base_dir / ".env"
    if not env_path.exists():
        return None
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.upper().startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        return None
    return None


def _parse_mysql_url(url: str) -> Tuple[str, int, str, str, str, str]:
    """Return connection parameters (host, port, user, password, database, charset)."""
    parsed = urlparse(url)
    if parsed.scheme not in {"mysql", "mariadb"}:
        raise ValueError("This importer only supports mysql:// or mariadb:// URLs.")

    host = parsed.hostname or "localhost"
    port = parsed.port or 3306
    user = parsed.username or ""
    password = parsed.password or ""
    database = (parsed.path or "/").lstrip("/")
    qs = parse_qs(parsed.query)
    charset = (qs.get("charset", ["utf8mb4"]) or ["utf8mb4"])[0]
    return host, int(port), user, password, database, charset


def _sanitize_table_name(name: str) -> str:
    if not name or not all(c.isalnum() or c in {"_", "$", "."} for c in name):
        raise ValueError("Invalid table name.")
    return name


def _validate_headers(fieldnames: List[str]) -> None:
    normalized = [f.strip() for f in fieldnames]
    if normalized != EXPECTED_HEADERS:
        raise ValueError(
            f"CSV header must exactly match {EXPECTED_HEADERS}, got {normalized}."
        )


def main() -> int:
    base_dir = Path(__file__).resolve().parent

    parser = argparse.ArgumentParser(
        description="Import Deepfake CSV data into the database."
    )
    parser.add_argument(
        "--csv-path",
        default="Resources/deepfake/deepfake_data.csv",
        help="Path to CSV file (default: Resources/deepfake/deepfake_data.csv)",
    )
    parser.add_argument(
        "--database-url",
        dest="database_url",
        help="MySQL/MariaDB URL, e.g. mysql://user:pass@host:3306/dbname",
    )
    parser.add_argument(
        "--table",
        default="deepfake_deepfakequestion",
        help="Target table name (default: deepfake_deepfakequestion)",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8-sig",
        help="CSV encoding (default: utf-8-sig; use gbk if needed)",
    )
    parser.add_argument(
        "--delimiter",
        default=",",
        help="CSV delimiter (default: ,)",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Delete all existing rows before import.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Batch size for executemany (default: 200)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse CSV only, do not write to the database.",
    )

    args = parser.parse_args()

    csv_path = Path(args.csv_path).expanduser()
    if not csv_path.exists():
        print(f"CSV file not found: {csv_path}", file=sys.stderr)
        return 2

    database_url = args.database_url or _read_env_database_url(base_dir)
    if not database_url:
        print("DATABASE_URL not provided and .env missing or invalid.", file=sys.stderr)
        return 2

    try:
        host, port, user, password, database, charset = _parse_mysql_url(database_url)
    except Exception as exc:
        print(f"Invalid DATABASE_URL: {exc}", file=sys.stderr)
        return 2

    table = _sanitize_table_name(args.table)

    try:
        with csv_path.open("r", encoding=args.encoding, newline="") as handle:
            reader = csv.DictReader(handle, delimiter=args.delimiter)
            if not reader.fieldnames:
                print("CSV header row is missing.", file=sys.stderr)
                return 2
            _validate_headers(reader.fieldnames)

            rows: List[Tuple[int, str, str, str]] = []
            for row in reader:
                try:
                    pk = int(row["id"])
                except (TypeError, ValueError):
                    print(f"Skipping row with invalid id: {row}", file=sys.stderr)
                    continue
                real_img = (row.get("real_img") or "").strip()
                ai_img = (row.get("ai_img") or "").strip()
                analysis = (row.get("analysis") or "").strip()
                if not real_img or not ai_img:
                    print(
                        f"Skipping row {pk}: real_img/ai_img must not be empty.",
                        file=sys.stderr,
                    )
                    continue
                rows.append((pk, real_img, ai_img, analysis))
    except UnicodeDecodeError as exc:
        print(
            f"Failed to decode CSV. Consider using --encoding gbk. Details: {exc}",
            file=sys.stderr,
        )
        return 2
    except Exception as exc:
        print(f"Failed to read CSV: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(f"Dry-run: parsed {len(rows)} rows.")
        return 0

    try:
        conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset=charset,
            autocommit=False,
        )
    except Exception as exc:
        print(f"Failed to connect to MySQL: {exc}", file=sys.stderr)
        return 3

    try:
        with conn.cursor() as cursor:
            if args.truncate:
                cursor.execute(f"DELETE FROM `{table}`")

            if rows:
                sql = (
                    f"INSERT INTO `{table}` (id, real_img, ai_img, analysis) "
                    f"VALUES (%s, %s, %s, %s) "
                    f"ON DUPLICATE KEY UPDATE "
                    f"real_img = VALUES(real_img), "
                    f"ai_img = VALUES(ai_img), "
                    f"analysis = VALUES(analysis)"
                )
                batch = max(1, args.batch_size)
                for i in range(0, len(rows), batch):
                    cursor.executemany(sql, rows[i : i + batch])
        conn.commit()
    except Exception as exc:
        conn.rollback()
        print(f"Import failed and was rolled back: {exc}", file=sys.stderr)
        return 4
    finally:
        conn.close()

    print(f"Imported or updated {len(rows)} rows into `{table}`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
