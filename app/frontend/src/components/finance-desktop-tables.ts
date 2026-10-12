import type { CompactFinanceColumn, CompactFinanceDetailGroup } from './CompactFinanceTable';

// Column positions and headers refer to the existing full ledger; no values are recalculated.
export const FINANCE_DESKTOP_TABLES = {
  "customer_profit": {
    "label": "客户利润",
    "columns": [
      {
        "label": "客户",
        "indexes": [
          0
        ],
        "width": 26
      },
      {
        "label": "实收",
        "indexes": [
          1
        ],
        "width": 12,
        "align": "right"
      },
      {
        "label": "成本 / 费用",
        "indexes": [
          5,
          4
        ],
        "width": 16
      },
      {
        "label": "利润 / 利润率",
        "indexes": [
          6,
          8
        ],
        "width": 16
      },
      {
        "label": "预警 / 欠款",
        "indexes": [
          7,
          9
        ],
        "width": 14
      },
      {
        "label": "操作",
        "indexes": [
          10
        ],
        "width": 16
      }
    ],
    "detailGroups": [
      {
        "label": "收款结构",
        "indexes": [
          0,
          1,
          2,
          3
        ]
      },
      {
        "label": "成本与利润",
        "indexes": [
          4,
          5,
          6,
          8
        ]
      },
      {
        "label": "风险与欠款",
        "indexes": [
          7,
          9
        ]
      }
    ],
    "actionIndexes": [
      10
    ],
    "expectedHeaders": [
      "客户",
      "实收",
      "管理费",
      "投流",
      "扣点/手续费/佣金",
      "客户成本",
      "利润",
      "预警",
      "利润率",
      "欠款",
      "操作"
    ]
  },
  "receivables": {
    "label": "应收欠款",
    "columns": [
      {
        "label": "客户 / 产品",
        "indexes": [
          0,
          1
        ],
        "width": 28
      },
      {
        "label": "应收 / 实收",
        "indexes": [
          2,
          3
        ],
        "width": 16
      },
      {
        "label": "欠款",
        "indexes": [
          4
        ],
        "width": 16,
        "align": "right"
      },
      {
        "label": "逾期",
        "indexes": [
          5
        ],
        "width": 12
      },
      {
        "label": "负责人 / 跟进",
        "indexes": [
          6
        ],
        "width": 18
      },
      {
        "label": "日期",
        "indexes": [
          7
        ],
        "width": 14
      }
    ],
    "detailGroups": [
      {
        "label": "客户与跟进",
        "indexes": [
          0,
          1,
          6,
          7
        ]
      },
      {
        "label": "收款与欠款",
        "indexes": [
          2,
          3,
          4,
          5
        ]
      }
    ],
    "actionIndexes": [],
    "expectedHeaders": [
      "客户",
      "产品",
      "应收",
      "实收",
      "欠款",
      "欠款天数",
      "负责人 / 最近跟进",
      "日期"
    ]
  },
  "income": {
    "label": "收入管理",
    "columns": [
      {
        "label": "客户",
        "indexes": [
          0
        ],
        "width": 25
      },
      {
        "label": "收入项目",
        "indexes": [
          2,
          1
        ],
        "width": 22
      },
      {
        "label": "应收",
        "indexes": [
          3
        ],
        "width": 11,
        "align": "right"
      },
      {
        "label": "实收 / 欠款",
        "indexes": [
          4,
          9
        ],
        "width": 15
      },
      {
        "label": "日期 / 方式",
        "indexes": [
          12,
          11
        ],
        "width": 16
      },
      {
        "label": "操作",
        "indexes": [
          14
        ],
        "width": 13
      }
    ],
    "detailGroups": [
      {
        "label": "收款信息",
        "indexes": [
          0,
          1,
          2,
          3,
          4,
          9,
          12
        ]
      },
      {
        "label": "收入拆分与费用",
        "indexes": [
          5,
          6,
          7,
          8
        ]
      },
      {
        "label": "支付与凭证",
        "indexes": [
          10,
          11,
          13
        ]
      }
    ],
    "actionIndexes": [
      14
    ],
    "expectedHeaders": [
      "客户",
      "收入类型",
      "产品",
      "应收",
      "实收",
      "管理费",
      "投流充值",
      "Stripe手续费",
      "净入账",
      "欠款",
      "模式",
      "方式",
      "日期",
      "发票",
      "操作"
    ]
  },
  "refunds": {
    "label": "退款记录",
    "columns": [
      {
        "label": "客户",
        "indexes": [
          1
        ],
        "width": 32
      },
      {
        "label": "退款日期",
        "indexes": [
          0
        ],
        "width": 18
      },
      {
        "label": "退款金额",
        "indexes": [
          2
        ],
        "width": 20,
        "align": "right"
      },
      {
        "label": "状态",
        "indexes": [
          6
        ],
        "width": 18
      }
    ],
    "detailGroups": [
      {
        "label": "退款信息",
        "indexes": [
          0,
          1,
          2,
          6
        ]
      },
      {
        "label": "手续费与凭证",
        "indexes": [
          3,
          4,
          5
        ]
      }
    ],
    "actionIndexes": [],
    "expectedHeaders": [
      "退款日期",
      "客户",
      "退款金额",
      "手续费退回",
      "原因",
      "凭证",
      "状态"
    ]
  },
  "ad_funds": {
    "label": "投流月结",
    "columns": [
      {
        "label": "月份 / 客户",
        "indexes": [
          0
        ],
        "width": 26
      },
      {
        "label": "净充值",
        "indexes": [
          2
        ],
        "width": 14,
        "align": "right"
      },
      {
        "label": "广告实支",
        "indexes": [
          3
        ],
        "width": 14,
        "align": "right"
      },
      {
        "label": "确认差价",
        "indexes": [
          5
        ],
        "width": 14,
        "align": "right"
      },
      {
        "label": "结余 / 状态",
        "indexes": [
          6,
          7
        ],
        "width": 18
      },
      {
        "label": "操作",
        "indexes": [
          8
        ],
        "width": 14
      }
    ],
    "detailGroups": [
      {
        "label": "客户资金",
        "indexes": [
          0,
          1,
          2,
          4
        ]
      },
      {
        "label": "结算结果",
        "indexes": [
          3,
          5,
          6,
          7
        ]
      }
    ],
    "actionIndexes": [
      8
    ],
    "expectedHeaders": [
      "月份/客户",
      "期初自动结转",
      "本月净充值",
      "广告实支",
      "退客户",
      "确认差价",
      "结余",
      "状态",
      "操作"
    ]
  },
  "customer_expense": {
    "label": "客户支出",
    "columns": [
      {
        "label": "客户",
        "indexes": [
          0
        ],
        "width": 28
      },
      {
        "label": "费用类型",
        "indexes": [
          1
        ],
        "width": 20
      },
      {
        "label": "金额 / 币种",
        "indexes": [
          2,
          3
        ],
        "width": 20
      },
      {
        "label": "月份",
        "indexes": [
          4
        ],
        "width": 16
      },
      {
        "label": "操作",
        "indexes": [
          6
        ],
        "width": 16
      }
    ],
    "detailGroups": [
      {
        "label": "费用信息",
        "indexes": [
          0,
          1,
          2,
          3,
          4
        ]
      },
      {
        "label": "备注",
        "indexes": [
          5
        ]
      }
    ],
    "actionIndexes": [
      6
    ],
    "expectedHeaders": [
      "客户",
      "费用类型",
      "金额",
      "币种",
      "月份",
      "备注",
      "操作"
    ]
  },
  "company_expense": {
    "label": "运营支出",
    "columns": [
      {
        "label": "支出类型",
        "indexes": [
          0
        ],
        "width": 28
      },
      {
        "label": "金额 / 币种",
        "indexes": [
          1,
          2
        ],
        "width": 22
      },
      {
        "label": "月份 / 日期",
        "indexes": [
          3,
          4
        ],
        "width": 24
      },
      {
        "label": "操作",
        "indexes": [
          6
        ],
        "width": 16
      }
    ],
    "detailGroups": [
      {
        "label": "费用信息",
        "indexes": [
          0,
          1,
          2,
          3,
          4
        ]
      },
      {
        "label": "备注",
        "indexes": [
          5
        ]
      }
    ],
    "actionIndexes": [
      6
    ],
    "expectedHeaders": [
      "支出类型",
      "金额",
      "币种",
      "月份",
      "支出日期",
      "备注",
      "操作"
    ]
  },
  "monthly_detail": {
    "label": "按月明细",
    "columns": [
      {
        "label": "月份 / 关账",
        "indexes": [
          0,
          1
        ],
        "width": 27
      },
      {
        "label": "净收款",
        "indexes": [
          4
        ],
        "width": 17,
        "align": "right"
      },
      {
        "label": "服务收入",
        "indexes": [
          5
        ],
        "width": 17,
        "align": "right"
      },
      {
        "label": "总成本",
        "indexes": [
          18
        ],
        "width": 17,
        "align": "right"
      },
      {
        "label": "经营利润",
        "indexes": [
          19
        ],
        "width": 20,
        "align": "right"
      }
    ],
    "detailGroups": [
      {
        "label": "资金收支",
        "indexes": [
          0,
          2,
          3,
          4
        ]
      },
      {
        "label": "服务与管理费收入",
        "indexes": [
          5,
          6,
          8
        ]
      },
      {
        "label": "投流客户资金",
        "indexes": [
          7,
          9,
          10
        ]
      },
      {
        "label": "费用与经营利润",
        "indexes": [
          11,
          12,
          13,
          14,
          15,
          16,
          17,
          18,
          19
        ]
      }
    ],
    "actionIndexes": [
      1
    ],
    "expectedHeaders": [
      "月份",
      "关账",
      "总收款",
      "退款",
      "净收款",
      "服务收入",
      "管理费收入",
      "投流客户资金",
      "确认投流差价",
      "广告实支",
      "投流结余",
      "管理费扣点率",
      "管理费扣点",
      "Stripe手续费",
      "总扣点",
      "客户成本",
      "USD运营支出",
      "渠道佣金",
      "总成本 (cost)",
      "利润 (profit)"
    ]
  }
} satisfies Record<string, { label: string; columns: CompactFinanceColumn[]; detailGroups: CompactFinanceDetailGroup[]; actionIndexes: number[]; expectedHeaders: string[] }>;
