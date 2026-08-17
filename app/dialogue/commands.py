"""Voice commands recognized by the CLI/UI (Vietnamese)."""

from __future__ import annotations

from enum import Enum


class Command(str, Enum):
    REPEAT = "REPEAT"
    SLOWER = "SLOWER"
    NEXT_STEP = "NEXT_STEP"
    SOURCES = "SOURCES"
    HUMAN = "HUMAN"
    CONNECT = "CONNECT"
    END = "END"
    HELP = "HELP"
    NONE = "NONE"


_TRIGGERS: dict[Command, list[str]] = {
    Command.REPEAT: [
        "nói lại",
        "nghe lại",
        "lặp lại",
        "đọc lại",
        "repeat",
    ],
    Command.SLOWER: [
        "nói chậm",
        "chậm hơn",
        "chậm thôi",
        "chậm lại",
        "slower",
    ],
    Command.NEXT_STEP: [
        "bước tiếp theo",
        "tiếp theo",
        "làm gì tiếp",
        "sau đó làm gì",
        "next step",
    ],
    Command.SOURCES: [
        "nguồn ở đâu",
        "nguồn từ đâu",
        "thông tin từ đâu",
        "lấy đâu ra",
        "sources",
        "nguồn",
    ],
    Command.HUMAN: [
        "hỏi người thật",
        "người thật",
        "cán bộ",
        "nhân viên",
        "gặp người",
        "tư vấn viên",
        "human",
    ],
    Command.CONNECT: [
        "nối máy",
        "nối tới",
        "kết nối cơ quan",
        "kết nối tới",
        "gọi cơ quan",
        "gọi đến cơ quan",
        "đồng ý kết nối",
        "oke",
        "ok",
        "đồng ý",
        "connect",
    ],
    Command.END: [
        "kết thúc",
        "thoát",
        "tạm biệt",
        "hết",
        "dừng lại",
        "end",
        "stop",
    ],
    Command.HELP: [
        "trợ giúp",
        "giúp",
        "help",
        "hướng dẫn sử dụng",
    ],
}


def parse_command(text: str) -> Command:
    """Match a transcript fragment against known commands (prefix match)."""
    if not text:
        return Command.NONE
    lowered = " ".join(text.casefold().split())
    for cmd, triggers in _TRIGGERS.items():
        for trigger in triggers:
            if trigger.casefold() in lowered:
                return cmd
    return Command.NONE
