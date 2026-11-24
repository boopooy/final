import json
import sqlite3
import tempfile
import unittest
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from final import core


class CoreTests(unittest.TestCase):
    def test_existing_sqlite_income_records_gain_a_default_category(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.sqlite3"
            with sqlite3.connect(path) as connection:
                connection.execute(
                    """
                    CREATE TABLE income_records (
                        id TEXT PRIMARY KEY,
                        date TEXT NOT NULL,
                        item TEXT NOT NULL,
                        amount INTEGER NOT NULL,
                        memo TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO income_records (id, date, item, amount, memo)
                    VALUES ('existing', '2026-11-01', '급여', 1000000, '')
                    """
                )

            data = core.load_data(path)
            self.assertEqual(data["income_records"][0]["id"], "existing")
            self.assertEqual(data["income_records"][0]["category"], "기타")

    def test_sqlite_round_trip_and_idempotent_saves(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "data.sqlite3"
            data = core.load_data(path)
            data["categories"].append("반려동물")
            data["expenses"].append(
                {
                    "id": "expense-1",
                    "date": date.today().isoformat(),
                    "place": "동물병원",
                    "amount": 25000,
                    "category": "반려동물",
                    "payment_method": "체크카드",
                    "purpose": "필수 지출",
                    "behavior": "계획 소비",
                    "memo": "정기 진료",
                }
            )
            data["income_records"].append(
                {
                    "id": "income-1",
                    "date": date.today().isoformat(),
                    "item": "급여",
                    "amount": 3_000_000,
                    "category": "급여",
                    "memo": "11월 급여",
                }
            )
            data["budgets"]["2026-11"] = {
                "total": 1_000_000,
                "categories": {"반려동물": 50000},
            }
            data["savings_goal"].update(
                {"name": "여행", "target": 1_000_000, "saved": 300_000}
            )

            core.save_data(data, path)
            core.save_data(data, path)
            loaded = core.load_data(path)

            self.assertEqual(len(loaded["expenses"]), 1)
            self.assertEqual(loaded["expenses"][0]["memo"], "정기 진료")
            self.assertEqual(len(loaded["income_records"]), 1)
            self.assertEqual(loaded["income_records"][0]["category"], "급여")
            self.assertEqual(loaded["incomes"]["2026-11"], 3_000_000)
            self.assertIn("반려동물", loaded["categories"])
            self.assertEqual(loaded["budgets"]["2026-11"]["total"], 1_000_000)
            self.assertEqual(loaded["savings_goal"]["name"], "여행")

    def test_concurrent_additions_merge_and_explicit_deletion_persists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.sqlite3"
            original = core.load_data(path)
            first = deepcopy(original)
            second = deepcopy(original)
            first["expenses"].append(self.expense("first"))
            second["income_records"].append(self.income("second"))

            core.save_data(first, path, original)
            core.save_data(second, path, original)
            merged = core.load_data(path)
            self.assertEqual(len(merged["expenses"]), 1)
            self.assertEqual(len(merged["income_records"]), 1)

            without_expense = deepcopy(merged)
            without_expense["expenses"] = []
            core.save_data(without_expense, path, merged)
            self.assertEqual(core.load_data(path)["expenses"], [])

    def test_deleting_a_category_keeps_expense_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.sqlite3"
            original = core.load_data(path)
            original["categories"].append("취미")
            original["expenses"].append(
                {
                    **self.expense("hobby-expense"),
                    "category": "취미",
                }
            )
            core.save_data(original, path)

            updated = deepcopy(core.load_data(path))
            updated["categories"].remove("취미")
            core.save_data(updated, path, original)
            restored = core.load_data(path)

            self.assertNotIn("취미", restored["categories"])
            self.assertEqual(restored["expenses"][0]["category"], "취미")

    def test_legacy_json_is_migrated_once_without_losing_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            database = directory_path / "finance_data.sqlite3"
            legacy = directory_path / "finance_data.json"
            legacy.write_text(
                json.dumps(
                    {
                        "expenses": [self.expense("legacy-expense")],
                        "incomes": {"2026-11": 2_500_000},
                        "budgets": {"2026-11": {"total": 900_000, "categories": {}}},
                        "savings_goal": {"target": 1_000_000, "months": 5, "saved": 200_000},
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(core, "DATABASE_FILE", database), patch.object(
                core, "LEGACY_DATA_FILE", legacy
            ):
                initial = core.load_data(database)
                self.assertEqual(len(initial["expenses"]), 1)
                self.assertEqual(initial["incomes"]["2026-11"], 2_500_000)
                self.assertEqual(initial["budgets"]["2026-11"]["total"], 900_000)

                initial["income_records"].append(self.income("new-income"))
                core.save_data(initial, database)
                restored = core.load_data(database)

            self.assertEqual(len(restored["expenses"]), 1)
            self.assertEqual(len(restored["income_records"]), 2)

    def test_behavior_summary_uses_spending_amounts(self) -> None:
        summary = core.behavior_summary(
            [
                {"amount": 20_000, "behavior": "충동 소비", "purpose": "선택 지출"},
                {"amount": 50_000, "behavior": "계획 소비", "purpose": "필수 지출"},
                {"amount": 30_000, "behavior": "계획 소비", "purpose": "필수 지출"},
            ]
        )

        self.assertEqual(summary["type"], "계획적인 소비형")
        self.assertEqual(summary["impulsive_ratio"], 0.2)
        self.assertEqual(summary["necessary_ratio"], 0.8)

    def test_consumption_diagnosis_reports_insufficient_data(self) -> None:
        summary = core.behavior_summary(
            [
                {"amount": 20_000, "behavior": "충동 소비", "purpose": "선택 지출"},
                {"amount": 30_000, "behavior": "계획 소비", "purpose": "필수 지출"},
            ]
        )
        self.assertEqual(summary["type"], "데이터 부족")
        self.assertEqual(summary["total"], 50_000)

    def test_period_comparison_daily_averages_and_grouping_match_totals(self) -> None:
        start = date(2026, 11, 1)
        end = date(2026, 11, 7)
        expenses = [
            {**self.expense("a"), "date": "2026-11-02", "amount": 10_000},
            {**self.expense("b"), "date": "2026-11-09", "amount": 15_000},
            {**self.expense("c"), "date": "2026-11-07", "amount": 5_000},
        ]

        period = core.period_summary(expenses, start, end)
        weekday = core.weekday_averages(expenses, start, end)
        grouped = core.grouped_spending(expenses, start, end, "일별", "기간 A")
        comparison = core.category_comparison(
            [expenses[0]], [{**expenses[0], "amount": 4_000}]
        )

        self.assertEqual(period["total"], 15_000)
        self.assertEqual(period["days"], 7)
        self.assertEqual(period["daily_average"], 15_000 / 7)
        self.assertEqual(len(grouped), 7)
        self.assertEqual(sum(row["amount"] for row in grouped), period["total"])
        self.assertEqual(weekday[0]["average"], 10_000)
        self.assertEqual(comparison[0]["difference"], 6_000)
        self.assertEqual(comparison[0]["rate"], 1.5)

    def test_budget_and_behavior_ratios_drive_the_diagnosis(self) -> None:
        expenses = [
            {"amount": 10_000, "behavior": "계획 소비", "purpose": "필수 지출"},
            {"amount": 10_000, "behavior": "계획 소비", "purpose": "필수 지출"},
            {"amount": 10_000, "behavior": "계획 소비", "purpose": "선택 지출"},
        ]
        summary = core.behavior_summary(expenses, budget_limit=100_000)
        self.assertEqual(summary["type"], "절약 중심형")
        self.assertEqual(summary["total"], 30_000)
        self.assertEqual(summary["planned_ratio"], 1)

    def test_expense_and_income_validation_reject_invalid_values(self) -> None:
        with self.assertRaises(ValueError):
            core.validate_expense(
                expense_date=date.today() + timedelta(days=1),
                place="식당",
                amount=1000,
                category="식비",
                payment_method="현금",
            )
        with self.assertRaises(ValueError):
            core.validate_income(income_date=date.today(), item="  ", amount=0)
        with self.assertRaises(ValueError):
            core.validate_income(
                income_date=date.today(),
                item="급여",
                amount=1000,
                category="없는 카테고리",
                categories=["급여", "기타"],
            )

    def test_category_names_are_unique_case_insensitively(self) -> None:
        with self.assertRaises(ValueError):
            core.validate_category_name(" 식비 ", ["식비", "카페"])
        self.assertEqual(
            core.validate_category_name(" 식사 ", ["식비", "카페"]),
            "식사",
        )

    @staticmethod
    def expense(record_id: str) -> dict[str, object]:
        return {
            "id": record_id,
            "date": date.today().isoformat(),
            "place": "식당",
            "amount": 1000,
            "category": "식비",
            "payment_method": "현금",
            "purpose": "필수 지출",
            "behavior": "계획 소비",
            "memo": "",
        }

    @staticmethod
    def income(record_id: str) -> dict[str, object]:
        return {
            "id": record_id,
            "date": date.today().isoformat(),
            "item": "급여",
            "amount": 3_000_000,
            "memo": "",
        }


if __name__ == "__main__":
    unittest.main()
