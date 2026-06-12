# Travel Agent

自用出门游玩推荐智能体，基于 LangGraph 实现。

## 安装依赖

```powershell
cd C:\Users\Lenovo\PycharmProjects\PythonProject
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## 配置环境变量

复制 `.env.example` 为 `.env`，填写 DeepSeek 配置：

```env
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

### 实时数据接口

天气、餐厅、酒店、小红书搜索都在 `travel_agent/tools` 下做成独立工具，`graph.py`
只负责串联数据和生成行程。

```env
# 墨迹天气
MOJI_WEATHER_URL=你的墨迹天气接口地址
MOJI_METHOD=GET
MOJI_CITY_PARAM=city
MOJI_DAYS_PARAM=days
MOJI_API_KEY=你的墨迹天气key
MOJI_KEY_PARAM=key

# 美团酒旅助手 Skill
MEITUAN_SKILL_MODE=cli
MEITUAN_SKILL_ID=12
MEITUAN_TRAVEL_CLI=mttravel.cmd
MEITUAN_DEFAULT_CITY=北京
MEITUAN_TRAVEL_ASSISTANT_TOOL=travel_assistant
MEITUAN_SKILL_ACCESS_TOKEN=你的token
MEITUAN_SKILL_LIMIT=8
MEITUAN_SKILL_TIMEOUT=150

# 小红书授权搜索接口
XHS_SEARCH_URL=你的小红书搜索接口地址
XHS_METHOD=GET
XHS_QUERY_PARAM=keyword
XHS_LIMIT_PARAM=limit
XHS_ACCESS_TOKEN=你的access_token
```

已下载到 `travel_agent/skills/meituan-travel` 的 Skill 包主要是调用说明；真实运行依赖
美团提供的 `mttravel` CLI。先安装：

```powershell
npm.cmd i -g @meituan-travel/travel-cli
```

`MEITUAN_SKILL_MODE=cli` 时，程序会调用 `mttravel [城市] "<query>"`。Windows PowerShell
下建议用 `MEITUAN_TRAVEL_CLI=mttravel.cmd`，避免 `.ps1` 执行策略拦截。如果
`~/.config/meituan-travel/config.json` 不存在，程序会用 `.env` 里的
`MEITUAN_SKILL_ACCESS_TOKEN` 自动写入：

```json
{"key": "你的token"}
```

`MEITUAN_DEFAULT_CITY` 是用户没有明确出发城市时传给 `mttravel` 的城市，默认可填 `北京`。
如果未安装 CLI 或未配置 Token，工具会返回 `config_required`，最终答案会在“数据说明”里
提示未接入，不会伪造实时结果。

当前 `graph.py` 会通过 `travel_agent/tools/meituan_skill.py` 调用一次美团酒旅助手，统一获取酒店、
本地餐厅、价格、评分、链接等实时内容；查询提示会尽量要求 5-6 家餐厅和 3-4 家酒店。结果会同时
进入“餐饮候选”和“住宿候选”，最终行程再把它们拆到每天的午餐、晚餐、可替换餐厅和住宿建议里。
工具会从美团返回的 Markdown 文本中解析 `[名称](链接)`，在结果里额外提供 `links` 字段，后续做
前端跳转时可以直接使用。

兼容模式仍保留：`MEITUAN_SKILL_MODE=http` 使用 `MEITUAN_SKILL_URL`，`command` 使用
`MEITUAN_SKILL_COMMAND_JSON`，`auto` 会优先尝试 HTTP、本地命令，最后尝试 `mttravel`。

## 运行

```powershell
python -m travel_agent.app
```

如果 Windows 控制台打印美团返回的 emoji 时报编码错误，可以先执行
`$env:PYTHONIOENCODING='utf-8'`，或在支持 UTF-8 的终端中运行。

示例输入：

```text
周末去苏州玩两天，预算1500，想吃本地菜，住宿不要太贵
```

## 后续接入

- `travel_agent/tools/weather.py`: 墨迹天气接口适配
- `travel_agent/tools/meituan_skill.py`: 美团酒旅 Skills 适配
- `travel_agent/tools/food.py`: 餐厅搜索
- `travel_agent/tools/hotel.py`: 酒店搜索
- `travel_agent/tools/xiaohongshu.py`: 小红书授权搜索
- `travel_agent/tools/transport.py`: 路线和交通建议
