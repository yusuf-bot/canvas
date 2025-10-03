def extract_between(text: str) -> str | None:
    start_tag = "<<<LATEX_START>>>"
    end_tag = "<<<LATEX_END>>>"

    start_idx = text.find(start_tag)
    if start_idx == -1:
        return None

    end_idx = text.find(end_tag, start_idx)
    if end_idx == -1:
        return None

    # Slice between the tags, excluding the headers
    return text[start_idx + len(start_tag):end_idx].strip()

# Example
sample = "random text <<<LATEX_START>>>ljfkldjfljfdlkflj;<<<LATEX_END>>> more text"
print(extract_between(sample))
# ➝ 'x^2 + y^2 = 1'
