"""Inline encoding, validation, projection and the per-span fallback (ADR-011)."""

from doctranslator_core.inline import (
    Keep,
    Obj,
    Text,
    Wrap,
    decode,
    encode,
    join_segmented,
    normalize_tag_whitespace,
    plain_text,
    project,
    protect_tag_like,
    segmented_pieces,
    span_texts,
    strip_paired_tags,
    validate,
)
from doctranslator_core.types import Language

BASE, BOLD, ITALIC = 0, 1, 2


def test_uniform_paragraph_has_no_tags() -> None:
    encoded = encode([Text("你好", BASE), Text("世界", BASE)])
    assert encoded.text == "你好世界"
    assert not encoded.has_tags


def test_dominant_style_is_untagged_and_others_are_paired_tags() -> None:
    encoded = encode([Text("请", BASE), Text("立即", BOLD), Text("提交季度报告。", BASE)])
    assert encoded.text == "请<g1>立即</g1>提交季度报告。"
    assert encoded.base_style == BASE


def test_dominant_style_can_be_the_formatted_one() -> None:
    encoded = encode([Text("全部加粗的一段文字", BOLD), Text("普通", BASE)])
    assert encoded.text == "全部加粗的一段文字<g1>普通</g1>"
    assert encoded.base_style == BOLD


def test_objects_keeps_and_wrappers() -> None:
    nodes = [
        Text("访问", BASE),
        Keep("https://example.com", BASE),
        Obj(7),
        Wrap(3, (Text("手册", BASE), Text("第一章", ITALIC))),
    ]
    encoded = encode(nodes)
    assert encoded.text == "访问<x1/><x2/><g1>手册<g2>第一章</g2></g1>"
    assert encoded.parents == {"x1": "", "x2": "", "g1": "", "g2": "g1"}


def test_identical_paragraphs_encode_identically() -> None:
    a = encode([Text("请", 5), Text("立即", 9), Text("提交", 5)])
    b = encode([Text("请", 1), Text("立即", 2), Text("提交", 1)])
    assert a.text == b.text


def test_whitespace_only_style_change_does_not_create_a_tag() -> None:
    encoded = encode([Text("Hello", BASE), Text(" ", BOLD), Text("world", BASE)])
    assert encoded.text == "Hello world"


def test_round_trip_decode_restores_styles_and_structure() -> None:
    nodes = [
        Text("Please submit the report ", BASE),
        Text("today", BOLD),
        Text(". See ", BASE),
        Keep("https://example.com", BASE),
        Wrap(4, (Text("handbook", BASE),)),
    ]
    encoded = encode(nodes)
    output = "请<g1>今天</g1>提交报告。参见<x1/><g2>手册</g2>"
    assert validate(encoded, output) is None
    assert decode(encoded, output) == [
        Text("请", BASE),
        Text("今天", BOLD),
        Text("提交报告。参见", BASE),
        Keep("https://example.com", BASE),
        Wrap(4, (Text("手册", BASE),)),
    ]


def test_moved_emphasis_is_valid() -> None:
    encoded = encode([Text("我们", BASE), Text("昨天", BOLD), Text("签署了合同。", BASE)])
    output = "We signed the contract <g1>yesterday</g1>."
    assert validate(encoded, output) is None


def test_validation_failures() -> None:
    encoded = encode([Text("a", BASE), Text("b", BOLD), Text("c", BASE), Text("d", ITALIC), Obj(1)])
    assert encoded.text == "a<g1>b</g1>c<g2>d</g2><x1/>"
    assert validate(encoded, "A<g1>B</g1>C<g2>D</g2>") == "tag_inventory"
    assert validate(encoded, "A<g1>B<g2></g1>D</g2><x1/>") == "tag_nesting"
    assert validate(encoded, "A<g1>B<g2>D</g2></g1><x1/>") == "tag_parent"
    assert validate(encoded, "A<g1> </g1>C<g2>D</g2><x1/>") == "empty_span"
    assert validate(encoded, "A<g1>B</g1><g1>B</g1><g2>D</g2><x1/>") == "tag_inventory"


def test_whitespace_inside_tags_moves_outside() -> None:
    assert normalize_tag_whitespace("<g1> sales</g1> grew") == " <g1>sales</g1> grew"
    assert normalize_tag_whitespace("the <g1>report </g1>is") == "the <g1>report</g1> is"


def test_edge_whitespace_matches_the_source() -> None:
    # SMALL-100 put a space inside the opening tag at the paragraph start (seen in native render)
    assert normalize_tag_whitespace("<g1> sales</g1> grew", "<g1>销售额</g1>增长") == (
        "<g1>sales</g1> grew"
    )
    assert normalize_tag_whitespace("<g1>x </g1>", "  <g1>甲</g1> ") == "  <g1>x</g1> "


def test_segmented_fallback_spaces_after_sentence_punctuation() -> None:
    nodes = [Text("请见", BASE), Text("内部网", BOLD), Text("站", BASE)]
    rebuilt = join_segmented(
        nodes, {"请见": "See", "内部网": "the internal network.", "站": "Stations"}, Language.EN
    )
    assert plain_text(rebuilt) == "See the internal network. Stations"


def test_projection_recovers_a_lost_tag() -> None:
    encoded = encode([Text("请", BASE), Text("立即", BOLD), Text("提交季度报告。", BASE)])
    assert strip_paired_tags(encoded.text) == "请立即提交季度报告。"
    assert span_texts(encoded) == {1: "立即"}
    projected = project(
        encoded, "Please submit the quarterly report immediately.", {1: "Immediately."}
    )
    assert projected == "Please submit the quarterly report <g1>immediately</g1>."


def test_projection_respects_nesting() -> None:
    encoded = encode(
        [Wrap(1, (Text("重要：请在", BASE), Text("三月一日", BOLD), Text("前完成。", BASE)))]
    )
    projected = project(
        encoded,
        "Important: complete it before March 1.",
        {1: "Important: complete it before March 1.", 2: "March 1"},
    )
    assert projected == "<g1>Important: complete it before <g2>March 1</g2></g1>."


def test_projection_refuses_ambiguous_or_missing_spans() -> None:
    encoded = encode([Text("红", BOLD), Text("和红", BASE), Text("色", BASE)])
    assert project(encoded, "red and red", {1: "red"}) is None
    assert project(encoded, "crimson and scarlet", {1: "red"}) is None


def test_projection_requires_standalone_tags_in_plain_output() -> None:
    encoded = encode([Text("访问", BASE), Obj(1), Text("网站", BOLD)])
    assert project(encoded, "Visit the website", {1: "website"}) is None
    assert project(encoded, "Visit <x1/> the website", {1: "website"}) == (
        "Visit <x1/> the <g1>website</g1>"
    )


def test_segmented_fallback_keeps_every_style() -> None:
    nodes = [Text("请", BASE), Text("立即", BOLD), Text("提交", BASE), Obj(2), Text("报告", ITALIC)]
    assert segmented_pieces(nodes) == ["请", "立即", "提交", "报告"]
    rebuilt = join_segmented(
        nodes,
        {"请": "Please", "立即": "immediately", "提交": "submit", "报告": "report"},
        Language.EN,
    )
    assert rebuilt == [
        Text("Please ", BASE),
        Text("immediately", BOLD),  # the joining space goes on the plain side, never bold
        Text(" submit", BASE),
        Obj(2),
        Text("report", ITALIC),
    ]
    assert plain_text(rebuilt) == "Please immediately submitreport"


def test_segmented_fallback_removes_spaces_between_cjk() -> None:
    nodes = [Text("Please ", BASE), Text("submit", BOLD), Text(" now", BASE)]
    rebuilt = join_segmented(
        nodes, {"Please ": "请 ", "submit": "提交", " now": " 现在"}, Language.ZH
    )
    assert plain_text(rebuilt) == "请提交现在"
    assert rebuilt[1] == Text("提交", BOLD)


def test_segmented_fallback_spaces_around_kept_text_for_latin_targets() -> None:
    nodes = [Text("访问", BASE), Keep("example.com", BASE), Text("了解", BOLD)]
    rebuilt = join_segmented(nodes, {"访问": "Visit", "了解": "learn"}, Language.EN)
    assert plain_text(rebuilt) == "Visit example.com learn"


def test_literal_tag_like_text_is_protected() -> None:
    nodes = protect_tag_like([Text("literal <g1> in text", BASE)])
    assert nodes == [Text("literal ", BASE), Keep("<g1>", BASE), Text(" in text", BASE)]
    encoded = encode(nodes)
    assert encoded.text == "literal <x1/> in text"
