"""An env file's grammar (AC-350.46, docs/design/scenarios.md § Credentials).

Values are synthetic and built from parts at run time, so no secret shape is committed.
"""

import pytest

from agent_hub.core.scenarios.env_file import (
    MAX_ENV_FILE_VARIABLES,
    EnvFileError,
    parse_env_file,
)

SECRET = "x-" + "secret" + "-y"


def test_parses_dotenv_when_env_file_well_formed() -> None:
    content = "\n".join(
        [
            "# the staging database",
            "",
            f"DEMO_DB_URL={SECRET}",
            "export DEMO_REGION=eu-west-1",
            "  DEMO_SINGLE = 'a $HOME b'  ",
            'DEMO_DOUBLE="one \\"two\\" $DEMO_REGION"',
            "DEMO_EMPTY=",
            "DEMO_COMMENTED=plain # a note",
            "DEMO_HASH=a#b",
            "DEMO_CRLF=windows\r",
        ]
    ).encode()

    assert parse_env_file(content) == {
        "DEMO_DB_URL": SECRET,
        "DEMO_REGION": "eu-west-1",
        "DEMO_SINGLE": "a $HOME b",
        "DEMO_DOUBLE": 'one "two" $DEMO_REGION',
        "DEMO_EMPTY": "",
        "DEMO_COMMENTED": "plain",
        "DEMO_HASH": "a#b",
        "DEMO_CRLF": "windows",
    }


@pytest.mark.parametrize(
    ("line", "number"),
    [
        (f"no equals sign {SECRET}", 2),
        (f"1BAD={SECRET}", 2),
        (f"DEMO_OPEN='{SECRET}", 2),
        (f'DEMO_OPEN="{SECRET}', 2),
        (f"DEMO_TRAIL='{SECRET}' junk", 2),
        (f"DEMO_NUL={SECRET}\0", 2),
        (f"export {SECRET}", 2),
    ],
)
def test_refuses_line_when_env_file_grammar_broken(line: str, number: int) -> None:
    content = f"DEMO_OK=fine\n{line}\nDEMO_LATER={SECRET}\n".encode()

    with pytest.raises(EnvFileError) as raised:
        parse_env_file(content)

    assert raised.value.reason == f"not a dotenv file (line {number})"
    assert SECRET not in str(raised.value)


def test_refuses_line_when_env_file_grammar_not_utf8() -> None:
    with pytest.raises(EnvFileError) as raised:
        parse_env_file(b"DEMO_OK=fine\nDEMO_BAD=\xff\xfe\n")

    assert raised.value.reason == "not a dotenv file (line 2)"


def test_refuses_when_env_file_over_variable_cap() -> None:
    at_cap = "".join(f"DEMO_{index}=v\n" for index in range(MAX_ENV_FILE_VARIABLES))

    assert len(parse_env_file(at_cap.encode())) == 200
    with pytest.raises(EnvFileError) as raised:
        parse_env_file((at_cap + "DEMO_ONE_MORE=v\n").encode())

    assert raised.value.reason == "too large (more than 200 variables)"
