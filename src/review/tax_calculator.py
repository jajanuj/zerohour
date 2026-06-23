TAX_RATES = {
    "stock_transaction_tax": 0.003,
    "futures_transaction_tax": 0.00002,
    "broker_commission_rate": 0.001425,
    "capital_gains_tax": 0.0,
}


def calculate_after_tax_pnl(
    gross_pnl: float,
    instrument: str,
    transaction_value: float,
    commission_discount: float = 0.6,
) -> dict:
    """
    計算稅後淨損益。

    Args:
        gross_pnl:            毛利
        instrument:           "stock" | "futures"
        transaction_value:    成交金額
        commission_discount:  手續費折扣率（通常 0.6 = 6折）
    """
    if instrument == "stock":
        tax = transaction_value * TAX_RATES["stock_transaction_tax"]
        commission = (
            transaction_value
            * TAX_RATES["broker_commission_rate"]
            * commission_discount
            * 2
        )
    else:
        tax = TAX_RATES["futures_transaction_tax"] * transaction_value
        commission = 80 * 2  # NT$80/口 × 買賣各一次

    total_cost = tax + commission
    net_pnl = gross_pnl - total_cost

    return {
        "gross_pnl": round(gross_pnl, 2),
        "tax": round(tax, 2),
        "commission": round(commission, 2),
        "total_cost": round(total_cost, 2),
        "net_pnl": round(net_pnl, 2),
        "cost_drag_pct": round(total_cost / transaction_value * 100, 4) if transaction_value else 0.0,
    }
