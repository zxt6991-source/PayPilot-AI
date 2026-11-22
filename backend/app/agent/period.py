"""Resolve a requested rolling window, or ask before querying an unsupported range."""

import re

ROLLING = {
    "24h": r"(?:24|二十四|twenty[ -]four)[ -]?(?:h(?:ours?|rs?)?|小时)|(?:1|一|one)[ -]?(?:days?|d|天|日)|(?:past|trailing|a)\s+day",
    "7d": r"(?:7|七|seven)[ -]?(?:days?|d|天|日)|(?:1|一|one)[ -]?(?:weeks?|周|星期)|(?:past|trailing|a)\s+week",
    "30d": r"(?:30|三十|thirty)[ -]?(?:days?|d|天|日)",
}
SUPPORTED = {
    key: re.compile(r"(?<![a-z\d.零一二两三四五六七八九十百])(?:" + pattern + r")(?![a-z\d])", re.I)
    for key, pattern in ROLLING.items()
}
# Remove any supported spans before checking for other temporal constraints in the same question.
OTHER_TIME = re.compile(
    r"(?:\d+(?:\.\d+)?|[零一二两三四五六七八九十百半几数多]+)\s*个?\s*"
    r"(?:工作日|小时|天|日|周|星期|礼拜|月|季度|年|分钟|[ -]?(?:hours?|hrs?|days?|weeks?|months?|years?|[hdw])(?![a-z]))"
    r"|(?:今天|今日|昨日|昨天|前天|本周|这周|上周|上上周|本月|上月|上个月|本季|上季|今年|去年|月初至今)"
    r"|(?:最近|过去|近)(?:一段时间|这段时间|几天|一阵子)"
    r"|\b(?:today|yesterday|ytd|mtd|wtd|(?:this|last|past|trailing|previous|next)\s+(?:day|week|month|quarter|year|morning))\b"
    r"|\b(?:last|past|trailing|previous|next)\s+(?:[a-z-]+\s+){1,3}(?:hours?|days?|weeks?|months?|years?)\b"
    r"|\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}月\d{1,2}[日号]?"
    r"|\b(?:fortnight|last night)\b|近期|本星期|上星期|这几天"
    r"|\b(?:from|since|until|through|on)\s+(?:mon|tues?|wed(?:nes)?|thu(?:rs)?|fri|sat(?:ur)?|sun)day\b"
    r"|\b\d+[ -]+(?:business|working)\s+days?\b"
    r"|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|fourteen|twenty|thirty)[ -]+(?:hours?|days?|weeks?|months?|quarters?|years?)\b"
    r"|\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,4}\b",
    re.I,
)
NEGATED = re.compile(
    r"(?:排除|别看|不看|不是|不要|不用|except|excluding|not)\s*(?:过去|最近|近|the last)?\s*$", re.I
)


def period_request(question):
    text = question.lower()
    # Calendar ranges and explicit bounded intervals cannot be represented by a rolling window.
    if re.search(r"(?:上|下)一(?:周|天)|\d+\s*[-~～至到]\s*\d+\s*(?:天|日|小时|days?|hours?)", text):
        return "clarify"
    periods = set()
    remaining = list(text)
    for period, pattern in SUPPORTED.items():
        for match in pattern.finditer(text):
            before, after = text[: match.start()], text[match.end() :]
            if (
                NEGATED.search(before)
                or re.search(
                    r"\b(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)[ -]$", before
                )
                or re.match(r"\s*(?:之前|以前|之后|前|后|\bago\b)", after)
            ):
                return "clarify"
            periods.add(period)
            remaining[match.start() : match.end()] = " " * len(match[0])
    if len(periods) > 1 or OTHER_TIME.search("".join(remaining)):
        return "clarify"
    return next(iter(periods), None)
