from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import date, timedelta
from math import ceil
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from final.core import (
    DEFAULT_CATEGORIES,
    PAYMENT_METHODS,
    behavior_summary,
    category_comparison,
    category_totals,
    compare_amounts,
    expenses_between,
    grouped_spending,
    load_data,
    month_expenses,
    month_key,
    monthly_totals,
    new_id,
    period_summary,
    save_data,
    total_income,
    total_expense,
    validate_category_name,
    validate_expense,
    validate_income,
    weekday_averages,
)


st.set_page_config(
    page_title="소비 습관 관리",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root { --mint: #12a67a; --ink: #15352d; --muted: #71847e; }
    .stApp { background: #f7faf8; color: var(--ink); }
    [data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid #e8efeb; }
    [data-testid="stMetric"] {
        background: #ffffff; border: 1px solid #e8efeb; border-radius: 16px;
        padding: 18px 20px; box-shadow: 0 4px 16px rgba(22, 56, 45, .04);
    }
    [data-testid="stMetricValue"] { color: #123d31; font-weight: 750; }
    div.stButton > button[kind="primary"], div.stFormSubmitButton > button {
        background: var(--mint); border-color: var(--mint); color: #ffffff;
        border-radius: 10px; font-weight: 650;
    }
    h1, h2, h3 { letter-spacing: -.03em; }
    </style>
    """,
    unsafe_allow_html=True,
)


def won(amount: int | float) -> str:
    value = f"{abs(amount):,.0f}"
    return f"-₩{value}" if amount < 0 else f"₩{value}"


def commit_data(updated: dict[str, Any]) -> None:
    save_data(updated, previous_data=st.session_state["finance_data"])
    st.session_state["finance_data"] = load_data()


def categories_for(data: dict[str, Any]) -> list[str]:
    categories = list(data.get("categories", DEFAULT_CATEGORIES))
    for expense in data["expenses"]:
        old_category = str(expense.get("category", ""))
        if old_category and old_category not in categories:
            categories.append(old_category)
    return categories


def select_month(label: str) -> str:
    today = date.today()
    current_index = today.year * 12 + today.month - 1
    available = set()
    for offset in range(24):
        index = current_index - offset
        year, month = divmod(index, 12)
        available.add(f"{year:04d}-{month + 1:02d}")
    available.update(
        str(item.get("date", ""))[:7]
        for item in st.session_state["finance_data"]["expenses"]
        if len(str(item.get("date", ""))) >= 7
    )
    available.update(
        str(item.get("date", ""))[:7]
        for item in st.session_state["finance_data"].get("income_records", [])
        if len(str(item.get("date", ""))) >= 7
    )
    available.update(st.session_state["finance_data"]["incomes"].keys())
    available.update(st.session_state["finance_data"]["budgets"].keys())
    months = sorted(available, reverse=True)
    return st.selectbox(label, months, key=f"month-{label}")


def current_budget(data: dict[str, Any], month: str) -> dict[str, Any]:
    budget = data["budgets"].get(month, {})
    categories = list(
        dict.fromkeys([*categories_for(data), *budget.get("categories", {})])
    )
    return {
        "total": int(budget.get("total", 0)),
        "categories": {
            category: int(budget.get("categories", {}).get(category, 0)) for category in categories
        },
    }


def show_budget_status(data: dict[str, Any], month: str) -> None:
    budget = current_budget(data, month)
    expenses = month_expenses(data, month)
    spent = total_expense(expenses)
    if budget["total"] <= 0:
        st.info("이 달의 총예산이 아직 설정되지 않았어요. 예산 관리에서 설정해 주세요.")
    else:
        usage = spent / budget["total"]
        st.progress(min(usage, 1.0), text=f"월간 예산 사용률 {usage:.0%}")
        remaining = budget["total"] - spent
        st.metric("남은 월간 예산", won(remaining))
        if usage >= 1:
            st.error(f"예산을 {won(spent - budget['total'])} 초과했어요. 지출을 확인해 주세요.")
        elif usage >= 0.8:
            st.warning("월간 예산의 80% 이상을 사용했어요. 남은 지출을 점검해 보세요.")

    category_spending = category_totals(expenses)
    for category, limit in budget["categories"].items():
        if limit <= 0:
            continue
        usage = category_spending.get(category, 0) / limit
        if usage >= 1:
            st.error(f"{category} 예산을 {won(category_spending[category] - limit)} 초과했어요.")
        elif usage >= 0.8:
            st.warning(f"{category} 예산의 {usage:.0%}를 사용했어요.")


def empty_chart(message: str) -> None:
    st.info(message)


def render_dashboard(data: dict[str, Any]) -> None:
    st.title("안녕하세요, 오늘의 소비를 살펴볼까요? 🌿")
    st.caption("기록을 바탕으로 소비 흐름을 한눈에 확인하고, 더 나은 습관을 만들어 보세요.")
    month = select_month("확인할 월")
    expenses = month_expenses(data, month)
    spent = total_expense(expenses)
    income = total_income(data, month)
    balance = income - spent

    first, second, third, fourth = st.columns(4)
    first.metric("이번 달 수입", won(income))
    second.metric("이번 달 지출", won(spent), delta=f"{len(expenses)}건")
    third.metric("현재 잔액", won(balance), delta_color="normal")
    fourth.metric("평균 소비 금액", won(spent / len(expenses)) if expenses else "₩0")

    if income or spent:
        st.info(
            f"{month}에는 수입 {won(income)} 중 {won(spent)}을 사용해 "
            f"{won(balance)}이 남아 있어요."
        )

    st.subheader("예산 현황")
    show_budget_status(data, month)
    st.divider()
    left, right = st.columns(2)

    with left:
        st.subheader("카테고리별 지출")
        totals = category_totals(expenses)
        if totals:
            figure = px.pie(
                names=list(totals),
                values=list(totals.values()),
                hole=0.62,
                color_discrete_sequence=px.colors.qualitative.Pastel,
            )
            figure.update_layout(
                margin=dict(t=8, b=8, l=8, r=8),
                legend_title_text="카테고리",
                height=330,
            )
            st.plotly_chart(figure, width="stretch")
        else:
            empty_chart("소비 내역을 등록하면 카테고리별 지출을 보여드릴게요.")

    with right:
        st.subheader("최근 6개월 지출 추이")
        trend = pd.DataFrame(monthly_totals(data))
        if not trend.empty:
            figure = px.line(
                trend,
                x="month",
                y="amount",
                markers=True,
                labels={"month": "월", "amount": "지출 (원)"},
            )
            figure.update_traces(line_color="#12a67a", fill="tozeroy", fillcolor="rgba(18,166,122,.10)")
            figure.update_layout(margin=dict(t=8, b=8, l=8, r=8), height=330)
            st.plotly_chart(figure, width="stretch")

    if expenses:
        st.subheader("이번 달 요일별 소비")
        weekday_order = ["월", "화", "수", "목", "금", "토", "일"]
        weekday_data = []
        for item in expenses:
            weekday = date.fromisoformat(item["date"]).weekday()
            weekday_data.append({"요일": weekday_order[weekday], "금액": int(item["amount"])})
        weekday_frame = (
            pd.DataFrame(weekday_data)
            .groupby("요일", as_index=False)["금액"]
            .sum()
            .set_index("요일")
            .reindex(weekday_order, fill_value=0)
            .reset_index()
        )
        figure = px.bar(
            weekday_frame,
            x="요일",
            y="금액",
            color="금액",
            color_continuous_scale=["#c9eee1", "#12a67a"],
            labels={"금액": "지출 (원)"},
        )
        figure.update_layout(showlegend=False, coloraxis_showscale=False, height=280)
        st.plotly_chart(figure, width="stretch")
    else:
        empty_chart("이번 달 소비를 등록하면 요일별 지출을 분석할 수 있어요.")

    st.divider()
    st.subheader("최근 소비 내역")
    recent_expenses = sorted(
        expenses,
        key=lambda item: (item["date"], item.get("id", "")),
        reverse=True,
    )[:5]
    if recent_expenses:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "날짜": item["date"],
                        "사용처": item["place"],
                        "카테고리": item["category"],
                        "금액": int(item["amount"]),
                    }
                    for item in recent_expenses
                ]
            ),
            width="stretch",
            hide_index=True,
            column_config={"금액": st.column_config.NumberColumn(format="₩%d")},
        )
    else:
        st.info("이번 달 소비를 기록하면 최근 내역을 여기에서 확인할 수 있어요.")

def expense_form_fields(
    prefix: str,
    categories: list[str],
    values: dict[str, Any] | None = None,
    selected_category: str | None = None,
    show_category_selector: bool = True,
) -> dict[str, Any]:
    values = values or {}
    first_row = st.columns([1, 2, 1])
    with first_row[0]:
        expense_date = st.date_input(
            "날짜",
            value=values.get("date", date.today()),
            max_value=date.today(),
            key=f"{prefix}-date",
        )
    with first_row[1]:
        place = st.text_input(
            "사용처", value=values.get("place", ""), max_chars=80, key=f"{prefix}-place"
        )
    with first_row[2]:
        amount = st.number_input(
            "금액 (₩)",
            min_value=1,
            value=max(1, int(values.get("amount", 10000))),
            step=1000,
            key=f"{prefix}-amount",
        )
    category = selected_category
    if show_category_selector:
        category_row = st.columns(2)
        with category_row[0]:
            category = st.selectbox(
                "카테고리",
                categories,
                index=categories.index(values["category"])
                if values.get("category") in categories
                else 0,
                key=f"{prefix}-category",
            )
        with category_row[1]:
            payment = st.selectbox(
                "결제 수단",
                PAYMENT_METHODS,
                index=PAYMENT_METHODS.index(values["payment_method"])
                if values.get("payment_method") in PAYMENT_METHODS
                else 0,
                key=f"{prefix}-payment",
            )
    else:
        payment = st.selectbox(
            "결제 수단",
            PAYMENT_METHODS,
            index=PAYMENT_METHODS.index(values["payment_method"])
            if values.get("payment_method") in PAYMENT_METHODS
            else 0,
            key=f"{prefix}-payment",
        )
    behavior_row = st.columns(2)
    with behavior_row[0]:
        purpose = st.radio(
            "지출 구분",
            ["필수 지출", "선택 지출"],
            horizontal=True,
            index=0 if values.get("purpose", "필수 지출") == "필수 지출" else 1,
            key=f"{prefix}-purpose",
        )
    with behavior_row[1]:
        behavior = st.radio(
            "소비 방식",
            ["계획 소비", "충동 소비"],
            horizontal=True,
            index=0 if values.get("behavior", "계획 소비") == "계획 소비" else 1,
            key=f"{prefix}-behavior",
        )
    memo = st.text_input(
        "메모 (선택)", value=values.get("memo", ""), max_chars=200, key=f"{prefix}-memo"
    )
    return {
        "date": expense_date,
        "place": place,
        "memo": memo,
        "amount": amount,
        "category": category,
        "payment_method": payment,
        "purpose": purpose,
        "behavior": behavior,
    }


def render_expenses(data: dict[str, Any]) -> None:
    categories = categories_for(data)
    create_tab, manage_tab = st.tabs(["내역 등록", "내역 조회 · 수정 · 삭제"])

    with create_tab:
        category_options = [*data["categories"], "＋ 새 카테고리 추가"]
        selected_category = st.selectbox(
            "카테고리",
            category_options,
            key="create-category-selection",
        )
        if selected_category == "＋ 새 카테고리 추가":
            new_category = st.text_input(
                "추가할 카테고리 이름",
                max_chars=30,
                key="create-new-category",
            )
            if st.button("카테고리 추가", key="add-category-inline"):
                try:
                    new_category = validate_category_name(new_category, data["categories"])
                except ValueError as error:
                    st.error(str(error))
                else:
                    updated = deepcopy(data)
                    updated["categories"].append(new_category)
                    commit_data(updated)
                    st.success(f"'{new_category}' 카테고리를 추가했어요.")
                    st.rerun()

        with st.form("create-expense", clear_on_submit=True):
            st.subheader("새 소비 등록")
            fields = expense_form_fields(
                "create",
                data["categories"],
                selected_category=(
                    selected_category
                    if selected_category != "＋ 새 카테고리 추가"
                    else None
                ),
                show_category_selector=False,
            )
            submitted = st.form_submit_button("소비 내역 저장", type="primary")
        if submitted:
            if selected_category == "＋ 새 카테고리 추가":
                st.error("먼저 카테고리를 추가하거나 기존 카테고리를 선택해 주세요.")
            else:
                try:
                    validate_expense(
                        expense_date=fields["date"],
                        place=fields["place"],
                        amount=fields["amount"],
                        category=fields["category"],
                        payment_method=fields["payment_method"],
                        categories=data["categories"],
                    )
                except ValueError as error:
                    st.error(str(error))
                else:
                    updated = deepcopy(data)
                    updated["expenses"].append(
                        {
                            "id": uuid.uuid4().hex,
                            **fields,
                            "date": fields["date"].isoformat(),
                            "amount": int(fields["amount"]),
                        }
                    )
                    commit_data(updated)
                    st.success("소비 내역을 저장했어요.")
                    st.rerun()

        with st.expander("카테고리 이름 변경 · 삭제"):
            render_inline_category_management(data)

    with manage_tab:
        records = data["expenses"]
        today = date.today()
        default_start = today.replace(day=1)
        date_range = st.date_input(
            "조회 기간",
            value=(default_start, today),
            max_value=today,
            key="expense-filter-dates",
        )
        filter_columns = st.columns(3)
        with filter_columns[0]:
            category_filter = st.selectbox(
                "카테고리 필터", ["전체", *categories], key="expense-filter-category"
            )
        with filter_columns[1]:
            payment_filter = st.selectbox(
                "결제 수단 필터",
                ["전체", *PAYMENT_METHODS],
                key="expense-filter-payment",
            )
        with filter_columns[2]:
            search_term = st.text_input("사용처 · 메모 검색", key="expense-search").strip().casefold()
        sort_order = st.radio(
            "정렬",
            ["최신순", "오래된순"],
            horizontal=True,
            key="expense-sort-order",
        )
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date, end_date = date_range
        else:
            start_date, end_date = default_start, today
        filtered = [
            item
            for item in records
            if start_date.isoformat() <= item["date"] <= end_date.isoformat()
            and (category_filter == "전체" or item.get("category") == category_filter)
            and (payment_filter == "전체" or item.get("payment_method") == payment_filter)
            and (
                not search_term
                or search_term in item.get("place", "").casefold()
                or search_term in item.get("memo", "").casefold()
            )
        ]
        filtered.sort(
            key=lambda item: (item["date"], item.get("id", "")),
            reverse=sort_order == "최신순",
        )
        if filtered:
            table = pd.DataFrame(
                [
                    {
                        "날짜": item["date"],
                        "사용처": item["place"],
                        "금액": int(item["amount"]),
                        "카테고리": item["category"],
                        "결제 수단": item["payment_method"],
                        "메모": item.get("memo", ""),
                        "목적": item["purpose"],
                        "소비 유형": item["behavior"],
                    }
                    for item in filtered
                ]
            )
            st.dataframe(
                table,
                width="stretch",
                hide_index=True,
                column_config={"금액": st.column_config.NumberColumn(format="₩%d")},
            )
        else:
            st.info("선택한 조건에 해당하는 소비 내역이 없어요.")

        if records:
            def expense_label(expense: dict[str, Any]) -> str:
                return (
                    f"{expense['date']} · {expense['place']} · "
                    f"{won(int(expense['amount']))} ({expense['category']})"
                )

            selected_id = st.selectbox(
                "수정하거나 삭제할 내역",
                [item["id"] for item in sorted(records, key=lambda row: row["date"], reverse=True)],
                format_func=lambda record_id: expense_label(
                    next(item for item in records if item["id"] == record_id)
                ),
                key="expense-selected-id",
            )
            selected = next(item for item in records if item["id"] == selected_id)
            with st.form("edit-expense"):
                st.subheader("내역 수정")
                edit_categories = list(dict.fromkeys([*data["categories"], selected["category"]]))
                fields = expense_form_fields("edit", edit_categories, {
                    **selected,
                    "date": date.fromisoformat(selected["date"]),
                })
                update_submitted = st.form_submit_button("수정 내용 저장", type="primary")
            if update_submitted:
                try:
                    validate_expense(
                        expense_date=fields["date"],
                        place=fields["place"],
                        amount=fields["amount"],
                        category=fields["category"],
                        payment_method=fields["payment_method"],
                        categories=edit_categories,
                    )
                except ValueError as error:
                    st.error(str(error))
                else:
                    updated = deepcopy(data)
                    for item in updated["expenses"]:
                        if item["id"] == selected_id:
                            item.update(
                                {
                                    **fields,
                                    "date": fields["date"].isoformat(),
                                    "amount": int(fields["amount"]),
                                }
                            )
                            break
                    commit_data(updated)
                    st.success("소비 내역을 수정했어요.")
                    st.rerun()
            with st.form("delete-expense"):
                confirmed = st.checkbox("이 소비 내역을 삭제할게요.", key="confirm-expense-delete")
                delete_submitted = st.form_submit_button("선택한 내역 삭제")
            if delete_submitted:
                if not confirmed:
                    st.error("삭제를 진행하려면 확인 항목을 선택해 주세요.")
                else:
                    updated = deepcopy(data)
                    updated["expenses"] = [
                        item for item in updated["expenses"] if item["id"] != selected_id
                    ]
                    commit_data(updated)
                    st.success("소비 내역을 삭제했어요.")
                    st.rerun()


def render_analysis(data: dict[str, Any]) -> None:
    st.title("소비 분석 및 리포트")
    st.caption("분석 기간과 비교 기간을 먼저 선택하면 요약, 비교, 그래프가 함께 업데이트됩니다.")
    today = date.today()
    current_start = today.replace(day=1)
    previous_start, previous_end = month_bounds(
        previous_month(month_key(today)), current_start - timedelta(days=1)
    )
    period_columns = st.columns(2)
    with period_columns[0]:
        st.markdown("#### 분석 기간")
        analysis_range = st.date_input(
            "시작일 · 종료일",
            value=(current_start, today),
            max_value=today,
            key="analysis-date-range",
        )
    with period_columns[1]:
        st.markdown("#### 비교 기간")
        comparison_range = st.date_input(
            "시작일 · 종료일",
            value=(previous_start, previous_end),
            max_value=today,
            key="analysis-comparison-range",
        )
    if not (isinstance(analysis_range, tuple) and len(analysis_range) == 2):
        analysis_range = (current_start, today)
    if not (isinstance(comparison_range, tuple) and len(comparison_range) == 2):
        comparison_range = (previous_start, previous_end)
    start, end = analysis_range
    comparison_start, comparison_end = comparison_range
    if end < start or comparison_end < comparison_start:
        st.error("각 기간의 종료일을 시작일 이후로 선택해 주세요.")
        return

    expenses = expenses_between(data["expenses"], start, end)
    comparison_expenses = expenses_between(
        data["expenses"], comparison_start, comparison_end
    )
    total = total_expense(expenses)
    comparison_total = total_expense(comparison_expenses)
    analysis_stats = period_summary(data["expenses"], start, end)
    comparison_stats = period_summary(
        data["expenses"], comparison_start, comparison_end
    )
    categories = category_totals(expenses)
    report_month = month_key(end)
    report_expenses = month_expenses(data, report_month)
    report_spent = total_expense(report_expenses)
    report_income = total_income(data, report_month)
    report_balance = report_income - report_spent
    prior_month = previous_month(report_month)
    prior_spent = total_expense(month_expenses(data, prior_month))
    budget_limit = (
        int(data["budgets"].get(report_month, {}).get("total", 0))
        if start.year == end.year and start.month == end.month
        else None
    )
    summary = behavior_summary(expenses, budget_limit=budget_limit)
    weekdays = weekday_averages(expenses, start, end)
    top_places: dict[str, int] = {}
    for item in expenses:
        place = str(item.get("place", "")).strip() or "사용처 미입력"
        top_places[place] = top_places.get(place, 0) + int(item["amount"])
    top_category = max(categories, key=categories.get) if categories else "기록 없음"
    top_place = max(top_places, key=top_places.get) if top_places else "기록 없음"

    st.subheader(f"{report_month} 월간 리포트")
    st.caption("분석 기간의 종료일이 속한 달의 수입·지출 요약입니다.")
    report_columns = st.columns(4)
    report_columns[0].metric("총수입", won(report_income))
    report_columns[1].metric("총지출", won(report_spent))
    report_columns[2].metric("잔액", won(report_balance))
    report_columns[3].metric(
        "전월 대비 지출",
        won(report_spent),
        delta=rate_label(report_spent, prior_spent),
        delta_color="inverse",
    )
    if report_income:
        st.progress(
            min(report_spent / report_income, 1.0),
            text=f"수입 대비 지출 {report_spent / report_income:.0%}",
        )
    report_budget = current_budget(data, report_month)["total"]
    if report_budget:
        st.progress(
            min(report_spent / report_budget, 1.0),
            text=f"월간 예산 사용률 {report_spent / report_budget:.0%}",
        )
    else:
        st.info(f"{report_month} 예산을 설정하면 리포트에서 예산 사용률을 확인할 수 있어요.")

    st.divider()
    st.subheader(f"분석 기간 요약 · {start:%Y-%m-%d} – {end:%Y-%m-%d}")
    summary_columns = st.columns(3)
    summary_columns[0].metric("기간 총지출", won(total))
    summary_columns[1].metric("비교 기간 총지출", won(comparison_total))
    comparison_rate = compare_amounts(total, comparison_total)["rate"]
    summary_columns[2].metric(
        "지출 증감액",
        won(total - comparison_total),
        delta=(
            f"{float(comparison_rate):+.1%}"
            if comparison_rate is not None
            else ("신규 지출" if total else "변동 없음")
        ),
        delta_color="inverse",
    )
    st.caption(
        f"분석 기간 {len(expenses)}건 · 가장 많이 쓴 카테고리 {top_category} "
        f"· 두 기간 지출 차이 {won(total - comparison_total)}"
    )
    st.caption(
        f"분석 기간 {analysis_stats['days']}일 · 일평균 {won(analysis_stats['daily_average'])}"
        f"　|　비교 기간 {comparison_stats['days']}일 · "
        f"일평균 {won(comparison_stats['daily_average'])}"
    )
    if top_places:
        st.caption(f"주요 사용처: {top_place} ({won(top_places[top_place])})")
    if expenses:
        st.write(
            f"이 기간에 {len(expenses)}건을 소비했고 평균 지출은 "
            f"{won(total / len(expenses))}입니다. {summary['description']}"
        )

    left, right = st.columns(2)
    with left:
        st.subheader("카테고리별 소비 비교")
        st.caption("선택한 두 기간의 카테고리별 지출 금액을 비교합니다.")
        category_rows = category_comparison(expenses, comparison_expenses)
        if category_rows:
            category_frame = pd.DataFrame(
                [
                    {
                        "카테고리": row["category"],
                        "분석 기간": int(row["current"]),
                        "비교 기간": int(row["previous"]),
                    }
                    for row in category_rows
                ]
            )
            figure = px.bar(
                category_frame.melt(
                    id_vars="카테고리", var_name="기간", value_name="지출"
                ),
                x="카테고리",
                y="지출",
                color="기간",
                barmode="group",
                color_discrete_sequence=["#12a67a", "#b8e4d4"],
                labels={"지출": "지출 (₩)"},
            )
            figure.update_layout(legend_title_text="")
            st.plotly_chart(figure, width="stretch")
        else:
            empty_chart("선택한 두 기간에 소비 내역이 없습니다.")

    with right:
        st.subheader("카테고리별 소비 비중")
        st.caption("분석 기간의 총지출에서 각 카테고리가 차지하는 비율입니다.")
        if categories:
            figure = px.pie(
                names=list(categories),
                values=list(categories.values()),
                hole=0.55,
                color_discrete_sequence=px.colors.qualitative.Pastel,
            )
            st.plotly_chart(figure, width="stretch")
        else:
            empty_chart("분석 기간에 소비 내역을 등록하면 비중을 볼 수 있어요.")

    st.subheader("분석 기간의 월별 소비 추이")
    st.caption("선택한 분석 기간에 해당하는 날짜만 월별로 합산합니다.")
    monthly_rows = grouped_spending(
        data["expenses"], start, end, "월별", "분석 기간"
    )
    if any(int(row["amount"]) > 0 for row in monthly_rows):
        month_labels = []
        cursor = start.replace(day=1)
        while cursor <= end:
            month_labels.append(month_key(cursor))
            cursor = date(
                cursor.year + (cursor.month == 12),
                cursor.month % 12 + 1,
                1,
            )
        monthly_frame = pd.DataFrame(
            [
                {"월": month, "지출": int(row["amount"])}
                for month, row in zip(month_labels, monthly_rows)
            ]
        )
        figure = px.bar(
            monthly_frame,
            x="월",
            y="지출",
            color="지출",
            color_continuous_scale=["#c9eee1", "#12a67a"],
            labels={"지출": "월 지출 (₩)"},
        )
        figure.update_layout(coloraxis_showscale=False)
        st.plotly_chart(figure, width="stretch")
    else:
        empty_chart("선택한 분석 기간에 소비 내역이 없습니다.")

    st.subheader("두 기간 소비 추이 비교")
    st.caption("두 기간의 지출 합계를 일별·주별·월별로 나란히 비교합니다.")
    granularity = st.selectbox(
        "추이 집계 단위",
        ["일별", "주별", "월별"],
        key="analysis-comparison-granularity",
    )
    trend_rows = grouped_spending(
        data["expenses"], start, end, granularity, "분석 기간"
    ) + grouped_spending(
        data["expenses"],
        comparison_start,
        comparison_end,
        granularity,
        "비교 기간",
    )
    if total or comparison_total:
        figure = px.bar(
            pd.DataFrame(trend_rows),
            x="interval",
            y="amount",
            color="period",
            barmode="group",
            color_discrete_sequence=["#12a67a", "#b8e4d4"],
            labels={"interval": "기간 내 구간", "amount": "지출 (₩)", "period": "비교 기간"},
        )
        figure.update_layout(legend_title_text="")
        st.plotly_chart(figure, width="stretch")
    else:
        empty_chart("선택한 두 기간에 소비 내역이 없습니다.")

    left, right = st.columns(2)
    with left:
        st.subheader("요일별 소비 패턴")
        st.caption("요일별 총지출이 아닌, 해당 요일 하루의 평균 소비액을 표시합니다.")
        weekday_frame = pd.DataFrame(
            [{"요일": item["weekday"], "평균 지출": item["average"]} for item in weekdays]
        )
        figure = px.bar(
            weekday_frame,
            x="요일",
            y="평균 지출",
            color="평균 지출",
            color_continuous_scale=["#c9eee1", "#12a67a"],
            labels={"평균 지출": "하루 평균 지출 (₩)"},
        )
        figure.update_layout(coloraxis_showscale=False)
        st.plotly_chart(figure, width="stretch")

    with right:
        st.subheader("계획 소비 · 지출 목적 비율")
        st.caption("금액 기준으로 소비 방식과 필수·선택 지출의 비율을 봅니다.")
        if total:
            behavior_frame = pd.DataFrame(
                {
                    "구분": ["계획 소비", "충동 소비", "필수 지출", "선택 지출"],
                    "비율": [
                        summary["planned_ratio"],
                        summary["impulsive_ratio"],
                        summary["necessary_ratio"],
                        summary["optional_ratio"],
                    ],
                }
            )
            figure = px.bar(
                behavior_frame,
                x="구분",
                y="비율",
                color="구분",
                range_y=[0, 1],
                labels={"비율": "전체 지출 대비 비율"},
                color_discrete_sequence=["#12a67a", "#b8e4d4", "#70c6a7", "#d9eee6"],
            )
            figure.update_layout(yaxis_tickformat=".0%", showlegend=False)
            st.plotly_chart(figure, width="stretch")
        else:
            empty_chart("소비 내역이 있으면 소비 방식과 지출 목적을 분석할 수 있어요.")

    st.subheader(f"소비 성향 진단: {summary['type']}")
    st.write(summary["description"])
    st.subheader("주요 소비 카테고리와 사용처")
    detail_columns = st.columns(2)
    if categories:
        top_categories = sorted(categories.items(), key=lambda row: row[1], reverse=True)[:5]
        detail_columns[0].dataframe(
            pd.DataFrame(
                [{"카테고리": name, "지출": amount} for name, amount in top_categories]
            ),
            width="stretch",
            hide_index=True,
            column_config={"지출": st.column_config.NumberColumn(format="₩%d")},
        )
    if top_places:
        top_place_rows = sorted(top_places.items(), key=lambda row: row[1], reverse=True)[:5]
        detail_columns[1].dataframe(
            pd.DataFrame(
                [{"사용처": name, "지출": amount} for name, amount in top_place_rows]
            ),
            width="stretch",
            hide_index=True,
            column_config={"지출": st.column_config.NumberColumn(format="₩%d")},
        )

    st.subheader("월간 소비 리포트")
    st.caption(
        f"{report_month} 총 {len(report_expenses)}건, "
        f"평균 지출 {won(report_spent / len(report_expenses)) if report_expenses else '₩0'}"
        f" · 전월 지출 {won(prior_spent)}"
    )
    for index, recommendation in enumerate(
        personalized_recommendations(data, report_month), start=1
    ):
        st.markdown(f"**{index}.** {recommendation}")


def render_budget(data: dict[str, Any]) -> None:
    st.title("예산 및 저축 관리")
    st.caption("월간 예산과 저축 목표를 함께 관리하고, 실제 소비에 맞춘 개선 제안을 확인해요.")
    month = select_month("예산을 설정할 월")
    budget = current_budget(data, month)
    categories = list(budget["categories"])
    expenses = month_expenses(data, month)
    spent = total_expense(expenses)

    with st.form("budget-settings"):
        st.subheader(f"{month} 예산 설정")
        total_budget = st.number_input(
            "월간 총예산 (₩)",
            min_value=0,
            value=budget["total"],
            step=10000,
            key=f"budget-total-{month}",
        )
        st.markdown("#### 카테고리별 예산")
        columns = st.columns(2)
        category_budgets = {}
        for index, category in enumerate(categories):
            with columns[index % 2]:
                category_budgets[category] = st.number_input(
                    f"{category} 예산 (₩)",
                    min_value=0,
                    value=budget["categories"][category],
                    step=5000,
                    key=f"budget-{month}-{category}",
                )
        submitted = st.form_submit_button("예산 저장", type="primary")
    if submitted:
        updated = deepcopy(data)
        updated["budgets"][month] = {
            "total": int(total_budget),
            "categories": {name: int(amount) for name, amount in category_budgets.items()},
        }
        commit_data(updated)
        st.success("예산을 저장했어요.")
        st.rerun()

    st.divider()
    st.subheader("실제 지출과 예산 비교")
    summary_columns = st.columns(3)
    summary_columns[0].metric("총예산", won(budget["total"]))
    summary_columns[1].metric("사용 금액", won(spent))
    summary_columns[2].metric("잔여 금액", won(budget["total"] - spent))
    show_budget_status(data, month)
    actual_by_category = category_totals(expenses)
    comparison = pd.DataFrame(
        [
            {
                "카테고리": category,
                "예산": budget["categories"][category],
                "실제 지출": actual_by_category.get(category, 0),
            }
            for category in categories
            if budget["categories"][category] > 0 or actual_by_category.get(category, 0) > 0
        ]
    )
    if not comparison.empty:
        figure = px.bar(
            comparison,
            x="카테고리",
            y=["예산", "실제 지출"],
            barmode="group",
            color_discrete_sequence=["#b8e4d4", "#12a67a"],
            labels={"value": "금액 (원)", "variable": "항목"},
        )
        figure.update_layout(legend_title_text="", height=370)
        st.plotly_chart(figure, width="stretch")
    else:
        empty_chart("예산을 설정하거나 소비 내역을 등록하면 비교 그래프가 표시돼요.")

    st.subheader("카테고리별 예산 사용률")
    st.caption("설정한 한도와 실제 지출, 남은 금액을 확인할 수 있어요.")
    tracked_categories = [
        category
        for category in categories
        if budget["categories"][category] > 0 or actual_by_category.get(category, 0) > 0
    ]
    if tracked_categories:
        for category in tracked_categories:
            limit = budget["categories"][category]
            actual = actual_by_category.get(category, 0)
            if limit:
                ratio = actual / limit
                st.progress(
                    min(ratio, 1.0),
                    text=(
                        f"{category} · {won(actual)} / {won(limit)} "
                        f"· 잔여 {won(limit - actual)} · 사용률 {ratio:.0%}"
                    ),
                )
            else:
                st.caption(f"{category} · {won(actual)} 지출 · 설정된 카테고리 예산 없음")
    else:
        st.info("카테고리별 예산을 설정하면 사용률을 확인할 수 있어요.")

    st.divider()
    render_savings(data)
    st.divider()
    st.subheader(f"{month} 실제 소비 기반 개선 제안")
    for index, recommendation in enumerate(
        personalized_recommendations(data, month), start=1
    ):
        st.markdown(f"**{index}.** {recommendation}")


def render_income(data: dict[str, Any]) -> None:
    categories = categories_for(data) or ["기타"]
    month = select_month("수입 합계를 확인할 월")
    st.metric(f"{month} 총수입", won(total_income(data, month)))
    st.divider()
    add_tab, manage_tab = st.tabs(["수입 등록", "수입 조회 · 수정 · 삭제"])

    with add_tab:
        with st.expander("카테고리 추가"):
            new_category = st.text_input(
                "추가할 카테고리 이름",
                max_chars=30,
                key="create-income-new-category",
            )
            if st.button("카테고리 추가", key="add-income-category-inline"):
                try:
                    new_category = validate_category_name(new_category, data["categories"])
                except ValueError as error:
                    st.error(str(error))
                else:
                    updated = deepcopy(data)
                    updated["categories"].append(new_category)
                    commit_data(updated)
                    st.success(f"'{new_category}' 카테고리를 추가했어요.")
                    st.rerun()

        with st.form("create-income", clear_on_submit=True):
            st.subheader("새 수입 등록")
            input_columns = st.columns([1, 2, 1])
            with input_columns[0]:
                income_date = st.date_input(
                    "날짜",
                    value=date.today(),
                    max_value=date.today(),
                    key="create-income-date",
                )
            with input_columns[1]:
                item = st.text_input("수입 항목", max_chars=80, key="create-income-item")
            with input_columns[2]:
                amount = st.number_input(
                    "금액 (₩)",
                    min_value=1,
                    value=10000,
                    step=10000,
                    key="create-income-amount",
                )
            category_options = categories_for(data) or ["기타"]
            income_category = st.selectbox(
                "카테고리",
                category_options,
                key="create-income-category",
            )
            memo = st.text_input("메모 (선택)", max_chars=200, key="create-income-memo")
            submitted = st.form_submit_button("수입 저장", type="primary")
        if submitted:
            try:
                validate_income(
                    income_date=income_date,
                    item=item,
                    amount=amount,
                    category=income_category,
                    categories=category_options,
                )
            except ValueError as error:
                st.error(str(error))
            else:
                updated = deepcopy(data)
                updated["income_records"].append(
                    {
                        "id": new_id(),
                        "date": income_date.isoformat(),
                        "item": item.strip(),
                        "amount": int(amount),
                        "category": income_category,
                        "memo": memo.strip(),
                    }
                )
                commit_data(updated)
                st.success("수입 내역을 저장했어요.")
                st.rerun()

        with st.expander("카테고리 이름 변경 · 삭제"):
            render_inline_category_management(data)

    with manage_tab:
        today = date.today()
        default_start = today.replace(day=1)
        date_range = st.date_input(
            "조회 기간",
            value=(default_start, today),
            max_value=today,
            key="income-filter-dates",
        )
        filter_columns = st.columns(2)
        with filter_columns[0]:
            category_filter = st.selectbox(
                "카테고리 필터", ["전체", *categories], key="income-filter-category"
            )
        with filter_columns[1]:
            search_term = st.text_input(
                "수입 항목 · 메모 검색", key="income-search"
            ).strip().casefold()
        start, end = date_range if isinstance(date_range, tuple) and len(date_range) == 2 else (
            default_start,
            today,
        )
        filtered = [
            record
            for record in data["income_records"]
            if start.isoformat() <= record["date"] <= end.isoformat()
            and (category_filter == "전체" or record.get("category", "기타") == category_filter)
            and (
                not search_term
                or search_term in record["item"].casefold()
                or search_term in record.get("memo", "").casefold()
            )
        ]
        filtered.sort(key=lambda record: (record["date"], record["id"]), reverse=True)
        if filtered:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "날짜": record["date"],
                            "수입 항목": record["item"],
                            "금액": int(record["amount"]),
                            "카테고리": record.get("category", "기타"),
                            "메모": record.get("memo", ""),
                        }
                        for record in filtered
                    ]
                ),
                width="stretch",
                hide_index=True,
                column_config={"금액": st.column_config.NumberColumn(format="₩%d")},
            )
        else:
            st.info("선택한 조건에 해당하는 수입 내역이 없어요.")

        if data["income_records"]:
            selected_id = st.selectbox(
                "수정하거나 삭제할 수입",
                [
                    record["id"]
                    for record in sorted(
                        data["income_records"], key=lambda row: row["date"], reverse=True
                    )
                ],
                format_func=lambda record_id: next(
                    f"{record['date']} · {record['item']} · {won(int(record['amount']))}"
                    for record in data["income_records"]
                    if record["id"] == record_id
                ),
                key="income-selected-id",
            )
            selected = next(
                record for record in data["income_records"] if record["id"] == selected_id
            )
            with st.form("edit-income"):
                st.subheader("수입 수정")
                input_columns = st.columns([1, 2, 1])
                with input_columns[0]:
                    income_date = st.date_input(
                        "날짜",
                        value=date.fromisoformat(selected["date"]),
                        max_value=date.today(),
                        key="edit-income-date",
                    )
                with input_columns[1]:
                    item = st.text_input(
                        "수입 항목",
                        value=selected["item"],
                        max_chars=80,
                        key="edit-income-item",
                    )
                with input_columns[2]:
                    amount = st.number_input(
                        "금액 (₩)",
                        min_value=1,
                        value=int(selected["amount"]),
                        step=10000,
                        key="edit-income-amount",
                    )
                edit_categories = list(
                    dict.fromkeys([*categories, selected.get("category", "기타")])
                )
                income_category = st.selectbox(
                    "카테고리",
                    edit_categories,
                    index=edit_categories.index(selected.get("category", "기타")),
                    key="edit-income-category",
                )
                memo = st.text_input(
                    "메모 (선택)",
                    value=selected.get("memo", ""),
                    max_chars=200,
                    key="edit-income-memo",
                )
                update_submitted = st.form_submit_button("수입 수정 저장", type="primary")
            if update_submitted:
                try:
                    validate_income(
                        income_date=income_date,
                        item=item,
                        amount=amount,
                        category=income_category,
                        categories=edit_categories,
                    )
                except ValueError as error:
                    st.error(str(error))
                else:
                    updated = deepcopy(data)
                    for record in updated["income_records"]:
                        if record["id"] == selected_id:
                            record.update(
                                {
                                    "date": income_date.isoformat(),
                                    "item": item.strip(),
                                    "amount": int(amount),
                                    "category": income_category,
                                    "memo": memo.strip(),
                                }
                            )
                            break
                    commit_data(updated)
                    st.success("수입 내역을 수정했어요.")
                    st.rerun()
            with st.form("delete-income"):
                confirmed = st.checkbox("이 수입 내역을 삭제할게요.", key="confirm-income-delete")
                delete_submitted = st.form_submit_button("선택한 수입 삭제")
            if delete_submitted:
                if not confirmed:
                    st.error("삭제를 진행하려면 확인 항목을 선택해 주세요.")
                else:
                    updated = deepcopy(data)
                    updated["income_records"] = [
                        record
                        for record in updated["income_records"]
                        if record["id"] != selected_id
                    ]
                    commit_data(updated)
                    st.success("수입 내역을 삭제했어요.")
                    st.rerun()


def render_inline_category_management(data: dict[str, Any]) -> None:
    if not data["categories"]:
        st.info("카테고리가 없습니다. 위의 카테고리 선택란에서 새 카테고리를 추가해 주세요.")
        return

    selected = st.selectbox(
        "수정하거나 삭제할 카테고리",
        data["categories"],
        key="inline-category-selected",
    )
    with st.form("rename-category-inline"):
        new_name = st.text_input("새 카테고리 이름", value=selected, max_chars=30)
        rename_submitted = st.form_submit_button("카테고리 이름 변경")
    if rename_submitted:
        try:
            new_name = validate_category_name(new_name, data["categories"], selected)
        except ValueError as error:
            st.error(str(error))
        else:
            updated = deepcopy(data)
            updated["categories"] = [
                new_name if name == selected else name for name in updated["categories"]
            ]
            for expense in updated["expenses"]:
                if expense.get("category") == selected:
                    expense["category"] = new_name
            for record in updated["income_records"]:
                if record.get("category") == selected:
                    record["category"] = new_name
            for budget in updated["budgets"].values():
                if selected in budget.get("categories", {}):
                    budget["categories"][new_name] = budget["categories"].pop(selected)
            commit_data(updated)
            st.success("카테고리 이름을 변경했어요.")
            st.rerun()

    with st.form("delete-category-inline"):
        confirmed = st.checkbox(
            "삭제해도 기존 소비 내역은 보존됩니다.",
            key="confirm-category-delete-inline",
        )
        delete_submitted = st.form_submit_button("카테고리 삭제")
    if delete_submitted:
        if not confirmed:
            st.error("삭제를 진행하려면 확인 항목을 선택해 주세요.")
        else:
            updated = deepcopy(data)
            updated["categories"] = [
                name for name in updated["categories"] if name != selected
            ]
            commit_data(updated)
            st.success("카테고리를 삭제했어요. 기존 소비 내역은 그대로 보존됩니다.")
            st.rerun()


def render_records(data: dict[str, Any]) -> None:
    st.title("내역 입력 및 관리")
    st.caption("지출과 수입을 한곳에서 기록하고, 기존 내역을 검색·수정·삭제할 수 있어요.")
    record_type = st.radio(
        "입력 유형",
        ["지출 입력", "수입 입력"],
        horizontal=True,
        key="record-entry-type",
    )
    st.divider()
    if record_type == "지출 입력":
        render_expenses(data)
    else:
        render_income(data)


def previous_month(month: str) -> str:
    year, month_number = (int(part) for part in month.split("-"))
    index = year * 12 + month_number - 2
    previous_year, previous_month_number = divmod(index, 12)
    return f"{previous_year:04d}-{previous_month_number + 1:02d}"


def month_bounds(month: str, today: date) -> tuple[date, date]:
    year, month_number = (int(part) for part in month.split("-"))
    start = date(year, month_number, 1)
    if month_number == 12:
        next_month_start = date(year + 1, 1, 1)
    else:
        next_month_start = date(year, month_number + 1, 1)
    return start, min(next_month_start - timedelta(days=1), today)


def rate_label(current: int | float, previous: int | float) -> str:
    comparison = compare_amounts(current, previous)
    difference = int(comparison["difference"])
    if previous == 0:
        return "신규 지출" if current else "변동 없음"
    direction = "증가" if difference > 0 else "감소" if difference < 0 else "변동 없음"
    rate = abs(float(comparison["rate"] or 0))
    return f"{direction} {won(abs(difference))} ({rate:.1%})" if difference else direction


def personalized_recommendations(data: dict[str, Any], month: str) -> list[str]:
    expenses = month_expenses(data, month)
    if not expenses:
        return ["이 달의 소비 내역을 등록하면 실제 지출에 맞춘 제안을 확인할 수 있어요."]

    previous = previous_month(month)
    previous_expenses = month_expenses(data, previous)
    categories = category_comparison(expenses, previous_expenses)
    budget = current_budget(data, month)
    summary = behavior_summary(expenses, budget_limit=budget["total"])
    spent = total_expense(expenses)
    recommendations: list[str] = []

    increased = next((row for row in categories if int(row["difference"]) > 0), None)
    if increased:
        rate = increased["rate"]
        if rate is None:
            recommendations.append(
                f"**{increased['category']}**에서 {won(int(increased['current']))}의 소비가 새로 기록됐어요. "
                "다음 달에는 이 항목이 반복 지출인지 먼저 확인해 보세요."
            )
        elif float(rate) >= 0.2:
            recommendations.append(
                f"**{increased['category']}** 지출이 지난달보다 "
                f"{won(int(increased['difference']))} ({float(rate):.1%}) 증가했어요. "
                "다음 달에는 해당 카테고리의 주간 한도를 정해 지출을 점검해 보세요."
            )

    if summary["type"] == "데이터 부족":
        recommendations.append(summary["description"])
    elif summary["impulsive_ratio"] >= 0.25:
        recommendations.append(
            f"충동 소비가 전체 지출의 {summary['impulsive_ratio']:.1%}예요. "
            "충동 소비로 기록한 구매에는 24시간 대기 규칙을 적용해 보세요."
        )

    if budget["total"] > 0:
        usage = spent / budget["total"]
        previous_budget = current_budget(data, previous)
        previous_spent = total_expense(previous_expenses)
        repeated_overrun = (
            previous_budget["total"] > 0
            and previous_spent > previous_budget["total"]
            and spent > budget["total"]
        )
        if repeated_overrun:
            recommendations.append(
                f"이번 달과 지난달 모두 총예산을 초과했어요. "
                f"지난 2개월 평균 지출({won((spent + previous_spent) / 2)})을 기준으로 "
                "다음 달 예산을 현실적으로 조정하고, 줄일 카테고리를 함께 정해 보세요."
            )
        elif usage >= 1:
            recommendations.append(
                f"예산을 {won(spent - budget['total'])} 초과했어요. "
                "예산을 넘긴 카테고리의 다음 결제부터 한도를 확인해 보세요."
            )
        elif usage >= 0.8:
            recommendations.append(
                f"예산의 {usage:.1%}를 사용했어요. 남은 {won(budget['total'] - spent)} 안에서 "
                "월말 지출을 계획해 보세요."
            )

    goal = data["savings_goal"]
    target = int(goal.get("target", 0))
    if target > 0:
        start = date.fromisoformat(str(goal.get("start_date", date.today().isoformat())))
        months_elapsed = max(
            1, (date.today().year - start.year) * 12 + date.today().month - start.month + 1
        )
        expected_progress = min(
            1.0, months_elapsed / max(1, int(goal.get("months", 12)))
        )
        current_progress = min(1.0, int(goal.get("saved", 0)) / target)
        if current_progress < expected_progress:
            gap = int(target * expected_progress - int(goal.get("saved", 0)))
            optional_by_category: dict[str, int] = {}
            for item in expenses:
                if item.get("purpose") == "선택 지출":
                    category = str(item.get("category", "기타"))
                    optional_by_category[category] = (
                        optional_by_category.get(category, 0) + int(item["amount"])
                    )
            if optional_by_category:
                discretionary_category = max(optional_by_category, key=optional_by_category.get)
                recommendations.append(
                    f"저축 목표 진행이 계획보다 {won(gap)} 뒤처져 있어요. "
                    f"이번 달 선택 지출 중 가장 큰 **{discretionary_category}**를 "
                    "우선 점검해 목표액을 보완해 보세요."
                )
            else:
                recommendations.append(
                    f"저축 목표 진행이 계획보다 {won(gap)} 뒤처져 있어요. "
                    "이번 달 선택 지출을 기록하면 줄일 수 있는 항목을 더 구체적으로 찾을 수 있어요."
                )

    if not recommendations:
        top_category = max(category_totals(expenses), key=category_totals(expenses).get)
        recommendations.append(
            f"현재 기록에서는 두드러진 예산 초과나 소비 급증이 없어요. "
            f"지출 중 비중이 가장 큰 **{top_category}**를 다음 달에도 살펴보세요."
        )
    return recommendations


def render_comparison(data: dict[str, Any]) -> None:
    st.title("기간별 소비 비교")
    st.caption("저장된 소비 내역으로 월별 변화와 원하는 기간의 소비 흐름을 비교해요.")
    monthly_tab, custom_tab = st.tabs(["이번 달 · 지난달", "원하는 두 기간 비교"])

    with monthly_tab:
        month = select_month("비교할 기준 월")
        previous = previous_month(month)
        current_start, current_end = month_bounds(month, date.today())
        previous_start, previous_end = month_bounds(previous, current_start - timedelta(days=1))
        current_expenses = expenses_between(data["expenses"], current_start, current_end)
        previous_expenses = expenses_between(data["expenses"], previous_start, previous_end)
        current_total = total_expense(current_expenses)
        previous_total = total_expense(previous_expenses)
        current_stats = period_summary(data["expenses"], current_start, current_end)
        previous_stats = period_summary(data["expenses"], previous_start, previous_end)

        st.subheader(f"{month} · {previous} 지출 비교")
        first, second, third, fourth = st.columns(4)
        first.metric(f"{month} 총지출", won(current_total))
        second.metric(f"{previous} 총지출", won(previous_total))
        second.caption(rate_label(current_total, previous_total))
        third.metric("이번 기간 일평균", won(current_stats["daily_average"]))
        fourth.metric("지난 기간 일평균", won(previous_stats["daily_average"]))
        st.caption(
            f"비교 기간: {current_start:%Y-%m-%d}–{current_end:%Y-%m-%d} "
            f"({current_stats['days']}일) · {previous_start:%Y-%m-%d}–{previous_end:%Y-%m-%d} "
            f"({previous_stats['days']}일)"
        )

        monthly_comparison = pd.DataFrame(
            [
                {"카테고리": row["category"], month: row["current"], previous: row["previous"]}
                for row in category_comparison(current_expenses, previous_expenses)
            ]
        )
        if not monthly_comparison.empty:
            left, right = st.columns(2)
            with left:
                st.subheader("카테고리별 지출 비교")
                figure = px.bar(
                    monthly_comparison.melt(
                        id_vars="카테고리", var_name="기간", value_name="지출"
                    ),
                    x="카테고리",
                    y="지출",
                    color="기간",
                    barmode="group",
                    color_discrete_sequence=["#12a67a", "#b8e4d4"],
                    labels={"지출": "지출 (₩)"},
                )
                figure.update_layout(legend_title_text="")
                st.plotly_chart(figure, width="stretch")
            with right:
                st.subheader("카테고리별 지출 비중")
                pie_columns = st.columns(2)
                for column, label, rows, value_key in (
                    (pie_columns[0], month, category_comparison(current_expenses, previous_expenses), "current"),
                    (pie_columns[1], previous, category_comparison(current_expenses, previous_expenses), "previous"),
                ):
                    values = [int(row[value_key]) for row in rows]
                    names = [str(row["category"]) for row in rows]
                    with column:
                        st.caption(label)
                        if sum(values):
                            figure = px.pie(
                                names=names,
                                values=values,
                                hole=0.55,
                                color_discrete_sequence=px.colors.qualitative.Pastel,
                            )
                            figure.update_layout(height=250, margin=dict(t=0, b=0, l=0, r=0))
                            st.plotly_chart(figure, width="stretch")
                        else:
                            st.caption("해당 기간에는 소비 내역이 없어요.")

            changed_rows = category_comparison(current_expenses, previous_expenses)
            increased = next((row for row in changed_rows if int(row["difference"]) > 0), None)
            decreased = next(
                (row for row in reversed(changed_rows) if int(row["difference"]) < 0), None
            )
            changes = []
            if increased:
                changes.append(f"가장 증가: {increased['category']} +{won(int(increased['difference']))}")
            if decreased:
                changes.append(f"가장 감소: {decreased['category']} {won(int(decreased['difference']))}")
            st.info("　 ·　".join(changes) if changes else "카테고리 지출에 증감이 없어요.")
        else:
            empty_chart("두 달 모두 소비 내역이 없어 카테고리 비교를 표시할 수 없어요.")

        month_budget = current_budget(data, month)
        actual = category_totals(current_expenses)
        budget_rows = [
            {
                "카테고리": category,
                "예산": int(limit),
                "실제 지출": actual.get(category, 0),
            }
            for category, limit in month_budget["categories"].items()
            if limit > 0 or actual.get(category, 0) > 0
        ]
        st.subheader(f"{month} 카테고리 예산 대비 실제 지출")
        if budget_rows:
            figure = px.bar(
                pd.DataFrame(budget_rows),
                x="카테고리",
                y=["예산", "실제 지출"],
                barmode="group",
                color_discrete_sequence=["#b8e4d4", "#12a67a"],
                labels={"value": "금액 (₩)", "variable": "항목"},
            )
            figure.update_layout(legend_title_text="")
            st.plotly_chart(figure, width="stretch")
        else:
            st.info("예산 또는 지출 내역이 등록되면 카테고리별로 비교할 수 있어요.")

    with custom_tab:
        today = date.today()
        current_start = today.replace(day=1)
        previous_start = date.fromisoformat(f"{previous_month(month_key(today))}-01")
        previous_end = current_start - timedelta(days=1)
        first_col, second_col = st.columns(2)
        with first_col:
            st.markdown("#### 기간 A")
            first_range = st.date_input(
                "기간 A 시작일 · 종료일",
                value=(current_start, today),
                max_value=today,
                key="compare-range-a",
            )
        with second_col:
            st.markdown("#### 기간 B")
            second_range = st.date_input(
                "기간 B 시작일 · 종료일",
                value=(previous_start, previous_end),
                max_value=today,
                key="compare-range-b",
            )
        if not (isinstance(first_range, tuple) and len(first_range) == 2):
            first_range = (current_start, today)
        if not (isinstance(second_range, tuple) and len(second_range) == 2):
            second_range = (previous_start, previous_end)
        start_a, end_a = first_range
        start_b, end_b = second_range
        if end_a < start_a or end_b < start_b:
            st.error("각 기간의 종료일을 시작일 이후로 선택해 주세요.")
        else:
            label_a = f"A ({start_a:%m/%d}–{end_a:%m/%d})"
            label_b = f"B ({start_b:%m/%d}–{end_b:%m/%d})"
            expenses_a = expenses_between(data["expenses"], start_a, end_a)
            expenses_b = expenses_between(data["expenses"], start_b, end_b)
            stats_a = period_summary(data["expenses"], start_a, end_a)
            stats_b = period_summary(data["expenses"], start_b, end_b)
            total_a = int(stats_a["total"])
            total_b = int(stats_b["total"])
            amount_change = compare_amounts(total_a, total_b)
            daily_change = compare_amounts(stats_a["daily_average"], stats_b["daily_average"])

            st.subheader("기간 합계와 일평균 비교")
            columns = st.columns(4)
            columns[0].metric(label_a, won(total_a))
            columns[1].metric(label_b, won(total_b))
            columns[2].metric("총지출 증감", rate_label(total_a, total_b))
            columns[3].metric(
                "일평균 증감",
                rate_label(stats_a["daily_average"], stats_b["daily_average"]),
            )
            st.caption(
                f"기간 A {stats_a['days']}일 · {won(stats_a['daily_average'])}/일"
                f"　|　기간 B {stats_b['days']}일 · {won(stats_b['daily_average'])}/일"
            )
            granularity = st.selectbox(
                "추이 집계 단위",
                ["일별", "주별", "월별"],
                key="comparison-granularity",
            )
            trend_rows = grouped_spending(
                data["expenses"], start_a, end_a, granularity, label_a
            ) + grouped_spending(data["expenses"], start_b, end_b, granularity, label_b)
            if total_a or total_b:
                figure = px.bar(
                    pd.DataFrame(trend_rows),
                    x="interval",
                    y="amount",
                    color="period",
                    barmode="group",
                    color_discrete_sequence=["#12a67a", "#b8e4d4"],
                    labels={"interval": "기간 내 구간", "amount": "지출 (₩)", "period": "비교 기간"},
                )
                figure.update_layout(legend_title_text="")
                st.plotly_chart(figure, width="stretch")
            else:
                empty_chart("두 기간에 소비 내역이 없습니다.")


def render_report(data: dict[str, Any]) -> None:
    st.title("월간 소비 리포트")
    month = select_month("리포트 월")
    expenses = month_expenses(data, month)
    spent = total_expense(expenses)
    income = total_income(data, month)
    balance = income - spent
    prev_month = previous_month(month)
    prev_spent = total_expense(month_expenses(data, prev_month))

    first, second, third, fourth = st.columns(4)
    first.metric("총수입", won(income))
    second.metric("총지출", won(spent))
    third.metric("잔액", won(balance))
    if prev_spent:
        fourth.metric("전월 대비 지출", won(spent), delta=rate_label(spent, prev_spent))
    elif spent:
        fourth.metric("전월 대비 지출", rate_label(spent, prev_spent))
    else:
        fourth.metric("전월 대비 지출", "비교 데이터 없음")

    category_amounts = category_totals(expenses)
    top_category = max(category_amounts, key=category_amounts.get) if category_amounts else "기록 없음"
    budget = current_budget(data, month)
    traits = behavior_summary(expenses, budget_limit=budget["total"])
    st.info(f"가장 많이 소비한 카테고리: **{top_category}** · 소비 성향: **{traits['type']}**")
    if budget["total"] > 0:
        usage = spent / budget["total"]
        st.progress(
            min(usage, 1.0),
            text=f"월간 예산 사용률 {usage:.1%} · 남은 예산 {won(budget['total'] - spent)}",
        )
    else:
        st.info("월간 예산을 설정하면 리포트에 예산 사용률이 표시돼요.")
    if category_amounts:
        report_frame = pd.DataFrame(
            {"카테고리": list(category_amounts), "지출": list(category_amounts.values())}
        )
        figure = px.bar(
            report_frame,
            x="카테고리",
            y="지출",
            color="지출",
            color_continuous_scale=["#c9eee1", "#12a67a"],
            labels={"지출": "금액 (원)"},
        )
        figure.update_layout(coloraxis_showscale=False)
        st.plotly_chart(figure, width="stretch")
    else:
        empty_chart("이 달의 소비 내역이 아직 없어요.")

    if income > 0:
        st.progress(min(spent / income, 1.0), text=f"수입 대비 지출 {spent / income:.0%}")
    if expenses:
        st.subheader("이번 달 소비 요약")
        st.write(
            f"총 {len(expenses)}건을 소비했고, 평균 소비 금액은 "
            f"{won(spent / len(expenses))}이에요. {traits['description']}"
        )
    st.subheader("다음 달 소비 개선 제안")
    for index, recommendation in enumerate(
        personalized_recommendations(data, month), start=1
    ):
        st.markdown(f"**{index}.** {recommendation}")


def recent_month_keys(month: str, count: int) -> list[str]:
    year, month_number = (int(part) for part in month.split("-"))
    index = year * 12 + month_number - 1
    keys = []
    for offset in range(count - 1, -1, -1):
        year_number, month_index = divmod(index - offset, 12)
        keys.append(f"{year_number:04d}-{month_index + 1:02d}")
    return keys


def render_savings(data: dict[str, Any]) -> None:
    st.subheader("저축 목표")
    st.caption("목표 금액, 현재 저축액과 달성 예상 시점을 함께 확인해요.")
    goal = data["savings_goal"]
    with st.form("savings-goal"):
        goal_name = st.text_input(
            "저축 목표 이름",
            value=str(goal.get("name", "")),
            max_chars=80,
            key="savings-name",
        )
        target = st.number_input(
            "목표 저축 금액 (₩)",
            min_value=0,
            value=int(goal.get("target", 0)),
            step=100000,
            key="savings-target",
        )
        months = st.number_input(
            "목표 기간 (개월)",
            min_value=1,
            value=max(1, int(goal.get("months", 12))),
            step=1,
            key="savings-months",
        )
        saved = st.number_input(
            "현재 저축 금액 (₩)",
            min_value=0,
            value=int(goal.get("saved", 0)),
            step=50000,
            key="savings-saved",
        )
        start_date = st.date_input(
            "목표 시작일",
            value=date.fromisoformat(goal.get("start_date", date.today().isoformat())),
            max_value=date.today(),
            key="savings-start",
        )
        submitted = st.form_submit_button("저축 목표 저장", type="primary")
    if submitted:
        updated = deepcopy(data)
        updated["savings_goal"] = {
            "name": goal_name.strip(),
            "target": int(target),
            "months": int(months),
            "saved": int(saved),
            "start_date": start_date.isoformat(),
        }
        commit_data(updated)
        st.success("저축 목표를 저장했어요.")
        st.rerun()

    target = int(goal.get("target", 0))
    saved = int(goal.get("saved", 0))
    remaining = max(0, target - saved)
    progress = min(saved / target, 1.0) if target else 0.0
    st.subheader(goal.get("name") or "목표 진행 상황")
    st.progress(progress, text=f"목표 달성률 {progress:.0%}")
    first, second, third = st.columns(3)
    first.metric("목표 금액", won(target))
    second.metric("현재 저축액", won(saved))
    third.metric("남은 목표 금액", won(remaining))

    month = month_key(date.today())
    months_with_income = [
        key for key in recent_month_keys(month, 3) if key in data["incomes"]
    ]
    if months_with_income:
        monthly_capacity = sum(
            int(data["incomes"][key]) - total_expense(month_expenses(data, key))
            for key in months_with_income
        ) / len(months_with_income)
    else:
        monthly_capacity = total_income(data, month) - total_expense(month_expenses(data, month))
    monthly_capacity = max(0, monthly_capacity)
    required_per_month = remaining / max(1, int(goal.get("months", 12)))
    st.metric("최근 소비 기준 월 저축 가능액", won(monthly_capacity))
    st.metric("목표 기간 내 필요한 월 저축액", won(required_per_month))
    if target <= 0:
        st.info("목표 금액을 설정하면 예상 달성 기간을 계산해 드릴게요.")
    elif remaining == 0:
        st.success("목표 저축 금액을 달성했어요!")
    elif monthly_capacity <= 0:
        st.warning("저축 가능액을 계산하기 어려워요. 월간 수입을 등록하고 지출을 관리해 보세요.")
    else:
        estimated_months = ceil(remaining / monthly_capacity)
        estimated_date = date.today() + timedelta(days=estimated_months * 30)
        st.success(
            f"최근 소비 흐름을 유지하면 약 **{estimated_months}개월** 후 "
            f"({estimated_date:%Y년 %m월}) 목표에 도달할 수 있어요."
        )
        if monthly_capacity < required_per_month:
            st.warning("현재 저축 가능액은 목표 기간 달성에 필요한 월 저축액보다 적어요.")


def render_recommendations(data: dict[str, Any]) -> None:
    st.title("맞춤형 소비 개선 제안")
    st.caption("최근 소비 내역, 설정한 예산과 소비 성향을 바탕으로 제안해요.")
    month = select_month("분석할 월")
    expenses = month_expenses(data, month)
    spent = total_expense(expenses)
    totals = category_totals(expenses)
    budget = current_budget(data, month)
    summary = behavior_summary(expenses, budget_limit=budget["total"])

    if not expenses:
        st.info("소비 내역을 등록하면 맞춤 제안을 확인할 수 있어요.")
        return

    optional = sum(
        int(item["amount"]) for item in expenses if item.get("purpose") == "선택 지출"
    )
    budget_saving = (
        max(0, spent - budget["total"])
        if budget["total"] > 0
        else 0
    )
    if not budget_saving:
        budget_saving = int(optional * 0.1)
    st.metric("기록 기반 절약 목표액", won(budget_saving))
    st.subheader(f"소비 성향 진단: {summary['type']}")
    st.caption(summary["description"])
    recommendations = personalized_recommendations(data, month)
    for index, recommendation in enumerate(recommendations, start=1):
        st.markdown(f"**{index}.** {recommendation}")


def main() -> None:
    data = st.session_state.get("finance_data")
    session_version = st.session_state.get("finance_data_version")
    required_keys = {
        "expenses",
        "income_records",
        "incomes",
        "categories",
        "budgets",
        "savings_goal",
    }
    if (
        not isinstance(data, dict)
        or not required_keys.issubset(data)
        or session_version != 2
    ):
        try:
            data = load_data()
            st.session_state["finance_data"] = data
            st.session_state["finance_data_version"] = 2
        except ValueError as error:
            st.error(str(error))
            st.stop()
    st.sidebar.title("🌿 소소")
    st.sidebar.caption("나를 위한 스마트 소비 관리")
    page = st.sidebar.radio(
        "메뉴",
        [
            "대시보드",
            "내역 입력 및 관리",
            "예산 및 저축 관리",
            "소비 분석 및 리포트",
        ],
        label_visibility="collapsed",
    )
    st.sidebar.divider()
    st.sidebar.caption("입력한 데이터는 이 Codespace의 로컬 SQLite 데이터베이스에 저장됩니다.")
    if page == "대시보드":
        render_dashboard(data)
    elif page == "내역 입력 및 관리":
        render_records(data)
    elif page == "예산 및 저축 관리":
        render_budget(data)
    else:
        render_analysis(data)


main()
