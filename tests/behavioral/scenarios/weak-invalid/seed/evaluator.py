def exact_reply_score(*, output, expected, input_data, metadata):
    del input_data, metadata
    return float(output.strip() == expected.strip())
