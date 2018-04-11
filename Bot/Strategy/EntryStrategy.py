from binance.exceptions import BinanceAPIException

from Bot.TradeEnums import OrderStatus, Side
from Bot.FXConnector import FXConnector
from Bot.Strategy.SmartOrder import SmartOrder
from Bot.Strategy.TradingStrategy import TradingStrategy
from Bot.Target import Target, PriceHelper
from Bot.Trade import Trade
from Bot.Value import Value

class EntryStrategy(TradingStrategy):
    def __init__(self, trade: Trade, fx: FXConnector, trade_updated=None, nested=False, exchange_info=None, balance=None):
        super().__init__(trade, fx, trade_updated, nested, exchange_info, balance)
        self.smart_order = None
        self.last_smart_price = 0
        self.init_smart_order()

    def init_smart_order(self):
        self.smart_order = SmartOrder(is_buy=self.trade_side().is_buy(),
                                      price=self.trade_target().price,
                                      sl_threshold=self.get_trade_section().sl_threshold,
                                      pull_back=self.get_trade_section().pullback_threshold,
                                      logger=self.logger,
                                      best_price=self.get_trade_section().best_price)

    def update_trade(self, trade: Trade):
        self.trade = trade
        self.init_smart_order()


    def execute(self, new_price):
        try:
            if self.is_completed():
                return

            target = self.trade_target()

            if self.validate_all_completed([target]):
                self.logInfo('All Orders are Completed')
                return

            price = self.get_single_price(new_price, self.price_selector(self.trade_side()))

            # if self.is_smart:
            if not self.smart_order.is_init():
                ph = PriceHelper.create_price_helper(self.trade_target().price)
                actual_price = ph.get_value(price)
                self.smart_order.init_price(actual_price)

                self.trade_target().price = actual_price
                self.trigger_target_updated()

            # TODO: add automatic order placement if it was canceled by someone
            trigger_order_price = self.smart_order.price_update(price)
            self.on_smart_buy(trigger_order_price)


        except BinanceAPIException as bae:
            self.logError(str(bae))

    def get_available_amount(self):
        return self.balance.avail

    def on_smart_buy(self, trigger_order_price):
        if not trigger_order_price:
            return

        if (self.trade_side().is_sell() and trigger_order_price > self.last_smart_price) or \
                (self.trade_side().is_buy() and trigger_order_price < self.last_smart_price) or \
                self.last_smart_price == 0:

            self.logInfo('Setting StopLoss-{} for {:.08f}'.format(self.trade_side().name, trigger_order_price))

            t = self.trade_target()

            if t.is_active():
                status = self.fx.get_order_status(self.symbol(), t.id)

                if self.fx.cancel_order(self.symbol(), t.id):
                    t.set_canceled()
                    self.trigger_target_updated()
                    self.balance.avail = float(status["origQty"]) - float(status["executedQty"])

            # if self.trade_side().is_buy():
            #     limit = max(trigger_order_price, t.price + self.smart_order.sl_threshold_val)
            # else:
            #     limit = min(trigger_order_price, t.price - self.smart_order.sl_threshold_val)

            if self.trade_side().is_buy():
                limit = max(trigger_order_price + self.smart_order.sl_threshold_val,
                            t.price + self.smart_order.sl_threshold_val)
            else:
                limit = min(trigger_order_price - self.smart_order.sl_threshold_val,
                            t.price - self.smart_order.sl_threshold_val)

            try:
                order = self.fx.create_stop_order(
                    sym=self.symbol(),
                    side=self.trade_side().name,
                    stop_price=self.exchange_info.adjust_price(trigger_order_price),
                    price=self.exchange_info.adjust_price(limit),
                    volume=self.exchange_info.adjust_quanity(t.vol.get_val(self.balance.avail))
                )
            except BinanceAPIException as sl_exception:
                if sl_exception.message.lower().find('order would trigger immediately') > -1:
                    order = self.fx.create_makret_order(
                        self.symbol(),
                        self.trade_side().name,
                        self.exchange_info.adjust_quanity(
                            self.exchange_info.adjust_quanity(t.vol.get_val(self.balance.avail)))
                    )
                else:
                    raise

            self.get_trade_section().best_price = trigger_order_price
            self.last_smart_price = trigger_order_price
            t.set_active(order['orderId'])
            self.trigger_target_updated()

    def trade_side(self):
        return self.get_trade_section().side if self.get_trade_section().side else self.trade.side.reverse()

    def is_completed(self):
        return self.get_trade_section().is_completed()

    def trade_target(self):
        return self.get_trade_section().targets[-1]

    def validate_all_orders(self, targets):
        return all(t.is_completed() or (t.status.is_active() or t.has_id()) for t in targets)

    def validate_all_completed(self, targets):
        return all(t.status.is_completed() for t in targets)

    def get_trade_section(self):
        return self.trade.entry

    def order_status_changed(self, t: Target, data):
        if not t.is_entry_target():
            return

        if t.is_completed():
            self.logInfo('Target {} completed'.format(t))
        else:
            self.logInfo('Order status updated: {}'.format(t.status))


class ExitStrategy(EntryStrategy):
    def __init__(self, trade: Trade, fx: FXConnector, trade_updated=None, nested=False, exchange_info=None, balance=None):
        super().__init__(trade, fx, trade_updated, nested, exchange_info, balance)

    def get_trade_section(self):
        return self.trade.exit

    def trade_side(self):
        return self.get_trade_section().side if self.get_trade_section().side else self.trade.side

    def order_status_changed(self, t: Target, data):
        if not t.is_exit_target():
            return

        if t.is_completed():
            self.logInfo('Target {} completed'.format(t))
        else:
            self.logInfo('Order status updated: {}'.format(t.status))


