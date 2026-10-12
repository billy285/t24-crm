import type { CompactFinanceColumn } from './CompactFinanceTable';

// Original cells stay intact in the detail drawer; displayed values are never recalculated.
export const CRM_COMMAND_TABLES = {
  "salesPerformance": {
    "label": "销售执行表现",
    "columns": [
      {
        "label": "销售",
        "indexes": [
          0
        ],
        "width": 24,
        "summaryMode": "first"
      },
      {
        "label": "综合分",
        "indexes": [
          1
        ],
        "width": 10
      },
      {
        "label": "任务完成",
        "indexes": [
          2
        ],
        "width": 12,
        "align": "right"
      },
      {
        "label": "接通率",
        "indexes": [
          3
        ],
        "width": 12,
        "priority": 2,
        "align": "right"
      },
      {
        "label": "预约 / 转客户",
        "indexes": [
          5
        ],
        "width": 16,
        "priority": 2,
        "align": "right"
      },
      {
        "label": "逾期回访",
        "indexes": [
          6
        ],
        "width": 12,
        "align": "right"
      }
    ],
    "expectedHeaders": [
      "排名 / 销售",
      "综合分",
      "任务完成",
      "接通率",
      "意向率",
      "预约 / 转客户",
      "逾期回访",
      "下一步建议"
    ],
    "actionIndexes": []
  },
  "cashHistory": {
    "label": "现金月度快照",
    "columns": [
      {
        "label": "月份",
        "indexes": [
          0
        ],
        "width": 18
      },
      {
        "label": "状态",
        "indexes": [
          1
        ],
        "width": 15
      },
      {
        "label": "账户余额",
        "indexes": [
          2
        ],
        "width": 22,
        "priority": 2,
        "align": "right"
      },
      {
        "label": "受限资金",
        "indexes": [
          3
        ],
        "width": 22,
        "priority": 2,
        "align": "right"
      },
      {
        "label": "可用现金",
        "indexes": [
          4
        ],
        "width": 23,
        "align": "right"
      }
    ],
    "expectedHeaders": [
      "月份",
      "状态",
      "账户余额",
      "受限资金",
      "可用现金"
    ],
    "actionIndexes": []
  },
  "cashRestrictions": {
    "label": "受限资金",
    "columns": [
      {
        "label": "类别",
        "indexes": [
          0
        ],
        "width": 18
      },
      {
        "label": "说明",
        "indexes": [
          1
        ],
        "width": 34,
        "summaryMode": "first"
      },
      {
        "label": "原币金额",
        "indexes": [
          2
        ],
        "width": 24,
        "align": "right"
      },
      {
        "label": "折合人民币",
        "indexes": [
          3
        ],
        "width": 24,
        "priority": 2,
        "align": "right"
      }
    ],
    "expectedHeaders": [
      "类别",
      "说明",
      "原币金额",
      "折合人民币",
      "操作"
    ],
    "actionIndexes": [
      4
    ]
  },
  "businessProjects": {
    "label": "业务项目",
    "columns": [
      {
        "label": "客户",
        "indexes": [
          0
        ],
        "width": 28,
        "summaryMode": "first"
      },
      {
        "label": "业务项目",
        "indexes": [
          1
        ],
        "width": 17,
        "priority": 2
      },
      {
        "label": "套餐 / 项目",
        "indexes": [
          2
        ],
        "width": 25
      },
      {
        "label": "首次收款",
        "indexes": [
          4
        ],
        "width": 18,
        "priority": 3
      },
      {
        "label": "状态",
        "indexes": [
          5
        ],
        "width": 16
      }
    ],
    "expectedHeaders": [
      "客户",
      "业务项目",
      "套餐/项目名称",
      "行业/负责人",
      "首次有效收款",
      "状态",
      "收费",
      "操作"
    ],
    "actionIndexes": [
      7
    ]
  },
  "teamCapacity": {
    "label": "团队产能",
    "columns": [
      {
        "label": "员工",
        "indexes": [
          0
        ],
        "width": 24,
        "summaryMode": "first"
      },
      {
        "label": "在管项目",
        "indexes": [
          1
        ],
        "width": 18
      },
      {
        "label": "容量使用",
        "indexes": [
          2
        ],
        "width": 18,
        "summaryMode": "last",
        "priority": 2
      },
      {
        "label": "协作任务",
        "indexes": [
          3
        ],
        "width": 18,
        "summaryMode": "first",
        "priority": 2
      },
      {
        "label": "判断",
        "indexes": [
          5
        ],
        "width": 22
      }
    ],
    "expectedHeaders": [
      "员工",
      "在管项目",
      "容量使用",
      "协作任务",
      "交付任务",
      "判断"
    ],
    "actionIndexes": []
  },
  "unitEconomics": {
    "label": "项目效益",
    "columns": [
      {
        "label": "客户 / 项目",
        "indexes": [
          0
        ],
        "width": 29,
        "summaryMode": "first"
      },
      {
        "label": "业务线",
        "indexes": [
          1
        ],
        "width": 14,
        "priority": 2
      },
      {
        "label": "服务收入",
        "indexes": [
          2
        ],
        "width": 18,
        "align": "right"
      },
      {
        "label": "成本及分润",
        "indexes": [
          5
        ],
        "width": 18,
        "priority": 2,
        "align": "right"
      },
      {
        "label": "贡献利润",
        "indexes": [
          6
        ],
        "width": 18,
        "summaryMode": "first",
        "align": "right"
      },
      {
        "label": "可信度",
        "indexes": [
          7
        ],
        "width": 16,
        "priority": 3,
        "align": "right"
      }
    ],
    "expectedHeaders": [
      "客户/项目",
      "业务线",
      "服务收入",
      "投流差价",
      "退款及手续费",
      "成本及分润",
      "贡献利润",
      "可信度"
    ],
    "actionIndexes": []
  },
  "formalProfit": {
    "label": "公司人民币经营净利润",
    "columns": [
      {
        "label": "月份",
        "indexes": [
          0
        ],
        "width": 18,
        "summaryMode": "first"
      },
      {
        "label": "服务期收入 · USD",
        "indexes": [
          1
        ],
        "width": 21,
        "summaryMode": "first"
      },
      {
        "label": "实际收款 · USD",
        "indexes": [
          2
        ],
        "width": 21,
        "summaryMode": "first",
        "priority": 2,
        "align": "right"
      },
      {
        "label": "经营利润 · CNY",
        "indexes": [
          8
        ],
        "width": 22,
        "align": "right"
      },
      {
        "label": "现金口径 · CNY",
        "indexes": [
          9
        ],
        "width": 22,
        "priority": 2,
        "align": "right"
      }
    ],
    "expectedHeaders": [
      "月份",
      "服务期收入",
      "实际收款",
      "投流差价",
      "退款/手续费",
      "客户成本/分润",
      "公司支出",
      "月均汇率",
      "经营利润",
      "现金口径",
      "月结"
    ],
    "actionIndexes": [
      7,
      10
    ]
  }
} satisfies Record<string, {label: string; columns: CompactFinanceColumn[]; expectedHeaders: string[]; actionIndexes: number[]}>;
