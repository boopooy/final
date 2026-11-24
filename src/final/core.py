from __future__ import annotations

import json
import sqlite3
import uuid
from copy import deepcopy
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from typing import Any


DEFAULT_CATEGORIES = ["식비", "카페", "쇼핑", "교통", "여가", "생활용품", "의료", "기타"]
CATEGORIES = DEFAULT_CATEGORIES
PAYMENT_METHODS = ["신용카드", "체크카드", "현금", "간편결제", "계좌이체", "기타"]
DATA_DIRECTORY = Path(__file__).resolve().parents[2] / "data"
DATABASE_FILE = DATA_DIRECTORY / "finance_data.sqlite3"
LEGACY_DATA_FILE = DATA_DIRECTORY / "finance_data.json"
DATA_FILE = DATABASE_FILE
DEFAULT_DATA: dict[str, Any] = {
    "expenses": [],
    "income_records": [],
    "incomes": {},
    "categories": DEFAULT_CATEGORIES.copy(),
    "budgets": {},
    "savings_goal": {
        "name": "",
        "target": 0,
        "months": 12,
        "saved": 0,
        "start_date": date.today().isoformat(),
    },
}


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _initialize(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS expenses (
            id TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            place TEXT NOT NULL,
            amount INTEGER NOT NULL CHECK (amount > 0),
            category TEXT NOT NULL,
            payment_method TEXT NOT NULL,
            purpose TEXT NOT NULL,
            behavior TEXT NOT NULL,
            memo TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS income_records (
            id TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            item TEXT NOT NULL,
            amount INTEGER NOT NULL CHECK (amount > 0),
            memo TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS categories (
            name TEXT PRIMARY KEY COLLATE NOCASE,
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS budgets (
            month TEXT PRIMARY KEY,
            total INTEGER NOT NULL DEFAULT 0,
            categories TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS savings_goal (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            name TEXT NOT NULL DEFAULT '',
            target INTEGER NOT NULL DEFAULT 0,
            months INTEGER NOT NULL DEFAULT 12,
            saved INTEGER NOT NULL DEFAULT 0,
            start_date TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS active_category_names
            ON categories(name COLLATE NOCASE) WHERE active = 1;
        """
    )
    connection.executemany(
        "INSERT OR IGNORE INTO categories(name, active) VALUES (?, 1)",
        ((name,) for name in DEFAULT_CATEGORIES),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO savings_goal(singleton, name, target, months, saved, start_date)
        VALUES (1, '', 0, 12, 0, ?)
        """,
        (date.today().isoformat(),),
    )
    income_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(income_records)")
    }
    if "category" not in income_columns:
        connection.execute(
            "ALTER TABLE income_records ADD COLUMN category TEXT NOT NULL DEFAULT '기타'"
        )
    connection.commit()


def _migrate_legacy_json(connection: sqlite3.Connection, path: Path) -> None:
    if path != DATABASE_FILE or not LEGACY_DATA_FILE.exists():
        return
    migrated = connection.execute(
        "SELECT value FROM metadata WHERE key = 'legacy_json_migrated'"
    ).fetchone()
    if migrated:
        return
    try:
        legacy = json.loads(LEGACY_DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"기존 JSON 데이터를 읽을 수 없습니다: {LEGACY_DATA_FILE}") from error
    if not isinstance(legacy, dict):
        raise ValueError("기존 JSON 데이터 형식이 올바르지 않습니다.")

    with connection:
        for index, expense in enumerate(legacy.get("expenses", [])):
            if not isinstance(expense, dict):
                continue
            expense_date = str(expense.get("date", ""))
            if len(expense_date) < 10:
                continue
            connection.execute(
                """
                INSERT OR IGNORE INTO expenses
                    (id, date, place, amount, category, payment_method, purpose, behavior, memo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(expense.get("id") or f"legacy-expense-{index}"),
                    expense_date[:10],
                    str(expense.get("place", "")),
                    int(expense.get("amount", 0)),
                    str(expense.get("category", "기타")),
                    str(expense.get("payment_method", "기타")),
                    str(expense.get("purpose", "필수 지출")),
                    str(expense.get("behavior", "계획 소비")),
                    str(expense.get("memo", "")),
                ),
            )
        for month, amount in legacy.get("incomes", {}).items():
            try:
                income_date = f"{month}-01"
                date.fromisoformat(income_date)
                value = int(amount)
            except (TypeError, ValueError):
                continue
            if value > 0:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO income_records(id, date, item, amount, memo)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        f"legacy-income-{month}",
                        income_date,
                        "기존 월간 수입",
                        value,
                        "기존 소비 관리 앱에서 가져온 월간 합계",
                    ),
                )
        for month, budget in legacy.get("budgets", {}).items():
            if not isinstance(budget, dict):
                continue
            connection.execute(
                """
                INSERT OR IGNORE INTO budgets(month, total, categories)
                VALUES (?, ?, ?)
                """,
                (
                    str(month),
                    max(0, int(budget.get("total", 0))),
                    json.dumps(budget.get("categories", {}), ensure_ascii=False),
                ),
            )
        savings_goal = legacy.get("savings_goal", {})
        if isinstance(savings_goal, dict):
            connection.execute(
                """
                UPDATE savings_goal
                SET name = ?, target = ?, months = ?, saved = ?, start_date = ?
                WHERE singleton = 1
                """,
                (
                    str(savings_goal.get("name", "")),
                    max(0, int(savings_goal.get("target", 0))),
                    max(1, int(savings_goal.get("months", 12))),
                    max(0, int(savings_goal.get("saved", 0))),
                    str(savings_goal.get("start_date", date.today().isoformat())),
                ),
            )
        connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES ('legacy_json_migrated', '1')"
        )


def load_data(path: Path = DATABASE_FILE) -> dict[str, Any]:
    connection = _connect(path)
    try:
        with connection:
            _initialize(connection)
            _migrate_legacy_json(connection, path)
            expenses = [
                dict(row)
                for row in connection.execute("SELECT * FROM expenses ORDER BY date, rowid")
            ]
            income_records = [
                dict(row)
                for row in connection.execute("SELECT * FROM income_records ORDER BY date, rowid")
            ]
            categories = [
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM categories WHERE active = 1 ORDER BY rowid"
                )
            ]
            budgets = {
                row["month"]: {
                    "total": int(row["total"]),
                    "categories": json.loads(row["categories"]),
                }
                for row in connection.execute("SELECT * FROM budgets")
            }
            goal_row = connection.execute(
                "SELECT name, target, months, saved, start_date FROM savings_goal WHERE singleton = 1"
            ).fetchone()
    except (sqlite3.Error, OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        if isinstance(error, ValueError) and str(error).startswith("기존"):
            raise
        raise ValueError(f"SQLite 저장 데이터를 읽을 수 없습니다: {path}") from error
    finally:
        connection.close()

    incomes: dict[str, int] = {}
    for record in income_records:
        month = record["date"][:7]
        incomes[month] = incomes.get(month, 0) + int(record["amount"])

    data = deepcopy(DEFAULT_DATA)
    data.update(
        {
            "expenses": expenses,
            "income_records": income_records,
            "incomes": incomes,
            "categories": categories,
            "budgets": budgets,
            "savings_goal": dict(goal_row) if goal_row else deepcopy(DEFAULT_DATA["savings_goal"]),
        }
    )
    return data


def save_data(
    data: dict[str, Any],
    path: Path = DATABASE_FILE,
    previous_data: dict[str, Any] | None = None,
) -> None:
    previous_expenses = {
        item["id"]: item for item in (previous_data or {}).get("expenses", [])
    }
    expenses_to_write = [
        {"memo": "", **item}
        for item in data.get("expenses", [])
        if item["id"] not in previous_expenses
        or {"memo": "", **item} != {"memo": "", **previous_expenses[item["id"]]}
    ]
    previous_income_records = {
        item["id"]: {"category": "기타", **item}
        for item in (previous_data or {}).get("income_records", [])
    }
    income_records_to_write = [
        {"category": "기타", **item}
        for item in data.get("income_records", [])
        if item["id"] not in previous_income_records
        or {"category": "기타", **item} != previous_income_records[item["id"]]
    ]
    try:
        with closing(_connect(path)) as connection:
            _initialize(connection)
            _migrate_legacy_json(connection, path)
            with connection:
                connection.executemany(
                    """
                    INSERT INTO expenses
                        (id, date, place, amount, category, payment_method, purpose, behavior, memo)
                    VALUES (:id, :date, :place, :amount, :category, :payment_method, :purpose, :behavior, :memo)
                    ON CONFLICT(id) DO UPDATE SET
                        date=excluded.date, place=excluded.place, amount=excluded.amount,
                        category=excluded.category, payment_method=excluded.payment_method,
                        purpose=excluded.purpose, behavior=excluded.behavior, memo=excluded.memo
                    """,
                    expenses_to_write,
                )
                connection.executemany(
                    """
                    INSERT INTO income_records(id, date, item, amount, memo, category)
                    VALUES (:id, :date, :item, :amount, :memo, :category)
                    ON CONFLICT(id) DO UPDATE SET
                        date=excluded.date, item=excluded.item,
                        amount=excluded.amount, memo=excluded.memo,
                        category=excluded.category
                    """,
                    income_records_to_write,
                )
                if previous_data is not None:
                    old_expense_ids = {
                        item["id"] for item in previous_data.get("expenses", [])
                    }
                    new_expense_ids = {
                        item["id"] for item in data.get("expenses", [])
                    }
                    connection.executemany(
                        "DELETE FROM expenses WHERE id = ?",
                        ((item_id,) for item_id in old_expense_ids - new_expense_ids),
                    )
                    old_income_ids = {
                        item["id"] for item in previous_data.get("income_records", [])
                    }
                    new_income_ids = {
                        item["id"] for item in data.get("income_records", [])
                    }
                    connection.executemany(
                        "DELETE FROM income_records WHERE id = ?",
                        ((item_id,) for item_id in old_income_ids - new_income_ids),
                    )

                active_categories = list(dict.fromkeys(data.get("categories", DEFAULT_CATEGORIES)))
                if previous_data is None:
                    old_categories = {
                        row["name"]
                        for row in connection.execute(
                            "SELECT name FROM categories WHERE active = 1"
                        )
                    }
                else:
                    old_categories = set(previous_data.get("categories", active_categories))
                new_categories = set(active_categories)
                connection.executemany(
                    "UPDATE categories SET active = 0 WHERE name = ? COLLATE NOCASE",
                    ((name,) for name in old_categories - new_categories),
                )
                connection.executemany(
                    """
                    INSERT INTO categories(name, active) VALUES (?, 1)
                    ON CONFLICT(name) DO UPDATE SET active = 1
                    """,
                    ((name,) for name in new_categories - old_categories),
                )
                previous_budgets = (previous_data or {}).get("budgets", {})
                connection.executemany(
                    """
                    INSERT INTO budgets(month, total, categories) VALUES (?, ?, ?)
                    ON CONFLICT(month) DO UPDATE SET
                        total=excluded.total, categories=excluded.categories
                    """,
                    (
                        (
                            month,
                            int(budget.get("total", 0)),
                            json.dumps(budget.get("categories", {}), ensure_ascii=False),
                        )
                        for month, budget in data.get("budgets", {}).items()
                        if month not in previous_budgets or budget != previous_budgets[month]
                    ),
                )
                goal = {**DEFAULT_DATA["savings_goal"], **data.get("savings_goal", {})}
                previous_goal = (previous_data or {}).get("savings_goal")
                if previous_goal is None or goal != {
                    **DEFAULT_DATA["savings_goal"],
                    **previous_goal,
                }:
                    connection.execute(
                        """
                        INSERT INTO savings_goal(singleton, name, target, months, saved, start_date)
                        VALUES (1, :name, :target, :months, :saved, :start_date)
                        ON CONFLICT(singleton) DO UPDATE SET
                            name=excluded.name, target=excluded.target,
                            months=excluded.months, saved=excluded.saved,
                            start_date=excluded.start_date
                        """,
                        goal,
                    )
    except (sqlite3.Error, OSError, TypeError, ValueError) as error:
        raise ValueError(f"SQLite 데이터 저장에 실패했습니다: {path}") from error


def month_key(value: date) -> str:
    return value.strftime("%Y-%m")


def month_expenses(data: dict[str, Any], month: str) -> list[dict[str, Any]]:
    return [
        expense
        for expense in data["expenses"]
        if str(expense.get("date", "")).startswith(month)
    ]


def month_income_records(data: dict[str, Any], month: str) -> list[dict[str, Any]]:
    return [
        record
        for record in data.get("income_records", [])
        if str(record.get("date", "")).startswith(month)
    ]


def total_income(data: dict[str, Any], month: str) -> int:
    return sum(int(item["amount"]) for item in month_income_records(data, month))


def total_expense(expenses: list[dict[str, Any]]) -> int:
    return sum(int(expense["amount"]) for expense in expenses)


def category_totals(expenses: list[dict[str, Any]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for expense in expenses:
        category = str(expense.get("category", "기타"))
        totals[category] = totals.get(category, 0) + int(expense["amount"])
    return totals


def expenses_between(
    expenses: list[dict[str, Any]], start: date, end: date
) -> list[dict[str, Any]]:
    if end < start:
        raise ValueError("기간 종료일은 시작일보다 빠를 수 없습니다.")
    start_text = start.isoformat()
    end_text = end.isoformat()
    return [
        item
        for item in expenses
        if start_text <= str(item.get("date", ""))[:10] <= end_text
    ]


def period_summary(
    expenses: list[dict[str, Any]], start: date, end: date
) -> dict[str, int | float]:
    records = expenses_between(expenses, start, end)
    days = (end - start).days + 1
    total = total_expense(records)
    return {
        "total": total,
        "days": days,
        "daily_average": total / days,
        "count": len(records),
    }


def compare_amounts(current: int | float, previous: int | float) -> dict[str, int | float | None]:
    difference = current - previous
    return {
        "difference": difference,
        "rate": difference / previous if previous else None,
    }


def category_comparison(
    current_expenses: list[dict[str, Any]],
    previous_expenses: list[dict[str, Any]],
) -> list[dict[str, int | float | str | None]]:
    current = category_totals(current_expenses)
    previous = category_totals(previous_expenses)
    rows = []
    for category in sorted(set(current) | set(previous)):
        current_amount = current.get(category, 0)
        previous_amount = previous.get(category, 0)
        change = compare_amounts(current_amount, previous_amount)
        rows.append(
            {
                "category": category,
                "current": current_amount,
                "previous": previous_amount,
                "difference": change["difference"],
                "rate": change["rate"],
            }
        )
    return sorted(rows, key=lambda row: abs(int(row["difference"])), reverse=True)


def weekday_averages(
    expenses: list[dict[str, Any]], start: date, end: date
) -> list[dict[str, str | int | float]]:
    if end < start:
        raise ValueError("기간 종료일은 시작일보다 빠를 수 없습니다.")
    names = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
    totals = [0] * 7
    occurrences = [0] * 7
    day = start
    while day <= end:
        occurrences[day.weekday()] += 1
        day += timedelta(days=1)
    for item in expenses_between(expenses, start, end):
        weekday = date.fromisoformat(str(item["date"])[:10]).weekday()
        totals[weekday] += int(item["amount"])
    return [
        {
            "weekday": names[index],
            "total": totals[index],
            "days": occurrences[index],
            "average": totals[index] / occurrences[index] if occurrences[index] else 0,
        }
        for index in range(7)
    ]


def grouped_spending(
    expenses: list[dict[str, Any]],
    start: date,
    end: date,
    granularity: str,
    period_label: str,
) -> list[dict[str, str | int]]:
    if granularity not in {"일별", "주별", "월별"}:
        raise ValueError("집계 단위는 일별, 주별, 월별 중 하나여야 합니다.")
    totals: dict[int, int] = {}
    for item in expenses_between(expenses, start, end):
        expense_date = date.fromisoformat(str(item["date"])[:10])
        if granularity == "일별":
            index = (expense_date - start).days
        elif granularity == "주별":
            index = (expense_date - start).days // 7
        else:
            index = (expense_date.year - start.year) * 12 + expense_date.month - start.month
        totals[index] = totals.get(index, 0) + int(item["amount"])

    suffix = {"일별": "일차", "주별": "주차", "월별": "개월차"}[granularity]
    duration_days = (end - start).days + 1
    if granularity == "일별":
        bucket_count = duration_days
    elif granularity == "주별":
        bucket_count = (duration_days + 6) // 7
    else:
        bucket_count = (end.year - start.year) * 12 + end.month - start.month + 1
    return [
        {
            "period": period_label,
            "interval": f"{index + 1}{suffix}",
            "amount": totals.get(index, 0),
        }
        for index in range(bucket_count)
    ]


def monthly_totals(data: dict[str, Any], months: int = 6) -> list[dict[str, Any]]:
    today = date.today()
    current_index = today.year * 12 + today.month - 1
    results = []
    for offset in range(months - 1, -1, -1):
        index = current_index - offset
        year, month = divmod(index, 12)
        key = f"{year:04d}-{month + 1:02d}"
        results.append({"month": key, "amount": total_expense(month_expenses(data, key))})
    return results


def behavior_summary(
    expenses: list[dict[str, Any]], budget_limit: int | None = None
) -> dict[str, Any]:
    total = total_expense(expenses)
    planned = sum(
        int(item["amount"]) for item in expenses if item.get("behavior") == "계획 소비"
    )
    impulsive = sum(
        int(item["amount"]) for item in expenses if item.get("behavior") == "충동 소비"
    )
    necessary = sum(
        int(item["amount"]) for item in expenses if item.get("purpose") == "필수 지출"
    )
    optional = total - necessary
    planned_ratio = planned / total if total else 0
    impulsive_ratio = impulsive / total if total else 0
    necessary_ratio = necessary / total if total else 0

    if total == 0 or len(expenses) < 3:
        return {
            "total": total,
            "planned_amount": planned,
            "impulsive_amount": impulsive,
            "necessary_amount": necessary,
            "optional_amount": optional,
            "planned_ratio": planned_ratio,
            "impulsive_ratio": impulsive_ratio,
            "necessary_ratio": necessary_ratio,
            "optional_ratio": optional / total if total else 0,
            "type": "데이터 부족",
            "description": (
                f"현재 {len(expenses)}건이 있어요. 소비 성향 진단에는 "
                "최소 3건의 소비 기록이 필요합니다."
            ),
        }

    if impulsive_ratio >= 0.3:
        profile = "충동 소비 주의형"
        description = "충동 소비 비중이 높아요. 구매 전 하루 보류 규칙과 주간 한도를 활용해 보세요."
    elif (
        budget_limit is not None
        and budget_limit > 0
        and total <= budget_limit * 0.8
        and optional / total <= 0.35
    ):
        profile = "절약 중심형"
        description = "예산 사용률과 선택 지출 비중이 낮아요. 현재의 지출 점검 습관을 유지해 보세요."
    elif planned_ratio >= 0.7:
        profile = "계획적인 소비형"
        description = "계획 소비 비중이 높아요. 현재의 예산 점검 습관을 꾸준히 유지해 보세요."
    elif optional / total >= 0.6:
        profile = "선택적 소비형"
        description = "선택 지출 비중이 높아요. 선택 지출 한도를 정해 구매 우선순위를 점검해 보세요."
    elif necessary_ratio >= 0.75:
        profile = "필수 지출 중심형"
        description = "필수 지출 비중이 높아요. 고정 지출을 점검하고 필수 지출 내 절감 여지를 확인해 보세요."
    else:
        profile = "균형 소비형"
        description = "계획과 선택 지출이 균형을 이루고 있어요. 카테고리별 한도를 점검해 보세요."

    return {
        "total": total,
        "planned_amount": planned,
        "impulsive_amount": impulsive,
        "necessary_amount": necessary,
        "optional_amount": optional,
        "planned_ratio": planned_ratio,
        "impulsive_ratio": impulsive_ratio,
        "necessary_ratio": necessary_ratio,
        "optional_ratio": optional / total,
        "type": profile,
        "description": description,
    }


def validate_expense(
    *,
    expense_date: date,
    place: str,
    amount: int,
    category: str,
    payment_method: str,
    categories: list[str] | None = None,
) -> None:
    if not isinstance(expense_date, date):
        raise ValueError("날짜를 올바르게 입력해 주세요.")
    if expense_date > date.today():
        raise ValueError("미래 날짜는 소비 내역으로 등록할 수 없습니다.")
    if not place.strip():
        raise ValueError("사용처를 입력해 주세요.")
    if isinstance(amount, bool) or int(amount) != amount or amount <= 0:
        raise ValueError("금액은 1원 이상의 정수로 입력해 주세요.")
    if category not in (categories or DEFAULT_CATEGORIES):
        raise ValueError("목록에 있는 카테고리를 선택해 주세요.")
    if payment_method not in PAYMENT_METHODS:
        raise ValueError("목록에 있는 결제 수단을 선택해 주세요.")


def validate_income(
    *,
    income_date: date,
    item: str,
    amount: int,
    category: str | None = None,
    categories: list[str] | None = None,
) -> None:
    if not isinstance(income_date, date) or income_date > date.today():
        raise ValueError("오늘까지의 날짜를 올바르게 입력해 주세요.")
    if not item.strip():
        raise ValueError("수입 항목을 입력해 주세요.")
    if isinstance(amount, bool) or int(amount) != amount or amount <= 0:
        raise ValueError("금액은 1원 이상의 정수로 입력해 주세요.")
    if category is not None and category not in (categories or DEFAULT_CATEGORIES):
        raise ValueError("목록에 있는 카테고리를 선택해 주세요.")


def validate_category_name(name: str, categories: list[str], old_name: str | None = None) -> str:
    normalized = name.strip()
    if not normalized:
        raise ValueError("카테고리 이름을 입력해 주세요.")
    if len(normalized) > 30:
        raise ValueError("카테고리 이름은 30자 이내로 입력해 주세요.")
    if any(
        existing.casefold() == normalized.casefold()
        and (old_name is None or existing.casefold() != old_name.casefold())
        for existing in categories
    ):
        raise ValueError("이미 등록된 카테고리 이름입니다.")
    return normalized


def new_id() -> str:
    return uuid.uuid4().hex
