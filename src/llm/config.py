# src/llm/config.py —— LLM / RAG / 新闻管线配置
#
# 所有可调参数集中在此。规则引擎与 LLM 分离：
# LLM 只做文本理解与表达，不生成财务数字，不覆盖程序计算结果。

import os
from pathlib import Path


ROOT_PATH = Path(__file__).resolve().parents[2]
ROOT_DIR = str(ROOT_PATH)

# 用户指定的唯一 DeepSeek 推理模型。FinGPT 风格管线会再次校验该值，
# 防止环境变量或兼容网关悄悄切换到其他模型。
DEEPSEEK_V4_FLASH_MODEL = "deepseek-v4-flash"
DEEPSEEK_API_KEY_FILE = os.environ.get(
    "DEEPSEEK_API_KEY_FILE",
    str(ROOT_PATH / "api-key.txt"),
)

# ============================================================
# 功能开关
# ============================================================

def _env_flag(name: str, default: bool) -> bool:
    val = os.environ.get(name, str(default)).strip().lower()
    return val in ("1", "true", "yes", "on")

# 新闻抓取开关（离线测试时关闭）
NEWS_ENABLED = _env_flag("LLM_NEWS_ENABLED", True)
# LLM 报告生成开关（无 API Key 时自动关闭）
LLM_ENABLED = _env_flag("LLM_ENABLED", True)
# 主分析流水线完成后是否自动调度研究报告。
# 关闭时既不读取本地密钥，也不会发起新闻或 LLM 请求。
LLM_REPORTS_ENABLED = _env_flag("LLM_REPORTS_ENABLED", True)
# 每次主分析最多生成前 K 名的报告，控制每日 API 与新闻抓取成本。
# 设为 0 表示对全部自选股生成报告（v2.5：默认全量覆盖）。
LLM_REPORTS_TOP_K = max(0, int(os.environ.get("LLM_REPORTS_TOP_K", "0")))
# 已有合格的 DeepSeek 报告时默认跳过，支持中断后的低成本续跑。
LLM_REPORTS_SKIP_EXISTING = _env_flag("LLM_REPORTS_SKIP_EXISTING", True)
# RAG 检索开关
RAG_ENABLED = _env_flag("LLM_RAG_ENABLED", True)

# ============================================================
# LLM 客户端（OpenAI 兼容接口，默认 DeepSeek）
# ============================================================

# 后端选择: "deepseek" | "dashscope" | "openai" | ""
# 为空且无 API Key 时，报告退化为模板生成（不调用外部 API）。
LLM_BACKEND = os.environ.get("LLM_BACKEND", "deepseek")

LLM_CONFIG = {
    "deepseek": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "api_key_file": DEEPSEEK_API_KEY_FILE,
        "base_url": os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        "model": DEEPSEEK_V4_FLASH_MODEL,
        "default_api_key": "",  # 由环境变量提供
    },
    "dashscope": {
        "api_key_env": "DASHSCOPE_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": os.environ.get("DASHSCOPE_MODEL", "qwen-turbo"),
        "default_api_key": "",
    },
    "openai": {
        "api_key_env": "OPENAI_API_KEY",
        "base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "default_api_key": "",
    },
}

# 单次报告生成的最大 token 数（防止成本失控）
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "1200"))
# 每次调用超时（秒）
LLM_TIMEOUT_SECONDS = float(os.environ.get("LLM_TIMEOUT_SECONDS", "30"))
# 每日全管线调用次数上限（保护 API 预算；本地测试可调高）
LLM_DAILY_CALL_LIMIT = int(os.environ.get("LLM_DAILY_CALL_LIMIT", "50"))

# ============================================================
# 嵌入与向量检索
# ============================================================

# 首选嵌入方式: "sentence-transformers" | "hash" | ""
#   sentence-transformers 需要联网下载模型（约 118MB），CI 内存可承载；
#   hash 为确定性哈希向量（纯 numpy，零下载，用于离线测试/降级）。
EMBEDDING_BACKEND = os.environ.get("EMBEDDING_BACKEND", "hash")

# sentence-transformers 模型名
EMBEDDING_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
# 哈希嵌入维度
EMBEDDING_HASH_DIM = 256

# RAG 检索参数
RAG_TOP_K = 5
RAG_MIN_SCORE = 0.0

# ============================================================
# 新闻抓取
# ============================================================

# 单只标的抓取的新闻天数
NEWS_DAYS_BACK = int(os.environ.get("LLM_NEWS_DAYS_BACK", "30"))
# 公告抓取天数
ANNOUNCEMENT_DAYS_BACK = int(os.environ.get("LLM_ANNOUNCEMENT_DAYS_BACK", "90"))
# 单只标的新闻最大条数
NEWS_MAX_ITEMS = int(os.environ.get("LLM_NEWS_MAX_ITEMS", "30"))
# 抓取间隔（秒），避免封 IP
NEWS_REQUEST_INTERVAL = float(os.environ.get("LLM_NEWS_REQUEST_INTERVAL", "1.0"))
# 抓取超时（秒）
NEWS_REQUEST_TIMEOUT = float(os.environ.get("LLM_NEWS_REQUEST_TIMEOUT", "20"))

# ============================================================
# 文本分块
# ============================================================

CHUNK_MAX_CHARS = 512
CHUNK_OVERLAP_SENTENCES = 2
CHUNK_MAX_SENTENCES = 20

# ============================================================
# 情感分析（规则基线）
# ============================================================

# 正向/负向概率阈值
SENTIMENT_POSITIVE_THRESHOLD = 0.6
SENTIMENT_NEGATIVE_THRESHOLD = 0.4

# 新闻采样数（FinGPT sample_news 模式：采样 k 条做 LLM 情感分析，省 API）
SENTIMENT_SAMPLE_K = int(os.environ.get("LLM_SENTIMENT_SAMPLE_K", "8"))

# ============================================================
# 输出路径（相对仓库根目录）
# ============================================================

DATA_DIR = os.path.join(ROOT_DIR, "docs", "data")
LLM_DIR = os.path.join(DATA_DIR, "llm")
NEWS_DIR = os.path.join(LLM_DIR, "news")
REPORT_DIR = os.path.join(LLM_DIR, "reports")
SENTIMENT_DIR = os.path.join(LLM_DIR, "sentiment")
FEEDBACK_PATH = os.path.join(LLM_DIR, "market_feedback.json")
