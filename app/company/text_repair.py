import re


def decode_response_text(response) -> str:
    """根据响应字节选择更可靠的编码，减少官网中文乱码。"""
    content = getattr(response, "content", None)
    if isinstance(content, bytes | bytearray):
        best_text = ""
        best_score = -10**9
        for encoding in candidate_encodings(response):
            try:
                text = bytes(content).decode(encoding, errors="replace")
            except LookupError:
                continue
            text = repair_mojibake(text) or text
            score = text_quality_score(text)
            if score > 0 and not looks_mojibake(text):
                return text
            if score > best_score:
                best_text = text
                best_score = score
        if best_text:
            return best_text

    text = response.text
    repaired_text = repair_mojibake(text)
    return repaired_text or text


def candidate_encodings(response) -> list[str]:
    """按可信度排列候选编码，优先使用 requests 探测到的 apparent_encoding。"""
    candidates = [
        getattr(response, "apparent_encoding", None),
        getattr(response, "encoding", None),
        "utf-8",
        "gb18030",
        "gbk",
    ]
    result: list[str] = []
    for encoding in candidates:
        if not encoding:
            continue
        encoding = str(encoding).strip()
        if encoding and encoding.lower() not in {item.lower() for item in result}:
            result.append(encoding)
    return result


def text_quality_score(text: str) -> int:
    """给解码结果打分：中文越多越好，乱码特征越多越差。"""
    chinese_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    mojibake_count = sum(text.count(marker) for marker in scoring_mojibake_markers())
    return chinese_count * 2 - mojibake_count * 5


def repair_mojibake(text: str) -> str:
    """兜底修复已经被 Latin-1 或 GB18030 解错的 UTF-8 文本。"""
    if not looks_mojibake(text):
        return ""
    best_repaired = ""
    best_text = text
    best_score = text_quality_score(text)
    for source_encoding in ["latin1", "gb18030", "gbk"]:
        try:
            repaired = text.encode(source_encoding).decode("utf-8")
        except UnicodeError:
            repaired = repair_mojibake_by_chunks(text, source_encoding)
        score = text_quality_score(repaired)
        if score > best_score or (score == best_score and len(repaired) > len(best_text)):
            best_repaired = repaired
            best_text = repaired
            best_score = score
    return best_repaired


def looks_mojibake(text: str) -> bool:
    """判断文本是否存在常见的中文乱码特征。"""
    if not text:
        return False
    strong_count = sum(text.count(marker) for marker in strong_mojibake_markers())
    if strong_count:
        return True
    if any(marker in text for marker in ["Ã", "Â"]):
        return True
    latin_marker_count = sum(text.count(marker) for marker in latin_mojibake_markers())
    if latin_marker_count >= 6 and latin_marker_count / max(len(text), 1) >= 0.08:
        return True
    gb_latin_marker_count = sum(text.count(marker) for marker in gb18030_latin_mojibake_markers())
    if gb_latin_marker_count < 2:
        return False
    latin_letter_count = sum(1 for char in text if ("A" <= char <= "Z") or ("a" <= char <= "z"))
    cjk_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    return latin_letter_count > cjk_count * 2


def mojibake_markers() -> list[str]:
    """常见乱码标记，覆盖 Latin-1 误解码和 GB18030 误解码两类场景。"""
    return latin_mojibake_markers() + gb18030_latin_mojibake_markers() + strong_mojibake_markers()


def scoring_mojibake_markers() -> list[str]:
    """用于候选文本评分的乱码标记；不惩罚正常外文重音字母。"""
    return ["Ã", "Â"] + gb18030_latin_mojibake_markers() + strong_mojibake_markers()


def latin_mojibake_markers() -> list[str]:
    """拉丁误解码标记；正常英文/外文中也可能出现，需按数量和比例判断。"""
    return [
        "Ã",
        "Â",
        "é",
        "å",
        "ç",
        "è",
    ]


def gb18030_latin_mojibake_markers() -> list[str]:
    """西语等拉丁文本被 GB18030 误解码后常见的中文形似标记。"""
    return [
        "贸",
        "谩",
        "铆",
        "煤",
        "脕",
        "茅",
        "帽",
        "掳",
        "鈥",
        "麓",
    ]


def strong_mojibake_markers() -> list[str]:
    """强乱码标记，通常不会出现在正常英文证据中。"""
    return [
        "�",
        "\\x",
        "鍥",
        "绉",
        "妧",
        "锛",
        "鏈",
        "檺",
        "徃",
        "級",
        "瀹",
        "窘",
        "閲",
        "嘲",
        "嶄",
        "笟",
        "鎴",
        "愮",
        "珛",
        "浜",
        "骞",
        "涓",
        "撴",
        "敞",
        "荆",
        "妞",
        "瀛",
        "鐮",
        "斿",
        "彂",
        "攢",
        "鍞",
    ]


def compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def repair_compacted_text(text: str) -> str:
    """先压缩空白，再兜底修复可能已经形成的中文乱码。"""
    compacted = compact_text(text)
    return repair_mojibake(compacted) or compacted


def repair_mojibake_by_chunks(text: str, source_encoding: str) -> str:
    """长文本里可能混入坏字符，分段反解可恢复片段，避免坏字符破坏整段中文。"""
    repaired_parts: list[str] = []
    current: list[str] = []

    def flush_current():
        if not current:
            return
        chunk = "".join(current)
        current.clear()
        try:
            repaired_parts.append(chunk.encode(source_encoding).decode("utf-8"))
        except UnicodeError:
            repaired_parts.append(chunk.encode(source_encoding, errors="ignore").decode("utf-8", errors="ignore"))

    for char in text:
        try:
            char.encode(source_encoding)
        except UnicodeError:
            flush_current()
            continue
        current.append(char)
    flush_current()
    return "".join(repaired_parts)
