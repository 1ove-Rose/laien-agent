const path = require("path");
const crypto = require("crypto");
const { ApiError } = require("./apple-reviews");

const MAX_IMPORT_REVIEWS = 500;
const MAX_IMPORT_BYTES = 2 * 1024 * 1024;

const aliases = {
  id: ["id", "reviewId", "review_id", "评论id", "评论 ID"],
  rating: ["rating", "score", "stars", "评分"],
  version: ["version", "appVersion", "app_version", "版本"],
  title: ["title", "reviewTitle", "review_title", "标题"],
  text: ["text", "content", "review", "comment", "body", "评论", "正文", "内容"],
  author: ["author", "user", "username", "作者", "用户"],
  authorUrl: ["authorUrl", "author_url", "作者链接"],
  createdAt: ["createdAt", "created_at", "date", "time", "日期", "时间"],
  sourceUrl: ["sourceUrl", "source_url", "url", "来源链接"]
};

function normalizeKey(value) {
  return String(value ?? "")
    .replace(/^\uFEFF/, "")
    .trim()
    .toLowerCase()
    .replace(/[\s_-]+/g, "");
}

const aliasLookup = new Map(
  Object.entries(aliases).flatMap(([field, names]) => names.map((name) => [normalizeKey(name), field]))
);

function validateImportInput({ fileName, content }) {
  if (!String(fileName ?? "").trim()) {
    throw new ApiError("INVALID_IMPORT_FILE", "请选择 JSON 或 CSV 文件。", { status: 400 });
  }
  const extension = path.extname(String(fileName)).toLowerCase();
  if (![".json", ".csv"].includes(extension)) {
    throw new ApiError("UNSUPPORTED_IMPORT_FORMAT", "只支持 JSON 或 CSV 文件。", { status: 400 });
  }
  if (typeof content !== "string" || !content.trim()) {
    throw new ApiError("EMPTY_IMPORT_FILE", "导入文件内容为空。", { status: 400 });
  }
  if (Buffer.byteLength(content, "utf8") > MAX_IMPORT_BYTES) {
    throw new ApiError("IMPORT_FILE_TOO_LARGE", "导入文件不能超过 2 MB。", { status: 413 });
  }
  return extension.slice(1);
}

function createDatasetId(content) {
  const digest = crypto.createHash("sha256").update(content, "utf8").digest("hex");
  return ((BigInt("0x" + digest.slice(0, 16)) % 900000000000000000n) + 100000000000000000n).toString();
}

function parseJson(content) {
  let value;
  try {
    value = JSON.parse(content.replace(/^\uFEFF/, ""));
  } catch {
    throw new ApiError("INVALID_IMPORT_JSON", "JSON 文件格式无效。", { status: 400 });
  }
  const records = Array.isArray(value) ? value : value && (value.reviews || value.data || value.records);
  if (!Array.isArray(records)) {
    throw new ApiError("INVALID_IMPORT_SCHEMA", "JSON 顶层应为评论数组，或包含 reviews 数组。", { status: 400 });
  }
  return records;
}

function parseCsv(content) {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  const text = content.replace(/^\uFEFF/, "");

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];
    if (char === '"') {
      if (quoted && next === '"') {
        cell += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
    } else if (char === "," && !quoted) {
      row.push(cell);
      cell = "";
    } else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && next === "\n") index += 1;
      row.push(cell);
      if (row.some((value) => value.trim())) rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }
  if (quoted) throw new ApiError("INVALID_IMPORT_CSV", "CSV 文件存在未闭合的引号。", { status: 400 });
  row.push(cell);
  if (row.some((value) => value.trim())) rows.push(row);
  if (rows.length < 2) throw new ApiError("INVALID_IMPORT_SCHEMA", "CSV 至少需要一行表头和一行评论记录。", { status: 400 });

  const headers = rows[0].map((header) => aliasLookup.get(normalizeKey(header)) || String(header).trim());
  return rows.slice(1).map((values) => Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""])));
}

function mapRecord(record, appId, format, fileName) {
  if (!record || typeof record !== "object" || Array.isArray(record)) return null;
  const mapped = {};
  for (const [key, value] of Object.entries(record)) {
    const field = aliasLookup.get(normalizeKey(key)) || key;
    mapped[field] = value;
  }
  return {
    ...mapped,
    appId: String(appId),
    sourceType: "file-" + format,
    sourceUrl: mapped.sourceUrl || fileName
  };
}

function importReviews({ fileName, content }) {
  const format = validateImportInput({ fileName, content });
  const records = format === "json" ? parseJson(content) : parseCsv(content);
  if (records.length > MAX_IMPORT_REVIEWS) {
    throw new ApiError("TOO_MANY_REVIEWS", "单次最多导入 500 条评论。", { status: 400 });
  }
  const appId = createDatasetId(content);
  const reviews = records.map((record) => mapRecord(record, appId, format, String(fileName))).filter(Boolean);
  if (!reviews.length) {
    throw new ApiError("EMPTY_IMPORT_DATA", "文件中没有可识别的评论记录。", { status: 400 });
  }
  return {
    appId: String(appId),
    reviews,
    import: {
      provider: "file-import",
      datasetId: appId,
      format,
      fileName: String(fileName),
      requestedCount: reviews.length,
      importedCount: reviews.length,
      warnings: []
    }
  };
}

module.exports = {
  MAX_IMPORT_REVIEWS,
  createDatasetId,
  importReviews,
  parseCsv,
  parseJson,
  validateImportInput
};
