// Sentiment aggregates shared by the reporting views. Each is a SQL
// expression over the rows of one GROUP BY; use as ${sentiment.positive}.
//
// Shares are always counts divided by COUNT(*) of the same group — never
// an average of shares — so a chart that sums the counts and divides again
// gets the same number at any grain.

const positive = "COUNTIF(sentiment_label = 'pos')";
const neutral = "COUNTIF(sentiment_label = 'neu')";
const negative = "COUNTIF(sentiment_label = 'neg')";

const share = (count) => `SAFE_DIVIDE(${count}, COUNT(*))`;

// Positive minus negative, in [-1, 1]: one number per group that a line
// chart can carry.
const netSentiment = `SAFE_DIVIDE(${positive} - ${negative}, COUNT(*))`;

module.exports = {
  positive,
  neutral,
  negative,
  positiveShare: share(positive),
  negativeShare: share(negative),
  netSentiment,
};
