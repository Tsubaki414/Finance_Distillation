# 视频语料：要求与已运行状态

要求是可检索、可追溯的视频语料蒸馏，不是视频摘要。来源全片 transcript 和 segment 永久保留；人类字幕优先→平台自动字幕→无字幕时 ASR。然后说话人分离、金融专名/ticker/数字/百分比/日期校正、segment、内容分类、统一 KOL corpus、profile 更新，再进入热点或 Evergreen。

## 上游审计

`KIRVO-REPORTING/video-to-notes` 已阅读审计，commit `aa06415ef985290398db765271d6e85a66c436db`，证据 `evidence_loop/video-audit.json`（11 文件 hash）和 `historical_workspace/work/repo-audit/video-to-notes/`。没有执行上游 installer 或摘要 pipeline。可借鉴 discovery、metadata、caption fetch、timestamp、Whisper fallback；不能复用自动摘要作为蒸馏结果。

审计发现字幕处理会丢时间结构、installer 有全局目录删除路径、可选浏览器 cookies/Notion/Obsidian 配置和媒体清理路径。项目自写 wrapper 保留原文件，匿名公开访问，不抽取账户 Cookie。Bilibili CLI 0.6.2 wheel 仅审计未安装运行，其 auth 可能读本地凭证/浏览器刷新；实际采用匿名 bilibili-api-python 获取允许的音频。具体网络/凭证/费用审计以 video-audit.json 为准。

## 当前真实数据

| 视频 ID | 平台 | 已保存 | 未完成 |
|---|---|---|---|
| 6weg9-YmGVs | YouTube 游庭皓 | metadata、auto_caption zh-TW、1172 cues、47 segments、全文/hash | speaker 未分离；该片早于 BLS 发布，不能当事后观点 |
| VFPlA2c5MfI | YouTube Brian Shannon | metadata、auto_caption en-orig、2761 cues、75 segments、全文/hash | speaker/金融语义校正/原则提取未完成 |
| tOk7gGe_jj0 | YouTube The Quant Brief | metadata、auto_caption en-orig、1037 cues、27 segments、全文/hash | 没有进入热点 Claim Graph |
| 01s3YdYUCcU | YouTube 美投讲美股 | metadata | 无字幕；音频 403，未 ASR |
| BV1eubj6GEaV | Bilibili 川叔叔Chris | metadata/player 响应、m4a/16k WAV/hash | 匿名字幕为空；ASR/说话人未运行 |
| BV1qMt26hEGs | Bilibili 笨鸟不会飞怎么飞 | 同上 | 同上 |
| BV1xS4y1x7Tp | Bilibili Jim做交易 | 同上；2022 历史交易知识视频 | ASR/原则/反例/冲突图未运行 |

目前共 149 segments，规则标记 knowledge_eligible=108；这不是通过真人审核的 108 条知识。没有 Bilibili transcript，未满足 3+3 验收。下载 Whisper Turbo 与 diarization ONNX 权重只证明准备完成，锁在 transcripts/audio-model-lock.json；没有 ASR/diarization 输出。准备/采集脚本有部分 log 覆盖历史重试问题，不应再次覆盖。

## 必需 segment contract 与当前差距

必须包含 platform/channel/video ID/title/published_at/original URL、start/end、speaker/speaker confidence、raw caption/clean text、caption_source (`human_caption/auto_caption/ASR`)、内容类型（事实、观点、推理、预测、案例、交易规则、广告、闲聊）、公司/ticker/资产/宏观指标/数字/日期、主题/方向/周期/置信度、timestamp URL、raw_file/hash/cue IDs、提取模型/版本/run ID、纠正前后与证据。

现有 segment 已保存 metadata、raw/clean、时间/hash/cue引用和时间戳链接；speaker/confidence 是 null，分类是 provisional regex，方向/周期/置信度为 unknown。不能把字符规范化当数字事实校正；ASR 数字和名称仍需原音、官方出处校验。speaker confidence 设计为时间重叠率，不是校准概率或真人身份认证。

跨平台去重需要 title + transcript 语义/指纹、可用时音频指纹并保留两个 URL。现有代码仅对 transcript_ready 比较；3 个 ready 全来自 YouTube，实际跨平台配对 0。`cross_platform_dedup=[]` 不能解释为已验证没有重复。

视频应主要更新 Knowledge/Reasoning Profile、Framework Library、Prediction Ledger、Evergreen Library。当前尚未写入统一 corpus 或这些 profile。短帖 Style/Habit 继续主要从真实短帖学习，149 segments 均 short_post_style_eligible=false。

恢复实施后先校验 Bili 3 音频→ASR→说话人→金融数字/日期→完整 segment；原 VTT/音频不删。之后至少两个与同一真实热点有关的 segment 和五名 KOL 原帖形成 Claim Graph。保留适用范围、不能把发布前视频当事件后反应；提供完整回放和时间戳回源。
