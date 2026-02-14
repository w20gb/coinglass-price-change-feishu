import asyncio
import json
import logging
import sys
import os
import requests
from datetime import datetime, timedelta
# 兼容本地运行检查: 如果没有安装 playwright，先报错提示
try:
    from playwright.async_api import async_playwright
except ImportError:
    print("❌ 缺少 playwright 库，请运行: pip install playwright && playwright install chromium")
    sys.exit(1)

# === 配置区域 ===
# 目标 URL: Coinglass 币安合约筛选器页面 (包含所有币种价格和 OI)
TARGET_URL = 'https://www.coinglass.com/zh/exchanges/Binance'

# 历史数据文件
HISTORY_FILE = "history_data.json"

# 异动阈值 (例如 5分钟内涨跌幅超过 2%)
# 注意: Github Actions 间隔不固定 (5-15分钟)，此阈值需适配间隔
CHANGE_THRESHOLD = 0.02  # 2%

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# === 核心注入脚本 (V5.6 Safe Mode) ===
# 原理: 劫持 JSON.parse，拦截页面加载时的 API 响应数据
INJECT_JS = """
(function() {
    console.log("[JS] Injecting God Mode...");
    const originalParse = JSON.parse;
    JSON.parse = function(text) {
        const result = originalParse.apply(this, arguments);
        try {
            if (text && text.length > 500 && result && typeof result === 'object') {
                detect(result);
            }
        } catch(e) {}
        return result;
    };

    function detect(json) {
        let list = null;
        // 智能尝试解析不同层级的 list
        if (Array.isArray(json)) list = json;
        else if (json.data && Array.isArray(json.data)) list = json.data;
        else if (json.list && Array.isArray(json.list)) list = json.list;
        else if (json.data && json.data.list && Array.isArray(json.data.list)) list = json.data.list;

        if (!list || list.length < 5) return;

        // 特征检测: 必须包含 symbol 和 price
        const first = list[0];
        if (!first || typeof first !== 'object') return;
        const keys = Object.keys(first);
        const hasSymbol = keys.includes('symbol') || keys.includes('uSymbol');
        const hasPrice = keys.includes('price') || keys.includes('lastPrice') || keys.includes('close');

        if (hasSymbol && hasPrice) {
             if (window.onCapturedData) {
                 window.onCapturedData(JSON.stringify(list));
             }
        }
    }
})();
"""

async def run_browser():
    async with async_playwright() as p:
        logger.info("🚀 启动无头浏览器...")
        # 启动 Chromium
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )

        page = await context.new_page()

        # 创建 Future 对象用于等待数据捕获
        data_captured = asyncio.Future()

        # 暴露 Python 函数给 JS 调用
        await page.expose_function("onCapturedData", lambda d: on_data_received(d, data_captured))

        # 注入劫持脚本
        await page.add_init_script(INJECT_JS)

        logger.info(f"👉 正在访问: {TARGET_URL}")
        try:
            # wait_until="networkidle" 确保页面完全加载
            response = await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
            if response.status != 200:
                logger.warning(f"⚠️ 页面返回状态码: {response.status}")
        except Exception as e:
            logger.warning(f"⚠️ 页面加载提示: {e}")

        logger.info("⏳ 等待数据捕获...")

        try:
            # 最多等待 30 秒，如果 30 秒还没抓到数据，说明页面结构变了或反爬升级
            raw_data = await asyncio.wait_for(data_captured, timeout=45.0)
            return raw_data
        except asyncio.TimeoutError:
            logger.error("❌ 失败: 45秒内未捕获到有效数据")
            # 截个图方便调试 (仅本地或 Artifacts 可看)
            # await page.screenshot(path="debug_failed.png")
            return None
        finally:
            await browser.close()

def on_data_received(json_str, future):
    if not future.done():
        future.set_result(json_str)
        logger.info("✅ 成功捕获数据包!")

def load_history():
    """读取上次价格快照"""
    if not os.path.exists(HISTORY_FILE):
        return {}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 格式兼容: 可能是 list 或 dict
            if isinstance(data, list):
                # 旧格式转 map: {BTCUSDT: 68000}
                return {item['symbol']: item['price'] for item in data}
            return data
    except Exception as e:
        logger.warning(f"⚠️ 读取历史文件失败: {e}")
        return {}

def save_history(current_data):
    """保存当前价格快照"""
    # current_data 是一个 dict: {symbol: price}
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(current_data, f, indent=2)
        logger.info(f"💾 已保存 {len(current_data)} 个币种的价格快照")
    except Exception as e:
        logger.error(f"❌ 保存历史文件失败: {e}")

def analyze_and_notify(raw_json):
    if not raw_json: return

    try:
        data_list = json.loads(raw_json)
        logger.info(f"📊 解析到 {len(data_list)} 条数据")

        # 1. 提取当前价格映射
        current_map = {}
        for item in data_list:
            # 兼容字段名
            symbol = item.get('symbol') or item.get('uSymbol')
            price = item.get('price') or item.get('lastPrice') or item.get('close')

            if symbol and price:
                # 统一格式: 移除 /USDT，确保是 float
                symbol = symbol.replace('/USDT', '') + 'USDT' # 统一加 USDT 后缀方便识别，或者按需调整
                try:
                    current_map[symbol] = float(price)
                except:
                    pass

        # 2. 读取历史
        history_map = load_history()

        # 3. 对比计算异动
        alerts = []
        for symbol, curr_price in current_map.items():
            if symbol not in history_map:
                continue

            last_price = history_map[symbol]
            if last_price <= 0: continue

            change_pct = (curr_price - last_price) / last_price

            if abs(change_pct) >= CHANGE_THRESHOLD:
                trend = "🚀" if change_pct > 0 else "📉"
                alerts.append({
                    "symbol": symbol,
                    "price": curr_price,
                    "change": change_pct,
                    "trend": trend,
                    "prev": last_price
                })

        # 4. 保存新历史 (覆盖旧的)
        save_history(current_map)

        # 5. 推送
        if alerts:
            # 按涨跌幅绝对值排序
            alerts.sort(key=lambda x: abs(x['change']), reverse=True)
            send_feishu(alerts)
        else:
            logger.info("🍵 无显著波动的币种 (阈值: ±{:.1f}%)".format(CHANGE_THRESHOLD * 100))

    except Exception as e:
        logger.error(f"❌ 数据解析错误: {e}")

def send_feishu(alerts):
    webhook = os.environ.get("FEISHU_WEBHOOK")
    if not webhook:
        logger.warning("⚠️ 未配置 FEISHU_WEBHOOK，跳过推送")
        # 打印到控制台模拟推送
        for a in alerts[:5]:
            print(f"   {a['trend']} {a['symbol']} {a['change']*100:.2f}%")
        return

    # 构建卡片
    lines = []
    # 限制显示数量，防止卡片超长
    top_alerts = alerts[:20]

    for item in top_alerts:
        symbol = item['symbol'].replace("USDT", "")
        # 格式: 🚀 BTC +2.5% $69000
        change_str = f"+{item['change']*100:.2f}%" if item['change'] > 0 else f"{item['change']*100:.2f}%"
        # 价格精度智能处理
        price_str = f"{item['price']:.2f}" if item['price'] > 10 else f"{item['price']:.4f}"

        # Coinglass K线链接 (支持持仓/多空数据)
        # 格式: https://www.coinglass.com/tv/Binance_BTCUSDT
        link = f"https://www.coinglass.com/tv/Binance_{item['symbol']}"

        line = f"{item['trend']} **[{symbol}]({link})** `{change_str}` <font color='grey'>${price_str}</font>"
        lines.append(line)

    if len(alerts) > 20:
        lines.append(f"... 还有 {len(alerts)-20} 个异动未显示")

    # 计算时间差 (Github Action 间隔)
    # 实际上这里没法精确计算上次运行时间，只能显示当前时间
    utc_now = datetime.utcnow()
    bj_time = utc_now + timedelta(hours=8)
    time_str = bj_time.strftime("%H:%M")

    card = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"⚡ 价格异动监控 [{time_str}]"
                },
                "template": "red" if alerts[0]['change'] < 0 else "blue"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "\n".join(lines)
                    }
                },
                {
                    "tag": "note",
                    "elements": [{"tag": "plain_text", "content": f"对比基准: 上次GitHub Action运行时的价格"}]
                }
            ]
        }
    }

    try:
        requests.post(webhook, json=card)
        logger.info(f"✅ 已推送 {len(alerts)} 条异动")
    except Exception as e:
        logger.error(f"❌ 推送失败: {e}")

if __name__ == "__main__":
    # Windows 本地调试需要 event loop 策略调整
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    raw_data = asyncio.run(run_browser())
    if raw_data:
        analyze_and_notify(raw_data)
