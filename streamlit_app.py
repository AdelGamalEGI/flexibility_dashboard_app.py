# Streamlit structure setup for integrated flexibility market dashboard
# Tabs: Consumer, Aggregator, Utility (scenario-driven)

import streamlit as st
import json
import pandas as pd

# Load defaults
with open("flexibility_model_defaults_be.json") as f:
    defaults = json.load(f)

# Global state - shared inputs
st.set_page_config(page_title="Flexibility Market Simulator", layout="wide")
st.title("🇧🇪 Flexibility Market Simulator - Belgium")
st.sidebar.header("Global Parameters")

households = st.sidebar.number_input("Total Households", value=defaults['consumer']['households'])
penetration = st.sidebar.slider("Penetration Rate (%)", 0.0, 1.0, value=defaults['consumer']['penetration_rate'])
aggr_present = st.sidebar.checkbox("Aggregator Present?", value=True)

# Calculate shared parameters across all tabs
participating_households = int(households * penetration)
loads_per_household = defaults['consumer']['loads_per_household']
total_devices = participating_households * loads_per_household

# Calculate total flexibility globally before tabs
flexibility_total_kW = sum(
    params['flexibility_kW'] * params['availability_factor'] * (total_devices // len(defaults['consumer']['devices']))
    for params in defaults['consumer']['devices'].values()
)

# Tab structure
tabs = st.tabs(["👥 Consumer", "🏢 Aggregator" if aggr_present else "🏢 (Aggregator Skipped)", "⚡ Utility"])

# --- Consumer Tab ---
with tabs[0]:
    st.header("👥 Consumer Flexibility Model")
    st.subheader(f"Participating Households: {participating_households:,}")

    flexibility_total_kW = 0

    for device, params in defaults['consumer']['devices'].items():
        st.markdown(f"### {device}")

        device_count = total_devices // len(defaults['consumer']['devices'])
        flex_kW = params['flexibility_kW'] * params['availability_factor'] * device_count
        capex = device_count * params['CAPEX']
        savings = device_count * params['annual_energy_savings']
        annual_rev = flex_kW * params['annual_revenue_per_kW']
        degr_cost = device_count * params['degradation_cost_per_year']
        net_cash = annual_rev + savings - degr_cost

        discount_rate = defaults['consumer']['cost_of_capital']
        lifetime = params['lifetime_years']
        discounted_cashflows = sum([
            net_cash / (1 + discount_rate) ** t for t in range(1, lifetime + 1)
        ])
        npv = discounted_cashflows - capex

        revenue_per_device = annual_rev / device_count if device_count else 0
        npv_per_device = npv / device_count if device_count else 0

        flexibility_total_kW += flex_kW

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("# Devices", f"{device_count:,}")
        col2.metric("Flexibility (MW)", round(flex_kW / 1000, 2))
        col3.metric("Revenue/Device (€)", round(revenue_per_device, 2))
        col4.metric("NPV per Device (€)", round(npv_per_device, 2))

    st.success(f"**Total Flexibility Offered**: {round(flexibility_total_kW / 1000, 2)} MW")

# --- Aggregator Tab ---
with tabs[1]:
    if aggr_present:
        st.header("🏢 Aggregator Model")
        st.write("Aggregator tab is running...")
        loads = loads_per_household
        kW_per_load = defaults['aggregator']['flexibility_kW_per_load']
        revenue_kW = defaults['aggregator']['market_price_per_kW_year']

        revenue_total = flexibility_total_kW * revenue_kW
        payout = revenue_total * defaults['aggregator']['consumer_share_percentage']
        retained = revenue_total - payout

        annual_cost = (
            participating_households * defaults['aggregator']['platform_om_cost_per_household_per_year'] +
            flexibility_total_kW * defaults['aggregator']['settlement_admin_cost_per_kW']
        )
        margin = retained - annual_cost

        npv = sum([margin / (1 + defaults['aggregator']['discount_rate']) ** t for t in range(1, defaults['aggregator']['years'] + 1)]) - \
              (participating_households * defaults['aggregator']['customer_acquisition_cost'])

        st.metric("Revenue from Utility (€M/year)", round(revenue_total / 1e6, 2))
        st.metric("Passed to Consumers (€M/year)", round(payout / 1e6, 2))
        st.metric("Annual Gross Margin (€M)", round(margin / 1e6, 2))
        st.metric("NPV (10 yrs, €M)", round(npv / 1e6, 2))
    else:
        st.info("Aggregator not enabled in this scenario.")

# --- Utility Tab ---
with tabs[2]:
    st.header("⚡ Utility Market Pricing Model")
    st.write("Utility tab is running...")

    peak_load_MW = defaults['utility']['peak_system_load_GW'] * 1000
    res_factor = 1 - defaults['utility']['renewables_price_reduction_factor']
    flexibility_total_MW = flexibility_total_kW / 1000

    market_definitions = {
        "Capacity (Fixed/Auctioned)": {
            "percent_of_peak": 0.05,
            "base_price": 45000,
            "type": "fixed",
            "price_unit": "€/MW-year"
        },
        "Demand Response (mFRR)": {
            "percent_of_peak": 0.025,
            "base_price": 120,
            "type": "dynamic",
            "price_unit": "€/MWh-event",
            "avg_events_per_year": 8,
            "avg_duration_hr": 2,
            "min_price": 40,
            "max_price": 180
        },
        "Balancing Energy (aFRR/mFRR)": {
            "percent_of_peak": 0.01,
            "base_price": 85,
            "type": "dynamic",
            "price_unit": "€/MWh-utilized",
            "avg_utilization": 0.2,
            "min_price": 30,
            "max_price": 150
        },
        "Ancillary Services (FCR/aFRR Cap)": {
            "percent_of_peak": 0.008,
            "base_price": 9,
            "type": "dynamic",
            "price_unit": "€/MW-hour",
            "min_price": 5,
            "max_price": 20
        },
        "Wholesale Energy (Reference)": {
            "base_price": 70,
            "price_unit": "€/MWh"
        }
    }

    results = []

    for market, params in market_definitions.items():
        if market == "Wholesale Energy (Reference)":
            adjusted_price = params["base_price"] * res_factor
            required_MW = "-"
        else:
            required_MW = peak_load_MW * params["percent_of_peak"]
            supply_ratio = flexibility_total_MW / required_MW if required_MW > 0 else 0

            if params["type"] == "fixed":
                adjusted_price = params["base_price"]
            else:
                price = params["base_price"] * (1 / supply_ratio) if supply_ratio > 1 else params["base_price"]
                adjusted_price = min(params["max_price"], max(params["min_price"], price))

        if market == "Demand Response (mFRR)":
            total_payment = required_MW * params["avg_events_per_year"] * params["avg_duration_hr"] * adjusted_price / 1e6
        elif market == "Balancing Energy (aFRR/mFRR)":
            total_payment = required_MW * 8760 * params["avg_utilization"] * adjusted_price / 1e6
        elif market == "Ancillary Services (FCR/aFRR Cap)":
            total_payment = required_MW * 8760 * adjusted_price / 1e6
        elif market == "Wholesale Energy (Reference)":
            total_payment = "-"
        else:
            total_payment = required_MW * adjusted_price / 1e6

        results.append({
            "Market": market,
            "Required Flex (MW)": round(required_MW, 2) if isinstance(required_MW, (int, float)) else required_MW,
            "Adjusted Price": round(adjusted_price, 2),
            "Price Unit": params["price_unit"],
            "Total Payment (M€)": round(total_payment, 2) if isinstance(total_payment, (int, float)) else total_payment
        })

    st.dataframe(pd.DataFrame(results), use_container_width=True)
