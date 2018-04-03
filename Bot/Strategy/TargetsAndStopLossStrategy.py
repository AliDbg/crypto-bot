from Bot.FXConnector import FXConnector
from Bot.OrderEnums import OrderStatus
from Bot.Strategy.EntryStrategy import EntryStrategy
from Bot.Strategy.PlaceOrderStrategy import PlaceOrderStrategy
from Bot.Strategy.StopLossStrategy import StopLossStrategy
from Bot.Strategy.TradingStrategy import TradingStrategy
from Bot.Target import Target
from Bot.Trade import Trade


class TargetsAndStopLossStrategy(TradingStrategy):
    def __init__(self, trade: Trade, fx: FXConnector, trade_updated=None):
        super().__init__(trade, fx, trade_updated)
        self.validate_asset_balance()

        self.strategy_sl = StopLossStrategy(trade, fx, trade_updated, True, self.exchange_info, self.balance) \
            if trade.get_initial_stop() is not None else None

        self.strategy_po = PlaceOrderStrategy(trade, fx, trade_updated, True, self.exchange_info, self.balance) \
            if len(trade.targets) > 0 else None

        self.strategy_en = EntryStrategy(trade, fx, trade_updated, True, self.exchange_info, self.balance) \
            if trade.has_entry() and not trade.entry.target.is_completed() else None

        self.last_price = 0
        self.last_execution_price = 0

    def execute(self, new_price):
        if self.is_completed():
            self.logInfo('Trade Complete')
            return

        if self.strategy_sl and (self.strategy_sl.is_completed() or self.strategy_po.is_completed()):
            self.set_trade_completed()
            return

        # self.log_price(new_price)

        if new_price == self.last_execution_price:
            return

        self.last_execution_price = new_price

        if self.trade.status == OrderStatus.NEW:
            if self.trade.has_entry():
                self.strategy_en.execute(new_price)
                # # implementy market entry
                # self.trade.status = OrderStatus.ACTIVE
                # self.trade_updated(self.trade)
            else: # if no entry is needed
                self.trade.set_active()
                self.trigger_target_updated()

        if self.trade.status == OrderStatus.ACTIVE:
            if self.strategy_sl:
                self.strategy_sl.execute(new_price)

            if self.strategy_sl and not self.strategy_sl.is_stoploss_order_active():
                if self.strategy_po:
                    self.strategy_po.execute(new_price)

    def log_price(self, new_price):
        if self.last_price != new_price:
            self.logInfo('Price: {:.08f}'.format(new_price))
            self.last_price = new_price

    def order_status_changed(self, t: Target, data):
        if t.is_entry_target() and t.is_completed():
            self.trade.set_active()
            self.trigger_target_updated()

        if self.strategy_sl:
            self.strategy_sl.order_status_changed(t, data)

        if self.strategy_po:
            self.strategy_po.order_status_changed(t, data)

        if self.strategy_en:
            self.strategy_en.order_status_changed(t, data)

