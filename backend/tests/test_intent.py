"""Tests for intent classification + intent-routed prompt assembly."""
from app.services.intent import classify_intent
from app.services.llm import (
    _INTENT_SUFFIX_KEYS,
    _PROMPT_SUFFIX,
    _SUFFIX_SECTIONS,
    _suffix_for_intent,
    build_system_prompt,
)


class TestClassifyIntent:
    def test_summary_patterns(self):
        assert classify_intent("בפרוטוקול אסיפת חברים 4-16 - מה מסופר?") == "summary"
        assert classify_intent("תסכם לי את תקנון הפנסיה") == "summary"
        assert classify_intent("על מה דנו באסיפה מ-2024?") == "summary"
        assert classify_intent("אילו נושאים עלו בישיבה האחרונה של הועד?") == "summary"

    def test_meta_patterns(self):
        assert classify_intent("כמה פרוטוקולים יש במאגר?") == "meta"
        assert classify_intent("מה המסמך העדכני ביותר?") == "meta"
        assert classify_intent("אילו תקנונים קיימים אצלך?") == "meta"

    def test_rules_default(self):
        assert classify_intent("מה קורה אם חבר לא שילם דמי חבר?") == "rules"
        assert classify_intent("מי זכאי לשיוך דירה?") == "rules"
        assert classify_intent("") == "rules"

    def test_section_reference_forces_rules(self):
        # "מה מסופר בסעיף 4" asks for the rule, not a document overview.
        assert classify_intent("מה מסופר בסעיף 4 לתקנון?") == "rules"
        assert classify_intent("תסכם את סעיף 12") == "rules"


class TestSuffixAssembly:
    def test_all_expected_sections_present(self):
        for key in ("2.5", "3", "4", "4.5", "6", "7", "8", "9"):
            assert key in _SUFFIX_SECTIONS, f"section {key} missing from suffix split"

    def test_rules_is_byte_identical_to_full_suffix(self):
        # THE core safety property: default intent composes the exact
        # pre-routing prompt. If a new section is added to _PROMPT_SUFFIX
        # without updating _INTENT_SUFFIX_KEYS["rules"], this fails.
        assert _suffix_for_intent("rules") == _PROMPT_SUFFIX

    def test_unknown_intent_falls_back_to_rules(self):
        assert _suffix_for_intent("nonsense") == _PROMPT_SUFFIX

    def test_summary_keeps_45_drops_6_and_7(self):
        s = _suffix_for_intent("summary")
        assert "## 4.5" in s
        assert "שאלות סקירה" in s
        assert "## 6." not in s
        assert "## 7." not in s
        assert "## 3." in s  # no-invention stays everywhere

    def test_meta_is_slimmest(self):
        s = _suffix_for_intent("meta")
        assert "## 3." in s
        assert "## 4." in s
        assert "## 8." in s
        assert "## 9." in s
        assert "## 2.5" not in s
        assert "## 4.5" not in s
        assert len(s) < len(_suffix_for_intent("summary")) < len(_PROMPT_SUFFIX)

    def test_build_system_prompt_default_matches_pre_routing(self):
        base = build_system_prompt(tenant_name="קיבוץ בדיקה", tenant_context="הקשר")
        routed = build_system_prompt(
            tenant_name="קיבוץ בדיקה", tenant_context="הקשר", intent="rules"
        )
        assert base == routed
        assert base.endswith(_PROMPT_SUFFIX)

    def test_intent_keys_reference_real_sections(self):
        for intent, keys in _INTENT_SUFFIX_KEYS.items():
            for k in keys:
                assert k in _SUFFIX_SECTIONS, f"{intent} references missing section {k}"
