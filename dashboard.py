import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import os

st.set_page_config(page_title="Dashboard Billing Incentivo", layout="wide", page_icon="☁️")

st.title("📊 Visão Geral - Billing Incentivo")
st.markdown("Acompanhamento histórico de consumo de recursos dos clientes")

# Emails that should NEVER appear in the metrics
EXCLUDED_EMAILS = ["apresentacao@saveincloud.com"]

# Function to conn DB and load the infos
@st.cache_data(ttl=600)
def load_data():
    # Ensures the 'data' directory exists for the Docker volume
    os.makedirs('data', exist_ok=True)
    
    conn = sqlite3.connect('data/billing_history.db')
    
    # Auto-creates the table so Pandas doesn't crash on an empty DB
    conn.execute('''
        CREATE TABLE IF NOT EXISTS daily_billing (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            uid INTEGER,
            email TEXT,
            consumption REAL
        )
    ''')
    conn.commit()
    
    df = pd.read_sql_query("SELECT * FROM daily_billing", conn)
    conn.close()

    if not df.empty:
        # Convert 'date' column to datetime for better handling
        df['date'] = pd.to_datetime(df['date'])
        
        # Creates the Year-Month column safely at load time
        df['year_month'] = df['date'].dt.to_period('M').astype(str)
        
        # Filter out the excluded emails directly at load time
        df = df[~df['email'].isin(EXCLUDED_EMAILS)]

    return df

df = load_data()

if df.empty:
    st.warning("Nenhum dado de consumo encontrado. O relatório diário ainda não foi processado.")
else:
    # Sidebar filters
    st.sidebar.header("Filtros")
    
    # Get the most recent date registered in the database
    recent_date = df['date'].max()
    
    # Define "active" clients as those with records in the last 3 days
    active_emails = df[df['date'] >= (recent_date - pd.Timedelta(days=3))]['email'].unique()
    
    # Add checkbox to toggle view
    show_only_active = st.sidebar.checkbox("Ocultar clientes inativos", value=True)
    
    if show_only_active:
        clients_list = active_emails
    else:
        clients_list = df['email'].unique()

    # Apply the list to the selectbox
    selected_client = st.sidebar.selectbox("Filtrar por Cliente:", ["Todos"] + list(clients_list))

    # Apply client filter
    if selected_client != "Todos":
        filtered_df = df[df['email'] == selected_client]
    else:
        filtered_df = df

    # Fast Metrics
    col1, col2, col3, col4 = st.columns(4)

    filtered_recent_date = filtered_df['date'].max()
    last_day_consumption = filtered_df[filtered_df['date'] == filtered_recent_date]['consumption'].sum()
    all_period_consumption = filtered_df['consumption'].sum()
    current_active_count = len(active_emails)

    col1.metric("Data da Última Atualização", filtered_recent_date.strftime("%d/%m/%Y"))
    col2.metric("Consumo do Último Dia", f"R$ {last_day_consumption:.2f}")
    col3.metric("Consumo Total do Período", f"R$ {all_period_consumption:.2f}")
    col4.metric("Clientes Ativos (Atualmente)", current_active_count)

    st.divider()

    # --- UI TABS CONFIGURATION ---
    tab_overview, tab_monthly = st.tabs(["📊 Visão Geral", "📅 Análise Mensal"])

    # ==========================================
    # TAB 1: DAILY OVERVIEW
    # ==========================================
    with tab_overview:
        graph_col1, graph_col2 = st.columns([2, 1])

        with graph_col1:
            st.subheader("📈 Tendência de Consumo Diário")
            daily_consumption = filtered_df.groupby('date')['consumption'].sum().reset_index()
            
            line_fig = px.line(
                daily_consumption, 
                x='date', 
                y='consumption', 
                markers=True,
                labels={'date': 'Data', 'consumption': 'Consumo (R$)'}
            )
            line_fig.update_traces(line_color='#0056b3')
            st.plotly_chart(line_fig, use_container_width=True, key="overview_line_chart")

        with graph_col2:
            if selected_client == "Todos":
                st.subheader("🏆 Maiores Consumidores (Total Histórico)")
                top_consumers = df.groupby('email')['consumption'].sum().sort_values(ascending=False).head(10).reset_index()
                
                bar_fig = px.bar(
                    top_consumers, 
                    y='email', 
                    x='consumption', 
                    orientation='h',
                    labels={'email': '', 'consumption': 'R$'}
                )
                bar_fig.update_layout(yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(bar_fig, use_container_width=True, key="overview_bar_chart")
                
            else:
                st.subheader("Detalhamento do Cliente")
                st.dataframe(
                    filtered_df[['date', 'consumption']].sort_values(by='date', ascending=False),
                    use_container_width=True,
                    hide_index=True
                )

    # ==========================================
    # TAB 2: MONTHLY/PERIOD ANALYSIS
    # ==========================================
    with tab_monthly:
        st.subheader("Filtro de Período")
        
        # Get unique months available in the DB for the dropdown
        available_months = sorted(df['year_month'].unique(), reverse=True)
        selected_month = st.selectbox("Selecione o Mês para Análise:", available_months)
        
        # Filter the dataframe for the selected month
        month_df = filtered_df[filtered_df['year_month'] == selected_month]
        
        # Month specific metrics
        month_total_cost = month_df['consumption'].sum()
        month_unique_clients = month_df['email'].nunique()
        
        m_col1, m_col2 = st.columns(2)
        m_col1.metric(f"Custo Total em {selected_month}", f"R$ {month_total_cost:.2f}")
        m_col2.metric(f"Clientes Únicos em {selected_month}", month_unique_clients)
        
        st.divider()
        
        m_graph_col1, m_graph_col2 = st.columns([2, 1])
        
        with m_graph_col1:
            st.markdown(f"**Curva de Consumo ({selected_month})**")
            month_daily_trend = month_df.groupby('date')['consumption'].sum().reset_index()
            
            month_line_fig = px.line(
                month_daily_trend, 
                x='date', 
                y='consumption', 
                markers=True,
                labels={'date': 'Data', 'consumption': 'Consumo (R$)'}
            )
            # Using a different color (Green) to differentiate from the overview tab
            month_line_fig.update_traces(line_color='#28a745')
            st.plotly_chart(month_line_fig, use_container_width=True, key="monthly_line_chart")
            
        with m_graph_col2:
            st.markdown(f"**Top Consumidores ({selected_month})**")
            month_top_consumers = month_df.groupby('email')['consumption'].sum().sort_values(ascending=False).head(10).reset_index()
            
            month_bar_fig = px.bar(
                month_top_consumers, 
                y='email', 
                x='consumption', 
                orientation='h',
                labels={'email': '', 'consumption': 'R$'}
            )
            month_bar_fig.update_layout(yaxis={'categoryorder':'total ascending'})
            st.plotly_chart(month_bar_fig, use_container_width=True, key="monthly_bar_chart")

        # Historical Monthly Active Clients Chart
        st.divider()
        st.subheader("👥 Histórico Geral de Clientes Ativos por Mês")
        
        monthly_active = filtered_df.groupby('year_month')['email'].nunique().reset_index()
        monthly_active.columns = ['Mês', 'Clientes Ativos']
        
        monthly_fig = px.bar(
            monthly_active,
            x='Mês',
            y='Clientes Ativos',
            text='Clientes Ativos', 
            labels={'Mês': 'Mês', 'Clientes Ativos': 'Quantidade de Clientes'}
        )
        
        monthly_fig.update_traces(textposition='outside', marker_color='#17a2b8')
        monthly_fig.update_layout(yaxis=dict(tickformat="d"))
        
        st.plotly_chart(monthly_fig, use_container_width=True, key="historical_active_chart")