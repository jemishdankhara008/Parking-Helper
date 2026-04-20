from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTING_DIR = PROJECT_ROOT / "data" / "reporting"


def _get_history_lots() -> list[str]:
    if not REPORTING_DIR.exists():
        return []
    return sorted(f.stem.replace("_history", "") for f in REPORTING_DIR.glob("*_history.csv"))


def page_analytics() -> None:
    st.header("Analytics")
    st.caption("Historical occupancy trends and lot utilization insights.")

    lots = _get_history_lots()
    if not lots:
        st.markdown(
            """
        <div style="background:#1A1D27;border:1px solid #2A2D3A;border-radius:14px;
                    padding:48px;text-align:center;">
            <div style="font-size:18px;font-weight:600;color:#F0F0F5;margin-bottom:8px;">
                No Historical Data Available</div>
            <div style="font-size:14px;color:#8B8FA3;">
                Run the detection engine to start collecting analytics.</div>
        </div>""",
            unsafe_allow_html=True,
        )
        return

    lot_dfs: dict[str, pd.DataFrame] = {}
    lot_capacities: dict[str, int] = {}

    for lot in lots:
        csv_path = REPORTING_DIR / f"{lot}_history.csv"
        try:
            df = pd.read_csv(csv_path)
        except Exception:
            continue
        if df.empty or "Timestamp" not in df.columns:
            continue
        spot_cols = [c for c in df.columns if c.startswith("SP")]
        if not spot_cols:
            continue

        df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
        df = df.dropna(subset=["Timestamp"]).sort_values("Timestamp")
        # History rows store spot-level strings, so analytics are rebuilt by counting occupied markers across SP* columns.
        df["Occupied"] = df[spot_cols].apply(lambda r: (r == "occupied").sum(), axis=1)
        df["Available"] = df[spot_cols].apply(lambda r: (r == "available").sum(), axis=1)
        df["Pct"] = df["Occupied"] / len(spot_cols) * 100
        df["Hour"] = df["Timestamp"].dt.hour
        df["Lot"] = lot
        cap = len(spot_cols)

        if cap < 5 and df["Occupied"].mean() == 0:
            continue

        lot_dfs[lot] = df
        lot_capacities[lot] = cap

    if not lot_dfs:
        st.warning("History files found but could not be parsed.")
        return

    def kpi_card(label: str, value: str, sub: str = "", color: str = "#FF3B3B") -> str:
        return f"""
        <div style="background:#1A1D27;border:1px solid #2A2D3A;border-radius:12px;
                    padding:20px 16px;text-align:center;">
            <div style="font-size:12px;color:#8B8FA3;text-transform:uppercase;
                        letter-spacing:0.8px;margin-bottom:6px;">{label}</div>
            <div style="font-size:26px;font-weight:700;color:{color};">{value}</div>
            <div style="font-size:12px;color:#8B8FA3;margin-top:4px;">{sub}</div>
        </div>"""

    st.markdown("### Fleet Summary")
    total_capacity = sum(lot_capacities.values())
    all_df = pd.concat(lot_dfs.values(), ignore_index=True)
    fleet_avg_pct = all_df.groupby("Timestamp")["Occupied"].sum().mean() / total_capacity * 100
    busiest_lot = max(lot_dfs, key=lambda l: lot_dfs[l]["Pct"].mean())
    peak_hour_global = all_df.groupby("Hour")["Occupied"].mean().idxmax()

    cols = st.columns(4)
    metrics = [
        ("Total Capacity", f"{total_capacity} spots", f"Across {len(lot_dfs)} lots", "#4FC3F7"),
        ("Fleet Avg Occ.", f"{fleet_avg_pct:.1f}%", "All lots combined", "#FF3B3B"),
        ("Busiest Lot", busiest_lot, f"{lot_dfs[busiest_lot]['Pct'].mean():.1f}% avg", "#FF9800"),
        ("Peak Hour (Fleet)", f"{peak_hour_global:02d}:00", "Highest avg demand", "#66BB6A"),
    ]
    for col, (lbl, val, sub, clr) in zip(cols, metrics):
        col.markdown(kpi_card(lbl, val, sub, clr), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    tab1, tab2, tab3 = st.tabs(["Occupancy Over Time", "Lot Comparison", "Hourly Heatmap"])

    with tab1:
        st.markdown("##### Occupancy % over time, one card per lot")
        lot_list = list(lot_dfs.keys())

        for i in range(0, len(lot_list), 2):
            row_cols = st.columns(2)
            for j, lot in enumerate(lot_list[i : i + 2]):
                df = lot_dfs[lot]
                capacity = lot_capacities[lot]
                avg_pct = df["Pct"].mean()
                peak_pct = df["Pct"].max()

                pct_series = df["Pct"]
                first_nonzero = pct_series[pct_series > 0].index.min()
                last_nonzero = pct_series[pct_series > 0].index.max()
                # Trim the idle zero-only edges so the chart scale reacts to actual occupancy changes, not startup gaps.
                trimmed = pct_series.loc[first_nonzero:last_nonzero] if pd.notna(first_nonzero) and pd.notna(last_nonzero) else pct_series
                y_min = max(0, trimmed.min() - 5)
                y_max = min(100, trimmed.max() + 5)

                with row_cols[j]:
                    st.markdown(
                        f"""
                    <div style="background:#1A1D27;border:1px solid #2A2D3A;border-radius:10px;
                                padding:12px 16px;margin-bottom:8px;display:flex;
                                justify-content:space-between;align-items:center;">
                        <div>
                            <span style="font-size:15px;font-weight:700;color:#F0F0F5;">{lot}</span>
                            <span style="font-size:12px;color:#8B8FA3;margin-left:8px;">{capacity} spots</span>
                        </div>
                        <div style="display:flex;gap:20px;">
                            <div style="text-align:right;">
                                <div style="font-size:11px;color:#8B8FA3;">Avg</div>
                                <div style="font-size:16px;font-weight:700;color:#FF9800;">{avg_pct:.1f}%</div>
                            </div>
                            <div style="text-align:right;">
                                <div style="font-size:11px;color:#8B8FA3;">Peak</div>
                                <div style="font-size:16px;font-weight:700;color:#FF3B3B;">{peak_pct:.1f}%</div>
                            </div>
                        </div>
                    </div>""",
                        unsafe_allow_html=True,
                    )

                    chart_df = df[["Timestamp", "Pct", "Occupied", "Available"]].rename(
                        columns={"Timestamp": "time", "Pct": "pct", "Occupied": "occupied", "Available": "available"}
                    )
                    chart_df = chart_df[chart_df["pct"] > 0].reset_index(drop=True)
                    if chart_df.empty:
                        st.info("No occupancy changes recorded yet for this lot.")
                        continue

                    threshold_df = pd.DataFrame({"time": [chart_df["time"].min(), chart_df["time"].max()], "pct": [80, 80]})
                    base = alt.Chart(chart_df)

                    area = base.mark_area(color="#FF3B3B", opacity=0.15, interpolate="monotone", clip=True).encode(
                        x=alt.X("time:T", title=None, axis=alt.Axis(gridColor="#2A2D3A", labelColor="#8B8FA3", format="%H:%M")),
                        y=alt.Y("pct:Q", title="Occupancy %", scale=alt.Scale(domain=[y_min, y_max], clamp=True), axis=alt.Axis(gridColor="#2A2D3A", labelColor="#8B8FA3", titleColor="#8B8FA3")),
                        y2=alt.Y2(datum=y_min),
                        tooltip=[
                            alt.Tooltip("time:T", title="Time", format="%Y-%m-%d %H:%M"),
                            alt.Tooltip("pct:Q", title="Occ %", format=".1f"),
                            alt.Tooltip("occupied:Q", title="Occupied"),
                            alt.Tooltip("available:Q", title="Available"),
                        ],
                    )
                    line = base.mark_line(color="#FF3B3B", strokeWidth=2, interpolate="monotone").encode(
                        x="time:T",
                        y=alt.Y("pct:Q", scale=alt.Scale(domain=[y_min, y_max], clamp=True)),
                        tooltip=[
                            alt.Tooltip("time:T", title="Time", format="%Y-%m-%d %H:%M"),
                            alt.Tooltip("pct:Q", title="Occ %", format=".1f"),
                            alt.Tooltip("occupied:Q", title="Occupied"),
                            alt.Tooltip("available:Q", title="Available"),
                        ],
                    )
                    thresh = alt.Chart(threshold_df).mark_line(color="#FF9800", strokeDash=[6, 3], strokeWidth=1).encode(x="time:T", y="pct:Q")

                    chart = (area + line + thresh).properties(height=220).configure_view(strokeWidth=0).configure_axis(labelFontSize=11)
                    st.altair_chart(chart, use_container_width=True)

                    spot_stats = []
                    for sp in [c for c in df.columns if c.startswith("SP")]:
                        occ_rate = (df[sp] == "occupied").mean() * 100
                        spot_stats.append({"Spot": sp, "Occ Rate %": round(occ_rate, 1)})

                    if spot_stats:
                        spot_df = pd.DataFrame(spot_stats).sort_values("Occ Rate %", ascending=False)
                        spot_bar = (
                            alt.Chart(spot_df)
                            .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                            .encode(
                                x=alt.X("Spot:N", title=None, sort="-y", axis=alt.Axis(labelColor="#8B8FA3", labelAngle=-45, gridColor="#2A2D3A")),
                                y=alt.Y("Occ Rate %:Q", title="Occ Rate %", scale=alt.Scale(domain=[0, 100]), axis=alt.Axis(gridColor="#2A2D3A", labelColor="#8B8FA3", titleColor="#8B8FA3")),
                                color=alt.Color("Occ Rate %:Q", scale=alt.Scale(domain=[0, 50, 80, 100], range=["#4FC3F7", "#66BB6A", "#FF9800", "#FF3B3B"]), legend=None),
                                tooltip=["Spot:N", alt.Tooltip("Occ Rate %:Q", format=".1f")],
                            )
                            .properties(height=140, title=alt.TitleParams(text="Individual Spot Occupancy Rate", color="#8B8FA3", fontSize=12))
                            .configure_view(strokeWidth=0)
                        )
                        st.altair_chart(spot_bar, use_container_width=True)

        st.markdown('<span style="font-size:11px;color:#8B8FA3;">Dashed line = 80% capacity threshold</span>', unsafe_allow_html=True)

    with tab2:
        st.markdown("##### Average vs peak occupancy per lot")
        summary_rows = []
        for lot, df in lot_dfs.items():
            summary_rows.append({"Lot": lot, "metric": "Average", "occupied": df["Pct"].mean()})
            summary_rows.append({"Lot": lot, "metric": "Peak", "occupied": df["Pct"].max()})
        summary_df = pd.DataFrame(summary_rows)

        grouped_bar = (
            alt.Chart(summary_df)
            .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
            .encode(
                x=alt.X("Lot:N", title="Parking Lot", axis=alt.Axis(labelColor="#8B8FA3", titleColor="#8B8FA3", gridColor="#2A2D3A")),
                y=alt.Y("occupied:Q", title="Occupancy %", scale=alt.Scale(domain=[0, 100]), axis=alt.Axis(gridColor="#2A2D3A", labelColor="#8B8FA3", titleColor="#8B8FA3")),
                color=alt.Color("metric:N", scale=alt.Scale(domain=["Average", "Peak"], range=["#4FC3F7", "#FF3B3B"]), legend=alt.Legend(labelColor="#8B8FA3", titleColor="#8B8FA3", orient="top-right")),
                xOffset="metric:N",
                tooltip=["Lot:N", "metric:N", alt.Tooltip("occupied:Q", title="Occupancy %", format=".1f")],
            )
            .properties(height=320)
            .configure_view(strokeWidth=0)
        )
        st.altair_chart(grouped_bar, use_container_width=True)

        table_rows = []
        for lot, df in lot_dfs.items():
            peak_h = df.groupby("Hour")["Occupied"].mean().idxmax()
            table_rows.append(
                {
                    "Lot": lot,
                    "Capacity": lot_capacities[lot],
                    "Avg Occupancy": f"{df['Pct'].mean():.1f}%",
                    "Peak Occ.": f"{df['Pct'].max():.1f}%",
                    "Peak Hour": f"{peak_h:02d}:00",
                    "Total Readings": len(df),
                }
            )
        st.markdown("##### Utilisation summary table")
        st.dataframe(pd.DataFrame(table_rows).set_index("Lot"), use_container_width=True)

    with tab3:
        st.markdown("##### Average occupancy % by lot and hour of day")
        all_hours = pd.DataFrame({"Hour": range(24)})
        heat_rows = []
        for lot, df in lot_dfs.items():
            hourly = df.groupby("Hour")["Pct"].mean().reset_index()
            hourly = all_hours.merge(hourly, on="Hour", how="left").fillna(0)
            hourly["Lot"] = lot
            heat_rows.append(hourly)

        heat_df = pd.concat(heat_rows, ignore_index=True)
        heat_df["HourLabel"] = heat_df["Hour"].apply(lambda h: f"{h:02d}:00")
        heatmap = (
            alt.Chart(heat_df)
            .mark_rect(cornerRadius=2)
            .encode(
                x=alt.X("HourLabel:O", title="Hour of Day", sort=[f"{h:02d}:00" for h in range(24)], axis=alt.Axis(labelColor="#8B8FA3", titleColor="#8B8FA3", labelAngle=-45)),
                y=alt.Y("Lot:N", title="Parking Lot", axis=alt.Axis(labelColor="#8B8FA3", titleColor="#8B8FA3")),
                color=alt.Color("Pct:Q", title="Avg Occ %", scale=alt.Scale(domain=[0, 50, 80, 100], range=["#1A1D27", "#4FC3F7", "#FF9800", "#FF3B3B"]), legend=alt.Legend(labelColor="#8B8FA3", titleColor="#8B8FA3")),
                tooltip=["Lot:N", alt.Tooltip("HourLabel:O", title="Hour"), alt.Tooltip("Pct:Q", title="Avg Occ %", format=".1f")],
            )
            .properties(height=180)
            .configure_view(strokeWidth=0)
        )
        st.altair_chart(heatmap, use_container_width=True)
        st.markdown('<span style="font-size:11px;color:#8B8FA3;">No data -> Low -> Busy -> Full</span>', unsafe_allow_html=True)
