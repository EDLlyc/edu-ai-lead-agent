# Same-topic headline rule

- Pairs: 20 (9 same topic), real production headlines
- Headline clause only; missed pairs may still be caught by the embedding clause.

| Rule | Precision | Recall | False same-topic | Missed |
|---|---|---|---|---|
| `current` | 0.438 | 0.778 | 9 | 2 |
| `candidate` | 1.0 | 0.778 | 0 | 2 |

## `current` errors

- `s02-university-classified-reform` missed_same_topic: 中共中央办公厅 国务院办公厅印发《关于分类推进高校改革的意见》 ~ 教育部：建立分类评价机制 推进各类高校特色发展
- `s05-beidou-industry` missed_same_topic: 从“天上星座”到身边“时空底座” 北斗产业规模加速向万亿级跃升 ~ AI加速渗透、从卖产品到卖服务、出海成关键增量 冲刺万亿 北斗产业发展呈三大新动向
- `d01-opening-speech-boilerplate` false_same_topic: 张国清出席第五届北斗规模应用国际峰会开幕式并致辞 ~ 李强出席2026年世界技能大会开幕式并致辞
- `d02-year-number` false_same_topic: 2026年APEC工商领导人峰会将于11月17日至18日在深圳举办 ~ 李强出席2026年世界技能大会开幕式并致辞
- `d03-money-figures` false_same_topic: 8000亿元新型政策性金融工具资金加快投放 ~ 前8个月全国完成水利建设投资近7000亿元
- `d04-summit-opening` false_same_topic: 丁薛祥在第23届中国－东盟博览会暨中国－东盟商务与投资峰会开幕式上的致辞（全文） ~ 张国清出席第五届北斗规模应用国际峰会开幕式并致辞
- `d05-issuing-bodies` false_same_topic: 中共中央办公厅 国务院办公厅印发《关于分类推进高校改革的意见》 ~ 中共中央办公厅 国务院办公厅 中央军委办公厅印发《退役军人服务和保障“十五五”规划》
- `d06-bnu-name-a` false_same_topic: 北京师范大学党委理论学习中心组：系统性重塑师范育人新范式 ~ 国际爱护动物基金会一行访问北京师范大学
- `d07-bnu-name-b` false_same_topic: 北京师范大学—山西省乡宁县基础教育高质量发展行动计划座谈会举行 ~ 北京师范大学党委理论学习中心组：系统性重塑师范育人新范式
- `d08-high-quality-development` false_same_topic: “扎实推进先进制造业高质量发展”——习近平总书记引领我国加快向制造强国迈进 ~ 北京师范大学—山西省乡宁县基础教育高质量发展行动计划座谈会举行
- `d09-column-prefix` false_same_topic: 总编辑圈点丨首个月球模型发布并开源，将数十年观测数据转化为可复用工具 ~ 总编辑圈点 | 63℃仍能分裂繁殖，火变形虫改写真核生物耐热上限

## `candidate` errors

- `s02-university-classified-reform` missed_same_topic: 中共中央办公厅 国务院办公厅印发《关于分类推进高校改革的意见》 ~ 教育部：建立分类评价机制 推进各类高校特色发展
- `s05-beidou-industry` missed_same_topic: 从“天上星座”到身边“时空底座” 北斗产业规模加速向万亿级跃升 ~ AI加速渗透、从卖产品到卖服务、出海成关键增量 冲刺万亿 北斗产业发展呈三大新动向
