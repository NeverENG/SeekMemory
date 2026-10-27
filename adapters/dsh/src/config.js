/**
 * 配置：默认值 + 归一化。
 *
 * 刻意**不导出 schemastery 的 `Config`**：cordis 只读 `plugin.Config`，
 * 但我们没有本地 schemastery 依赖，静态 import 它在宿主缺包时会让
 * 整个插件树加载失败（《方案 v2.1》G13）——宁可手工校验，也不要加载期风险。
 * 等确认宿主一定提供 schemastery 后再换成真正的 schema。
 */

export const DEFAULTS = {
  /** 总开关。关掉即完全不注册任何钩子。 */
  enabled: true,
  /** 内核 runtime.json 的路径；留空则按 dataDir 推导。 */
  runtimePath: '',
  /** 内核数据目录（仅用于推导 runtimePath，不影响内核自己的配置）。 */
  dataDir: '',
  /** 期望的契约版本；内核报别的版本即拒绝注入并给出 contract_mismatch。 */
  hostContract: 1,
  /** /recall 超时（毫秒）。超过就当本轮没有记忆，绝不拖慢对话。 */
  recallTimeoutMs: 800,
  /** /capture 超时（毫秒）。捕获失败只记日志。 */
  captureTimeoutMs: 300,
  /** 每轮注入的记忆字符上限。 */
  budgetChars: 600,
  /** 每轮最多几条。 */
  k: 8,
  /** 主体键。留空 + mode=auto 时按会话推导（见 host-dsh.js）。 */
  subjectKey: '',
  /** auto：从会话元数据推导；fixed：一律用 subjectKey（单用户宿主）。 */
  subjectMode: 'auto',
  /** 关掉则可只捕获不注入（用于和别的记忆插件并存的过渡期）。 */
  injectRecall: true,
  /** 是否注入人格块。 */
  injectPersona: true,
  /** 降级原因是否写进状态（G14：不静默）。 */
  reportDegraded: true,
  /** 日志前缀。 */
  logPrefix: '[seekmemory]',
  /** 日志目录；留空 = $DSH_HOME/seekmemory-logs，再退系统临时目录。 */
  logDir: '',
  /** 跳闸状态目录（boot.json 放这里）；留空 = 与日志同目录。 */
  stateDir: '',
  /** 连续几次"启动阶段没走完"后进入安全模式。1 = 崩一次就跳闸。 */
  safeModeAfterFailures: 1,
  /** 安全模式里连续启动几次后自动重试一次（自愈）。0 = 永不自动重试。 */
  safeModeAutoRetry: 3,
  /** 抽取循环（拉取式）。默认关：不配 llmProvider/llmModel 时它没意义。 */
  extractEnabled: false,
  /** 抽取用的宿主侧 provider / model。留空则跳过并记原因，绝不猜默认值。 */
  llmProvider: '',
  llmModel: '',
};

function clampInt(value, min, max, fallback) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, Math.trunc(n)));
}

/**
 * @param {Record<string, unknown>} raw
 * @returns {{ config: typeof DEFAULTS, warnings: string[] }}
 */
export function normalize(raw) {
  const input = raw && typeof raw === 'object' ? raw : {};
  const warnings = [];
  const cfg = { ...DEFAULTS };

  const bool = (key) => {
    const v = input[key];
    if (v === undefined) return;
    if (typeof v === 'boolean') cfg[key] = v;
    else warnings.push(`${key}: 期望 boolean，忽略 ${JSON.stringify(v)}`);
  };
  const str = (key) => {
    const v = input[key];
    if (v === undefined) return;
    if (typeof v === 'string') cfg[key] = v;
    else warnings.push(`${key}: 期望 string，忽略 ${JSON.stringify(v)}`);
  };

  bool('enabled');
  bool('injectRecall');
  bool('injectPersona');
  bool('reportDegraded');
  str('runtimePath');
  str('dataDir');
  str('subjectKey');
  str('logPrefix');
  str('logDir');
  str('stateDir');
  str('llmProvider');
  str('llmModel');
  bool('extractEnabled');

  cfg.hostContract = clampInt(input.hostContract, 0, 1_000_000, DEFAULTS.hostContract);
  cfg.recallTimeoutMs = clampInt(input.recallTimeoutMs, 50, 30_000, DEFAULTS.recallTimeoutMs);
  cfg.captureTimeoutMs = clampInt(input.captureTimeoutMs, 50, 30_000, DEFAULTS.captureTimeoutMs);
  cfg.budgetChars = clampInt(input.budgetChars, 0, 20_000, DEFAULTS.budgetChars);
  cfg.k = clampInt(input.k, 0, 50, DEFAULTS.k);
  cfg.safeModeAfterFailures = clampInt(input.safeModeAfterFailures, 1, 10, DEFAULTS.safeModeAfterFailures);
  cfg.safeModeAutoRetry = clampInt(input.safeModeAutoRetry, 0, 50, DEFAULTS.safeModeAutoRetry);

  const mode = input.subjectMode;
  if (mode !== undefined) {
    if (mode === 'auto' || mode === 'fixed') cfg.subjectMode = mode;
    else warnings.push(`subjectMode: 只接受 auto|fixed，忽略 ${JSON.stringify(mode)}`);
  }

  if (cfg.subjectMode === 'fixed' && !cfg.subjectKey) {
    warnings.push('subjectMode=fixed 但 subjectKey 为空：将退化为 owner_only 单用户模式');
  }

  return { config: cfg, warnings };
}
