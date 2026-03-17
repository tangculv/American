from __future__ import annotations

from dataclasses import dataclass
import json


SHARP_DROP_PCT = -5.0
DRAWDOWN_THRESHOLD = 15.0
ROE_DROP_THRESHOLD = 5.0
FUNDAMENTAL_DE_RATIO_THRESHOLD = 2.0
LEVERAGE_THRESHOLD = 4.0
TECHNICAL_VOLUME_SPIKE_MULTIPLIER = 2.0
EARNINGS_DAYS_THRESHOLD = 3
STOP_LOSS_PCT = -8.0
PROFIT_TARGET_PCT = 20.0
OVERVALUATION_MULTIPLIER = 1.5
RSI_OVERBOUGHT = 70
VALID_ACTIONS = ["继续持有", "重点关注", "考虑减仓", "考虑止盈", "考虑止损", "考虑清仓"]


@dataclass
class Signal:
    type: str
    level: str
    action: str
    value: float | None = None
    threshold: float | None = None
    detail: str | None = None


class AlertEngine:
    """Signal detection engine for post-buy monitoring."""

    def detect_signals(
        self,
        symbol: str,
        snapshot: dict,
        research: dict | None,
        position: dict | None,
    ) -> list[Signal]:
        signals: list[Signal] = []
        signals.extend(self._check_risk_warnings(symbol, snapshot, research))
        if position is not None:
            signals.extend(self._check_sell_reminders(symbol, snapshot, research, position))
        return signals

    def _check_risk_warnings(
        self,
        symbol: str,
        snapshot: dict,
        research: dict | None,
    ) -> list[Signal]:
        signals: list[Signal] = []
        daily_change_pct = snapshot.get("daily_change_pct")
        if daily_change_pct is not None and float(daily_change_pct) <= SHARP_DROP_PCT:
            signals.append(
                Signal(
                    type="急跌预警",
                    level="warning",
                    action="重点关注",
                    value=float(daily_change_pct),
                    threshold=SHARP_DROP_PCT,
                )
            )

        price = snapshot.get("price")
        if price is not None:
            drawdown = self._calc_drawdown(symbol, float(price), snapshot=snapshot)
            if drawdown >= DRAWDOWN_THRESHOLD:
                signals.append(
                    Signal(
                        type="阶段回撤",
                        level="warning",
                        action="重点关注",
                        value=drawdown,
                        threshold=DRAWDOWN_THRESHOLD,
                    )
                )

        if research:
            prev_roe = research.get("prev_roe")
            roe = research.get("roe")
            roe_drop = None
            if prev_roe is not None and roe is not None:
                roe_drop = float(prev_roe) - float(roe)

            prev_net_margin = research.get("prev_net_margin", snapshot.get("prev_net_margin"))
            curr_net_margin = research.get("curr_net_margin", snapshot.get("curr_net_margin"))
            curr_de_ratio = research.get("curr_de_ratio", snapshot.get("curr_de_ratio"))

            fundamental_reasons: list[str] = []
            if roe_drop is not None and roe_drop >= ROE_DROP_THRESHOLD:
                fundamental_reasons.append(f"ROE 下降 {roe_drop:.1f} 个百分点")
            if (
                prev_net_margin is not None
                and curr_net_margin is not None
                and float(prev_net_margin) > 0
                and float(curr_net_margin) < 0
            ):
                fundamental_reasons.append("净利率由正转负")
            if curr_de_ratio is not None and float(curr_de_ratio) >= FUNDAMENTAL_DE_RATIO_THRESHOLD:
                fundamental_reasons.append(f"负债权益比升至 {float(curr_de_ratio):.1f}")

            if fundamental_reasons:
                signals.append(
                    Signal(
                        type="基本面恶化",
                        level="warning",
                        action="重点关注",
                        value=roe_drop if roe_drop is not None and roe_drop >= ROE_DROP_THRESHOLD else None,
                        threshold=ROE_DROP_THRESHOLD if roe_drop is not None and roe_drop >= ROE_DROP_THRESHOLD else None,
                        detail="；".join(fundamental_reasons),
                    )
                )

            nde_ratio = research.get("net_debt_to_ebitda")
            if nde_ratio is not None and float(nde_ratio) >= LEVERAGE_THRESHOLD:
                signals.append(
                    Signal(
                        type="杠杆风险升级",
                        level="warning",
                        action="重点关注",
                        value=float(nde_ratio),
                        threshold=LEVERAGE_THRESHOLD,
                    )
                )

        ma_50 = snapshot.get("ma_50")
        ma_200 = snapshot.get("ma_200")
        prev_ma_50 = snapshot.get("prev_ma_50")
        prev_ma_200 = snapshot.get("prev_ma_200")
        death_cross = (
            None not in (ma_50, ma_200, prev_ma_50, prev_ma_200)
            and float(ma_50) < float(ma_200)
            and float(prev_ma_50) >= float(prev_ma_200)
        )
        avg_volume_20d = snapshot.get("avg_volume_20d")
        curr_volume = snapshot.get("volume")
        volume_spike_with_down = (
            curr_volume is not None
            and avg_volume_20d is not None
            and float(avg_volume_20d) > 0
            and float(curr_volume) >= float(avg_volume_20d) * TECHNICAL_VOLUME_SPIKE_MULTIPLIER
            and daily_change_pct is not None
            and float(daily_change_pct) < 0
        )
        if death_cross or volume_spike_with_down:
            detail = "50日均线下穿200日均线（死叉）" if death_cross else "成交量异常放大且当日收跌"
            signals.append(
                Signal(
                    type="技术面转弱",
                    level="warning",
                    action="重点关注",
                    detail=detail,
                )
            )

        days_to_earnings = self._days_to_earnings(symbol)
        if days_to_earnings is not None and days_to_earnings <= EARNINGS_DAYS_THRESHOLD:
            signals.append(
                Signal(
                    type="财报临近",
                    level="warning",
                    action="重点关注",
                    value=float(days_to_earnings),
                    threshold=float(EARNINGS_DAYS_THRESHOLD),
                    detail=f"距财报发布 {days_to_earnings} 天",
                )
            )

        return signals

    def _check_sell_reminders(
        self,
        symbol: str,
        snapshot: dict,
        research: dict | None,
        position: dict | None,
    ) -> list[Signal]:
        del symbol
        signals: list[Signal] = []
        if position is None:
            return signals

        price = snapshot.get("price")
        avg_cost = position.get("avg_cost")
        return_pct: float | None = None
        if price is not None and avg_cost not in (None, 0) and float(avg_cost) > 0:
            return_pct = (float(price) - float(avg_cost)) / float(avg_cost) * 100.0

        if return_pct is not None and return_pct <= STOP_LOSS_PCT:
            signals.append(
                Signal(
                    type="止损触发",
                    level="action",
                    action="考虑止损",
                    value=return_pct,
                    threshold=STOP_LOSS_PCT,
                )
            )

        if research:
            stop_loss_condition = research.get("stop_loss_condition")
            if self._evaluate_condition(stop_loss_condition, snapshot):
                signals.append(
                    Signal(
                        type="止损触发",
                        level="action",
                        action="考虑止损",
                        detail=f"止损条件：{stop_loss_condition}",
                    )
                )

            for scenario, field in (
                ("保守", "target_price_conservative"),
                ("基准", "target_price_base"),
                ("乐观", "target_price_optimistic"),
            ):
                target = research.get(field)
                if price is not None and target is not None and float(price) >= float(target):
                    signals.append(
                        Signal(
                            type="目标价达成",
                            level="action",
                            action="考虑止盈",
                            value=float(price),
                            threshold=float(target),
                            detail=f"{scenario}目标价 ${float(target):.2f} 已达成",
                        )
                    )

            reduce_condition = research.get("reduce_position_condition")
            if self._evaluate_condition(reduce_condition, snapshot):
                signals.append(
                    Signal(
                        type="减仓条件达成",
                        level="action",
                        action="考虑减仓",
                        detail=f"减仓条件：{reduce_condition}",
                    )
                )

            target_base = research.get("target_price_base")
            if price is not None and target_base is not None and float(target_base) > 0:
                overvaluation_threshold = float(target_base) * OVERVALUATION_MULTIPLIER
                if float(price) >= overvaluation_threshold:
                    signals.append(
                        Signal(
                            type="估值过高",
                            level="action",
                            action="考虑减仓",
                            value=float(price),
                            threshold=overvaluation_threshold,
                            detail=f"当前价格超过基准目标价 {float(target_base):.2f} 的 {OVERVALUATION_MULTIPLIER:.1f} 倍",
                        )
                    )

        if return_pct is not None and return_pct >= PROFIT_TARGET_PCT:
            signals.append(
                Signal(
                    type="收益率达标",
                    level="action",
                    action="考虑止盈",
                    value=return_pct,
                    threshold=PROFIT_TARGET_PCT,
                )
            )

        for condition in self._extract_invalidation_conditions(research):
            if self._evaluate_condition(condition, snapshot):
                signals.append(
                    Signal(
                        type="失效条件触发",
                        level="action",
                        action="考虑清仓",
                        detail=condition,
                    )
                )

        if research and research.get("overall_conclusion") == "不值得投":
            signals.append(
                Signal(
                    type="持有逻辑失效",
                    level="action",
                    action="考虑清仓",
                    detail="最新研究结论变为不值得投",
                )
            )

        rsi_14 = snapshot.get("rsi_14")
        ma_50_slope = snapshot.get("ma_50_slope")
        if rsi_14 is not None and ma_50_slope is not None:
            if float(rsi_14) >= RSI_OVERBOUGHT and float(ma_50_slope) < 0:
                signals.append(
                    Signal(
                        type="技术顶部信号",
                        level="action",
                        action="考虑减仓",
                        detail=f"RSI={float(rsi_14):.0f}, 50日均线向下拐头",
                    )
                )

        return signals

    def _calc_drawdown(self, symbol: str, current_price: float, snapshot: dict | None = None) -> float:
        del symbol
        high_52w = (snapshot or {}).get("high_52w")
        if high_52w is None or float(high_52w) <= 0:
            return 0.0
        return (float(high_52w) - float(current_price)) / float(high_52w) * 100.0

    def _days_to_earnings(self, symbol: str) -> int | None:
        del symbol
        return None

    def _evaluate_condition(self, condition_text: str | None, snapshot: dict) -> bool:
        del snapshot
        return bool(condition_text and str(condition_text).strip())

    def _extract_invalidation_conditions(self, research: dict | None) -> list[str]:
        if not research:
            return []

        raw_conditions = research.get("invalidation_conditions")
        if isinstance(raw_conditions, list):
            normalized = [str(item).strip() for item in raw_conditions if str(item).strip()]
            if normalized:
                return normalized
        elif isinstance(raw_conditions, str) and raw_conditions.strip():
            return [raw_conditions.strip()]

        raw_json = research.get("invalidation_conditions_json")
        if isinstance(raw_json, list):
            return [str(item).strip() for item in raw_json if str(item).strip()]
        if isinstance(raw_json, str) and raw_json.strip():
            try:
                parsed = json.loads(raw_json)
            except json.JSONDecodeError:
                return [raw_json.strip()]
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
            if isinstance(parsed, str) and parsed.strip():
                return [parsed.strip()]
        return []
