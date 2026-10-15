# 来源与读取范围

来源为《Next-day manufacture of a novel anti-CD19 CAR-T therapy for B-cell acute lymphoblastic leukemia: first-in-human clinical study》，Blood Cancer Journal 12:104（2022），DOI：10.1038/s41408-022-00694-6，PMCID：PMC9262977，临床登记 NCT03825718。

已读取所给 PDF 全部 9 页，包括方法、结果、讨论、图 1–4、表 1–2及图表说明；目视检查含图表的页面，并从 PDF 提取原始高分辨率图像。另读取同篇文章官方 XML 以检查表格列、上标及源标识，读取官方补充 DOCX 的完整方法、补图 S1–S11、补表 S1–S6；实际查看 DOCX 内嵌图像，TIFF 转为 PNG 后查看。没有查阅先前提取结果，也没有从已知 FMC63 序列补填本篇未报告的序列。

补充材料于 2026-10-14 恢复。先检查本地材料；沙箱内网络解析失败，获准联网后按技能读取 PMC 云服务列表和元数据。元数据的 PMCID、标题、DOI、版本 1 均与来源一致。Europe PMC 补充文件接口超时，但补充材料随后已从 PMC 云服务成功恢复，因此没有未恢复的相关文件。

- 版本列表：https://pmc-oa-opendata.s3.amazonaws.com/?list-type=2&prefix=PMC9262977.&delimiter=/
- 版本元数据：https://pmc-oa-opendata.s3.amazonaws.com/PMC9262977.1/PMC9262977.1.json
- 官方 XML：https://www.ebi.ac.uk/europepmc/webservices/rest/PMC9262977/fullTextXML
- 图 1：https://pmc-oa-opendata.s3.amazonaws.com/PMC9262977.1/41408_2022_694_Fig1_HTML.jpg
- 图 2：https://pmc-oa-opendata.s3.amazonaws.com/PMC9262977.1/41408_2022_694_Fig2_HTML.jpg
- 图 3：https://pmc-oa-opendata.s3.amazonaws.com/PMC9262977.1/41408_2022_694_Fig3_HTML.jpg
- 图 4：https://pmc-oa-opendata.s3.amazonaws.com/PMC9262977.1/41408_2022_694_Fig4_HTML.jpg
- 补充 DOCX：https://pmc-oa-opendata.s3.amazonaws.com/PMC9262977.1/41408_2022_694_MOESM1_ESM.docx
- 尝试后超时的接口：https://www.ebi.ac.uk/europepmc/webservices/rest/PMC9262977/supplementaryFiles

四张云端主图和补充 DOCX 均下载成功，五项 MD5 与元数据一致；来源版本、下载地址、文件及校验明细保存在私有 `scratch/`。定量读图采用 PDF 图 1原始 1975×1040 图像和补充图原始 1280×720 图像，未用低分辨率云端缩图替代高分辨率图像。

# 实体、归属与数值处理

以下行号均为最终 `data.jsonl` 的一基物理行号。

- `binder` 第 1 行：补充方法明确使用鼠源 FMC63 anti-CD19 scFv，记录靶点及非人源属性；未报告的 VH/VL、linker 和全长序列留空。
- `car` 第 2 行 `modules`：依据补充方法和 S1A，按顺序记录 FLAG/Beacon 标签（DYKDDDDK）、CD8a hinge、CD8a transmembrane、CD28 costimulation、CD3ζ signaling。标签长度 8 来自所给序列直接计数。CD8a 信号肽无活动模块枚举，不以 linker 等其他类型替代。
- `manufacturing` 第 3–4 行：F/C 为两种实际不同工艺，按方法及 S1B 分开；供者、患者、批次、剂量及测量结果不另建工艺。两者共享来源明确的 FMC63 结合域和 CD19 CAR 骨架，分别建立 `abc_combination_db1` 第 5–6 行。F 的最远阶段为明确报告的 I 期，C 为研究级动物实验。
- 第 3–4 行 `selection_steps` 保留单采设备和 Dynabeads 分选顺序；Dynabeads 已在分选试剂中记录，不在顶层试剂中重复。培养基与 IL-2 分别保留在 `culture_system`、`cytokine_combination`，未报告浓度不补填。生理盐水和冻存液仅归入明确报告这些操作的 F 工艺。分析抗体、染料、检测试剂不进入制造试剂；相关流式条件保留在对应 `evidence.applicable_scenario`。
- S1B 的 F 总生产流程为 22–36 小时，C 总流程为 2–6 周；总流程时间不等于培养时长。第 3 行 `culture_duration` 留空；第 4 行只存明确标为扩增培养的 1–5 周，不挑选某个未报告的固定培养天数。图示转导阶段时长也不直接当作细胞与病毒接触时长。
- 激活与转导时序在正文、S1B 和共同图例中不完全一致，第 3–4 行 `transduction_transfection_conditions` 留空并分别记异常。未报告 MOI、冻存配方、DMSO 比例、起始活率和起始 CD4:CD8 比例，不补推。
- `evidence` 第 12–14 行保留记忆表型的原始门控和分母。F 组 Tem 的正文为 7.84% ± 3.79%，S2C 为 Mean 7.84、SD 3.49，分行保留并记冲突；没有把它们当成两个独立重复实验。正文未说明该 ± 类型，保留 `plus_minus_unspecified`；S2C 明示的 SD 使用相应类型。
- 第 15–16 行按图 1C 保留 CD8 CAR-T 内 PD-1/LAG3/Tim3 三阳性表型，不把单个耗竭标志物当作功能状态。未刺激健康供者表型单列第 11 行，不当成制造前投料质量。
- 第 41 行中原文所谓 transduction efficiency 实际为流式 CAR+/CD3+，因此存入 `manufacturing.car_positive_ratio`，不存入 `manufacturing.transduction_efficiency`。同一临床制品实验的 CAR 阳性与记忆表型合并在同一行；均值写入 `value`，同时报告的队列范围完整保存在 `raw`，不分配给个别患者。
- 第 41 行 `manufacturing.tscm_ratio` 保留正文 Tscm 23.3% 的报告，并在 `raw` 保留 S5B 对相同门控使用 T Naïve 的名称，异常日志记录这一命名不一致；不追加未报告的 Tscm 鉴定标志物。
- 第 21–32 行按靶细胞、F/C 组和实际 E:T 分开，均为 6 小时荧光素酶杀伤实验。第 33–36 行将同一共培养条件下的 IFN-γ 和 IL-2 放在同一条证据；S2D 的 CBA 图例与补充方法 Ella ELISA 描述均保留，未选定其中一种为确定平台。
- 第 17–20、44 行保留 RTCA 的靶细胞、E:T 和方法。归一化 cell index 和 CIT50 不是杀伤率，CIT50 也不是预先规定的共培养时长；相应 `killing_rate`、`duration` 留空，不换算出百分比。
- 第 37–40 行为 n=6/组的动物外周血扩增实验，保留 F/C、高低剂量、Raji-luc 负荷和取样时点；没有与 n=3/组的肿瘤成像实验合并。正文“2–6 folds greater”是跨组概述，不分配为某一个剂量组的精确倍数。
- 第 45 行合并同一临床队列的 qPCR 与流式峰值，保留原始统计口径、剂量组和处理条件。qPCR copies/µg gDNA 是临床细胞动力学，不是制造 VCN。
- 第 46–85 行按补表 S5 原顺序保留 13 名患者的 40 个 PB 取样记录，`car.expansion_capacity` 存原文逐时点细胞数量/比例；是细胞扩增随访的测量，不自行计算扩增倍数。CSF/PB 斜线两侧严格区分，未把 CSF 数值归入 PB。患者身份、疾病、剂量和桥接条件由同篇表 1、S3 对齐，原始标识和原文基因名不改写。百分比为 0 与计数 NA 分别处理，不由前者推断细胞绝对数为零。
- 补表 S1 是放行标准，不能作为实测活率、VCN、CD3 阳性率、内毒素、IFN-γ 或无菌/支原体结果。制品放行不被改写成逐批检测结果。患者血清/CSF 细胞因子不进入制造功能试验字段；day 101 单例仍检出不等于中位持久性，`car.persistence` 留空。

# 覆盖复查

覆盖状态同时考虑活动字段能否容纳结果；“部分覆盖”不代表未读取相应来源。

| 实验、工艺或实体及位置 | 状态 | 最终存储或缺口 |
|---|---|---|
| CD19 CAR 构型和 F/C 制造流程，正文 1–2 页、S1、补充方法 | 部分覆盖 | `binder` 第 1 行；`car` 第 2 行 `modules`；`manufacturing` 第 3–4 行；组合第 5–6 行；`evidence` 第 7–8 行。分选、递送、培养、试剂及 F 冻存设备已记录。运输 30 h/18–25°C、完整流程时间、后处理操作时长及独立信号肽无对应活动字段；激活时序歧义记日志。 |
| 体外抗原刺激增殖，正文 2 页、1A、补充方法 | 部分覆盖 | `evidence` 第 9–10 行 `car.expansion_capacity`，含 6 例、K562-CD19、每 3 天刺激、d17 均值±SD、计数方法和分母。d9/d13 仅图示，扩增字段为字符串，未伪造精确数字或测量对象。 |
| 细胞周期/凋亡基因表达，正文 2 页、S2A、S2 表、补充方法 | 未存储 | 已读取：780 基因面板、2:1 K562-CD19 刺激、d6 分选、Nanostring/nSolver 和基因集；活动字段没有该表达评分或基因集的存储位置。 |
| 未刺激健康供者表型，正文 2 页 | 已覆盖 | `evidence` 第 11 行 `manufacturing.tscm_ratio`：3 名健康供者、45.7% ± 2.2%、门控与未刺激条件；± 类型未说明。 |
| 刺激后记忆表型，正文 2 页、1B、S2B–C | 部分覆盖 | `evidence` 第 12–14 行 `manufacturing.tscm_ratio/tcm_ratio/tem_ratio`，含 d9、门控、分母、统计量和冲突。S2B 两张无组标签的代表性图不推断归属；S2C 双阴性亚群未明确称为 Teff，不强行映射。 |
| 刺激后耗竭表型，正文 2 页、1C | 已覆盖 | `evidence` 第 15–16 行 `manufacturing.exhaustion_phenotype`，保留 F/C、CD8 门控、三阳性组合、数值及比较。 |
| RTCA 杀伤方法，1D、补充方法 | 部分覆盖 | `evidence` 第 17–20 行 `manufacturing.killing_activity`，保留 HeLa-CD19/HeLa、F/C、1:1、5000 靶细胞/孔、96 孔板、次日加效应细胞及不加 IL-2 的条件。cell index 无对应结果字段。 |
| 白血病细胞杀伤，1E–F、补充方法 | 已覆盖 | `evidence` 第 21–32 行 `manufacturing.killing_activity`：Nalm6-Luc/Raji-Luc、F/C、5:1/1:1/0.2:1、6 h、One-Glo、12 项图像估算杀伤率。 |
| 体外上清细胞因子，S2D、补充方法 | 已覆盖 | `evidence` 第 33–36 行 `manufacturing.ifn_gamma_release/cytokine_release`：F/C、HeLa-CD19/HeLa、IFN-γ 和 IL-2 共 8 项图像估算；平台冲突保留。 |
| Raji 异种移植及血液扩增，正文 2 页、2A–B、补充方法 | 部分覆盖 | `evidence` 第 37–40 行 `car.expansion_capacity` 保留 n=6、5×10^5/2×10^6 CAR-T、3×10^5 Raji-luc、i.v. 和各取样日。n=3 的肿瘤成像、d20 清瘤/复发无活动结果字段；不把 BLI 当作杀伤百分比。 |
| Nalm6 骨髓归巢，正文 2–4 页、2C–D、补充方法 | 未存储 | 已检查 1×10^6 Nalm6、200 μL PBS、2×10^6 CAR-T、CTX 20 mg/kg、d10、n=3、BM/PB 标注；归巢细胞数无活动字段。图示 CTX 在 CAR-T 前一天，补充方法写在后一天，来源歧义未转换成虚构制造条件。 |
| CXCR4 及迁移，正文 4 页、S3、补充方法 | 未存储 | 已检查 CD4/CD8 CAR+ 亚群、CXCR4；24 孔/5 μm、5×10^4 细胞/0.1 mL、mSDF-1α 0/25/100 ng/mL、4 h、37°C、20× 及 ImageJ。无相应迁移或受体表达字段。 |
| 临床制造及功能，正文 4 页、S5、S1 表 | 部分覆盖 | `evidence` 第 41 行阳性率及表型，第 42–43 行 IFN-γ，第 44 行 RTCA 条件。CD4/CD8 成品构成、CIT50 和放行阈值无相应实测字段；阴性靶细胞以原文 molt-4/Hela 合并组保留，不拆成两种独立实验。 |
| 临床入组、剂量及预处理，正文 2、4–5 页、表 1、S4、S3 表 | 部分覆盖 | `abc_combination_db1` 第 5 行阶段；`evidence` 第 45–85 行 `applicable_scenario`：四剂量组、实际患者剂量、疾病、桥接及计划 FC 条件。未为每个患者另建工艺；其他临床特征没有单独指标列。 |
| 临床安全性及血清细胞因子，正文 4–6 页、表 1–2、S6–10、S4 表 | 未存储 | 已读取 CRS/ICANS 分级、时间、处理和细胞因子曲线/热图；无活动临床毒性或系统性细胞因子字段。表 1 F07 的 CRS 4 与正文“无 4 级”不一致、年龄边界等只说明来源局限，不借制造字段存储，也不据此改写原表。 |
| 临床细胞动力学，正文 4、7 页、图 3、S5 表 PB | 已覆盖 | `evidence` 第 45 行 `car.expansion_capacity` 为汇总 qPCR/FCM 峰值；第 46–85 行同字段为可逐项核对的 40 个原始 PB 时点，按来源顺序排列。图 3 重叠曲线没有逐患者精确值，不补推。 |
| 临床疗效及移植随访，正文 4、7 页、表 1、图 4 | 未存储 | 已读取 14/28 天 CR/CRi/MRD、移植和长期随访；无活动临床疗效、缓解持续时间或生存字段，不以 CAR 持久性替代缓解持续时间。 |
| CSF 与 PB 关联，正文 4、6 页、S5 表、S11 | 部分覆盖 | S5 表 PB 部分按上条存于 `evidence` 第 46–85 行。CSF 细胞比例、计数、细胞因子及单例 day 101 检出没有相应活动字段；未混入制造 CAR 阳性率或体外分泌。 |

正常 T 细胞、培养基、靶细胞单独培养和未明确构成的 Control 组保留为对应实验的对照背景，不虚构缺失的 CAR 或制造方案。讨论中另引的 4-1BB/双靶产品属于其他研究，不新建本篇实验实体。

# 图像定量依据

共 22 项估算，均存为 `image_estimated_range`；`value` 和 `error` 为 null。范围表示像素定位与标定精度，不是 SD、SEM、供者范围或置信区间。条形图读取实心柱顶，S5C 读取组均值横线，未把误差线端点或个别供者极值当作组结果。近零柱保留含零的读图区间，不报告“未检出”或精确零。

像素坐标以原始图左上角为原点，x 向右、y 向下；下表坐标均为未裁剪原图坐标。检查时使用的放大裁剪仅帮助观察，不增加有效分辨率。图 1：`scratch/page3-image0.view.png`，1975×1040，来自所给 PDF 第 3 页嵌入图，CMYK 转 RGB 不改变尺寸；S2D：`scratch/image2.jpeg`，1280×720；S5C：`scratch/image5.jpeg`，1280×720，两者均为所恢复补充 DOCX 内的原始图片。

所有相关轴在使用区段内为线性，映射为 `v(y)=v0+(v1−v0)×(y−y0)/(y1−y0)`。图 1E 两刻度为 y=909→0%、y=664→100%；图 1F 为 y=903→0%、y=655→100%。S2D 为断轴：高段 y=495→2000、y=436→8000 pg/ml；低段 y=594→0、y=516→500 pg/ml，分别标定，未跨断口插值。S5C 为 y=550→0、y=411→80 ng/mL。像素区间包含柱顶/均值线厚度、JPEG 边缘和刻度定位的约 1–2 像素不确定性，再按表中步长向外取整；低端受非负读数域约束。

| 输出表及物理行、字段 | 图、组别与条件 | x 位置；结果 y 区间 | 标定刻度 y→数值 | 向外取整步长 | 最终范围 |
|---|---|---|---|---|---|
| `evidence` 第 21 行 `manufacturing.killing_activity.killing_rate` | Fig. 1E；F-CAR-T；Nalm6-Luc; E:T=5:1; 6 h; target cell killing efficacy | 850；695–700 | 909→0；664→100 | 1 | 85–88 % |
| `evidence` 第 22 行 `manufacturing.killing_activity.killing_rate` | Fig. 1E；C-CAR-T；Nalm6-Luc; E:T=5:1; 6 h; target cell killing efficacy | 911；702–707 | 909→0；664→100 | 1 | 82–85 % |
| `evidence` 第 23 行 `manufacturing.killing_activity.killing_rate` | Fig. 1E；F-CAR-T；Nalm6-Luc; E:T=1:1; 6 h; target cell killing efficacy | 1008；778–783 | 909→0；664→100 | 1 | 51–54 % |
| `evidence` 第 24 行 `manufacturing.killing_activity.killing_rate` | Fig. 1E；C-CAR-T；Nalm6-Luc; E:T=1:1; 6 h; target cell killing efficacy | 1070；812–817 | 909→0；664→100 | 1 | 37–40 % |
| `evidence` 第 25 行 `manufacturing.killing_activity.killing_rate` | Fig. 1E；F-CAR-T；Nalm6-Luc; E:T=0.2:1; 6 h; target cell killing efficacy | 1166；876–881 | 909→0；664→100 | 1 | 11–14 % |
| `evidence` 第 26 行 `manufacturing.killing_activity.killing_rate` | Fig. 1E；C-CAR-T；Nalm6-Luc; E:T=0.2:1; 6 h; target cell killing efficacy | 1227；890–895 | 909→0；664→100 | 1 | 5–8 % |
| `evidence` 第 27 行 `manufacturing.killing_activity.killing_rate` | Fig. 1F；F-CAR-T；Raji-Luc; E:T=5:1; 6 h; target cell killing efficacy | 1485；701–706 | 903→0；655→100 | 1 | 79–82 % |
| `evidence` 第 28 行 `manufacturing.killing_activity.killing_rate` | Fig. 1F；C-CAR-T；Raji-Luc; E:T=5:1; 6 h; target cell killing efficacy | 1547；702–707 | 903→0；655→100 | 1 | 79–82 % |
| `evidence` 第 29 行 `manufacturing.killing_activity.killing_rate` | Fig. 1F；F-CAR-T；Raji-Luc; E:T=1:1; 6 h; target cell killing efficacy | 1647；832–837 | 903→0；655→100 | 1 | 26–29 % |
| `evidence` 第 30 行 `manufacturing.killing_activity.killing_rate` | Fig. 1F；C-CAR-T；Raji-Luc; E:T=1:1; 6 h; target cell killing efficacy | 1708；844–849 | 903→0；655→100 | 1 | 21–24 % |
| `evidence` 第 31 行 `manufacturing.killing_activity.killing_rate` | Fig. 1F；F-CAR-T；Raji-Luc; E:T=0.2:1; 6 h; target cell killing efficacy | 1808；879–884 | 903→0；655→100 | 1 | 7–10 % |
| `evidence` 第 32 行 `manufacturing.killing_activity.killing_rate` | Fig. 1F；C-CAR-T；Raji-Luc; E:T=0.2:1; 6 h; target cell killing efficacy | 1870；891–896 | 903→0；655→100 | 1 | 2–5 % |
| `evidence` 第 33 行 `manufacturing.ifn_gamma_release` | Fig. S2D；F-CAR-T；HeLa-CD19; supernatant IFN-γ | 853；465–470 | 495→2000；436→8000 | 100 | 4500–5100 pg/ml |
| `evidence` 第 33 行 `manufacturing.cytokine_release[0].concentration` | Fig. S2D；F-CAR-T；HeLa-CD19; supernatant IL-2 | 902；439–444 | 495→2000；436→8000 | 100 | 7100–7700 pg/ml |
| `evidence` 第 34 行 `manufacturing.ifn_gamma_release` | Fig. S2D；C-CAR-T；HeLa-CD19; supernatant IFN-γ | 864；449–454 | 495→2000；436→8000 | 100 | 6100–6700 pg/ml |
| `evidence` 第 34 行 `manufacturing.cytokine_release[0].concentration` | Fig. S2D；C-CAR-T；HeLa-CD19; supernatant IL-2 | 913；437–442 | 495→2000；436→8000 | 100 | 7300–7900 pg/ml |
| `evidence` 第 35 行 `manufacturing.ifn_gamma_release` | Fig. S2D；F-CAR-T；HeLa; supernatant IFN-γ | 999；591–594 | 594→0；516→500 | 10 | 0–20 pg/ml |
| `evidence` 第 35 行 `manufacturing.cytokine_release[0].concentration` | Fig. S2D；F-CAR-T；HeLa; supernatant IL-2 | 1047；590–594 | 594→0；516→500 | 10 | 0–30 pg/ml |
| `evidence` 第 36 行 `manufacturing.ifn_gamma_release` | Fig. S2D；C-CAR-T；HeLa; supernatant IFN-γ | 1009；587–591 | 594→0；516→500 | 10 | 10–50 pg/ml |
| `evidence` 第 36 行 `manufacturing.cytokine_release[0].concentration` | Fig. S2D；C-CAR-T；HeLa; supernatant IL-2 | 1058；592–594 | 594→0；516→500 | 10 | 0–20 pg/ml |
| `evidence` 第 42 行 `manufacturing.ifn_gamma_release` | Fig. S5C；F-CAR-T；CD19+; E:T=1:1; mean supernatant IFN-γ | 380；494–498 | 550→0；411→80 | 1 | 29–33 ng/mL |
| `evidence` 第 43 行 `manufacturing.ifn_gamma_release` | Fig. S5C；F-CAR-T；CD19−; E:T=1:1; mean supernatant IFN-γ | 457；547–551 | 550→0；411→80 | 1 | 0–2 ng/mL |

各项范围已回看原图：图 1E 的 F/C 差异、图 1F 低 E:T 小柱及 S2D 的近零阴性组均与估算区间对应。未从 cell index、BLI、CSF 检出或未定义单位的图像另行推导生物学指标。

# 异常与完成检查

`error_log.jsonl` 含 9 项当前运行异常：F/C 激活至转导间隔各 1 项；Tem ±/SD 冲突 1 项；S2B 代表图组别不明 1 项；临床 Tscm/T Naïve 命名冲突 1 项；S2D 检测平台冲突按受影响的四条证据各 1 项。所有异常均带具体简体中文 `message`，机器分类和动作码保持技能要求。来源仍有上述歧义，相关字段留空或保留相互冲突的来源报告，未静默纠正。

本次为单代理完整提取和本人回源核对，未启用子代理，没有独立多代理交叉核对。已在草稿形成后重新核对方法、结果、主图、补图、表头/脚注与工艺清单，完成覆盖复查和语义复查；所有清单条目均有最终处置，来源可恢复而且活动字段能容纳的读数已写入。

最终候选通过仓库 `cart_db.agent_output.prepare_output` 的只读验证，返回值未写回。另核对所有活动字段、类型、枚举、正则模式、measurement 数值成员与类型匹配、比例范围、非负读数、序列长度、主键唯一性、外键存在且先于引用、组合与三实体外键一致、行顺序和异常结构。全文临床 qPCR 未混作制造 VCN，流式 CAR 阳性未混作另一口径的转导效率，放行门槛未当作结果。64 个 measurement 中有 22 项图像估算。

本目录根部仅有三个可发布文件：`data.jsonl`、`reasoning.md`、`error_log.jsonl`；下载、图像、清单、脚本和校验明细均在独立 `scratch/`。未修改共享代码、Schema 或其他文档输出。最终 UUID 分配、可空字段补全/排序和单位归一化由 runner 执行；当前文件保留来源单位和数值，尚未实际发布或写回归一化结果。

行数：`binder` 1，`car` 1，`manufacturing` 2，`abc_combination_db1` 2，`evidence` 79；合计 85 行。异常日志 9 行。
