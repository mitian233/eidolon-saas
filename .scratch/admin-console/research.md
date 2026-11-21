# 各服务 API 单价（用于后台「按单价估算花费」）

整理日期：2026-10-07。所有价格都来自服务方自己的价格页、官方文档，或 OpenRouter Models API（对 OpenRouter 上的价格算一手来源）。查不到的写「未查到」，没有凭记忆填写。仓库里早先的两份调研（`.scratch/cloudflare-judge/research.md`、`.scratch/jev-provider/research.md`）只当线索用，价格都重新核对过。

**口径说明**

- 花费 = 计费用量 × 单价。单价按系统记录用量的单位换算：
  - tokens：按「每百万 token」。LLM 分输入价和输出价。判断模型、向量化、重排只记输入 token，所以只给输入价。缓存命中价只写在备注里，系统按普通输入价算。
  - bytes：按「每百万 UTF-8 字节」。
  - seconds：按「每小时音频」。官方按秒计价的，乘 3600 后写出，并保留官方原文。
- 估算**不扣免费额度**，包括 Cloudflare 每天 10,000 neurons、阿里云新人额度、Gemini 免费档等。
- 只列标准（实时、非 Batch）价格。Batch、Flex、Fast、数据驻留加价等都只写在备注里。
- 「主机」指服务地址的主机名，和系统里「提供方」的键一致。

---

## 1. 扮演角色和提炼记忆用的 LLM（单位 tokens）

### 1.1 OpenAI（api.openai.com）

出处：https://developers.openai.com/api/docs/pricing （`platform.openai.com/docs/pricing` 会 301 跳转到这里）。数字取自页面的 Standard 表，单位是 USD / 1M tokens。

| 主机 | 模型 ID | 单位 | 输入价 | 输出价 | 币种 | 备注（缓存命中价等） |
|---|---|---|---|---|---|---|
| api.openai.com | `gpt-6-astra` | tokens | 10.00 | 50.00 | USD | 缓存命中 1.00，写缓存 12.50；长上下文 20.00 / 75.00 |
| api.openai.com | `gpt-6.1-sol` | tokens | 2.00 | 10.00 | USD | 缓存命中 0.10，写缓存 2.50；长上下文 4.00 / 15.00 |
| api.openai.com | `gpt-6-sol` | tokens | 2.00 | 10.00 | USD | 缓存命中 0.20，写缓存 2.50 |
| api.openai.com | `gpt-6-luna` | tokens | 0.10 | 0.50 | USD | 缓存命中 0.01，写缓存 0.125；长上下文 0.20 / 0.75 |
| api.openai.com | `gpt-5.6-sol` | tokens | 4.00 | 20.00 | USD | 缓存命中 0.40，写缓存 5.00。页面原文："GPT-5.6 Sol's promotional pricing is available at least through November 21, 2026"，即这是促销价 |
| api.openai.com | `gpt-5.4-mini` | tokens | 0.75 | 4.50 | USD | 缓存命中 0.075 |

- 页面原文的表头是 "Short context | Long context"，每组都有 "Input / Cached input / Cache writes / Output"。上表的主价格取 Short context。旧型号的行名写着 "(<272K context length)"，所以长、短上下文以 272K 输入 token 为界。
- 关于 Cache writes，原文："Input tokens are either Input, Cached Input, or Cache Write and writes are not an additive fee"。
- 关于输出价，原文："Output prices include visible output tokens and reasoning tokens"。
- 同一张表里还有 `gpt-5.6-terra`（2.00 / 12.00）、`gpt-5.6-luna`（0.20 / 1.20）、`gpt-5.5`（5.00 / 30.00）、`gpt-5.4`（2.50 / 15.00）、`gpt-5.4-nano`（0.20 / 1.25）、`gpt-5-mini`（0.25 / 2.00），需要时可以补上。
- 页面另注：数据驻留（Data residency）对 2026-03-05 及以后发布的模型加价 10%；Batch 打五折。

### 1.2 Anthropic（api.anthropic.com）

出处：价格见 https://platform.claude.com/docs/en/about-claude/pricing ，模型 ID 见 https://platform.claude.com/docs/en/about-claude/models/overview （`docs.claude.com` 会 302 跳转到 `platform.claude.com`）。单位是 USD / MTok。

| 主机 | 模型 ID（Claude API ID） | 单位 | 输入价 | 输出价 | 币种 | 备注 |
|---|---|---|---|---|---|---|
| api.anthropic.com | `claude-fable-5-1` | tokens | 10 | 50 | USD | 缓存命中 0.25（0.025 倍），5 分钟写缓存 12.50 |
| api.anthropic.com | `claude-opus-5-5` | tokens | 4 | 20 | USD | 缓存命中 0.20（0.05 倍），5 分钟写缓存 5 |
| api.anthropic.com | `claude-sonnet-5-5` | tokens | 2 | 10 | USD | 缓存命中 0.10（0.05 倍；2026-10-14 按 `.scratch/prompt-caching/research.md` 第 5 节更正，原写 0.20），5 分钟写缓存 2.50 |
| api.anthropic.com | `claude-haiku-4-5-20251001`（别名 `claude-haiku-4-5`） | tokens | 1 | 5 | USD | 缓存命中 0.10，5 分钟写缓存 1.25。官方写的退役时间是 "Not sooner than October 15, 2026" |

- 上面 4 个是 models overview 页列出的当前模型。价格页还列了旧版但仍可用的模型，比如 Claude Opus 5（5 / 25）、Claude Sonnet 5（2 / 10，原文注明 $2/$10 已转为标准价）。但 overview 页没给出这两个模型的 API ID 原文，所以没有列进表里。
- 页面另注：`inference_geo: "us"` 时所有 token 价格乘 1.1；Batch 打五折；4.6 及以后的模型 1M 上下文都按标准价计费，没有长上下文加价。

### 1.3 DeepSeek（api.deepseek.com）

出处：英文页 https://api-docs.deepseek.com/quick_start/pricing （USD），中文页 https://api-docs.deepseek.com/zh-cn/quick_start/pricing （CNY）。

DeepSeek 分**高峰和空闲两档价**。原文："Off-peak rates are half of the peak rates. Peak hours are 01:00 - 04:00 and 06:00 - 10:00 UTC, Monday through Friday"。中文页写的是："北京时间周一至周五（不含中国法定节假日）9:00 - 12:00、14:00 - 18:00 为高峰时段"。系统只能存一个价，建议取高峰价作为估算上限，或者取空闲价（一周大部分时间是空闲时段）。由你决定。

| 主机 | 模型 ID | 单位 | 输入价（缓存未命中）高峰 / 空闲 | 输出价 高峰 / 空闲 | 币种 | 缓存命中价 高峰 / 空闲 |
|---|---|---|---|---|---|---|
| api.deepseek.com | `deepseek-flash`（DeepSeek-V4.1-Flash） | tokens | 0.30 / 0.15 | 1.20 / 0.60 | USD | 0.006 / 0.003 |
| api.deepseek.com | `deepseek-v4-pro`（DeepSeek-V4-Pro-0813） | tokens | 1.32 / 0.66 | 3.96 / 1.98 | USD | 0.044 / 0.022 |
| api.deepseek.com | `deepseek-flash` | tokens | 2 / 1 | 8 / 4 | CNY | 0.04 / 0.02 |
| api.deepseek.com | `deepseek-v4-pro` | tokens | 9.0 / 4.5 | 27.0 / 13.5 | CNY | 0.30 / 0.15 |

- **模型名要注意**：官方页面原文是 "Use `deepseek-flash` as the model name. The legacy names `deepseek-v4-flash` and `deepseek-v4-flash-vision-exp` are still accepted, but the corresponding models have been retired, their requests are served by the DeepSeek-V4.1-Flash model and billed at the Flash price."。项目用的 `deepseek-v4.1-flash` **不在官方列出的模型名里**，DeepSeek 直连接受这个名字的说明未查到。如果它能调通，按 Flash 价计费是合理推断，但没有得到官方确认。建议价格表里同时为 `deepseek-flash` 和 `deepseek-v4.1-flash` 两个键配 Flash 价。
- 美元价和人民币价不是按汇率换算的关系，比如 Flash 高峰输入 $0.30 对应 2 元。按账户实际充值的币种选。
- 参考：OpenRouter 上有 `deepseek/deepseek-v4.1-flash`，价格为输入 $0.05/M、输出 $1.20/M（Models API，2026-10-07）。那是 openrouter.ai 主机上的价，和直连不同。

---

## 2. Fish Audio 语音合成（api.fish.audio，单位 bytes）

出处：https://docs.fish.audio/developer-platform/models-pricing/pricing-and-rate-limits （原始 Markdown：同一地址加 `.md`）

官方口径和系统一致。原文："TTS pricing is based on the size of input text, measured in millions of UTF-8 bytes."，所以不用换算。

| 主机 | 模型 | 单位 | 单价（每百万 UTF-8 字节） | 输出价 | 币种 | 官方原文 |
|---|---|---|---|---|---|---|
| api.fish.audio | `s2.1-pro-free` | bytes | 0.00 | - | USD | `$0.00 / M UTF-8 bytes` |
| api.fish.audio | `s2.1-pro` | bytes | 15.00 | - | USD | `$15.00 / M UTF-8 bytes` |
| api.fish.audio | `s2-pro` | bytes | 15.00 | - | USD | `$15.00 / M UTF-8 bytes` |
| api.fish.audio | `s1` | bytes | 15.00 | - | USD | `$15.00 / M UTF-8 bytes` |

- 官方备注："1M UTF-8 bytes is approximately 180,000 English words, or about 12 hours of speech"。
- 同一页还有：ASR `transcribe-1-pro` 和 `transcribe-1` 都是 $0.36 / audio hour；Voice Design `voice-design-1` 是 $0.01 / successful API request。本项目没用到。
- fish.audio/plan 上的订阅 credits（网页端产品）和 API 计费是两套体系，API 价格以上表为准。

---

## 3. Soniox 实时语音识别（stt-rt.soniox.com，单位 seconds）

出处：https://soniox.com/pricing

| 主机 | 模型 | 单位 | 单价（每小时音频） | 输出价 | 币种 | 官方原文 |
|---|---|---|---|---|---|---|
| stt-rt.soniox.com | `stt-rt-v5` | seconds | 0.12 | - | USD | "Equivalent to about ... $0.12/hour for real-time (streaming) transcription"；计算器里写 "Soniox stt-rt-v5 ... $0.12/hr" |

- Soniox 实际按 token 计费。实时（streaming）的 token 价：
  - Input audio tokens（"Duration of audio or streaming session"）：$2.00 per 1M tokens
  - Input text tokens（自定义上下文）：$4.00 per 1M tokens
  - Output text tokens（转写文字）：$4.00 per 1M tokens
- 官方用量参考："1 hour of audio is ~30,000 input audio tokens • 1 hour of speech is ~15,000 output text tokens"。
- 换算核对：30,000 × $2/M 加上 15,000 × $4/M，正好是 $0.12/小时，和官方的「每小时约 $0.12」一致。这个价已经包含了按满语音估计的输出文字。如果送了很长的自定义 context，会多出 input text 费用，按秒估算算不到这部分。

---

## 4. 阿里云百炼实时语音识别（单位 seconds）

出处：
- 模型页（中文）：https://help.aliyun.com/zh/model-studio/qwen-audio-3-1-asr-flash-streaming
- 模型页（英文，USD）：https://www.alibabacloud.com/help/en/model-studio/qwen-audio-3-1-asr-flash-streaming
- 总价格页（中文）：https://help.aliyun.com/zh/model-studio/model-pricing
- 总价格页（英文）：https://www.alibabacloud.com/help/en/model-studio/model-pricing

### 4.1 `qwen-audio-3.1-asr-flash-streaming`：**查到了，但官方按 token 计费，不按秒**

总价格页原文："qwen-audio-3.1-asr-flash-streaming：按输入和输出 Token 数分别计费。"

| 地域 / 主机 | 输入价 | 输出价 | 币种 | 单位（官方） |
|---|---|---|---|---|
| 华北 2（北京）/ dashscope.aliyuncs.com | 6 | 4.5 | CNY | 每百万 Token |
| 新加坡（国际）/ dashscope-intl.aliyuncs.com | 0.93 | 0.70 | USD（英文页） | per million tokens |
| 新加坡（国际），中文页标的人民币价 | 6.781 | 5.104 | CNY | 每百万 Token |
| 北京，英文页标的美元价 | 0.848 | 0.636 | USD | per million tokens |

- **换算成「每小时音频」的结论是未查到**：官方没有给出这个模型「每秒音频等于多少 token」的系数，所以换算不出来。
  - 总价格页里「千问 Audio」一节（`qwen-audio-turbo`）写的是「每一秒钟的音频对应 25 个 Token」；「实时语音对话」一节（`qwen-audio-3.x-realtime-*`）写的是「总 Token 数 = 音频时长（单位：秒）* 12.5」。这两条都**不是**针对 3.1-ASR-Flash-Streaming 的，不能直接套用。
  - 如果硬套 25 token/秒，北京地域输入约 6 × 90,000 / 1,000,000 = 0.54 元/小时，另加输出文字的 token 费。这只是推测，不是官方口径。
  - 第三方文章（阿里云开发者社区，非官方）报告实测 24.88 秒音频记了 368 个输入词元，约 14.8 token/秒。只能当线索。
- 这个模型在北京地域有 100 万 Token 免费额度（90 天），按约定估算时不扣。

### 4.2 价格页上最接近的按秒计费实时识别模型（参考，**不是同一个模型**）

| 地域 / 主机 | 模型 | 官方原文 | 折合每小时 | 币种 |
|---|---|---|---|---|
| 北京 / dashscope.aliyuncs.com | `qwen-audio-3.0-asr-flash-streaming`（上一代同系列） | 0.00033 元/秒，输出不计费 | 1.188 | CNY |
| 新加坡 / dashscope-intl.aliyuncs.com | `qwen-audio-3.0-asr-flash-streaming` | $0.00009/second（英文页）；中文页写 0.00066 元/秒 | 0.324 USD；2.376 CNY | USD / CNY |
| 北京 | `fun-asr-realtime` | 0.00033 元/秒 | 1.188 | CNY |
| 新加坡 | `fun-asr-realtime` | 0.00066 元/秒（中文页） | 2.376 | CNY |
| 北京 | `paraformer-realtime-v2` | 0.00024 元/秒 | 0.864 | CNY |
| 北京 | `qwen3-asr-flash-realtime` | 0.00033 元/秒（模型页） | 1.188 | CNY |

---

## 5. 判断模型经 OpenRouter（openrouter.ai，单位 tokens，只记输入）

出处：OpenRouter Models API `GET https://openrouter.ai/api/v1/models?output_modalities=all`（2026-10-07 实测；不带 `output_modalities=all` 时列表里看不到 decisions 类模型）。`pricing.prompt` 和 `pricing.completion` 的单位是 USD/token，下表已乘 1,000,000。模型页：https://openrouter.ai/typesafe/jev-1.13 、https://openrouter.ai/cloudflare/clef 、https://openrouter.ai/cloudflare/clef-flash

| 主机 | 模型 | 单位 | 输入价 | 输出价 | 币种 | API 原文 |
|---|---|---|---|---|---|---|
| openrouter.ai | `typesafe/jev-1.13` | tokens | 0.042 | 0（不收费） | USD | `prompt: "0.000000042", completion: "0"`，modality `text->decisions` |
| openrouter.ai | `~typesafe/jev-latest`（别名） | tokens | 0.042 | 0 | USD | 同上 |
| openrouter.ai | `cloudflare/clef` | tokens | 0.24 | 0 | USD | `prompt: "0.00000024", completion: "0"` |
| openrouter.ai | `cloudflare/clef-flash` | tokens | 0.09 | 0 | USD | `prompt: "0.00000009", completion: "0"` |

- **Jev 不收输出费**（completion 为 "0"），所以系统只记输入的口径是对的。
- OpenRouter 充值另收手续费（据旧调研：5.5%，最低 $0.80），不计入单价。

---

## 6. Cloudflare Workers AI 直连 Clef（api.cloudflare.com，单位 tokens，只记输入）

出处：https://developers.cloudflare.com/workers-ai/platform/pricing/ （"Other model pricing" 一节）

| 主机 | 模型（请求体里的 `model`） | 单位 | 输入价 | 输出价 | 币种 | 官方原文 |
|---|---|---|---|---|---|---|
| api.cloudflare.com | `clef`（`@cf/cloudflare/clef`） | tokens | 0.24 | - | USD | "$0.240 per M input tokens / 21818 neurons per M input tokens" |
| api.cloudflare.com | `clef-flash`（`@cf/cloudflare/clef-flash`） | tokens | 0.09 | - | USD | "$0.090 per M input tokens / 8182 neurons per M input tokens" |

- 表里只列了输入价，没有输出价这一列。
- 免费额度原文："Our free allocation allows anyone to use a total of 10,000 Neurons per day at no charge"。超出部分要开 Workers Paid，按 "$0.011 / 1,000 Neurons" 收费。额度每天 00:00 UTC 重置。按约定，**估算不扣这份免费额度**。

---

## 7. 向量化（单位 tokens，只记输入）

### 7.1 硅基流动（api.siliconflow.cn）

出处：https://siliconflow.cn/pricing 。页面是 JS 渲染的，价格是从页面内嵌的 Next.js 数据里解析出来的，字段是 `"price"`、`"currency":"¥"`、`"priceUnit":"/ M Tokens"`，`pricing` 数组里 prompt 一项是下面的价，completion 一项是 0。`https://api.siliconflow.cn/v1/models` 需要 key，不带 key 返回 401。

| 主机 | 模型 | 单位 | 输入价 | 输出价 | 币种 | 官方口径 |
|---|---|---|---|---|---|---|
| api.siliconflow.cn | `Qwen/Qwen3-Embedding-0.6B` | tokens | 0.07 | - | CNY | ¥ / M Tokens |
| api.siliconflow.cn | `Qwen/Qwen3-Embedding-4B` | tokens | 0.14 | - | CNY | ¥ / M Tokens |
| api.siliconflow.cn | `Qwen/Qwen3-Embedding-8B` | tokens | 0.28 | - | CNY | ¥ / M Tokens |

### 7.2 Gemini（generativelanguage.googleapis.com）

出处：https://ai.google.dev/gemini-api/docs/pricing （"Gemini Embedding 2" 一节）

| 主机 | 模型 | 单位 | 输入价 | 输出价 | 币种 | 官方原文 |
|---|---|---|---|---|---|---|
| generativelanguage.googleapis.com | `gemini-embedding-2` | tokens | 0.20 | - | USD | Standard, Paid Tier, per 1M tokens: "Text input price ... $0.20" |

- 维度后缀（如 `@1536`）不影响价格，官方没有按维度区分价格。
- 其他：Batch 的文本输入价是 $0.10；图片 $0.45，音频 $6.50，视频 $12.00（每百万 token）。Free Tier 是 "Free of charge"，但原文注明 Free Tier "Used to improve our products: Yes"。

---

## 8. 重排（api.siliconflow.cn，单位 tokens，只记输入）

出处同 7.1。

| 主机 | 模型 | 单位 | 输入价 | 输出价 | 币种 | 官方口径 |
|---|---|---|---|---|---|---|
| api.siliconflow.cn | `Qwen/Qwen3-Reranker-0.6B` | tokens | 0.07 | - | CNY | ¥ / M Tokens |
| api.siliconflow.cn | `Qwen/Qwen3-Reranker-4B` | tokens | 0.14 | - | CNY | ¥ / M Tokens |
| api.siliconflow.cn | `Qwen/Qwen3-Reranker-8B` | tokens | 0.28 | - | CNY | ¥ / M Tokens |

---

## 9. 未查到 / 有疑问

1. **`qwen-audio-3.1-asr-flash-streaming` 按秒的价格未查到**。官方按输入、输出 token 计费（北京 6 / 4.5 元每百万 Token；新加坡 $0.93 / $0.70），而且没有公布「每秒音频等于多少 token」。系统按秒记用量，没法用官方口径直接换算。可以选的做法：
   - 改为记录响应里的 token 用量；
   - 用上一代 `qwen-audio-3.0-asr-flash-streaming` 的按秒价作参考（北京 1.188 元/小时；新加坡 $0.324/小时），并标明是参考价；
   - 先不给这个键配价。
2. **DeepSeek 模型名 `deepseek-v4.1-flash`**：官方价格页没有列出这个名字（只列了 `deepseek-flash`，以及旧名 `deepseek-v4-flash`、`deepseek-v4-flash-vision-exp`）。直连是否接受这个名字、按什么价计费，都未查到官方说明。
3. **DeepSeek 分高峰和空闲价**，系统只能存一个价，需要决定取哪一档。DeepSeek 的 USD 价和 CNY 价也要按账户币种二选一。
4. **OpenAI `gpt-5.6-sol` 是促销价**（"at least through November 21, 2026"），之后可能涨价。
5. **Anthropic 旧版模型**（Opus 5、Sonnet 5 等）的价格查到了，但 API ID 原文没有在 overview 页核对，所以没列进表里。
6. **Soniox** 的 $0.12/小时是官方给的等效价，已经包含按满语音估计的输出文字 token。如果有大量自定义 context（input text tokens，$4/M），按秒估算会偏低。
7. 阿里云新加坡地域的价格，中文页标的是人民币（6.781 / 5.104 元），英文页标的是美元（0.93 / 0.70）。国际站账户实际按哪种币种结算，以账单为准，这一点未确认。

---

## 10. 写进代码的预设（`backend/src/eidolon/prices.py` 的 `PRESETS`）

> ticket 14 之后，预设只是兜底：按 tokens 计费的模型优先用在线目录的价格（第 11 节），只有目录拉取不到、或者目录里没有的模型才用预设。按字节和按秒计费的单价始终用预设。下面关于 DeepSeek 人民币价的取舍只在目录拉取不到时有效；目录里 DeepSeek 是美元价。

按上面的表照抄，整理日期都是 2026-10-07。取舍如下：

- **DeepSeek 取人民币的高峰价**（`deepseek-flash`、旧名 `deepseek-v4-flash` 2 / 8 元，`deepseek-v4-pro` 9 / 27 元每百万 token）：估算宁可偏高；空闲时段是它的一半。用美元结算的部署者在「配置」页改成美元价即可。
- **`deepseek-v4.1-flash` 不放预设**：官方价格页没有这个名字（第 9 节第 2 条）。看板上显示「未设单价」，管理者可以在「配置」页按 Flash 价补上。
- **阿里云百炼的 `qwen-audio-3.1-asr-flash-streaming` 不放预设**：官方按 token 计费，系统按音频秒数记用量，换算系数未查到（第 9 节第 1 条）。
- OpenAI、Anthropic 只放上面表里的当前模型；Anthropic 的 Haiku 4.5 同时放了带日期的 ID 和别名。
- 判断模型（Jev、Clef）、向量化和重排只有输入价；LLM 有输入、输出两个价；缓存命中价、Batch 价、长上下文价都不算。
- Gemini 向量化的模型在运行记录里带维度后缀（`gemini-embedding-2@1536`），按不带后缀的模型找单价。不过目前 Gemini 的接口不返回用量，它的调用在看板上都算「用量未知」。

## 11. 在线价格目录（ticket 14 用）

2026-10-07 实测，做法参照 magpie（https://github.com/yetone/magpie 的 `internal/catalog/catalog.go`、`fresh.go`）。

**来源**

- models.dev：`GET https://models.dev/api.json`，226 个提供方。每个模型的 `cost` 是 USD/百万 token（`input`、`output`、`cache_read`、`cache_write`，部分有按上下文长度分档的 `tiers`）。约 200 个提供方带 `api` 字段（服务地址，例如 `https://api.deepseek.com`、`https://api.siliconflow.cn/v1`），`openai`、`anthropic`、`google` 没有。
- OpenRouter：`GET https://openrouter.ai/api/v1/models?output_modalities=all`。`pricing.prompt` 和 `pricing.completion` 是 USD/token（见第 5 节）。

**现有预设在目录里的覆盖情况**

| 预设 | 目录 |
|---|---|
| OpenAI 6 个模型、Anthropic 5 个、Gemini `gemini-embedding-2` | models.dev 有，价格与第 1、7 节一致 |
| DeepSeek `deepseek-flash`、`deepseek-v4-flash`、`deepseek-v4-pro` | models.dev 有，但为美元：0.15/0.6、0.15/0.6、0.66/1.98。和第 1.3 节的人民币高峰价不同，决定用目录的价格 |
| `deepseek-v4.1-flash` | models.dev 也没有（只有 `deepseek-v4-flash-vision-exp`） |
| Jev、Clef、Clef-flash 经 OpenRouter | models.dev 的 `openrouter` 下没有价格；OpenRouter 自己的 API 有（0.042、0.24、0.09，输出 0），与第 5 节一致 |
| Cloudflare 直连 Clef | models.dev 的 `cloudflare-workers-ai` 里没有，留在预设 |
| 硅基流动的向量化和重排 | models.dev 的 `siliconflow-cn` 里没有，留在预设 |
| Fish Audio、Soniox | models.dev 没有这两个提供方，而且只收按 token 计价的模型，留在预设 |

**从 VPS 访问**

- 宿主机直连两个地址都返回 200。models.dev 不压缩时 5.3 MB、用时 30.7 秒；带 `Accept-Encoding: gzip` 时下载 0.44 MB、用时 3.2 秒。OpenRouter 不压缩时 0.98 MB、用时 4.3 秒。
- 上游当时用自己的后端容器试过 Python `urllib` 的 gzip 请求。models.dev 1.5 秒，OpenRouter 0.5 秒，容器内直连。
