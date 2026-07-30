import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

# 페이지 기본 설정
st.set_page_config(
    page_title="전국 시군구 고령화 지도",
    layout="wide",
)


# 1. 데이터 로딩 및 전처리 함수 (캐싱 적용)
@st.cache_data
def load_data():
    # 인구 데이터 불러오기 (압축된 Gzip CSV 파일)
    pop_url = "https://raw.githubusercontent.com/greatsong/modudata/main/data/population_yearly.csv.gz"

    # 코드(행정동 코드) 열을 문자열로 읽고 10자리 포맷 맞춤
    df = pd.read_csv(pop_url, compression="gzip", dtype={"코드": str})
    df["코드"] = df["코드"].astype(str).str.zfill(10)

    # 가장 최신 연도 데이터만 필터링
    latest_year = df["연도"].max()
    df_latest = df[df["연도"] == latest_year].copy()

    # '코드' 열의 앞 5자리를 추출하여 5자리 시군구 코드 생성
    df_latest["시군구코드"] = df_latest["코드"].str.slice(0, 5)

    # 65세 이상 인구 열 찾기 ('계_65세'부터 '계_100세 이상'까지)
    total_cols = [
        col
        for col in df_latest.columns
        if col.startswith("계_") and col != "계_전체인구"
    ]

    elderly_cols = []
    for col in total_cols:
        age_str = col.replace("계_", "").replace("세", "").replace(" 이상", "")
        if age_str.isdigit() and int(age_str) >= 65:
            elderly_cols.append(col)

    # 시군구 단위로 인구 합산
    df_latest["전체인구"] = df_latest[total_cols].sum(axis=1)
    df_latest["고령인구"] = df_latest[elderly_cols].sum(axis=1)

    grouped = (
        df_latest.groupby(["시도", "시군구", "시군구코드"])[
            ["전체인구", "고령인구"]
        ]
        .sum()
        .reset_index()
    )

    # 고령화율(%) 계산
    grouped["고령화율"] = (grouped["고령인구"] / grouped["전체인구"]) * 100
    grouped["고령화율"] = grouped["고령화율"].round(1)

    # 5단계 범주화 (경계값: 19%, 23%, 28%, 38%)
    bins = [-1, 19, 23, 28, 38, 100]
    labels = [
        "19% 미만",
        "19% 이상 ~ 23% 미만",
        "23% 이상 ~ 28% 미만",
        "28% 이상 ~ 38% 미만",
        "38% 이상",
    ]

    grouped["고령화율_구간"] = pd.cut(
        grouped["고령화율"], bins=bins, labels=labels
    )

    return grouped, latest_year


# 2. GeoJSON 데이터 및 중심 좌표(위경도) 자동 계산 함수
@st.cache_data
def load_geojson_and_centroids():
    geojson_url = "https://raw.githubusercontent.com/greatsong/modudata/main/data/boundaries/sigungu_kr.geojson"
    response = requests.get(geojson_url)
    geojson_data = response.json()

    centroids = {}
    for feature in geojson_data.get("features", []):
        # GeoJSON 내부 코드값을 5자리 문자열로 표준화하여 매핑 오류 완전 방지
        raw_code = str(feature.get("properties", {}).get("코드", "")).strip()
        code = raw_code[:5].zfill(5) if raw_code else ""

        # GeoJSON 속성 코드 업데이트
        feature["properties"]["코드"] = code

        geom = feature.get("geometry", {})
        coords = geom.get("coordinates", [])

        lons, lats = [], []

        def extract_coords(c_list):
            if not c_list:
                return
            if isinstance(c_list[0], (int, float)):
                lons.append(c_list[0])
                lats.append(c_list[1])
            else:
                for sub in c_list:
                    extract_coords(sub)

        extract_coords(coords)

        if lons and lats and code:
            centroids[code] = {
                "lat": sum(lats) / len(lats),
                "lon": sum(lons) / len(lons),
            }

    return geojson_data, centroids


# 메인 화면 구성
st.title("🗺️ 전국 시군구 고령화율 지도")

# 데이터 로딩
data, latest_year = load_data()
geojson, centroids = load_geojson_and_centroids()

# 상위 10개, 하위 10개 표 데이터 추출
display_cols = [
    "시도",
    "시군구",
    "고령화율",
    "전체인구",
    "고령인구",
    "시군구코드",
    "고령화율_구간",
]

top10 = (
    data[display_cols]
    .sort_values(by="고령화율", ascending=False)
    .head(10)
    .reset_index(drop=True)
)

bottom10 = (
    data[display_cols]
    .sort_values(by="고령화율", ascending=True)
    .head(10)
    .reset_index(drop=True)
)


# 표 클릭 이벤트 또는 검색 선택에 의해 지정될 선택 코드 추적
selected_code = None

# 1) 상위 10개 표 선택 상태 확인
if "top10_table" in st.session_state:
    rows = st.session_state.top10_table.get("selection", {}).get("rows", [])
    if rows:
        selected_code = top10.iloc[rows[0]]["시군구코드"]

# 2) 하위 10개 표 선택 상태 확인
if "bottom10_table" in st.session_state:
    rows = st.session_state.bottom10_table.get("selection", {}).get("rows", [])
    if rows and selected_code is None:
        selected_code = bottom10.iloc[rows[0]]["시군구코드"]

# 3) 지역 셀렉트박스로 직접 선택할 수도 있도록 상단에 수단 제공
region_options = ["전국 전체 보기"] + [
    f"{row['시도']} {row['시군구']}" for _, row in data.iterrows()
]
selected_region_str = st.selectbox(
    "🔍 지역 직접 검색/선택",
    region_options,
    help="목록에서 원하는 지역을 선택하거나 하단 표에서 클릭하면 해당 위치가 지도에 강조됩니다.",
)

if selected_region_str != "전국 전체 보기":
    sido, sigungu = selected_region_str.split(" ", 1)
    matched = data[(data["시도"] == sido) & (data["시군구"] == sigungu)]
    if not matched.empty:
        selected_code = matched.iloc[0]["시군구코드"]


# 기본 지도 위치 및 줌 레벨
center_lat, center_lon = 36.35, 127.8
zoom_level = 6.0  # 전국 보기 줌

selected_info = None

# 선택된 지역이 있을 경우 지도 중심 이동 및 20% 확대 적용
if selected_code and selected_code in centroids:
    center_lat = centroids[selected_code]["lat"]
    center_lon = centroids[selected_code]["lon"]
    zoom_level = 7.5  # 기존 6.0 대비 20% 이상 확대

    matched_row = data[data["시군구코드"] == selected_code]
    if not matched_row.empty:
        selected_info = matched_row.iloc[0]

# 상단 안내 및 선택 상태 표시
st.write(
    f"**기준 연도:** {latest_year}년 | 💡 **하단 표의 지역을 클릭하거나 위 검색창을 이용해 지도 위치를 확대해 보세요.**"
)

if selected_info is not None:
    st.info(
        f"📍 **선택된 지역:** [{selected_info['시도']} {selected_info['시군구']}] | "
        f"**고령화율:** {selected_info['고령화율']:.1f}% | "
        f"**전체인구:** {selected_info['전체인구']:,}명 | "
        f"**고령인구:** {selected_info['고령인구']:,}명 | "
        f"**구간:** {selected_info['고령화율_구간']}"
    )

# 5단계 범주화 색상 매핑
color_discrete_map = {
    "19% 미만": "#edf8fb",
    "19% 이상 ~ 23% 미만": "#b2e2e2",
    "23% 이상 ~ 28% 미만": "#66c2a4",
    "28% 이상 ~ 38% 미만": "#2ca25f",
    "38% 이상": "#006d2c",
}

# Plotly 단계구분도 생성
fig = px.choropleth_mapbox(
    data,
    geojson=geojson,
    locations="시군구코드",
    featureidkey="properties.코드",
    color="고령화율_구간",
    color_discrete_map=color_discrete_map,
    category_orders={"고령화율_구간": list(color_discrete_map.keys())},
    center={"lat": center_lat, "lon": center_lon},
    zoom=zoom_level,
    mapbox_style="white-bg",
    hover_name="시군구",
    hover_data={
        "시도": True,
        "고령화율": ":.1f%",
        "시군구코드": False,
        "고령화율_구간": False,
    },
    labels={"고령화율": "고령화율", "시도": "시도"},
)

# 선택된 지역 위치에 강렬한 핀 마커 및 텍스트 박스 표시
if selected_info is not None:
    fig.add_trace(
        go.Scattermapbox(
            lat=[center_lat],
            lon=[center_lon],
            mode="markers+text",
            marker=dict(size=18, color="red"),
            text=[f"📍 {selected_info['시군구']}"],
            textposition="top center",
            hoverinfo="text",
            hovertext=(
                f"<b>{selected_info['시도']} {selected_info['시군구']}</b><br>"
                f"고령화율: {selected_info['고령화율']:.1f}%<br>"
                f"전체인구: {selected_info['전체인구']:,}명<br>"
                f"고령인구: {selected_info['고령인구']:,}명"
            ),
            showlegend=False,
        )
    )

# 지도 레이아웃 설정
fig.update_layout(
    margin={"r": 0, "t": 10, "l": 0, "b": 10},
    legend_title_text="고령화율 구간",
    legend=dict(yanchor="top", y=0.98, xanchor="left", x=0.01),
)

# 지도 표시
st.plotly_chart(fig, use_container_width=True)

st.markdown("---")

# 지도 하단: 고령화율 Top 10 / Bottom 10 선택 가능한 표
col1, col2 = st.columns(2)

with col1:
    st.subheader("🔴 고령화율 가장 높은 곳 Top 10")
    formatted_top10 = top10[["시도", "시군구", "고령화율", "전체인구", "고령인구"]].copy()
    formatted_top10["전체인구"] = formatted_top10["전체인구"].apply(
        lambda x: f"{x:,}명"
    )
    formatted_top10["고령인구"] = formatted_top10["고령인구"].apply(
        lambda x: f"{x:,}명"
    )
    formatted_top10["고령화율"] = formatted_top10["고령화율"].apply(
        lambda x: f"{x:.1f}%"
    )

    st.dataframe(
        formatted_top10,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        key="top10_table",
    )

with col2:
    st.subheader("🔵 고령화율 가장 낮은 곳 Top 10")
    formatted_bottom10 = bottom10[
        ["시도", "시군구", "고령화율", "전체인구", "고령인구"]
    ].copy()
    formatted_bottom10["전체인구"] = formatted_bottom10["전체인구"].apply(
        lambda x: f"{x:,}명"
    )
    formatted_bottom10["고령인구"] = formatted_bottom10["고령인구"].apply(
        lambda x: f"{x:,}명"
    )
    formatted_bottom10["고령화율"] = formatted_bottom10["고령화율"].apply(
        lambda x: f"{x:.1f}%"
    )

    st.dataframe(
        formatted_bottom10,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        key="bottom10_table",
    )
