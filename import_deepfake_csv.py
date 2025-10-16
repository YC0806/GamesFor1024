#!/usr/bin/env python3
"""
Standalone loader for the Deepfake datasets.

Supports two CSV layouts:
- Pair questions (`id, real_img, ai_img, analysis`) -> `deepfake_deepfakepair`
- Selection challenges (`id, img_path, ai_generated, analysis`) -> `deepfake_deepfakeselection`

The script is intentionally lightweight and does not import Django; it connects
directly via PyMySQL using a DATABASE_URL provided either as a CLI argument or read
from the project's .env file.
"""

import argparse
import csv
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

try:
    import pymysql
except Exception as exc:  # pragma: no cover
    print("PyMySQL is required. Install via `pip install PyMySQL`.", file=sys.stderr)
    raise


RowBuilder = Callable[[Dict[str, str]], Optional[Tuple[Any, ...]]]


def _parse_bool(value: str) -> Optional[bool]:
    text = (value or "").strip().lower()
    if text in {"1", "true", "t", "yes", "y"}:
        return True
    if text in {"0", "false", "f", "no", "n"}:
        return False
    return None


def _build_pairs_row(row: Dict[str, str]) -> Optional[Tuple[int, str, str, str]]:
    try:
        pk = int(row["id"])
    except (TypeError, ValueError):
        print(f"Skipping row with invalid id: {row}", file=sys.stderr)
        return None

    real_img = (row.get("real_img") or "").strip()
    ai_img = (row.get("ai_img") or "").strip()
    analysis = (row.get("analysis") or "").strip()

    if not real_img or not ai_img:
        print(
            f"Skipping row {pk}: real_img/ai_img must not be empty.",
            file=sys.stderr,
        )
        return None

    return pk, real_img, ai_img, analysis


def _build_selection_row(row: Dict[str, str]) -> Optional[Tuple[int, str, bool, str]]:
    try:
        pk = int(row["id"])
    except (TypeError, ValueError):
        print(f"Skipping row with invalid id: {row}", file=sys.stderr)
        return None

    img_path = (row.get("img_path") or "").strip()
    if not img_path:
        print(f"Skipping row {pk}: img_path must not be empty.", file=sys.stderr)
        return None

    flag = _parse_bool(row.get("ai_generated", ""))
    if flag is None:
        print(
            f"Skipping row {pk}: ai_generated must be true/false.",
            file=sys.stderr,
        )
        return None

    analysis = (row.get("analysis") or "").strip()
    return pk, img_path, flag, analysis


DATASET_CONFIGS: Dict[str, Dict[str, Any]] = {
    "pairs": {
        "expected_headers": ["id", "real_img", "ai_img", "analysis"],
        "default_table": "deepfake_deepfakepair",
        "default_csv": "Resources/deepfake/deepfake_data.csv",
        "columns": ["id", "real_img", "ai_img", "analysis"],
        "row_builder": _build_pairs_row,
    },
    "selection": {
        "expected_headers": ["id", "img_path", "ai_generated", "analysis"],
        "default_table": "deepfake_deepfakeselection",
        "default_csv": "Resources/deepfake/deepfake_data_select.csv",
        "columns": ["id", "img_path", "ai_generated", "analysis"],
        "row_builder": _build_selection_row,
    },
}


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


def _validate_headers(fieldnames: List[str], expected_headers: List[str]) -> None:
    normalized = [f.strip() for f in fieldnames]
    if normalized != expected_headers:
        raise ValueError(
            f"CSV header must exactly match {expected_headers}, got {normalized}."
        )


def main() -> int:
    base_dir = Path(__file__).resolve().parent

    parser = argparse.ArgumentParser(
        description="Import Deepfake CSV data into the database."
    )
    parser.add_argument(
        "--dataset",
        choices=sorted(DATASET_CONFIGS),
        default="pairs",
        help="Dataset type to import: 'pairs' (real vs AI) or 'selection' (2 real + 1 AI).",
    )
    parser.add_argument(
        "--csv-path",
        help="Path to CSV file (default depends on dataset).",
    )
    parser.add_argument(
        "--database-url",
        dest="database_url",
        help="MySQL/MariaDB URL, e.g. mysql://user:pass@host:3306/dbname",
    )
    parser.add_argument(
        "--table",
        help="Target table name (default depends on dataset).",
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

    config = DATASET_CONFIGS[args.dataset]
    csv_path_str = args.csv_path or config["default_csv"]
    csv_path = Path(csv_path_str).expanduser()
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

    table_name = args.table or config["default_table"]
    table = _sanitize_table_name(table_name)
    expected_headers = config["expected_headers"]
    columns: List[str] = config["columns"]
    row_builder: RowBuilder = config["row_builder"]

    try:
        with csv_path.open("r", encoding=args.encoding, newline="") as handle:
            reader = csv.DictReader(handle, delimiter=args.delimiter)
            if not reader.fieldnames:
                print("CSV header row is missing.", file=sys.stderr)
                return 2
            _validate_headers(reader.fieldnames, expected_headers)

            rows: List[Tuple[Any, ...]] = []
            for row in reader:
                parsed_row = row_builder(row)
                if parsed_row is not None:
                    rows.append(parsed_row)
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
                column_list = ", ".join(columns)
                placeholders = ", ".join(["%s"] * len(columns))
                update_columns = [col for col in columns if col != "id"]
                update_clause = ", ".join(
                    f"{col} = VALUES({col})" for col in update_columns
                )
                sql = (
                    f"INSERT INTO `{table}` ({column_list}) "
                    f"VALUES ({placeholders}) "
                    f"ON DUPLICATE KEY UPDATE {update_clause}"
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
