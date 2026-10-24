// The deduplicated events table: one row per classified record, written by
// the Dataflow pipeline (MERGE from events_landing). Terraform owns it
// (terraform/modules/bigquery); Dataform only reads it, through the
// reporting views.
declare({
  schema: dataform.projectConfig.vars.analytics_dataset,
  name: "events",
});
