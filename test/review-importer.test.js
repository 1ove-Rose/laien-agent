const test = require("node:test");
const assert = require("node:assert/strict");
const { createDatasetId, importReviews, parseCsv, parseJson } = require("../lib/review-importer");
const { cleanReviews } = require("../lib/review-cleaner");

test("imports a JSON review array and maps common fields", () => {
  const result = importReviews({
    fileName: "reviews.json",
    content: JSON.stringify([{ review_id: "r1", score: 5, content: "Great app", date: "2026-01-01" }])
  });

  assert.equal(result.import.format, "json");
  assert.equal(result.reviews[0].id, "r1");
  assert.equal(result.reviews[0].rating, 5);
  assert.equal(result.reviews[0].text, "Great app");
  assert.match(result.appId, /^\d{18}$/);
  assert.equal(result.reviews[0].appId, result.appId);
});

test("imports a JSON object containing reviews", () => {
  assert.equal(parseJson(JSON.stringify({ reviews: [{ text: "ok" }] })).length, 1);
});

test("parses quoted CSV fields containing commas and newlines", () => {
  const rows = parseCsv('id,rating,title,text\n1,4,Title,"line one,\nline two"');
  assert.deepEqual(rows, [{ id: "1", rating: "4", title: "Title", text: "line one,\nline two" }]);
});

test("creates a stable internal dataset ID from file content", () => {
  assert.equal(createDatasetId("same content"), createDatasetId("same content"));
  assert.notEqual(createDatasetId("same content"), createDatasetId("different content"));
});

test("cleans an unfamiliar imported dataset without a supplied App ID", () => {
  const imported = importReviews({
    fileName: "external.csv",
    content: "score,comment,user,time\n4,Useful,Ada,2026-08-01"
  });
  const cleaned = cleanReviews({ appId: imported.appId, reviews: imported.reviews });

  assert.equal(cleaned.reviews.length, 1);
  assert.equal(cleaned.reviews[0].text, "Useful");
  assert.equal(cleaned.reviews[0].sourceType, "file-csv");
  assert.match(cleaned.reviews[0].id, /^generated-/);
});

test("rejects unsupported formats, invalid JSON, and too many rows", () => {
  assert.throws(() => importReviews({ fileName: "reviews.txt", content: "x" }), { code: "UNSUPPORTED_IMPORT_FORMAT" });
  assert.throws(() => importReviews({ fileName: "reviews.json", content: "bad" }), { code: "INVALID_IMPORT_JSON" });
  const records = Array.from({ length: 501 }, (_, index) => ({ id: String(index), rating: 5, text: "review" }));
  assert.throws(() => importReviews({ fileName: "reviews.json", content: JSON.stringify(records) }), { code: "TOO_MANY_REVIEWS" });
});
