"""供應鏈選股 Agent — 評估台灣股票與美國科技需求的供應鏈關聯性。"""
import httpx
import json
import logging
import time
from dataclasses import dataclass

from ..gemini_usage import record_gemini_call, redact_secrets

logger = logging.getLogger(__name__)

# 預設供應鏈分數（已知公司的靜態知識，減少 Gemini 呼叫次數）
_KNOWN_SCORES: dict[str, tuple[float, str]] = {
    "2330.TW": (95, "全球最大晶圓代工廠，為 NVIDIA/Apple/AMD 生產晶片，與美國科技需求高度連動"),
    "2454.TW": (80, "全球第二大無廠半導體，產品廣泛應用於智慧型手機與 IoT"),
    "2317.TW": (72, "全球最大 EMS 廠，組裝 iPhone 等美國品牌產品，與消費電子景氣高度相關"),
    "3008.TW": (78, "全球最大手機鏡頭廠，Apple iPhone 主要供應商，直接受惠 iPhone 出貨"),
    "2308.TW": (70, "全球最大電源供應器廠，客戶涵蓋 Dell/HP/Google 等美國企業"),
    "2382.TW": (68, "全球前三大筆電代工廠，主要客戶為 Apple/Dell/HP"),
    "2303.TW": (80, "全球前五大晶圓代工廠，生產成熟製程晶片，受惠半導體景氣復甦"),
    "2379.TW": (65, "全球領先網通晶片廠，產品應用於 Wi-Fi 路由器與以太網"),
    "2395.TW": (55, "工業自動化與 IoT 方案廠，終端市場較分散"),
    "3711.TW": (75, "全球最大 IC 封裝廠，受惠 AI 先進封裝需求"),
    "2357.TW": (50, "消費電子品牌廠，直接與美國品牌競爭，關聯度中等"),
    "4938.TW": (65, "Apple 組裝二線廠，直接受益 iPhone 出貨"),
    "2344.TW": (60, "DRAM 廠商，受記憶體景氣週期影響"),
    "5483.TW": (45, "半導體測試設備廠，間接受惠半導體資本支出"),
    "2353.TW": (40, "PC 品牌廠，與美國科技需求關聯度較低"),
}


@dataclass
class SupplyChainResult:
    symbol: str
    supply_chain_score: float  # 0-100
    us_tech_exposure: str  # "HIGH" | "MEDIUM" | "LOW"
    key_customers: list[str]
    supply_chain_summary: str
    risks: list[str]


async def analyze_supply_chain(symbol: str) -> SupplyChainResult:
    """
    評估股票與美國科技需求的供應鏈關聯性。
    優先使用靜態知識庫，未知股票才呼叫 Gemini。
    """
    # 靜態知識庫直接回傳
    if symbol in _KNOWN_SCORES:
        score, summary = _KNOWN_SCORES[symbol]
        if score >= 70:
            exposure = "HIGH"
        elif score >= 45:
            exposure = "MEDIUM"
        else:
            exposure = "LOW"
        return SupplyChainResult(
            symbol=symbol,
            supply_chain_score=float(score),
            us_tech_exposure=exposure,
            key_customers=_guess_customers(symbol),
            supply_chain_summary=summary,
            risks=_default_risks(symbol),
        )

    # 未知股票：使用 Gemini 分析
    return await _analyze_with_gemini(symbol)


def _guess_customers(symbol: str) -> list[str]:
    _customers = {
        "2330.TW": ["NVIDIA", "Apple", "AMD", "Qualcomm"],
        "2454.TW": ["Samsung", "Xiaomi", "Google"],
        "2317.TW": ["Apple", "Microsoft", "Google", "Dell"],
        "3008.TW": ["Apple"],
        "2308.TW": ["Dell", "HP", "Google", "Microsoft"],
        "2382.TW": ["Apple", "Dell", "HP"],
        "2303.TW": ["NXP", "STMicro", "Texas Instruments"],
        "2379.TW": ["TP-Link", "Netgear", "ASUS"],
        "3711.TW": ["Intel", "AMD", "NVIDIA", "Apple"],
        "4938.TW": ["Apple"],
    }
    return _customers.get(symbol, [])


def _default_risks(symbol: str) -> list[str]:
    high_exposure = {"2330.TW", "2454.TW", "2317.TW", "3008.TW", "2303.TW", "3711.TW"}
    if symbol in high_exposure:
        return ["美國出口管制風險", "台海地緣政治風險", "大客戶集中度風險"]
    return ["美中貿易摩擦風險", "台海地緣政治風險"]


async def _analyze_with_gemini(symbol: str) -> SupplyChainResult:
    """對未知股票使用 Gemini 評估供應鏈關聯性。"""
    from ...config import get_settings
    settings = get_settings()

    _default = SupplyChainResult(
        symbol=symbol,
        supply_chain_score=40.0,
        us_tech_exposure="LOW",
        key_customers=[],
        supply_chain_summary="無供應鏈資料",
        risks=["地緣政治風險"],
    )

    if not settings.gemini_api_key:
        return _default

    prompt = f"""
你是台灣供應鏈分析師。評估以下台灣股票與美國科技產業的供應鏈關聯性，回覆必須是合法 JSON。

股票代號：{symbol}

問題：
1. 這家公司的主要客戶是哪些美國科技企業？
2. 這家公司在美國科技供應鏈中扮演什麼角色？
3. 當 NASDAQ/QQQ 上漲（科技需求強勁）時，這家公司的業務受益程度？

JSON 格式：
{{
    "supply_chain_score": 0到100的整數,
    "us_tech_exposure": "HIGH或MEDIUM或LOW",
    "key_customers": ["客戶1", "客戶2"],
    "supply_chain_summary": "供應鏈角色一句話說明",
    "risks": ["風險1", "風險2"]
}}
"""

    _t0 = time.monotonic()
    _logged = False
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                "https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent",
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": settings.gemini_api_key,
                },
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 400},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            await record_gemini_call("supply_chain_agent", symbol, _t0, data=data)
            _logged = True
            raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            r = json.loads(raw)
            return SupplyChainResult(
                symbol=symbol,
                supply_chain_score=float(r.get("supply_chain_score", 40)),
                us_tech_exposure=r.get("us_tech_exposure", "LOW"),
                key_customers=r.get("key_customers", []),
                supply_chain_summary=r.get("supply_chain_summary", ""),
                risks=r.get("risks", []),
            )
    except Exception as e:
        if not _logged:
            await record_gemini_call("supply_chain_agent", symbol, _t0, error=e)
        logger.error(f"supply_chain_agent {symbol} error: {redact_secrets(str(e))}")
        return _default
