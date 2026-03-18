from collections import OrderedDict

import plotly.graph_objects as go
import streamlit as st

from components import show_address_confirmation_card
from db import fetch_all, fetch_one
from platforms import platform_label
from ui import apply_ui_theme


st.set_page_config(page_title="Application Dashboard", page_icon="📊", layout="wide")
apply_ui_theme()
st.title("📊 Application Dashboard")
st.session_state["current_page"] = "application_dashboard"

with st.sidebar:
    show_address_confirmation_card()


PLOT_THEME = "plotly_dark"
STAGE_COLORS = OrderedDict(
    [
        ("applied", "#4A90D9"),
        ("interview", "#F5A623"),
        ("offer", "#7ED321"),
        ("rejected", "#D0021B"),
        ("closed", "#9B9B9B"),
    ]
)


def _transparent_layout(fig):
    fig.update_layout(
        template=PLOT_THEME,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


status_rows = fetch_all(
    """
    SELECT status, COUNT(*) AS count
    FROM applications
    GROUP BY status
    """
)
status_counts = {row["status"]: row["count"] for row in status_rows}
funnel_values = [status_counts.get(stage, 0) for stage in STAGE_COLORS]

funnel_fig = go.Figure(
    go.Funnel(
        y=[stage.title() for stage in STAGE_COLORS.keys()],
        x=funnel_values,
        textinfo="value+percent initial",
        marker={"color": list(STAGE_COLORS.values())},
    )
)
annotations = []
for index in range(len(funnel_values) - 1):
    start = funnel_values[index]
    end = funnel_values[index + 1]
    rate = round((end / start) * 100, 1) if start else 0
    annotations.append(
        {
            "x": max(funnel_values) * 0.75 if funnel_values else 0,
            "y": index + 0.45,
            "xref": "x",
            "yref": "y",
            "text": f"{list(STAGE_COLORS.keys())[index].title()} -> {list(STAGE_COLORS.keys())[index + 1].title()}: {rate}%",
            "showarrow": False,
            "font": {"size": 12},
        }
    )
funnel_fig.update_layout(annotations=annotations, margin={"l": 10, "r": 10, "t": 30, "b": 10})
_transparent_layout(funnel_fig)

score_rows = fetch_all(
    """
    SELECT
        CASE
            WHEN LEAST(GREATEST(score, 0), 100) < 60 THEN '<60'
            WHEN LEAST(GREATEST(score, 0), 100) BETWEEN 60 AND 69 THEN '60-69'
            WHEN LEAST(GREATEST(score, 0), 100) BETWEEN 70 AND 79 THEN '70-79'
            WHEN LEAST(GREATEST(score, 0), 100) BETWEEN 80 AND 89 THEN '80-89'
            ELSE '90-100'
        END AS bucket,
        COUNT(*) AS count
    FROM cover_letters
    GROUP BY bucket
    """
)
bucket_order = ["<60", "60-69", "70-79", "80-89", "90-100"]
bucket_counts = {row["bucket"]: row["count"] for row in score_rows}
score_fig = go.Figure(
    go.Bar(
        x=bucket_order,
        y=[bucket_counts.get(bucket, 0) for bucket in bucket_order],
        marker_color="#4A90D9",
    )
)
score_fig.update_layout(title="Cover Letter Score Distribution", margin={"l": 10, "r": 10, "t": 40, "b": 10})
_transparent_layout(score_fig)

timeline_rows = fetch_all(
    """
    SELECT DATE_TRUNC('week', created_at) AS week, COUNT(*) AS count
    FROM applications
    WHERE created_at >= NOW() - INTERVAL '12 weeks'
    GROUP BY week
    ORDER BY week
    """
)
timeline_fig = go.Figure(
    go.Scatter(
        x=[row["week"] for row in timeline_rows],
        y=[row["count"] for row in timeline_rows],
        mode="lines+markers",
        line={"color": "#7ED321", "width": 3},
        marker={"size": 8},
    )
)
timeline_fig.update_layout(title="Applications Submitted per Week", margin={"l": 10, "r": 10, "t": 40, "b": 10})
_transparent_layout(timeline_fig)

platform_rows = fetch_all(
    """
    SELECT COALESCE(NULLIF(platform, ''), 'other') AS platform_name, COUNT(*) AS count
    FROM applications
    GROUP BY platform_name
    ORDER BY count DESC
    """
)
platform_fig = go.Figure(
    go.Pie(
        labels=[platform_label(row["platform_name"]) for row in platform_rows],
        values=[row["count"] for row in platform_rows],
        hole=0.35,
    )
)
platform_fig.update_layout(title="Platform Breakdown", margin={"l": 10, "r": 10, "t": 40, "b": 10})
_transparent_layout(platform_fig)

total_applications_row = fetch_one("SELECT COUNT(*) AS value FROM applications")
interview_rate_row = fetch_one(
    """
    SELECT
        CASE WHEN COUNT(*) = 0 THEN 0
             ELSE ROUND(
                (SUM(CASE WHEN status IN ('interview', 'offer') THEN 1 ELSE 0 END)::numeric / COUNT(*)) * 100,
                1
             )
        END AS value
    FROM applications
    """
)
average_score_row = fetch_one("SELECT ROUND(AVG(match_score)::numeric, 1) AS value FROM jobs")
open_applications_row = fetch_one("SELECT COUNT(*) AS value FROM applications WHERE status = 'applied'")

kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)
kpi_col1.metric("Total Applications", total_applications_row["value"] if total_applications_row else 0)
kpi_col2.metric("Interview Rate", f"{interview_rate_row['value'] if interview_rate_row else 0}%")
kpi_col3.metric("Average Match Score", average_score_row["value"] if average_score_row and average_score_row["value"] else 0)
kpi_col4.metric("Open Applications", open_applications_row["value"] if open_applications_row else 0)

top_left, top_right = st.columns(2)
with top_left:
    st.subheader("Funnel")
    st.plotly_chart(funnel_fig, use_container_width=True)
with top_right:
    st.subheader("Score Distribution")
    st.plotly_chart(score_fig, use_container_width=True)

bottom_left, bottom_right = st.columns(2)
with bottom_left:
    st.subheader("Activity Timeline")
    st.plotly_chart(timeline_fig, use_container_width=True)
with bottom_right:
    st.subheader("Platform Breakdown")
    st.plotly_chart(platform_fig, use_container_width=True)
