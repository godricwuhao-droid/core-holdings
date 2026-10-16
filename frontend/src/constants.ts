/**
 * 前端静态配置 / 展示数据（非业务数据，不随请求变化）
 *
 * - CATEGORY_UNITS：分类单位（板块 → 类型 → 计量单位）
 * - FEATURE_CATALOGS：功能清单（软件/平台软件类产品的结构化模块树）
 *
 * 业务数据（资产/项目/出库/流水/日志/交付物）由后端 + db 镜像提供，见 @/api。
 */
import type { CategoryUnit, FeatureModule } from '@/types'

export const CATEGORY_UNITS: CategoryUnit[] = [
  { board: 'embodied', type: '机器人', unit: '套 / 台', note: '整机交付，可选序列号出库' },
  { board: 'embodied', type: '数采设备', unit: '套', note: '数采软件及设备接入' },
  { board: 'embodied', type: '平台软件', unit: '套', note: '管理平台类' },
  { board: 'satellite', type: '卫星Token', unit: '颗（Token 额度）', note: '按 Token 额度与有效期售卖' },
  { board: 'satellite', type: '卫星数据', unit: '轨 / 期 / 条', note: '默认可重复售卖，不扣减库存' },
  { board: 'satellite', type: '遥感数据', unit: '份（可售明细）', note: '父资产容器，按 省/精度/月份 维护明细售卖' },
  { board: 'software', type: '软件', unit: '套', note: '永久 / 年限 / 并发 / 账号许可' },
  { board: 'hardware', type: '硬件集群', unit: '集群 / 台', note: '整机柜或单台交付' },
  { board: 'compute', type: '算力服务器', unit: '台（服务期）', note: '按服务期售卖，建设中' },
]

/** 中国 31 省级行政区（ADR-011 遥感数据可售明细「省份」下拉内置常量） */
export const PROVINCES: string[] = [
  '北京市', '天津市', '河北省', '山西省', '内蒙古自治区',
  '辽宁省', '吉林省', '黑龙江省',
  '上海市', '江苏省', '浙江省', '安徽省', '福建省', '江西省', '山东省',
  '河南省', '湖北省', '湖南省', '广东省', '广西壮族自治区', '海南省',
  '重庆市', '四川省', '贵州省', '云南省', '西藏自治区',
  '陕西省', '甘肃省', '青海省', '宁夏回族自治区', '新疆维吾尔自治区',
]

export const FEATURE_CATALOGS: Record<string, FeatureModule[]> = {
  软件: [
    {
      name: '核心引擎平台',
      subs: [
        {
          name: '大模型能力中枢',
          capabilities: [
            {
              name: '场景化意图理解',
              desc: '理解用户复杂、多变表达中的真实意图，不局限于固定关键词。',
              value: '大模型处理复杂语义，小模型保障高并发、低延迟的稳定交互。',
            },
            {
              name: '动态话术生成',
              desc: '按业务场景与客户画像实时生成应答话术，支持多轮改写。',
              value: '话术质量对齐人工坐席水平，减少脚本维护成本。',
            },
            {
              name: '多轮上下文管理',
              desc: '维护会话级上下文与指代消解，支持长对话不丢失关键信息。',
              value: '减少客户重复表述，提升一次解决率。',
            },
          ],
        },
        {
          name: '小模型能力引擎',
          capabilities: [
            {
              name: '高并发低延迟路由',
              desc: '轻量模型承担意图分类与分流，毫秒级返回。',
              value: '高并发下成本可控，核心链路响应稳定。',
            },
            {
              name: '敏感词与合规拦截',
              desc: '本地化小模型实时拦截违规和敏感表述。',
              value: '合规审查前置，降低业务风险。',
            },
          ],
        },
      ],
    },
    {
      name: '业务编排与知识服务',
      subs: [
        {
          name: '业务流程编排',
          capabilities: [
            {
              name: '可视化流程画布',
              desc: '拖拽式编排业务分支、条件与转人工策略。',
              value: '业务变更无需发版，配置即时生效。',
            },
            {
              name: '人机协同转接',
              desc: '复杂场景无缝转接人工，并同步完整会话上下文。',
              value: '人工介入成本降低，服务体验连续。',
            },
          ],
        },
        {
          name: '知识库服务',
          capabilities: [
            {
              name: '多源知识接入',
              desc: '支持文档、表格与接口数据统一接入并自动切分。',
              value: '知识更新一处生效，答案口径统一。',
            },
            {
              name: '引用溯源',
              desc: '每条回答附知识来源与置信度标记。',
              value: '回答可解释、可审计，便于质检复盘。',
            },
          ],
        },
      ],
    },
  ],
  平台软件: [
    {
      name: '采集管理平台',
      subs: [
        {
          name: '设备接入管理',
          capabilities: [
            {
              name: '多型号设备纳管',
              desc: '统一管理不同厂商采集设备，自动识别与在线状态监控。',
              value: '设备上线时间从天级缩短到分钟级。',
            },
            {
              name: '采集任务调度',
              desc: '按场景批量下发采集任务，支持优先级与断点续采。',
              value: '批量作业效率提升，任务可追溯。',
            },
          ],
        },
      ],
    },
    {
      name: '数据处理服务',
      subs: [
        {
          name: '数据标注工具',
          capabilities: [
            {
              name: '可视化标注',
              desc: '支持点云、图像与轨迹多模态标注，模板可复用。',
              value: '标注一致性提升，返工率下降。',
            },
            {
              name: '质检与抽检',
              desc: '规则化质检 + 人工抽检，问题样本自动回流。',
              value: '数据质量可量化，交付更可靠。',
            },
          ],
        },
      ],
    },
  ],
}
