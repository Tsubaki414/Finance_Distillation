# 真实样本链路：lineage broken

样本事件 `bls-employment-2026-08`，version `75155f58f5a995e3`。该事件是真实获取的原文衍生件；以下仅证明存储及转换，未声称金融语义已经真人验证。取宏观 persona 的计划与真实 qinbafrank 检索样本；**没有完整 source→donor→draft→citation 成功链路**。

| 步骤 | ID / 文件 | 输入→输出 / 转换代码 | 时间、版本、模型、prompt | 状态 |
|---|---|---|---|---|
| 事件来源 | https://www.bls.gov/news.release/pdf/empsit.pdf；sources/acquisition.json | 原 PDF 403；Jina derivative 200→完整原文文本 | published 2026-09-04 08:30 −04:00；fetch 2026-09-06T04:36:38.223742Z | 衍生文本，不是原 PDF 二进制 |
| 事件 raw | evidence_loop/sources/bls-full-reader.txt | 163478 bytes，完整 39 页文本；SHA `23717afd4e5677deebb8fd19ff24e330756eef18aacd8f0d71f07957b74088d6` | acquisition 保存 URL/status/hash；无模型 | verified hash |
| fact | payroll；packet 75155f58f5a995e3.json | raw characters [600,653) → 162000 persons, 2026-08 CES，block B0012；build_event.py regex/单位换算 | 51 facts/616 blocks；processing observed_at 2026-09-06T04:58:36.271245Z | span 可逐字符复核；observed_at 误用处理时间，不是重新抓取时间 |
| donor source/raw | qinbafrank post `2072665494768021550`；data/raw_posts.jsonl | X 原帖 https://x.com/qinbafrank/status/2072665494768021550 → inherited provider source_record/hash | created 2026-07-02T12:55:36Z；import-794f061e4f6d；collected_at 以原行字段为准，缺失不补 | 历史 donor 表达，不是本次 Aug 数据证据 |
| donor clean | 同 post ID；data/clean_posts.jsonl raw_source_ref | promotion_policy + import_corpus.classify、同作者精确去重；原 raw 不改 | rules-v3-commercial-cleanup；无 LLM | clean 可回 raw payload SHA；语言/原创分类未真人审核 |
| donor quantification | qinbafrank profile `a8e2585d5d288be0` | 312 clean 帖 → knowledge/ reasoning/style/habit/visual；每项 n、公式、support/denominator IDs | empirical-five-profile-v1；profile window 2026-07-01→09-05 | 表层统计；全语料回顾画像含事件后帖子，不是 point-in-time backtest |
| retrieval | experiments/retrieval.json results.macro[0] | 真实 query embedding→该 post cosine/排序，macro 共 3 donor×2 exemplar | MiniLM-L12-v2 rev e8f8c211226b894fcb81acc59f3b34ba3efd5f42；routing 指定版本；created protocol 2026-09-06T05:10:26.192706Z | 真实检索，历史样本均早于 event release |
| 组合决策 | experiments/routing.json macro | qinbafrank、phyrexni、michael_qqq2025；分五角色权重 | top2 cosine/主题率/样本数的人工公式；非学得最优组合 | planned route；没有被本次已运行 simple/base plan 消费 |
| 实际 neutral plan | case-3805e3a232c8；model call local-a1ec004c02684efa | 同完整 narrative+51 typed facts→plan JSON；无 donor/persona（控制组设计） | 2026-09-06T05:12:37.545840Z；modern 锁定 Qwen3.5-4B、temp .2、seed42、max_tokens650 | finish_reason=length，650 tokens；JSONDecodeError，未到 draft |
| 实际 persona plan | case-21b8d4f70185；local-e34f0c6259364bd3 | 同事实+macro name/question→独立计划；没有 donor profile/exemplar | 2026-09-06T05:15:30.679265Z；temp .2、seed42、650 budget；532 output tokens；stop | JSON 可解析；无真人研究质量认证 |
| draft | local-0538caa511c642cf；task evidence_loop_draft | 请求文件记录新事实和独立计划，max_tokens2400；响应未保存 | 2026-09-06T05:16:25.719936Z，started；之后用户要求停止 | 中断；case 未保存 generation_run_id，只有时间/task/context 关联，不伪造直接外键 |
| citation/influence/QA | 当前新 case 无 sentence_to_source_ledger / sentence_to_donor_ledger | run_experiments.py 后续代码未到达成稿完成 | 无完成时间、无新稿 hash、无事实忠实度/盲测/编辑成本 | **lineage broken** |

完整模型 revision、request messages、temperature/max_tokens、输出及错误均以相应 model_calls JSON 为准。三次 neutral base 的相同输入/seed 输出重复是控制设计，不是三个 persona 研究成功。尚未执行 structured/profile+exemplar/multi-separated 格；不能将预先准备的 retrieval 拼接成“实际 donor influence”。

视频旁支例：`youtube:6weg9-YmGVs:22666-7eb1cb12` 在 transcripts/segments.jsonl，对应原 VTT、cue-1 等 IDs、22.666–69.1 秒和 timestamp URL。raw_hash 校验通过，但 speaker=null、没有 Claim Card、未合入 donor profile。该视频发表于非农之前，不能标为非农公布后的反应。此 segment 也不能补成上面断掉的 donor→draft 链。

下一次合格证据闭环必须有主键连接所有阶段，记录真实消费 ID 而非预选 ID，并将逐句引文的“ID 有效”与“事实支持该句”分别评估。缺数据时保持 null/unknown，不让提示词补造。
