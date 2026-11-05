"""Rainbow FinGPT v2 源码包。

本 ``__init__`` 只做一件事：在任何子模块 ``import akshare`` **之前**装好出站网络护栏。

## 为什么放在包级而不是各入口脚本

AkShare 的导入点分散在 ``analysis/industry.py``、``analysis/fundamental.py``、
``strategies/market_temperature.py``、``llm/news_fetcher.py``、``server.py`` 等多处，
而 Python 的 ``import akshare`` 一旦执行，``curl_cffi`` 就会在导入期把
``DEFAULT_CACERT`` 固化成模块级常量。等到业务函数里再想改就来不及了。

包级 ``__init__`` 是唯一能保证「先于所有子模块的 akshare 导入」的位置：
任何 ``from src.x import y`` / ``import src.x`` 都必然先执行这里。

以脚本方式直接运行（``python src/fetch_data.py``）时不会触发本文件，
那两个入口脚本已各自显式调用了 :func:`configure_outbound_network`。

## 行为

- 幂等：重复导入不会叠加补丁；
- 可用 ``STOCK_FORCE_IPV4=0`` / ``STOCK_ASCII_CA_BUNDLE=0`` 单独关闭；
- 不发起任何网络请求，失败只记日志。
"""

from .net_guard import configure_outbound_network

configure_outbound_network()
