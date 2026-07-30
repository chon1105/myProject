import pandas as pd
import plotly.express as px
import requests
import streamlit as st

# 페이지 기본 설정
st.set_page_config(
    page_title="전국 시군구 고령화 지도",
    layout="wide",
)


# 1. 데이터 로딩 및 전처리 함수 (캐싱 적용으로 속도 최적화)
@st.cache_data
def load_data():
    # 인구 데이터 불러오기 (압축된 Gzip CSV 파일)
    pop_url = "https://raw.githubusercontent.com/greatsong/modudata/main/data/population_yearly.csv.gz"

    # 코드(행정동 코드) 열은 반드시 문자열(string)로 읽어 앞자리 0이 손실되지 않도록 함
    df = pd.read_csv(pop_url, compression="gzip", dtype={"코드": str})

    # 가장 최신 연도 데이터만 필터링
    latest_year = df["연도"].max()
    df_latest = df[df["연도"] == latest_year].copy()

    # '코드' 열의 앞 5자리를 추출하여 5자리 시군구 코드 생성
    df_latest["시군구코드"] = df_latest["코드"].str.slice(0, 5)

    # 65세 이상 인구 열 찾기 ('계_65세'부터 '계_100세 이상'까지)
    # '계_'로 시작하면서 나이가 65세 이상인 열 추출
    total_cols = [
        col
        for col in df_latest.columns
        if col.startswith("계_") and col != "계_전체인구"
    ]

    elderly_cols = []
    for col in total_cols:
        # '계_65세' 형태에서 숫자 부분만 추출
        age_str = col.replace("계_", "").replace("세", "").replace(" 이상", "")
        if age_str.isdigit() and int(age_str) >= 65:
            elderly_cols.append(col)

    # 시군구 단위로 인구 합산 (시도, 시군구, 시군구코드 기준 그룹화)
    # 전체 인구 합계와 65세 이상 인구 합계 계산
    df_latest["전체인구"] = df_latest[total_cols].sum(axis=1)
    df_latest["고령인구"] = df_latest[elderly_cols].sum(axis=1)

    grouped = (
        df_latest.groupby(["시도", "시군구", "시군구코드"])[
            ["전체인구", "고령인구"]
        ]
        .sum()
        .reset_index()
    )

    # 고령화율(%) 계산 (65세 이상 인구 / 전체 인구 * 100)
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


# GeoJSON 경계 데이터 로딩 함수
@st.cache_data
def load_geojson():
    geojson_url = "https://raw.githubusercontent.com/greatsong/modudata/main/data/boundaries/sigungu_kr.geojson"
    response = requests.get(geojson_url)
    return response.json()


# 메인 화면 구성
st.title("🗺️ 전국 시군구 고령화율 지도")

# 데이터 및 GeoJSON 불러오기
data, latest_year = load_data()
geojson = load_geojson()

st.write(f"**기준 연도:** {latest_year}년 (시군구 단위 65세 이상 인구 비율)")

# 색상 매핑 (연한 색에서 진한 색으로 5단계 설정)
color_discrete_map = {
    "19% 미만": "#edf8fb",
    "19% 이상 ~ 23% 미만": "#b2e2e2",
    "23% 이상 ~ 28% 미만": "#66c2a4",
    "28% 이상 ~ 38% 미만": "#2ca25f",
    "38% 이상": "#006d2c",
}

# Plotly 단계구분도(Choropleth Map) 생성
fig = px.choropleth_mapbox(
    data,
    geojson=geojson,
    locations="시군구코드",  # GeoJSON 매핑 기준 키 (데이터)
    featureidkey="properties.코드",  # GeoJSON 매핑 기준 키 (GeoJSON 속성)
    color="고령화율_구간",  # 5단계 범주화 열 적용
    color_discrete_map=color_discrete_map,
    category_orders={"고령화율_구간": list(color_discrete_map.keys())},
    center={"lat": 36.35, "lon": 127.8},  # 대한민국 중심 좌표
    zoom=6,
    mapbox_style="white-bg",  # 배경 타일 없이 경계선만 표시
    hover_name="시군구",  # 마우스 올렸을 때 굵은 글씨로 표시될 이름
    hover_data={
        "시도": True,
        "고령화율": ":.1f%",  # 소수점 첫째자리 및 % 표시
        "시군구코드": False,  # 툴팁에서 코드 숨김
        "고령화율_구간": False,  # 툴팁에서 구간 라벨 숨김
    },
    labels={"고령화율": "고령화율", "시도": "시도"},
)

# 지도 레이아웃 세부 설정
fig.update_layout(
    margin={"r": 0, "t": 10, "l": 0, "b": 10},
    legend_title_text="고령화율 구간",
    legend=dict(yanchor="top", y=0.98, xanchor="left", x=0.01),
)

# 스트림릿에 지도 출력
st.plotly_chart(fig, use_container_width=True)

st.markdown("---")

# 지도 하단: 고령화율 상위/하위 10개 지역 표 구성
col1, col2 = st.columns(2)

# 화면용 표 컬럼 재정의
table_df = data[["시도", "시군구", "고령화율", "전체인구", "고령인구"]].copy()

with col1:
    st.subheader("🔴 고령화율 가장 높은 곳 Top 10")
    top10 = (
        table_df.sort_values(by="고령화율", ascending=False)
        .head(10)
        .reset_index(drop=True)
    )
    # 인구 수에 천 단위 쉼표 추가
    top10["전체인구"] = top10["전체인구"].apply(lambda x: f"{x:,}명")
    top10["고령인구"] = top10["고령인구"].apply(lambda x: f"{x:,}명")
    top10["고령화율"] = top10["고령화율"].apply(lambda x: f"{x:.1f}%")
    st.dataframe(top10, use_container_width=True)

with col2:
    st.subheader("🔵 고령화율 가장 낮은 곳 Top 10")
    bottom10 = (
        table_df.sort_values(by="고령화율", ascending=True)
        .head(10)
        .reset_index(drop=True)
    )
    bottom10["전체인구"] = bottom10["전체인구"].apply(lambda x: f"{x:,}명")
    bottom10["고령인구"] = bottom10["고령인구"].apply(lambda x: f"{x:,}명")
    bottom10["고령화율"] = bottom10["고령화율"].apply(lambda x: f"{x:.1f}%")
    st.dataframe(bottom10, use_container_width=True)
