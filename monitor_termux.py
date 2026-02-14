# -*- coding: utf-8 -*-
"""
币安USDT永续合约价格异动监控 (Termux/Python版)
版本: v1.0.0
功能: 轮询币安合约API，发现价格短时异动(1分钟)即通过飞书推送通知。
特点:
  - 轻量级 (仅依赖 requests)
  - 适配 Termux 手机环境
  - 自动去重 (防刷屏)
"""

import time
import requests
import json
import os
import sys
from datetime import datetime, timedelta

# ================= 配置加载区域 =================
# 尝试读取同级目录下的 config.json
CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "feishu_webhook": "",
    "monitor_settings": {
        "interval_seconds": 20,       # 轮询间隔(秒)，建议 20-60
        "price_change_threshold": 1.0, # 异动阈值(%)，超过此幅度报警
        "cooldown_minutes": 5          # 单个币种冷却时间(分)，防止连续刷屏
    },
    "filter_settings": {
        "min_volume_usdt": 1000000,    # 最小成交额(USDT)，过滤垃圾山寨币
        "exclude_symbols": ["USDCUSDT", "BUSDUSDT"] # 排除的币种
    },
    "proxy_settings": {
        "enabled": False,
        "http": "http://127.0.0.1:7890",
        "https": "http://127.0.0.1:7890"
    }
}

# 全局变量
config = DEFAULT_CONFIG
price_cache = {}    # 缓存: {symbol: {'price': float, 'time': timestamp}}
alert_history = {}  # 报警记录: {symbol: timestamp}

def load_config():
    """加载配置文件，若不存在则使用默认并生成文件"""
    global config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
                # 递归更新配置 (简单合并)
                for k, v in user_config.items():
                    if isinstance(v, dict) and k in config:
                        config[k].update(v)
                    else:
                        config[k] = v
                print("✅ 配置文件加载成功")
        except Exception as e:
            print(f"⚠️ 配置文件读取失败: {e}，使用默认配置")
    else:
        print("⚠️ 配置文件不存在，将生成默认模板... 请稍后编辑 config.json 填入 Webhook")
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_CONFIG, f, indent=4, ensure_ascii=False)

def get_session():
    """获取带代理设置的 requests session"""
    s = requests.Session()
    # Termux 环境下通常不需要 headers 也能跑，但加个 User-Agent 更保险
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    })

    # 代理配置
    proxy_cfg = config.get("proxy_settings", {})
    if proxy_cfg.get("enabled"):
        proxies = {
            "http": proxy_cfg.get("http"),
            "https": proxy_cfg.get("https")
        }
        s.proxies.update(proxies)
        # print(f"🔌 已启用代理: {proxies}")

    return s

def get_market_prices(session):
    """
    获取币安合约全市场最新价格
    API: GET https://fapi.binance.com/fapi/v1/ticker/price
    或者 ticker/24hr (数据更全，含成交额)
    这里选用 ticker/24hr 以便过滤成交额
    """
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    try:
        resp = session.get(url, timeout=10)
        if resp.status_code != 200:
            print(f"❌ API 请求失败: {resp.status_code} - {resp.text[:50]}")
            return None
        return resp.json()
    except Exception as e:
        print(f"❌ 网络异常: {str(e)[:50]}")
        return None

def send_feishu_card(alerts):
    """
    发送飞书卡片消息
    alerts: list of dict [{'symbol': 'BTCUSDT', 'change': 1.2, 'price': 68000, 'trend': '🚀'}]
    """
    webhook = config.get("feishu_webhook")
    if not webhook or "YOUR_WEBHOOK" in webhook:
        print("❌ 未配置飞书 Webhook，跳过推送")
        return

    # 生成时间
    # ⚠️ Termux 容器时间可能不准，使用 UTC+8 计算
    utc_now = datetime.utcnow()
    bj_time = utc_now + timedelta(hours=8)
    time_str = bj_time.strftime("%H:%M")

    # 构建卡片内容
    # 标题: 🚨 市场异动监控 [12:30]
    # 内容: 列表形式

    content_lines = []

    for item in alerts:
        symbol = item['symbol'].replace("USDT", "") # 简化显示 BTCUSDT -> BTC
        trend = item['trend']
        change = item['change']
        price = item['price']

        # 价格格式化: 大于100保留1位，小于100保留4位
        price_str = f"{price:.1f}" if price > 100 else f"{price:.4f}"

        # 涨跌幅符号
        change_str = f"+{change:.2f}%" if change > 0 else f"{change:.2f}%"

        # K线链接 (Coinglass 或 Binance)
        # Binance App Scheme: binance://futures/BTCUSDT (手机端可能唤起App)
        # Web Link: https://www.binance.com/zh-CN/futures/BTCUSDT
        # Coinglass: https://www.coinglass.com/zh/tv/Binance_BTCUSDT

        # 这里使用 Binance Web 链接，兼容性最好
        link = f"https://www.binance.com/zh-CN/futures/{item['symbol']}"

        # 行格式: 🚀 BTC +1.2% $68000
        line = f"{trend} [{symbol}]({link}) {change_str} ${price_str}"
        content_lines.append(line)

    # 组合文本
    text_body = "\n".join(content_lines)

    # 构建请求体 (使用 text 类型简单明了，或者 post 类型)
    # 这里用 interactive (卡片) 太复杂，用 post 富文本
    msg = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"⚡ 价格异动监控 [{time_str}]"
                },
                "template": "red" if content_lines[0].startswith("📉") else "blue"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": text_body
                    }
                }
            ]
        }
    }

    try:
        requests.post(webhook, json=msg)
        print(f"✅ 已推送 {len(alerts)} 条异动信息")
    except Exception as e:
        print(f"❌ 推送失败: {e}")

def monitor_loop():
    """主监控循环"""
    print("🚀 启动监控脚本...")
    print(f"🎯 异动阈值: ±{config['monitor_settings']['price_change_threshold']}%")
    print(f"⏱️ 轮询间隔: {config['monitor_settings']['interval_seconds']}秒")

    session = get_session()

    # 首次运行，先填充缓存，不报警
    print("⏳正在初始化基础数据...")
    data = get_market_prices(session)
    if data:
        for item in data:
            symbol = item['symbol']
            if not symbol.endswith("USDT"): continue
            try:
                price = float(item['lastPrice'])
                price_cache[symbol] = {'price': price, 'time': time.time()}
            except:
                pass
        print(f"✅ 初始化完成，监控 {len(price_cache)} 个币种")

    # 开始循环
    while True:
        try:
            # 1. 等待
            time.sleep(config['monitor_settings']['interval_seconds'])

            # 2. 获取新数据
            new_data = get_market_prices(session)
            if not new_data: continue

            alerts = [] # 本轮需要报警的列表
            current_time = time.time()

            # 3. 遍历分析
            # 获取过滤配置
            min_vol = config['filter_settings']['min_volume_usdt']
            excludes = config['filter_settings']['exclude_symbols']
            threshold = config['monitor_settings']['price_change_threshold']
            cooldown = config['monitor_settings']['cooldown_minutes'] * 60

            for item in new_data:
                symbol = item['symbol']

                # --- 基础过滤 ---
                if not symbol.endswith("USDT"): continue
                if symbol in excludes: continue
                # 成交额过滤 (quoteVolume 是 USDT 成交额)
                if float(item['quoteVolume']) < min_vol: continue

                try:
                    current_price = float(item['lastPrice'])
                except:
                    continue

                # --- 异动计算 ---
                if symbol in price_cache:
                    last_price = price_cache[symbol]['price']

                    # 避免价格为0
                    if last_price == 0:
                        price_cache[symbol] = {'price': current_price, 'time': current_time}
                        continue

                    # 涨跌幅 %
                    pct_change = (current_price - last_price) / last_price * 100

                    # 检查是否超过阈值 (绝对值)
                    if abs(pct_change) >= threshold:
                        # --- 冷却检查 ---
                        last_alert_time = alert_history.get(symbol, 0)
                        if current_time - last_alert_time > cooldown:
                            # 触发报警
                            trend = "🚀" if pct_change > 0 else "📉"
                            alerts.append({
                                'symbol': symbol,
                                'change': pct_change,
                                'price': current_price,
                                'trend': trend
                            })

                            # 更新报警历史
                            alert_history[symbol] = current_time
                            # print(f"🔔 触发: {symbol} {pct_change:.2f}%")

                # --- 更新缓存 ---
                # 无论是否报警，都更新为最新价格，作为下一次比较的基准
                # 特别说明：这里是否更新基准决定了是监控“瞬间波动”还是“累计波动”
                # 如果每次都更新，监控的是 Interval 内的波动。
                # 如果要监控 1分钟内的累计，这里的逻辑需要更复杂（维护一个时间窗口队列）。
                # 为了简单和实效性，这里采用 "滚动更新"：
                # 但为了防止价格 0.5% -> 0.5% -> 0.5% 慢慢涨但不触发，
                # 理想做法是：缓存里存的是 "1分钟前" 的价格，而不是 "上次轮询" 的价格。
                # 鉴于代码复杂度，简单版：interval 设为 60秒，那么每次对比的就是 60秒前的价格。
                price_cache[symbol] = {'price': current_price, 'time': current_time}

            # 4. 批量推送
            if alerts:
                # 按涨跌幅绝对值排序
                alerts.sort(key=lambda x: abs(x['change']), reverse=True)
                print(f"⚡ 发现 {len(alerts)} 个异动，准备推送...")
                send_feishu_card(alerts)
            else:
                sys.stdout.write(f"\r✅ [{datetime.now().strftime('%H:%M:%S')}] 扫描完成，无异动")
                sys.stdout.flush()

        except KeyboardInterrupt:
            print("\n🛑 用户停止")
            break
        except Exception as e:
            print(f"\n❌ 未知错误: {e}")
            time.sleep(5)

if __name__ == "__main__":
    load_config()

    # 尝试设置 Termux 唤醒锁 (仅在 Android 有效)
    try:
        os.system("termux-wake-lock")
        print("🔒 [Termux] 已申请电源锁，防止后台休眠")
    except:
        pass

    monitor_loop()
