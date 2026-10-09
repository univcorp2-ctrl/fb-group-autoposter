// Regression: Facebook feed metadata can precede a property's body by >48 characters.
// Run: node tests/test_extension_permalink.cjs
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const extensionSource = process.env.FB_EXTENSION_SOURCE ||
  path.join(process.env.LOCALAPPDATA, "FBGroupAutoposter", "app", "extension", "content.js");
const src = fs.readFileSync(extensionSource, "utf8");
const start = src.indexOf("  function normalizeText(value)");
const stop = src.indexOf("  async function verifyPublished(", start);
assert(start >= 0 && stop > start, "matcher functions present");
const code = src.slice(start, stop);
const article = (text, links) => ({
  textContent: text,
  querySelectorAll: () => links.map(href => ({ href }))
});
const makeMatcher = (...articles) =>
  new Function("document", code + "\nreturn findPermalinkForBody;")({
    querySelectorAll: () => articles
  });

const body = "【物件情報】川崎市・広い空間・駅から徒歩圏内・新築戸建です。詳細はお問い合わせください。";
const permalink = "https://www.facebook.com/groups/123/posts/456/";
const longMetadata = "テストユーザーがグループに投稿しました。お知らせ等の説明文が非常に長く続いています。";
assert(longMetadata.length > 48, "metadata is long enough");
assert.equal(makeMatcher(article(longMetadata + body, [permalink]))(body), permalink);
assert.equal(makeMatcher(article("別の物件についての投稿", [permalink]))(body), null);
assert.equal(makeMatcher(article(longMetadata + body, ["https://www.facebook.com/groups/123/members"])) (body), null);
console.log("PASS: metadata prefix, irrelevant body, and non-permalink guard");
