from nlp.base import normalize_text


class TestNormalizeText:
    def test_handle_to_user(self) -> None:
        assert normalize_text("hey @Alice check this") == "hey @user check this"

    def test_multiple_handles(self) -> None:
        assert normalize_text("@bob and @carol") == "@user and @user"

    def test_does_not_rewrite_email_local_part(self) -> None:
        assert normalize_text("write me@site.com please") == "write me@site.com please"

    def test_https_url_to_http(self) -> None:
        assert normalize_text("see https://example.com/a now") == "see http now"

    def test_http_and_www_urls(self) -> None:
        assert normalize_text("http://x.com and www.y.com") == "http and http"

    def test_nbsp_and_repeated_whitespace(self) -> None:
        assert normalize_text("  foo\xa0\xa0bar\t baz  ") == "foo bar baz"

    def test_empty_and_whitespace_only(self) -> None:
        assert normalize_text("") == ""
        assert normalize_text("  \t \xa0 ") == ""

    def test_combined_social_noise(self) -> None:
        raw = "  @bob  see https://x.com/y \xa0 thanks "
        assert normalize_text(raw) == "@user see http thanks"
