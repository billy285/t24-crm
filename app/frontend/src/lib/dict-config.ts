import { useEffect, useState } from 'react';
import { APP_CONFIG_UPDATED_EVENT, readCachedAppConfig, writeCachedAppConfig } from './app-config';

export interface BusinessDictConfig {
  industries: string;
  statuses: string;
  sources: string;
  levels: string;
  products: string;
  incomeTypes: string;
  customerPackages: string;
  customerPackagePlatforms: string;
  countries: string;
  billingCycles: string;
  paymentModes: string;
  paymentMethods: string;
  customerExpenseTypes: string;
  companyExpenseTypes: string;
  subscriptionStatuses: string;
  followUpStages: string;
  followUpMethods: string;
  callbackTypes: string;
  callbackStatuses: string;
  callbackResults: string;
  taskTypes: string;
  taskPriorities: string;
  taskStatuses: string;
}

export const defaultBusinessDictConfig: BusinessDictConfig = {
  industries: 'restaurant:餐厅,nail:美甲,massage:按摩,beauty:美容,supermarket:超市,other:其他',
  statuses: 'new:新线索,following:跟进中,closed:已成交,paused:暂停,lost:流失',
  sources: 'phone:电话销售,referral:转介绍,ads:广告,private:私域,returning:老客户,other:其他',
  levels: 'high:高意向,normal:普通,low:低意向,vip:VIP',
  products: 'ordering_system:线上点餐系统,social_media:新媒体代运营,ads:广告投放,website:网站设计,combo:组合套餐',
  incomeTypes: 'management_fee:管理费,ads_fee:投流费,management_ads_mixed:管理费+投流费,website_fee:网站费,ordering_fee:点餐系统费,renewal_fee:续费收入,other_income:其他收入',
  customerPackages: 'google_business_management:Google商家管理,facebook_business_management:Facebook商家管理,instagram_business_management:Instagram商家管理,yelp_business_management:Yelp商家管理,tiktok_business_management:Tiktok商家管理,xiaohongshu_management:小红书管理,x_business_management:X商家管理,ads_campaign_management:广告投放,brand_website:品牌官网',
  customerPackagePlatforms: 'google_business_management:google_business,facebook_business_management:facebook,instagram_business_management:instagram,yelp_business_management:yelp,tiktok_business_management:tiktok,xiaohongshu_management:xiaohongshu,x_business_management:x,ads_campaign_management:ads_campaign,brand_website:brand_website',
  countries: 'US:美国,CA:加拿大,GB:英国,AU:澳大利亚',
  billingCycles: 'monthly:月付,quarterly:季付,semi_annual:半年付,annual:年付',
  paymentModes: 'subscription_auto:自动订阅扣款,manual_collection:手动收款',
  paymentMethods: 'stripe:Stripe自动扣款,check:支票,zelle:Zelle,apple_cash:Apple Cash,venmo:Venmo,wire:电汇,cash:现金,credit_card:信用卡,other:其他',
  customerExpenseTypes: 'ads_fee:投流成本,website_fee:网站成本,domain_fee:域名费,hosting_fee:主机/服务器费,design_fee:设计制作费,other:其他客户成本',
  companyExpenseTypes: 'salary:工资,internet:网络费,phone:电话费,rent:办公室租金,software:软件订阅费,ai_tools:AI工具费,cloud_services:云服务费,operations_tools:运营工具费,recruitment:招聘费,travel:差旅费,other_company:其他支出',
  subscriptionStatuses: 'active:正常,expiring_soon:即将到期,renewal_pending:待扣款确认,expired:已到期,renewed:已续费,upgraded:已升级结束,stopped:停止续费,paused:暂停,lost:流失',
  followUpStages: 'new_lead:新线索,contacted:已联系,communicating:沟通中,quoted:已报价,considering:考虑中,pending_close:待成交,closed:已成交,not_closed:未成交,lost:流失,follow_later:后续再跟进',
  followUpMethods: 'phone:电话,wechat:微信,sms:短信,email:邮件',
  callbackTypes: 'satisfaction:满意度回访,renewal:续费提醒,upsell:增值服务推荐,maintenance:售后维护,feedback:意见收集,other:其他',
  callbackStatuses: 'pending:待回访,completed:已完成,no_answer:未接通,rescheduled:已改期,cancelled:已取消',
  callbackResults: 'satisfied:满意,neutral:一般,unsatisfied:不满意,interested:有意向,not_interested:无意向,need_followup:需再跟进',
  taskTypes: 'follow_up:跟进客户,design:设计页面,menu_entry:菜单录入,stripe_setup:Stripe配置,google_auth:Google权限,test_order:测试订单,report:周报提交,renewal_reminder:续费催款,other:其他',
  taskPriorities: 'high:高,medium:中,low:低',
  taskStatuses: 'pending:待处理,in_progress:进行中,completed:已完成,delayed:延期',
};

export const coreCustomerPackageLabels: Record<string, string> = {
  google_business_management: 'Google商家管理',
  facebook_business_management: 'Facebook商家管理',
  instagram_business_management: 'Instagram商家管理',
  yelp_business_management: 'Yelp商家管理',
  tiktok_business_management: 'Tiktok商家管理',
  xiaohongshu_management: '小红书管理',
};

export const platformLabels: Record<string, string> = {
  google_business: 'Google商家',
  facebook: 'Facebook',
  instagram: 'Instagram',
  yelp: 'Yelp',
  tiktok: 'TikTok',
  xiaohongshu: '小红书',
  x: 'X',
  ads_campaign: '广告投放',
  brand_website: '品牌官网',
};

const packagePlatformRules: Array<{ platform: string; labels: string[] }> = [
  { platform: 'google_business', labels: ['Google商家管理', 'Google Business', 'google_business_management'] },
  { platform: 'facebook', labels: ['Facebook商家管理', 'facebook_business_management'] },
  { platform: 'instagram', labels: ['Instagram商家管理', 'Instgram商家管理', 'instgram商家管理', 'instagram_business_management'] },
  { platform: 'yelp', labels: ['Yelp商家管理', 'yelp_business_management'] },
  { platform: 'tiktok', labels: ['Tiktok商家管理', 'TikTok商家管理', 'tiktok_business_management'] },
  { platform: 'xiaohongshu', labels: ['小红书管理', 'xiaohongshu_management'] },
  { platform: 'x', labels: ['X商家管理', 'Twitter商家管理', 'x_business_management'] },
  { platform: 'ads_campaign', labels: ['广告投放', 'ads_campaign_management'] },
  { platform: 'brand_website', labels: ['品牌官网', '官网', '网站', 'brand_website'] },
];

export interface BusinessDictMaps {
  industries: Record<string, string>;
  statuses: Record<string, string>;
  sources: Record<string, string>;
  levels: Record<string, string>;
  products: Record<string, string>;
  incomeTypes: Record<string, string>;
  customerPackages: Record<string, string>;
  customerPackagePlatforms: Record<string, string[]>;
  countries: Record<string, string>;
  billingCycles: Record<string, string>;
  paymentModes: Record<string, string>;
  paymentMethods: Record<string, string>;
  customerExpenseTypes: Record<string, string>;
  companyExpenseTypes: Record<string, string>;
  subscriptionStatuses: Record<string, string>;
  followUpStages: Record<string, string>;
  followUpMethods: Record<string, string>;
  callbackTypes: Record<string, string>;
  callbackStatuses: Record<string, string>;
  callbackResults: Record<string, string>;
  taskTypes: Record<string, string>;
  taskPriorities: Record<string, string>;
  taskStatuses: Record<string, string>;
}

export function normalizeDictConfig(config?: Partial<BusinessDictConfig>): BusinessDictConfig {
  return { ...defaultBusinessDictConfig, ...(config || {}) };
}

export function parseDictEntries(value: string): Record<string, string> {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
    .reduce<Record<string, string>>((acc, item) => {
      const separatorIndex = item.indexOf(':');
      if (separatorIndex === -1) return acc;
      const key = item.slice(0, separatorIndex).trim();
      const label = item.slice(separatorIndex + 1).trim();
      if (!key || !label) return acc;
      acc[key] = label;
      return acc;
    }, {});
}

export function serializeDictEntries(entries: Record<string, string>): string {
  return Object.entries(entries)
    .filter(([, label]) => Boolean(label?.trim()))
    .map(([key, label]) => `${key}:${sanitizeDictLabel(label)}`)
    .join(',');
}

export function parsePackagePlatformEntries(value?: string): Record<string, string[]> {
  return (value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
    .reduce<Record<string, string[]>>((acc, item) => {
      const separatorIndex = item.indexOf(':');
      if (separatorIndex === -1) return acc;
      const key = item.slice(0, separatorIndex).trim();
      const platforms = item
        .slice(separatorIndex + 1)
        .split('|')
        .map(platform => platform.trim())
        .filter(platform => Boolean(platform) && Boolean(platformLabels[platform]));
      if (key && platforms.length > 0) {
        acc[key] = Array.from(new Set(platforms));
      }
      return acc;
    }, {});
}

export function serializePackagePlatformEntries(entries: Record<string, string[]>): string {
  return Object.entries(entries)
    .map(([key, platforms]) => [
      key,
      Array.from(new Set((platforms || []).filter(platform => Boolean(platformLabels[platform])))),
    ] as const)
    .filter(([key, platforms]) => Boolean(key) && platforms.length > 0)
    .map(([key, platforms]) => `${key}:${platforms.join('|')}`)
    .join(',');
}

export function sanitizeDictLabel(label: string): string {
  // The dictionary string uses "," and ":" as separators, so keep labels readable without breaking parsing.
  return label.trim().replace(/,/g, '，').replace(/:/g, '：');
}

function normalizePlatformText(value?: string | null) {
  return (value || '').toLowerCase().replace(/\s+/g, '');
}

export function inferPackagePlatforms(
  packageName?: string | null,
  customerPackageLabels: Record<string, string> = {},
  customerPackagePlatforms: Record<string, string[]> = {},
) {
  const tokens = (packageName || '')
    .split(/[、,，]/)
    .map(item => item.trim())
    .filter(Boolean);
  const normalizedFull = normalizePlatformText(packageName);
  const platforms: string[] = [];
  const addPlatforms = (items?: string[]) => {
    (items || []).forEach(platform => {
      if (platformLabels[platform] && !platforms.includes(platform)) platforms.push(platform);
    });
  };
  const labelToKey = new Map<string, string>();
  Object.entries(customerPackageLabels).forEach(([key, label]) => {
    labelToKey.set(normalizePlatformText(label), key);
    labelToKey.set(normalizePlatformText(key), key);
  });

  tokens.forEach(token => {
    const normalizedToken = normalizePlatformText(token);
    const matchedKey = labelToKey.get(normalizedToken);
    if (matchedKey) addPlatforms(customerPackagePlatforms[matchedKey]);
    packagePlatformRules
      .filter(rule => rule.labels.some(label => normalizedToken.includes(normalizePlatformText(label))))
      .forEach(rule => addPlatforms([rule.platform]));
  });

  if (platforms.length === 0 && normalizedFull) {
    Object.entries(customerPackageLabels).forEach(([key, label]) => {
      const normalizedLabel = normalizePlatformText(label);
      if (normalizedLabel && normalizedFull.includes(normalizedLabel)) {
        addPlatforms(customerPackagePlatforms[key]);
      }
    });
    packagePlatformRules
      .filter(rule => rule.labels.some(label => normalizedFull.includes(normalizePlatformText(label))))
      .forEach(rule => addPlatforms([rule.platform]));
  }

  return platforms;
}

export function buildOptionKey(label: string): string {
  const normalized = label.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  return normalized ? `custom_${normalized}` : `custom_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

export function loadDictConfig(): BusinessDictConfig {
  const cached = readCachedAppConfig<Partial<BusinessDictConfig>>('dict_config', defaultBusinessDictConfig);
  return normalizeDictConfig(cached);
}

export function saveDictConfig(config: BusinessDictConfig) {
  writeCachedAppConfig('dict_config', normalizeDictConfig(config));
}

export function buildBusinessDicts(config = loadDictConfig()): BusinessDictMaps {
  const normalized = normalizeDictConfig(config);
  return {
    industries: parseDictEntries(normalized.industries),
    statuses: parseDictEntries(normalized.statuses),
    sources: parseDictEntries(normalized.sources),
    levels: parseDictEntries(normalized.levels),
    products: parseDictEntries(normalized.products),
    incomeTypes: parseDictEntries(normalized.incomeTypes),
    customerPackages: parseDictEntries(normalized.customerPackages),
    customerPackagePlatforms: parsePackagePlatformEntries(normalized.customerPackagePlatforms),
    countries: parseDictEntries(normalized.countries),
    billingCycles: parseDictEntries(normalized.billingCycles),
    paymentModes: parseDictEntries(normalized.paymentModes),
    paymentMethods: parseDictEntries(normalized.paymentMethods),
    customerExpenseTypes: parseDictEntries(normalized.customerExpenseTypes),
    companyExpenseTypes: parseDictEntries(normalized.companyExpenseTypes),
    subscriptionStatuses: parseDictEntries(normalized.subscriptionStatuses),
    followUpStages: parseDictEntries(normalized.followUpStages),
    followUpMethods: parseDictEntries(normalized.followUpMethods),
    callbackTypes: parseDictEntries(normalized.callbackTypes),
    callbackStatuses: parseDictEntries(normalized.callbackStatuses),
    callbackResults: parseDictEntries(normalized.callbackResults),
    taskTypes: parseDictEntries(normalized.taskTypes),
    taskPriorities: parseDictEntries(normalized.taskPriorities),
    taskStatuses: parseDictEntries(normalized.taskStatuses),
  };
}

export function useDictConfig() {
  const [config, setConfig] = useState<BusinessDictConfig>(() => loadDictConfig());

  useEffect(() => {
    const refresh = () => setConfig(loadDictConfig());
    refresh();
    window.addEventListener(APP_CONFIG_UPDATED_EVENT, refresh as EventListener);
    return () => window.removeEventListener(APP_CONFIG_UPDATED_EVENT, refresh as EventListener);
  }, []);

  return config;
}

export function useBusinessDicts() {
  const [dicts, setDicts] = useState<BusinessDictMaps>(() => buildBusinessDicts());

  useEffect(() => {
    const refresh = () => setDicts(buildBusinessDicts());
    refresh();
    window.addEventListener(APP_CONFIG_UPDATED_EVENT, refresh as EventListener);
    return () => window.removeEventListener(APP_CONFIG_UPDATED_EVENT, refresh as EventListener);
  }, []);

  return dicts;
}
