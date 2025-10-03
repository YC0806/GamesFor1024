#!/usr/bin/env python3
"""
Standalone CSV → MySQL importer for Risk Hunter scenarios.

Inserts rows into a target table (default: riskhunter_riskscenario) with columns:
  - title (str)
  - content (str)
  - risk_label (bool → stored as tinyint 1/0)
  - analysis (str)

Database URL can be provided via --database-url or read from .env (DATABASE_URL=...).
This script does NOT import Django or depend on the Django project.
"""

import argparse
import csv
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

try:
    import pymysql
except Exception as exc:  # pragma: no cover
    print("PyMySQL is required. Try: pip install PyMySQL", file=sys.stderr)
    raise


TITLE_KEYS = ["title", "标题", "场景", "题目", "问题"]
CONTENT_KEYS = ["content", "文本", "内容", "题干", "生成内容", "答案"]
ANALYSIS_KEYS = ["analysis", "解析", "答案解析", "说明", "点评"]
LABEL_KEYS = ["risk_label", "label", "标签", "是否通过", "判定", "正确答案", "结论"]


def _first_nonempty(d: dict, keys: Iterable[str]) -> Optional[str]:
    for k in keys:
        if k in d and d[k] is not None:
            v = str(d[k]).strip()
            if v != "":
                return v
    return None


def _label_to_bool(value: str) -> bool:
    v = (value or "").strip().lower()
    if v in {"1", "true", "t", "yes", "y"}:
        return True
    if v in {"0", "false", "f", "no", "n"}:
        return False
    return True


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
    """Return (host, port, user, password, database, charset)."""
    parsed = urlparse(url)
    if parsed.scheme not in {"mysql", "mariadb"}:
        raise ValueError("Only mysql:// or mariadb:// URLs are supported by this tool.")

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


def main() -> int:
    base_dir = Path(__file__).resolve().parent

    parser = argparse.ArgumentParser(description="Import Risk Hunter CSV into MySQL table.")
    parser.add_argument("csv_path", help="Path to CSV file")
    parser.add_argument("--database-url", dest="database_url", help="MySQL DSN, e.g. mysql://user:pass@host:3306/dbname")
    parser.add_argument("--table", default="riskhunter_riskscenario", help="Target table name (default: riskhunter_riskscenario)")
    parser.add_argument("--encoding", default="utf-8-sig", help="CSV encoding (default: utf-8-sig; try gbk if needed)")
    parser.add_argument("--delimiter", default=",", help="CSV delimiter (default: ,)")
    parser.add_argument("--truncate", action="store_true", help="Delete all existing rows before import")
    parser.add_argument("--batch-size", type=int, default=500, help="Batch size for executemany (default: 500)")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, do not write to DB")

    args = parser.parse_args()

    csv_path = Path(args.csv_path).expanduser()
    if not csv_path.exists():
        print(f"CSV file not found: {csv_path}", file=sys.stderr)
        return 2

    database_url = args.database_url or _read_env_database_url(base_dir)
    if not database_url:
        print("DATABASE_URL not provided and .env not found/invalid.", file=sys.stderr)
        return 2

    try:
        host, port, user, password, database, charset = _parse_mysql_url(database_url)
    except Exception as e:
        print(f"Invalid DATABASE_URL: {e}", file=sys.stderr)
        return 2

    table = _sanitize_table_name(args.table)

    # Read CSV
    try:
        with csv_path.open("r", encoding=args.encoding, newline="") as f:
            reader = csv.DictReader(f, delimiter=args.delimiter)
            if not reader.fieldnames:
                print("CSV appears to have no header row.", file=sys.stderr)
                return 2

            to_insert: List[Tuple[str, str, int, str]] = []
            total = 0
            for row in reader:
                print(row)
                total += 1
                title = _first_nonempty(row, TITLE_KEYS)
                content = _first_nonempty(row, CONTENT_KEYS)
                analysis = _first_nonempty(row, ANALYSIS_KEYS)
                label_raw = _first_nonempty(row, LABEL_KEYS)
                print(title, content, analysis, label_raw)
                if not title or not content or not analysis or label_raw is None:
                    print(f"Skipping row {total}: missing required fields (title/content/analysis/risk_label).", file=sys.stderr)
                    continue

                risk_bool = _label_to_bool(label_raw)
                to_insert.append((title, content, 1 if risk_bool else 0, analysis))
    except UnicodeDecodeError as e:
        print(f"Failed to decode CSV. Try --encoding gbk. Details: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Failed to read CSV: {e}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(f"Dry-run: parsed {len(to_insert)} valid rows.")
        return 0

    # Connect and import
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
    except Exception as e:
        print(f"Failed to connect to MySQL: {e}", file=sys.stderr)
        return 3

    try:
        with conn.cursor() as cur:
            if args.truncate:
                # Use DELETE for broader compatibility with permissions and FKs
                cur.execute(f"DELETE FROM `{table}`")

            if to_insert:
                sql = f"INSERT INTO `{table}` (title, content, risk_label, analysis) VALUES (%s, %s, %s, %s)"
                batch = args.batch_size
                for i in range(0, len(to_insert), batch):
                    cur.executemany(sql, to_insert[i : i + batch])
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Import failed and was rolled back: {e}", file=sys.stderr)
        return 4
    finally:
        conn.close()

    print(f"Imported {len(to_insert)} rows into `{table}`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

