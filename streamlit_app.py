import os
import io
import csv
import json
import time
import zipfile
import logging
from html import escape
from pathlib import Path
from datetime import datetime, date
import requests
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from PIL import ImageGrab
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

st.set_page_config(
    page_title="Job Market Intelligence",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

API_URL=os.getenv("JOBMARKET_API_URL","http://127.0.0.1:5000/api").rstrip("/")
TIMEOUT=int(os.getenv("JOBMARKET_API_TIMEOUT","20"))
MAX_UPLOAD_MB=100
MAX_UPLOAD_ROWS=500_000

LOG_DIR=Path("logs")
SHOT_DIR=Path("screenshots/streamlit")
ASSET_DIR=Path("assets")

LOG_DIR.mkdir(exist_ok=True)
SHOT_DIR.mkdir(parents=True,exist_ok=True)

DATA_START=date(2023,11,2)
RELIABLE_START=date(2024,2,13)
RELIABLE_END=date(2024,3,23)
PARTIAL_DATE=date(2024,3,24)

METHOD_TEXT="""Job Market Intelligence Platform

Historical coverage:
2 November 2023 to 24 March 2024.

Reliable dense trend window:
13 February 2024 to 23 March 2024.

Partial observation:
24 March 2024 is incomplete and should not be treated as a full comparison day.

Compensation:
Hourly compensation and fixed-price budgets are analysed separately.

Currency:
No reliable currency field exists, so currency normalization is intentionally excluded.

Known source limitations:
No verified remote status, explicit skills, verified experience requirement or company field is available.

Interpretation:
Results represent the supplied historical dataset rather than a live labour-market feed.

Uploaded CSVs:
Files uploaded through CSV Workspace remain separate from validated production model inputs.
"""

logger=logging.getLogger("streamlit_frontend")

if not logger.handlers:
    logger.setLevel(logging.INFO)
    handler=logging.FileHandler(LOG_DIR/"streamlit.log",encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    )
    logger.addHandler(handler)

LOGGER_STATUS="ACTIVE"

defaults={
    "upload_key":0,
    "uploaded_df":None,
    "uploaded_name":None,
    "uploaded_encoding":None,
    "csv_working_df":None,
    "latest_screenshot":None,
    "latest_screenshot_name":None,
    "last_auto_page":None,
    "last_refresh":datetime.now().strftime("%d %b %Y · %H:%M:%S"),
    "api_telemetry":{}
}

for key,value in defaults.items():
    if key not in st.session_state:
        st.session_state[key]=value

PAGES={
    "🏠 Client Summary":"Client Summary",
    "📊 Executive Overview":"Executive Overview",
    "💰 Salary Intelligence":"Salary Intelligence",
    "🚀 Emerging Jobs":"Emerging Jobs",
    "📈 Demand Forecast":"Demand Forecast",
    "🌍 Geographic Intelligence":"Geographic Intelligence",
    "📉 Market Dynamics":"Market Dynamics",
    "🔮 Future Scenarios":"Future Scenarios",
    "🎯 Job Recommender":"Job Recommender",
    "🧠 Model Performance":"Model Performance",
    "📁 CSV Workspace":"CSV Workspace",
    "⚙️ System Diagnostics":"System Diagnostics"
}

PAGE_INFO={
    "Client Summary":"A concise presentation-ready view of the strongest market findings, evidence, risks and recommendations.",
    "Executive Overview":"Decision-ready intelligence covering demand movement, emerging opportunities and geographic activity.",
    "Salary Intelligence":"Analyse hourly and fixed-price compensation independently using distributions, percentiles and ranges.",
    "Emerging Jobs":"Identify categories showing stronger recent demand momentum and relative opportunity.",
    "Demand Forecast":"Generate production demand predictions and inspect forecast evidence visually.",
    "Geographic Intelligence":"Compare market activity through maps, rankings, shares and concentration measures.",
    "Market Dynamics":"Explore historical demand, rolling trends, averages and period-over-period changes.",
    "Future Scenarios":"Compare alternative future market conditions and projected demand outcomes.",
    "Job Recommender":"Generate ranked job recommendations using the production recommendation engine.",
    "Model Performance":"Review model evaluation evidence supporting production selection.",
    "CSV Workspace":"Upload a CSV and explore schema, quality, missingness, outliers, relationships and trends.",
    "System Diagnostics":"Inspect endpoint health, latency, logs, screenshots, exports and system architecture."
}

REMOTE_IMAGES={
    "Client Summary":"https://images.unsplash.com/photo-1556761175-b413da4baf72?auto=format&fit=crop&w=1400&q=85",
    "Executive Overview":"https://images.unsplash.com/photo-1551288049-bebda4e38f71?auto=format&fit=crop&w=1400&q=85",
    "Salary Intelligence":"https://images.unsplash.com/photo-1554224155-8d04cb21cd6c?auto=format&fit=crop&w=1400&q=85",
    "Emerging Jobs":"https://images.unsplash.com/photo-1521737711867-e3b97375f902?auto=format&fit=crop&w=1400&q=85",
    "Demand Forecast":"https://images.unsplash.com/photo-1460925895917-afdab827c52f?auto=format&fit=crop&w=1400&q=85",
    "Geographic Intelligence":"https://images.unsplash.com/photo-1521295121783-8a321d551ad2?auto=format&fit=crop&w=1400&q=85",
    "Market Dynamics":"https://images.unsplash.com/photo-1556761175-b413da4baf72?auto=format&fit=crop&w=1400&q=85",
    "Future Scenarios":"https://images.unsplash.com/photo-1516321318423-f06f85e504b3?auto=format&fit=crop&w=1400&q=85",
    "Job Recommender":"https://images.unsplash.com/photo-1497366754035-f200968a6e72?auto=format&fit=crop&w=1400&q=85",
    "Model Performance":"https://images.unsplash.com/photo-1555949963-aa79dcee981c?auto=format&fit=crop&w=1400&q=85",
    "CSV Workspace":"https://images.unsplash.com/photo-1504868584819-f8e8b4b6d7e3?auto=format&fit=crop&w=1400&q=85",
    "System Diagnostics":"https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1400&q=85"
}

EXPECTED_COLUMNS=[
    "title",
    "link",
    "published_date",
    "is_hourly",
    "hourly_low",
    "hourly_high",
    "budget",
    "country"
]

COUNTRY_MAP={
    "USA":"United States",
    "US":"United States",
    "U.S.":"United States",
    "United States of America":"United States",
    "UK":"United Kingdom",
    "U.K.":"United Kingdom",
    "UAE":"United Arab Emirates",
    "Republic of Korea":"South Korea",
    "Russian Federation":"Russia",
    "Viet Nam":"Vietnam"
}

PALETTE=[
    "#4a4e69",
    "#9a8c98",
    "#c9ada7",
    "#6d6875",
    "#8d99ae",
    "#b8a7b0"
]

PLOT_CONFIG={
    "displaylogo":False,
    "responsive":True,
    "scrollZoom":False,
    "toImageButtonOptions":{
        "format":"png",
        "filename":"job_market_chart",
        "height":900,
        "width":1500,
        "scale":2
    }
}

retry=Retry(
    total=3,
    connect=3,
    read=3,
    backoff_factor=.5,
    status_forcelist=[429,500,502,503,504],
    allowed_methods=["GET","POST"]
)

SESSION=requests.Session()
SESSION.mount("http://",HTTPAdapter(max_retries=retry))
SESSION.mount("https://",HTTPAdapter(max_retries=retry))

def html(content):
    st.html(content.strip())

def asset_image(page):
    slug=page.lower().replace(" ","_")

    for ext in [".jpg",".jpeg",".png",".webp"]:
        path=ASSET_DIR/f"{slug}{ext}"

        if path.exists():
            return str(path)

    return REMOTE_IMAGES[page]

def validate_api_body(body):
    if not isinstance(body,dict):
        raise RuntimeError("API returned an invalid response structure.")

    if "status" not in body:
        raise RuntimeError("API response does not contain a status field.")

    if body.get("status")!="success":
        raise RuntimeError(body.get("error") or "API request failed.")

    return body.get("data")

@st.cache_data(ttl=300,show_spinner=False)
def cached_get(endpoint):
    start=time.perf_counter()

    response=SESSION.get(
        f"{API_URL}/{endpoint.lstrip('/')}",
        timeout=TIMEOUT
    )

    response.raise_for_status()

    latency=round(
        (time.perf_counter()-start)*1000,
        1
    )

    data=validate_api_body(
        response.json()
    )

    return data,latency

def api_get(endpoint):
    try:
        data,latency=cached_get(endpoint)

        st.session_state.api_telemetry[endpoint]={
            "Endpoint":endpoint,
            "Status":"PASS",
            "Latency ms":latency,
            "Checked":datetime.now().strftime("%H:%M:%S")
        }

        return data

    except Exception as exc:
        st.session_state.api_telemetry[endpoint]={
            "Endpoint":endpoint,
            "Status":"FAIL",
            "Latency ms":None,
            "Checked":datetime.now().strftime("%H:%M:%S")
        }

        raise exc

def api_post(endpoint,payload):
    start=time.perf_counter()

    try:
        response=SESSION.post(
            f"{API_URL}/{endpoint.lstrip('/')}",
            json=payload,
            timeout=TIMEOUT
        )

        response.raise_for_status()

        latency=round(
            (time.perf_counter()-start)*1000,
            1
        )

        data=validate_api_body(
            response.json()
        )

        st.session_state.api_telemetry[endpoint]={
            "Endpoint":endpoint,
            "Status":"PASS",
            "Latency ms":latency,
            "Checked":datetime.now().strftime("%H:%M:%S")
        }

        return data

    except Exception as exc:
        st.session_state.api_telemetry[endpoint]={
            "Endpoint":endpoint,
            "Status":"FAIL",
            "Latency ms":None,
            "Checked":datetime.now().strftime("%H:%M:%S")
        }

        raise exc

def frame(data):
    if data is None:
        return pd.DataFrame()

    if isinstance(data,pd.DataFrame):
        return data.copy()

    if isinstance(data,list):
        return pd.DataFrame(data)

    if isinstance(data,dict):
        try:
            return pd.DataFrame(data)

        except:
            try:
                return pd.DataFrame([data])

            except:
                return pd.DataFrame()

    return pd.DataFrame()

def fmt(value):
    if pd.isna(value):
        return "—"

    if isinstance(value,(int,float,np.integer,np.floating)):
        if abs(value)>=1_000_000:
            return f"{value/1_000_000:.2f}M"

        if abs(value)>=1_000:
            return f"{value/1_000:.1f}K"

        if isinstance(value,(float,np.floating)):
            return f"{value:,.2f}"

        return f"{value:,}"

    return str(value)

def pretty(name):
    return str(name).replace("_"," ").title()

def section(title,subtitle=""):
    html(
        f"""
        <div class="section-title">{escape(title)}</div>
        <div class="section-sub">{escape(subtitle)}</div>
        """
    )

def insight(title,text,kind="info"):
    html(
        f"""
        <div class="{kind}">
            <b>{escape(title)}</b><br><br>
            {escape(text)}
        </div>
        """
    )

def empty_state(message):
    html(
        f"""
        <div class="empty">
            <b>No results to display</b><br><br>
            {escape(message)}
        </div>
        """
    )

def table(df,height=420):
    df=frame(df)

    if df.empty:
        empty_state(
            "Try widening the current filters or selecting another metric."
        )
        return df

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=min(
            height,
            max(190,80+35*len(df))
        )
    )

    return df

def download_csv(df,filename,key,label="⬇ Download CSV"):
    if isinstance(df,pd.DataFrame) and not df.empty:
        st.download_button(
            label,
            df.to_csv(index=False).encode("utf-8"),
            filename,
            "text/csv",
            use_container_width=True,
            key=key
        )

def numeric_columns(df):
    return df.select_dtypes(
        include=np.number
    ).columns.tolist()

def categorical_columns(df):
    nums=set(numeric_columns(df))

    return [
        column
        for column in df.columns
        if column not in nums
    ]

def detect_dates(df):
    dates=[]

    for column in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[column]):
            dates.append(column)
            continue

        name=column.lower()

        if any(
            term in name
            for term in [
                "date",
                "time",
                "month",
                "year"
            ]
        ):
            parsed=pd.to_datetime(
                df[column],
                errors="coerce",
                utc=True
            )

            if parsed.notna().mean()>=.5:
                dates.append(column)

    return dates

def style_fig(fig,height=470):
    fig.update_layout(
        template="plotly_white",
        height=height,
        margin=dict(l=25,r=25,t=70,b=40),
        font=dict(
            family="Arial",
            color="#22223b"
        ),
        title=dict(
            font=dict(size=18)
        ),
        hoverlabel=dict(
            font_size=12
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        )
    )

    fig.update_xaxes(
        showgrid=False,
        linecolor="#e7e1df",
        title_font=dict(size=11)
    )

    fig.update_yaxes(
        gridcolor="#eee9e7",
        zeroline=False,
        title_font=dict(size=11)
    )

    return fig

def plot(fig,height=470):
    st.plotly_chart(
        style_fig(fig,height),
        use_container_width=True,
        config=PLOT_CONFIG
    )

    st.caption(
        "Use the camera icon in the chart toolbar to download this visual as a high-resolution PNG."
    )

def metric_cards(data,limit=5):
    if isinstance(data,dict):
        values={
            key:value
            for key,value in data.items()
            if not isinstance(value,(dict,list))
        }

    else:
        df=frame(data)

        values=(
            df.iloc[0].to_dict()
            if not df.empty
            else {}
        )

    values=dict(
        list(values.items())[:limit]
    )

    if not values:
        return

    cols=st.columns(len(values))

    for col,(name,value) in zip(
        cols,
        values.items()
    ):
        with col:
            st.metric(
                pretty(name),
                fmt(value)
            )

def health_score(df):
    if df.empty:
        return 0

    completeness=1-(
        df.isna().sum().sum()/df.size
    )

    duplicate_score=1-(
        df.duplicated().sum()/len(df)
    )

    usable_columns=sum(
        df[column].notna().any()
        for column in df.columns
    )/len(df.columns)

    return round(
        max(
            0,
            min(
                100,
                (
                    completeness*.55+
                    duplicate_score*.25+
                    usable_columns*.20
                )*100
            )
        ),
        1
    )

def profile_cards(df):
    if df.empty:
        return

    memory=(
        df.memory_usage(deep=True).sum()
        /1024/1024
    )

    values=[
        ("Rows",f"{len(df):,}"),
        ("Columns",len(df.columns)),
        ("Missing",f"{int(df.isna().sum().sum()):,}"),
        ("Duplicates",f"{int(df.duplicated().sum()):,}"),
        ("Memory",f"{memory:.2f} MB"),
        ("Health Score",f"{health_score(df)}%")
    ]

    cols=st.columns(6)

    for col,(label,value) in zip(
        cols,
        values
    ):
        with col:
            st.metric(label,value)

def normalize_countries(series):
    return (
        series
        .astype(str)
        .str.strip()
        .replace(COUNTRY_MAP)
    )

def require_fields(df,fields,context):
    missing=[
        field
        for field in fields
        if field not in df.columns
    ]

    if missing:
        st.warning(
            f"{context} cannot be rendered because the API did not return: "
            +", ".join(missing)
        )

        return False

    return True

def reset_filters(prefix):
    for suffix in [
        "keyword",
        "country",
        "comp",
        "dates"
    ]:
        key=f"{prefix}_{suffix}"

        if key in st.session_state:
            del st.session_state[key]

def global_filters(df,key):
    if df.empty:
        return df

    filtered=df.copy()

    dates=detect_dates(filtered)

    countries=[
        column
        for column in filtered.columns
        if "country" in column.lower()
    ]

    titles=[
        column
        for column in filtered.columns
        if "title" in column.lower()
    ]

    with st.expander(
        "🎛 Filters",
        expanded=False
    ):
        c1,c2,c3,c4,c5=st.columns(
            [1.3,1,1,1.5,.7]
        )

        with c1:
            keyword=st.text_input(
                "Keyword",
                placeholder="Job title...",
                key=f"{key}_keyword"
            )

        with c2:
            country=st.text_input(
                "Country",
                placeholder="All",
                key=f"{key}_country"
            )

        with c3:
            compensation=st.selectbox(
                "Compensation",
                ["All","Hourly","Fixed Price"],
                key=f"{key}_comp"
            )

        with c4:
            selected_dates=st.date_input(
                "Period",
                value=(
                    RELIABLE_START,
                    RELIABLE_END
                ),
                min_value=DATA_START,
                max_value=PARTIAL_DATE,
                key=f"{key}_dates"
            )

        with c5:
            st.write("")

            if st.button(
                "Reset",
                use_container_width=True,
                key=f"{key}_reset"
            ):
                reset_filters(key)
                st.rerun()

    if keyword:
        search_columns=(
            titles
            if titles
            else categorical_columns(filtered)
        )

        if search_columns:
            mask=filtered[
                search_columns
            ].astype(str).apply(
                lambda series:
                series.str.contains(
                    keyword,
                    case=False,
                    na=False
                )
            ).any(axis=1)

            filtered=filtered[mask]

    if country and countries:
        filtered=filtered[
            filtered[countries[0]]
            .astype(str)
            .str.contains(
                country,
                case=False,
                na=False
            )
        ]

    if "is_hourly" in filtered.columns:
        values=(
            filtered["is_hourly"]
            .astype(str)
            .str.lower()
        )

        if compensation=="Hourly":
            filtered=filtered[
                values.isin(
                    ["true","1","yes","hourly"]
                )
            ]

        elif compensation=="Fixed Price":
            filtered=filtered[
                values.isin(
                    ["false","0","no","fixed","fixed price"]
                )
            ]

    if dates and len(selected_dates)==2:
        column=dates[0]

        parsed=pd.to_datetime(
            filtered[column],
            errors="coerce",
            utc=True
        )

        start=pd.Timestamp(
            selected_dates[0],
            tz="UTC"
        )

        end=(
            pd.Timestamp(
                selected_dates[1],
                tz="UTC"
            )
            +pd.Timedelta(days=1)
            -pd.Timedelta(seconds=1)
        )

        filtered=filtered[
            parsed.between(start,end)
        ]

    return filtered

def page_visual(page):
    left,right=st.columns(
        [1.5,.8],
        gap="large"
    )

    with left:
        html(
            f"""
            <div class="feature">

                <div class="feature-tag">
                    DECISION INTELLIGENCE
                </div>

                <div class="feature-title">
                    {escape(page)}
                </div>

                <div class="feature-copy">
                    {escape(PAGE_INFO[page])}
                </div>

                <div class="pills">
                    <span>Historical Evidence</span>
                    <span>API Powered</span>
                    <span>Interactive</span>
                    <span>Export Ready</span>
                    <span>Chart Download</span>
                    <span>Evidence Capture</span>
                </div>

            </div>
            """
        )

    with right:
        st.image(
            asset_image(page),
            use_container_width=True
        )

def data_freshness():
    html(
        f"""
        <div class="freshness">

            <div>
                <span>DATA COVERAGE</span>
                <b>02 Nov 2023 – 24 Mar 2024</b>
            </div>

            <div>
                <span>RELIABLE TREND WINDOW</span>
                <b>13 Feb 2024 – 23 Mar 2024</b>
            </div>

            <div>
                <span>LAST REFRESHED</span>
                <b>{escape(st.session_state.last_refresh)}</b>
            </div>

        </div>
        """
    )

def capture_screenshot(label):
    try:
        time.sleep(.5)

        image=ImageGrab.grab()

        timestamp=datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        safe="".join(
            char if char.isalnum() else "_"
            for char in label.lower()
        ).strip("_")

        path=SHOT_DIR/f"{timestamp}_{safe}.png"

        image.save(path)

        buffer=io.BytesIO()
        image.save(
            buffer,
            format="PNG"
        )

        manifest=SHOT_DIR/"screenshot_manifest.csv"

        row=pd.DataFrame([{
            "captured_at":datetime.now().isoformat(timespec="seconds"),
            "page":label,
            "file":path.name
        }])

        row.to_csv(
            manifest,
            mode="a" if manifest.exists() else "w",
            header=not manifest.exists(),
            index=False
        )

        logger.info(
            "SCREENSHOT_CAPTURED | page=%s | file=%s",
            label,
            path
        )

        return buffer.getvalue(),path

    except Exception as exc:
        logger.warning(
            "SCREENSHOT_FAILED | %s",
            exc
        )

        return None,None

def screenshot_zip():
    files=sorted(
        SHOT_DIR.glob("*.png"),
        key=lambda path:path.stat().st_mtime,
        reverse=True
    )

    if not files:
        return None

    buffer=io.BytesIO()

    with zipfile.ZipFile(
        buffer,
        "w",
        zipfile.ZIP_DEFLATED
    ) as archive:

        for file in files:
            archive.write(
                file,
                f"screenshots/{file.name}"
            )

        manifest=SHOT_DIR/"screenshot_manifest.csv"

        if manifest.exists():
            archive.write(
                manifest,
                manifest.name
            )

    return buffer.getvalue()

@st.cache_data(show_spinner=False)
def parse_csv(raw):
    if len(raw)>MAX_UPLOAD_MB*1024*1024:
        raise ValueError(
            f"Maximum upload size is {MAX_UPLOAD_MB} MB."
        )

    encoding=None

    for candidate in [
        "utf-8",
        "utf-8-sig",
        "cp1252",
        "latin-1"
    ]:
        try:
            raw.decode(candidate)
            encoding=candidate
            break

        except:
            continue

    if encoding is None:
        raise ValueError(
            "CSV encoding could not be detected."
        )

    text=raw.decode(encoding)

    duplicate_headers=[]

    try:
        header=next(
            csv.reader(
                io.StringIO(text)
            )
        )

        duplicate_headers=[
            value
            for value in set(header)
            if header.count(value)>1
        ]

    except:
        pass

    df=pd.read_csv(
        io.BytesIO(raw),
        encoding=encoding,
        low_memory=False,
        nrows=MAX_UPLOAD_ROWS,
        on_bad_lines="error"
    )

    if df.empty:
        raise ValueError(
            "The uploaded CSV contains no data."
        )

    return df,encoding,duplicate_headers

def automatic_csv_insights(df):
    findings=[]

    missing=(
        df.isna().mean()*100
    ).sort_values(
        ascending=False
    )

    if (
        len(missing)
        and missing.iloc[0]>0
    ):
        findings.append(
            f"{missing.index[0]} has the highest missingness at {missing.iloc[0]:.2f}%."
        )

    duplicate_count=int(
        df.duplicated().sum()
    )

    findings.append(
        f"{duplicate_count:,} exact duplicate rows were detected."
    )

    nums=numeric_columns(df)

    if len(nums)>=2:
        corr=df[nums].corr(
            numeric_only=True
        )

        upper=(
            corr.where(
                np.triu(
                    np.ones(corr.shape),
                    k=1
                ).astype(bool)
            )
            .stack()
            .abs()
            .sort_values(
                ascending=False
            )
        )

        if not upper.empty:
            pair=upper.index[0]

            findings.append(
                f"The strongest numeric relationship is {pair[0]} vs {pair[1]} with |r|={upper.iloc[0]:.2f}."
            )

    dates=detect_dates(df)

    if dates:
        parsed=pd.to_datetime(
            df[dates[0]],
            errors="coerce",
            utc=True
        )

        if parsed.notna().any():
            findings.append(
                f"Detected date range is {parsed.min().date()} to {parsed.max().date()}."
            )

    high_cardinality=[]

    for column in df.columns:
        ratio=(
            df[column].nunique(dropna=True)
            /max(len(df),1)
        )

        if ratio>=.95:
            high_cardinality.append(column)

    if high_cardinality:
        findings.append(
            "Likely identifier/high-cardinality fields: "
            +", ".join(high_cardinality[:5])
            +"."
        )

    return findings

def outlier_summary(df):
    rows=[]

    for column in numeric_columns(df):
        values=pd.to_numeric(
            df[column],
            errors="coerce"
        ).dropna()

        if len(values)<4:
            continue

        q1=values.quantile(.25)
        q3=values.quantile(.75)
        iqr=q3-q1

        low=q1-1.5*iqr
        high=q3+1.5*iqr

        count=int(
            (
                (values<low)
                |
                (values>high)
            ).sum()
        )

        rows.append({
            "Column":column,
            "Q1":q1,
            "Q3":q3,
            "IQR":iqr,
            "Potential Outliers":count,
            "Outlier %":round(
                count/len(values)*100,
                2
            )
        })

    return pd.DataFrame(rows)

def load_examples():
    path=Path(
        "frontend_handoff/frontend_request_examples.json"
    )

    if not path.exists():
        return {}

    try:
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except:
        return {}

EXAMPLES=load_examples()

def example_for(*keys):
    for key in keys:
        if key in EXAMPLES:
            value=EXAMPLES[key]

            if isinstance(value,dict):
                return value.get(
                    "payload",
                    value
                )

    return {}

def collect_request(endpoint,example):
    payload=(
        example.copy()
        if isinstance(example,dict)
        else {}
    )

    edited={}

    if payload:
        cols=st.columns(2)

        for index,(key,value) in enumerate(
            payload.items()
        ):
            with cols[index%2]:
                label=pretty(key)

                if isinstance(value,bool):
                    edited[key]=st.toggle(
                        label,
                        value=value,
                        key=f"{endpoint}_{key}"
                    )

                elif isinstance(value,int):
                    edited[key]=st.number_input(
                        label,
                        value=value,
                        step=1,
                        key=f"{endpoint}_{key}"
                    )

                elif isinstance(value,float):
                    edited[key]=st.number_input(
                        label,
                        value=float(value),
                        key=f"{endpoint}_{key}"
                    )

                elif isinstance(value,list):
                    raw=st.text_input(
                        label,
                        value=", ".join(
                            map(str,value)
                        ),
                        key=f"{endpoint}_{key}"
                    )

                    edited[key]=[
                        item.strip()
                        for item in raw.split(",")
                        if item.strip()
                    ]

                else:
                    edited[key]=st.text_input(
                        label,
                        value=str(value),
                        key=f"{endpoint}_{key}"
                    )

    else:
        raw=st.text_area(
            "Request JSON",
            "{}",
            height=180,
            key=f"{endpoint}_json"
        )

        try:
            edited=json.loads(raw)

        except:
            edited={}

    return edited

def render_forecast(result):
    df=frame(result)

    if df.empty:
        st.json(result)
        return

    dates=detect_dates(df)
    nums=numeric_columns(df)

    actual=[
        column
        for column in nums
        if "actual" in column.lower()
    ]

    prediction=[
        column
        for column in nums
        if any(
            term in column.lower()
            for term in [
                "forecast",
                "predict"
            ]
        )
    ]

    if dates and nums:
        date_col=dates[0]

        df[date_col]=pd.to_datetime(
            df[date_col],
            errors="coerce",
            utc=True
        )

        series=[]

        if actual:
            series.append(actual[0])

        if prediction:
            series.append(prediction[0])

        if not series:
            series=[nums[0]]

        fig=px.line(
            df,
            x=date_col,
            y=series,
            markers=True,
            color_discrete_sequence=PALETTE,
            title="Demand Forecast"
        )

        plot(fig,520)

    table(df)

    download_csv(
        df,
        "demand_forecast.csv",
        "forecast_download"
    )

def render_scenarios(result):
    df=frame(result)

    if df.empty:
        st.json(result)
        return

    dates=detect_dates(df)
    nums=numeric_columns(df)
    cats=categorical_columns(df)

    scenario=next(
        (
            column
            for column in cats
            if "scenario" in column.lower()
        ),
        None
    )

    if dates and nums:
        date_col=dates[0]
        metric=nums[0]

        df[date_col]=pd.to_datetime(
            df[date_col],
            errors="coerce",
            utc=True
        )

        fig=px.line(
            df,
            x=date_col,
            y=metric,
            color=scenario,
            markers=True,
            color_discrete_sequence=PALETTE,
            title="Future Scenario Comparison"
        )

        plot(fig,520)

    elif scenario and nums:
        metric=nums[0]

        fig=px.bar(
            df,
            x=scenario,
            y=metric,
            color=scenario,
            color_discrete_sequence=PALETTE,
            title="Scenario Comparison"
        )

        plot(fig)

    table(df)

    download_csv(
        df,
        "future_scenarios.csv",
        "scenario_download"
    )

def render_recommendations(result):
    df=frame(result)

    if df.empty:
        empty_state(
            "No recommendations were returned. Try a broader job title."
        )
        return

    title_col=next(
        (
            column
            for column in df.columns
            if "title" in column.lower()
            or "job" in column.lower()
        ),
        df.columns[0]
    )

    score_col=next(
        (
            column
            for column in numeric_columns(df)
            if "score" in column.lower()
            or "similarity" in column.lower()
        ),
        None
    )

    section(
        "Recommended Opportunities",
        "Ranked recommendations returned by the production recommendation service."
    )

    cols=st.columns(3)

    for index,(_,row) in enumerate(
        df.head(9).iterrows()
    ):
        with cols[index%3]:
            title=str(
                row.get(
                    title_col,
                    f"Recommendation {index+1}"
                )
            )

            score=(
                row.get(score_col)
                if score_col
                else None
            )

            html(
                f"""
                <div class="recommend-card">

                    <div class="rank">
                        RANK #{index+1}
                    </div>

                    <div class="recommend-title">
                        {escape(title)}
                    </div>

                    <div class="recommend-score">
                        {
                            "Similarity / score · "+escape(fmt(score))
                            if score is not None
                            else "Production recommendation"
                        }
                    </div>

                </div>
                """
            )

    with st.expander(
        "View recommendation evidence"
    ):
        table(df)

    download_csv(
        df,
        "job_recommendations.csv",
        "recommendation_download"
    )

def run_api_analysis(endpoint,title,example,renderer):
    section(
        title,
        "Configure the request and send it through the production Flask API."
    )

    payload=collect_request(
        endpoint,
        example
    )

    if st.button(
        "▶ Run Analysis",
        type="primary",
        use_container_width=True,
        key=f"run_{endpoint}"
    ):
        try:
            with st.spinner(
                "Running production inference..."
            ):
                result=api_post(
                    endpoint,
                    payload
                )

            st.success(
                "Analysis completed successfully."
            )

            renderer(result)

            logger.info(
                "API_POST_SUCCESS | endpoint=%s",
                endpoint
            )

        except Exception as exc:
            st.error(
                "The request could not be completed."
            )

            with st.expander(
                "Technical details"
            ):
                st.code(str(exc))

            logger.warning(
                "API_POST_FAILED | endpoint=%s | error=%s",
                endpoint,
                exc
            )

def client_report(summary,emerging,countries):
    indicators=""

    if isinstance(summary,dict):
        for key,value in summary.items():
            if not isinstance(value,(dict,list)):
                indicators+=(
                    f"<li><b>{escape(pretty(key))}:</b> "
                    f"{escape(fmt(value))}</li>"
                )

    emerging_text="No emerging-job evidence available."
    country_text="No geographic evidence available."

    if not emerging.empty:
        nums=numeric_columns(emerging)
        cats=categorical_columns(emerging)

        if nums and cats:
            row=emerging.nlargest(
                1,
                nums[0]
            ).iloc[0]

            emerging_text=escape(
                str(row[cats[0]])
            )

    if not countries.empty:
        nums=numeric_columns(countries)
        cats=categorical_columns(countries)

        if nums and cats:
            row=countries.nlargest(
                1,
                nums[0]
            ).iloc[0]

            country_text=escape(
                str(row[cats[0]])
            )

    return f"""
    <html>
    <head>

    <meta charset="utf-8">

    <style>
    body{{
        font-family:Arial;
        margin:45px;
        color:#22223b;
        line-height:1.65;
    }}

    h1,h2{{
        color:#22223b;
    }}

    .box{{
        background:#f2e9e4;
        border-radius:10px;
        padding:18px;
        margin:14px 0;
    }}
    </style>

    </head>

    <body>

    <h1>Job Market Intelligence Report</h1>

    <p>
    Client-ready historical market intelligence generated from
    the supplied job-market dataset.
    </p>

    <h2>Executive Indicators</h2>

    <ul>
        {indicators}
    </ul>

    <h2>Leading Emerging Opportunity</h2>

    <div class="box">
        {emerging_text}
    </div>

    <h2>Leading Geographic Market</h2>

    <div class="box">
        {country_text}
    </div>

    <h2>Methodology</h2>

    <p>
        Reliable trend analysis prioritises 13 February 2024 through
        23 March 2024. The 24 March 2024 observation is partial.
    </p>

    <p>
        Hourly and fixed-price compensation are analysed separately.
        Currency normalization is intentionally excluded.
    </p>

    <h2>Limitations</h2>

    <p>
        Results represent a historical snapshot rather than a live
        labour-market feed. Verified remote status, explicit skills,
        experience requirements and company information are not
        available in the source dataset.
    </p>

    </body>
    </html>
    """

def evidence_package():
    buffer=io.BytesIO()

    endpoints={
        "market_summary.csv":"market/summary",
        "market_trends.csv":"market/trends",
        "emerging_jobs.csv":"market/emerging-jobs",
        "countries.csv":"market/countries",
        "model_performance.csv":"models/performance"
    }

    with zipfile.ZipFile(
        buffer,
        "w",
        zipfile.ZIP_DEFLATED
    ) as archive:

        archive.writestr(
            "methodology.txt",
            METHOD_TEXT
        )

        for filename,endpoint in endpoints.items():
            try:
                data=api_get(endpoint)
                df=frame(data)

                if not df.empty:
                    archive.writestr(
                        filename,
                        df.to_csv(
                            index=False
                        )
                    )

                elif isinstance(data,dict):
                    archive.writestr(
                        filename.replace(
                            ".csv",
                            ".json"
                        ),
                        json.dumps(
                            data,
                            indent=2,
                            default=str
                        )
                    )

            except Exception as exc:
                archive.writestr(
                    f"errors/{endpoint.replace('/','_')}.txt",
                    str(exc)
                )

        screenshots=sorted(
            SHOT_DIR.glob("*.png")
        )

        for file in screenshots:
            archive.write(
                file,
                f"screenshots/{file.name}"
            )

        manifest=SHOT_DIR/"screenshot_manifest.csv"

        if manifest.exists():
            archive.write(
                manifest,
                "screenshot_manifest.csv"
            )

        telemetry=pd.DataFrame(
            st.session_state.api_telemetry.values()
        )

        if not telemetry.empty:
            archive.writestr(
                "api_health.csv",
                telemetry.to_csv(
                    index=False
                )
            )

    return buffer.getvalue()

def methodology():
    with st.expander(
        "ℹ Methodology & analytical scope"
    ):
        st.markdown(
            """
**Historical coverage:** 2 November 2023 to 24 March 2024.

**Reliable trend window:** 13 February 2024 to 23 March 2024.

**Partial observation:** 24 March 2024 is incomplete and should not be treated as a complete comparison day.

**Compensation:** hourly compensation and fixed-price budgets are kept separate.

**Currency:** no reliable currency field is available, so currency normalization is intentionally excluded.

**Known source limitations:** no verified remote status, explicit skills, verified experience requirements or company information is available.

**Interpretation:** the platform analyses a historical market snapshot rather than the current live labour market.

**Uploaded CSVs:** files uploaded to CSV Workspace remain isolated from the validated production model pipeline.
            """
        )

try:
    health=api_get(
        "health"
    )

    health_info=st.session_state.api_telemetry.get(
        "health",
        {}
    )

    API_LATENCY=health_info.get(
        "Latency ms"
    )

    API_STATUS="CONNECTED"

except Exception as exc:
    health={}
    API_LATENCY=None
    API_STATUS="OFFLINE"

    logger.warning(
        "API_HEALTH_FAILED | %s",
        exc
    )

html("""
<style>

:root{
--indigo:#22223b;
--grape:#4a4e69;
--ash:#9a8c98;
--almond:#c9ada7;
--shell:#f2e9e4;
}

.stApp{
background:linear-gradient(180deg,#fcfbfa 0%,#f4f1ef 100%);
color:#22223b;
}

.block-container{
max-width:1560px;
padding-top:1.1rem;
padding-bottom:3rem;
}

[data-testid="stSidebar"]{
background:
radial-gradient(circle at 20% 0%,rgba(201,173,167,.13),transparent 24%),
linear-gradient(180deg,#1e2037,#292c47 55%,#41445f);
border-right:1px solid rgba(255,255,255,.06);
}

[data-testid="stSidebar"] *{
color:#f2e9e4;
}

[data-testid="stSidebar"] hr{
border-color:rgba(255,255,255,.12);
}

.hero{
background:
radial-gradient(circle at 87% 15%,rgba(201,173,167,.27),transparent 26%),
linear-gradient(120deg,#22223b,#30324d 53%,#4a4e69);
padding:28px 31px;
border-radius:21px;
color:white;
box-shadow:0 15px 38px rgba(34,34,59,.18);
margin-bottom:17px;
}

.hero-grid{
display:flex;
justify-content:space-between;
align-items:flex-start;
gap:30px;
}

.hero-tag{
font-size:9px;
font-weight:800;
letter-spacing:1.8px;
color:#c9ada7;
}

.hero-title{
font-size:33px;
font-weight:800;
margin:7px 0;
}

.hero-copy{
font-size:11px;
line-height:1.8;
color:#f2e9e4;
}

.hero-status{
text-align:right;
min-width:160px;
font-size:8px;
color:#c9ada7;
}

.hero-status b{
display:block;
font-size:15px;
color:white;
margin:3px 0 10px;
}

.freshness{
display:grid;
grid-template-columns:repeat(3,1fr);
gap:8px;
margin-bottom:20px;
}

.freshness div{
background:white;
border:1px solid #e8e1df;
border-radius:10px;
padding:10px 13px;
}

.freshness span{
display:block;
font-size:7px;
letter-spacing:1px;
font-weight:800;
color:#9a8c98;
}

.freshness b{
display:block;
font-size:10px;
margin-top:3px;
color:#4a4e69;
}

.feature{
height:100%;
min-height:250px;
display:flex;
flex-direction:column;
justify-content:center;
background:linear-gradient(145deg,#fff,#fbfaf9);
border:1px solid #e7e0dd;
border-radius:18px;
padding:30px 32px;
box-shadow:0 7px 24px rgba(34,34,59,.055);
}

.feature-tag{
font-size:8px;
font-weight:800;
letter-spacing:1.6px;
color:#9a8c98;
}

.feature-title{
font-size:28px;
font-weight:800;
color:#22223b;
margin:9px 0 11px;
}

.feature-copy{
font-size:12px;
line-height:1.85;
color:#4a4e69;
}

.pills{
margin-top:18px;
}

.pills span{
display:inline-block;
background:#f2e9e4;
color:#4a4e69;
font-size:8px;
font-weight:700;
padding:6px 10px;
border-radius:20px;
margin:4px 4px 0 0;
}

.section-title{
font-size:21px;
font-weight:800;
color:#22223b;
margin-top:24px;
margin-bottom:4px;
}

.section-sub{
font-size:11px;
line-height:1.65;
color:#777286;
margin-bottom:15px;
}

[data-testid="stMetric"]{
background:linear-gradient(145deg,#fff,#fbfaf9);
border:1px solid #e7e1df;
border-radius:15px;
padding:17px;
box-shadow:0 5px 17px rgba(34,34,59,.045);
}

[data-testid="stMetricLabel"]{
color:#9a8c98;
font-weight:600;
}

[data-testid="stMetricValue"]{
color:#22223b;
font-weight:800;
}

.info{
background:white;
border:1px solid #e7e1df;
border-left:4px solid #4a4e69;
border-radius:11px;
padding:16px 18px;
margin:12px 0;
color:#4a4e69;
font-size:11px;
line-height:1.8;
}

.limit{
background:#f2e9e4;
border-left:4px solid #c9ada7;
border-radius:11px;
padding:16px 18px;
margin:12px 0;
color:#4a4e69;
font-size:11px;
line-height:1.8;
}

.good{
background:#eef7f0;
border-left:4px solid #598763;
border-radius:11px;
padding:15px 17px;
color:#3c6144;
font-size:11px;
}

.review{
background:#fff4e8;
border-left:4px solid #b87935;
border-radius:11px;
padding:15px 17px;
color:#765022;
font-size:11px;
}

.empty{
background:#faf8f7;
border:1px dashed #c9ada7;
border-radius:12px;
padding:25px;
text-align:center;
color:#777286;
font-size:11px;
}

.recommend-card{
min-height:145px;
background:linear-gradient(145deg,#fff,#f8f5f4);
border:1px solid #e6dedb;
border-radius:15px;
padding:17px;
margin:6px 0 14px 0;
box-shadow:0 5px 16px rgba(34,34,59,.05);
}

.rank{
font-size:9px;
font-weight:800;
color:#9a8c98;
}

.recommend-title{
font-size:16px;
font-weight:800;
color:#22223b;
margin:8px 0;
}

.recommend-score{
font-size:10px;
color:#4a4e69;
}

div[data-testid="stImage"] img{
width:100%;
height:250px;
object-fit:cover;
border-radius:18px;
box-shadow:0 7px 24px rgba(34,34,59,.08);
}

[data-testid="stDataFrame"]{
border:1px solid #e6dfdc;
border-radius:12px;
overflow:hidden;
}

.stButton>button{
background:#4a4e69;
color:white;
border:none;
border-radius:10px;
font-weight:700;
transition:.2s;
}

.stButton>button:hover{
background:#22223b;
color:white;
border:none;
transform:translateY(-1px);
}

div[data-testid="stDownloadButton"] button{
border-radius:10px;
}

.stTabs [data-baseweb="tab-list"]{
gap:7px;
}

.stTabs [data-baseweb="tab"]{
background:#f2e9e4;
border-radius:10px;
padding:8px 15px;
}

.stTabs [aria-selected="true"]{
background:#4a4e69!important;
color:white!important;
}

.footer{
margin-top:42px;
padding:20px 10px;
border-top:1px solid #ddd5d1;
text-align:center;
font-size:9px;
color:#9a8c98;
}

@media(max-width:900px){

.freshness{
grid-template-columns:1fr;
}

.hero-grid{
display:block;
}

.hero-status{
text-align:left;
margin-top:18px;
}

}

</style>
""")

with st.sidebar:
    st.markdown(
        "## 📊 Job Market Intelligence"
    )

    st.caption(
        "Analytics & Recommendation Platform"
    )

    st.markdown("---")
    st.markdown("#### CSV Workspace")

    uploaded=st.file_uploader(
        "Upload CSV",
        type=["csv"],
        key=f"csv_upload_{st.session_state.upload_key}",
        help=f"Maximum {MAX_UPLOAD_MB} MB."
    )

    if uploaded is not None:
        try:
            uploaded_df,encoding,duplicate_headers=parse_csv(
                uploaded.getvalue()
            )

            if (
                st.session_state.uploaded_name
                !=uploaded.name
            ):
                st.session_state.csv_working_df=uploaded_df.copy()

            st.session_state.uploaded_df=uploaded_df
            st.session_state.uploaded_name=uploaded.name
            st.session_state.uploaded_encoding=encoding

            st.success(
                f"✓ {uploaded.name}"
            )

            st.caption(
                f"{len(uploaded_df):,} rows · "
                f"{len(uploaded_df.columns)} columns · "
                f"{encoding}"
            )

            if duplicate_headers:
                st.warning(
                    "Duplicate column names detected: "
                    +", ".join(duplicate_headers)
                )

            if len(uploaded_df)>=100_000:
                st.info(
                    "Large CSV detected. Plot sizes are limited automatically for responsiveness."
                )

        except Exception as exc:
            st.error(str(exc))

    if st.session_state.uploaded_df is not None:
        st.caption(
            f"Dataset health · "
            f"{health_score(st.session_state.uploaded_df)}%"
        )

        if st.button(
            "✕ Clear CSV",
            use_container_width=True
        ):
            st.session_state.uploaded_df=None
            st.session_state.csv_working_df=None
            st.session_state.uploaded_name=None
            st.session_state.upload_key+=1

            st.rerun()

    st.markdown("---")

    selected=st.radio(
        "Navigation",
        list(PAGES.keys()),
        label_visibility="collapsed"
    )

    page=PAGES[selected]

    st.markdown("---")
    st.markdown("#### System")

    st.caption(
        f"● API · {API_STATUS}"
    )

    st.caption(
        f"● Logger · {LOGGER_STATUS}"
    )

    if API_LATENCY is not None:
        st.caption(
            f"● Latency · {API_LATENCY} ms"
        )

    if st.button(
        "↻ Refresh Data",
        use_container_width=True
    ):
        cached_get.clear()

        st.session_state.last_refresh=datetime.now().strftime(
            "%d %b %Y · %H:%M:%S"
        )

        st.rerun()

    st.markdown("---")
    st.markdown("#### Screenshot")

    if st.button(
        "📸 Capture Screen",
        use_container_width=True
    ):
        screenshot_data,path=capture_screenshot(
            page
        )

        if screenshot_data:
            st.session_state.latest_screenshot=screenshot_data
            st.session_state.latest_screenshot_name=path.name

            st.success(
                "Screenshot captured."
            )

    if st.session_state.latest_screenshot:
        st.download_button(
            "⬇ Download Latest",
            st.session_state.latest_screenshot,
            st.session_state.latest_screenshot_name,
            "image/png",
            use_container_width=True,
            key="sidebar_screen_download"
        )

CSV_STATUS=(
    "READY"
    if st.session_state.uploaded_df is not None
    else "NONE"
)

html(
    f"""
    <div class="hero">

        <div class="hero-grid">

            <div>

                <div class="hero-tag">
                    JOB MARKET ANALYSIS &amp; RECOMMENDATION SYSTEM
                </div>

                <div class="hero-title">
                    {escape(page)}
                </div>

                <div class="hero-copy">
                    Market intelligence &bull;
                    Forecasting &bull;
                    Recommendation &bull;
                    Interactive analytics &bull;
                    Client-ready evidence
                </div>

            </div>

            <div class="hero-status">

                API
                <b>{API_STATUS}</b>

                LOGGER
                <b>{LOGGER_STATUS}</b>

                CSV
                <b>{CSV_STATUS}</b>

            </div>

        </div>

    </div>
    """
)

data_freshness()

if (
    page!="CSV Workspace"
    and API_STATUS=="OFFLINE"
):
    st.error(
        "The Streamlit frontend is running, but the Flask backend is unavailable."
    )

    st.code(
        r'.\.venv\Scripts\python.exe -m api.app',
        language="powershell"
    )

    st.stop()

page_visual(page)

if page=="Client Summary":
    try:
        summary=api_get(
            "market/summary"
        )

        emerging=frame(
            api_get(
                "market/emerging-jobs"
            )
        )

        countries=frame(
            api_get(
                "market/countries"
            )
        )

        trends=frame(
            api_get(
                "market/trends"
            )
        )

        section(
            "Client Decision Summary",
            "The strongest evidence and conclusions in a single presentation-ready view."
        )

        metric_cards(
            summary,
            5
        )

        left,right=st.columns(
            [1.4,1]
        )

        with left:
            dates=detect_dates(
                trends
            )

            nums=numeric_columns(
                trends
            )

            if dates and nums:
                date_col=dates[0]
                metric=nums[0]

                trends[date_col]=pd.to_datetime(
                    trends[date_col],
                    errors="coerce",
                    utc=True
                )

                chart=(
                    trends[
                        [date_col,metric]
                    ]
                    .dropna()
                    .sort_values(
                        date_col
                    )
                )

                chart["7-period trend"]=(
                    chart[metric]
                    .rolling(
                        7,
                        min_periods=1
                    )
                    .mean()
                )

                fig=px.line(
                    chart,
                    x=date_col,
                    y=[
                        metric,
                        "7-period trend"
                    ],
                    color_discrete_sequence=PALETTE,
                    title="Demand Direction"
                )

                plot(
                    fig,
                    430
                )

        with right:
            if not emerging.empty:
                nums=numeric_columns(
                    emerging
                )

                cats=categorical_columns(
                    emerging
                )

                if nums and cats:
                    best=emerging.nlargest(
                        1,
                        nums[0]
                    ).iloc[0]

                    insight(
                        "Leading opportunity",
                        f"{best[cats[0]]} ranks highest on the available emerging-job metric."
                    )

            if not countries.empty:
                nums=numeric_columns(
                    countries
                )

                cats=categorical_columns(
                    countries
                )

                if nums and cats:
                    leader=countries.nlargest(
                        1,
                        nums[0]
                    ).iloc[0]

                    insight(
                        "Leading geographic market",
                        f"{leader[cats[0]]} has the highest observed activity on the available geographic metric."
                    )

            insight(
                "Interpretation",
                "This platform analyses a historical market snapshot rather than the current live labour market.",
                "limit"
            )

        section(
            "Client Recommendations"
        )

        c1,c2,c3=st.columns(3)

        with c1:
            insight(
                "Prioritise momentum",
                "Use emerging-job rankings to identify categories demonstrating stronger recent demand momentum."
            )

        with c2:
            insight(
                "Assess concentration",
                "Combine country-level volume with market-share concentration rather than relying on posting counts alone."
            )

        with c3:
            insight(
                "Use forecasts with validation",
                "Interpret predictions together with historical model error and scenario evidence rather than as guaranteed outcomes."
            )

        report=client_report(
            summary,
            emerging,
            countries
        )

        st.download_button(
            "📄 Download Client Report",
            report.encode("utf-8"),
            "job_market_client_report.html",
            "text/html",
            use_container_width=True
        )

    except Exception as exc:
        st.error(str(exc))

elif page=="Executive Overview":
    try:
        summary=api_get(
            "market/summary"
        )

        trends=frame(
            api_get(
                "market/trends"
            )
        )

        emerging=frame(
            api_get(
                "market/emerging-jobs"
            )
        )

        countries=frame(
            api_get(
                "market/countries"
            )
        )

        section(
            "Executive Market Snapshot"
        )

        metric_cards(
            summary,
            5
        )

        tabs=st.tabs([
            "📈 Demand",
            "🚀 Opportunities",
            "🌍 Geography",
            "💡 Takeaways"
        ])

        with tabs[0]:
            filtered=global_filters(
                trends,
                "executive"
            )

            dates=detect_dates(
                filtered
            )

            nums=numeric_columns(
                filtered
            )

            if dates and nums:
                date_col=dates[0]

                metric=st.selectbox(
                    "Demand metric",
                    nums,
                    format_func=pretty,
                    key="exec_metric"
                )

                rolling=st.slider(
                    "Rolling average",
                    1,
                    14,
                    7,
                    key="exec_rolling"
                )

                filtered[date_col]=pd.to_datetime(
                    filtered[date_col],
                    errors="coerce",
                    utc=True
                )

                chart=(
                    filtered[
                        [date_col,metric]
                    ]
                    .dropna()
                    .sort_values(
                        date_col
                    )
                )

                if chart.empty:
                    empty_state(
                        "No trend records match the current filters."
                    )

                else:
                    chart["Trend"]=(
                        chart[metric]
                        .rolling(
                            rolling,
                            min_periods=1
                        )
                        .mean()
                    )

                    fig=go.Figure()

                    fig.add_trace(
                        go.Scatter(
                            x=chart[date_col],
                            y=chart[metric],
                            name="Observed",
                            line=dict(
                                color="#9a8c98",
                                width=1
                            )
                        )
                    )

                    fig.add_trace(
                        go.Scatter(
                            x=chart[date_col],
                            y=chart["Trend"],
                            name=f"{rolling}-period trend",
                            line=dict(
                                color="#4a4e69",
                                width=3
                            )
                        )
                    )

                    fig.update_layout(
                        title="Observed Demand vs Smoothed Trend"
                    )

                    plot(
                        fig,
                        500
                    )

                    if len(chart)>1:
                        start_value=chart[metric].iloc[0]
                        end_value=chart[metric].iloc[-1]

                        movement=(
                            (
                                end_value-start_value
                            )/start_value*100
                            if start_value
                            else np.nan
                        )

                        st.metric(
                            "Selected-period movement",
                            fmt(end_value),
                            (
                                f"{movement:.2f}%"
                                if pd.notna(movement)
                                else None
                            )
                        )

            else:
                empty_state(
                    "The trend API response does not contain a usable date and numeric metric."
                )

        with tabs[1]:
            nums=numeric_columns(
                emerging
            )

            cats=categorical_columns(
                emerging
            )

            if nums and cats:
                metric=st.selectbox(
                    "Opportunity metric",
                    nums,
                    format_func=pretty,
                    key="exec_emerging_metric"
                )

                ranked=emerging.nlargest(
                    min(
                        15,
                        len(emerging)
                    ),
                    metric
                )

                fig=px.bar(
                    ranked.sort_values(metric),
                    x=metric,
                    y=cats[0],
                    orientation="h",
                    color=metric,
                    color_continuous_scale="Purples",
                    title="Emerging Opportunities"
                )

                plot(
                    fig,
                    520
                )

        with tabs[2]:
            nums=numeric_columns(
                countries
            )

            cats=categorical_columns(
                countries
            )

            if nums and cats:
                metric=st.selectbox(
                    "Geographic metric",
                    nums,
                    format_func=pretty,
                    key="exec_geo_metric"
                )

                ranked=countries.nlargest(
                    min(
                        15,
                        len(countries)
                    ),
                    metric
                )

                fig=px.bar(
                    ranked.sort_values(metric),
                    x=metric,
                    y=cats[0],
                    orientation="h",
                    color=metric,
                    color_continuous_scale="Purples",
                    title="Leading Geographic Markets"
                )

                plot(
                    fig,
                    520
                )

        with tabs[3]:
            insight(
                "Reliable trend window",
                "Trend interpretation should prioritise 13 February 2024 through 23 March 2024."
            )

            insight(
                "Partial final date",
                "24 March 2024 is a partial observation and should not be treated as a complete comparison day.",
                "limit"
            )

            insight(
                "Compensation governance",
                "Hourly and fixed-price compensation remain analytically separate."
            )

    except Exception as exc:
        st.error(str(exc))

elif page=="Salary Intelligence":
    try:
        df=frame(
            api_get(
                "market/salary"
            )
        )

        filtered=global_filters(
            df,
            "salary"
        )

        section(
            "Compensation Intelligence",
            "Hourly and fixed-price compensation are deliberately analysed independently."
        )

        profile_cards(
            filtered
        )

        mode=st.radio(
            "Compensation Type",
            [
                "Hourly",
                "Fixed Price"
            ],
            horizontal=True
        )

        if mode=="Hourly":
            hourly=filtered.copy()

            if "is_hourly" in hourly.columns:
                hourly=hourly[
                    hourly["is_hourly"]
                    .astype(str)
                    .str.lower()
                    .isin(
                        [
                            "true",
                            "1",
                            "yes",
                            "hourly"
                        ]
                    )
                ]

            if {
                "hourly_low",
                "hourly_high"
            }.issubset(hourly.columns):

                hourly["hourly_midpoint"]=(
                    pd.to_numeric(
                        hourly["hourly_low"],
                        errors="coerce"
                    )
                    +
                    pd.to_numeric(
                        hourly["hourly_high"],
                        errors="coerce"
                    )
                )/2

                hourly["hourly_spread"]=(
                    pd.to_numeric(
                        hourly["hourly_high"],
                        errors="coerce"
                    )
                    -
                    pd.to_numeric(
                        hourly["hourly_low"],
                        errors="coerce"
                    )
                )

            options=[
                column
                for column in [
                    "hourly_low",
                    "hourly_high",
                    "hourly_midpoint",
                    "hourly_spread"
                ]
                if column in hourly.columns
            ]

            if options:
                metric=st.selectbox(
                    "Hourly metric",
                    options,
                    format_func=pretty
                )

                values=pd.to_numeric(
                    hourly[metric],
                    errors="coerce"
                ).dropna()

                if not values.empty:
                    q1=values.quantile(.25)
                    q3=values.quantile(.75)

                    cols=st.columns(5)

                    cols[0].metric(
                        "Median",
                        f"{values.median():,.2f}"
                    )

                    cols[1].metric(
                        "Q1",
                        f"{q1:,.2f}"
                    )

                    cols[2].metric(
                        "Q3",
                        f"{q3:,.2f}"
                    )

                    cols[3].metric(
                        "IQR",
                        f"{q3-q1:,.2f}"
                    )

                    outlier_count=int(
                        (
                            (
                                values
                                <
                                q1-1.5*(q3-q1)
                            )
                            |
                            (
                                values
                                >
                                q3+1.5*(q3-q1)
                            )
                        ).sum()
                    )

                    cols[4].metric(
                        "Potential Outliers",
                        f"{outlier_count:,}"
                    )

                    fig=px.histogram(
                        hourly,
                        x=metric,
                        nbins=40,
                        marginal="box",
                        color_discrete_sequence=[
                            "#4a4e69"
                        ],
                        title=f"{pretty(metric)} Distribution"
                    )

                    plot(
                        fig,
                        520
                    )

            else:
                empty_state(
                    "Hourly compensation fields were not returned by the API."
                )

            download_csv(
                hourly,
                "hourly_compensation.csv",
                "hourly_compensation_download"
            )

        else:
            fixed=filtered.copy()

            if "is_hourly" in fixed.columns:
                fixed=fixed[
                    ~fixed["is_hourly"]
                    .astype(str)
                    .str.lower()
                    .isin(
                        [
                            "true",
                            "1",
                            "yes",
                            "hourly"
                        ]
                    )
                ]

            if "budget" in fixed.columns:
                values=pd.to_numeric(
                    fixed["budget"],
                    errors="coerce"
                ).dropna()

                if not values.empty:
                    q1=values.quantile(.25)
                    q3=values.quantile(.75)

                    cols=st.columns(5)

                    cols[0].metric(
                        "Median Budget",
                        f"{values.median():,.2f}"
                    )

                    cols[1].metric(
                        "Q1",
                        f"{q1:,.2f}"
                    )

                    cols[2].metric(
                        "Q3",
                        f"{q3:,.2f}"
                    )

                    cols[3].metric(
                        "IQR",
                        f"{q3-q1:,.2f}"
                    )

                    outlier_count=int(
                        (
                            (
                                values
                                <
                                q1-1.5*(q3-q1)
                            )
                            |
                            (
                                values
                                >
                                q3+1.5*(q3-q1)
                            )
                        ).sum()
                    )

                    cols[4].metric(
                        "Potential Outliers",
                        f"{outlier_count:,}"
                    )

                    fig=px.histogram(
                        fixed,
                        x="budget",
                        nbins=40,
                        marginal="box",
                        color_discrete_sequence=[
                            "#4a4e69"
                        ],
                        title="Fixed-Price Budget Distribution"
                    )

                    plot(
                        fig,
                        520
                    )

            else:
                empty_state(
                    "The salary API did not return a budget field."
                )

            download_csv(
                fixed,
                "fixed_price_compensation.csv",
                "fixed_compensation_download"
            )

        insight(
            "Interpretation rule",
            "No currency conversion is applied because the source dataset does not contain a reliable currency field.",
            "limit"
        )

    except Exception as exc:
        st.error(str(exc))

elif page=="Emerging Jobs":
    try:
        df=frame(
            api_get(
                "market/emerging-jobs"
            )
        )

        section(
            "Emerging Opportunity Explorer",
            "Rank and inspect categories using the available growth and demand evidence."
        )

        if df.empty:
            empty_state(
                "No emerging-job results were returned."
            )

        else:
            profile_cards(df)

            nums=numeric_columns(df)
            cats=categorical_columns(df)

            if nums and cats:
                c1,c2=st.columns(2)

                with c1:
                    metric=st.selectbox(
                        "Ranking metric",
                        nums,
                        format_func=pretty
                    )

                with c2:
                    top_n=st.slider(
                        "Top opportunities",
                        5,
                        min(
                            40,
                            max(
                                5,
                                len(df)
                            )
                        ),
                        min(
                            15,
                            max(
                                5,
                                len(df)
                            )
                        )
                    )

                ranked=df.nlargest(
                    min(
                        top_n,
                        len(df)
                    ),
                    metric
                )

                tabs=st.tabs([
                    "🏆 Ranking",
                    "🧩 Opportunity Mix",
                    "📋 Evidence"
                ])

                with tabs[0]:
                    fig=px.bar(
                        ranked.sort_values(metric),
                        x=metric,
                        y=cats[0],
                        orientation="h",
                        color=metric,
                        color_continuous_scale="Purples",
                        title="Emerging Opportunity Ranking"
                    )

                    plot(
                        fig,
                        520
                    )

                with tabs[1]:
                    positive=ranked[
                        ranked[metric].fillna(0)>0
                    ]

                    if not positive.empty:
                        fig=px.treemap(
                            positive,
                            path=[
                                cats[0]
                            ],
                            values=metric,
                            color=metric,
                            color_continuous_scale="Purples",
                            title="Relative Opportunity Footprint"
                        )

                        plot(
                            fig,
                            520
                        )

                with tabs[2]:
                    table(
                        ranked
                    )

                if not ranked.empty:
                    insight(
                        "Leading emerging category",
                        f"{ranked.iloc[0][cats[0]]} ranks first on {pretty(metric)}."
                    )

                download_csv(
                    ranked,
                    "emerging_jobs.csv",
                    "emerging_download"
                )

            else:
                empty_state(
                    "The API response does not contain both a category and numeric ranking metric."
                )

    except Exception as exc:
        st.error(str(exc))

elif page=="Demand Forecast":
    run_api_analysis(
        "predict-demand",
        "Demand Forecast Engine",
        example_for(
            "predict-demand",
            "/api/predict-demand",
            "predict_demand"
        ),
        render_forecast
    )

elif page=="Geographic Intelligence":
    try:
        df=frame(
            api_get(
                "market/countries"
            )
        )

        section(
            "Geographic Market Intelligence",
            "Compare market activity, share and concentration across countries."
        )

        if df.empty:
            empty_state(
                "No geographic evidence was returned."
            )

        else:
            profile_cards(df)

            nums=numeric_columns(df)
            cats=categorical_columns(df)

            if nums and cats:
                country_col=next(
                    (
                        column
                        for column in cats
                        if "country" in column.lower()
                    ),
                    cats[0]
                )

                metric=st.selectbox(
                    "Market metric",
                    nums,
                    format_func=pretty
                )

                working=df[
                    [
                        country_col,
                        metric
                    ]
                ].dropna().copy()

                working[country_col]=normalize_countries(
                    working[country_col]
                )

                working=(
                    working.groupby(
                        country_col,
                        as_index=False
                    )[metric]
                    .sum()
                )

                total=working[metric].sum()

                working["Share %"]=(
                    working[metric]
                    /total*100
                    if total
                    else 0
                )

                tabs=st.tabs([
                    "🗺 World Map",
                    "🏆 Ranking",
                    "📊 Concentration",
                    "📋 Data"
                ])

                with tabs[0]:
                    fig=px.choropleth(
                        working,
                        locations=country_col,
                        locationmode="country names",
                        color=metric,
                        hover_name=country_col,
                        hover_data={
                            "Share %":":.2f"
                        },
                        color_continuous_scale="Purples",
                        title="Global Market Distribution"
                    )

                    fig.update_geos(
                        showframe=False,
                        showcoastlines=True,
                        projection_type="natural earth"
                    )

                    plot(
                        fig,
                        540
                    )

                with tabs[1]:
                    ranked=working.nlargest(
                        min(
                            20,
                            len(working)
                        ),
                        metric
                    )

                    fig=px.bar(
                        ranked.sort_values(metric),
                        x=metric,
                        y=country_col,
                        orientation="h",
                        color=metric,
                        color_continuous_scale="Purples",
                        title="Leading Geographic Markets"
                    )

                    plot(
                        fig,
                        520
                    )

                with tabs[2]:
                    concentration=working.sort_values(
                        metric,
                        ascending=False
                    ).copy()

                    concentration["Cumulative Share %"]=(
                        concentration[metric]
                        .cumsum()
                        /concentration[metric].sum()
                        *100
                    )

                    fig=px.line(
                        concentration.head(30),
                        x=country_col,
                        y="Cumulative Share %",
                        markers=True,
                        title="Market Concentration"
                    )

                    fig.update_yaxes(
                        range=[0,100]
                    )

                    plot(
                        fig,
                        490
                    )

                with tabs[3]:
                    table(
                        working
                    )

                if not working.empty:
                    leader=working.nlargest(
                        1,
                        metric
                    ).iloc[0]

                    insight(
                        "Largest observed market",
                        f"{leader[country_col]} has the highest observed {pretty(metric)} in this historical dataset."
                    )

                download_csv(
                    working,
                    "geographic_intelligence.csv",
                    "geographic_download"
                )

            else:
                empty_state(
                    "The geographic API response does not contain a usable country field and numeric metric."
                )

    except Exception as exc:
        st.error(str(exc))

elif page=="Market Dynamics":
    try:
        df=frame(
            api_get(
                "market/trends"
            )
        )

        section(
            "Historical Market Dynamics",
            "Explore observed demand, rolling movement and period-over-period change."
        )

        filtered=global_filters(
            df,
            "market_dynamics"
        )

        dates=detect_dates(
            filtered
        )

        nums=numeric_columns(
            filtered
        )

        if dates and nums:
            date_col=dates[0]

            filtered[date_col]=pd.to_datetime(
                filtered[date_col],
                errors="coerce",
                utc=True
            )

            filtered=(
                filtered
                .dropna(
                    subset=[
                        date_col
                    ]
                )
                .sort_values(
                    date_col
                )
            )

            if filtered.empty:
                empty_state(
                    "No market-dynamics records match the selected filters."
                )

            else:
                c1,c2,c3=st.columns(3)

                with c1:
                    metric=st.selectbox(
                        "Metric",
                        nums,
                        format_func=pretty
                    )

                with c2:
                    rolling=st.slider(
                        "Rolling average",
                        1,
                        14,
                        7
                    )

                with c3:
                    view=st.selectbox(
                        "View",
                        [
                            "Observed + Trend",
                            "% Change"
                        ]
                    )

                chart=filtered[
                    [
                        date_col,
                        metric
                    ]
                ].copy()

                chart["Trend"]=(
                    chart[metric]
                    .rolling(
                        rolling,
                        min_periods=1
                    )
                    .mean()
                )

                chart["Change %"]=(
                    chart[metric]
                    .pct_change()*100
                )

                if view=="Observed + Trend":
                    fig=go.Figure()

                    fig.add_trace(
                        go.Scatter(
                            x=chart[date_col],
                            y=chart[metric],
                            name="Observed",
                            line=dict(
                                color="#9a8c98",
                                width=1
                            )
                        )
                    )

                    fig.add_trace(
                        go.Scatter(
                            x=chart[date_col],
                            y=chart["Trend"],
                            name=f"{rolling}-period trend",
                            line=dict(
                                color="#4a4e69",
                                width=3
                            )
                        )
                    )

                    fig.add_hline(
                        y=chart[metric].mean(),
                        line_dash="dash",
                        annotation_text="Period average"
                    )

                    fig.update_layout(
                        title="Observed Demand vs Trend"
                    )

                else:
                    fig=px.bar(
                        chart,
                        x=date_col,
                        y="Change %",
                        color="Change %",
                        color_continuous_scale="RdYlGn",
                        title="Period-over-Period Change"
                    )

                plot(
                    fig,
                    520
                )

                if len(chart)>1:
                    latest=chart[metric].iloc[-1]
                    previous=chart[metric].iloc[-2]

                    movement=(
                        (
                            latest-previous
                        )/previous*100
                        if previous
                        else np.nan
                    )

                    c1,c2,c3=st.columns(3)

                    c1.metric(
                        "Latest",
                        fmt(latest)
                    )

                    c2.metric(
                        "Previous",
                        fmt(previous)
                    )

                    c3.metric(
                        "Latest Change",
                        (
                            f"{movement:.2f}%"
                            if pd.notna(movement)
                            else "—"
                        )
                    )

                table(
                    filtered
                )

                download_csv(
                    filtered,
                    "market_dynamics.csv",
                    "market_dynamics_download"
                )

        else:
            empty_state(
                "The trend response does not contain both a usable date field and numeric metric."
            )

    except Exception as exc:
        st.error(str(exc))

elif page=="Future Scenarios":
    run_api_analysis(
        "predict-future",
        "Future Scenario Simulator",
        example_for(
            "predict-future",
            "/api/predict-future",
            "predict_future"
        ),
        render_scenarios
    )

elif page=="Job Recommender":
    run_api_analysis(
        "recommend",
        "Job Recommendation Engine",
        example_for(
            "recommend",
            "/api/recommend",
            "recommendation"
        ),
        render_recommendations
    )

elif page=="Model Performance":
    try:
        df=frame(
            api_get(
                "models/performance"
            )
        )

        section(
            "Production Model Evidence",
            "Review model comparison metrics and the evidence supporting production selection."
        )

        if df.empty:
            empty_state(
                "No model-performance evidence was returned."
            )

        else:
            profile_cards(df)

            nums=numeric_columns(df)
            cats=categorical_columns(df)

            tabs=st.tabs([
                "📊 Comparison",
                "📋 Evidence",
                "💡 Interpretation"
            ])

            with tabs[0]:
                if nums and cats:
                    metric=st.selectbox(
                        "Evaluation metric",
                        nums,
                        format_func=pretty
                    )

                    fig=px.bar(
                        df,
                        x=cats[0],
                        y=metric,
                        color=metric,
                        color_continuous_scale="Purples",
                        title="Model Performance Comparison"
                    )

                    plot(
                        fig,
                        480
                    )

                else:
                    empty_state(
                        "The performance response does not contain both model labels and numeric metrics."
                    )

            with tabs[1]:
                table(df)

            with tabs[2]:
                insight(
                    "Forecast validation",
                    "Forecast model selection is supported by held-out actual-versus-predicted evaluation."
                )

                insight(
                    "Recommendation validation",
                    "Recommendation quality uses ranking-oriented evidence rather than fabricated user-feedback labels."
                )

            download_csv(
                df,
                "model_performance.csv",
                "model_performance_download"
            )

    except Exception as exc:
        st.error(str(exc))

elif page=="CSV Workspace":
    original=st.session_state.uploaded_df

    if original is None:
        empty_state(
            "Upload a CSV from the sidebar to begin independent analysis."
        )

    else:
        if st.session_state.csv_working_df is None:
            st.session_state.csv_working_df=original.copy()

        df=st.session_state.csv_working_df

        section(
            "Uploaded Dataset Intelligence",
            f"{st.session_state.uploaded_name} · independent analytical workspace"
        )

        profile_cards(df)

        present=[
            column
            for column in EXPECTED_COLUMNS
            if column in df.columns
        ]

        missing_expected=[
            column
            for column in EXPECTED_COLUMNS
            if column not in df.columns
        ]

        schema_score=round(
            len(present)
            /len(EXPECTED_COLUMNS)
            *100,
            1
        )

        c1,c2,c3=st.columns(3)

        c1.metric(
            "Project Schema Match",
            f"{schema_score}%"
        )

        c2.metric(
            "Expected Fields",
            f"{len(present)}/{len(EXPECTED_COLUMNS)}"
        )

        c3.metric(
            "Additional Fields",
            len([
                column
                for column in df.columns
                if column not in EXPECTED_COLUMNS
            ])
        )

        if not missing_expected:
            html(
                """
                <div class="good">
                    <b>✓ Project source schema compatible</b><br>
                    All expected source fields are available.
                </div>
                """
            )

        else:
            html(
                f"""
                <div class="review">
                    <b>Independent CSV schema</b><br><br>
                    Missing project fields:
                    <strong>{escape(", ".join(missing_expected))}</strong>
                </div>
                """
            )

        findings=automatic_csv_insights(
            df
        )

        if findings:
            section(
                "Automatic Insights",
                "Key observations detected automatically from the uploaded dataset."
            )

            cols=st.columns(
                min(
                    3,
                    len(findings)
                )
            )

            for index,text in enumerate(
                findings[:6]
            ):
                with cols[
                    index%len(cols)
                ]:
                    insight(
                        f"Insight {index+1}",
                        text
                    )

        tabs=st.tabs([
            "📋 Overview",
            "🧹 Quality",
            "🛠 Clean",
            "⚠️ Outliers",
            "🔗 Relationships",
            "📊 Visual Lab",
            "🔎 Explorer"
        ])

        with tabs[0]:
            structure=pd.DataFrame({
                "Column":df.columns,
                "Data Type":[
                    str(df[column].dtype)
                    for column in df.columns
                ],
                "Non Null":[
                    int(df[column].notna().sum())
                    for column in df.columns
                ],
                "Missing":[
                    int(df[column].isna().sum())
                    for column in df.columns
                ],
                "Unique":[
                    int(df[column].nunique(dropna=True))
                    for column in df.columns
                ]
            })

            c1,c2=st.columns(
                [1.2,1]
            )

            with c1:
                section(
                    "Column Structure"
                )

                table(
                    structure,
                    520
                )

            with c2:
                section(
                    "Numeric Summary"
                )

                nums=df.select_dtypes(
                    include=np.number
                )

                if nums.empty:
                    empty_state(
                        "No numeric fields were detected."
                    )

                else:
                    st.dataframe(
                        nums.describe().T,
                        use_container_width=True
                    )

        with tabs[1]:
            missing=pd.DataFrame({
                "Column":df.columns,
                "Missing":df.isna().sum().values
            })

            missing["Missing %"]=(
                missing["Missing"]
                /len(df)
                *100
            ).round(2)

            missing=missing.sort_values(
                "Missing %",
                ascending=False
            )

            fig=px.bar(
                missing,
                x="Column",
                y="Missing %",
                color="Missing %",
                color_continuous_scale="Purples",
                title="Missing-Value Profile"
            )

            plot(
                fig,
                480
            )

            table(
                missing
            )

        with tabs[2]:
            section(
                "Cleaning Controls",
                "Cleaning changes only the temporary CSV Workspace copy."
            )

            c1,c2,c3,c4=st.columns(4)

            with c1:
                if st.button(
                    "Remove Duplicates",
                    use_container_width=True
                ):
                    st.session_state.csv_working_df=(
                        df.drop_duplicates()
                        .reset_index(drop=True)
                    )

                    st.rerun()

            with c2:
                if st.button(
                    "Fill Numeric Missing",
                    use_container_width=True
                ):
                    cleaned=df.copy()

                    for column in numeric_columns(
                        cleaned
                    ):
                        median=cleaned[
                            column
                        ].median()

                        cleaned[column]=cleaned[
                            column
                        ].fillna(median)

                    st.session_state.csv_working_df=cleaned

                    st.rerun()

            with c3:
                if st.button(
                    "Fill Categorical Missing",
                    use_container_width=True
                ):
                    cleaned=df.copy()

                    for column in categorical_columns(
                        cleaned
                    ):
                        mode=cleaned[
                            column
                        ].mode(
                            dropna=True
                        )

                        if not mode.empty:
                            cleaned[column]=cleaned[
                                column
                            ].fillna(
                                mode.iloc[0]
                            )

                    st.session_state.csv_working_df=cleaned

                    st.rerun()

            with c4:
                if st.button(
                    "Reset CSV",
                    use_container_width=True
                ):
                    st.session_state.csv_working_df=(
                        st.session_state
                        .uploaded_df
                        .copy()
                    )

                    st.rerun()

            download_csv(
                df,
                f"cleaned_{st.session_state.uploaded_name}",
                "cleaned_csv_download",
                "⬇ Download Current CSV"
            )

        with tabs[3]:
            outliers=outlier_summary(
                df
            )

            if outliers.empty:
                empty_state(
                    "No numeric columns are suitable for IQR-based outlier analysis."
                )

            else:
                fig=px.bar(
                    outliers.sort_values(
                        "Outlier %",
                        ascending=False
                    ),
                    x="Column",
                    y="Outlier %",
                    color="Outlier %",
                    color_continuous_scale="Purples",
                    title="Potential Outliers by Numeric Field"
                )

                plot(
                    fig,
                    480
                )

                table(
                    outliers
                )

        with tabs[4]:
            nums=numeric_columns(
                df
            )

            if len(nums)>=2:
                corr=df[
                    nums
                ].corr(
                    numeric_only=True
                )

                fig=px.imshow(
                    corr,
                    text_auto=".2f",
                    zmin=-1,
                    zmax=1,
                    aspect="auto",
                    color_continuous_scale="RdBu_r",
                    title="Numeric Correlation Matrix"
                )

                plot(
                    fig,
                    560
                )

                c1,c2,c3=st.columns(3)

                with c1:
                    x=st.selectbox(
                        "X variable",
                        nums,
                        key="csv_relation_x"
                    )

                with c2:
                    y=st.selectbox(
                        "Y variable",
                        [
                            column
                            for column in nums
                            if column!=x
                        ],
                        key="csv_relation_y"
                    )

                with c3:
                    cats=categorical_columns(
                        df
                    )

                    colour=st.selectbox(
                        "Group",
                        ["None"]+cats,
                        key="csv_relation_colour"
                    )

                selected=[
                    x,
                    y
                ]+(
                    [colour]
                    if colour!="None"
                    else []
                )

                scatter=df[
                    selected
                ].dropna()

                if len(scatter)>5000:
                    scatter=scatter.sample(
                        5000,
                        random_state=42
                    )

                fig=px.scatter(
                    scatter,
                    x=x,
                    y=y,
                    color=(
                        colour
                        if colour!="None"
                        else None
                    ),
                    opacity=.65,
                    color_discrete_sequence=PALETTE,
                    title=f"{pretty(y)} vs {pretty(x)}"
                )

                plot(
                    fig,
                    510
                )

            else:
                empty_state(
                    "At least two numeric fields are required for relationship analysis."
                )

        with tabs[5]:
            columns=df.columns.tolist()
            nums=numeric_columns(df)
            cats=categorical_columns(df)
            dates=detect_dates(df)

            c1,c2,c3,c4=st.columns(4)

            with c1:
                chart_type=st.selectbox(
                    "Chart",
                    [
                        "Bar",
                        "Line",
                        "Area",
                        "Scatter",
                        "Histogram",
                        "Box",
                        "Pie"
                    ]
                )

            with c2:
                x=st.selectbox(
                    "X axis",
                    columns
                )

            with c3:
                y=st.selectbox(
                    "Y axis",
                    ["None"]+nums
                )

            with c4:
                aggregation=st.selectbox(
                    "Aggregation",
                    [
                        "None",
                        "Count",
                        "Mean",
                        "Median",
                        "Sum",
                        "Min",
                        "Max"
                    ]
                )

            c1,c2,c3,c4=st.columns(4)

            with c1:
                colour=st.selectbox(
                    "Group",
                    ["None"]+cats
                )

            with c2:
                top_n=st.slider(
                    "Top N",
                    5,
                    50,
                    20
                )

            with c3:
                sort_order=st.selectbox(
                    "Sort",
                    [
                        "Descending",
                        "Ascending"
                    ]
                )

            with c4:
                if x in dates:
                    date_group=st.selectbox(
                        "Date aggregation",
                        [
                            "None",
                            "Daily",
                            "Weekly",
                            "Monthly"
                        ]
                    )
                else:
                    date_group="None"

            max_points=min(
                10000,
                max(
                    100,
                    len(df)
                )
            )

            sample_size=st.slider(
                "Maximum plotted records",
                100,
                max_points,
                min(
                    2000,
                    max_points
                ),
                step=100
            ) if max_points>100 else max_points

            chart_df=df.copy()

            if len(chart_df)>sample_size:
                chart_df=chart_df.sample(
                    sample_size,
                    random_state=42
                )

            group=(
                None
                if colour=="None"
                else colour
            )

            y_plot=(
                None
                if y=="None"
                else y
            )

            if (
                x in dates
                and date_group!="None"
            ):
                chart_df[x]=pd.to_datetime(
                    chart_df[x],
                    errors="coerce",
                    utc=True
                )

                chart_df=chart_df.dropna(
                    subset=[x]
                )

                frequency={
                    "Daily":"D",
                    "Weekly":"W",
                    "Monthly":"MS"
                }[date_group]

                chart_df["_period"]=(
                    chart_df[x]
                    .dt.to_period(
                        frequency
                        if frequency!="MS"
                        else "M"
                    )
                    .astype(str)
                )

                x="_period"

            if aggregation!="None":
                group_fields=[
                    x
                ]+(
                    [group]
                    if group
                    else []
                )

                if aggregation=="Count":
                    chart_df=(
                        chart_df.groupby(
                            group_fields,
                            dropna=False
                        )
                        .size()
                        .reset_index(
                            name="Value"
                        )
                    )

                    y_plot="Value"

                elif y_plot:
                    functions={
                        "Mean":"mean",
                        "Median":"median",
                        "Sum":"sum",
                        "Min":"min",
                        "Max":"max"
                    }

                    chart_df=(
                        chart_df.groupby(
                            group_fields,
                            dropna=False
                        )[y_plot]
                        .agg(
                            functions[
                                aggregation
                            ]
                        )
                        .reset_index()
                    )

            ascending=(
                sort_order=="Ascending"
            )

            fig=None

            if chart_type=="Bar":
                if y_plot:
                    chart_df=chart_df.sort_values(
                        y_plot,
                        ascending=ascending
                    ).head(top_n)

                    fig=px.bar(
                        chart_df,
                        x=x,
                        y=y_plot,
                        color=group,
                        color_discrete_sequence=PALETTE,
                        title=f"{pretty(y_plot)} by {pretty(x)}"
                    )

                else:
                    counts=(
                        chart_df[x]
                        .astype(str)
                        .value_counts()
                        .head(top_n)
                        .rename_axis(x)
                        .reset_index(
                            name="Count"
                        )
                    )

                    fig=px.bar(
                        counts,
                        x=x,
                        y="Count",
                        color="Count",
                        color_continuous_scale="Purples",
                        title=f"Top {pretty(x)} Values"
                    )

            elif chart_type=="Line" and y_plot:
                fig=px.line(
                    chart_df,
                    x=x,
                    y=y_plot,
                    color=group,
                    markers=True,
                    color_discrete_sequence=PALETTE,
                    title=f"{pretty(y_plot)} by {pretty(x)}"
                )

            elif chart_type=="Area" and y_plot:
                fig=px.area(
                    chart_df,
                    x=x,
                    y=y_plot,
                    color=group,
                    color_discrete_sequence=PALETTE,
                    title=f"{pretty(y_plot)} by {pretty(x)}"
                )

            elif chart_type=="Scatter" and y_plot:
                fig=px.scatter(
                    chart_df,
                    x=x,
                    y=y_plot,
                    color=group,
                    opacity=.65,
                    color_discrete_sequence=PALETTE,
                    title=f"{pretty(y_plot)} vs {pretty(x)}"
                )

            elif chart_type=="Histogram":
                fig=px.histogram(
                    chart_df,
                    x=x,
                    color=group,
                    nbins=40,
                    marginal="box",
                    color_discrete_sequence=PALETTE,
                    title=f"Distribution of {pretty(x)}"
                )

            elif chart_type=="Box":
                if y_plot:
                    fig=px.box(
                        chart_df,
                        x=x,
                        y=y_plot,
                        color=group,
                        points=False,
                        color_discrete_sequence=PALETTE,
                        title=f"{pretty(y_plot)} by {pretty(x)}"
                    )

                elif x in nums:
                    fig=px.box(
                        chart_df,
                        y=x,
                        points="outliers",
                        color_discrete_sequence=PALETTE,
                        title=f"Distribution of {pretty(x)}"
                    )

            elif chart_type=="Pie":
                if y_plot:
                    pie=(
                        chart_df.groupby(
                            x,
                            as_index=False
                        )[y_plot]
                        .sum()
                        .nlargest(
                            min(
                                top_n,
                                12
                            ),
                            y_plot
                        )
                    )

                    fig=px.pie(
                        pie,
                        names=x,
                        values=y_plot,
                        hole=.42,
                        color_discrete_sequence=PALETTE,
                        title=f"{pretty(y_plot)} Composition by {pretty(x)}"
                    )

                else:
                    pie=(
                        chart_df[x]
                        .astype(str)
                        .value_counts()
                        .head(
                            min(
                                top_n,
                                12
                            )
                        )
                        .rename_axis(x)
                        .reset_index(
                            name="Count"
                        )
                    )

                    fig=px.pie(
                        pie,
                        names=x,
                        values="Count",
                        hole=.42,
                        color_discrete_sequence=PALETTE,
                        title=f"{pretty(x)} Composition"
                    )

            if fig is not None:
                plot(
                    fig,
                    540
                )

            else:
                empty_state(
                    "Choose compatible X and Y fields for the selected chart."
                )

        with tabs[6]:
            search=st.text_input(
                "Search all visible fields",
                placeholder="Search values..."
            )

            visible_columns=st.multiselect(
                "Visible columns",
                df.columns.tolist(),
                default=df.columns.tolist()
            )

            filtered=(
                df[
                    visible_columns
                ].copy()
                if visible_columns
                else df.copy()
            )

            low_cardinality=[
                column
                for column in filtered.columns
                if (
                    filtered[column]
                    .nunique(
                        dropna=True
                    )
                    >1
                )
                and (
                    filtered[column]
                    .nunique(
                        dropna=True
                    )
                    <=50
                )
            ]

            if low_cardinality:
                category_filter=st.selectbox(
                    "Category filter",
                    [
                        "None"
                    ]+low_cardinality
                )

                if category_filter!="None":
                    options=sorted(
                        filtered[
                            category_filter
                        ]
                        .dropna()
                        .astype(str)
                        .unique()
                        .tolist()
                    )

                    selected_values=st.multiselect(
                        "Keep values",
                        options,
                        default=options
                    )

                    filtered=filtered[
                        filtered[
                            category_filter
                        ]
                        .astype(str)
                        .isin(
                            selected_values
                        )
                    ]

            if search:
                mask=filtered.astype(str).apply(
                    lambda series:
                    series.str.contains(
                        search,
                        case=False,
                        na=False
                    )
                ).any(axis=1)

                filtered=filtered[mask]

            c1,c2,c3=st.columns(3)

            c1.metric(
                "Filtered Rows",
                f"{len(filtered):,}"
            )

            c2.metric(
                "Visible Columns",
                len(filtered.columns)
            )

            c3.metric(
                "Rows Retained",
                (
                    f"{len(filtered)/len(df)*100:.1f}%"
                    if len(df)
                    else "0%"
                )
            )

            table(
                filtered,
                560
            )

            download_csv(
                filtered,
                f"filtered_{st.session_state.uploaded_name}",
                "filtered_uploaded_csv"
            )

elif page=="System Diagnostics":
    section(
        "Operational Health",
        "Live runtime status, endpoint monitoring, evidence capture and exports."
    )

    cols=st.columns(5)

    values=[
        ("API",API_STATUS),
        (
            "Health Latency",
            (
                f"{API_LATENCY} ms"
                if API_LATENCY is not None
                else "—"
            )
        ),
        ("Logger",LOGGER_STATUS),
        (
            "Screenshots",
            len(
                list(
                    SHOT_DIR.glob("*.png")
                )
            )
        ),
        ("CSV",CSV_STATUS)
    ]

    for col,(label,value) in zip(
        cols,
        values
    ):
        with col:
            st.metric(
                label,
                value
            )

    tabs=st.tabs([
        "⚙️ API Health",
        "⏱ Endpoint Monitor",
        "📸 Evidence",
        "📦 Export Center",
        "⚠️ Limitations",
        "🏗 Architecture"
    ])

    with tabs[0]:
        if isinstance(health,dict):
            st.json(health)
        else:
            table(health)

    with tabs[1]:
        telemetry=pd.DataFrame(
            st.session_state.api_telemetry.values()
        )

        if telemetry.empty:
            empty_state(
                "Endpoint telemetry will appear as API endpoints are used."
            )

        else:
            table(
                telemetry,
                420
            )

            numeric_latency=pd.to_numeric(
                telemetry["Latency ms"],
                errors="coerce"
            )

            valid=telemetry[
                numeric_latency.notna()
            ].copy()

            valid["Latency ms"]=numeric_latency[
                numeric_latency.notna()
            ]

            if not valid.empty:
                fig=px.bar(
                    valid.sort_values(
                        "Latency ms"
                    ),
                    x="Endpoint",
                    y="Latency ms",
                    color="Latency ms",
                    color_continuous_scale="Purples",
                    title="API Endpoint Latency"
                )

                plot(
                    fig,
                    450
                )

    with tabs[2]:
        screenshots=sorted(
            SHOT_DIR.glob("*.png"),
            key=lambda path:
            path.stat().st_mtime,
            reverse=True
        )

        evidence=pd.DataFrame([
            {
                "Screenshot":file.name,
                "Captured":
                    datetime.fromtimestamp(
                        file.stat().st_mtime
                    ).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                "Size KB":
                    round(
                        file.stat().st_size/1024,
                        1
                    )
            }
            for file in screenshots
        ])

        table(
            evidence
        )

        if screenshots:
            gallery=st.columns(3)

            for index,file in enumerate(
                screenshots[:6]
            ):
                with gallery[index%3]:
                    st.image(
                        str(file),
                        caption=file.name,
                        use_container_width=True
                    )

    with tabs[3]:
        section(
            "Client Evidence Package",
            "Download analysis outputs, API health information, methodology and screenshot evidence in one archive."
        )

        package=evidence_package()

        st.download_button(
            "📦 Download Complete Client Evidence Package",
            package,
            "job_market_client_evidence.zip",
            "application/zip",
            use_container_width=True,
            key="evidence_package_download"
        )

        screenshot_archive=screenshot_zip()

        if screenshot_archive:
            st.download_button(
                "📸 Download Screenshot Evidence Only",
                screenshot_archive,
                "streamlit_screenshot_evidence.zip",
                "application/zip",
                use_container_width=True,
                key="screenshot_archive_download"
            )

        if st.session_state.uploaded_df is not None:
            download_csv(
                st.session_state.uploaded_df,
                st.session_state.uploaded_name,
                "original_uploaded_csv",
                "📁 Download Original Uploaded CSV"
            )

    with tabs[4]:
        insight(
            "Known source limitations",
            "No verified remote-work field, explicit skills field, verified experience requirement, company field or reliable currency field is available.",
            "limit"
        )

        insight(
            "Historical interpretation",
            "The platform describes the supplied historical job-market snapshot and should not be presented as a current live labour-market feed.",
            "limit"
        )

    with tabs[5]:
        html(
            """
            <div class="info">

                <b>Production Architecture</b><br><br>

                <strong>stream.py</strong>
                &nbsp; → &nbsp;

                <strong>Flask REST API</strong>
                &nbsp; → &nbsp;

                <strong>Services / Inference</strong>
                &nbsp; → &nbsp;

                <strong>Models + SQL Server</strong>

                <br><br>

                Uploaded CSV files remain isolated inside CSV Workspace
                and do not automatically replace validated production
                data or trained model artifacts.

            </div>
            """
        )

methodology()

if (
    st.session_state.last_auto_page
    !=page
):
    screenshot_data,path=capture_screenshot(
        f"auto_{page}"
    )

    if screenshot_data:
        st.session_state.latest_screenshot=screenshot_data
        st.session_state.latest_screenshot_name=path.name
        st.session_state.last_auto_page=page

if st.session_state.latest_screenshot:
    st.markdown("---")

    left,right=st.columns(
        [3,1]
    )

    with left:
        st.caption(
            "📸 Latest evidence · "
            +st.session_state.latest_screenshot_name
        )

    with right:
        st.download_button(
            "⬇ Download Screenshot",
            st.session_state.latest_screenshot,
            st.session_state.latest_screenshot_name,
            "image/png",
            use_container_width=True,
            key=f"bottom_screenshot_{page}"
        )

html(
    """
    <div class="footer">

        Job Market Intelligence Platform
        &nbsp; • &nbsp;
        Market Analytics
        &nbsp; • &nbsp;
        Forecasting
        &nbsp; • &nbsp;
        Recommendation
        &nbsp; • &nbsp;
        CSV Intelligence
        &nbsp; • &nbsp;
        Client Decision Support

    </div>
    """
)

logger.info(
    "STREAMLIT_PAGE | page=%s | api=%s | logger=%s | latency_ms=%s | csv=%s",
    page,
    API_STATUS,
    LOGGER_STATUS,
    API_LATENCY,
    CSV_STATUS
)