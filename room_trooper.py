# DEPRECATED shim: kept to avoid breaking scripts that call the old name.
import warnings, cli


def main():
    warnings.warn(
        "room_trooper.py is deprecated. Use `python cli.py` moving forward.",
        UserWarning,
        stacklevel=1,
    )
    return cli.main()


if __name__ == "__main__":
    raise SystemExit(main())
