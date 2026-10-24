// Settings shared by every reporting view.

// The labels Terraform puts on everything else, with the owner of these
// objects swapped in.
const labels = {
  project: "pop-vibe-check",
  env: "dev",
  owner: "team-198019-198265-198223",
  managed_by: "dataform",
};

// The two analytics columns no reporting view may expose: author_hash is
// pseudonymous personal data under GDPR, text is what individuals wrote.
// Author counts are computed inside the aggregates instead.
const personalColumns = ["author_hash", "text"];
const personalColumnList = personalColumns.map((c) => `'${c}'`).join(", ");

// The reporting dataset this compilation writes to: co_reporting_dev on a
// deploy, co_reporting_dev_<workspace> from a web IDE workspace.
function dataset() {
  const { defaultDatabase, defaultSchema, schemaSuffix } = dataform.projectConfig;
  const schema = schemaSuffix ? `${defaultSchema}_${schemaSuffix}` : defaultSchema;
  return `${defaultDatabase}.${schema}`;
}

module.exports = { labels, personalColumns, personalColumnList, dataset };
