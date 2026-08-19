const test = require("node:test");
const assert = require("node:assert/strict");
const { cleanReviews, normalizeText } = require("../lib/review-cleaner");

test("normalizes Unicode, invisible spaces, line endings, and mixed-language text", () => {
  assert.equal(normalizeText("  Ａpp\r\n很好\u00a0🙂  "), "App 很好 🙂");
});

test("filters invalid ratings and empty reviews while preserving invalid dates as null", () => {
  const result = cleanReviews({
    appId: "123",
    reviews: [
      { id: "bad-rating", rating: 6, text: "text" },
      { id: "empty", rating: 3, text: "  \u200b " },
      { id: "valid", rating: 4, text: "Useful", createdAt: "not-a-date" }
    ]
  });

  assert.equal(result.reviews.length, 1);
  assert.equal(result.reviews[0].createdAt, null);
  assert.equal(result.report.invalidRatingCount, 1);
  assert.equal(result.report.emptyTextCount, 1);
  assert.equal(result.report.removedCount, 2);
});

test("generates stable IDs and fingerprints for reviews without source IDs", () => {
  const input = {
    appId: "123",
    reviews: [{ rating: 5, title: "很好", text: "训练计划很实用 🙂", author: "用户", createdAt: "2026-08-19" }]
  };
  const first = cleanReviews(input);
  const second = cleanReviews(input);

  assert.match(first.reviews[0].id, /^generated-[a-f0-9]{24}$/);
  assert.equal(first.reviews[0].id, second.reviews[0].id);
  assert.equal(first.reviews[0].fingerprint, second.reviews[0].fingerprint);
  assert.equal(first.report.generatedIdCount, 1);
});

test("deduplicates by source ID before exact normalized content", () => {
  const result = cleanReviews({
    appId: "123",
    reviews: [
      { id: "one", rating: 2, version: "1.0", title: "Bug", text: "Audio is late" },
      { id: "one", rating: 2, version: "1.0", title: "Changed", text: "Different text" },
      { id: "two", rating: 2, version: "1.0", title: "Ｂug", text: "Audio   is late" },
      { id: "three", rating: 2, version: "1.0", title: "Bug", text: "Audio is slightly late" }
    ]
  });

  assert.deepEqual(result.reviews.map((review) => review.id), ["one", "three"]);
  assert.equal(result.report.duplicateIdCount, 1);
  assert.equal(result.report.duplicateContentCount, 1);
  assert.equal(result.report.outputCount, 2);
  assert.equal(result.report.removedCount, 2);
});

test("rejects invalid clean requests", () => {
  assert.throws(() => cleanReviews({ appId: "abc", reviews: [] }), { code: "INVALID_APP_ID" });
  assert.throws(() => cleanReviews({ appId: "123", reviews: null }), { code: "INVALID_REVIEWS" });
});
