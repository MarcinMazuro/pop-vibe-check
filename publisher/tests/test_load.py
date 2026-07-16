from publisher.load import build_merge_sql, landing_source_uri


class TestLandingSourceUri:
    def test_wildcard_covers_whole_bucket(self):
        assert landing_source_uri("co-raw-archive-dev") == (
            "gs://co-raw-archive-dev/*.jsonl.gz"
        )


class TestBuildMergeSql:
    def _sql(self) -> str:
        return build_merge_sql("proj", "ds", "raw_landing", "raw_staging")

    def test_tables_fully_qualified(self):
        sql = self._sql()
        assert "MERGE `proj.ds.raw_staging` AS t" in sql
        assert "FROM `proj.ds.raw_landing`" in sql

    def test_dedup_keeps_freshest_collected_at_per_id(self):
        sql = self._sql()
        assert "ROW_NUMBER() OVER (PARTITION BY id ORDER BY collected_at DESC)" in sql
        assert "WHERE rn = 1" in sql

    def test_matched_rows_only_updated_when_fresher(self):
        assert "WHEN MATCHED AND s.collected_at > t.collected_at THEN UPDATE" in (
            self._sql()
        )

    def test_unmatched_rows_inserted(self):
        assert "WHEN NOT MATCHED THEN" in self._sql()
        assert "INSERT ROW" in self._sql()

    def test_update_covers_every_field_except_id(self):
        sql = self._sql()
        for field in (
            "source",
            "parent_id",
            "created_utc",
            "collected_at",
            "author_hash",
            "text",
            "language",
            "score",
            "context_id",
            "event_tag",
        ):
            assert f"{field} = s.{field}" in sql
        assert "id = s.id," not in sql
