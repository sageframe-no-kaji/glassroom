"""Tests for src/downloader.py — pure helper functions.

The do_download_attachments() function requires a live Playwright browser
session and a real Google Classroom login, so it is not unit-tested here.
All pure helper functions are covered.
"""



from src.downloader import (
    _class_folder_slug,
    _export_url,
    _load_manifest,
    _make_pdf_filename,
    _previously_downloaded,
    _save_manifest,
    _slugify,
    _title_slug,
    _unique_filename,
    attachment_type,
)


# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_lowercase(self):
        assert _slugify("Hello World") == "hello-world"

    def test_special_chars_to_hyphens(self):
        assert _slugify("Math: 002") == "math-002"

    def test_collapse_consecutive_hyphens(self):
        assert _slugify("a--b---c") == "a-b-c"

    def test_strip_leading_trailing_hyphens(self):
        assert _slugify("  -hello-  ") == "hello"

    def test_numbers_preserved(self):
        assert _slugify("Week 3") == "week-3"


# ---------------------------------------------------------------------------
# _class_folder_slug
# ---------------------------------------------------------------------------


class TestClassFolderSlug:
    def test_subject_lastname_pattern(self):
        # "Science Heumann" → "heumann-science"
        assert _class_folder_slug("Science Heumann") == "heumann-science"

    def test_lastname_initial_pattern(self):
        # "Mathematics: 002 - Boren, J" → "boren-mathematics"
        assert _class_folder_slug("Mathematics: 002 - Boren, J") == "boren-mathematics"

    def test_slash_subject_pattern(self):
        # "Social Studies/History: 004 - Lessage, P" → "lessage-social-studies"
        assert _class_folder_slug("Social Studies/History: 004 - Lessage, P") == "lessage-social-studies"

    def test_ms_title_pattern(self):
        # "Barker ELA -Ms. Joella" → "barker-ela"
        assert _class_folder_slug("Barker ELA -Ms. Joella") == "barker-ela"

    def test_single_word_fallback(self):
        result = _class_folder_slug("Science")
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# _title_slug
# ---------------------------------------------------------------------------


class TestTitleSlug:
    def test_basic(self):
        assert _title_slug("Chapter 1 Review") == "chapter-1-review"

    def test_truncated_to_max_len(self):
        long_title = "a" * 100
        result = _title_slug(long_title, max_len=20)
        assert len(result) <= 20

    def test_no_trailing_hyphens_after_truncation(self):
        # Ensure no trailing hyphens
        result = _title_slug("word1 word2 word3 word4", max_len=10)
        assert not result.endswith("-")


# ---------------------------------------------------------------------------
# _make_pdf_filename
# ---------------------------------------------------------------------------


class TestMakePdfFilename:
    def test_with_date(self):
        name = _make_pdf_filename("2026-01-15", "Chapter 1 Review")
        assert name.startswith("2026-01-15_")
        assert name.endswith(".pdf")

    def test_without_date(self):
        name = _make_pdf_filename(None, "Assignment Title")
        assert name.startswith("undated_")
        assert name.endswith(".pdf")


# ---------------------------------------------------------------------------
# _unique_filename
# ---------------------------------------------------------------------------


class TestUniqueFilename:
    def test_no_conflict(self, tmp_path):
        result = _unique_filename(tmp_path, "report.pdf")
        assert result == "report.pdf"

    def test_conflict_appends_counter(self, tmp_path):
        (tmp_path / "report.pdf").touch()
        result = _unique_filename(tmp_path, "report.pdf")
        assert result == "report-2.pdf"

    def test_multiple_conflicts(self, tmp_path):
        (tmp_path / "report.pdf").touch()
        (tmp_path / "report-2.pdf").touch()
        result = _unique_filename(tmp_path, "report.pdf")
        assert result == "report-3.pdf"


# ---------------------------------------------------------------------------
# _export_url
# ---------------------------------------------------------------------------


class TestExportUrl:
    def test_google_doc(self):
        url = "https://docs.google.com/document/d/abc123/edit"
        result = _export_url(url)
        assert result is not None
        export_url, doc_type = result
        assert "abc123" in export_url
        assert "format=pdf" in export_url
        assert doc_type == "Google Doc"

    def test_google_slides(self):
        url = "https://docs.google.com/presentation/d/xyz789/edit"
        result = _export_url(url)
        assert result is not None
        export_url, doc_type = result
        assert "xyz789" in export_url
        assert doc_type == "Google Slides"

    def test_google_sheets(self):
        url = "https://docs.google.com/spreadsheets/d/sheet456/edit"
        result = _export_url(url)
        assert result is not None
        export_url, doc_type = result
        assert "sheet456" in export_url
        assert doc_type == "Google Sheets"

    def test_non_google_doc_returns_none(self):
        assert _export_url("https://example.com/file.pdf") is None

    def test_generic_google_url_returns_none(self):
        assert _export_url("https://classroom.google.com/c/abc") is None


# ---------------------------------------------------------------------------
# _load_manifest / _save_manifest
# ---------------------------------------------------------------------------


class TestManifest:
    def test_load_missing_returns_empty(self, tmp_path):
        result = _load_manifest(tmp_path)
        assert result == {}

    def test_save_and_reload(self, tmp_path):
        data = {"generated_at": "2026-01-01", "classes": {}}
        _save_manifest(tmp_path, data)
        loaded = _load_manifest(tmp_path)
        assert loaded == data

    def test_load_corrupt_returns_empty(self, tmp_path):
        (tmp_path / "manifest.json").write_text("not valid json")
        result = _load_manifest(tmp_path)
        assert result == {}

    def test_save_creates_directory(self, tmp_path):
        subdir = tmp_path / "new_dir"
        _save_manifest(subdir, {"classes": {}})
        assert (subdir / "manifest.json").exists()


# ---------------------------------------------------------------------------
# _previously_downloaded
# ---------------------------------------------------------------------------


class TestPreviouslyDownloaded:
    def _make_manifest(self, class_slug: str, filename: str, downloaded: bool) -> dict[str, object]:
        return {
            "classes": {
                class_slug: {
                    "files": [
                        {"filename": filename, "downloaded": downloaded}
                    ]
                }
            }
        }

    def test_returns_true_when_downloaded(self):
        manifest = self._make_manifest("math-smith", "2026-01-01_hw1.pdf", True)
        assert _previously_downloaded(manifest, "math-smith", "2026-01-01_hw1.pdf") is True

    def test_returns_false_when_not_downloaded(self):
        manifest = self._make_manifest("math-smith", "2026-01-01_hw1.pdf", False)
        assert _previously_downloaded(manifest, "math-smith", "2026-01-01_hw1.pdf") is False

    def test_returns_false_for_missing_class(self):
        manifest = self._make_manifest("math-smith", "hw1.pdf", True)
        assert _previously_downloaded(manifest, "science-jones", "hw1.pdf") is False

    def test_returns_false_for_missing_filename(self):
        manifest = self._make_manifest("math-smith", "hw1.pdf", True)
        assert _previously_downloaded(manifest, "math-smith", "hw2.pdf") is False

    def test_empty_manifest(self):
        assert _previously_downloaded({}, "math-smith", "hw1.pdf") is False


# ---------------------------------------------------------------------------
# attachment_type
# ---------------------------------------------------------------------------


class TestAttachmentType:
    def test_google_doc(self):
        assert attachment_type("https://docs.google.com/document/d/abc/edit") == "Doc"

    def test_google_slides(self):
        assert attachment_type("https://docs.google.com/presentation/d/xyz/edit") == "Slides"

    def test_google_sheets(self):
        assert attachment_type("https://docs.google.com/spreadsheets/d/sheet/edit") == "Sheet"

    def test_google_forms(self):
        assert attachment_type("https://docs.google.com/forms/d/form123/viewform") == "Form"

    def test_google_drive_file(self):
        assert attachment_type("https://drive.google.com/file/d/fileid/view") == "Drive"

    def test_youtube_full(self):
        assert attachment_type("https://www.youtube.com/watch?v=abc") == "Video"

    def test_youtu_be_short(self):
        assert attachment_type("https://youtu.be/abc123") == "Video"

    def test_external_link(self):
        assert attachment_type("https://example.com/some-resource") == "Link"

    def test_empty_string_returns_link(self):
        assert attachment_type("") == "Link"
