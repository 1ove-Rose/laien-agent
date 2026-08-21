const DEFAULT_STOREFRONT = "us";
const SUPPORTED_STOREFRONTS = new Set(["us", "cn"]);
const STOREFRONT_LABELS = { us: "美国", cn: "中国" };
const PAGE_SIZE = 50;
const MAX_PAGES = 10;
const MAX_REVIEWS = PAGE_SIZE * MAX_PAGES;
const REQUEST_TIMEOUT_MS = 10_000;
const MAX_RETRIES = 2;
const PAGE_DELAY_MS = 150;

class ApiError extends Error {
  constructor(code, message, { status = 500, retryable = false, cause } = {}) {
    super(message, { cause });
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.retryable = retryable;
  }
}

function parseAppStoreUrl(value) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new ApiError("INVALID_APP_URL", "请输入有效的 App Store 链接。", { status: 400 });
  }

  if (parsed.protocol !== "https:" || parsed.hostname.toLowerCase() !== "apps.apple.com") {
    throw new ApiError("INVALID_APP_URL", "链接必须来自 https://apps.apple.com。", { status: 400 });
  }

  const match = parsed.pathname.match(/(?:^|\/)id(\d+)(?:\/|$)/i);
  if (!match) {
    throw new ApiError("INVALID_APP_URL", "无法从 App Store 链接中识别应用 ID。", { status: 400 });
  }

  const storefrontMatch = parsed.pathname.match(/^\/([a-z]{2})(?:\/|$)/i);
  const storefront = storefrontMatch && SUPPORTED_STOREFRONTS.has(storefrontMatch[1].toLowerCase())
    ? storefrontMatch[1].toLowerCase()
    : DEFAULT_STOREFRONT;

  return { appId: match[1], storefront };
}

function normalizeStorefront(country = DEFAULT_STOREFRONT) {
  const storefront = String(country || DEFAULT_STOREFRONT).toLowerCase();
  if (!SUPPORTED_STOREFRONTS.has(storefront)) {
    throw new ApiError("INVALID_COUNTRY", "当前仅支持美国和中国 App Store 评论。", { status: 400 });
  }
  return storefront;
}

function validateCollectionInput({ appUrl, country = DEFAULT_STOREFRONT, maxReviews = 200 }) {
  const parsed = parseAppStoreUrl(appUrl);
  const storefront = normalizeStorefront(country);
  const requestedCount = Number(maxReviews);

  if (!Number.isInteger(requestedCount) || requestedCount < 1 || requestedCount > MAX_REVIEWS) {
    throw new ApiError("INVALID_MAX_REVIEWS", `评论上限必须是 1 到 ${MAX_REVIEWS} 之间的整数。`, {
      status: 400
    });
  }

  return { appId: parsed.appId, storefront, requestedCount };
}

function label(value, fallback = "") {
  if (value && typeof value === "object" && "label" in value) return String(value.label ?? fallback);
  return value == null ? fallback : String(value);
}

function ensureArray(value) {
  if (!value) return [];
  return Array.isArray(value) ? value : [value];
}

function countAppleEntries(feedPayload) {
  return ensureArray(feedPayload?.feed?.entry).length;
}

function mapAppleFeed(feedPayload, { appId, storefront = DEFAULT_STOREFRONT, fetchedAt }) {
  if (!feedPayload || typeof feedPayload !== "object" || !feedPayload.feed || typeof feedPayload.feed !== "object") {
    throw new ApiError("APPLE_INVALID_RESPONSE", "Apple 评论接口返回了无法识别的数据。", {
      status: 502,
      retryable: true
    });
  }

  return ensureArray(feedPayload.feed.entry).map((entry) => ({
    id: label(entry.id),
    appId,
    country: storefront,
    rating: Number(label(entry["im:rating"], "0")),
    version: label(entry["im:version"]),
    title: label(entry.title),
    text: label(entry.content),
    author: label(entry.author?.name),
    authorUrl: label(entry.author?.uri),
    createdAt: label(entry.updated) || null,
    sourceUrl: entry.link?.attributes?.href ? String(entry.link.attributes.href) : "",
    sourceType: "apple-rss",
    fetchedAt
  }));
}

function applePageUrl(appId, page, storefront = DEFAULT_STOREFRONT) {
  return `https://itunes.apple.com/${storefront}/rss/customerreviews/page=${page}/id=${appId}/sortby=mostrecent/json`;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function toRequestError(error) {
  if (error instanceof ApiError) return error;
  if (error?.name === "AbortError") {
    return new ApiError("APPLE_REQUEST_TIMEOUT", "Apple 评论请求超时。", {
      status: 504,
      retryable: true,
      cause: error
    });
  }
  return new ApiError("APPLE_REQUEST_FAILED", "无法获取 App Store 评论。", {
    status: 502,
    retryable: true,
    cause: error
  });
}

async function requestApplePage({
  appId,
  storefront,
  page,
  fetchImpl,
  requestTimeoutMs,
  maxRetries,
  now,
  sleepImpl
}) {
  let lastError;
  for (let attempt = 0; attempt <= maxRetries; attempt += 1) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), requestTimeoutMs);
    try {
      const response = await fetchImpl(applePageUrl(appId, page, storefront), {
        headers: { Accept: "application/json", "User-Agent": "app-review-insights/1.0" },
        signal: controller.signal
      });

      if (response.status === 404) {
        throw new ApiError("APP_NOT_FOUND", "未找到对应的 App Store 应用或评论源。", {
          status: 404,
          retryable: false
        });
      }
      if (!response.ok) {
        const retryable = response.status === 429 || response.status >= 500;
        throw new ApiError("APPLE_REQUEST_FAILED", `Apple 评论接口返回 HTTP ${response.status}。`, {
          status: response.status === 429 ? 429 : 502,
          retryable
        });
      }

      let data;
      try {
        data = await response.json();
      } catch (error) {
        throw new ApiError("APPLE_INVALID_RESPONSE", "Apple 评论接口返回了无效 JSON。", {
          status: 502,
          retryable: true,
          cause: error
        });
      }
      if (!data || typeof data !== "object" || !data.feed || typeof data.feed !== "object") {
        throw new ApiError("APPLE_INVALID_RESPONSE", "Apple 评论接口返回了无法识别的数据。", {
          status: 502,
          retryable: true
        });
      }

      const fetchedAt = new Date(now()).toISOString();
      return { data, fetchedAt, cache: "network", warning: null };
    } catch (error) {
      lastError = toRequestError(error);
      if (!lastError.retryable || attempt === maxRetries) break;
      await sleepImpl(150 * 2 ** attempt);
    } finally {
      clearTimeout(timeout);
    }
  }

  throw lastError;
}

async function collectReviews(
  input,
  {
    fetchImpl = globalThis.fetch,
    requestTimeoutMs = REQUEST_TIMEOUT_MS,
    maxRetries = MAX_RETRIES,
    pageDelayMs = PAGE_DELAY_MS,
    now = Date.now,
    sleepImpl = sleep
  } = {}
) {
  if (typeof fetchImpl !== "function") {
    throw new ApiError("FETCH_UNAVAILABLE", "当前 Node 运行环境不支持 fetch。", { status: 500 });
  }

  const { appId, storefront, requestedCount } = validateCollectionInput(input);
  const minimumPagesNeeded = Math.min(MAX_PAGES, Math.ceil(requestedCount / PAGE_SIZE));
  const collectedAt = new Date(now()).toISOString();
  const reviews = [];
  const warnings = [];
  const pageSignatures = new Set();
  const emptyPages = [];
  let pagesFetched = 0;
  let fromCache = false;
  let staleCache = false;

  for (let page = 1; page <= MAX_PAGES; page += 1) {
    let result;
    try {
      result = await requestApplePage({
        appId,
        storefront,
        page,
        fetchImpl,
        requestTimeoutMs,
        maxRetries,
        now,
        sleepImpl
      });
    } catch (error) {
      if (page === 1) throw error;
      warnings.push(`第 ${page} 页采集失败，已保留前 ${pagesFetched} 页数据：${error.message}`);
      break;
    }

    pagesFetched += 1;
    fromCache ||= result.cache === "fresh";
    staleCache ||= result.cache === "stale";
    if (result.warning) warnings.push(result.warning);

    const pageReviews = mapAppleFeed(result.data, { appId, storefront, fetchedAt: result.fetchedAt });
    if (pageReviews.length === 0) {
      emptyPages.push(page);
      warnings.push(`第 ${page} 页没有返回可用评论，已继续尝试后续页面。`);
      if (page < MAX_PAGES) await sleepImpl(pageDelayMs);
      continue;
    }

    const signature = pageReviews.map((review) => review.id).join("|");
    if (pageSignatures.has(signature)) {
      warnings.push(`第 ${page} 页与之前页面重复，已提前停止采集。`);
      break;
    }
    pageSignatures.add(signature);
    reviews.push(...pageReviews.slice(0, requestedCount - reviews.length));

    if (reviews.length >= requestedCount) break;
    if (page < MAX_PAGES) await sleepImpl(pageDelayMs);
  }

  if (reviews.length < requestedCount) {
    if (reviews.length === 0 && emptyPages.length > 0) {
      warnings.push("Apple 评论源当前没有返回可用评论。");
    }
    warnings.push(`请求 ${requestedCount} 条评论，实际获得 ${reviews.length} 条。`);
  }

  return {
    appId,
    storefront,
    reviews,
    collection: {
      provider: "apple-rss",
      requestedCount,
      collectedCount: reviews.length,
      pagesRequested: Math.max(minimumPagesNeeded, pagesFetched),
      pagesFetched,
      collectedAt,
      fromCache,
      staleCache,
      warnings
    }
  };
}

module.exports = {
  ApiError,
  DEFAULT_STOREFRONT,
  MAX_REVIEWS,
  STOREFRONT_LABELS,
  SUPPORTED_STOREFRONTS,
  applePageUrl,
  collectReviews,
  mapAppleFeed,
  normalizeStorefront,
  parseAppStoreUrl,
  validateCollectionInput
};
