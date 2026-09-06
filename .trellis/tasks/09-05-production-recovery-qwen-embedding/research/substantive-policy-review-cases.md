# Independent substantive-topic review cases

These authored synthetic cases exercise the approved R7/AC6 boundary without providers, private
content or production data. They are not human annotations, a measured precision/recall dataset,
or a prediction about any provider safety verdict. `accept` means substantive candidacy only:
the existing evidence, hard-veto and eligibility gates still apply. `reject` means this body does
not substantiate the approved subject. Inputs are intentionally varied; implementation should
model subject, predicate and continuity rather than blacklist these sample words or speakers.

## Executable input matrix

Each row has one title and one body. Literal `\n` represents a paragraph boundary.

| ID | Expected | Title | Body |
|---|---|---|---|
| trade-research-incidental | reject | 区域合作会议召开 | 会议研究区域经贸合作的总体安排，代表讨论交通口岸与旅游服务，双方表示人工智能领域值得关注，后续将完善交流机制并落实双边合作计划。 |
| trade-require-incidental | reject | 代表团举行工作会谈 | 会谈要求各方扩大贸易规模并持续完善金融结算机制，代表顺带谈到人工智能，双方随后讨论旅游航线和地方文化交流安排。 |
| long-unpunctuated-trade | reject | 经贸论坛发布合作倡议 | 会议研究人工智能之外的港口贸易与旅游协作并要求各方扩大金融结算便利化同时明确后续商贸展览和客运航线合作安排以及文化交流和边境通关服务措施。 |
| mixed-meeting-ai-clause | reject | 多方召开合作会议 | 代表讨论港口运输和货物通关的年度合作计划。会议提出人工智能治理合作倡议。双方还协商旅游签证便利化措施和文化交流安排，并发布新一轮经贸合作意向清单。 |
| bare-keywords | reject | 本周发展情况通报 | 人工智能 大模型 芯片 机器人 人工智能 大模型 芯片 机器人。量子计算 航天 生物技术 量子计算 航天 生物技术。 |
| noun-action-overlap-quantum | reject | 本周关键词汇总 | 量子计算 量子计算 量子计算 量子计算 量子计算 量子计算。 |
| noun-action-overlap-recovery | reject | 合作方向词语列表 | 可回收火箭 可回收火箭 可回收火箭 可回收火箭 可回收火箭。 |
| repeated-single-anchor | reject | 综合合作情况通报 | 本次会议主要讨论旅游航线和贸易结算安排并协调多个地方的口岸服务。人工智能模型发布。人工智能模型发布。人工智能模型发布。人工智能模型发布。 |
| title-only | reject | 新一代人工智能推理模型发布 |  |
| title-body-disagreement | reject | 人工智能技术交流新进展 | 代表团举行欢迎仪式并参观城市展馆。随后讨论农产品进口和旅游航线，双方签署地方文化交流备忘录，并安排下一年度经贸合作访问。 |
| distant-education | reject | 城市公共服务工作会议召开 | 人工智能成为会议背景资料中的一个词语。代表讨论道路维护和商贸市场经营情况，决定改善交通秩序。另一份情况介绍提到普通学校招生人数。 |
| genuine-ai-governance | accept | 人工智能治理办法公布 | 新办法明确人工智能模型上线前开展风险评估和能力测试。该标准规范训练数据管理与模型安全评测程序。 |
| genuine-international-ai-policy | accept | 多国代表公布人工智能治理标准 | 各国代表发布人工智能风险评估标准，规范模型能力测试和训练数据审查。该标准提出统一评测方法并明确技术报告要求。 |
| genuine-science-education | accept | 学校开展科学课程改革 | 学校开设科学教育实验课程并组织教师培训。学生在课堂中测量温度变化并记录实验数据。 |
| genuine-research | accept | 团队公布最新研究结果 | 团队研制新型量子计算芯片。实验测得其误差率低于此前方案，测试结果显示该器件在低温条件下保持稳定。 |
| neutral-headline-measurements | accept | 研究团队公布实验结果 | 团队开发新型人工智能推理模型。其准确率达到百分之九十二。实验测得延迟降低三成。该系统功耗较此前方案减少一半。 |
| neutral-headline-long-detail | accept | 一项新成果对外发布 | 团队研制新型量子芯片。其工作温度达到二十毫开尔文。实验测得误差率下降三成。该器件在持续测试中表现稳定。其性能在不同条件下得到验证。 |
| concrete-product | accept | 研发团队推出新产品 | 团队推出新型机器人控制系统并公开测试方法。该系统采用视觉算法完成机械臂定位，测试显示其精度和响应速度得到改善。 |
| english-research | accept | Researchers report new results | Researchers developed a quantum computing processor. The experiment measured its error rate and accuracy. The system demonstrated improved latency and lower energy consumption. |
| explicit-model-measurements | accept | 测试数据公布 | 新型人工智能模型的准确率为92%。该系统的推理延迟为15毫秒，功耗比此前方案低三成。 |
| explicit-chip-measurements | accept | 芯片测试结果公布 | 新型量子芯片的误差率为0.1%。其工作温度为二十毫开尔文，持续运行时间为十小时。 |
| paragraph-subject-reset | reject | 城市合作工作取得进展 | 团队发布人工智能模型。\n其旅游服务覆盖多个地区并带动年度客流增长，双方随后讨论经贸合作与文化演出安排。测试结果显示港口运输效率提高，代表肯定合作成果并提出扩大展览规模。 |
| economic-detail-continuation | reject | 经贸论坛公布年度合作成果 | 会议提出人工智能合作。其效率在通关便利化方面提高。结果显示贸易额增长三成。代表协商文化交流与旅游合作。 |
| genuine-education-neutral-title | accept | 试点方案公布 | 试点开设人工智能教育课程，教师采用科学实验教学方法。学生开展探究并记录测量结果，课程明确实验安全和课堂实践要求。 |

## Additional cross-layer review requirements

- Run the cases under literal v4 explicitly; acquisition/listing defaults remain literal v3.
- Compare exact historical v2/v3 serialized outputs and .6–.11 snapshots, fingerprints, scores,
  explanations and ordering against the deployed commit, not a newly generated expected answer.
- Under .12, taxonomy/category labels cannot authenticate subject. The same stored content keeps
  historical projection behavior under .11. Government/Ministry metadata cannot rescue an
  unqualified subject, even with maximal product/source score or ordinary broad-pool admission.
- Preserve the existing profile/slot/copy/rerank identities and test .11 versus .12 immutable
  enqueue conflicts against real PostgreSQL, including a previously owned/expired slot.

## Review state

Initial authored matrix recorded before product handoff. A case failure is evidence for a focused
review, not permission to weaken an existing hard veto, change source policy or add a sample-only
exception. Final observed results and any adjudicated refinements are recorded separately below.

- Initial 20-case execution matched 19 expected candidacy outcomes. The dedicated international AI
  governance policy was wrongly rejected because its continued technical predicate did not repeat
  the full topic or start with a recognized pronoun. The implementation owner is fixing bounded
  predicate/subject continuity, not exempting a speaker, country or source.
- Independent repository review found a separate integration risk: inserting a newline between
  every governed fact resets paragraph continuity, although measurements/pronouns refer to the
  same technical summary. Require a real PostgreSQL projection regression rather than proving
  only an artificially concatenated domain body.
- Main review added explicit noun/action-overlap cases: `计算` within `量子计算` and `回收` within
  `可回收火箭` are not independent predicates. A plain list must not authenticate subject merely
  by substring overlap. These extend the matrix to 22 cases.
- After those fixes, all 22 cases matched. Two additional measurement-only results extend the
  matrix to 24: a technical subject plus explicitly quantified accuracy/error/latency does not
  need a separate announcement/development verb. Both initially failed despite the new spec's
  meaningful-supported-detail contract; sent to the implementation owner before handoff.
