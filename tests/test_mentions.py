from app.bot.mentions import build_messages, mention_html, safe_name
from app.database.models import Member


def test_mention_uses_numeric_id_not_username():
    m = Member(user_id=123456789, first_name="Nassim", username="nassim_dz")
    assert mention_html(m) == '<a href="tg://user?id=123456789">Nassim</a>'


def test_user_without_username_or_first_name_still_mentionable():
    assert mention_html(Member(user_id=5, first_name="")) == '<a href="tg://user?id=5">Member</a>'
    assert "Doe" in mention_html(Member(user_id=6, first_name="", last_name="Doe"))


def test_html_is_escaped():
    m = Member(user_id=7, first_name='<script>&"x"')
    out = mention_html(m)
    assert "<script>" not in out and "&lt;script&gt;" in out


def test_invisible_and_control_characters_removed():
    assert safe_name(Member(user_id=1, first_name="A\x00B")) == "A B"
    assert "\u202e" not in safe_name(Member(user_id=1, first_name="A\u202eB"))


def test_arabic_and_french_names_survive():
    assert safe_name(Member(user_id=1, first_name="خولة")) == "خولة"
    assert safe_name(Member(user_id=2, first_name="Élodie")) == "Élodie"


def test_splitting_respects_count_and_length_limits():
    members = [Member(user_id=1_000_000_000 + i, first_name=f"User{i}") for i in range(103)]
    msgs = build_messages(members, "SIGL L3", per_message=20)
    assert len(msgs) == 6                       # 103 / 20 -> 6 messages
    assert msgs[0].startswith("📢 <b>SIGL L3</b> — 103 members")
    assert all(len(m) <= 4096 for m in msgs)
    total_links = sum(m.count("tg://user?id=") for m in msgs)
    assert total_links == 103                    # nobody lost or duplicated


def test_long_names_never_exceed_telegram_limit():
    members = [Member(user_id=2_000_000_000 + i, first_name="N" * 200) for i in range(50)]
    msgs = build_messages(members, "T" * 500, per_message=50)
    assert all(len(m) <= 4096 for m in msgs)
    assert sum(m.count("tg://user?id=") for m in msgs) == 50


def test_empty_group():
    assert len(build_messages([], "Empty")) == 1
