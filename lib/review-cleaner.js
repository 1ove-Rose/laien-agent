const crypto = require("crypto");
const { ApiError } = require("./apple-reviews");

const NORMALIZATION_VERSION = "1.0.0";

function normalizeText(value) {
  return String(value ?? "")
    .normalize("NFKC")
    .replace(/\r\n?/g, "\n")
    .replace(/[\u00a0\u200b-\u200d\ufeff]/g, " ")
    .replace(/\s+/gu, " ")
    .trim();
}

function hash(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function normalizeDate(value) {
  if (!value) return null;
  const timestamp = Date.parse(String(value));
  return Number.isFinite(timestamp) ? new Date(timestamp).toISOString() : null;
}

function validateCleanInput({ appId, reviews }) {
  if (!/^\d+$/.test(String(appId ?? ""))) {
    throw new ApiError("INVALID_APP_ID", "清洗请求中的 App ID 无效。", { status: 400 });
  }
  if (!Array.isArray(reviews)) {
    throw new ApiError("INVALID_REVIEWS", "reviews 必须是评论数组。", { status: 400 });
  }
  if (reviews.length > 500) {
    throw new ApiError("TOO_MANY_REVIEWS", "单次最多清洗 500 条评论。", { status: 400 });
  }
}

function cleanReviews({ appId, reviews }) {
  validateCleanInput({ appId, reviews });

  const report = {
    inputCount: reviews.length,
    outputCount: 0,
    removedCount: 0,
    generatedIdCount: 0,
    invalidRatingCount: 0,
    emptyTextCount: 0,
    duplicateIdCount: 0,
    duplicateContentCount: 0,
    removals: []
  };
  const cleaned = [];
  const seenIds = new Set();
  const seenFingerprints = new Set();

  reviews.forEach((review, index) => {
    const title = normalizeText(review?.title);
    const text = normalizeText(review?.text ?? review?.content);
    const version = normalizeText(review?.version) || "unknown";
    const author = normalizeText(review?.author);
    const rawDate = review?.createdAt ?? review?.date ?? null;
    const createdAt = normalizeDate(rawDate);
    const rating = Number(review?.rating);
    const suppliedId = normalizeText(review?.id);
    const removalId = suppliedId || `row-${index + 1}`;

    if (!Number.isInteger(rating) || rating < 1 || rating > 5) {
      report.invalidRatingCount += 1;
      report.removals.push({ reviewId: removalId, reason: "invalid_rating" });
      return;
    }
    if (!text) {
      report.emptyTextCount += 1;
      report.removals.push({ reviewId: removalId, reason: "empty_text" });
      return;
    }

    let id = suppliedId;
    if (!id) {
      id = `generated-${hash([appId, author, rawDate ?? "", title, text].join("\u001f")).slice(0, 24)}`;
      report.generatedIdCount += 1;
    }

    if (seenIds.has(id)) {
      report.duplicateIdCount += 1;
      report.removals.push({ reviewId: id, reason: "duplicate_id" });
      return;
    }

    const fingerprint = hash([title.toLowerCase(), text.toLowerCase(), rating, version].join("\u001f"));
    if (seenFingerprints.has(fingerprint)) {
      report.duplicateContentCount += 1;
      report.removals.push({ reviewId: id, reason: "duplicate_content" });
      return;
    }

    seenIds.add(id);
    seenFingerprints.add(fingerprint);
    cleaned.push({
      ...review,
      id,
      appId: String(appId),
      country: "us",
      rating,
      version,
      title,
      text,
      author,
      createdAt,
      sourceType: normalizeText(review?.sourceType) || "unknown",
      cleanStatus: "normalized",
      fingerprint,
      normalizationVersion: NORMALIZATION_VERSION
    });
  });

  report.outputCount = cleaned.length;
  report.removedCount = report.inputCount - report.outputCount;
  return { reviews: cleaned, report };
}

module.exports = {
  NORMALIZATION_VERSION,
  cleanReviews,
  normalizeDate,
  normalizeText,
  validateCleanInput
};
