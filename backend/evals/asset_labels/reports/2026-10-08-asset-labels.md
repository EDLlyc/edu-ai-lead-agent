# Qwen3-VL 品牌素材自动打标签（离线评测，2026-10-08）

- 素材 41 张（动作图 26 张、形象图 15 张），标准答案是现有私有素材清单（人物、道具经人工确认；动作和场景标签来自清单生成规则，偏粗）。
- 每张图只给图片本身（不给文件名），另附每个角色一张全身参考图（其中 2 张本身也在被测素材里）。
- 道具、动作、场景只在动作图上评；形象图按清单惯例固定为无道具、无动作、场景 brand。

| 指标 | qwen3-vl-plus | qwen3-vl-flash |
|---|---|---|
| 已标注 / 触达调用上限 | 41 / 否 | 41 / 否 |
| 非法输出（重试后仍不合法） | 0 | 6 |
| 调用次数 / 平均耗时 | 43 / 2.6s | 47 / 1.3s |
| 平均输入 / 输出 token | 1,833 / 67 | 1,854 / 83 |
| 形象图 / 动作图分类正确 | 25/41（61%） | 23/35（66%） |
| 人物完全正确 | 41/41（100%） | 32/35（91%） |
| 人物 精确率 / 召回率 | 100% / 100% | 93% / 93% |
| 道具完全正确（动作图） | 21/26（81%） | 16/21（76%） |
| 道具 精确率 / 召回率 | 81% / 81% | 80% / 73% |
| 动作 精确率 / 召回率（粗标） | 56% / 28% | 45% / 21% |
| 场景 精确率 / 召回率（粗标） | 30% / 22% | 22% / 16% |

## qwen3-vl-plus：错在哪里

- 人物（对/多标/漏标）：xiao-sai 22/0/0；sai-xiansheng 27/0/0
- 道具（对/多标/漏标）：astronaut 6/0/0；book 1/1/1；brand_team 0/0/1；detector 1/0/0；explorer 1/0/0；microscope 1/1/0；specimen 0/0/1；telescope 1/0/0；time_machine 2/1/0
- 道具错配（标准 → 模型）：specimen → ∅ ×1；time_machine → book,time_machine ×1；book → time_machine ×1；book → book,microscope ×1；brand_team → ∅ ×1

## qwen3-vl-flash：错在哪里

- 人物（对/多标/漏标）：xiao-sai 19/3/0；sai-xiansheng 19/0/3
- 道具（对/多标/漏标）：astronaut 5/0/1；book 0/1/0；brand_team 0/1/1；microscope 1/0/0；specimen 0/0/1；telescope 1/0/0；time_machine 1/0/0
- 人物错配（标准 → 模型）：sai-xiansheng → xiao-sai ×3
- 道具错配（标准 → 模型）：specimen → ∅ ×1；time_machine → book,time_machine ×1；∅ → brand_team ×1；brand_team → ∅ ×1；astronaut → ∅ ×1
