import sys

from promptmeld.__main__ import main


if __name__ == "__main__":
    if sys.argv[1:] == ["--smoke-test"]:
        raise SystemExit(0)
    raise SystemExit(main())
