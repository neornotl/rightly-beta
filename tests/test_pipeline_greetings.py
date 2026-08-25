from app.pipeline import _is_social_greeting


def test_alo_variants_are_social_greetings():
    assert _is_social_greeting("alo")
    assert _is_social_greeting("A lô!")
    assert _is_social_greeting("alo alo")
    assert _is_social_greeting("xin chào")


def test_long_message_is_not_downgraded_to_greeting():
    assert not _is_social_greeting("alo, cho tôi hỏi thủ tục đăng ký kết hôn")
