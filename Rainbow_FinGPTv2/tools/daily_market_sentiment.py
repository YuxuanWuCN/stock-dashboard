"""
每日市场情绪分析 - 使用 DeepSeek API 分析市场数据和新闻

功能：
1. 收集当日市场数据（涨跌、成交量、涨跌停等）
2. 抓取财经新闻标题
3. 使用 DeepSeek v4-flash 分析市场情绪
4. 生成每日市场情绪报告

执行时间：每天 18:00（在数据抓取之后）
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.config import DATA_DIR
from src.utils import beijing_datetime_str, beijing_date_str


def load_deepseek_client():
    """加载 DeepSeek API 客户端（统一支持外置 api-key.txt 与环境变量）"""
    try:
        from openai import OpenAI
        from src.llm.config import DEEPSEEK_API_KEY_FILE

        api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not api_key and Path(DEEPSEEK_API_KEY_FILE).exists():
            api_key = Path(DEEPSEEK_API_KEY_FILE).read_text(encoding="utf-8").strip()

        if not api_key:
            print("⚠️  未找到有效 API key，将自动降级为规则引擎生成情绪报告")
            return None

        client = OpenAI(
            api_key=api_key,
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            timeout=20.0
        )

        return client
    except Exception as e:
        print(f"⚠️  无法加载 DeepSeek 客户端（{e}），降级为规则引擎")
        return None


def collect_market_data():
    """收集当日市场数据"""
    summary_file = Path(DATA_DIR) / "summary.json"

    if not summary_file.exists():
        print("❌ summary.json 不存在")
        return None

    with open(summary_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    items = data.get('items', [])

    # 统计涨跌
    up_count = sum(1 for item in items if (item.get('change_pct') or 0) > 0)
    down_count = sum(1 for item in items if (item.get('change_pct') or 0) < 0)
    flat_count = len(items) - up_count - down_count

    # 涨跌幅分布
    changes = [item.get('change_pct') for item in items if item.get('change_pct') is not None]
    avg_change = sum(changes) / len(changes) if changes else 0

    # 涨跌停
    limit_up = sum(1 for c in changes if c >= 9.5)
    limit_down = sum(1 for c in changes if c <= -9.5)

    # 强势股（涨幅>5%）
    strong_stocks = [
        {"code": item['code'], "name": item['name'], "change": item['change_pct']}
        for item in items if (item.get('change_pct') or 0) > 5
    ]
    strong_stocks.sort(key=lambda x: x['change'], reverse=True)

    # 弱势股（跌幅<-5%）
    weak_stocks = [
        {"code": item['code'], "name": item['name'], "change": item['change_pct']}
        for item in items if item.get('change_pct', 0) < -5
    ]
    weak_stocks.sort(key=lambda x: x['change'])

    return {
        "date": data.get('date', beijing_date_str()),
        "total": len(items),
        "up_count": up_count,
        "down_count": down_count,
        "flat_count": flat_count,
        "avg_change": round(avg_change, 2),
        "limit_up": limit_up,
        "limit_down": limit_down,
        "strong_stocks": strong_stocks[:10],
        "weak_stocks": weak_stocks[:10]
    }


def collect_news():
    """收集财经新闻（从 LLM 市场反馈或其他来源）"""
    # 检查是否有市场反馈数据
    feedback_file = Path(DATA_DIR) / "llm" / "market_feedback.json"

    news_items = []

    if feedback_file.exists():
        try:
            with open(feedback_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 提取最近的样本作为"新闻"
            samples = data.get('samples', [])
            for sample in samples[-5:]:  # 最近5条
                news_items.append({
                    "title": f"{sample.get('code')} {sample.get('name')}: {sample.get('summary', '')}",
                    "sentiment": sample.get('sentiment', 'neutral')
                })
        except:
            pass

    # 如果没有数据，返回占位
    if not news_items:
        news_items = [
            {"title": "市场数据已更新，等待新闻抓取功能", "sentiment": "neutral"}
        ]

    return news_items


def analyze_market_sentiment(client, market_data, news):
    """使用 LLM 分析市场情绪"""
    if client is None:
        return None

    print("\n🧠 DeepSeek 分析市场情绪...")

    # 构建分析 Prompt
    prompt = f"""
你是一个专业的市场情绪分析师。基于今日市场数据和新闻，分析市场整体情绪。

**今日市场数据**:
- 日期: {market_data['date']}
- 上涨: {market_data['up_count']}只 ({market_data['up_count']/market_data['total']*100:.1f}%)
- 下跌: {market_data['down_count']}只 ({market_data['down_count']/market_data['total']*100:.1f}%)
- 平盘: {market_data['flat_count']}只
- 平均涨跌: {market_data['avg_change']:+.2f}%
- 涨停: {market_data['limit_up']}只
- 跌停: {market_data['limit_down']}只

**强势股** (涨幅>5%):
{json.dumps(market_data['strong_stocks'][:5], ensure_ascii=False, indent=2)}

**弱势股** (跌幅<-5%):
{json.dumps(market_data['weak_stocks'][:5], ensure_ascii=False, indent=2)}

**市场新闻/事件**:
{json.dumps([n['title'] for n in news[:5]], ensure_ascii=False, indent=2)}

**分析任务**:
1. 判断今日市场情绪（极度乐观/乐观/中性/悲观/极度悲观）
2. 识别市场热点板块或主题
3. 分析资金流向（追涨/抄底/观望）
4. 评估明日市场预期
5. 推荐具体组合策略

**可用组合策略**:
- aggressive（激进组合）: 满仓追热点，适合单边上涨
- robust（稳健组合）: 80%仓位，低风险高概率，适合震荡市
- bluechip（蓝筹组合）: 大盘龙头，适合防御
- defensive（防御组合）: 银行+黄金，适合下跌市
- global（全球组合）: 多市场分散，适合不确定性高时
- tech（科技组合）: 科技股集中，适合科技牛市

**推荐逻辑** (必须遵循):

1. **市场涨多跌少** (上涨>60% 或 平均涨跌>0.5%):
   - 涨停多(>5只) → aggressive (追热点)
   - 涨停少但涨幅分散 → robust 或 global (稳健参与)

2. **市场震荡** (上涨45-60% 且 平均涨跌±0.5%以内):
   - 有明显热点板块 → 对应主题组合(tech/bluechip等)
   - 无明显热点 → robust 或 global (控制风险)

3. **市场跌多涨少** (上涨<45% 或 平均涨跌<-0.5%):
   - 跌停多(>5只) → defensive (防御为主)
   - 跌幅温和 → bluechip (蓝筹避险)

4. **特殊情况**:
   - 科技股普涨 → tech
   - 大盘蓝筹领涨 → bluechip
   - 全球市场波动大 → global

**今日数据**:
- 上涨占比: {market_data['up_count']}/{market_data['total']} = {market_data['up_count']/market_data['total']*100:.1f}%
- 平均涨跌: {market_data['avg_change']:+.2f}%
- 涨停: {market_data['limit_up']}只, 跌停: {market_data['limit_down']}只

**根据以上规则推荐组合，并说明符合哪条规则。**

**输出格式** (JSON):
{{
  "sentiment": "乐观/中性/悲观",
  "sentiment_score": 7.5,
  "hot_sectors": ["板块1", "板块2"],
  "capital_flow": "追涨/抄底/观望",
  "key_observations": [
    "观察点1: 涨停数{market_data['limit_up']}只，跌停{market_data['limit_down']}只，资金{{'追涨' if market_data['limit_up'] > market_data['limit_down'] else '观望' if market_data['limit_up'] == market_data['limit_down'] else '谨慎'}}",
    "观察点2: 强势股{len(market_data['strong_stocks'])}只，弱势股{len(market_data['weak_stocks'])}只"
  ],
  "tomorrow_expectation": {{
    "direction": "上涨/震荡/下跌",
    "confidence": 70,
    "reasoning": "基于今日涨跌分布、资金流向、热点持续性综合判断"
  }},
  "trading_advice": {{
    "recommended_portfolio": "aggressive",
    "alternative_portfolio": "robust",
    "reasoning": "明确说明为什么推荐这个组合（考虑市场情绪、趋势、热点）",
    "position_suggestion": "满仓/80%/60%",
    "caution_points": ["风险点1", "风险点2"],
    "opportunities": ["机会1: 具体到板块或个股", "机会2"]
  }}
}}

请用中文回答，推荐必须有清晰逻辑，不要矛盾（比如市场乐观却推荐防御）。
"""

    try:
        response = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": "你是一个专业的市场情绪分析师，精通技术分析和市场心理学。"},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )

        result = json.loads(response.choices[0].message.content)

        print(f"✅ 分析完成")
        print(f"   市场情绪: {result.get('sentiment', '未知')}")
        print(f"   情绪分数: {result.get('sentiment_score', 0)}/10")
        print(f"   热点板块: {', '.join(result.get('hot_sectors', []))}")

        return result

    except Exception as e:
        print(f"❌ LLM 分析失败: {e}")
        return None




def _generate_rule_based_sentiment(market_data: dict, news: list) -> dict:
    """当 LLM 不可用时，按既定规则确定性生成市场情绪分析（防日历停摆）。"""
    total = market_data.get("total", 202) or 202
    up_count = market_data.get("up_count", 0)
    down_count = market_data.get("down_count", 0)
    up_ratio = up_count / total * 100.0
    avg_change = market_data.get("avg_change", 0.0)
    limit_up = market_data.get("limit_up", 0)
    limit_down = market_data.get("limit_down", 0)

    if up_ratio >= 60.0 or avg_change >= 0.5:
        sentiment = "乐观"
        score = 7.5
        capital_flow = "追涨"
        portfolio = "aggressive" if limit_up >= 5 else "robust"
        pos = "80%~满仓"
        direction = "上涨"
    elif up_ratio < 45.0 or avg_change <= -0.5:
        sentiment = "悲观"
        score = 3.5
        capital_flow = "观望"
        portfolio = "defensive" if limit_down >= 5 else "bluechip"
        pos = "60%"
        direction = "震荡偏弱"
    else:
        sentiment = "中性"
        score = 5.5
        capital_flow = "平衡"
        portfolio = "robust"
        pos = "70%"
        direction = "窄幅震荡"

    return {
        "sentiment": sentiment,
        "sentiment_score": score,
        "hot_sectors": ["贵金属/资源", "新能源", "核心蓝筹"],
        "capital_flow": capital_flow,
        "key_observations": [
            f"观察点1: 上涨 {up_count} 只 ({up_ratio:.1f}%)，下跌 {down_count} 只，涨停 {limit_up} 只，跌停 {limit_down} 只",
            f"观察点2: 强势股 {len(market_data.get('strong_stocks', []))} 只，弱势股 {len(market_data.get('weak_stocks', []))} 只",
            "观察点3: [规则降级模式] 基础市场情绪由盘面涨跌比与动能规则确定性导出"
        ],
        "tomorrow_expectation": {
            "direction": direction,
            "confidence": 65,
            "reasoning": f"今日上涨占比 {up_ratio:.1f}%，平均涨跌 {avg_change:+.2f}%，市场整体处于{sentiment}状态。"
        },
        "trading_advice": {
            "recommended_portfolio": portfolio,
            "alternative_portfolio": "global",
            "reasoning": f"根据规则引擎判断：市场处于{sentiment}状态（上涨占比{up_ratio:.1f}%），推荐配置 {portfolio} 组合以平衡收益与波动。",
            "position_suggestion": pos,
            "caution_points": [
                "风险点1: 留意宏观与外盘波动对核心资产的传导",
                "风险点2: 控制单一板块追高暴露，严格遵守止损纪律"
            ],
            "opportunities": [
                "机会1: 重点关注前沿供需拐点向上的资源与新能源标的",
                "机会2: 兼顾大盘低估值蓝筹的底线避险价值"
            ]
        }
    }

def save_sentiment_report(market_data, news, sentiment_analysis):
    """保存市场情绪报告"""
    report_dir = Path("reports") / "market_sentiment"
    report_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d")
    report_file = report_dir / f"sentiment_{timestamp}.json"

    report = {
        "generated_at": beijing_datetime_str(),
        "date": market_data['date'],
        "market_data": market_data,
        "news": news,
        "sentiment_analysis": sentiment_analysis
    }

    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\n💾 报告已保存: {report_file}")
    return report_file


def main():
    print("=" * 80)
    print("📊 每日市场情绪分析")
    print("=" * 80)

    # 1. 连接 API
    print("\n📡 连接 DeepSeek API...")
    client = load_deepseek_client()
    if client is not None:
        print("✅ API 已连接")
    else:
        print("ℹ️  将启用规则引擎离线生成")

    # 2. 收集市场数据
    print("\n📈 收集市场数据...")
    market_data = collect_market_data()

    if market_data is None:
        print("❌ 无法收集市场数据")
        return 1

    print(f"✅ 数据收集完成")
    print(f"   日期: {market_data['date']}")
    print(f"   上涨: {market_data['up_count']}只 ({market_data['up_count']/market_data['total']*100:.1f}%)")
    print(f"   下跌: {market_data['down_count']}只 ({market_data['down_count']/market_data['total']*100:.1f}%)")
    print(f"   平均涨跌: {market_data['avg_change']:+.2f}%")

    # 3. 收集新闻
    print("\n📰 收集市场新闻...")
    news = collect_news()
    print(f"✅ 收集了 {len(news)} 条新闻/事件")

    # 4. 情绪分析（优先 LLM，失败/无 Key 自动降级为规则引擎）
    sentiment_analysis = None
    if client is not None:
        sentiment_analysis = analyze_market_sentiment(client, market_data, news)
    
    if sentiment_analysis is None:
        print("⚙️  使用规则引擎生成确定性市场情绪报告...")
        sentiment_analysis = _generate_rule_based_sentiment(market_data, news)

    # 5. 保存报告
    report_file = save_sentiment_report(market_data, news, sentiment_analysis)

    # 6. 打印摘要
    print("\n" + "=" * 80)
    print("📊 今日市场情绪摘要")
    print("=" * 80)

    if sentiment_analysis:
        print(f"\n🎯 市场情绪: {sentiment_analysis.get('sentiment', '未知')}")
        print(f"📊 情绪分数: {sentiment_analysis.get('sentiment_score', 0)}/10")

        hot_sectors = sentiment_analysis.get('hot_sectors', [])
        if hot_sectors:
            print(f"🔥 热点板块: {', '.join(hot_sectors)}")

        print(f"💰 资金流向: {sentiment_analysis.get('capital_flow', '未知')}")

        tomorrow = sentiment_analysis.get('tomorrow_expectation', {})
        if tomorrow:
            print(f"\n📅 明日预期: {tomorrow.get('direction', '未知')} (置信度 {tomorrow.get('confidence', 0)}%)")
            print(f"   理由: {tomorrow.get('reasoning', '未知')}")

        advice = sentiment_analysis.get('trading_advice', {})
        if advice:
            recommended = advice.get('recommended_portfolio', '')
            alternative = advice.get('alternative_portfolio', '')
            if recommended:
                print(f"\n💡 推荐组合: {recommended}")
                if alternative:
                    print(f"   备选组合: {alternative}")
                print(f"   推荐理由: {advice.get('reasoning', '未知')}")
                print(f"   仓位建议: {advice.get('position_suggestion', '未知')}")

            opportunities = advice.get('opportunities', [])
            if opportunities:
                print(f"\n🎯 机会点:")
                for opp in opportunities:
                    print(f"   - {opp}")

    print("\n" + "=" * 80)

    return 0


if __name__ == '__main__':
    sys.exit(main())
