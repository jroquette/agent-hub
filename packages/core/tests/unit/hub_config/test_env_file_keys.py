from agent_hub.core.hub_config.env_file_keys import MAX_KEYS, dotenv_keys


def test_lists_names_in_order_when_lines_hold_values() -> None:
    content = (
        b"# a comment\nDATABASE_URL=postgres://db/app\n\n"
        b"export AWS_REGION=eu-west-1\nAPI_KEY = abc\n"
    )

    keys, truncated = dotenv_keys(content)

    assert keys == ("DATABASE_URL", "AWS_REGION", "API_KEY")
    assert truncated is False


def test_skips_inner_lines_when_a_quoted_value_spans_lines() -> None:
    content = b'PRIVATE_KEY="-----BEGIN KEY-----\nNOT_A_NAME=xyz\n-----END KEY-----"\nNEXT=1\n'

    assert dotenv_keys(content)[0] == ("PRIVATE_KEY", "NEXT")


def test_lists_each_name_once_when_lines_repeat_or_are_not_assignments() -> None:
    content = b"A=1\nA=2\njust text\n1BAD=x\n#C=3\n"

    assert dotenv_keys(content)[0] == ("A",)


def test_says_more_when_names_are_over_the_cap() -> None:
    content = "".join(f"K{index}=v\n" for index in range(MAX_KEYS + 5)).encode()

    keys, truncated = dotenv_keys(content)

    assert len(keys) == MAX_KEYS
    assert truncated is True
