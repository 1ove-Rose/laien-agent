const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs/promises");
const os = require("os");
const path = require("path");
const {
  collectReviews,
  mapAppleFeed,
  parseAppStoreUrl,
  validateCollectionInput
} = require("../lib/apple-reviews");

function makeEntry(id, overrides = {}) {
  return {
    id: { label: String(id) },
    author: {
      name: { label: overrides.author || `author-${id}` },
      uri: { label: `https://itunes.apple.com/us/reviews/id${id}` }
    },
    "im:version": { label: overrides.version || "1.2.3" },
    "im:rating": { label: String(overrides.rating || 4) },
    title: { label: overrides.title || `title-${id}` },
    content: { label: overrides.text || `review-${id}` },
    link: { attributes: { href: `https://itunes.apple.com/us/review?id=${id}` } },
    updated: { label: overrides.updated || "2026-08-19T10:00:00-07:00" }
  };
}

function makePage(start, count = 50) {
  return { feed: { entry: Array.from({ length: count }, (_, index) => makeEntry(start + index)) } };
}

function response(status, payload) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() {
      if (payload instanceof Error) throw payload;
      return payload;
    }
  };
}

async function tempCache(t) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "app-review-cache-"));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  return directory;
}

test("parses US and CN App Store links and always selects the US storefront", () => {
  assert.deepEqual(parseAppStoreUrl("https://apps.apple.com/us/app/example/id839285684"), {
    appId: "839285684",
    storefront: "us"
  });
  assert.deepEqual(parseAppStoreUrl("https://apps.apple.com/cn/app/example/id839285684?l=en"), {
    appId: "839285684",
    storefront: "us"
  });
});

test("rejects non-Apple links, missing IDs, unsupported countries, and invalid limits", () => {
  assert.throws(() => parseAppStoreUrl("https://example.com/us/app/id123"), { code: "INVALID_APP_URL" });
  assert.throws(() => parseAppStoreUrl("https://apps.apple.com/us/app/example"), { code: "INVALID_APP_URL" });
  assert.throws(
    () => validateCollectionInput({ appUrl: "https://apps.apple.com/us/app/example/id123", country: "cn" }),
    { code: "INVALID_COUNTRY" }
  );
  assert.throws(
    () => validateCollectionInput({ appUrl: "https://apps.apple.com/us/app/example/id123", maxReviews: 501 }),
    { code: "INVALID_MAX_REVIEWS" }
  );
});

test("maps both a single Apple entry and an entry array", () => {
  const single = mapAppleFeed({ feed: { entry: makeEntry(1) } }, { appId: "123", fetchedAt: "now" });
  const multiple = mapAppleFeed(
    { feed: { entry: [makeEntry(1), makeEntry(2)] } },
    { appId: "123", fetchedAt: "now" }
  );

  assert.equal(single.length, 1);
  assert.equal(multiple.length, 2);
  assert.deepEqual(
    {
      id: single[0].id,
      appId: single[0].appId,
      country: single[0].country,
      rating: single[0].rating,
      sourceType: single[0].sourceType
    },
    { id: "1", appId: "123", country: "us", rating: 4, sourceType: "apple-rss" }
  );
});

for (const [limit, expectedPages] of [[100, 2], [200, 4], [400, 8]]) {
  test(`collects ${limit} reviews from ${expectedPages} sequential pages`, async (t) => {
    const cacheDir = await tempCache(t);
    const calls = [];
    const result = await collectReviews(
      { appUrl: "https://apps.apple.com/us/app/example/id123", country: "us", maxReviews: limit },
      {
        cacheDir,
        sleepImpl: async () => {},
        now: () => Date.parse("2026-08-19T00:00:00Z"),
        fetchImpl: async (url) => {
          const page = Number(url.match(/page=(\d+)/)[1]);
          calls.push(page);
          return response(200, makePage((page - 1) * 50 + 1));
        }
      }
    );

    assert.equal(result.reviews.length, limit);
    assert.equal(result.collection.pagesFetched, expectedPages);
    assert.deepEqual(calls, Array.from({ length: expectedPages }, (_, index) => index + 1));
  });
}

test("reports the shortfall when later pages are empty", async (t) => {
  const cacheDir = await tempCache(t);
  const result = await collectReviews(
    { appUrl: "https://apps.apple.com/us/app/example/id123", maxReviews: 100 },
    {
      cacheDir,
      sleepImpl: async () => {},
      fetchImpl: async (url) => {
        const page = Number(url.match(/page=(\d+)/)[1]);
        return response(200, page === 1 ? makePage(1, 20) : { feed: {} });
      }
    }
  );

  assert.equal(result.reviews.length, 20);
  assert.match(result.collection.warnings.join(" "), /实际获得 20 条/);
});

test("continues after an empty page because Apple RSS can return sparse pages", async (t) => {
  const cacheDir = await tempCache(t);
  const calls = [];
  const result = await collectReviews(
    { appUrl: "https://apps.apple.com/us/app/example/id123", maxReviews: 100 },
    {
      cacheDir,
      sleepImpl: async () => {},
      fetchImpl: async (url) => {
        const page = Number(url.match(/page=(\d+)/)[1]);
        calls.push(page);
        return response(200, page <= 2 ? { feed: {} } : makePage((page - 3) * 50 + 1, 50));
      }
    }
  );

  assert.equal(result.reviews.length, 100);
  assert.equal(result.collection.pagesFetched, 4);
  assert.deepEqual(calls, [1, 2, 3, 4]);
  assert.match(result.collection.warnings.join(" "), /第 1 页没有返回可用评论/);
});

test("retries retryable failures before succeeding", async (t) => {
  const cacheDir = await tempCache(t);
  let calls = 0;
  const result = await collectReviews(
    { appUrl: "https://apps.apple.com/us/app/example/id123", maxReviews: 1 },
    {
      cacheDir,
      sleepImpl: async () => {},
      fetchImpl: async () => {
        calls += 1;
        return calls < 3 ? response(500, {}) : response(200, makePage(1, 1));
      }
    }
  );

  assert.equal(calls, 3);
  assert.equal(result.reviews.length, 1);
});

test("keeps earlier pages when a later page fails", async (t) => {
  const cacheDir = await tempCache(t);
  const result = await collectReviews(
    { appUrl: "https://apps.apple.com/us/app/example/id123", maxReviews: 100 },
    {
      cacheDir,
      maxRetries: 0,
      sleepImpl: async () => {},
      fetchImpl: async (url) => {
        const page = Number(url.match(/page=(\d+)/)[1]);
        return page === 1 ? response(200, makePage(1)) : response(500, {});
      }
    }
  );

  assert.equal(result.reviews.length, 50);
  assert.match(result.collection.warnings.join(" "), /第 2 页采集失败/);
});

test("uses fresh cache and falls back to stale cache when the network fails", async (t) => {
  const cacheDir = await tempCache(t);
  const input = { appUrl: "https://apps.apple.com/us/app/example/id123", maxReviews: 1 };
  let networkCalls = 0;

  await collectReviews(input, {
    cacheDir,
    now: () => Date.parse("2026-08-19T00:00:00Z"),
    sleepImpl: async () => {},
    fetchImpl: async () => {
      networkCalls += 1;
      return response(200, makePage(1, 1));
    }
  });

  const fresh = await collectReviews(input, {
    cacheDir,
    now: () => Date.parse("2026-08-19T00:30:00Z"),
    sleepImpl: async () => {},
    fetchImpl: async () => {
      throw new Error("fresh cache should avoid the network");
    }
  });
  assert.equal(fresh.collection.fromCache, true);
  assert.equal(networkCalls, 1);

  const stale = await collectReviews(input, {
    cacheDir,
    cacheTtlMs: 1,
    maxRetries: 0,
    now: () => Date.parse("2026-08-19T02:00:00Z"),
    sleepImpl: async () => {},
    fetchImpl: async () => {
      throw new Error("offline");
    }
  });
  assert.equal(stale.collection.staleCache, true);
  assert.match(stale.collection.warnings.join(" "), /过期缓存/);
});

test("ignores a fresh empty cache page and retries the Apple feed", async (t) => {
  const cacheDir = await tempCache(t);
  const input = { appUrl: "https://apps.apple.com/us/app/example/id123", maxReviews: 1 };
  await fs.writeFile(
    path.join(cacheDir, "123-page-1.json"),
    JSON.stringify({
      fetchedAt: "2026-08-19T00:10:00Z",
      data: { feed: { title: { label: "Customer Reviews" } } }
    }),
    "utf8"
  );

  let networkCalls = 0;
  const result = await collectReviews(input, {
    cacheDir,
    now: () => Date.parse("2026-08-19T00:30:00Z"),
    sleepImpl: async () => {},
    fetchImpl: async () => {
      networkCalls += 1;
      return response(200, makePage(1, 1));
    }
  });

  assert.equal(networkCalls, 1);
  assert.equal(result.reviews.length, 1);
  assert.equal(result.collection.fromCache, false);
});
